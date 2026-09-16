# C 对 Issue #11 的前端契约确认

核对日期：2026-09-15。对应 [A 的 Issue #11](https://github.com/27ye/ai-quant-platform/issues/11)。

本文依据 C 实现及实际计算输出，确认参数、成交记录和曲线口径。C 已发布到 `pop17589822299-coder/ai-quant-platform` 的 `feature/v2-c-backtest-params` 分支，代码提交为 `92df017404126e9af920e1ad82e4a136d813f8d1`；按项目命名规则更正后的交付入口见 [C_V2_DELIVERY_20260916.md](C_V2_DELIVERY_20260916.md)。最新组合复核见 [C_V2_COMBINED_15315_REVIEW_20260916.md](C_V2_COMBINED_15315_REVIEW_20260916.md)，本文不能代替 B 的最终 HTTP 契约或最终组合 SHA 验收。下文带日期的旧评审记录保留其当时范围。

完整核心契约见 [C_V2_BACKTEST_CONTRACT.md](C_V2_BACKTEST_CONTRACT.md)，与 D 的边界见 [C_V2_PR10_COORDINATION.md](C_V2_PR10_COORDINATION.md)。

## 1. 请求参数与表单

`parameters` 只接受以下五个字段，可省略其中任意字段以使用该字段默认值：

| 请求字段 | 默认值 | 校验与单位 |
|---|---:|---|
| `ma_short_period` | 5 | JSON 整数，`2 <= ma_short_period < ma_long_period <= 120` |
| `ma_long_period` | 20 | JSON 整数，同上 |
| `initial_cash` | 100000 | 有限数值且大于 0，元 |
| `transaction_cost` | 0.001 | 有限数值，`[0,1)`；按买、卖各自成交金额收取的成本率 |
| `slippage` | 0 | 有限数值，`[0,1)`；买入价上调、卖出价下调的比例 |

```json
{
  "ma_short_period": 5,
  "ma_long_period": 20,
  "initial_cash": 100000,
  "transaction_cost": 0.001,
  "slippage": 0
}
```

拒绝字符串数字、布尔值、非有限值和未知字段。周期要求整数类型；资金、成本率和滑点可以使用合法的整数或小数。页面百分比输入若显示 `0.1%`，请求发送 `0.001`，只换算一次。

Issue 中的 `short`、`long`、`commission` 可以作为页面内部变量，但发往 C 契约的字段必须映射为 `ma_short_period`、`ma_long_period`、`transaction_cost`；不能作为请求别名直接发送。建议将成本标签写为“交易成本率”。

新表单始终显式提交 `parameters` 和日期，进入 `v2_windowed`。显式 `{}` 使用上述默认值，仍是 V2；完全省略 `parameters` 是 `v1_legacy`，显式 `null` 无效。

返回结果保留旧字段 `parameters.short_ma` / `parameters.long_ma`；完整生效配置使用 `effective_parameters.ma_short_period` / `effective_parameters.ma_long_period`。重填表单时只挑选五个白名单字段，不能把整个 `effective_parameters` 原样 POST 回去。

## 2. 日期、预热与结果归属

- 日期格式为 `YYYY-MM-DD`，首尾均包含，允许单日区间。
- `start_date <= end_date`，最长五个日历年，不以固定 1825 天判断。闰日五周年落在非闰年时按 2 月 28 日：`2020-02-29` 至 `2025-02-28` 合法，至 `2025-03-01` 超限。
- 当前 C 核心需要开始日期之前至少 `ma_long_period` 条有效日线，选取最近这些行预热；默认需 20 条。数据交付预备至少 120 条是为覆盖最大长周期，不代表每次计算都使用 120 条。
- B 传入包含预热的规范化行情，C 统一选择窗口。预热不产生窗口前的交易、持仓或收益；最后一个预热日的收盘信号可以在窗口首个有效交易日开盘成交。
- 返回 `requested_start_date` / `requested_end_date` 为请求区间，`start_date` / `end_date` 为实际有数据的回测区间；`warmup` 含 `start_date`、`end_date`、`required_rows`、`used_rows`。
- 曲线和成交执行日期只覆盖实际回测区间，不补周末或预热点。初始本金单独放在 `initial_equity`，其 `valuation` 为 `before_open`；不要将它重复插入日线数组，制造多一个同日点。
- C 不规定全站固定默认日期；A/B 应根据可用数据选取。不要把某一只股票的冻结样本日期当作所有股票都有覆盖的事实。
- 按 C 接入约定，非法参数映射 `40001`；预热不足或区间无有效行情映射 `40003`。A 对 `40003` 的通用提示宜为“可用行情不足”，再显示具体原因，不能一律断言是预热不足。最终 HTTP 映射由 B 落地。

以上窗口与本金描述适用于 `v2_windowed`。C 新包装入口的 `v1_legacy` 返回 `warmup=null`，`requested_start_date` / `requested_end_date` 可为 `null`，`initial_equity.valuation="first_close"`；V2 为 `"before_open"`。更早的数据库记录可能缺少这些新增字段，应按 B 确认的历史缺失状态显示，不补造对象或数值。

页面改表单后、尚未重新计算时，旧结果继续显示保存时的生效参数、实际区间和语义版本。历史 GET 读取保存结果，不重新取数或计算。默认评分、技术指标与 AI 默认分析不应被最近一次自定义回测静默替换。

## 3. 成交数组及计数

C 返回的数组字段是 `trades`，不是 `orders`。如果页面内部变量叫 `orders`，读取时应明确映射。每条记录字段如下：

| 字段 | 类型/说明 |
|---|---|
| `order_id` | 整数，本次回测内从 1 开始的序号，不是数据库主键 |
| `signal_date` | `YYYY-MM-DD`，信号日期，可为窗口前最后一个预热日 |
| `execution_date` | `YYYY-MM-DD`，成交日期，必须位于回测区间 |
| `side` | `buy` 或 `sell` |
| `execution_price` | 含滑点的成交价，元/股 |
| `shares` | 本次成交股数，允许小数股 |
| `gross_amount` | 成交金额，元，未加减 `fee` |
| `fee` | 本次成本，元 |
| `cash_after` | 成交后现金，元 |
| `position_after` | `0` 空仓 / `1` 持仓，表示状态，不是股数 |
| `round_trip_pnl` | 买入为 `null`；卖出为该次完整往返的净盈亏，元，含双边成本 |
| `round_trip_return` | 买入为 `null`；卖出为完整往返收益率，比例值 |

`order_count = len(trades)` 表示买卖成交记录条数；`trade_count` 表示已完成买卖往返次数，两者不能混用。末日不强制平仓，因此允许奇数条成交记录或持仓结束；不要为显示凑成买卖对而生成额外卖出记录。

本版为 qfq 价格、允许小数股的简化研究模型，未模拟完整交易所成交约束。曲线和订单应标为回测结果，避免把它们表述成真实账户收益。

## 4. 三条曲线及显示单位

| 数组 | 单点字段 | 纵轴含义 |
|---|---|---|
| `equity_curve` | `trade_date`, `equity` | 策略收盘权益，元 |
| `benchmark_curve` | `trade_date`, `benchmark_equity` | 买入持有基准权益，元 |
| `drawdown_curve` | `trade_date`, `drawdown` | 回撤比例，非正数 |

三条曲线日期升序、一一对应，只包含实际回测区间。权益和基准不是百分数，也不是起点为 1 的净值。若页面切换收益率坐标，展示值使用 `(equity / initial_cash - 1) * 100`，基准同理；不覆盖原数值或重算服务端指标。

V2 基准口径为首个有效回测日开盘买入、持有至各日收盘，**不计交易成本和滑点**。标签建议“买入持有基准（不含成本）”。`parameters.benchmark_method` 和 `effective_parameters.benchmark_method` 为 `first_open_to_last_close_no_cost`。首日收盘点可能不等于初始本金，不应强行改为本金。

V1 保留首日收盘基准口径。历史页依据保存的 `semantics_version` 和参数展示，不能把 V1 历史曲线改标为 V2。

`total_return`、`annual_return`、`benchmark_return`、`win_rate`、`max_drawdown` 及 `round_trip_return` 都是比例值；显示百分比时乘 100。`max_drawdown` 和 `drawdown` 原始值不大于 0；若展示正的回撤幅度，须明确标注且只在展示层取绝对值。`sharpe_ratio` 不是百分比。保留存储数值，金额/比例的小数格式化只用于页面显示。

## 5. 无成交、空值和缺失记录

- 有有效行情但 `trades=[]` 是成功回测：照常显示指标和曲线，成交区显示“该区间无成交”，不能把整张回测卡片当成空数据隐藏。
- 没有已完成往返时 `win_rate=null`，包括仅买入尚未卖出的情况；显示“— / 无已完成往返”，不能转为 0% 胜率。
- `sharpe_ratio=null` 表示无法计算，显示“—”，不能用 0 替换。
- 单日区间的一个曲线点是合法结果，不应因点数小于 2 而判定空数据。
- 旧记录缺快照、未知 ID 的具体 HTTP 结构及状态字段由 B 确认；C 不生成假的快照、记录 ID 或创建时间。

## 6. 可供 A 对照的实际计算样例

[C_V2_FRONTEND_EXAMPLES.json](examples/C_V2_FRONTEND_EXAMPLES.json) 含三组请求和当前 C 核心实际输出，包括完整输入快照。所有价格都是明确标注的合成数据，不是三只验收股票的真实行情。文件是 **C 核心字段样例，不是完整 HTTP 响应**，未伪造 B 的包装、ID、分页或保存状态。

| 样例名 | 成交记录 | 已完成往返 | 曲线点数 | 核对结果 |
|---|---:|---:|---:|---|
| `default_open_position` | 1 | 0 | 2 | 首日使用最后预热信号，末日仍持仓，胜率为空 |
| `no_orders` | 0 | 0 | 2 | 成功回测、收益 0、胜率和夏普为空 |
| `completed_round_trip_with_costs` | 2 | 1 | 2 | 手算双边成本和滑点一致，末日权益 1960.20 元 |

另有四组拒绝输入样例：未知 `commission`、字符串周期、布尔本金、显式 `null`。五日历年的闰日边界也已核对。

样例文件 SHA-256：`029f4c9aed9f984f724dbbef0453e8f9b2d5371eb4bc038156cf587cb1f77311`。

这些检查不代表 A 页面构建、B 正式 HTTP、真实行情或 MySQL 已通过。

## 7. 仍由 A/B/D 协调的事项

1. B：`data-status` 真实 JSON、覆盖/新鲜度枚举、行情截至日和实际刷新时间；回测列表/详情包装、ID、创建时间、快照状态及分页。C 同意统一分页建议，但不声明 B 已实现。
2. B/D：未知回测与 AI 报告的错误码最终统一。现有协商目标为回测 `40005`、报告 `40006`，均 HTTP 404；已核对的 D PR #10 草稿仍有报告 `40005`，不能直接把目标写成已上线事实。
3. D：PR #10 合并时间线及 AI 时间字段语义。已核对的 PR #10 中 `data_as_of` 使用上下文组装时间，不宜直接标成“行情截至日期”；应确认使用已保存的实际行情日期字段，例如上下文中的 `provenance.market_end_date` / `market_snapshot.trade_date`，由 D 确认最终对外路径。
4. A：本次从公共 GitHub 入口未能读取 issue 提到的 `feature/v2-a-backtest-form` / `1ada4ee`，请提供可读取分支及完整 SHA。此次未检验 A 实际页面实现、typecheck 或 build；不能把 issue 中的内部变量名称直接当作已发生的接口错误。
5. C：实现和本说明仍在本地，后续提供可读取提交后，A/B 再进行真实接口联调；最终在 D 确认的组合 SHA 上验收。本轮不关闭仍含 B/D 待确认项的 Issue #11。
