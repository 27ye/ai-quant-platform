# V2 B 侧接口样例（最终基线）

> 分支：`feature/v2-b-market-data`　提交 SHA：`43269f5`　迁移版本：`schema_version = 7`
> 生成方式：`python scripts/generate_v2_b_api_samples.py` —— 跑**真实代码**
> （真实 FastAPI app + 真实 Service + 内存 SQLite + 确定性假行情源），
> 回测部分使用 C 的真实 `run_backtest_request`。**非手写样例。**
> 其中 `created_at` / `as_of` / catalog 时间戳为生成时的运行时间。

## 0. 统一约定

- Base URL：`http://localhost:8000/api/v1`；统一返回 `{ code, message, data }`。
- 分页统一为 `data: { items, total, page, page_size }`（与 D 的 AI 契约同构）。
- 日期 `YYYY-MM-DD`；时间带时区 ISO 8601（UTC）；百分比用小数（`0.0125` = 1.25%）。
- 错误码：`40001` 参数错误、`40003` 数据不足、`40005` 回测不存在、`40006` 报告不存在、`50001` 数据源、`50002` 数据库、`50004` 回测引擎不可用。

---

## 1. `GET /api/v1/stocks/{stock_code}/data-status`

```http
GET /api/v1/stocks/600519/data-status
```

```json
{
 "code": 0,
 "message": "success",
 "data": {
  "stock_code": "600519",
  "catalog": {
   "synced": true,
   "row_count": 2,
   "last_success_at": "2026-09-16T03:06:42.388537Z",
   "last_attempt_at": "2026-09-16T03:06:42.388537Z",
   "source": "sample-catalog",
   "last_error": null
  },
  "kline": {
   "mode": "live",
   "source": "akshare.stock_zh_a_hist",
   "rows": 730,
   "first_trade_date": "2024-01-02",
   "last_trade_date": "2025-12-31",
   "last_refreshed_at": "2026-09-16T00:30:00Z",
   "coverage": "known",
   "expected_trading_days": 730,
   "last_attempt_at": "2026-09-16T00:30:00Z",
   "last_error": null,
   "freshness": {
    "status": "stale",
    "stale_days": 259,
    "max_stale_days": 3
   }
  },
  "as_of": "2026-09-16T00:35:00Z"
 }
}
```

| 字段 | 含义 |
|---|---|
| `data.kline.last_trade_date` | 行情截至日期 |
| `data.kline.last_refreshed_at` | **最近一次成功**刷新时间；最近一次尝试见 `last_attempt_at`，失败原因见 `last_error` |
| `data.kline.mode` | `live` / `frozen` / `unknown`（无刷新元数据，不猜） |
| `data.kline.coverage` + `expected_trading_days` | 覆盖情况，来自**交易日历**；无法证明时为 `unknown` |
| `data.kline.freshness` | `fresh` / `stale` / `unknown`，含 `stale_days`、`max_stale_days` |

---

## 2. `POST /api/v1/backtests`（`v2_windowed`）

```http
POST /api/v1/backtests
Content-Type: application/json

{
 "stock_code": "600519",
 "start_date": "2025-07-04",
 "end_date": "2025-12-31",
 "parameters": {}
}
```

响应：`HTTP 200`，`code = 0`

