# C V2 第一轮实现与本地验证报告

日期：2026-09-15。范围：PR #9 中 C1–C4 的计算模块、计算契约和离线验证。

## 结论

C 参数化回测已完成本地实现和验证，可以交给 B/D/A 评审接入。全量后端 **373 passed，1 条依赖弃用 warning**；R2 旧 V1 完整结果精确保持一致。新回测默认参数、两组自定义参数、long=120 单日场景均完成 JSON 保存/回读后的完整复算。

状态是 **C 离线计算通过、跨模块接入待办**。没有声明新 HTTP 参数接口、V2 真实 MySQL 历史、实时多股票或 V2 浏览器流程已完成。

后续 PR #10 协调：在 D 的 `e95198a0ea3f1b34d64d562c161d37d033ab66ce` 独立检出上叠加本地 C 文件，修复 C 测试替身缺少来源接口的问题后，全量后端 **390 passed，1 warning**。此数字属于 D/C 叠加测试，不能替换上述 C 原基线的 373 项记录，也不包含 B 全部分支。详细当前状态见 [C_V2_PR10_COORDINATION.md](C_V2_PR10_COORDINATION.md)。

## 版本与改动

- 共同基线：`8062599b3d85c421f00714de9d27a9fbe11ad083`。
- 本地分支：`codex/v2-c-backtest-params`。
- 工作目录：`C:/Users/15149/Desktop/qproject/ai-quant-platform-c-v2`。
- 当前是基线加本地未提交改动；上述 SHA 不包含本轮实现。
- 两套回归清单绑定的核心源码指纹：`1b6be03348c2e46b524f17a2fec6be2c8751f5040d412f84ca83b25d479bfb45`。
- 没有提交、推送、合并，也没有改动 A/B/D 模块、数据库、依赖或原 V1 工作目录。

| 文件 | 作用 |
|---|---|
| backend/app/quant/backtest_config.py | 五参数白名单、严格验证、独立配置、旧/新请求语义 |
| backend/app/quant/windowed_backtest.py | 预热与交易窗口分离、首日规则、版本化结果和输入快照 |
| backend/app/quant/backtest.py | 复用既有成交引擎；V2 首日本金锚点、基准和浮点尾差处理；V1 分支保持原行为 |
| backend/app/quant/__init__.py | 导出新增 C 入口，原有入口保留 |
| tests/quant/test_backtest_config.py | 参数及请求语义测试 |
| tests/quant/test_windowed_backtest.py | 独立手算、区间、成交、默认隔离和数值边界 |
| tests/quant/test_backtest_snapshot.py | 实际计算输入、哈希、精度、无关数据隔离 |
| scripts/validate_v2_backtest.py | 无外部业务 I/O 的样例及证据生成 |
| tests/quant/test_v2_backtest_delivery.py | 交付脚本的完整比较、失败和防覆盖验证 |
| docs/C_V2_BACKTEST_CONTRACT.md | 给 B/D/A 的计算契约与接线说明 |
| docs/C_V2_PR10_COORDINATION.md | PR #10 最新实现、B 评审目标与 C 适配/验证边界 |
| scripts/validate_c_ai_history_compatibility.py | 在已包含 PR #10 的代码上验证默认 AI 与 C 自定义回测隔离、历史回读；仅合成行情/替身 LLM/SQLite |

## 已实现行为

1. 只开放短/长均线周期、初始资金、交易成本和滑点。未知参数、布尔伪整数、非有限数字、非法周期均明确拒绝。
2. 省略 parameters 保留旧语义；显式对象使用新窗口语义；null 报参数错误。
3. 新窗口只使用开始日前最后 long 条有效行情预热，首日零初始持仓，可按前一日已知信号在首日开盘成交。预热期没有交易或收益。
4. 首日盈亏进入总收益、日收益、回撤与 Sharpe；三条曲线仍各自每天一个点，本金起点另行标记。
5. 新基准从首日开盘买入、不扣费用，名称和假设明确披露。默认评分与 AI 使用的旧配置不受用户回测参数影响。
6. 输出完整配置、实际区间、订单/往返、曲线、版本、实际计算输入及哈希。历史读写接口和数据库 ID 仍由 B 实现。

