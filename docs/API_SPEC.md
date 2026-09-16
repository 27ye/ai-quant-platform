# AI 智能量化投研平台 V1 API 规范

> API Version：V1  
> Base URL：`/api/v1`

## 1. 通用返回格式

成功：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

错误：

```json
{
  "code": 40001,
  "message": "invalid parameter",
  "data": null
}
```

通用规则：

- JSON 字段统一 `snake_case`
- 日期统一 `YYYY-MM-DD`
- 股票代码统一 6 位字符串
- 百分比统一使用小数，例如 `0.0125` 表示 1.25%

## 2. 健康检查

```http
GET /api/v1/health
```

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "ok"
  }
}
```

## 3. V1 计划 API

以下接口属于 V1 主链路，但不要求在基础工程阶段全部实现：

```text
GET  /api/v1/stocks
GET  /api/v1/stocks/search
GET  /api/v1/stocks/{stock_code}
GET  /api/v1/stocks/{stock_code}/kline
GET  /api/v1/stocks/{stock_code}/indicators
GET  /api/v1/stocks/{stock_code}/score
GET  /api/v1/stocks/{stock_code}/news
POST /api/v1/backtests
GET  /api/v1/backtests/{backtest_id}
POST /api/v1/ai/analyze
```

## 4. 股票搜索与信息

### 4.1 股票搜索

```http
GET /api/v1/stocks/search?keyword=茅台
```

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "stock_code": "600519",
      "stock_name": "贵州茅台"
    }
  ]
}
```

> `keyword` 为空返回 `40001`；按代码或名称子串匹配，最多返回 50 条。
>
> **V2 起**：搜索改为查询本地股票目录（MySQL `stock_basic`），由
> `scripts/sync_stock_catalog.py` 低频同步；路径与响应结构不变。
> 已成功同步时**不再调用全市场 Provider**，无匹配返回空数组；
> 从未成功同步时回退实时 Provider，其失败仍返回 `50001`（不伪装成"无匹配"）；
> 目录查询期数据库异常返回 `50002`。同步状态见 4.4。

### 4.2 股票信息

```http
GET /api/v1/stocks/{stock_code}
```

返回（`StockBasicSchema`）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stock_code": "600519",
    "stock_name": "贵州茅台",
    "industry": "酿酒行业",
    "total_market_cap": 123456789000.0,
    "float_market_cap": 90000000000.0
  }
}
```

> 股票代码必须为 6 位字符串，非法返回 `40001`；数据源异常返回 `50001`。

### 4.3 股票新闻

```http
GET /api/v1/stocks/{stock_code}/news?limit=10
```

返回（`StockNewsSchema` 列表，按 `publish_time` 倒序优先）：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "stock_code": "600519",
      "title": "贵州茅台发布公告",
      "summary": "……",
      "source": "东方财富",
      "publish_time": "2026-08-31 09:30:00",
      "url": "http://finance.eastmoney.com/a/xxx.html"
    }
  ]
}
```

- `limit` 默认 10，允许 1–50，越界返回 `40001`。
- 数据源为东方财富个股新闻（AKShare `stock_news_em`）；服务先查 MySQL `stock_news`，缓存为空时从 AKShare 拉取并 Upsert，再返回。
- 返回结果按 `publish_time` **倒序**（最新在前），`publish_time=null` 排在最后，再按 `limit` 截取。
- `publish_time` 为 ISO 8601 字符串，缺省为 `null`。
- 非法股票代码返回 `40001`；数据源异常返回 `50001`；数据库异常返回 `50002`。

### 4.4 数据状态（V2 新增）

```http
GET /api/v1/stocks/{stock_code}/data-status
```

