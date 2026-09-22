"""C UI audit only: fixed sample, real backtest HTTP, isolated SQLite."""
import sys,json
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path.cwd()))
from sqlalchemy import create_engine,BIGINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from backend.app.main import create_app
from backend.app.api.v1.dependencies import get_backtest_repository,get_backtest_service
from backend.app.db.migrations import apply_migrations
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.quant_service import QuantService
from backend.app.services.backtest_service import BacktestService,BacktestRepository
from backend.app.services.c_quant_entry import load_c_windowed_entry
import uvicorn
folder=Path(__file__).parent/'ui-audit-runtime'
folder.mkdir(exist_ok=True)
@compiles(BIGINT,'sqlite')
def bigint(element,compiler,**kw):return 'INTEGER'
rows={}
for code in ('600519','000001','300750'):
    raw=json.loads(next((Path.cwd()/'docs/evidence/c-delivery-20260917').glob(code+'*normalized*.json')).read_text(encoding='utf-8'))
    rows[code]=[DailyKlineSchema(**r) for r in raw]
class Market:
    calls=0
    def query_daily(self,code,start_date=None,end_date=None,**kw):
        self.calls+=1
        return [r for r in rows[code] if (start_date is None or r.trade_date>=start_date) and (end_date is None or r.trade_date<=end_date)]
market=Market()
engine=create_engine('sqlite:///'+str(folder/'audit.sqlite3'),connect_args={'check_same_thread':False})
apply_migrations(engine)
def repo_dep():
    with Session(engine) as session:yield BacktestRepository(session)
def service_dep():
    with Session(engine) as session:
        yield BacktestService(quant_service=QuantService(stock_service=object(),market_data_source=market),market_data_source=market,repository=BacktestRepository(session),today=lambda:date(2026,8,31),c_entry_loader=load_c_windowed_entry)
app=create_app()
app.dependency_overrides[get_backtest_repository]=repo_dep
app.dependency_overrides[get_backtest_service]=service_dep
@app.middleware('http')
async def audit(request,call_next):
    payload=await request.json() if request.method=='POST' else None
    before=market.calls
    response=await call_next(request)
    with (folder/'requests.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'method':request.method,'path':request.url.path,'body':payload,'status':response.status_code,'market_calls':market.calls-before},ensure_ascii=False)+'\n')
    return response
uvicorn.run(app,host='127.0.0.1',port=8124)