```json
{
 "code": 0,
 "message": "success",
 "data": {
  "strategy_name": "ma_long_only",
  "start_date": "2025-07-04",
  "end_date": "2025-12-31",
  "initial_cash": 100000.0,
  "final_equity": 111544.89682097046,
  "total_return": 0.11544896820970463,
  "annual_return": 0.16429377170059323,
  "max_drawdown": -0.0006764304471761351,
  "sharpe_ratio": 98.17480320390345,
  "win_rate": null,
  "trade_count": 0,
  "order_count": 1,
  "benchmark_return": 0.1165644171779141,
  "current_position": 1,
  "parameters": {
   "contract_status": "provisional",
   "short_ma": 5,
   "long_ma": 20,
   "initial_cash": 100000.0,
   "transaction_cost": 0.001,
   "slippage": 0.0,
   "allow_fractional_shares": true,
   "risk_free_rate": 0.0,
   "annualization_days": 252,
   "benchmark_method": "first_open_to_last_close_no_cost",
   "effective_trading_days": 181
  },
  "equity_curve": [
   {
    "trade_date": "2025-07-04",
    "equity": 99932.35695528239
   },
   "… 共 181 条"
  ],
  "benchmark_curve": [
   {
    "trade_date": "2025-07-04",
    "benchmark_equity": 100032.28931223766
   },
   "… 共 181 条"
  ],
  "drawdown_curve": [
   {
    "trade_date": "2025-07-04",
    "drawdown": -0.0006764304471761351
   },
   "… 共 181 条"
  ],
  "trades": [
   {
    "order_id": 1,
    "signal_date": "2025-07-03",
    "execution_date": "2025-07-04",
    "side": "buy",
    "execution_price": 154.85,
    "shares": 645.1411036493375,
    "gross_amount": 99900.09990009991,
    "fee": 99.90009990009992,
    "cash_after": 0.0,
    "position_after": 1,
    "round_trip_pnl": null,
    "round_trip_return": null
   }
  ],
  "stock_code": "600519",
  "semantics_version": "v2_windowed",
  "algorithm_version": "ma_long_only_v2.0.0",
  "requested_start_date": "2025-07-04",
  "requested_end_date": "2025-12-31",
  "effective_parameters": {
   "ma_short_period": 5,
   "ma_long_period": 20,
   "initial_cash": 100000.0,
   "transaction_cost": 0.001,
   "slippage": 0.0
  },
  "warmup": {
   "start_date": "2025-06-14",
   "end_date": "2025-07-03",
   "required_rows": 20,
   "used_rows": 20
  },
  "initial_equity": {
   "trade_date": "2025-07-04",
   "equity": 100000.0,
   "valuation": "before_open"
  },
  "execution_assumptions": {
   "model": "research_fractional_v1",
   "signal": "previous_observation_close",
   "execution": "next_observation_open",
   "first_day_signal": "last_warmup_close",
   "transaction_cost": "proportional_on_each_buy_and_sell",
   "slippage": "buy_price_increased_sell_price_decreased",
   "fractional_shares": true,
   "forced_final_sale": false,
   "benchmark_includes_costs": false,
   "exchange_execution_constraints": "not_modelled",
   "price_basis": "qfq"
  },
  "input_snapshot": {
   "schema_version": "quant_input_v1",
   "stock_code": "600519",
   "frequency": "daily",
   "adjust": "qfq",
   "data_mode": "dataframe",
   "columns": [
    "stock_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "change_pct"
   ],
   "rows": [
    {
     "stock_code": "600519",
     "trade_date": "2025-06-14",
     "open": 152.85,
     "high": 153.9,
     "low": 151.9,
     "close": 152.9,
     "volume": 1529.0,
     "amount": 100529.0,
     "turnover_rate": 0.01,
     "change_pct": 0.02
    },
    "… 共 201 条"
   ],
   "sha256": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988"
  },
  "data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
  "warmup_start_date": "2025-05-21",
  "warmup_rows": 44,
  "data_meta": {
   "semantics_version": "v2_windowed",
   "requested_start_date": "2025-07-04",
   "requested_end_date": "2025-12-31",
   "warmup_start_date": "2025-05-21",
   "warmup_rows": 44,
   "warmup_required_days": 20,
   "delivery_warmup_min_bars": 120,
   "rows": 225,
   "rows_in_window": 181,
   "frame_digest": "cf75257ce70e3c095dd82e8ec7bb389cd269d46dc697622f21a21782dd19ed36",
   "c_data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
   "computed_start_date": "2025-07-04",
   "computed_end_date": "2025-12-31",
   "current_position": 1,
   "parameters_explicit": true,
   "data_source": "MarketDataSource.query_daily (warmup window)",
   "window_owner": "C.run_backtest_request"
  },
  "backtest_id": 1,
  "snapshot_status": "complete"
 }
}
```

> `parameters` **省略** → `v1_legacy`；**显式 `{}` 或非空对象** → `v2_windowed`；
> **显式 `null`**（整体或任一白名单字段）→ `40001`，取数前拒绝。
> `v2_windowed` 的 `effective_parameters` **只含白名单五字段**；完整算法配置在
> `c_result.effective_parameters`。

### 2.1 白名单五字段与默认值

```json
{
 "ma_short_period": 5,
 "ma_long_period": 20,
 "initial_cash": 100000.0,
 "transaction_cost": 0.001,
 "slippage": 0.0
}
```

严格类型：拒绝数字字符串、布尔值、浮点周期、`NaN`/`Infinity`、未知字段；
周期整数且 `2 ≤ short < long ≤ 120`，`initial_cash > 0`，成本/滑点 `∈ [0,1)`。

