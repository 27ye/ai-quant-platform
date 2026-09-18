# C 对 A/B 新回复的核对与协调记录

日期：2026-09-16。范围为字段、接线与离线复核，不是最终集成验收。未修改 A/B/D 源码，未发表评论、推送或合并。

## 1. 核对版本及最新状态

| 对象 | 版本/证据 | 状态 |
|---|---|---|
| A 前端 | `0e1d9b1595551a516bebe8714a24e64476dfe412` | fork 分支已可读取，已在独立副本检查 |
| B 数据服务 | `ad84dbdd6faa11144e1b860c95042deeaf61f367` | 最新提交只新增数据证据，相关接线源码与 `5f255d1` 相同 |
| D PR #10 | `e95198a0ea3f1b34d64d562c161d37d033ab66ce` | 本次查询仍 Draft/Open，未合并 |
| C | 本地 `codex/v2-c-backtest-params`，基底 `8062599b3d85c421f00714de9d27a9fbe11ad083` | C 实现仍未提交、推送；基底不含这些实现 |

来源：[A 执行回复](https://github.com/27ye/ai-quant-platform/issues/11#issuecomment-5680066516)、[B 最新交付声明](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5689910575)、[B 旧批次声明](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5677171819)。

B 最新评论发布时间为北京时间 2026-09-16 08:09:07；它替代旧批次的缺失状态。按用户要求，在 08:10:21 至 08:12:10 检查 PR #10 与 Issue #11，期间没有后续新增或编辑评论。不是持续后台监控。

## 2. A 已确认项及两处需修正的问题

A 的 `npm run build` 包含 `vue-tsc --noEmit`，两步均通过；Vite 仅有产物体积警告。源码工作树保持干净。

五个参数名、默认值、严格数值检查、成交和曲线类型已对齐。AI 详情读取保存快照的 `context_snapshot.provenance.market_end_date`，列表暂时不显示 `data_as_of`，与当前 D 实现含义相符。

### A-1 日期校验

[backtestParams.ts](https://github.com/kokona339/ai-quant-platform/blob/0e1d9b1595551a516bebe8714a24e64476dfe412/frontend/src/utils/backtestParams.ts#L41) 使用 `Date.setFullYear`，且未校验无效日期或严格格式。直接调用 A 原函数测试 17 组输入，其中 5 组日期输入与 C 不一致：

| 输入 | C 预期 | A 当前 |
|---|---|---|
| `2020-02-29` 至 `2025-03-01` | 拒绝，最晚应为 `2025-02-28` | 放行 |
| 开始日期 `not-a-date` | 拒绝 | 放行 |
| 结束日期 `not-a-date` | 拒绝 | 放行 |
| 开始日期 `2025-02-30` | 拒绝 | 放行 |
| 开始日期 `2025/07/04` | 拒绝 | 放行 |

另用当前 C 的 `validate_backtest_window` 直接核对 12 组日期输入，均符合已记录契约。请 A 按年月日验证真实日期，并将非闰年的闰日周年钳制到 2 月 28 日。

### A-2 历史页面的过期响应

[详情页 load](https://github.com/kokona339/ai-quant-platform/blob/0e1d9b1595551a516bebe8714a24e64476dfe412/frontend/src/views/AIReportDetailView.vue#L37) 与 [列表页 load](https://github.com/kokona339/ai-quant-platform/blob/0e1d9b1595551a516bebe8714a24e64476dfe412/frontend/src/views/AIReportHistoryView.vue#L28) 没有过期请求隔离。

在内存中编译原始 setup 逻辑、替换外部响应为可控制的 Promise，已复现：

- 报告 2 先返回、报告 1 后返回，当前路由为 2，正文最终为报告 1。
- 切到 000001 后，600519 的旧响应仍可覆盖当前列表。
- 两个页面的旧请求 finally 均可在新请求待返回时提前清除 loading。

请 A 参考已有 StockDetailView 的 epoch 机制，成功、失败、finally 都只允许当前请求更新状态。此为状态逻辑复现，不是浏览器端到端测试。

A 明确将 A2 表单、A3 回测历史留待后续；当前工具函数尚未接入表单，历史回测路由仍为占位页，不将这些待办误报为已完成功能的回归。后续仍需补实际参数、区间、warmup、initial_equity 类型及 V1 空值兼容。

## 3. B 数据包：声明完整，但 C 尚未收到

B 最新声明三只股票 600519/000001/300750 的 raw 与 normalized 各 436 行，实际区间 2024-12-02 至 2026-09-15；三股 normalized 与其 MySQL 的 frame_digest 一致。本次未采用 v7，旧的缺失项目和迁移选择不再作为当前阻塞。

评论列有六份完整 SHA-256，但 `frozen/c-delivery/` 明确是 B 本机 Git 忽略目录。最新提交树中没有这些文件或数据包，C 当前工作区也未找到相应文件。应请 B 提供可下载 ZIP 或双方可读位置，包含六份 JSON、三份 metadata、MANIFEST.json、mysql_readback.json。

取数脚本重新抓到的内容不等于本批相同文件；此时不能把“B 声明完成”写成“C 已收到并验收”。C 收到后核对字节哈希、股票代码/日期顺序/重复值/行数、预热覆盖及规范化规则，再固定同一回测区间进行验收。

B 的 normalized 与行情表回读相等只属于输入层证据，不代替 C 直接计算、服务返回、回测历史快照的逐字段一致性。

## 4. B 最新 SHA 的接线问题

离线检查显式读取最新 `ad84dbd` 源码，使用当前 C 实现、合成行情和替身数据源，无网络或数据库写入。

### B-1 完整配置误作请求参数

[backtest_service.py:413](https://github.com/Lawera2601/ai-quant-platform/blob/ad84dbdd6faa11144e1b860c95042deeaf61f367/backend/app/services/backtest_service.py#L413) 与第 440 行向 C 传 `effective.to_parameters()`，包含整个 QuantConfig。C 严格五字段解析器拒绝未知字段。前一次解析异常被吞掉，离线复现中先取数一次，再在 run 失败。

请 B 仅传五个请求字段，先校验参数及日期再取数，不能吞掉校验异常。C 入口探测成功并不证明调用成功。

### B-2 旧路径被标为 V2

C 入口不存在时，B 仍调用旧 run_backtest，随后无条件写入 `semantics_version=v2_windowed`。在 150 条合成输入、5 条实际窗口的诊断中返回 150 点，却仍标 V2。

请在显式 V2 请求缺少 C 入口时明确失败且不保存成功记录；省略参数的 V1 路径保持原行为。`window_owner` 的文字说明不能弥补错误的机器可读版本。

### B-3 C 结果被覆盖、持久化字段不完整

仅在诊断适配器中将请求投影为五字段后，可继续执行。此时 [第 471 行](https://github.com/Lawera2601/ai-quant-platform/blob/ad84dbdd6faa11144e1b860c95042deeaf61f367/backend/app/services/backtest_service.py#L471) 又用 B 原配置覆盖 C 的 `effective_parameters`，将 `benchmark_method=first_open_to_last_close_no_cost` 改回 `first_close_to_last_close`。

静态读取 save/get 路径还发现：

- 持久化只保存选定列，未完整保留 C 的 algorithm_version、warmup 对象、initial_equity、execution_assumptions 和顶层 data_hash。
- `result.get('strategy_version')` 与 C 返回的 algorithm_version 名称不同。
- B 重建的 input_snapshot 是纯行数组，缺少 C 快照的 schema_version、columns、data_mode、sha256 等元信息。
- 历史详情从上述字段重新组装，而非读取原样 C 结果。

请 B 原样保存 C 完整结果 JSON，POST 和历史详情使用同一快照；摘要列可供列表和检索，不用舍入后的摘要重建完整验收结果。旧历史记录保留缺失状态，不使用当前行情补造。

### B-4 哈希边界

B `frame_digest` 对日期及 OHLC 等数值行计算摘要；C `data_hash` 对实际选用输入及其快照元信息计算摘要，两者不是同一算法/对象。B 当前 `data_meta.data_hash` 还按全部抓取行计算，包含 C 未使用的更早行。即使把 B 摘要范围裁到相同行，哈希仍不相等。

应分别记录文件字节 SHA-256、B 行情摘要、C 输入 data_hash、D AI context_hash，不相互替换。C 顶层 data_hash 在当前 POST 结果中暂存并不等于数据库已保存。

## 5. 责任与下一步

| 成员 | 当前动作 |
|---|---|
| A | 修日期校验及 A4 过期响应，给新 SHA；A2/A3 按计划接入 |
| B | 给出真实数据包下载位置；修五字段调用、禁止假 V2 回退、保留 C 完整结果与快照；在 Issue #11 补实际 HTTP 样例 |
| C | 当前只读评审和离线复核完成；待可读取 C 版本与真实文件到位后做直接计算/API/MySQL 一致性验收 |
| D | 统一迁移、回测/报告错误码及 AI 时间标签；确认合并时间线和最终组合 SHA |

C 入口仍为 `run_backtest_request(data, *, start_date=None, end_date=None, parameters=PARAMETERS_UNSET)`；输入含预热，由 C 选窗。当前入口不返回技术指标逐日序列，不将该项误称为已交付。

本轮未运行 B 的重新抓取、MySQL 导入或迁移，也未测试真实三股数据、真实 HTTP/MySQL 或完整浏览器流程。最终结论仍待组合版本与上述证据齐备。
