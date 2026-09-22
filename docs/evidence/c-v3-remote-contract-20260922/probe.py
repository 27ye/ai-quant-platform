"""Read-only repository/API contract probe in the isolated B+C checkout."""
import json
from pathlib import Path
from datetime import date
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, BIGINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from backend.app.main import create_app
from backend.app.api.v1.dependencies import get_backtest_service
from backend.app.db.migrations import apply_migrations
from backend.app.services.backtest_service import BacktestRepository
from scripts.validate_v3_macd import canonical, numeric_example

# Match the repository test fixture: SQLite autoincrement needs INTEGER PK.
# This affects only temporary SQLite DDL, not the B model or any MySQL schema.
@compiles(BIGINT, 'sqlite')
def sqlite_bigint(element, compiler, **kw):
    return 'INTEGER'

result = {
    'b_sha': 'fa91f4ca7477cc28db4df4021e32e40a42870fe6',
    'c_code_sha': '6a84901c82256b7d48dfab3ebee3208633e5058c',
    'c_published_sha': 'a79155e23e63ce1d8f01c56e41bdedc0c3a07c68',
    'scope': 'B PR19 exact files + C PR18 quant overlay, SQLite and TestClient only; not deployed server or MySQL',
    'repository_roundtrips': [], 'http_current_status': [],
}
package = Path('docs/evidence/c-v3-macd-20260922')
manifest = json.loads((package/'manifest.json').read_text(encoding='utf-8'))
with tempfile.TemporaryDirectory(prefix='c-v3-contract-') as temp:
    url = 'sqlite:///' + str(Path(temp)/'probe.sqlite3')
    engine = create_engine(url)
    assert apply_migrations(engine) == 9
    for filename in manifest['result_files']:
        expected = json.loads((package/filename).read_text(encoding='utf-8'))
        params = expected['effective_parameters']
        if filename == 'ma_default.json':
            params = {key:params[key] for key in ('ma_short_period','ma_long_period','initial_cash','transaction_cost','slippage')}
        with Session(engine) as session:
            record_id = BacktestRepository(session).save(
                stock_code=expected['stock_code'], result=expected,
                semantics_version=expected['semantics_version'], effective_parameters=params,
                warmup_start_date=date.fromisoformat(expected['warmup']['start_date']),
                data_meta={'current_position':expected['current_position']},
                input_snapshot=expected['input_snapshot']['rows'], c_result=expected,
            )
        engine.dispose()
        engine = create_engine(url)
        with patch('backend.app.quant.run_backtest_request', side_effect=AssertionError('GET recomputed')), \
             patch('backend.app.quant.pipeline.analyze_quant_dataframe', side_effect=AssertionError('GET recomputed')):
            with Session(engine) as session:
                actual = BacktestRepository(session).get(record_id, include_c_result=True, include_input_snapshot=True)
        assert actual['c_result_exact'] is True
        assert canonical(actual['c_result']) == canonical(expected)
        assert canonical(actual['effective_parameters']) == canonical(params)
        assert actual['c_algorithm_version'] == expected['algorithm_version']
        assert actual['c_data_hash'] == expected['data_hash']
        assert actual['c_warmup'] == expected['warmup']
        for key in ('equity_curve','benchmark_curve','drawdown_curve','trades'):
            assert canonical(actual[key]) == canonical(expected[key])
        assert numeric_example(actual['c_result']) == numeric_example(expected)
        result['repository_roundtrips'].append({'file':filename,'exact_c_result':True,'parameters_and_flat_projections':True,'new_engine_and_session':True})
    engine.dispose()

class StubService:
    calls = 0
    def run(self, **kwargs):
        self.calls += 1
        raise AssertionError('unexpected invocation in unsupported strategy audit')

stub = StubService()
app = create_app()
app.dependency_overrides[get_backtest_service] = lambda: stub
with TestClient(app) as client:
    for strategy in ('macd','ma_cross'):
        response = client.post('/api/v1/backtests', json={
            'stock_code':'600519','start_date':'2025-07-04','end_date':'2026-08-31',
            'strategy':strategy,'parameters':{},
        })
        result['http_current_status'].append({'strategy':strategy, 'http_status':response.status_code, 'business_code':response.json().get('code')})
        assert response.status_code == 400 and response.json()['code'] == 40001
assert stub.calls == 0
result['conclusion'] = 'C output preserves exact repository storage under B v9; explicit strategy HTTP wiring remains blocked until B F5 implementation.'
Path('../remote-contract-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
