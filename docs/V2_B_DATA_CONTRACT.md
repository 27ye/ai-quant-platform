# V2 B 侧数据与接口契约（M0 提案）

> 依据 `docs/V2_DEVELOPMENT_PLAN.md`；本文是 **B 在第 1–2 天的产出**，供 A/C/D 评审后在 `API_SPEC.md` / `DATABASE_DESIGN.md` 定稿。
> 基线：`main` = `8062599`（V1 已合并，含 A 前端与 D 验收工具）。所有"拟新增"字段均**尚未实现**。

## 1. 现状核对（B 负责范围的起点）

| 范围 | 现状（已核对代码） | V2 要做的事 |
|---|---|---|
| 搜索 | `StockService.search_stocks` → Provider `ak.stock_zh_a_spot_em()`，**每次请求都在线拉全市场快照**；上游故障即 `50001` | 改为「同步落库 + 本地搜索」，在线搜索不再依赖数据源 |
| 行情 | `MarketDataService.query_daily/sync_daily` 已有行数/覆盖/新鲜度/有效性四条件与交易日历注入；**缺"来源/刷新时间/模式"对外元数据** | 补刷新与来源元数据，新增 data-status 接口 |
| 回测 | `POST /backtests` 只收 `stock_code` + 日期；`BacktestResult` 有摘要列但**无曲线/成交明细**；无写入/查询链路 | 参数白名单入口、预热区间补取、一次性持久化、历史查询 |
| 迁移 | `db/migrations.py` 只有 `create_all(checkfirst=True)` + 版本号；**不会 ALTER 已有列**；`SCHEMA_VERSION = 1` | 显式分步增量迁移，空库/V1 库/重复执行都可恢复 |
| AI | `ai_analysis` 只有 `save`；历史 ID/列表/详情待补（D 主责） | B 负责**配套迁移**（字段由 D1 提供） |

## 2. 数据源阻塞与处置（B 第 1 天产出）

本机实测（低频、无代理）：

| 主机 / 端点 | 结果 | 对 V2 的影响 | 处置 |
|---|---|---|---|
| `push2` / `push2his` / `82.push2` | ❌ 0.5s `RemoteDisconnected`（网络层阻断） | 实时日线仍可能失败 | 保留有限重试 + 同源回退；失败一律 `50001` |
| `push2delay` `/api/qt/stock/get` | ✅ 200 | — | 股票信息回退（已实现） |
| `push2delay` `/api/qt/clist/get` | ✅ 200，`total≈5900`，**单页硬上限 100** | 60 页不适合**在线**搜索 | 只用于**离线目录同步**（分页约 60 次） |
| `push2delay` kline | ⚠️ 200 但 `dktotal=0`（限流后恒空） | 长区间回退不可靠 | 空响应抛 `50001`，不伪装成空数据 |
| `search-api-web`（新闻）/ `datacenter-web` | ✅ 200 | — | 保持 |

结论：

1. **B1 的目录同步可以完成**：主站优先，失败时用延迟主机 `clist` 分页拉全表（一次性落库）；在线搜索改为查 MySQL，彻底摆脱该阻塞。
2. **B2 的实时日线仍受上游阻断**：按计划第 6 节，M1 第 3–6 天优先验证；若第 6 天仍不可得，提交阻塞证据与恢复方案，其余人继续固定样本开发。
3. 不增加高频探测频率；**替代数据源（新浪/腾讯）需先验证口径并单列决策**，V2 不默认启用。

## 3. 目录与搜索契约（B1）

### 3.1 新增表 `stock_catalog_sync`（单行，`id=1`）

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | INT PK | 固定 1 |
| `status` | VARCHAR(20) | `success` / `failed` |
| `last_success_at` | DATETIME NULL | **仅成功时更新** |
| `last_attempt_at` | DATETIME | 每次尝试都更新 |
| `row_count` | INT | 最近成功同步的目录行数 |
| `source` | VARCHAR(200) | 实际使用的来源（主站或延迟主机） |
| `last_error` | VARCHAR(500) NULL | 失败原因（截断），供 data-status 暴露 |

### 3.2 同步规则

- 成功判定：拉到的目录 **≥ 1000 条**且 `stock_code` 唯一（防止**部分目录被标记为完整**）。
- 失败：不改 `last_success_at`；`status=failed`；接口/脚本如实返回 `50001`。
- 新增脚本 `scripts/sync_stock_catalog.py`（手动触发，不自动高频跑）。