返回该股票的**目录状态 + 行情来源/覆盖/新鲜度**（`StockDataStatusSchema`）：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stock_code": "600519",
    "catalog": {
      "synced": true,
      "row_count": 5915,
      "last_success_at": "2026-09-15T01:20:23Z",
      "last_attempt_at": "2026-09-15T01:20:23Z",
      "source": "https://push2delay.eastmoney.com/api/qt/clist/get",
      "last_error": null
    },
    "kline": {
      "mode": "live",
      "source": "akshare.stock_zh_a_hist",
      "rows": 403,
      "first_trade_date": "2025-01-02",
      "last_trade_date": "2026-08-31",
      "last_refreshed_at": "2026-09-15T01:44:55Z",
      "coverage": "known",
      "expected_trading_days": 403,
      "last_attempt_at": "2026-09-15T01:44:55Z",
      "last_error": null,
      "freshness": { "status": "stale", "stale_days": 15, "max_stale_days": 3 }
    },
    "as_of": "2026-09-15T01:50:00Z"
  }
}
```

- `kline.mode` ∈ `live`（实时抓取后落库）| `frozen`（冻结包导入）| `unknown`（**无刷新元数据，不猜**）。
- `kline.freshness.status` ∈ `fresh` | `stale` | `unknown`（无可用 bar）。
- `last_refreshed_at` 为**最近一次成功**刷新时间；`last_attempt_at`/`last_error` 反映**最近一次尝试**，失败不会抹掉成功信息。
- `coverage`/`expected_trading_days` 来自**交易日历**；日历无法证明时返回 `unknown`，不得用自然工作日顶替。
- 时间统一为带时区的 ISO 8601（UTC）。
- 代码非 6 位数字返回 `40001`；数据库异常返回 `50002`。

## 5. 股票 K 线

```http
GET /api/v1/stocks/600519/kline?start_date=2025-01-01&end_date=2026-08-31&period=daily
```

V1 固定使用前复权 `qfq`。

### 数据契约（量化模块输入要求）

- 固定 `qfq` 日线；字段统一 `snake_case`；百分比用小数（`0.0125` = 1.25%）；`period` 仅支持 `daily`。
- **数据量保证**：接口适配层（`StockService`）保证返回**至少 60 行清洗后的有效数据**（`DEFAULT_MIN_KLINE_ROWS`）。请求窗口不足时自动向前扩窗（首次空数据也继续扩窗）；扩窗后仍不足则返回业务错误码 `40003`（insufficient stock data）。
- **清洗校验规则**：日期唯一且升序、必需数值列有限、`volume ≥ 0`、OHLC 合法（`high ≥ open/close`、`low ≤ open/close`、`high ≥ low`）。
- 日期 `YYYY-MM-DD`；股票代码 6 位字符串。

返回字段：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "trade_date": "2026-08-28",
      "open": 1400.0,
      "high": 1430.0,
      "low": 1395.0,
      "close": 1420.0,
      "volume": 100000,
      "amount": 142000000.0,
      "turnover_rate": 0.0035,
      "change_pct": 0.012
    }
  ]
}
```

## 6. 技术指标

```http
GET /api/v1/stocks/{stock_code}/indicators
```

返回为**指标序列数组**（按 `trade_date` 升序），每项字段包括 `trade_date`、`ma5`、`ma10`、`ma20`、`ma60`、`macd`、`macd_signal`、`macd_hist`、`rsi14`、`boll_upper`、`boll_middle`、`boll_lower`。计算由 C 的量化模块提供，B 仅在 FastAPI 层包装。

## 7. 量化评分

```http
GET /api/v1/stocks/{stock_code}/score
```

评分字段包括 `stock_code`、`score`、`trend_score`、`momentum_score`、`volume_score`、`risk_score`、`level`、`reasons`。分项上限分别为 40、25、20、15，总分 0-100。

## 8. 回测

```http
POST /api/v1/backtests
```

请求体（`BacktestRequestSchema`，V2 起新增可选 `parameters`）：

```json
{
  "stock_code": "600519",
  "start_date": "2025-01-01",
  "end_date": "2026-08-31",
  "parameters": { "ma_short_period": 5, "ma_long_period": 60, "initial_cash": 100000 }
}
```

**请求语义矩阵（V2）**：

| 请求形态 | `semantics_version` | 行为 |
|---|---|---|
| 省略 `parameters` | `v1_legacy` | 保持 V1 默认计算与区间行为 |
| 显式 `parameters: {}` | `v2_windowed` | 默认金融参数；`start_date` 前数据仅作预热 |
| 显式非空 `parameters` | `v2_windowed` | 白名单字段覆盖，其余取默认 |
| `parameters: null` 或含未知字段 | — | **取数前**返回 `40001`，不产生记录 |