独立测试发现并修复了一个合法大资金场景：1 亿初始资金的买入可能产生约 −1.49e−8 的浮点现金尾差，旧固定阈值会误报。V2 采用按资金浮点精度计算的容差处理；V1 算术不变。不能表示的极端成交数值明确报错，不伪装为无交易成功。

## 实际验证

实际解释器为现有 C 虚拟环境的 Python 3.12.10，未更改依赖。另对 C 源码执行 Python 3.9 语法检查；这不等于运行了完整 Python 3.9 环境。

```powershell
$v2Python = 'C:/Users/15149/Desktop/qproject/ai-quant-platform-c-v1-regression/.venv/Scripts/python.exe'
Set-Location -LiteralPath 'C:/Users/15149/Desktop/qproject/ai-quant-platform-c-v2'
& $v2Python -m pytest tests -q --junitxml='C:/Users/15149/Desktop/qproject/.codex-task/v2-c-20260915/backend-tests.xml'
```

结果：373 passed，耗时 23.17 秒。唯一 warning 是 Starlette/AnyIO 的 BlockingPortal 别名弃用提示。另有 backend/scripts compileall、C 源码 Python 3.9 grammar 和 git diff --check 通过；变化路径已限定在 C 范围。

### 冻结默认回归

使用此前独立确认的 R2 规范化输入：

- 输入 SHA-256：`02524eee7322efb832df80c80cd79cc94c46056b98aa00639967e8e47d3179cb`。
- 旧完整结果 SHA-256：`9aed066204ba0689470ddb809e96219c69492cd0695c589f4b0610d79a3adafb`。
- 输入 403 行，实际日期 2025-01-02 至 2026-08-31。
- 完整 meta、全部指标及 null、评分/原因、所有回测指标、每条订单和三条曲线按值及类型精确一致。
- 因此旧默认仍为 33 分、24 条订单、12 次往返、403 个权益点。

本轮使用本地冻结文件及旧证据，不是重新获取实时行情，也不是重新访问 MySQL。输入的 dataframe 标签为保持原基线元数据，来源说明明确记为历史 R2 冻结规范化样本。

### 新参数回归样例

以下三个示例共用 2025-07-04 至 2026-08-31 的实际窗口，各 283 个权益点。它们是功能/口径验证样例，没有按收益优选参数。

| 示例 | 初始资金/成本/滑点 | 订单 / 完成往返 | 模型总收益 |
|---|---|---|---|
| V2 默认 MA5/20 | 100000 / 0.001 / 0 | 18 / 9 | −10.459070% |
| MA10/30 | 100000 / 0.001 / 0 | 14 / 7 | −20.405249% |
| MA20/60 | 200000 / 0.002 / 0.001 | 7 / 3 | −12.636743% |

另有 long=120、只回测一个交易日的场景通过。窗口与规则不同于 V1 403 行全区间，不能据这张表把收益差异归因于算法优劣。模型仍保留碎股和简化成交假设。

## 证据文件

相对于本工作目录：

- `../.codex-task/v2-c-20260915/backend-tests.xml`：全量后端测试。
- `../.codex-task/v2-c-20260915/validation-summary.json`：验证摘要与变更文件哈希。
- `../.codex-task/v2-c-20260915/frozen-r2-final/manifest.json`：403 行 R2 回归与完整结果清单。
- `../.codex-task/v2-c-20260915/synthetic-final/manifest.json`：696 行明确合成样本的独立回归。

两目录均含完整输入、V1 全量结果、旧回测、新默认、自定义两组、单日边界、源码指纹和文件 SHA。输出清单核验后与当前核心源码一致。脚本拒绝覆盖已有输出目录，失败返回非零。

这些证据只验证离线计算和 JSON 保存/回读/复算，不替代真实 MySQL 历史保存/查询。

## 下一步对接

### B 反馈后的交付准备补充（2026-09-15）

本次只补充 C 对接说明及 `scripts/example_v2_c_integration.py`，量化核心没有修改。明确验收数据包 120 条与每次计算 long 条的区别、Schema 转换前严格校验、C 统一窗口裁剪、实际输入快照、技术指标序列范围及 raw/canonical 精度责任。

