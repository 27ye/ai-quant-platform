"""C independent fixed-package HTTP/SQLite integration audit; no live data/LLM."""
import json
import sys
from pathlib import Path
from datetime import date
import tempfile
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from sqlalchemy import create_engine, BIGINT, select, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.api.v1.dependencies import get_backtest_repository, get_backtest_service
from backend.app.db.migrations import apply_migrations
from backend.app.models.backtest_result import BacktestResult
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.quant_service import QuantService
from backend.app.services.backtest_service import BacktestService, BacktestRepository
from backend.app.services.c_quant_entry import load_c_windowed_entry
from backend.app.quant import run_backtest_request
from scripts.validate_v3_macd import canonical, SETS

@compiles(BIGINT, 'sqlite')
def sqlite_bigint(element, compiler, **kw):
    return 'INTEGER'

root=Path.cwd()
rows={}
for code in ('600519','000001','300750'):
    raw=json.loads(next((root/'docs/evidence/c-delivery-20260917').glob(code+'*normalized*.json')).read_text(encoding='utf-8'))
    rows[code]=[DailyKlineSchema(**r) for r in raw]
class Market:
    calls=0
    def query_daily(self,code,start_date=None,end_date=None,**kw):
        self.calls+=1
        return [r for r in rows[code] if (start_date is None or r.trade_date>=start_date) and (end_date is None or r.trade_date<=end_date)]
market=Market()
report={'b_sha':'11a0c03ecca56fe667b845a976afd1cdde9197b7','c_code_sha':'6a84901c82256b7d48dfab3ebee3208633e5058c',
    'scope':'isolated B21 + C18; real HTTP routes/schema/service/C/repository; fixed Tencent qfq sample source; temporary SQLite, NOT MySQL/live Provider/LLM',
    'matrix':[], 'date_matrix':[], 'parameter_matrix':[]}
with tempfile.TemporaryDirectory(prefix='c-b21-audit-') as folder:
    url='sqlite:///'+str(Path(folder)/'audit.sqlite3')
    engine=create_engine(url,connect_args={'check_same_thread':False})
    apply_migrations(engine)
    missing_support=False
    def repository_dep():
        with Session(engine) as session:
            yield BacktestRepository(session)
    def service_dep():
        with Session(engine) as session:
            entry=load_c_windowed_entry()
            if missing_support: entry=replace(entry,supports_strategy=False)
            yield BacktestService(quant_service=QuantService(stock_service=object(),market_data_source=market),
                market_data_source=market,repository=BacktestRepository(session),today=lambda:date(2026,8,31),c_entry_loader=lambda:entry)
    app=create_app()
    app.dependency_overrides[get_backtest_repository]=repository_dep
    app.dependency_overrides[get_backtest_service]=service_dep
    base={'stock_code':'600519','strategy':'macd','start_date':'2025-07-04','end_date':'2026-08-31'}
    def count():
        with Session(engine) as session:return session.scalar(select(func.count()).select_from(BacktestResult))
    with TestClient(app) as client:
        for code in rows:
            frame=QuantService.rows_to_frame(rows[code])
            for label,params in SETS.items():
                direct=run_backtest_request(frame,strategy='macd',parameters=params,start_date=base['start_date'],end_date=base['end_date'])
                response=client.post('/api/v1/backtests',json={**base,'stock_code':code,'parameters':params})
                assert response.status_code==200,response.text
                posted=response.json()['data']
                # Compare every C field in POST before B's own extra envelope fields.
                post_equal=all(canonical(posted[k])==canonical(v) for k,v in direct.items())
                engine.dispose();engine=create_engine(url,connect_args={'check_same_thread':False})
                old_calls=market.calls
                with patch('backend.app.services.c_quant_entry.run_backtest_request',create=True,side_effect=AssertionError('GET recomputed')), \
                     patch('backend.app.quant.run_backtest_request',side_effect=AssertionError('GET recomputed')), \
                     patch.object(market,'query_daily',side_effect=AssertionError('GET fetched')):
                    response=client.get('/api/v1/backtests/'+str(posted['backtest_id']),params={'include_c_result':'true','include_input_snapshot':'true'})
                assert response.status_code==200,response.text
                got=response.json()['data']
                assert canonical(got['c_result'])==canonical(direct)
                assert got['c_result_exact'] is True and market.calls==old_calls
                report['matrix'].append({'stock_code':code,'parameters':label,'direct_post_equal':post_equal,
                    'direct_exact_get_equal':True,'new_engine_session':True,'history_effective_equals_post':canonical(got['effective_parameters'])==canonical(posted['effective_parameters']),
                    'post_parameter_keys':sorted(posted['effective_parameters']), 'get_parameter_keys':sorted(got['effective_parameters']),
                    'warmup_rows':direct['warmup']['used_rows'],'curve_points':len(direct['equity_curve'])})
        for label,updates in [('omit_both',{'start_date':'OMIT','end_date':'OMIT'}),('omit_start',{'start_date':'OMIT'}),('omit_end',{'end_date':'OMIT'}),('null_start',{'start_date':None}),('null_end',{'end_date':None})]:
            payload={**base,**updates};payload={k:v for k,v in payload.items() if v!='OMIT'}
            calls=market.calls;n=count()
            response=client.post('/api/v1/backtests',json=payload)
            report['date_matrix'].append({'case':label,'status':response.status_code,'code':response.json()['code'],
                'fetch_calls':market.calls-calls,'saved_records':count()-n,
                'resolved_start':(response.json().get('data') or {}).get('requested_start_date'),
                'resolved_end':(response.json().get('data') or {}).get('requested_end_date')})
        for label,patch_body in [('null_strategy',{'strategy':None}),('null_params',{'parameters':None}),('mixed_ma',{'parameters':{'ma_short_period':5}}),('period_bool',{'parameters':{'macd_fast_period':True}}),('period_range',{'parameters':{'macd_signal_period':121}}),('period_order',{'parameters':{'macd_fast_period':30}})]:
            calls=market.calls;n=count();response=client.post('/api/v1/backtests',json={**base,**patch_body})
            report['parameter_matrix'].append({'case':label,'status':response.status_code,'code':response.json()['code'],'fetch_calls':market.calls-calls,'saved_records':count()-n})
        missing_support=True
        calls=market.calls;n=count();response=client.post('/api/v1/backtests',json=base)
        report['missing_c_support']={'status':response.status_code,'code':response.json()['code'],'fetch_calls':market.calls-calls,'saved_records':count()-n}
    engine.dispose()
report['findings']=[]
if any(r['status']!=400 or r['code']!=40001 or r['fetch_calls'] or r['saved_records'] for r in report['date_matrix']):
    report['findings'].append('MACD missing/null dates are auto-filled before C validation, despite explicit-window contract.')
if any(not r['history_effective_equals_post'] for r in report['matrix']):
    report['findings'].append('MACD GET effective_parameters contains execution metadata (12 keys), unlike POST six actual configurable parameters. C exact envelope itself remains intact.')
report['status']='changes_required' if report['findings'] else 'passed'
Path('../b21-c-http-result.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
print(json.dumps({'groups':len(report['matrix']),'all_post_exact':all(r['direct_post_equal'] for r in report['matrix']),
    'history_parameters_equal':sum(r['history_effective_equals_post'] for r in report['matrix']),
    'sample_keys':report['matrix'][0],'dates':report['date_matrix'],'parameter_cases':report['parameter_matrix'],'missing_support':report['missing_c_support']},ensure_ascii=False,indent=2))
sys.exit(1 if report['findings'] else 0)