- 白名单（V2 B3）：`ma_short_period`、`ma_long_period`、`initial_cash`、`transaction_cost`、`slippage`；周期为整数且 `2 ≤ period ≤ 120`、`short < long`，资金为正，成本/滑点在 `[0,1)`。**只有这五个字段会转发给 C 的 `resolve_backtest_request` / `run_backtest_request`**（C 会拒绝非白名单字段）；其余算法配置归 C 所有，B 的默认值不得覆盖 C 的口径（例如基准 `first_open_to_last_close_no_cost`）。
- 参数为**严格类型**（C 契约）：拒绝数字字符串（如 `"5"`）、布尔值（`true` 不得当作 1 / 1.0）、浮点周期、`NaN`/`Infinity`、未知字段，一律 `40001` 且在**取数前**拒绝。
- `v2_windowed` 的**单次请求**只要求开始日前 **`ma_long_period` 条**有效预热 bar（默认 20；`long=120` 时 120 条，即「120 条预热 + 1 条区间内行情」即可，**不要求 121 条**）；预热不足或无区间内行情返回 `40003`。**验收数据包**另有「开始日前 ≥120 条」的覆盖要求（供覆盖全部允许的均线参数），这不是每次请求的门槛。
- **窗口由 C 统一处理**：B 把「预热+区间」整段规范化数据交给 `run_backtest_request`，由 C 选取实际预热与回测窗口并返回**只覆盖回测区间**的曲线与订单（首日订单 `signal_date` 可在最后一个预热日，`execution_date` 必须在区间内）；B 不再自行裁剪。`data_meta.window_owner` 记录当前由谁裁窗口。
- **参数与日期校验在取数之前完成**，且校验异常不被吞掉：C 的 `resolve_backtest_request` 失败会转成 `40001`，`validate_backtest_window` 也在取数前调用。
- **C 的 V2 入口不可用时返回 `50004`，且不产生记录**：此时不得回退到旧 `run_backtest` 并把结果标成 `v2_windowed`。省略 `parameters` 的 `v1_legacy` 路径行为不变。
- `v2_windowed` 会保存**送进 C 的输入快照**：**最后 `long` 条预热 + 区间内全部行情**（不含 B 为扩窗多取的更早历史）。详情默认只返回 `input_snapshot_available` / `input_snapshot_rows`；加 `?include_input_snapshot=true` 返回完整 `input_snapshot`（日期升序、ISO 字符串），供 C 核对。
- **C 的完整结果原样保存**，历史详情从该快照读取 `algorithm_version`、`warmup`、`initial_equity`、`execution_assumptions`、`data_hash`，不用舍入后的摘要列重新拼装。详情默认返回这些字段的平铺视图（`c_result_available`、`c_result_exact`、`c_algorithm_version`、`c_data_hash`、`c_initial_equity`、`c_warmup`、`c_execution_assumptions`、`c_semantics_version`）；加 `?include_c_result=true` 返回完整 `c_result`。
  - **无损存储（迁移 v8）**：C 的完整结果以**原文 JSON 文本**存入 `backtest_result.c_result_text`（LONGTEXT）。MySQL 的 JSON 列会把数值叶子归一化到约 15 位有效数字（实测 `99633.35582084299` 变成 `99633.355820843`），无法原样回读；文本列保存 B 写出的确切字节，读回时解析为对象，**API 结构不变**。
  - `c_result_exact` 表示该封套是否来自无损文本列：`true` = 本次 v8 之后保存的记录；`false` = v8 之前用 JSON 列保存的旧记录（仍可读，但数值已被 MySQL 归一化）。旧记录在 v8 迁移时由 JSON 列回填到文本列，保留其当时的值。
- 参数三种形态保持**互不混淆**：**省略** → `v1_legacy`；**显式 `{}`** → `v2_windowed` 默认参数；**显式 `null`** → `40001`（取数前拒绝）。
- **字段值显式 `null` 也一律 `40001`**：五个白名单字段中任一字段显式传 `null`（如 `{"ma_long_period": null}`）都在**取数前**拒绝，且不产生记录——只有**省略该字段**才使用默认值。此前 Schema 的 `provided_overrides()` 会丢掉 `None`，导致显式 `null` 被当成省略并成功落库，已修正。
- **C 侧校验异常按真实类别映射，不吞服务器错误**：C 的 `BacktestParameterError`（参数不合法、窗口超五年、日期格式等）→ `40001`；C 的 `InsufficientDataError`（窗口内无行情、预热不足）→ `40003`；**其余异常保持 `500`**，不伪装成用户参数错误。
- 响应在 V1 字段之外新增：`backtest_id`、`semantics_version`、`effective_parameters`、`warmup_start_date`、`warmup_rows`、`data_meta`（含请求/实际区间、参与计算行数 `rows`/`rows_in_window`、**B 的 `frame_digest`**、**C 的 `c_data_hash`**、`warmup_required_days`、`delivery_warmup_min_bars`、`window_owner`）、`snapshot_status`。
  - `frame_digest`（B：交给 C 的那份数据帧的摘要）与 `c_data_hash`（C：其自身结果的哈希）**分别记录、互不替代**；此前 data_meta 把 B 的帧摘要命名为 `data_hash`，与该口径冲突，已改名。
