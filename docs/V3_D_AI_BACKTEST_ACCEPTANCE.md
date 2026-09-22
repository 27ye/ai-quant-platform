# V3 D 角色：报告导出与 AI 回测解读验收

## 候选范围

- 生产代码候选：`ea0a0160e33e9ac9d9ee2e2be3ab79573c6611c5`
- 后端/迁移提交：`2aee049707c59c2928bfee31d1281733fb2bec7a`
- 分支：`codex/v3-d-report-workflow`
- 范围：已保存的 `v2_windowed` MA 精确回测 → AI 解读 → 报告历史 → Markdown 导出。
- 未纳入：MACD、追问、最新行情/新闻补充、自动调参和新页面布局。

## 自动化检查

| 检查 | 结果 |
|---|---|
| 后端全量 | `596 passed in 17.93s` |
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

## 尚未通过的外部门禁

- 真实 LLM 未执行。当前配置目的地为 `api.deepseek.com`，模型 `deepseek-v4-flash`；待发送内容是一条已保存的合成 MA 回测上下文，包含股票代码、策略/参数、日期区间、执行假设、历史指标及哈希，不包含 API key、完整日线、成交明细或个人信息。自动审批因该外发未获得对“具体目的地 + 具体载荷”的明确授权而拒绝。
- A 需复核公共类型、按钮与 custom 展示；B 需复核 v9 幂等迁移和读取路径；C 需复核 custom context 中投影的精确数值和两类哈希的语义。

PR 在真实 LLM 和 A/B/C 复核完成前保持 Draft。此后如修改生产代码，必须在新的完整 SHA 上重跑受影响验收。
