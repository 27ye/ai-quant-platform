# V3 D 角色：报告导出与 AI 回测解读验收

## 候选范围

- 生产代码候选：`6c9ca52`（rebase 到 `origin/main` `10283b0` 含 B #19 v9 迁移 + B #21 strategy 接线后的完整树；含两轮 C 复核修复，见末节）
- 后端提交：`44516e1`（AI ORM/Service/上下文，v9 迁移已移除，由 B #19 独占）
- 分支：`codex/v3-d-report-workflow`
- 范围：已保存的 `v2_windowed` MA 精确回测 → AI 解读 → 报告历史 → Markdown 导出。
- 未纳入：MACD、追问、最新行情/新闻补充、自动调参和新页面布局。

## 自动化检查

| 检查 | 结果 |
|---|---|
| 后端全量 | `630 passed`（rebase 到含 B #19/#21 的 main 后；修复前 `596`，两轮修复与去重后 `630`） |
| 定向 AI/迁移 | `91 passed` |
| Python 编译 | `python -m compileall -q backend scripts` 通过 |
| C/D 历史兼容 | `validate_c_ai_history_compatibility.py` 通过；SQLite + 合成行情 + 假 LLM |
| 前端类型 | `vue-tsc --noEmit` 通过 |
| 前端生产构建 | Vite 构建通过；仅保留现有大 chunk 警告 |
| Markdown 格式器 | standard、custom_backtest、legacy_missing 三种样例通过；包含完整两类 SHA-256 |
| diff | `git diff --check` 通过 |

custom 新增测试覆盖：严格请求类型、不存在/跨股票/不支持/损坏回测、C 输入哈希和曲线完整性、Prompt/快照/上下文哈希一致、最多一次修复、写库回滚、旧报告兼容，以及 custom 生成时 Provider/News/Quant 不构造、历史 GET 时 LLM 也不构造。

## MySQL 8.0.41

1. 独立库 `ai_quant_v1_acceptance_20260922_073913_688951`：V1 → v9 通过，旧 AI 报告保留。
2. 独立库 `ai_quant_v1_acceptance_20260922_074258_852432`：
   - 模拟 v9 DDL 中断（`analysis_mode` 已在、`backtest_id` 缺失、版本仍为 8），重跑恢复到 v9。
   - 保存精确 MA 回测 `#1`，生成 custom 报告 `#1` / `#2`。
   - 两份报告的 C 输入哈希均为 `b61a11d21ff0d91b02c04c46097cd79463865a80c5f4979177cd9a653874a9bd`；上下文哈希为 `24bde4d1c737759eff9f9e7dcb972db9f8e6433df5a29eb40d61e8fe83cb1ffd`。
   - 重新创建 App 且将 LLM key 设置为空后，列表与详情仍成功，顺序为 `#2, #1`，内容与生成响应一致。
3. 上述 custom 生成使用本地确定性 LLM 替身；它证明真实 MySQL 事务、快照和历史链路，不代表真实 LLM 验收。

## 关闭 Mock 的浏览器流程

- 验收库：`ai_quant_v1_acceptance_20260922_074641_480867`。
- 前端全局及分接口 Mock 全部为 `false`，后端使用 MySQL 和本地确定性 LLM 替身。
- 在回测 `#1` 详情双击“AI 解读本回测”，数据库只产生一份报告。
- 报告详情正确显示 custom 模式、回测 ID、保存事实表、完整 C 输入哈希和固定新闻边界，不显示股票多空评分。
- 历史列表标记“回测解读 / 回测 #1”；切换到 `000001` 路由后返回报告 `#1`，报告正文、事实和 C 哈希未被当前股票覆盖。
- 点击“导出 Markdown”实际生成 `ai-report-600519-1-2026-09-22.md`（1579 字节）；文件包含完整 context SHA-256、完整 C input SHA-256、保存事实表和新闻边界。
- 浏览器 console 错误为 0。