---

## 3. `GET /api/v1/backtests`（分页列表）

```http
GET /api/v1/backtests?stock_code=600519&page=1&page_size=20
```

```json
{
 "code": 0,
 "message": "success",
 "data": {
  "items": [
   {
    "backtest_id": 1,
    "stock_code": "600519",
    "strategy_name": "ma_long_only",
    "semantics_version": "v2_windowed",
    "start_date": "2025-07-04",
    "end_date": "2025-12-31",
    "initial_cash": 100000.0,
    "final_equity": 111544.9,
    "total_return": 0.11544897,
    "annual_return": 0.16429377,
    "max_drawdown": -0.00067643,
    "sharpe_ratio": 98.1748032,
    "win_rate": null,
    "trade_count": 0,
    "order_count": 1,
    "benchmark_return": 0.11656442,
    "snapshot_status": "complete",
    "created_at": "2026-09-16T03:06:42"
   }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
 }
}
```

排序固定 `created_at DESC, id DESC`；`page_size` 默认 20、最大 100。
`snapshot_status` ∈ `complete` / `missing`（旧 V1 记录只存摘要）。

---

## 4. `GET /api/v1/backtests/{backtest_id}`（详情）

```http
GET /api/v1/backtests/1
```

```json
{
 "backtest_id": 1,
 "stock_code": "600519",
 "strategy_name": "ma_long_only",
 "semantics_version": "v2_windowed",
 "start_date": "2025-07-04",
 "end_date": "2025-12-31",
 "initial_cash": 100000.0,
 "final_equity": 111544.9,
 "total_return": 0.11544897,
 "annual_return": 0.16429377,
 "max_drawdown": -0.00067643,
 "sharpe_ratio": 98.1748032,
 "win_rate": null,
 "trade_count": 0,
 "order_count": 1,
 "benchmark_return": 0.11656442,
 "snapshot_status": "complete",
 "created_at": "2026-09-16T03:06:42",
 "warmup_start_date": "2025-05-21",
 "strategy_version": null,
 "current_position": 1,
 "parameters": {
  "ma_short_period": 5,
  "ma_long_period": 20,
  "initial_cash": 100000.0,
  "transaction_cost": 0.001,
  "slippage": 0.0
 },
 "effective_parameters": {
  "ma_short_period": 5,
  "ma_long_period": 20,
  "initial_cash": 100000.0,
  "transaction_cost": 0.001,
  "slippage": 0.0
 },
 "equity_curve": [
  {
   "trade_date": "2025-07-04",
   "equity": 99932.35695528239
  },
  "… 共 181 条"
 ],
 "benchmark_curve": [
  {
   "trade_date": "2025-07-04",
   "benchmark_equity": 100032.28931223766
  },
  "… 共 181 条"
 ],
 "drawdown_curve": [
  {
   "trade_date": "2025-07-04",
   "drawdown": -0.0006764304471761351
  },
  "… 共 181 条"
 ],
 "trades": [
  {
   "order_id": 1,
   "signal_date": "2025-07-03",
   "execution_date": "2025-07-04",
   "side": "buy",
   "execution_price": 154.85,
   "shares": 645.1411036493375,
   "gross_amount": 99900.09990009991,
   "fee": 99.90009990009992,
   "cash_after": 0.0,
   "position_after": 1,
   "round_trip_pnl": null,
   "round_trip_return": null
  }
 ],
 "data_meta": {
  "semantics_version": "v2_windowed",
  "requested_start_date": "2025-07-04",
  "requested_end_date": "2025-12-31",
  "warmup_start_date": "2025-05-21",
  "warmup_rows": 44,
  "warmup_required_days": 20,
  "delivery_warmup_min_bars": 120,
  "rows": 225,
  "rows_in_window": 181,
  "frame_digest": "cf75257ce70e3c095dd82e8ec7bb389cd269d46dc697622f21a21782dd19ed36",
  "c_data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
  "computed_start_date": "2025-07-04",
  "computed_end_date": "2025-12-31",
  "current_position": 1,
  "parameters_explicit": true,
  "data_source": "MarketDataSource.query_daily (warmup window)",
  "window_owner": "C.run_backtest_request"
 },
 "input_snapshot_available": true,
 "input_snapshot_rows": 201,
 "c_result_available": true,
 "c_semantics_version": "v2_windowed",
 "c_algorithm_version": "ma_long_only_v2.0.0",
 "c_data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
 "c_initial_equity": {
  "trade_date": "2025-07-04",
  "equity": 100000.0,
  "valuation": "before_open"
 },
 "c_warmup": {
  "start_date": "2025-06-14",
  "end_date": "2025-07-03",
  "required_rows": 20,
  "used_rows": 20
 },
 "c_execution_assumptions": {
  "model": "research_fractional_v1",
  "signal": "previous_observation_close",
  "execution": "next_observation_open",
  "first_day_signal": "last_warmup_close",
  "transaction_cost": "proportional_on_each_buy_and_sell",
  "slippage": "buy_price_increased_sell_price_decreased",
  "fractional_shares": true,
  "forced_final_sale": false,
  "benchmark_includes_costs": false,
  "exchange_execution_constraints": "not_modelled",
  "price_basis": "qfq"
 }
}
```

