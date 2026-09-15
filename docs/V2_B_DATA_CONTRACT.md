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
| 从未成功同步 | 回退 Provider 实时搜索 | Provider 失败 → `50001`（**不得**当作"无匹配"） |
| 已同步但查询期数据库异常 | — | `50002` |

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

- Schema 必须保留**字段存在性**，不能用默认空对象抹掉「缺省」与「显式空对象」的区别。
- 新窗口请求未传日期时，B 先解析为明确的默认日历区间，再补取预热数据；**解析后的实际区间必须展示并保存**。
- B 只透传 C1 白名单字段，不整包透传 `QuantConfig`。

### 5.2 响应与历史接口

- `POST /api/v1/backtests` 响应新增：`backtest_id`、`semantics_version`、`effective_parameters`、`warmup_start_date`、`data_meta`。
- 新增 `GET /api/v1/backtests?stock_code=&page=&page_size=`（`created_at DESC, id DESC`，`page_size` 默认 20、最大 100）。
- 新增 `GET /api/v1/backtests/{backtest_id}`：返回**保存时的**参数、指标、曲线、成交与数据元信息；**GET 不取数、不重算**。
- 未知 `backtest_id` → HTTP **404** + 新业务码 **`40005 backtest not found`**（不复用 `40002 股票不存在`）。
- 持久化：同一次计算**一次性**保存摘要 + 曲线 + 成交明细；任何一步失败回滚，**不返回成功**。

## 6. 迁移清单（B4）

`schema_version` 由 1 → 3，分步、事务内执行、**成功后才写入版本号**。

**新增表**：

| 版本 | 表 | 用途 |
|---|---|---|
| v2 | `stock_catalog_sync` | 目录同步元数据（见 3.1） |
| v3 | `stock_daily_sync` | 每只股票的行情来源元数据（mode / source / 行数 / 区间 / 最近成功与最近尝试 / 最近错误），供 data-status 与诊断使用 |

**v2 新增列（回测快照，字段以 C1 定稿为准）**：

| 表 | 列 | 用途 |
|---|---|---|
| `backtest_result` | `semantics_version` VARCHAR(20) | `v1_legacy` / `v2_windowed` |
| | `strategy_version` VARCHAR(20) | 算法版本 |
| | `equity_curve` JSON | 完整曲线（不靠旧 DECIMAL 摘要列重拼） |
| | `orders` JSON | 成交明细 |
| | `warmup_start_date` DATE | 预热区间起点 |
| | `data_meta` JSON | 来源、模式、行数、实际截至日、数据哈希 |
| | `effective_parameters` JSON | 本次实际生效参数（含默认值回填） |

**v2 新增列（AI，字段由 D1 提供，B 写迁移）**：`ai_analysis` 计划补 `prompt_version`、`schema_version`、`context_snapshot` JSON、`data_as_of`、`source_mode` 等，**待 D1 定稿后并入同一迁移步**。

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
3. `40005 backtest not found` 是否接受；D 的 AI 历史是否复用同风格（如 `40006 report not found`）。
4. 历史快照 JSON 精度策略：是否按现有 4/2/6 口径落库，回读是否再舍入。
5. C1 白名单最小字段集与预热有效行数的正式定义（B3 依赖）。
