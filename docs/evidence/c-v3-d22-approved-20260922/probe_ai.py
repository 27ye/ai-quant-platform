"""C independent D22 numerical/context audit. Run from reviewed checkout."""
import hashlib
import json
import sys
import tempfile
import subprocess
from pathlib import Path
from datetime import date
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path.cwd()))
import pandas as pd
from sqlalchemy import BIGINT, create_engine, select, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.api.v1 import dependencies
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.models.backtest_result import BacktestResult
from backend.app.quant import run_backtest_request
from backend.app.schemas.ai import SavedBacktestMetricsContext, BacktestParametersContext
from backend.app.services.backtest_service import BacktestRepository
from backend.app.services.backtest_interpretation import BacktestInterpretationContextProvider

@compiles(BIGINT, 'sqlite')
def sqlite_bigint(element, compiler, **kw):
    return 'INTEGER'

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def normalized(value):
    if isinstance(value, float):
        return 0.0 if value == 0 else float(format(value, '.15g'))
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value

def forbidden(*args, **kwargs):
    raise AssertionError('custom/history called forbidden external dependency or quant')

class LLM:
    model_name = 'c-independent-fixture-not-real-llm'
    def __init__(self):
        self.calls = []
    async def complete_json(self, messages):
        self.calls.append(messages)
        return json.dumps(dict(trend='neutral', summary='Saved context.', technical_analysis='MA.',
            quant_analysis='Saved results.', news_analysis='None.', advantages=['Reproducible'],
            risks=['Historical'], conclusion='Research only.'))

root = Path.cwd()
sets = {'default': {}, '10_30': {'ma_short_period': 10, 'ma_long_period': 30},
    '20_60_cost': {'ma_short_period': 20, 'ma_long_period': 60, 'initial_cash': 200000,
                   'transaction_cost': .002, 'slippage': .001}}
report = {'d_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'scope': 'D22 unmodified checkout; actual MA C calculation, HTTP, repository, new SQLite engines. Fixture LLM. No MySQL/live provider/real LLM/browser.',
    'matrix': [], 'corruption_probes': [], 'source_files_sha256': {}}
if '--with-c-overlay' in sys.argv:
    report['c_code_sha'] = '6a84901c82256b7d48dfab3ebee3208633e5058c'
    report['scope'] = report['scope'].replace('D22 unmodified checkout', 'Rebased D22 (includes merged B19/B21) plus C18 quant overlay; no A23')