## 真实 DeepSeek LLM（用户明确授权后执行）

- 目的地：`https://api.deepseek.com/chat/completions`，模型 `deepseek-v4-flash`；用户于 2026-09-22 对“具体目的地 + 具体载荷”明确授权。
- 环境：全新隔离 MySQL 8.0.41 实例（127.0.0.1:3307），数据库 `ai_quant_v1_acceptance_20260922_082650_804723`，V1 → v9 迁移后执行。
- 种子：两条不同的精确 MA 回测 —— `#1` 默认参数（5/20）、`#2` `ma_short_period=8 / ma_long_period=25`，C 输入哈希不同。
- 生成：`POST /ai/analyze` 携带各自 `backtest_id`，真实 LLM 产出报告 `#1` / `#2`。断言全部通过：`analysis_mode=custom_backtest`、`backtest_id` 匹配、`quant_score=null`、新闻边界披露、Prompt/Context 版本 `v3.backtest.1`、`source_mode=unknown`、正文各段非空、上下文哈希与 C 输入哈希互相独立（报告 `#1`：context `0c87be8f…7583ee`、data `325782da…14f8`；报告 `#2`：context `8e8ba445…9b3f16`、data `132b54ff…67fe2`），且数据库记录与响应逐字段一致。
- 重启回读：新进程、`LLM_API_KEY` 置空后，列表顺序 `#2, #1`，两份详情与生成响应完全一致；LLM 未被构造（若构造会因空 key 立即失败）。

## C 复核后的修复（01dbe2c，rebase 前为 7530d01）

C 复核（PR #22 review5277425787）发现：保存结果的 `total_return`、`max_drawdown`、`trade_count` 与保存曲线/订单矛盾时（输入哈希仍合法），原实现仍调用 LLM 并生成报告。修复在 LLM 调用前新增三项保存字段一致性校验（`final_equity/initial_cash-1`、`min(0.0, 曲线最小值)`、卖出笔数，浮点 rel 1e-12），矛盾按数据损坏拒绝：HTTP 500 / 50002、LLM 0 调用、报告 0 条。损坏矩阵新增三个“类型合法但数值矛盾”用例。

第二轮修复（`6c9ca52`，C review5278362407）：上述除法在 `initial_cash=0` 的损坏记录上会先抛未捕获的 `ZeroDivisionError`（`ArithmeticError` 子类，不在 except 元组内），API 退化为纯文本 500。现于除法前校验分母为非 bool、有限、正数，否则 `ValueError` → JSON 50002；损坏矩阵新增零资金用例。

真实 LLM 证据针对未改动的正常链路，继续有效；受影响验收（矛盾拒绝路径、零资金路径与全量回归）已在 rebase 后重跑。

## Rebase 与 v9 去重（44516e1 之后）

B #19（v9 迁移）与 B #21（strategy 接线）已并入 `origin/main`，本分支 rebase 到 `10283b0`：移除 D 侧重复的 `_migration_v9` 与两个 v9 测试，保留 B 版迁移与其五个专项测试；`test_c_result_lossless.py` 采用 B 的 `version >= 8` 回退修正；`DATABASE_DESIGN.md` 采用 B 的列注释与 V2/V3 段落（保留 D 侧 v5–v9 版本表行）；`API_SPEC.md` 同时保留 B21 的 strategy 请求段与 D 的 AI 段。全量 629 passed。

## 尚未通过的外部门禁

- C 需按新完整 SHA 复验矛盾拦截（正常链路 C 已验证通过）。
- A 需复核公共类型、按钮与 custom 展示；B 需复核 v9 幂等迁移和读取路径；C 需复核 custom context 中投影的精确数值和两类哈希的语义。
- v9 重复实现已定来源并落地：B PR #19 为唯一迁移（已合并），D 侧迁移实现已移除。

PR 在 A/B/C 复核完成前保持 Draft。此后如修改生产代码，必须在新的完整 SHA 上重跑受影响验收。