### 3.3 搜索语义（路径与响应结构不变）

```http
GET /api/v1/stocks/search?keyword=茅台
```

```json
{
  "code": 0,
  "message": "success",
  "data": [
    { "stock_code": "600519", "stock_name": "贵州茅台" }
  ]
}
```

| 目录状态 | 行为 | 失败语义 |
|---|---|---|
| 已成功同步 | **只查 MySQL**，按代码或名称子串匹配，最多 50 条 | 无匹配 → 空数组（真实无匹配） |
| **已成功同步、但最近一次刷新失败** | **仍只查 MySQL**，用上一次成功留下的目录 | 刷新错误如实记在 `last_error`（`/data-status` 可见）；搜索照常可用 |
| **从未成功同步** | **不调用 Provider** | `50006`（HTTP 503，`stock catalog not synced`），可重试 |
| 已同步但查询期数据库异常 | — | `50002` |

> **为什么不再回退实时 Provider**：一次全市场快照实测约 34 秒（5915 行），而 Provider 的重试预算是 4 秒，
> 旧回退**永远不可能成功**，只会在约 4.7 秒后抛 `50001`，把「目录还没初始化」误报成「数据源故障」。
>
> **为什么"刷新失败"不等于"从未同步"**：`mark_failure` 不改 `last_success_at` / `row_count`，
> 目录数据仍然完整可用。把这两种状态混为一谈，会让一次瞬时刷新失败把本来能用的搜索打成 `50006`。
> 可用性判定因此基于「曾经成功同步过且行数达标」，而不是「最近一次尝试成功」。

## 4. 数据状态契约（B2，拟新增）

