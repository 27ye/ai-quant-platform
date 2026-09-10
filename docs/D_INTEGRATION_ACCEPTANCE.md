# D：V1 统一数据入口与联调记录

更新：2026-09-10（香港时间）。当前是**部分真实链路已验证，V1 全链路未验收完成**。此前“1045 / 未创建验收库”的结论已失效，以本记录为准。

## 版本与范围

- D 分支 `feature/V1-ai-context-integration`，草稿 PR #8；本轮改动基线 `d62f6d7`。
- 2026-09-10 重新 fetch：main `9fb1acf048726b0dd0f010cc59bb8d6117b765e5`、B PR #7 `35a048271d437281ed837ac94b437aac5302f332`，均未变化。
- D 修改后端依赖、股票/量化路由取数入口、验收工具和测试；没有修改 B 数据/缓存规则、C 量化算法或 A 前端源码，没有新增依赖、生产数据库降级或合并 main。
- 既有用户修改、未跟踪 `docs/V1_SUMMARY.md`、OMX 状态和备份 stash 保留，均不纳入 D 提交。

## 已实现的链路

- 股票、K 线、指标、评分、回测、新闻、AI 使用请求级依赖；行情统一为 B `MarketDataSource`，行情/新闻/报告仓库共享请求级数据库 Session。
- AI 单请求一次行情查询、一次 C 量化流水线，最新交易日映射为快照，结果不跨请求缓存。
- 注入 B `TradingCalendarProvider.count_between`；日历覆盖未知返回 `None` 时由 B 保守重拉，日历抛错返回 `50001`。不以工作日或 15 天阈值证明完整。
- 保留默认日期窗口、60 条有效数据、3 天容差、15 天辅助间隔、新闻 6 小时 TTL，以及价格 4 位/amount 2 位/百分比 6 位/volume 整数口径。D 不二次舍入或补数据。
- AI API 字段不变；新闻正常空列表与异常严格区分；输出校验只修复一次，第二次失败不保存，数据库写失败回滚。
- `--mysql` / `--serve` 只创建新验收库；迁移前实际查询 `VERSION()`、`@@port`、`DATABASE()`。`--serve` 默认实时，显式 `--frozen-dir` 才启用冻结源，不相互降级。

## 本轮真实证据

| 检查 | 结果 | 限制 |
|---|---|---|
| 真实 LLM `--llm-only` | 通过，`deepseek-v4-flash` | 只是 JSON 连通性，不是完整投研报告 |
| 独立 MySQL 恢复、创建新库、迁移 | MySQL 8.0.41，127.0.0.1:3307，schema version 1 | 与 B 8.0.44 有补丁版本差异 |
| 正式 AI 路由（TestClient） | HTTP 502 / `50001` | 未生成报告 |
| 浏览器真实健康请求 | HTTP 200，`X-Acceptance-Mode: live` | 不替代业务验收 |
| 浏览器搜索 600519 | 真实请求被取消，未取得结果 | 前端全局 10 秒超时；未据此判定搜索通过 |
| 浏览器详情 K 线 | HTTP 200 / `code=0`，图表已展示；243 行入库，2025-09-09 至 2026-09-09 | 本轮实时抓取，不是 B/C 的 403 行冻结样本 |
| 浏览器指标/评分/回测/AI | 均 HTTP 502 / `50001`；AI 显示失败和手动重试 | 没有成功报告展示 |
| 已入库明确区间的指标/评分/回测 | 三个真实 HTTP 接口均 HTTP 200 / `code=0`，完整结果逐字段等于同一数据直接运行 C 原算法 | 证明统一入口与 C 投影一致；不代表默认实时刷新或 AI 成功 |
| 两个验收库报告回查 | `ai_analysis` 均为 0 行 | 证明失败没有保存，不代表成功落库验收 |
| 独立外部源探测 | 新闻 10 条；日历计数 244；股票基础信息失败，异常链含 JSONDecodeError | 各自独立调用，不表示一次完整请求通过 |
| 前端 `npm run build` | 通过，2253 modules，14.19 秒 | 保留 >500 kB 包体积提示；未修改 A 源码 |
| 后端完整测试 | 222 passed，7.58 秒；compileall 与 diff check 通过 | 冻结测试夹具明确为合成数据，不是 B/C 实际数据包 |

保留的数据库：

- `ai_quant_v1_acceptance_20260910_001600_094060`：正式路由冒烟；7 张表，报告 0 行。
- `ai_quant_v1_acceptance_20260910_001629_456562`：真实 HTTP/浏览器；243 行行情，报告 0 行。

原有 MariaDB/Windows `MySQL` 服务在 3306 运行，`MySQL80` 服务保持停止。本轮只启动独立后台进程，没有停止、重配现有服务；没有操作 `ai_quant` 或 B 的 `ai_quant_test`。没有自动删除验收数据。