### 4.1 需要完整 C 结果时

```http
GET /api/v1/backtests/1?include_c_result=true
```

`data.c_result` 是 C 的**完整返回封套**（76420 字符，此处只展示关键字段）：

```json
{
 "c_result_available": true,
 "c_semantics_version": "v2_windowed",
 "c_algorithm_version": "ma_long_only_v2.0.0",
 "c_data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
 "c_initial_equity": {
  "trade_date": "2025-07-04",
  "equity": 100000.0,
  "valuation": "before_open"
 },
 "c_warmup": {
  "start_date": "2025-06-14",
  "end_date": "2025-07-03",
  "required_rows": 20,
  "used_rows": 20
 },
 "c_execution_assumptions": {
  "model": "research_fractional_v1",
  "signal": "previous_observation_close",
  "execution": "next_observation_open",
  "first_day_signal": "last_warmup_close",
  "transaction_cost": "proportional_on_each_buy_and_sell",
  "slippage": "buy_price_increased_sell_price_decreased",
  "fractional_shares": true,
  "forced_final_sale": false,
  "benchmark_includes_costs": false,
  "exchange_execution_constraints": "not_modelled",
  "price_basis": "qfq"
 },
 "c_result_keys": [
  "algorithm_version",
  "annual_return",
  "benchmark_curve",
  "benchmark_return",
  "current_position",
  "data_hash",
  "drawdown_curve",
  "effective_parameters",
  "end_date",
  "equity_curve",
  "execution_assumptions",
  "final_equity",
  "initial_cash",
  "initial_equity",
  "input_snapshot",
  "max_drawdown",
  "order_count",
  "parameters",
  "requested_end_date",
  "requested_start_date",
  "semantics_version",
  "sharpe_ratio",
  "start_date",
  "stock_code",
  "strategy_name",
  "total_return",
  "trade_count",
  "trades",
  "warmup",
  "win_rate"
 ]
}
```

| 字段 | 说明 |
|---|---|
| `warmup_start_date` | 预热区间起点（`v1_legacy` 为 `null`） |
| `equity_curve` / `benchmark_curve` / `drawdown_curve` | 数值键分别为 `equity` / `benchmark_equity` / `drawdown` |
| `trades` | 成交数组（不是 `orders`）；`order_count` 是记录数，`trade_count` 是完成往返次数 |
| `data_meta.frame_digest` | **B** 交给 C 的数据帧摘要 |
| `data_meta.c_data_hash` | **C** 输入快照哈希——与 `frame_digest` 分开记录，不能互替 |
| `c_result_available` | 是否有 C 结果封套；旧记录为 `false`，缺失时不补造、不重算 |
| `input_snapshot_available` / `input_snapshot_rows` | 送 C 的输入行数；`?include_input_snapshot=true` 取全量 |

> `snapshot_status = complete` **不能**代替 `c_result_available` 判断。

---

## 5. 错误样例

| 场景 | 请求 | HTTP | code |
|---|---|---|---|
| 未知回测 ID | `GET /backtests/999999` | 404 | `40005` |
| 股票代码非 6 位 | `GET /stocks/60/data-status` | 400 | `40001` |
| 白名单字段显式 `null` | `POST /backtests` `{'ma_long_period': null}` | 400 | `40001` |
| 省略 `parameters` → V1 | `POST /backtests` `{'stock_code': ...}` | 200 | `0` |

V1 路径响应 `semantics_version` = `v1_legacy`。

```json
{
 "code": 40005,
 "message": "backtest not found",
 "data": null
}
```
