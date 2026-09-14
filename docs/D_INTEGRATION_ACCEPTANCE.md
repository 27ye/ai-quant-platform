# D：V1 统一数据入口与联调记录

更新：2026-09-14（香港时间）。当前是**B 已合入 main，A 最终前端已合入 D，最终组合代码的冻结数据＋真实 MySQL＋真实 LLM 正式路由已重新通过，PR #8 可以解除 Draft 进入评审**。C 对最终推送 SHA 的复核和浏览器点击复验仍作为合并前证据；实时多股票链路归入 V2。

## 版本与范围

- D 分支 `feature/V1-ai-context-integration`，草稿 PR #8；功能组合提交 `f8ffcacf9a89558120c1a2df7d67ad8036a0f3b8`。
- `origin/main` 为 `d04f7d5613b25bcdfe94c687bd09d021278995a0`，已合入 B PR #7 `582510c60f59a051e8a707aaf0bbf9fcc59b5504`；D 通过 merge 同步 main，保留 PR 历史，没有 rebase 或强推。
- 已合入 A 最终前端 `8a045a2ee97fdb593276ebe3c59377c6ec767c37`：包含 120 秒 AI 超时、请求 epoch 隔离、冻结范围标识、新闻模块、空新闻状态，以及可由 `VITE_PROXY_TARGET` 覆盖的本机代理默认值。
- D 修改后端依赖、股票/量化路由取数入口、验收工具和测试；没有修改 B 数据/缓存规则或 C 量化算法，没有新增依赖、生产数据库降级或直接合并 main。
- 既有用户修改、未跟踪 `docs/V1_SUMMARY.md`、OMX 状态和备份 stash 保留，均不纳入 D 提交。

## 已实现的链路

- 股票、K 线、指标、评分、回测、新闻、AI 使用请求级依赖；行情统一为 B `MarketDataSource`，行情/新闻/报告仓库共享请求级数据库 Session。
- AI 单请求一次行情查询、一次 C 量化流水线，最新交易日映射为快照，结果不跨请求缓存。
- 注入 B `TradingCalendarProvider.count_between`；日历覆盖未知返回 `None` 时由 B 保守重拉，日历抛错返回 `50001`。不以工作日或 15 天阈值证明完整。
- 保留默认日期窗口、60 条有效数据、3 天容差、15 天辅助间隔、新闻 6 小时 TTL，以及价格 4 位/amount 2 位/百分比 6 位/volume 整数口径。D 不二次舍入或补数据。
- AI API 字段不变；新闻正常空列表与异常严格区分；输出校验只修复一次，第二次失败不保存，数据库写失败回滚。
- `--mysql` / `--serve` 只创建新验收库；迁移前实际查询 `VERSION()`、`@@port`、`DATABASE()`。`--serve` 默认实时，显式 `--frozen-dir` 才启用冻结源，不相互降级。

## 2026-09-14 冻结链路证据

