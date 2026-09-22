# C 对 B21 修复及 A23 对照字段的复核

日期：2026-09-22。**B21 上轮两项请求已修复，C专项通过；A23存在请求/实际区间映射问题；D22的数值矛盾拦截仍待修复。**

## 版本与边界

- B21：`0360b699f6530aefd5afe5e11e859f4c179146d8`。
- C代码：`6a84901c82256b7d48dfab3ebee3208633e5058c`（交付分支9206398的quant与该代码一致）。仅在隔离目录叠加C quant、两份测试、脚本和样本，未改B文件。
- A23：`6daa211fc98a2ec252fd19eccdd4d340a17e0dd3`，只读复核。
- 固定腾讯qfq normalized样本，三股票600519/000001/300750，三组MACD参数（默认、6/13/5、20/40/12+资金200000/成本0.002/滑点0.001）。区间2025-07-04至2026-08-31。
- 真实FastAPI/schema/service/C/Repository，临时文件SQLite；不是MySQL、实时Provider、真实LLM或浏览器验收。不包含B19/D22迁移组合，不是最终集成SHA。

## B修复独立复验通过

- 全量 **703 passed, 1 skipped**，2条依赖弃用warning。skip为C已存在时不执行的“缺C实现”分支用例；专项探针另关闭支持位实测500/50004、取数0/落库0。
- 三股九组直接C计算与POST全部字段/JSON类型一致；重建engine/session后GET的完整C精确结果一致，历史读取期间取数/重算入口禁止调用。
- 九组POST/GET的effective_parameters及GET parameters均六字段、值与类型一致；历史参数再次POST成功且完整C结果不变。C执行说明保留在精确结果，未泄漏为可调参数。
- 两日期都省略、仅省略start、仅省略end、start=null、end=null：5/5返回400/40001，取数0、落库0。
- 六项非法策略/参数边界仍40001、取数0、落库0。MA省略日期与显式ma_cross均保持旧补值行为，200，窗口2025-08-30至2026-08-31。
- 证据：`result.json`。`probe.py`在被测B+C checkout运行：`python <探针绝对路径> <新输出json路径>`；已有C脚本/样本为依赖。失败非零退出，不改项目数据库。

结论仅解除C对B21的日期和实际参数两项REQUEST_CHANGES；不代表最终组合已验收。

## A23请求/实际区间映射需修复

真实HTTP新增一个非交易日边界请求：2025-07-05至2026-08-30。GET返回：

| 字段 | 实际值 |
|---|---|
| data_meta.requested_start_date / requested_end_date | 2025-07-05 / 2026-08-30 |
| 顶层start_date / end_date | 2025-07-07 / 2026-08-28 |
| data_meta.computed_start_date / computed_end_date | 2025-07-07 / 2026-08-28 |
| data_meta.actual_start_date / actual_end_date | 不存在 |

将这些接口字段送入A原始`BacktestCompareView.vue`的infoRows（TypeScript转译执行，未修改源函数），得到“请求区间=2025-07-07 ~ 2026-08-28”，“实际区间=—”。用户选择的非交易日起止被替换，实际窗口反而丢失。

请A把请求区间映射到data_meta.requested_*；实际区间使用顶层start_date/end_date或已存在的computed_*。旧记录未保存请求区间时显示未保存，不用实际区间冒充请求；同时更新相应类型/fixture和差异提示。无需B新增actual_*别名、也不修改C窗口口径。

复现：从C checkout（已有frontend TypeScript依赖）执行：

```powershell
node docs/evidence/c-v3-b21-fixed-20260922/probe_a23.cjs docs/evidence/c-v3-b21-fixed-20260922/result.json <新输出文件.json>
```

需本地git对象已获取上述A SHA。输出`a23-projection.json`是实际源函数映射证据；不是浏览器验收。其他只读核对：MACD六参数构造与默认值/周期规则符合C契约；收益按equity/initial_cash-1换算，trade_count标为往返次数，null不伪造0。

## 下一步

- D22仍`bf7cd54a7694728e48937ce9d8f54a5ae4a12714`，C上一轮数值矛盾拦截请求未见修复，结论不变。
- 支持B建议由PR19提供唯一v9来源，请D确定集成顺序并处理D22重叠迁移；B可执行候选组合迁移/历史读取预验，但须写清全部输入SHA，不代替最终版本签字。
- A修复区间投影后，C复核对应SHA；B本次闭环不要求再重复执行旧探针。最终集成冻结后按C4执行完整验收。
