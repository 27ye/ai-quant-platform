# D：V1 AI 集成与验收记录

更新日期：2026-09-09。此记录区分代码完成、自动化测试和真实外部验收，不能据此宣称 V1 已全部交付。

## 版本与边界

- 独立分支：`feature/V1-ai-context-integration`；已同步 `origin/main` 的 `9fb1acf` 与 B PR #7 的 `35a0482`。没有合并远端 main。
- 同步前的用户修改、未跟踪文档及本轮代码均有保留的 Git stash 检查点；未删除备份。
- D 只改 AI 上下文、依赖、Prompt、验收脚本及对应测试/说明；未修改 C 算法、A 前端源码或 B 的数据服务实现。
- 生产 `POST /api/v1/ai/analyze` 的请求/响应不变，MySQL 是必需依赖；测试中的 SQLite、内存报告仓库不是生产降级。

## 已实现

- `get_data_provider` / `get_stock_service` / `get_market_data_source` 注入真实 B 服务。行情、新闻、AI 报告仓库使用同一个请求级 Session。
- 同一请求共享 `StockQuantAnalysisAdapter`：一次 `query_daily`、一次 C 量化流水线，行情快照取最新日期；多个投影复用同一结果，不跨请求复用。
- D 不再次舍入、不自行补行情、不用工作日推算交易日。沿用价格 4 位、amount 2 位、百分比 6 位和整数 volume。
- 行情参数为 `min_rows=60`、`max_stale_days=3`、`max_gap_days=15`。B 新增的交易日历可注入能力已同步，但当前 D 不注入未经验证的日历，默认覆盖未知时保守重拉。
- `NewsService` 替换空新闻占位，最多 10 条、默认 TTL 6 小时；Provider 正常返回空与异常严格区分，旧缓存新闻保留发布时间。
- 保持参数/股票不存在/不足/数据源/数据库/量化/AI 错误码；输出校验最多修复一次，写入失败回滚。

## 本轮证据

| 检查 | 实际结果 | 不能据此推断的结论 |
|---|---|---|
| `python -m pytest tests -q` | 197 passed，9.46 秒 | 不是 C 未提交的 11 个补充用例已全部复验 |
| `npm run build`（frontend） | 通过；仍有大于 500 kB 的包体积提示 | 不代表 A 已完成真实页面联调 |
| `git diff --check` | 通过 | 不替代运行时验收 |
| 真实 LLM `--llm-only` | JSON 连通性通过，模型 `deepseek-v4-flash` | 不代表 600519 报告、Schema 或落库验收通过 |
| 真实 `600519` 无 DB 冒烟 | 数据源 `50001`，未进入 LLM | 不标记实时 AKShare 链路成功 |
| 独立 MySQL `--mysql` | 认证错误 1045，尚未创建验收库 | 未执行真实 MySQL 迁移、入库或回读验收 |

新增 API 集成测试只替换 Provider、LLM HTTP 与测试数据库边界，保留真实依赖、量化、路由和报告仓库。覆盖首次查询/缓存回读完整量化一致性、缺段缓存重拉、新闻缓存/刷新/回退、空新闻、舍入后零价格、LLM 鉴权/限流/超时/非法输出与数据库回滚。行情和新闻样本均明确标记为模拟数据。

## 安全复验

从项目根目录使用项目虚拟环境执行：

```powershell
python scripts/validate_ai_analysis.py --stock-code 600519
python scripts/validate_ai_analysis.py --llm-only
python scripts/validate_ai_analysis.py --mysql --stock-code 600519
```

`--mysql` 必须在新进程运行：先确认本机地址、新库名不存在，再创建 `ai_quant_v1_acceptance_<UTC时间戳>`；切换进程环境变量之后才导入后端数据库引擎、执行 B 迁移、调用正式 AI 路由并核对 `ai_analysis`。不改 `.env`，不复用或删除已有库，不写现有 `ai_quant`。异常只输出公开类型/业务码/数字驱动错误码，不输出原始连接串、密码或响应细节。

当前生效的 MySQL 密码为空。应由用户在本机配置可用凭据及隔离测试库权限；不要在聊天或 PR 中发送密码。不执行重置密码或修改现有数据库账号等操作。

## 联合验收待办

1. B 提供冻结真实 600519 数据文件、真实交易日历及元数据：实际区间、qfq 参数、抓取时间和时区、行数、SHA-256；C 提供保留的 11 个补充用例及对应新 SHA 的结果。
2. 本机凭据就绪后创建唯一隔离库，完成真实冻结样本的完整量化一致性和 AI 报告落库回读验证。
3. B 的 `scripts/verify_frozen_mysql.py` 已同步，但其 CLI 固定目标为 `ai_quant_test`，不能直接拿来替代本次唯一隔离库流程；应复用其纯校验函数，或由 B 协调目标库参数。当前尚未运行该 CLI，未创建/改动 `ai_quant_test`。
4. B 的舍入后有效行数不足时，是否能进一步扩窗补足的边界继续由 B/C 确认；D 不放宽有效性或数量要求来掩盖问题。
5. 实时数据恢复后重跑完整 600519 链路，由 A 关闭相应 Mock 后做页面验收。冻结样本验证、LLM 连通性和实时冒烟分别记录。

在这些项完成前，D PR 保持草稿/待联合验收，不自动合并 main。
