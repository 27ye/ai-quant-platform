# V2 AI 报告历史验收记录

验收日期：2026-09-15

## 已通过

### 离线回归

- 全量 Pytest：通过。
- `python -m compileall -q backend scripts`：通过。
- `git diff --check`：通过，无空白错误。
- 覆盖生成、一次修复、失败回滚、快照哈希、分页排序、股票过滤、旧记录、损坏快照和历史读取零外部调用。

### 真实 LLM

- 模型：`deepseek-v4-flash`。
- JSON 连通性探针：通过。
- 冻结 600519 数据生成两份真实报告：通过，无修复调用。

### 真实 MySQL 8

- 版本：MySQL 8.0.41，独立监听 `127.0.0.1:3307`。
- V1 → V2 增量迁移：通过，schema version 为 2，V1 旧报告保留。
- 冻结数据联合验收库：`ai_quant_v1_acceptance_20260915_010252_056531`。
- 两份报告 ID：1、2，列表顺序为 2、1。
- 应用重新创建后，列表和详情仍可读取。
- 历史列表与详情期间 LLM 调用数：0。
- 旧 V1 报告返回 `snapshot_status=legacy_missing`、`source_mode=unknown`、`context_snapshot=null`。

### 冻结数据

- 股票：600519。
- 行情行数：403。
- 默认量化评分：33。
- `source_mode=frozen`。
- API 响应、MySQL 正文、版本字段、上下文快照和 SHA-256 哈希对账通过。

## 待联合验收

- 实时行情验收：AKShare 本次返回 `50001 data provider error`；真实 LLM 与 MySQL 已分别验证通过，待 Provider 恢复后重跑实时链路。
- 浏览器报告历史流程：等待 A 的报告列表和详情页面合入后执行。当前 D 的历史 API 已通过真实 MySQL 重启回读和自动化 API 测试。
