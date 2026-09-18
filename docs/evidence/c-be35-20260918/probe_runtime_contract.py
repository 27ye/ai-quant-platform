"""Offline C contract diagnostics against an explicit candidate source tree.

Uses synthetic bars, a fake HTTP response and fresh SQLite databases.
Exit 0 means diagnostics reproduced; inspect contract_met, not just exit code.
"""
import argparse, json, sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,default=root/'source')
parser.add_argument('--output',type=Path,default=root/'runtime-contract-probe.json')
args=parser.parse_args()
sys.path.insert(0,str(args.source.resolve()))
import pandas as pd
from sqlalchemy import create_engine, BIGINT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from backend.app.db.migrations import apply_migrations
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.market_data_service import MarketDataRepository, MarketDataService
from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.core.errors import DatabaseOperationError

@compiles(BIGINT, 'sqlite')
def sqlite_integer_pk(type_, compiler, **kw):
 return 'INTEGER'  # Same SQLite primary-key adaptation as tests/conftest.py.

CODE='600519'; OLD='eastmoney-synthetic'; NEW=AKShareStockProvider.tencent_kline_url
def bar(day,close=100):
 return DailyKlineSchema(stock_code=CODE,trade_date=date.fromisoformat(day),open=close,high=close+1,low=close-1,close=close,volume=1000,amount=None,turnover_rate=None,change_pct=None)
class Stock:
 provider_name='synthetic';last_kline_source=NEW
 def __init__(self,rows):self.rows=rows;self.calls=0
 def get_daily_kline(self,*args,**kwargs):self.calls+=1;return self.rows
def seed(repo,rows):
 repo.upsert_daily(rows)
 repo.upsert_daily_sync(stock_code=CODE,mode='live',source=OLD,row_count=len(rows),first_trade_date=rows[0].trade_date,last_trade_date=rows[-1].trade_date,at=datetime.now(timezone.utc).replace(tzinfo=None))
def engine():
 value=create_engine('sqlite://');apply_migrations(value);return value
results={}
e=engine()
with Session(e) as s:
 repo=MarketDataRepository(s)
 seed(repo,[bar('2025-01-06'),bar('2025-01-07')])
 stock=Stock([bar('2025-01-08',101),bar('2025-01-09',101)])
 svc=MarketDataService(stock_service=stock,repository=repo)
 svc.sync_daily(CODE,date(2025,1,8),date(2025,1,9),min_rows=2)
 read=MarketDataService(stock_service=Stock([]),repository=repo)
 rows=read.query_daily(CODE,date(2025,1,6),date(2025,1,9),min_rows=2,trading_days=lambda s,e:4)
 provenance=read.get_query_provenance(CODE)
 assert [r.close for r in rows]==[100,100,101,101] and provenance['provider']==NEW
 results['mixed_cache']={'contract_met':False,'returned_closes':[r.close for r in rows],'known_row_origins':[OLD,OLD,NEW,NEW],'reported_provenance':provenance,'cache_provider_calls':read._stock.calls}
e.dispose()
e=engine()
with Session(e) as s:
 repo=MarketDataRepository(s);seed(repo,[bar('2025-01-06')])
 class FailMetadata(MarketDataRepository):
  def upsert_daily_sync(self,**kwargs):raise DatabaseOperationError()
 svc=MarketDataService(stock_service=Stock([bar('2025-01-06',101)]),repository=FailMetadata(s))
 try:svc.sync_daily(CODE,date(2025,1,6),date(2025,1,6),min_rows=1)
 except DatabaseOperationError:pass
 else:raise AssertionError('failure injection missed')
with Session(e) as s:
 repo=MarketDataRepository(s)
 close=repo.list_daily(CODE)[0].close;src=repo.get_daily_sync(CODE).source
 assert close==101 and src==OLD
 results['metadata_write_failure']={'contract_met':False,'fresh_session_close':close,'fresh_session_source':src,'expected_previous_close':100,'successful_data_not_rolled_back':True}
e.dispose()
e=engine()
with Session(e) as s:
 repo=MarketDataRepository(s);seed(repo,[bar('2026-09-17')])
 stock=Stock([bar('2026-09-17'),bar('2026-09-18',100.5)])
 svc=MarketDataService(stock_service=stock,repository=repo)
 rows=svc.query_daily(CODE,date(2026,9,17),date(2026,9,18),min_rows=1,trading_days=lambda s,e:2)
 assert stock.calls==1 and rows[-1].trade_date==date(2026,9,18)
 results['intraday_complete_bar_policy']={'contract_met':False,'scenario':'synthetic 2026-09-18 intraday response; no real market claim','cache_through':'2026-09-17','refetch_calls':stock.calls,'returned_dates':[r.trade_date.isoformat() for r in rows],'unfinished_today_filtered':False}
e.dispose()
class Response:
 status_code=200
 def json(self):return {'data':{'sh600519':{'qfqday':[['2025-01-06','100','100','101','99','1000'],['2025-01-07','101','101','102','100','1100']]}}}
p=AKShareStockProvider()
with patch('requests.get',return_value=Response()):
 whole=p._daily_kline_from_tencent(CODE,date(2025,1,6),date(2025,1,7),ConnectionError('synthetic'))
 clipped=p._daily_kline_from_tencent(CODE,date(2025,1,7),date(2025,1,7),ConnectionError('synthetic'))
 assert pd.isna(whole.iloc[0]['change_pct']) and whole.iloc[1]['change_pct']==0.01 and clipped.iloc[0]['change_pct']==0.01
 results['change_pct_unit_and_crop']={'contract_met':True,'first_without_previous':None,'100_to_101':float(whole.iloc[1]['change_pct']),'cropped_first':float(clipped.iloc[0]['change_pct'])}
out={'sha':'be35e5febe1acebce32ea9eb495affd6bd730875','mode':'offline synthetic + SQLite; network mocked','diagnostic_execution':'completed','results':results,'all_contracts_met':False}
args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