```http
GET /api/v1/stocks/{stock_code}/data-status
```

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stock_code": "600519",
    "catalog": {
      "synced": true,
      "last_success_at": "2026-09-14T12:00:00+08:00",
      "row_count": 5913,
      "source": "push2delay.eastmoney.com/api/qt/clist/get"
    },
    "kline": {
      "mode": "cache",
      "source": "mysql:stock_daily",
      "rows": 403,
      "first_trade_date": "2025-01-02",
      "last_trade_date": "2026-08-31",
      "last_refreshed_at": "2026-09-14T12:03:00+08:00",
      "coverage": "known",
      "expected_trading_days": 403,
      "last_attempt_at": "2026-09-15T09:27:53+08:00",
      "last_error": "StockDataProviderError: ...",
      "freshness": { "status": "stale", "stale_days": 14, "max_stale_days": 3 }
    },
    "as_of": "2026-09-14T12:05:00+08:00"
  }
}
```

字段规则：

- `kline.mode` ∈ `live`（实时抓取后落库）| `frozen`（冻结包导入）| `unknown`（**无刷新元数据，不猜**）。
- `kline.freshness.status` ∈ `fresh` | `stale` | `unknown`（无可用 bar）。
- `last_refreshed_at` 取**最近一次成功**刷新时间（无元数据时退回 bars 的最后写入时间）；`last_attempt_at`/`last_error` 反映**最近一次尝试**，失败不会抹掉成功信息。
- `coverage` 与 `expected_trading_days` 来自**交易日历**；日历无法证明时必须返回 `unknown`，**不得用自然工作日顶替**。
- 状态必须与本次请求实际使用的数据一致，不能单独用来证明历史报告来源（报告/回测仍携带自身快照元信息）。

## 5. 回测契约（B3 / B4，扩展）

### 5.1 请求语义矩阵（与计划 §5 一致）

| 请求形态 | `semantics_version` | 行为 |
|---|---|---|
| 省略 `parameters`（含只传 stock_code/日期） | `v1_legacy` | 保持 V1 默认计算与区间行为 |
| 显式 `parameters: {}` | `v2_windowed` | 默认金融参数，**零初始持仓**，区间前数据仅预热 |
| 显式非空 `parameters`（含只改 `initial_cash`） | `v2_windowed` | 白名单覆盖，其余取默认 |
| `parameters: null` 或含未知字段 | — | **取数前**拒绝，`40001`，不产生成功记录 |
| 白名单字段**值**显式 `null`（如 `{"ma_long_period": null}`） | — | **取数前**拒绝，`40001`，不产生成功记录（2026-09-16 按 C 实测补充） |

- Schema 必须保留**字段存在性**，不能用默认空对象抹掉「缺省」与「显式空对象」的区别。
- **字段值显式 `null` ≠ 省略**：只有省略字段才使用默认值。Pydantic 用 `model_fields_set`
  记录存在性，`explicit_null_fields()` 据此拒绝显式 `null`——此前 `provided_overrides()`
  丢掉 `None`，把显式 `null` 当成省略并成功落库。
- 新窗口请求未传日期时，B 先解析为明确的默认日历区间，再补取预热数据；**解析后的实际区间必须展示并保存**。
- B 只透传 C1 白名单字段，不整包透传 `QuantConfig`。
- **C 侧异常按真实类别映射**：C 的 `BacktestParameterError`（`ValueError` 子类，不是
  `ApplicationError`）→ `40001`；C 的 `InsufficientDataError` → `40003`；**其余异常保持 `500`**，
  不伪装成用户参数错误。此前 `validate_backtest_window` 的异常逃逸成纯文本 `500`。

### 5.2 响应与历史接口

- `POST /api/v1/backtests` 响应新增：`backtest_id`、`semantics_version`、`effective_parameters`、`warmup_start_date`、`data_meta`。
- `effective_parameters` 在 `v2_windowed` 下**只含白名单五字段**（`ma_short_period` / `ma_long_period` / `initial_cash` / `transaction_cost` / `slippage`）：其余算法配置归 C，B 不回填、不覆盖（例如基准口径 `first_open_to_last_close_no_cost`）。`v1_legacy` 仍保存完整 V1 配置。
- `data_meta` 分别记录 **B 的 `frame_digest`**（交给 C 的那份数据帧摘要）与 **C 的 `c_data_hash`**，两者互不替代；此前把 B 的帧摘要命名为 `data_hash` 与该口径冲突，已改名。
- 参数与日期的校验**在取数之前**完成；C 的 `resolve_backtest_request` 失败转成 `40001`，**不吞掉校验异常**。
- C 的完整结果（`algorithm_version`、`warmup`、`initial_equity`、`execution_assumptions`、`input_snapshot` 封套、`data_hash`（**C 的输入快照哈希**）等）**原样保存**，历史详情从该快照读取而不是用舍入后的摘要列重拼；`GET /backtests/{id}?include_c_result=true` 返回完整封套。
  - **迁移 v8 起改为存原文文本**（`c_result_text` LONGTEXT）：MySQL 的 JSON 列把数值叶子归一化到约 15 位有效数字（实测 `99633.35582084299` → `99633.355820843`，C 在九组记录上量到 1439 处 1 ULP），无法满足"原样保存"契约。文本列保存 B 写出的确切字节，读回解析为对象，**API 结构不变**。
  - 详情新增 `c_result_exact`：`true` = 来自无损文本列；`false` = v8 之前由 JSON 列保存的旧记录（仍可读，数值已被 MySQL 归一化）。旧记录在 v8 迁移中由 JSON 列回填到文本列，保留当时的值。
- C 的 V2 入口不可用时返回 **`50004 backtest error`** 且**不产生记录**，绝不回退到旧 `run_backtest` 再把结果标成 `v2_windowed`；省略 `parameters` 的 `v1_legacy` 路径行为不变。
- 新增 `GET /api/v1/backtests?stock_code=&page=&page_size=`（`created_at DESC, id DESC`，`page_size` 默认 20、最大 100）。
- 新增 `GET /api/v1/backtests/{backtest_id}`：返回**保存时的**参数、指标、曲线、成交与数据元信息；**GET 不取数、不重算**。
- 未知 `backtest_id` → HTTP **404** + 新业务码 **`40005 backtest not found`**（不复用 `40002 股票不存在`）。
- 持久化：同一次计算**一次性**保存摘要 + 曲线 + 成交明细；任何一步失败回滚，**不返回成功**。

## 6. 迁移清单（B4）

`schema_version` 由 1 → 8，分步、事务内执行、**成功后才写入版本号**。

**新增表**：

| 版本 | 表 | 用途 |
|---|---|---|
| v2 | `stock_catalog_sync` | 目录同步元数据（见 3.1） |
| v3 | `stock_daily_sync` | 每只股票的行情来源元数据（mode / source / 行数 / 区间 / 最近成功与最近尝试 / 最近错误），供 data-status 与诊断使用 |

**v4 新增列（回测快照，字段以 C1 定稿为准）**：

| 表 | 列 | 用途 |
|---|---|---|
| `backtest_result` | `semantics_version` VARCHAR(20) | `v1_legacy` / `v2_windowed` |
| | `strategy_version` VARCHAR(20) | 算法版本 |
| | `equity_curve` JSON | 完整曲线（不靠旧 DECIMAL 摘要列重拼） |
| | `orders` JSON | 成交明细 |
| | `warmup_start_date` DATE | 预热区间起点 |
| | `data_meta` JSON | 来源、模式、行数、实际截至日；`frame_digest`（B）与 `c_data_hash`（C）**分开记录** |
| | `effective_parameters` JSON | `v1_legacy`：完整 V1 配置；`v2_windowed`：**仅白名单五字段**（其余算法配置归 C） |

**v5 新增列（AI，字段由 D 提供，B 写迁移）** —— 已按 D 的 `feature/v2-d-report-history` 落地：
`ai_analysis` 补 `context_snapshot` JSON、`context_hash` CHAR(64)、`source_mode` VARCHAR(16)、
`data_as_of` DATETIME、`prompt_version` VARCHAR(32)、`context_schema_version` VARCHAR(32)、
`output_schema_version` VARCHAR(32)。

**v6 / v7 新增列（C 对接，字段按 PR #10 评审）**：

| 表 | 列 | 用途 |
|---|---|---|
| `backtest_result` | `input_snapshot` JSON（v6） | 送进 C 的逐行输入：最后 `long` 条预热 + 区间内全部行情 |
| `backtest_result` | `c_result` JSON（v7） | C 的完整结果；**v8 起不再写入**，仅作 pre-v8 记录的读回退 |
| `backtest_result` | `c_result_text` LONGTEXT（v8） | C 完整结果的**原文 JSON 文本**，无损保存；迁移时由 `c_result` 回填旧记录 |

> **版本号冲突提示**：D 的分支曾独立把上述 AI 列记为「v2」，与本文 v2（`stock_catalog_sync`）语义不同。
> 统一后以 B 的分步序列为准（AI 列 = v5），并增加**收敛步骤**：版本号步骤执行完毕后，再用同一批
> 幂等步骤跑一遍，确保「版本行与实际结构不一致」的库也能补齐缺失表/列，不会静默缺表。

迁移规则：

- 既有 `create_all` 不能替代 ALTER/数据迁移；每个版本一个步骤，步骤内事务，失败**不记录**版本号，重跑可恢复。
- 先在**带 V1 数据的独立测试库**演练升级，验证旧数据保留与旧记录读取兼容；不自动删除旧数据。
- 旧 V1 记录缺曲线/上下文时，详情返回兼容结构并标注「历史快照缺失」，**不补造**。

## 7. 验收映射（B 主责）

| 编号 | B 的证据形式 |
|---|---|
| V01 | 600519 / 000001 / 300750 各 ≥ 60 行日线的取数记录（源、区间、行数、哈希） |
| V02 | 两轮低频取数（间隔 ≥ 30 分钟）+ 缓存回读；新闻成功有值或如实为空 |
| V03 | 注入超时/畸形数据/数据库失败：错误码明确（`50001` / `50002`），页面可见，重试有界 |
| V04 | `semantics_version` 语义矩阵的接口级回归（B 侧部分） |
| V05 | 同股票两组参数各产生独立 `backtest_id`；重启后可查；GET 不重算 |
| V09 | 空库初始化 / V1 库升级 / 重复迁移 / 旧记录缺快照兼容 |
| V10 | 多股票浏览器完整分析中的后端与落库部分 |

## 8. 待评审问题（请在契约 PR 中回复）

1. 目录同步的完整性判定：用「≥1000 条」还是「与上游 `total` 一致」？
2. 同步触发方式：仅手动脚本，还是启动时懒同步 + 手动？倾向**仅手动 + 显式状态暴露**。
3. `40005 backtest not found` / **`40006 report not found`** 的分工（已按此实现，API_SPEC 已同步）：
   两个「资源不存在」语义不复用同一业务码。
4. 历史快照 JSON 精度策略：是否按现有 4/2/6 口径落库，回读是否再舍入。
5. C1 白名单最小字段集与预热有效行数的正式定义（B3 依赖）。
