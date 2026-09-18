"""C source-switch contract probe; synthetic sensitivity is not market evidence."""
import argparse
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
source=args.source.resolve();sys.path.insert(0,str(source))
import pandas as pd
from backend.app.quant.scoring import _score_volume
from backend.app.quant.config import QuantConfig
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.quant.windowed_backtest import run_backtest_request

rows=json.loads((source/'docs/evidence/c-delivery-20260917/600519_qfq_normalized_20241201_20260916.json').read_text(encoding='utf-8'))
frame=pd.DataFrame(rows);filled=frame.copy()
filled['amount']=123456.;filled['turnover_rate']=0.0123
pipeline_equal=analyze_quant_dataframe(frame)==analyze_quant_dataframe(filled)
a=run_backtest_request(frame,start_date='2025-07-04',end_date='2026-08-31',parameters={})
b=run_backtest_request(filled,start_date='2025-07-04',end_date='2026-08-31',parameters={})
equal=all(a[k]==b[k] for k in a if k not in ('input_snapshot','data_hash'))
test=pd.DataFrame({'close':[100.]*20,'volume':[1000.]*19+[2000.],'change_pct':[0.]*20})
test.loc[19,'change_pct']=0.000001;positive=_score_volume(test,QuantConfig())[0]
test.loc[19,'change_pct']=-0.000001;negative=_score_volume(test,QuantConfig())[0]
assert pipeline_equal and equal and a['data_hash']!=b['data_hash']
assert positive==20 and negative==0
result={'source_SHA':'85b7617149fbff67189e52f6527c9921ff09d388',
 'optional_amount_turnover_financial_backtest_equal':equal,
 'optional_amount_turnover_pipeline_equal':pipeline_equal,
 'optional_amount_turnover_input_hash_changed':a['data_hash']!=b['data_hash'],
 'synthetic_volume_component_positive_change_1e_minus_6':positive,
 'synthetic_volume_component_negative_change_1e_minus_6':negative,
 'scope':'Fixed 600519 input with only optional values varied; synthetic component-level sign sensitivity. No new live source or complete new-provider acceptance tested.'}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
