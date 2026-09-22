# C V3 回测对照 / AI 数值口径（C3）

基于 main `26f422a6ebd64295a632cee5a92492ed3aacb62c` 的保存结果结构。F3/F4 可先使用已有 MA 快照，MACD 沿用公共数值字段。此文不代表 A/B/D 的功能已通过。

| C 原始字段 | 含义 / 展示与解释规则 |
|---|---|
| total_return / annual_return / benchmark_return | 小数收益率，0.12 才是12%；年化按252个交易观察值，窗口含首日收益，不是盈利预测 |
| max_drawdown / drawdown_curve[].drawdown | 非正小数，从初始资金锚点计算；−0.12 表示12%回撤，勿再取反参与结果比对 |
| sharpe_ratio | 无量纲；样本标准差 ddof=1，252交易日年化，默认无风险率0；样本不足或零波动为 null |
| win_rate | 已完成往返中盈利次数占比，小数；无已完成往返为 null，不是0% |
| order_count / len(trades) | 实际成交订单笔数，未平仓可能为奇数 |
| trade_count | 已完成买卖往返次数，不能直接称订单数 |
| initial_cash / final_equity | 资金金额；终值包含剩余持仓按最后收盘价估值，未必全是现金 |
| trades[].round_trip_pnl / round_trip_return | 已平仓净收益金额/比例；买单对应空值保留，不填0 |
| equity_curve[].equity | 每个窗口交易日收盘总权益，包含现金和持仓 |
| benchmark_curve[].benchmark_equity | 初始资金×当日收盘/首日开盘，无交易成本 |
| initial_equity | 窗口首日开盘前资金锚点，不算额外日线、订单或曲线点 |
| requested_start_date / requested_end_date | 请求窗口；start_date / end_date 是实际首末有效交易日，节假日可不同 |
| warmup | 只初始化，used_rows 不属于回测收益天数；MACD政策见专项契约 |
| data_hash / input_snapshot.sha256 | 实际消费输入及元数据的哈希，不能解释成结果或 AI 上下文哈希 |
| algorithm_version / semantics_version | 算法与窗口语义版本分别保留；V3 MACD 的窗口语义仍为 v2_windowed |

## F3 对照

只读已保存记录；同股票、不同记录 ID。两边显示实际策略、参数、版本、窗口、预热、资金、成本/滑点、来源和哈希。不同窗口、资金、版本必须可见，不以插值/截短制造可比性；不自动给出“胜者”。
归一化曲线只做 `equity / initial_cash - 1`，逐点保留原日期。输入曲线或初始资金缺失则标为缺失，不能补0或擅自重算。旧记录无完整精确 C 快照时不得伪装精确证据。
B 现有普通详情投影的 `c_algorithm_version/c_data_hash/c_initial_equity/c_warmup/c_execution_assumptions/c_semantics_version` 是对应 C 字段；需要完整原结果时由 B 的 `include_c_result=true` 提供，前端不得从默认评分接口拼接。

## F4 AI 上下文白名单

来自同一份保存快照：策略名/版本、实际参数、请求及实际区间、预热、初资和终值、上述绩效指标、执行假设、输入哈希。曲线摘要可确定性提取第一/最后点、最小回撤和点数；不让模型计算或改写原始金额。记录 ID、source、保存时间来自 B 的保存记录，不从 C data_mode 猜来源。
`quant_score=null`：参数回测没有默认评分。不得调用默认评分、实时行情、新闻或重跑回测来补齐上下文。保留 null；零收益、0笔订单和无胜率分别表达。对尚未平仓结果明确区分浮动收益与已实现往返收益。
原始 C 精确 JSON 文本必须原样存留。D/B 约定的上下文归一化仅执行一次，Prompt、保存快照和 context_hash 使用同一对象；context_hash 与 C 输入 data_hash 分开。数据截至日、保存时间与报告生成时间分别表示，不能声称记录反映当前行情。
缺少旧快照与新格式损坏按 D/B 契约区分，不能回退默认 AI 报告后仍标为 custom。

## C 验证边界

C 提供固定数据上的完整原结果和映射示例，复核小数单位、类型、空值、哈希和曲线计数。F3 页面、F4 Prompt/归一化实现、真实 LLM、数据库重启读回及调用隔离需在 A/B/D 提供对应 SHA 后复验；不能用 C 的离线结果替代。
