"""C independent diagnostics: synthetic Provider; SQLite or isolated real MySQL.

Exit 0 means all diagnostic scenarios completed, NOT all contracts passed.
Use --source exact_checkout --output result.json [--mysql].
No existing database is modified. No live market or real LLM claim.
"""
import argparse, importlib.util, json, os, sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--mysql',action='store_true')
args=parser.parse_args()
os.environ.update(MYSQL_HOST='127.0.0.1',MYSQL_PORT='1',MYSQL_USER='unused',MYSQL_PASSWORD='',LLM_API_KEY='')
sys.path.insert(0,str(args.source.resolve()))
import pandas as pd
from sqlalchemy import create_engine, BIGINT, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from backend.app.db.migrations import apply_migrations
from backend.app.core.errors import DatabaseOperationError
from backend.app.data.providers.base import StockDataProviderError
from backend.app.data.trading_calendar import TradingCalendarProvider
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.stock_service import StockService
from backend.app.services.market_data_service import MarketDataRepository, MarketDataService

@compiles(BIGINT,'sqlite')
def sqlite_pk(type_,compiler,**kw):return 'INTEGER'

if args.mysql:
    config_path=Path(__file__).resolve().parent.parent/'v2-c-final15315-adaptation-20260916/mysql_local_acceptance.py'
    spec=importlib.util.spec_from_file_location('local_config',config_path)
    config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
    db='ai_quant_cruntime119_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    admin=create_engine(config.connection_url())
    with admin.begin() as c:
        version=c.execute(text('SELECT VERSION()')).scalar_one()
        c.execute(text('CREATE DATABASE `'+db+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    admin.dispose();url=config.connection_url(db)
else:url='sqlite://';version='SQLite'
engine=create_engine(url);apply_migrations(engine)
OLD='eastmoney-synthetic';NEW='tencent-synthetic'
def bar(code,day,close=100):
    return DailyKlineSchema(stock_code=code,trade_date=date.fromisoformat(day),open=close,high=close+1,low=close-1,close=close,volume=1000,amount=None,turnover_rate=None,change_pct=None)
def seed(repo,rows,source=OLD):
    repo.replace_daily_snapshot(rows,source=source,at=datetime(2026,1,1))
class Provider:
    """Honors requested date range; exercised through the real StockService."""
    last_kline_source=NEW
    def __init__(self,rows,source=NEW):self.rows=rows;self.last_kline_source=source;self.calls=[]
    def get_daily_kline(self,code,start_date,end_date,adjust='qfq'):
        self.calls.append([str(start_date),str(end_date)])
        return pd.DataFrame([r.model_dump() for r in self.rows if start_date<=r.trade_date<=end_date])
def count(s,e):return (e-s).days+1 # Scenarios below use consecutive actual weekdays.
results={}

# Both source directions and a same-source qfq rebase must replace the prefix.
for i,(old,new) in enumerate([(OLD,NEW),(NEW,OLD),(NEW,NEW)]):
    code=f'60000{i}'
    with Session(engine) as s:
        repo=MarketDataRepository(s);seed(repo,[bar(code,'2025-01-06'),bar(code,'2025-01-07')],old)
        p=Provider([bar(code,f'2025-01-0{n}',101) for n in range(6,10)],new)
        svc=MarketDataService(StockService(p),repo,trading_days=count,completed_through=lambda:date(2025,1,9))
        svc.query_daily(code,date(2025,1,8),date(2025,1,9),min_rows=2)
    with Session(engine) as s:
        repo=MarketDataRepository(s);rows=repo.list_daily(code);state=repo.get_daily_sync(code)
        read=MarketDataService(StockService(Provider([])),repo,trading_days=count)
        cached=read.query_daily(code,date(2025,1,6),date(2025,1,9),min_rows=2)
        results[f'whole_window_{i}']={'contract_met':len(rows)==4 and all(r.close==101 for r in rows) and state.source==new and read.get_query_provenance(code)['provider']==new,'old_source':old,'new_source':new,'calls':p.calls,'closes':[r.close for r in cached]}

# Fail metadata SQL after DELETE/INSERT. Recreate engine before independent readback.
code='600010'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2025-01-06')]);before=asdict(repo.get_daily_sync(code))
    p=Provider([bar(code,'2025-01-06',101)])
    def fail_metadata(conn,cursor,statement,params,context,many):
        if statement.lstrip().upper().startswith('UPDATE STOCK_DAILY_SYNC') and 'last_success_at' in statement:
            raise SQLAlchemyError('C controlled success-metadata SQL failure')
    event.listen(engine,'before_cursor_execute',fail_metadata)
    try:
        MarketDataService(StockService(p),repo).sync_daily(code,date(2025,1,6),date(2025,1,6),min_rows=1)
        raise AssertionError('failure injection not reached')
    except DatabaseOperationError:pass
    finally:event.remove(engine,'before_cursor_execute',fail_metadata)
if args.mysql:engine.dispose();engine=create_engine(url)
with Session(engine) as s:
    repo=MarketDataRepository(s);after=asdict(repo.get_daily_sync(code));rows=repo.list_daily(code)
    stable=['source','mode','row_count','first_trade_date','last_trade_date','last_success_at']
    results['atomic_metadata_failure']={'contract_met':len(rows)==1 and rows[0].close==100 and all(before[k]==after[k] for k in stable),'recreated_engine':args.mysql,'close':rows[0].close,'successful_metadata_unchanged':all(before[k]==after[k] for k in stable),'failure_recorded':bool(after['last_error'])}

code='600011'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2026-09-16'),bar(code,'2026-09-17')])
    p=Provider([])
    rows=MarketDataService(StockService(p),repo,count,lambda:date(2026,9,17)).query_daily(code,date(2026,9,16),date(2026,9,18),min_rows=2)
    results['intraday_complete_cache']={'contract_met':not p.calls and rows[-1].trade_date==date(2026,9,17),'provider_calls':p.calls}

code='600012'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2026-09-16')])
    p=Provider([bar(code,'2026-09-16'),bar(code,'2026-09-17'),bar(code,'2026-09-18',100.5)])
    rows=MarketDataService(StockService(p),repo,count,lambda:date(2026,9,17)).query_daily(code,date(2026,9,16),date(2026,9,18),min_rows=2)
    results['intraday_missing_completed_day']={'contract_met':bool(p.calls) and rows[-1].trade_date==date(2026,9,17),'provider_calls':p.calls}

# Legacy cache contains an unfinished today plus a hole at yesterday.
code='600013'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2026-09-16'),bar(code,'2026-09-18',100.5)])
    p=Provider([bar(code,'2026-09-16',101),bar(code,'2026-09-17',101),bar(code,'2026-09-18',101.5)])
    rows=MarketDataService(StockService(p),repo,count,lambda:date(2026,9,17)).query_daily(code,date(2026,9,16),date(2026,9,18),min_rows=2)
    results['legacy_unfinished_tail']={'contract_met':all(r.trade_date<=date(2026,9,17) for r in rows),'provider_calls':p.calls,'returned_dates':[str(r.trade_date) for r in rows],'completed_through':'2026-09-17'}

# Calendar can know today while not covering an older cached prefix.
code='600014'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2025-01-06'),bar(code,'2025-01-07'),bar(code,'2025-01-08')])
    calendar=TradingCalendarProvider(trade_dates=[date(2025,1,n) for n in range(7,11)])
    assert calendar.last_completed_trade_date(datetime(2025,1,9,11,tzinfo=timezone.utc))==date(2025,1,9)
    assert calendar.count_between(date(2025,1,6),date(2025,1,9)) is None
    p=Provider([bar(code,'2025-01-08',101),bar(code,'2025-01-09',101)])
    rejected=False
    try:MarketDataService(StockService(p),repo,calendar.count_between,lambda:date(2025,1,9)).query_daily(code,date(2025,1,8),date(2025,1,9),min_rows=2)
    except StockDataProviderError:rejected=True
with Session(engine) as s:
    repo=MarketDataRepository(s);rows=repo.list_daily(code)
    preserved=len(rows)==3 and all(r.close==100 for r in rows)
    results['unknown_union_calendar']={'contract_met':rejected and preserved,'rejected':rejected,'old_snapshot_preserved':preserved,'provider_calls':p.calls,'remaining_dates':[str(r.trade_date) for r in rows]}

# A known missing completed day must fail and retain the old snapshot.
code='600015'
with Session(engine) as s:
    repo=MarketDataRepository(s);seed(repo,[bar(code,'2026-09-16')])
    p=Provider([bar(code,'2026-09-16')]);rejected=False
    try:MarketDataService(StockService(p),repo,count,lambda:date(2026,9,17)).query_daily(code,date(2026,9,16),date(2026,9,17),min_rows=1)
    except StockDataProviderError:rejected=True
    results['missing_completed_upstream_rejected']={'contract_met':rejected and repo.list_daily(code)[0].close==100,'rejected':rejected}

calendar=TradingCalendarProvider(trade_dates=[date(2026,9,n) for n in [16,17,18,21,22]])
observed=[]
for day,hour,expected in [(18,9,17),(18,10,18),(19,12,18),(21,9,18),(21,10,21)]:
    actual=calendar.last_completed_trade_date(datetime(2026,9,day,hour,tzinfo=timezone.utc))
    observed.append({'utc':f'2026-09-{day}T{hour}:00Z','completed':str(actual),'ok':actual==date(2026,9,expected)})
results['shanghai_1800_weekend_boundary']={'contract_met':all(x['ok'] for x in observed),'cases':observed}
engine.dispose()
out={'sha':'119a10c36c4b497ddfa0a3bb31666a6e6b803038','database_version':version,'mode':'synthetic Provider through real StockService and MarketDataService; no live data','existing_databases_modified':False,'diagnostics_completed':True,'results':results,'all_contracts_met':all(x['contract_met'] for x in results.values())}
args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