| 检查 | 结果 | 限制 |
|---|---|---|
| 最终 A＋B＋D 组合版本 | main `d04f7d5`＋A `8a045a2`＋D，功能组合提交 `f8ffcac`；静态合并无冲突 | C 尚需对最终推送 SHA 复核 |
| 组合版本后端测试 | `244 passed`，11.55 秒；`compileall` 与 `git diff --check` 通过 | 含 B Provider 重试、D 集成与冻结包契约测试 |
| 前端构建 | 2257 modules，11.43 秒 | TypeScript/Vite 通过；保留 >500 kB 包体积提示 |
| B/C 冻结包离线校验 | 600519，2025-01-02 至 2026-08-31，403 行；文件哈希、交易日历、股票快照与 metadata 契约全部通过 | 包内新闻明确为缺失 |
| 完整量化一致性 | 直接数据与 MySQL 回读文件严格一致；评分 33、订单记录 24 条、权益曲线 403 点、总收益率 -0.09165774117956027、最终资产 90834.22588204397 | 页面 API 的 `trade_count=12` 表示买卖往返次数，与 24 条订单记录口径不同 |
| 最终组合冻结正式 API＋MySQL＋真实 LLM | 在功能组合 `f8ffcac` 及证据提交 `9aeff09` 上复验；MySQL 8.0.41 / 127.0.0.1:3307；新库 `ai_quant_v1_acceptance_20260914_072253_345994`；正式路由校验通过，报告 `id=1`，量化评分 33、行情 403 行 | 新闻 0 条，报告明确按新闻缺失处理；验收库保留 |
| 冻结浏览器数据链 | 搜索、K 线、指标、评分、回测全部 HTTP 200 / `code=0`；403 行 K 线、403 行指标、评分 33、12 次往返、403 个权益点；页面无脚本错误 | 为避免未经再次确认的数据外发，本轮浏览器没有再次点击 AI；命令行正式路由的真实 LLM 与落库已通过 |
| 最新实时 Provider 冒烟 | 股票信息成功（6.012 秒）、新闻 10 条（0.166 秒）、交易日历 242 日（1.374 秒） | 搜索在 4.866 秒、日线在 5.918 秒后抛 `StockDataProviderError`；实时全链路仍不通过，服务层应保持映射为 `50001` |
| 页面截图 | `frozen/acceptance-frozen-data-success-20260914.png`，SHA-256 `f17b6b0be4cd3bd592b249a79ec6feecdb7a78ee3fef0f7b81382646ed37646a` | Git 忽略的本机脱敏证据 |

独立 MySQL 运行目录为 `frozen/_runtime/mysql_20260914_004213_790059`；实例和全部验收库均保留，没有操作现有 3306 数据库。冻结包位于 Git 忽略的 `frozen/packages/v1-frozen-package-r2`，ZIP SHA-256 为 `90b1f207b209cfea3a1570abb3c2fbbda5afb7079e01e3c11a34671e8c1df7dd`。

## 2026-09-10 实时链路历史证据

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

1. **冻结浏览器 AI**：命令行正式路由的真实 LLM 与落库已通过；浏览器页面仍需在明确允许向 `https://api.deepseek.com` 发送冻结行情、量化和空新闻上下文后，再点击一次 AI 并核对页面报告与新增数据库记录。
2. **冻结新闻**：发布包没有真实新闻快照；空新闻披露已保留，但冻结验收不能标成真实新闻通过。
3. **A 前端**：空字符串 base URL 回退、AI 120 秒超时、股票切换旧状态清理与过期请求隔离、冻结区间标识尚待提交。当前 AI 仍为 60 秒。搜索失败需要可持续辨识的错误状态；指标/评分/回测失败目前隐藏卡片。
4. **B 实时源**：已合入 `582510c` 的有限重试、同源备用主机和严格响应校验；当前环境复测仍是搜索、日线失败，股票信息、新闻和日历成功。失败时保留 `50001`，D 不硬编码股票信息或绕过数据错误。
5. **最终联合验收**：仍需同一次真实页面操作得到 `code=0` 报告、真实 LLM、真实 MySQL 新增记录及字段一致，随后证明实时全链路稳定通过。当前 PR 保持草稿，不自动合并 main。

冻结包的 `metadata.json` 必须包含 `stock_code=600519`、实际起止日期、带时区抓取时间、`adjust=qfq`、`rows=403`、四个必需文件（行情、日历、股票快照、MySQL 回读）的相对路径与 SHA-256、完整默认 `quant_config`，以及已确认的 `quant_expectations`：评分 33、订单 24、曲线 403 点、总收益率 `-0.09165774117956027`、最终资产 `90834.22588204397`。新闻文件可选；提供时同样必须有 SHA-256。任一文件逃逸包目录、哈希不符、日期/代码/行数/参数不一致，都在创建验收库前失败。