- `equity_curve` 固定为 `[{ "trade_date": "YYYY-MM-DD", "equity": 100000.0 }]`，不使用 `value/date/nav` 字段。
- `equity` 表示**账户绝对权益**，默认从 `initial_cash=100000.0` 起；归一化净值 = `equity / initial_cash`，累计收益率 = `equity / initial_cash - 1`。
- 响应同时返回 `stock_code`、`initial_cash`、`final_equity`、`total_return`。计算由 C 的量化模块提供，B 仅在 FastAPI 层包装并保存快照。

### 8.1 回测历史（V2 新增）

```http
GET /api/v1/backtests?stock_code=600519&page=1&page_size=20
GET /api/v1/backtests/{backtest_id}
```

- 列表返回 `{ items, total, page, page_size }`，按 `created_at DESC, id DESC` 稳定排序；`page_size` 默认 20、最大 100，越界返回 `40001`。
- 详情返回**保存时**的参数、指标、三条曲线（`equity_curve`/`benchmark_curve`/`drawdown_curve`）、成交明细与 `data_meta`；**GET 不取数、不重算**。
- 未知 `backtest_id` 返回 HTTP `404` + `40005`（不复用 `40002 股票不存在`）。
- 旧 V1 记录只存了摘要指标，详情返回 `snapshot_status="missing"` 与 `snapshot_missing_reason`，**不用当前行情补造曲线**。
- V2 记录额外返回 C 结果快照的平铺字段（见第 8 节）；`c_result_available=false` 表示该记录没有 C 的结果封套（V1 记录或 C 入口不可用时期的历史数据）。

## 9. AI 综合分析

```http
POST /api/v1/ai/analyze
```

AI Service 内部调用 Stock、Quant、Backtest、News Service，前端只传 `stock_code`。

请求：

```json
{
  "stock_code": "600519"
}
```

成功返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "stock_code": "600519",
    "quant_score": 82,
    "trend": "bullish",
    "summary": "...",
    "technical_analysis": "...",
    "quant_analysis": "...",
    "news_analysis": "...",
    "advantages": ["..."],
    "risks": ["..."],
    "conclusion": "...",
    "model_name": "..."
  }
}
```

字段规则：

- `stock_code` 必须是 6 位字符串。
- `quant_score` 来自 Quant Service，可为 `null`，AI 不得自行计算。
- `trend` 只允许 `bullish`、`neutral`、`bearish`。
- `advantages`、`risks` 为字符串数组。
- 其余分析字段由 LLM 生成，并且必须通过 Structured Output Schema 校验。
- 数据不足时返回 `40003`，LLM 调用或输出校验失败时返回 `50005`。

## 10. 错误码

```text
0        success
40001    invalid parameter
40002    stock not found
40003    insufficient stock data
40004    invalid strategy
40005    backtest not found
50001    data provider error
50002    database error
50003    quant calculation error
50004    backtest error
50005    ai service error
```

> **V2 补充口径**：
> - `40005 = backtest not found`（B）；`40006 = report not found`（D，随 PR #10 落地，勿与 `40005` 互借）。
> - `50004 backtest error` 用于**回测引擎无法服务该请求**：典型是 `v2_windowed` 请求到达但 C 的
>   `run_backtest_request` 不可导入。此时接口明确失败并且**不写入任何回测记录**，绝不回退到旧
>   `run_backtest` 再把结果标成 `v2_windowed`。省略 `parameters` 的 `v1_legacy` 路径不受影响。

## 11. 修改规则

API_SPEC.md 是多人协作契约。修改接口路径、字段名称、百分比格式或响应结构时，必须同步 Schema、Service、前端类型和测试。
