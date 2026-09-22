// Run from C checkout with its installed frontend TypeScript dependency.
// Executes the unchanged A23 infoRows projection against real B21 GET fields.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const ts = require(path.resolve('frontend/node_modules/typescript'));
const sha = 'af5e17217b16e8270107e771508d378e0b7dbba6';
const src = execFileSync('git', ['show', `${sha}:frontend/src/views/BacktestCompareView.vue`], {encoding:'utf8'});
const body = src.slice(src.indexOf('function semanticsLabel('), src.indexOf('// ---- 参数对照'));
if (!body.includes('const infoRows')) throw Error('A projection not found');
const source = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).nontrading_boundary_detail;
const sandbox = {computed:fn=>({get value(){return fn()}}),
  detailA:{value:source}, detailB:{value:source}, formatDateTime:String};
const js = ts.transpileModule(body+'\nJSON.stringify(infoRows.value)', {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
const rows = JSON.parse(vm.runInNewContext(js,sandbox));
const report = {a_sha:sha,b_sha:'0360b699f6530aefd5afe5e11e859f4c179146d8',
  scope:'Real B HTTP fields evaluated by original A computed projection; no browser',
  actual_rows:rows.filter(r=>r.label==='请求区间'||r.label==='实际区间'),
  expected_requested:`${source.data_meta.requested_start_date} ~ ${source.data_meta.requested_end_date}`,
  expected_actual:`${source.start_date} ~ ${source.end_date}`};
report.finding = report.actual_rows[0].a !== report.expected_requested || report.actual_rows[1].a !== report.expected_actual;
fs.writeFileSync(process.argv[3],JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
