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

> `keyword` 为空返回 `40001`；按代码或名称子串匹配（AKShare 全 A 股快照），最多返回 50 条。

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

请求体（`BacktestRequest`）：

```json
{ "stock_code": "600519", "start_date": "2025-01-01", "end_date": "2026-08-31" }
```

**V1：`POST /api/v1/backtests` 直接返回完整回测结果和 `equity_curve`，前端不需要再按 `backtest_id` 查询。** `GET /backtests/{id}` 待曲线持久化方案确定后再完善。

- `equity_curve` 固定为 `[{ "trade_date": "YYYY-MM-DD", "equity": 100000.0 }]`，不使用 `value/date/nav` 字段。
- `equity` 表示**账户绝对权益**，默认从 `initial_cash=100000.0` 起；归一化净值 = `equity / initial_cash`，累计收益率 = `equity / initial_cash - 1`。
- 响应同时返回 `stock_code`、`initial_cash`、`final_equity`、`total_return`。计算由 C 的量化模块提供，B 仅在 FastAPI 层包装。

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
50001    data provider error
50002    database error
50003    quant calculation error
50004    backtest error
50005    ai service error
```

## 11. 修改规则

API_SPEC.md 是多人协作契约。修改接口路径、字段名称、百分比格式或响应结构时，必须同步 Schema、Service、前端类型和测试。
