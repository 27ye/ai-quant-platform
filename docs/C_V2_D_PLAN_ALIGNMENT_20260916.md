# C 按 D 阶段计划调整与候选组合复核（2026-09-16）

> **后续更新：** B腾讯新包已交付并通过候选技术预验，当前待溯源修正、D确认来源和最终SHA。见[最新复核](C_V2_B_TENCENT_REVIEW_20260917.md)；下文原先等待交付的描述保留为当时状态。

依据 [D 阶段计划](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5694870966) 和本轮读取的 PR #10 实际 head **`cc574827c6c08d2336336a48d9f7a09e9582c60a`**。计划中的旧来源版本已经被后续集成推进，本文以实际代码为准。

**C 转入最终验收准备：保持算法核心，收口 HTTP 契约和版本证据；PR #10 是唯一最终集成入口，PR #12 仅保留 C 来源与审阅记录。当前阶段检查通过，尚不签最终验收。**

后续收尾状态见 [2026-09-17 最终验收准备](C_V2_FINAL_ACCEPTANCE_READY_20260917.md)；本文保留本轮 cc57482 的实测范围。

## 1. 版本冻结与分工

| 对象 | 完整 SHA / 状态 | C 的处理 |
|---|---|---|
| D 本轮实际组合 | `cc574827c6c08d2336336a48d9f7a09e9582c60a` | 从精确归档复核，不使用本地叠加后的代码冒充组合版本 |
| D 声明已合并的 A | `010841099b20b500ed322b15cec32d9e7add97cd` | 页面契约随后由 D cc57482 修正；不再要求 A 重复交同一修复 |
| D 声明已合并的 B | `25c11aa7b55d67fa5f77b3c603ca84b5369dc48e` | 搜索修复已进入；D cd88b67 另补 v8 中断恢复 |
| D 声明已合并的 C | `1d9cae17070dc7fe06a7c916ef8a0849e6790660` | C 后续 b98cc2e 与本轮提交补进度/证据；不是新的算法版本 |
| C 算法核心 | `92df017404126e9af920e1ad82e4a136d813f8d1` | D 中全部 12 个 quant Python 文件与此提交 Git blob 逐字节相同 |
| B 新提交 | `ab774a6591f2e9b5b25b2feee733c4c6c83b9be1` | [B 回复](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5695038513)；v8 执行 AST 与 D 相同，差异为函数说明；未把其 361 tests 当成本轮实测 |

D 决定如何保留 B 新提交的来源和测试；若合并产生新 head，C 结论重新绑定新 SHA。无需为本轮纯 C 验收文档频繁改动算法，但最终说明必须列清实际代码来源与证据链接。

## 2. C 本轮已独立完成

| 检查 | 结果与范围 |
|---|---|
| D 精确源码的全量 pytest | **523 passed**，0 failure/error/skip；Python 3.12.10；245 个归档原文件未改动 |
| compileall backend scripts | 通过 |
| C/AI 兼容脚本 | **7 项通过**；合成行情、SQLite、假 LLM；默认分析不被自定义回测污染，历史不重算 |
| v8 中断恢复，真实 MySQL 8.0.31 | 独立复制原 v7 的 9 条记录；预先有 LONGTEXT 列，注入回填失败后版本仍为 7；重试升至 8 并补齐 9 条；旧 exact 均 false |
| 精确文本保护及重复迁移 | 另植入一条已有直接计算结果作为精确文本，legacy SQL NULL；迁移后文本逐字节不变、读回相等且 exact=true；再次迁移记录与版本时间不变；原数据库指纹不变 |
| 前后端字段静态核对 | **8 项通过**，覆盖 5 个 C detail 字段、哈希路径、移除虚构嵌套字段、快照标志、50006、AI 404；不冒充浏览器检查 |

完整索引见 [机器可读摘要](evidence/c-dplan-20260916/summary.json)。本轮只写 C 文档/证据，未修改 A/B/D 生产文件。真实 MySQL 的新记录是迁移保护夹具，不是新数据包的 API 九组验收。

