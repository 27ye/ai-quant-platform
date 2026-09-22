import sys,json,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from scripts.validate_v3_macd import replay
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
report={'scope':'A23 af5e172 untouched UI + D22 fedeb09 with C quant 6a84901 overlay; fixed Tencent qfq package; actual HTTP and isolated SQLite. Other UI APIs mocked. Not final integration/MySQL/live provider/LLM.','cases':[]}
expected={2:['-17.47%','-15.82%','-26.83%','-1.02','21.43%',14,28],3:['-18.09%','-16.38%','-20.96%','-1.07','22.73%',22,44]}
for id in (2,3):
    with urllib.request.urlopen(f'http://127.0.0.1:8124/api/v1/backtests/{id}?include_c_result=true&include_input_snapshot=true') as r: data=json.load(r)['data']
    result=data['c_result'];replay(result)
    values=[f'{result[k]*100:.2f}%' for k in ('total_return','annual_return','max_drawdown')]+[f'{result["sharpe_ratio"]:.2f}',f'{result["win_rate"]*100:.2f}%',result['trade_count'],result['order_count']]
    assert values==expected[id],(values,expected[id])
    assert data['effective_parameters']==result['effective_parameters']
    report['cases'].append({'backtest_id':id,'exact_full_result_replay':True,'display_values_match':True,'ui_values':values,'curve_points':len(result['equity_curve']),'data_hash':result['data_hash'],'effective_parameters':data['effective_parameters'],'data_meta':data['data_meta']})
    (out/f'backtest-{id}.json').write_bytes((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())
logs=[json.loads(s) for s in (Path(__file__).parent/'ui-audit-runtime/requests.jsonl').read_text(encoding='utf-8').splitlines()]
posts=[r for r in logs if r['method']=='POST']
assert len(posts)==3
history=[r for r in logs if r['method']=='GET' and r['path'].startswith('/api/v1/backtests')]
assert all(r['status']==200 and r['market_calls']==0 for r in history)
report.update({'ui_invalid_empty_date_blocked':True,'ui_invalid_fast_ge_slow_blocked':True,'total_posts':len(posts),'history_requests':len(history),'history_market_calls':0,'a23_f3_window_mapping':'still incorrect; requested shown as actual 2025-07-07..2026-08-28; actual shown as dash','frontend_typecheck_build':'passed; large-chunk warning only','b25_targeted_tests':'4 passed; SQLite/fake provider; 976bb2306dad6b94d24d5842a921332ad92326ae'})
(out/'audit.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode())
(out/'requests.jsonl').write_bytes(('\n'.join(json.dumps(r,ensure_ascii=False) for r in logs)+'\n').encode())
print(json.dumps(report,ensure_ascii=False,indent=2))