新增可执行示例使用合成数据，四组合法请求（旧缺省、新空对象、自定义、long120 单日）运行通过；四组非法参数在内存 loader 调用前拒绝。每组输出完整请求和结果并验证 JSON 回读。该结果是 C 接线样例验证，不证明 B HTTP、真实行情、MySQL 或前端通过。前一轮针对参数/窗口/快照的 123 项测试已经通过，本轮未重复全套测试；既有 373 项记录仍属于此前全量后端运行。

示例输出位于 `../.codex-task/v2-c-b-handoff-20260915/examples/`。交付基线仍为 `8062599b3d85c421f00714de9d27a9fbe11ad083` 加未提交文件，不可将该基线 SHA 当成包含新实现的提交。三股票真实文件、B 正式接口与 MySQL 一致性仍待联合验证。

### PR #10 D/C 协调补充（2026-09-15）

PR #10 核对 HEAD 为 `e95198a0ea3f1b34d64d562c161d37d033ab66ce`，基线仍为 `8062599...`；评审要求报告错误码改为 40006、迁移归 B 统一分步方案，当前 PR 中尚未落地。本轮不修改 B/D 源码、不合并分支，独立目录只叠加 C 自己的文件。

- 修复前实际复现：C 默认 AI 隔离测试的行情替身缺少 `get_query_provenance`，D 新 adapter 明确抛错。
- 修复仅给 C 测试替身增加 `source_mode=frozen`、`provider=synthetic_c_test_fixture`，不放宽 D 检查；在原 C 基线单项测试通过。
- D/C 叠加全量回归：390 passed、1 条既有依赖弃用 warning，24.89 秒。
- D/C 叠加后的 R2 403 行冻结输入与完整 V1 JSON 精确一致；新默认、两组自定义、long120 单日及 JSON 回放继续通过。
- C 评分、回测算法及其版本号未变；D 的 15 位有效数字规范化只适用于 AI 上下文副本，不改变 C 的全精度输入/结果/hash。
- 新增独立兼容脚本 7 项检查通过：220 条合成行情、假 LLM、临时 SQLite；固定时间下默认 C/AI 投影在自定义回测前后不变，15 位规范化不改 C 输出；关闭并重建 engine/session 后历史结果一致，且禁止行情/C/LLM 调用；旧快照缺失和篡改哈希处理符合当前 D 契约。
- 同一脚本在没有 PR #10 能力的 C 原基线上明确非零退出并提示 Requires PR10，不误报兼容通过。首次 Windows asyncio 本机 socketpair 被网络保护误拦的问题已在校验脚本中修复，业务模块未受改动。

本轮证据在 `../.codex-task/v2-c-pr10-coordination-20260915/`：`before-c-fixture-fix.xml`、`c-base-fixture-check.xml`、`d-plus-c-tests.xml`、`d-plus-c-frozen-r2/manifest.json`、`ai-history-compatibility-v2/report.json` 和 `c-base-requires-pr10/report.json`。历史 `v2-c-b-handoff-20260915` 交付包保留为当时快照，不包含本轮适配，不能当作最新版本。

- **B**：保留 parameters 的字段存在性；在取数前调用参数/日期校验；按 C 需求补足开始日前有效预热行；调用新 C 入口；原子保存完整输入/结果快照，补版本和 ID，GET 仅回读。
- **A**：按白名单做表单，展示本次实际参数、区间和收益口径；区分默认分析与自定义回测；旧结果不随表单修改而改标。
- **D**：评审首日执行、基准和版本标记；默认 AI 保持默认分析口径；汇总后在最终组合提交组织复验。
- **C**：对 B 接入后的参数错误、long120 短窗口、两组参数的独立 ID、完整 MySQL 快照回读及最终组合复核。此前不把 C 单测通过称作整个平台 V2 完成。

可供用户转发的说明（本轮未代发）：

> C 已在主分支 8062599 基础上完成参数化回测的本地实现，支持五字段白名单、预热/回测窗口分离、首日盈亏、完整版本与快照。全量后端 373 项测试通过；R2 的旧完整结果精确不变；新默认和两组自定义参数均通过离线保存/回读复算。当前未推送，尚未接入 V2 HTTP 和真实 MySQL 历史。请 B/D/A 评审 C 计算契约，随后按职责接线。
