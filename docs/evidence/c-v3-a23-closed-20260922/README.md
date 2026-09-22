# C：D群内状态及A F3修复闭环

日期2026-09-22。D群内表示D线待办清空、类型统一、head已给B，待A修F3/B审C18后组合预演。本轮GitHub已出现A修复，因此不能继续沿用“A未修”的旧状态。

## A23：C窗口映射请求已闭环

被测SHA `6be52abd3b024853b4c297c5e03da118d15314a0`，相对af5e172仅4个前端文件变更。请求改读data_meta.requested_*，实际改读顶层start/end，移除actual_*；类型、mock与详情信息同步。

- 原样前端 `vue-tsc --noEmit`、`vite build` 均exit0，构建仅大chunk提示。
- 浏览器重新打开 `/backtests/compare?a=3&b=2`，复用上一轮实际HTTP/SQLite保存的两条MACD结果：请求显示 **2025-07-05 ~ 2026-08-30**，实际显示 **2025-07-07 ~ 2026-08-28**；两组参数/收益/哈希仍分别正确。
- 浏览器使用A新head和上一轮已经启动的D22 fedeb09+C后端进程；固定历史样本/SQLite，非实时/真实MySQL/LLM或最终组合。侧栏“后端未连接”不是本轮回测GET证据，未据此验收整体健康状态。
- `probe.cjs` 执行A原始computed投影，使用保存的真实GET以及缺data_meta、缺请求结束日两种变体，共3项通过；缺请求数据均“—”，不挪用实际区间。结果见projection.json。
- C范围可APPROVE，原窗口REQUEST_CHANGES解除；不代替A整站视觉/可访问性验收。
- 非阻塞文案：mock说明把2025-07-01写为“非交易日”不严谨，这只是人为设置的样本缺失。建议写“请求早于样本实际首日”，或使用已验证周末07-05的示例。

## D22：仅类型名统一

新head `64474b4458579b2378fd06a4af766c72b16c0789` 相对fedeb09只改AIReportBody.vue及types/api.ts的AnalysisMode→AIAnalysisMode，共5增5删。backend/tests/scripts差异为空；core/errors.py未改。新head前端typecheck exit0。C既有后端数值复验/APPROVE保持，不把旧746项宣称为本轮新跑，也不把新head当最终组合SHA。

## B新回复与PR26

Issue20 comment5778352216已给D22 fedeb09/生产6c9ca52的公共错误码唯一性结论，40007→HTTP422，既有11码不变。新D仅前端类型修改，不改变错误码文件；B若按其流程要求仍可补新head引用。

PR26 `9a7abbb6b748aa71a7e252cb76b3f1a5ca5fe4da`仅修改API_SPEC：40004保留未用、非法策略40001、登记50000、说明50005由AI异常体系承载。已读diff，与C接线一致，无C代码适配。合并时保留D22的40007行与B文档说明；由D集成，不自动合并。

## 后续归属

- B：按D要求主审C18；最终组合SHA上真实MySQL复验。
- D：安排C18/A23/B24/D22及新增B25/B26的取舍与集成，公布候选/最终完整SHA。
- C：A映射请求已关闭，算法不变。最终组合就绪后进行C4；当前不签最终V3。
