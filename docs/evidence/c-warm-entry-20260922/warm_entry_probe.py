"""C diagnostic: execute exact warm CLI main with synthetic calendar/provider and SQLite.

Usage: python warm_entry_probe.py --source D_CHECKOUT --git-repo FETCHED_REPO --output result.json
No live services or existing databases are used; B's script is evaluated in memory.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
p.add_argument('--git-repo', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
os.environ.update(MYSQL_HOST='127.0.0.1', MYSQL_PORT='1', MYSQL_USER='unused', MYSQL_PASSWORD='', LLM_API_KEY='')
sys.path.insert(0, str(a.source.resolve()))
import pandas as pd
from sqlalchemy import BIGINT, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from backend.app.db.migrations import apply_migrations
from backend.app.data.trading_calendar import TradingCalendarProvider
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.stock_service import StockService
from backend.app.services.market_data_service import MarketDataRepository

@compiles(BIGINT, 'sqlite')
def sqlite_pk(t, compiler, **kw):
    return 'INTEGER'

D = 'b506618e904b8b0edb09b5a06d0110c9392f493a'
B = 'a89c2ea5c67eb8a1b64f1ac195e2ef80d4390a1a'
def git(*args):
    return subprocess.check_output(['git', '-C', str(a.git_repo), *args])

dates = [d.date() for d in pd.bdate_range(end='2026-09-22', periods=100)]
cap = date(2026, 9, 21)
rows = [DailyKlineSchema(stock_code='600519', trade_date=d, open=100, high=101, low=99, close=100, volume=1000) for d in dates]

class Provider:
    last_kline_source = 'C-synthetic'
    def __init__(self):
        self.calls = []
    def get_daily_kline(self, code, start_date, end_date, adjust='qfq'):
        self.calls.append([str(start_date), str(end_date)])
        return pd.DataFrame([r.model_dump() for r in rows if start_date <= r.trade_date <= end_date])

results = {}
for name, revision, unknown, dirty in [
    ('D_original_reproduces_intraday_write', D, False, False),
    ('B_patch_cold_cache_caps_at_completed_day', B, False, False),
    ('B_patch_unknown_completed_day_rejects', B, True, False),
    ('B_patch_old_dirty_tail_is_replaced', B, False, True),
]:
    raw = git('show', revision + ':scripts/warm_market_data.py')
    namespace = {'__file__': str(a.source / 'scripts/warm_market_data.py'), '__name__': 'c_warm_probe'}
    exec(compile(raw.decode('utf-8-sig'), 'warm_market_data.py', 'exec'), namespace)
    engine = create_engine('sqlite://')
    apply_migrations(engine)
    if dirty:
        with Session(engine) as s:
            MarketDataRepository(s).replace_daily_snapshot([r for r in rows if r.trade_date != cap], source='C-old-synthetic', at=datetime(2026, 9, 21))
    provider = Provider()
    calendar = TradingCalendarProvider(trade_dates=dates)
    calendar.last_completed_trade_date = lambda: None if unknown else cap
    namespace.update(engine=engine, SessionLocal=lambda: Session(engine),
        TradingCalendarProvider=lambda: calendar, StockService=lambda: StockService(provider),
        parse_args=lambda: SimpleNamespace(stock_codes=['600519'], start_date=dates[0], end_date=dates[-1], rounds=1, interval=60))
    output = io.StringIO()
    with patch('time.sleep'), contextlib.redirect_stdout(output):
        exit_code = namespace['main']()
    with Session(engine) as s:
        stored = MarketDataRepository(s).list_daily('600519')
        stored_dates = [r.trade_date for r in stored]
        sync = MarketDataRepository(s).get_daily_sync('600519')
        source = getattr(sync, 'source', None)
    if revision == D:
        passed = exit_code == 0 and stored_dates == dates
    elif unknown:
        passed = exit_code == 1 and not provider.calls and not stored
    else:
        passed = exit_code == 0 and stored_dates == dates[:-1] and source == 'C-synthetic' and all(date.fromisoformat(c[1]) <= cap for c in provider.calls)
    results[name] = {'expected_observation_confirmed': passed, 'script_revision': revision,
        'script_sha256': hashlib.sha256(raw).hexdigest(), 'exit_code': exit_code,
        'stored_rows': len(stored), 'last_stored_date': str(stored_dates[-1]) if stored else None,
        'provider_calls': provider.calls, 'source': source, 'stdout': output.getvalue()}
    engine.dispose()

trees = {path: {ref: git('rev-parse', ref + ':' + path).decode().strip() for ref in [
    'bcbd559acb67d3435fe7a840f34ad73bbe35bbad', D]} for path in ['backend', 'frontend', 'scripts', 'tests', 'docs/evidence/c-delivery-20260917']}
report = {'D_head': D, 'B_script_commit': B, 'executed_core_sha': subprocess.check_output(['git', '-C', str(a.source), 'rev-parse', 'HEAD']).decode().strip(),
    'scope': 'exact CLI main + real StockService/MarketDataService + SQLite; synthetic Provider/calendar. B script + D core is a local diagnostic combination, not an integrated SHA.',
    'existing_databases_modified': False, 'tree_audit': trees,
    'production_and_fixed_package_identical': all(len(set(v.values())) == 1 for v in trees.values()),
    'D_changes_since_tested_core': git('diff', '--name-status', 'bcbd559acb67d3435fe7a840f34ad73bbe35bbad', D).decode(),
    'results': results, 'all_expected_observations_confirmed': all(v['expected_observation_confirmed'] for v in results.values())}
a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['all_expected_observations_confirmed'] else 1)
