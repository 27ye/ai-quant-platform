const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const ts=require(path.resolve('frontend/node_modules/typescript'));
const sha='6be52abd3b024853b4c297c5e03da118d15314a0';
const src=execFileSync('git',['show',`${sha}:frontend/src/views/BacktestCompareView.vue`],{encoding:'utf8'});
const body=src.slice(src.indexOf('function semanticsLabel('),src.indexOf('// ---- 参数对照'));
const source=JSON.parse(fs.readFileSync('docs/evidence/c-v3-ui-coordination-20260922/backtest-3.json','utf8'));
const js=ts.transpileModule(body+'\nJSON.stringify(infoRows.value)',{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const cases=[];
for(const label of ['real_http','legacy_missing','partial_request']){
 const record=JSON.parse(JSON.stringify(source));
 if(label==='legacy_missing')record.data_meta=null;
 if(label==='partial_request')delete record.data_meta.requested_end_date;
 const rows=JSON.parse(vm.runInNewContext(js,{computed:fn=>({get value(){return fn()}}),detailA:{value:record},detailB:{value:record},formatDateTime:String}));
 const actual=rows.filter(r=>['请求区间','实际区间'].includes(r.label));
 const want=label==='real_http'?'2025-07-05 ~ 2026-08-30':'—';
 if(actual[0].a!==want||actual[1].a!=='2025-07-07 ~ 2026-08-28')throw Error(JSON.stringify(actual));
 cases.push({label,rows:actual});
}
const report={a_sha:sha,cases,status:'passed',scope:'Original A computed source executed with saved real B GET and two missing-field variations; browser validation recorded separately in README'};
fs.writeFileSync(path.join(__dirname,'projection.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