D 在 PR 说明中另外报告了前端构建、MySQL **8.0.41** V1→v8、冻结/实时 600519 + 真实 LLM、部分浏览器流程。这些保留为 **D 报告**，没有写成 C 本轮亲自执行；C 的 MySQL 版本为 **8.0.31**。

## 3. 固定接口口径

- 前端详情哈希读 `data_meta.c_data_hash`，其含义为 **C 输入快照哈希**；不是结果哈希，也不是 `frame_digest`。
- 删除的只是虚构的 HTTP `BacktestDataMeta.input_snapshot` 及其 mock。C 核心结果中的合法 `input_snapshot` envelope、可选 `c_result.input_snapshot` 仍保留。
- 详情保留 `c_result_exact`、`c_data_hash`、`c_initial_equity`、`c_warmup`、`c_execution_assumptions`，以及顶层 `input_snapshot_available` / `input_snapshot_rows`；缺失/旧值不能补造。
- 未知 AI 报告 HTTP 404 / 40006；回测不存在仍 40005；目录未成功同步 HTTP 503 / 50006。已有可用目录的刷新失败不等于目录不可搜索，GET 不回退 Provider。
- 历史 GET 只读保存快照，不调用 Provider/Quant/News/LLM。默认 AI 量化独立于参数回测；不增加新精度徽章或新算法。
- 两处非阻塞注释仍把输入哈希写成结果哈希：`frontend/src/types/api.ts:354`、`backend/app/services/backtest_service.py:629`。请相应成员/D 随文档收尾更正，C 不代改他们的生产文件。

详见更新后的 [C 前端契约](C_V2_FRONTEND_CONTRACT.md)。旧 A 探针对嵌套 mock 的检查仅保留历史范围，不继续把该结构推荐为真实 HTTP 契约。

## 4. 后续顺序与交付门槛

| 顺序 | 负责人 | 实际交付条件 |
|---|---|---|
| 现在：候选组合复核 | C | 本文、证据、看板和 PR #12 同轮推送，向 PR #10 回复阶段结论；已完成的修复不重复列为待开发 |
| 新独立真实数据包 | B | 三股 600519/000001/300750；manifest、来源/时间/区间/缺失、raw/normalized/独立 MySQL readback、逐文件 SHA-256；明确完整交易日。旧 600519 2026-09-15 差异不能因固定窗未使用就视为整包通过 |
| 验包和最终组合 | D | 验新包，处理来源合并与测试，完成成功目录搜索/切股返回原报告/宽屏侧栏等浏览器项，解释首次自动回测失败；发布最终完整 SHA、运行方式和证据；核对远端 CI 状态 |
| 最终 C 复验 | C | 在指定 SHA、新包、同一输入与规范化方式上跑三股×三参数，比较直接计算/POST/重建 engine-session 后 MySQL GET 完整对象、类型、hash、订单与三曲线；旧 exact=false、新 exact=true；列表分页和 GET 零重算 |
| V1 与边界检查 | C | 冻结 R2 33 分、24 订单、12 往返、403 点；参数类型、空对象/缺省、预热/窗口、AI 默认隔离保持；V1 数量不强加于 V2 窗口 |
| 最终结论/合并 | C / B / D | C 针对最终 SHA 发布量化结论；B/C 更新审阅，D 汇总全项目关口后决定合并。C 不自行合并 PR #10/#12/#13 |

不再沿用上午的过时时点承诺，按上述交付依赖推进；今天优先完成可复验的 P0。若真实数据或浏览器/CI 关口仍未满足，保留候选状态，不用旧证据替代。

截至本轮读取，PR #10 API 显示 **非 Draft**，但 D 明确仍有合并前置条件；UI 状态不代表已批准合并。远端无 status 项也不等于 CI 通过。

目录完整性阈值沿用当前已约定的至少 1000 条。本轮不擅自增加与 provider 动态 total 严格相等的新条件；该变更若需要，由 D/B 另行确认。