with tempfile.TemporaryDirectory(prefix='c-d22-review-') as folder:
    url = 'sqlite:///' + str(Path(folder) / 'audit.sqlite3')
    engine = create_engine(url, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    app = create_app()
    llm = LLM()
    def session_dep():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db] = session_dep
    app.dependency_overrides[dependencies.get_llm_client] = lambda: llm
    def save(result):
        with Session(engine) as db:
            return BacktestRepository(db).save(stock_code=result['stock_code'], result=result,
                semantics_version='v2_windowed', effective_parameters=result['effective_parameters'],
                warmup_start_date=date.fromisoformat(result['warmup']['start_date']), data_meta={},
                strategy_version=result['algorithm_version'], input_snapshot=result['input_snapshot']['rows'], c_result=result)
    with ExitStack() as stack:
        for name in ('get_data_provider', 'get_trading_calendar_provider', 'build_standard_ai_context'):
            stack.enter_context(patch.object(dependencies, name, forbidden))
        client = stack.enter_context(TestClient(app, raise_server_exceptions=False))
        for code in ('600519', '000001', '300750'):
            file = next((root/'docs/evidence/c-delivery-20260917').glob(code+'*normalized*.json'))
            report['source_files_sha256'][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
            frame = pd.DataFrame(json.loads(file.read_text(encoding='utf-8')))
            for label, params in sets.items():
                direct = run_backtest_request(frame, parameters=params, start_date='2025-07-04', end_date='2026-08-31')
                backtest_id = save(direct)
                with Session(engine) as db:
                    raw = BacktestInterpretationContextProvider(db).get_context(code, backtest_id).model_dump(mode='json')
                    assert canonical(raw['metrics']) == canonical({k: direct[k] for k in SavedBacktestMetricsContext.model_fields})
                    assert canonical(raw['effective_parameters']) == canonical({k: direct['effective_parameters'][k] for k in BacktestParametersContext.model_fields})
                    for k in ('warmup', 'initial_equity', 'execution_assumptions', 'data_hash'):
                        assert canonical(raw[k]) == canonical(direct[k])
                with patch('backend.app.quant.run_backtest_request', forbidden), patch('backend.app.quant.windowed_backtest.run_backtest_request', forbidden):
                    response = client.post('/api/v1/ai/analyze', json={'stock_code': code, 'backtest_id': backtest_id})
                assert response.status_code == 200, response.text
                posted = response.json()['data']
                context = posted['context_snapshot']
                assert canonical(context) == canonical(normalized(raw))
                prompt = json.loads(llm.calls[-1][1]['content'].split('analysis_context=', 1)[1])
                assert canonical(prompt) == canonical(context)
                digest = hashlib.sha256(canonical(context).encode()).hexdigest()
                assert digest == posted['context_hash'] and digest != direct['data_hash']
                engine.dispose()
                engine = create_engine(url, connect_args={'check_same_thread': False})
                app.dependency_overrides[dependencies.get_llm_client] = forbidden
                with patch('backend.app.quant.run_backtest_request', forbidden), patch('backend.app.quant.windowed_backtest.run_backtest_request', forbidden):
                    response = client.get('/api/v1/ai/reports/' + str(posted['report_id']))
                assert response.status_code == 200 and canonical(response.json()['data']) == canonical(posted)
                app.dependency_overrides[dependencies.get_llm_client] = lambda: llm
                with Session(engine) as db:
                    assert canonical(json.loads(db.get(BacktestResult, backtest_id).c_result_text)) == canonical(direct)
                    assert canonical(db.get(AIAnalysis, posted['report_id']).context_snapshot) == canonical(context)
                report['matrix'].append({'stock_code': code, 'parameters': label, 'raw_numeric_mapping_exact': True,
                    'normalized_prompt_post_saved_get_equal': True, 'independent_context_hash': digest,
                    'c_input_hash': direct['data_hash'], 'new_engine_session': True, 'curve_points': len(direct['equity_curve'])})
        # All mutations leave C input rows and their input hash intact; these are
        # inconsistent saved results, not an expectation that data_hash hashes results.
        for field, replacement in (('total_return', .99), ('max_drawdown', -.5), ('trade_count', 999), ('initial_cash', 0.0)):
            backtest_id = save(direct)
            with Session(engine) as db:
                row = db.get(BacktestResult, backtest_id)
                value = json.loads(row.c_result_text)
                original = value[field]
                value[field] = replacement
                row.c_result_text = canonical(value)
                db.commit()
                before_rows = db.scalar(select(func.count()).select_from(AIAnalysis))
            before_calls = len(llm.calls)
            response = client.post('/api/v1/ai/analyze', json={'stock_code': direct['stock_code'], 'backtest_id': backtest_id})
            with Session(engine) as db:
                added = db.scalar(select(func.count()).select_from(AIAnalysis)) - before_rows
                try:
                    BacktestInterpretationContextProvider(db).get_context(direct['stock_code'], backtest_id)
                except Exception as exc:
                    exception_type = type(exc).__name__
                else:
                    exception_type = None
            try:
                response_body = response.json()
            except ValueError:
                response_body = {'non_json_body': response.text}
            report['corruption_probes'].append({'field': field, 'original': original, 'replacement': replacement,
                'http_status': response.status_code, 'code': response_body.get('code'),
                'response_body': response_body, 'provider_exception_type': exception_type,
                'llm_calls': len(llm.calls)-before_calls, 'reports_saved': added,
                'expected': '500/50002, zero LLM calls and zero saved reports',
                'initial_cash': direct['initial_cash'], 'final_equity': direct['final_equity'], 'order_count': direct['order_count']})
        if '--with-c-overlay' in sys.argv:
            macd = json.loads((root/'docs/evidence/c-v3-macd-20260922/600519_default.json').read_text(encoding='utf-8'))
            backtest_id = save(macd)
            before_calls = len(llm.calls)
            response = client.post('/api/v1/ai/analyze', json={'stock_code': '600519', 'backtest_id': backtest_id})
            assert (response.status_code, response.json()['code']) == (422, 40007)
            assert len(llm.calls) == before_calls
            report['macd_out_of_f4_scope'] = {'http_status': 422, 'code': 40007, 'llm_calls': 0}
    engine.dispose()
assert all(p['http_status']==500 and p['code']==50002 and p['llm_calls']==0 and p['reports_saved']==0 for p in report['corruption_probes'])
report['status'] = 'passed'
Path(sys.argv[1]).write_bytes((json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
print(json.dumps({'matrix_passed': len(report['matrix']), 'corruption_probes': report['corruption_probes']}, ensure_ascii=False))