本机脱敏证据在 Git 忽略的 `frozen/`：

- `live-network-20260910.txt`：实际浏览器 API 请求列表。
- `live-ai-error-20260910.md`、`acceptance-live-ai-error-20260910.png`：真实页面错误状态及 K 线。
- `live-kline-response-20260910.json`：本轮成功 K 线响应，SHA-256 `e3928a6eeda6dcb95e6f890f3af0c0969b896116e45c2caaf4cb1db3eb1144c6`。
- 页面截图 SHA-256 `82d158ff607727a242eb1c409f3e552362a5571c5e8ed20802936f1a8b431f77`。

这些文件不是 B/C 冻结数据包，不用于冒充 403 行一致性验收。

## 安全启动方式

首次创建全新独立实例（3307 已占用则退出，不停止其他服务）：

```powershell
./scripts/start_acceptance_mysql.ps1
```

脚本输出非敏感实例清单；凭据、初始化日志和数据在 `frozen/_runtime/mysql_<时间戳>/`，私有 ACL 只允许当前用户和 SYSTEM。已有实例仍运行时不要重复执行初始化。重启机器后应仅恢复该实例的精确数据目录，**不再次执行 initialize 或 bootstrap.sql**。

在新 PowerShell 进程中加载该实例的私有 `acceptance.env`（不要打印内容，不修改项目 `.env`）：

```powershell
$acceptanceEnv = '<实例清单中的 environment_file 路径>'
foreach ($entry in Get-Content -LiteralPath $acceptanceEnv) {
    $parts = $entry.Split('=', 2)
    [Environment]::SetEnvironmentVariable($parts[0], $parts[1], 'Process')
}
./.venv/Scripts/python.exe scripts/validate_ai_analysis.py --mysql --stock-code 600519
# 或：启动真实 HTTP 服务（不自动发送 AI POST）
./.venv/Scripts/python.exe scripts/validate_ai_analysis.py --serve
```

另开进程启动前端：

```powershell
./scripts/start_acceptance_frontend.ps1 -Mode live
```

该脚本只改变前端启动进程：`VITE_API_BASE_URL=/api/v1`，全局和所有分接口 Mock=false；校验后端模式后启动 127.0.0.1:5173。冻结模式传 `-Mode frozen`，并传递实际样本区间给 A 的页面；**A 尚未实现冻结标识时不得认定冻结页面验收通过**。

独立验收账户为兼容现有 PyMySQL（无可选 cryptography 依赖）使用 mysql_native_password，仅限 loopback 临时实例，不改生产账户。运行时凭据按保留要求存于私有目录；不要上传、共享或同步该目录。安全复核未发现本轮脚本高危问题；保留凭据仍有本机读取风险。B helper 的任意 `--output` 路径和 A 的 ECharts 依赖 advisory 另交负责人处理，D 不运行该 helper CLI 或擅自升级依赖。

## 未完成与协作交付

1. **B/C 数据包**：仍未收到可下载的 403 行真实行情、真实交易日历、股票基础信息快照、`mysql_readback_600519.json`、完整元数据/策略参数及 SHA-256。接受 B/C 关于其 MySQL 回读一致性已通过的报告，但不能标成 D 已独立复验。
2. **冻结全链路**：材料就绪后运行 `--mysql --frozen-dir <包目录>`，通过规范化直接计算/首次查询/缓存/MySQL 回读完整一致性检查后，调用真实 LLM、正式路由并核对新增报告全部字段。没有新闻快照则明确缺失，该轮不算真实新闻验收。
3. **A 前端**：空字符串 base URL 回退、AI 120 秒超时、股票切换旧状态清理与过期请求隔离、冻结区间标识尚待提交。当前 AI 仍为 60 秒。搜索失败需要可持续辨识的错误状态；指标/评分/回测失败目前隐藏卡片。
4. **B 实时源**：基础信息接口 JSON 解析失败；行情/其他接口存在间歇性 `50001`。由 B 检查外部响应、网络与限流策略，D 不硬编码股票信息或绕过数据错误。
5. **最终联合验收**：仍需同一次真实页面操作得到 `code=0` 报告、真实 LLM、真实 MySQL 新增记录及字段一致，随后证明实时全链路稳定通过。当前 PR 保持草稿，不自动合并 main。

冻结包的 `metadata.json` 必须包含 `stock_code=600519`、实际起止日期、带时区抓取时间、`adjust=qfq`、`rows=403`、四个必需文件（行情、日历、股票快照、MySQL 回读）的相对路径与 SHA-256、完整默认 `quant_config`，以及已确认的 `quant_expectations`：评分 33、订单 24、曲线 403 点、总收益率 `-0.09165774117956027`、最终资产 `90834.22588204397`。新闻文件可选；提供时同样必须有 SHA-256。任一文件逃逸包目录、哈希不符、日期/代码/行数/参数不一致，都在创建验收库前失败。
