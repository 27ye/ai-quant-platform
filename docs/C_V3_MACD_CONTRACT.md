# C V3 MACD 接口契约

日期：2026-09-22。基线：main `26f422a6ebd64295a632cee5a92492ed3aacb62c`。
任务 C1/C2，分支 `feature/v3-c-macd`。本契约由 C 提供给 B 接线；HTTP、数据库和前端完成情况以各方证据为准。

## 调用与参数

```python
from backend.app.quant import (
    PARAMETERS_UNSET, STRATEGY_UNSET,
    resolve_backtest_request, validate_backtest_window, run_backtest_request,
)
request = resolve_backtest_request(parameters, strategy=strategy)
if request.semantics_version == "v2_windowed":
    validate_backtest_window(start_date, end_date)  # 必须在取数前
# B 取窗口内数据及窗口前至少 request.required_warmup_rows 条有效日线。
result = run_backtest_request(
    frame, start_date=start_date, end_date=end_date,
    parameters=parameters, strategy=strategy,
)
```

省略字段必须传对应 sentinel 或不传实参，不能以 None 代替。新增 strategy 为仅关键字参数，旧的单参数调用保持兼容。

| strategy | parameters | 语义 |
|---|---|---|
| 省略 / `ma_cross` | 省略 | 原 `v1_legacy`，结果逐字段保持 |
| 省略 / `ma_cross` | `{}` 或 MA 对象 | 原 `v2_windowed` |
| `macd` | 省略 / `{}` / MACD 对象 | `v2_windowed`，必须明确起止日期 |
| null / 其他字符串 / 非字符串 | 任意 | BacktestParameterError，B 映射 40001 |
| 合法 strategy | null / 非对象 / 未知或串用字段 / 非法值 | 同上，在数据 I/O 前拒绝 |

MACD 六字段白名单：`macd_fast_period=12`、`macd_slow_period=26`、`macd_signal_period=9`、`initial_cash=100000.0`、`transaction_cost=0.001`、`slippage=0.0`。
周期必须是原生整数且非 bool；`2 ≤ fast < slow ≤ 120`，`2 ≤ signal ≤ 120`。资金须为正有限 JSON 数值；成本、滑点须为有限数值且位于 `[0,1)`。拒绝字符串数字、bool、null、NaN/Inf。MA 原五字段与默认值不变。

## 指标、预热与交易时序

- 复用现有 `calculate_indicators`：EMA `adjust=False`、`min_periods=0`、`ignore_na=False`；首个被消费的收盘价作为 fast/slow EMA 种子，首个 DIF=0 作为 DEA 种子。递推 `EMA_t = alpha*close_t + (1-alpha)*EMA_(t-1)`，`alpha=2/(period+1)`。
- DIF=`macd`=EMA_fast−EMA_slow；DEA=`macd_signal`=EMA_signal(DIF)；柱=`macd_hist`=2×(DIF−DEA)。保持现有指标命名及默认评分不变。
- **固定预热 N=slow+signal−1**，默认 34，上界 239。C 只消费请求开始日前最后 N 条有效日线和区间内日线；更多更早数据不参与 EMA，也不进入输入哈希。N 是本版本确定性初始化政策，**不是 EMA 完全收敛的保证**；改变该政策必须升级算法版本。
- 前 N−1 条仅初始化，第 N 条收盘开始信号有效。有效 DIF>DEA → 目标仓位 1，否则 0；相等为空仓。这是目标状态，不要求刚发生金叉。
- 最后一条预热日收盘信号可在区间首日开盘成交；窗口前不交易、不继承持仓。此后 T 收盘信号仅在下一有效日线开盘执行；区间最后收盘的新信号没有区间内成交机会。
- 复用原资金/订单执行器：单股、只做多、全仓、允许碎股、买卖均扣费，买价上浮/卖价下调滑点。区间末不强平；复权研究模型未建模整手、涨跌停和实际成交限制。
- 返回订单、权益/基准/回撤曲线只覆盖窗口。输入快照包含实际消费的 N 条预热及窗口，`data_hash` 仍是输入快照 SHA-256，不是结果哈希。预热不足抛原 InsufficientDataError，由 B 沿用数据不足错误映射，不静默缩短。

## 结果与兼容

MACD `strategy_name=macd_dif_above_dea_long_only`，`algorithm_version=macd_dif_dea_long_only_v3.0.0`，`semantics_version=v2_windowed`。
`effective_parameters` 为上述实际六字段；`parameters` 保留执行器公共说明并用三个 MACD 周期替换 MA 的 `short_ma/long_ma`。新增 `indicator_spec` 记录种子、EMA 设置、柱倍数、预热及信号政策。
其他结果字段沿用 MA，包括 `trades`（订单列表）、`order_count`（成交笔数）、`trade_count`（完成买卖往返数）、`initial_equity`、`warmup`、三曲线及原始输入快照。
MA 的策略名、算法版本、全部结果字段与默认 `QuantConfig`/评分/默认 AI 输入不变；MACD 不产生量化评分。

## 独立手算样例

fast=2 / slow=3 / signal=2 → N=4；收盘 `[10, 11, 12, 13, 5, 20]`。
前四天 DIF 分别为 `0, 1/6, 11/36, 85/216`；DEA 为 `0, 1/9, 13/54, 37/108`。
第4天 DIF−DEA=`11/216 > 0`；第5天 DIF=`-1369/1296`、DEA=`-1147/1944`，DIF<DEA。
窗口为第5、6天，开盘为10、20，初资1020.10，费率0.01，滑点0.01：
买价10.10、买100股、买费10.10；第5天权益500；第6天卖价19.80、卖费19.80、终值1960.20；往返净收益940.10；2笔订单、1次往返。基准无成本两点为510.05、2040.20。自动化以独立有理数递推及手算账本核验。

## B / A / D 对接

- B：适配器 resolve/run 透传 strategy；保持省略/null 区分，取数前验证，按 required_warmup_rows 取足，勿再次裁预热或重算历史；保存 MACD 类型、版本、六字段及完整 C 原始结果。
- A：仅展示对应策略参数；百分比只在展示时转换，订单笔数与往返次数分开；历史读取保存时策略，勿给 MACD 补 MA 参数。
- D：F4 可先用既有 MA 保存快照实现，无需等待 MACD；仅解释保存结果，不调用评分/行情/回测。数字口径见 `C_V3_NUMERIC_MAPPING.md`。
