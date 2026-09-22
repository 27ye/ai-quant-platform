"""ASGI/MySQL history check after isolated synthetic fixture setup."""
import asyncio,importlib.util,json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parent;source=root/'source'
os.environ.update(MYSQL_HOST='127.0.0.1',MYSQL_PORT='1',MYSQL_USER='unused',MYSQL_PASSWORD='',LLM_API_KEY='',LLM_BASE_URL='',LLM_MODEL='')
sys.path.insert(0,str(source))
spec=importlib.util.spec_from_file_location('local_config',root.parent/'v2-c-final15315-adaptation-20260916/mysql_local_acceptance.py')
config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
import httpx
from backend.app.main import app
from backend.app.db.session import get_db
from backend.app.api.v1.dependencies import get_ai_analysis_service,get_llm_client,get_data_provider,get_analysis_context_provider
from backend.app.core.config import get_settings
from backend.app.models.ai_analysis import AIAnalysis
report=json.loads((root/'mysql-final/report.json').read_text(encoding='utf-8'))
assert report['status']=='passed' and report['database'].startswith('ai_quant_cbcbd_')
engine=create_engine(config.connection_url(report['database']))
with Session(engine) as session:
    fixture=AIAnalysis(stock_code='000001',quant_score=50,trend='neutral',summary='C synthetic legacy fixture',technical_analysis='synthetic technical',quant_analysis='synthetic quant',news_analysis='synthetic news',advantages=['synthetic advantage'],risks=['synthetic risk'],conclusion='synthetic conclusion',model_name='synthetic-no-call')
    session.add(fixture);session.commit();fixture_id=fixture.id
def db_dependency():
    with Session(engine) as session:yield session
calls=[]
def forbidden():calls.append('generation_dependency');raise AssertionError('history constructed generation dependency')
async def run():
    assert not get_settings().llm_api_key and not get_settings().llm_base_url and not get_settings().llm_model
    app.dependency_overrides[get_db]=db_dependency
    for dependency in [get_ai_analysis_service,get_llm_client,get_data_provider,get_analysis_context_provider]:app.dependency_overrides[dependency]=forbidden
    with engine.connect() as c:before=[tuple(x) for x in c.execute(text('SELECT * FROM ai_analysis ORDER BY id'))]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://isolated.local') as client:
        listing=await client.get('/api/v1/ai/reports?stock_code=000001');detail=await client.get('/api/v1/ai/reports/'+str(fixture_id));missing=await client.get('/api/v1/ai/reports/999999')
        assert listing.status_code==200 and detail.status_code==200 and missing.status_code==404
        assert missing.json()['code']==40006 and detail.json()['data']['snapshot_status']=='legacy_missing'
        assert not calls
        # Only construction of a context placeholder is allowed; no market I/O.
        for dependency in [get_ai_analysis_service,get_llm_client,get_data_provider,get_analysis_context_provider]:app.dependency_overrides.pop(dependency)
        app.dependency_overrides[get_analysis_context_provider]=lambda:object()
        generated=await client.post('/api/v1/ai/analyze',json={'stock_code':'600519'})
        assert generated.json()['code']==50005,(generated.status_code,generated.text)
    engine.dispose()
    with engine.connect() as c:after=[tuple(x) for x in c.execute(text('SELECT * FROM ai_analysis ORDER BY id'))]
    assert before==after
    result={'sha':'bcbd559acb67d3435fe7a840f34ad73bbe35bbad','status':'passed','mode':'actual ASGI routes and real MySQL 8.0.31; separately seeded complete synthetic legacy report in current isolated test database','LLM_configuration':'empty','history_list_http':listing.status_code,'history_detail_http':detail.status_code,'missing_http':missing.status_code,'missing_code':missing.json()['code'],'legacy_snapshot_status':detail.json()['data']['snapshot_status'],'forbidden_generation_dependencies_called':calls,'generate_missing_config_code':generated.json()['code'],'generate_http':generated.status_code,'all_AI_rows_unchanged_after_reconnect':True,'real_LLM_called':False,'not_verified':'real LLM generation, browser, current live Provider, two newly generated real reports','harness_note':'Initial sparse migration sentinel lacked required report body fields; used a separate complete synthetic legacy fixture for the API contract, leaving original sentinel unchanged.'}
    (root/'history-dependency-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
try:asyncio.run(run())
finally:app.dependency_overrides.clear();engine.dispose()
