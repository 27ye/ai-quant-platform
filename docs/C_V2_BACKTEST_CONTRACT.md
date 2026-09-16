# C V2 参数回测：实现契约与接入交接

日期：2026-09-15。基线：上游 `8062599b3d85c421f00714de9d27a9fbe11ad083`（PR #9）。

本文件是 C1–C4 的本地实现提案和交接依据，供 B/D/A 评审接入。用户已授权 C 按此前规划开发；尚未代表团队已冻结共享 API/数据库契约，也不是 V2 整体验收结论。

2026-09-15 对接澄清：本文已结合 B 的反馈补清严格类型、预热、窗口归属及保存精度。以下是 C 当前实现的交接说明，仍待 B/D 确认并写入共享契约；B 的远端实现和三股票数据尚不能仅凭反馈视为已通过联合验收。

本次仅扩展 `quant/`、C 测试、C 离线校验脚本和本文。旧 V1 HTTP、默认评分、默认 AI、数据库及前端保持原入口。V1 规范的旧初始化范围不适用于本次已授权 V2 C 工作；模块边界、单位和数据规则继续适用。

## 1. C 的交付范围

- C1：五字段白名单、严格校验、旧/新请求语义、日期及有效预热行数。
- C2：基于现有 MA 策略和成交引擎的窗口回测，区间前只预热。
- C3：完整订单/往返、权益/基准/回撤、实际配置、计算版本及输入快照。
- C4：手算场景、边界与独立回归；生成默认及自定义参数结果样例。

HTTP Schema/Service/错误映射、真实 MySQL 迁移/保存/历史查询由 B 接入；A 负责表单与历史显示；D 负责默认 AI 口径和最终联合验收。C 不生成数据库 ID 或虚构保存成功。

## 2. 公共 Python 入口

```python
from backend.app.quant import (
    PARAMETERS_UNSET,
    BacktestParameterError,
    resolve_backtest_request,
    validate_backtest_window,
    run_backtest_request,
)

# B 保留 JSON 字段是否存在；不能用 .get("parameters", {}) 抹掉差别。
raw_parameters = body["parameters"] if "parameters" in body else PARAMETERS_UNSET
request_config = resolve_backtest_request(raw_parameters)  # 取数前执行

if request_config.semantics_version == "v2_windowed":
    # 日期未提供时，B 先解析为明确默认区间，再调用此函数。
    start, end = validate_backtest_window(start, end)
    required = request_config.required_warmup_rows
    # B 获取窗口内完整数据及 start 之前至少 required 条有效行情。

result = run_backtest_request(
    normalized_dataframe,
    start_date=start,
    end_date=end,
    parameters=raw_parameters,
)
```

以上是接线示意，`body/start/end/normalized_dataframe` 由 B 提供，不是当前已新增的 HTTP 功能。现有 `run_backtest(data, config=None)` 和 `analyze_quant_dataframe(data, config=None)` 保留 V1 行为。

B 提供规范化的“预热＋回测区间” DataFrame，C 的 `run_backtest_request` 统一选取实际预热与交易窗口。B 不先裁掉预热行，也不再把整段数据交给旧 `run_backtest` 作为 V2 结果；C 返回的窗口结果无需 B 二次裁剪。B 可以为缓存、覆盖核验或其他独立功能多取行情，额外行不改变本入口的窗口语义。

## 3. 参数白名单

| 名称 | 默认值 | 允许值 |
|---|---|---|
| ma_short_period | 5 | 原生整数，2 ≤ short < long |
| ma_long_period | 20 | 原生整数，short < long ≤ 120 |
| initial_cash | 100000.0 | 有限 JSON 数字，严格大于 0 |
| transaction_cost | 0.001 | 有限 JSON 数字，[0, 1)，每笔买/卖按成交额收取 |
| slippage | 0.0 | 有限 JSON 数字，[0, 1)，买价上浮、卖价下浮 |

不接收字符串数字、布尔值、NaN/Infinity、未知字段、任意策略名或任意 `QuantConfig` 字段。金融参数规范为 Python float；不进行金额/收益二次舍入。`0.001` 表示 0.1%，不是 0.001%。

HTTP 层必须在 Schema 自动转换之前检查原始 JSON 类型，否则 `"5" → 5`、`true → 1.0` 后，C 无法恢复被抹掉的类型信息。均线只接受 JSON 整数（`5.0` 也拒绝）；资金、成本、滑点接受 JSON 整数或小数，例如 `initial_cash=100000` 和 `100000.0` 都合法，不能因使用严格浮点字段而误拒绝合法整数。参数类型规则不等同于行情 DataFrame 的数值规范化规则。

`BacktestParameters` 不可变，每次创建独立配置。MA10 不参与短/长均线策略，不增加 short < 10 < long 约束。对外仅上述五项可调；评分权重、碎股开关、无风险利率及年化天数不由本次表单控制。

策略唯一为短均线大于长均线时目标多头，否则空仓。V2 策略名为 `ma_long_only`，实际周期在参数中表示；不能修改策略名而仍执行另一套固定算法。

## 4. 请求语义及兼容性

| parameters 形式 | semantics_version | C 行为 |
|---|---|---|
| 完全省略 / PARAMETERS_UNSET | v1_legacy | 默认配置，计算 B 旧入口提供的完整 DataFrame，保留旧扩窗行为 |
| 显式 {} | v2_windowed | 默认金融参数，但应用新的零初始持仓窗口规则 |
| 显式非空对象（含只改资金） | v2_windowed | 覆盖白名单字段，其他取默认，应用新窗口规则 |
| null / 非对象 / 未知字段 | 无成功结果 | BacktestParameterError，B 在取数前映射参数错误 |

旧结果原有字段保持不变；新包装入口增加版本和快照字段。旧省略参数请求和新 `{}` 请求即使参数数字相同，也可能因窗口、首日成交和基准起点不同而得到不同收益，页面与历史需显示语义版本。

V1 R2 的 33 分、24 条订单、12 次往返、403 点只适用于同一固定输入及默认旧行为，不能作为自定义回测的预期值。

## 5. 日期、预热与首日执行

V2 必须传明确的开始和结束日期：严格 `YYYY-MM-DD` 字符串或原生 `datetime.date`，不接受 datetime/时区时间/时间戳。起止包含边界，start ≤ end，最长五个日历年；闰日五周年按目标年 2 月 28 日处理。旧语义不新增五年限制。

从输入中选取 start 之前最后 **long 条**有效行情作为预热，另选 start ≤ trade_date ≤ end 的实际回测行情。至少一条窗口内行情；预热少一行也报告不足。多余更早历史及 end 之后数据不参与计算、输入快照或收益。

- 在首个实际交易日开盘前，现金为 initial_cash，持仓为零。
- 允许将预热末日收盘已知的信号，在区间首个实际交易日开盘执行。
- 预热期不产生交易、持仓或收益；不能先回测整个长区间再裁剪曲线。
- 每日只使用前一条已知有效行情的收盘信号，在当前开盘成交。
- 最后一天收盘的新信号不会凭空成交；最后持仓按收盘价估值，不强制卖出。
- 回测区间落在周末时，返回实际存在的交易日期，不补造周末或停牌行情。

三条曲线的 `trade_date` 和订单的 `execution_date` 只覆盖实际回测区间。首日订单的 `signal_date` 可以是最后一个预热日，不能因该信号日期早于 start 而删除合法首日订单。

这里的 long 条是有效行情观测数，不是自然日数。需要区分两个要求：

| 场景 | 开始日期之前的行情要求 |
|---|---|
| 三股票验收数据包 | 每只至少 120 条有效日线，以便同一包覆盖所有允许的长均线参数 |
| 单次 V2 回测 | 恰好使用最后 long 条；默认需要 20 条，long=120 时需要 120 条 |

`required_warmup_rows` 直接返回 long。B 可多取 `max(120, long+1)` 条，但不能把该取数策略变成 C 每次请求的最低通过门槛，也不能据此拒绝已满足 long 条的合法窗口。long=120 的单日请求需要 **120 条预热＋1 条区间内行情＝121 条总输入**，不要求开始日前有 121 条。V1 的旧取数/扩窗行为仍按旧入口保留。

B 仍负责真实交易日历、覆盖完整性、停牌和数据来源核验；C 不自行生成交易日历，也不能仅凭行数证明行情覆盖完整。数据包中某股区间前不足 120 条时应补取并标注，不能用别的股票数据、合成数据或改变日期掩盖缺口。

## 6. 成交、收益与基准口径

本版仍是研究用简化成交：qfq 价格、可买碎股、单次比例交易成本、固定比例滑点、无杠杆、只做多。没有模拟交易所整手、涨跌停、停牌期间撮合、流动性、最低佣金及税费结构，也没有改用未复权价格处理公司行动。允许参数调整不等于实现真实 A 股成交仿真。

- 买入价 = 当日 open × (1 + slippage)。买入数量保证成交金额及本次手续费不超过现金。
- 卖出价 = 当日 open × (1 − slippage)。买卖各扣一次按成交额计算的成本。
- 权益 = 当日现金 + 持仓股数 × 当日 close，为账户绝对值。
- 总收益 = final_equity / initial_cash − 1。
- V2 日收益从开盘前本金开始，包含首日盈亏；回撤的历史峰值也包含本金。
- V2 有效天数为窗口内观测数 N，年化使用 252/N；Sharpe 沿用样本标准差、年化 252 和无风险利率 0。少于两个日收益或零波动时 Sharpe=null。
- `initial_equity` 单独标记首日 `before_open` 本金，不人为向三条按日曲线添加额外日期/点。
- V2 基准是首日 open 建仓、无费用滑点、持有到各日 close，标记 `first_open_to_last_close_no_cost`。收益对照必须展示“不含成本”。
- V1 保留原首日 close 基准、首日无交易及 N−1 的原指标行为。

`trade_count` 是已经完成的买卖往返数，`order_count` 是买/卖订单记录总数。未完成往返不进入胜率，零往返时 win_rate=null。末日持仓的浮动盈亏计入权益，不伪造一笔已完成卖出。

## 7. 结果、输入快照与存储

保留现有扁平回测字段：收益/风险指标、订单、三条曲线、`parameters` 等。`parameters` 的原 `short_ma/long_ma` 字段继续回显实际周期；新增 `effective_parameters` 是完整实际 QuantConfig（含固定设置）。请求只接受 `ma_short_period/ma_long_period`，两种名字的映射在 B/A 的契约中明确，不能默默接受多套别名。

本入口目前**不返回逐日 MA/MACD/RSI 等技术指标序列，也不返回这些技术指标的末值**。“完整结果”指此入口实际返回的绩效指标、订单、曲线和元信息，不要求 B 凭空新增技术指标存储。不能另调默认 `analyze_quant_dataframe`，把固定周期分析冒充用户自定义参数的技术指标快照。若 A 需要历史技术指标图，应由 B/C/A 另行确定字段、实际周期、区间和预热要求后扩展；不得只切换标签而复用不相符的序列。

新增字段：

| 字段 | 含义 |
|---|---|
| stock_code | 实际计算输入中的六位股票代码 |
| semantics_version | v1_legacy 或 v2_windowed |
| algorithm_version | ma_long_only_v1 或 ma_long_only_v2.0.0；是本计算契约版本，不是 Git SHA |
| requested_start_date / requested_end_date | 用户/服务解析的请求区间；旧语义可为 null |
| start_date / end_date | 实际曲线覆盖区间 |
| warmup | 实际预热起止、所需和使用行数；旧语义为 null |
| initial_equity | 计算起点的日期、金额与估值时点 |
| effective_parameters | 完整生效配置，固定配置与自定义值都可追溯 |
| execution_assumptions | 成交时序、价格口径、费用及模型限制 |
| input_snapshot | 规范化计算输入，含预热和全部实际窗口数据 |
| data_hash | 与 input_snapshot.sha256 一致 |

`input_snapshot` 的 schema_version 为 `quant_input_v1`，保存 stock_code、daily/qfq、data_mode、固定顺序 columns 和规范化 rows。必需列及实际存在的可选列均保存；不带任意额外列或任意 DataFrame.attrs。未提供 data_mode 时写 dataframe，不伪造实时来源。

V2 保存的是 C 实际使用的最后 long 条预热和全部区间内行情，不是 B 多取的整段历史；V1 则保存旧入口实际使用的完整输入。可选列为 `amount`、`turnover_rate`、`change_pct`，存在的列连同空值一起保存。可选列的存在性、数值和 `data_mode` 都参与哈希；直接计算、API 与 MySQL 回读验收须保持一致，不能在一侧删列或为离线复核随意改写 `data_mode`。

哈希对快照中除 sha256 外的内容，用 `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 字节计算 SHA-256。数值使用已有校验器转换后的 float，可选缺失为 null，不二次舍入。哈希用于检验输入一致性，不代替输入本身，也不证明源数据真实。

B 应将**完整输入与结果快照一起原子保存**，补保存时 Git SHA、依赖版本、真实来源/抓取时间/数据版本、记录 ID 和创建时间。C 不从当前行情猜测这些事实。B 可从 HTTP 页面投影中排除大输入数组，但数据库应保存完整内容；历史 GET 直接读取保存时结果，不调用行情、C 或 LLM。

JSON 数值回读应保持约定精度。禁止用旧摘要 DECIMAL 列重新拼装曲线或结果。qfq 刷新会改变历史价格，重看历史不能用当前 stock_daily 覆盖当时快照。算法升级后版本号也应改变，历史结果仍返回原快照。

### 7.1 三股票数据交付与精度

B 反馈正式行情按既定 4/2/6 口径入库，C 的联合验收需要明确区分以下交付物：

| 交付物 | 用途 |
|---|---|
| provider 原精度 qfq 日线文件 | 来源核验、原始数据留档；记录抓取时间、覆盖区间、缺失/停牌情况及文件 SHA-256 |
| 与正式送入 C 一致的规范化输入 | 三股票直接计算、API 返回、MySQL 回读一致性验收的共同输入；记录规范化规则、可选列及实际 `data_mode` |

4/2/6 指 OHLC 4 位、amount 2 位、turnover_rate/change_pct 6 位；volume 按已有行情契约保留。由 B 在送入 C 之前统一规范化并再次检查行情有效性；不能 API 路径使用 provider 原精度、MySQL 路径使用舍入值，再仅用 metadata 解释计算差异。C 的验证器会将合法数值转为 float，但不替 B 执行 4/2/6 舍入。

对同一规范化输入、参数和算法版本，C 返回的完整结果和 `input_snapshot` 按 JSON 数值原样保存，禁止再次把订单、曲线或输入值截成摘要表精度。展示层可以格式化小数，不反写已保存快照。三方验收同时比对参数、版本、实际区间、全部订单和全部曲线点，不能只看收益四舍五入后或数量相同。

每个交付文件的 SHA-256 校验文件字节是否相同；`data_hash` 校验 C 实际选用的输入及快照元信息。两者计算对象不同，正常情况下不相等，应分别记录。B 交付说明还需包含分支、提交 SHA、文件路径和读取方式。接入方应直接保留 C 返回的 `data_hash`，不要用另一个序列化规则计算文件哈希后替换它。

## 8. 错误与 B 接线注意事项

- BacktestParameterError：参数/日期无效，B 在取数前映射 40001。
- InsufficientDataError：有效预热不足/窗口为空，B 映射 40003。
- QuantValidationError：规范化行情不合法，不能填零或吞错；沿用团队错误边界分类。
- RuntimeError/OverflowError 等计算异常：不得保存成功结果；由 B 使用统一计算错误处理。

现有 QuantService 的 ValueError 通用映射不能替代请求前参数校验，否则非法参数会被误报为 50003。C 仅提供异常及校验函数，不修改 B 的 Router/Service。

## 9. 回归与离线样例

在项目根使用已有合适的 Python 环境：

```powershell
python -m pytest tests/quant -q
python scripts/validate_v2_backtest.py --output-dir <一个尚不存在的输出目录>
python scripts/example_v2_c_integration.py --output-dir <另一个尚不存在的输出目录>
```

脚本默认明确标记 synthetic；可使用 `--input-json` 读取已有规范化冻结数组，不访问网络。`--expected-v1-json` 可提供完整旧 `analyze_quant_dataframe` 结果作严格比较。具体选项以 `--help` 为准。

输出提供旧默认、V2 默认和两组自定义完整结果、long=120 单日边界及清单。JSON 保存/读取/复算一致仅证明离线快照，不代表 HTTP、真实 MySQL、实时数据或浏览器已通过。

`example_v2_c_integration.py` 是可独立运行的接线样例：使用明确标记的合成行情、内存 loader 和显式日期，演示缺省参数、空对象、自定义周期、long=120 单日请求，以及坏参数在取数前拒绝。输出含请求、完整结果及摘要；loader 的关键字参数是示例约定，由 B 适配自身服务，不是已有 B API。示例不验证 B 的 HTTP Schema 或真实持久化。

现有 `validate_v2_backtest.py` 自动选择输入第 120 行作为窗口起点，用于通用离线回归；它并非固定日期的三股票联合验收工具。三股票统一区间验收需将同一组明确起止日期传给 `run_backtest_request`，不得因每股数据包起点不同而把不同窗口当成相同区间比较。

测试重点：类型/未知参数、缺省/空对象/null、默认不变、手算首日收益和回撤、双边费用/滑点、无交易/未平仓、长均线预热边界、跨年/周末、未来行情不改变既有信号与成交、输入不变、默认评分及 AI 配置隔离。

## 10. 接入前评审与后续工作

请 B/D/A 对上述五字段名称、首日执行、V2 基准起点、本金锚点、五年边界、错误映射和快照精度评审后，统一写入共享 API/数据库规范；本文件不代替他们的契约 PR。

后续验收由 B 提供至少三只约定股票的真实日线和真实 MySQL 保存/回读证据。C 对完整参数、版本、实际区间、每条订单和每个曲线点复核，D 在最终组合 SHA 汇总，不能只核对订单数量。

评分校准、MACD 重复信息权重和更真实成交模型属于独立后续议题。本版默认评分保持稳定，不通过调高某个冻结样本的收益宣称算法改进。

## 11. PR #10 的 C 接入协调（2026-09-15）

本节依据 [PR #10](https://github.com/27ye/ai-quant-platform/pull/10) 的 `e95198a0ea3f1b34d64d562c161d37d033ab66ce` 和 [B 的有条件评审](https://github.com/27ye/ai-quant-platform/pull/10#pullrequestreview-5205125821)。本轮保存的 GitHub 状态仍为 Draft/Open，评审状态为 `CHANGES_REQUESTED`。以下明确区分已核对的代码与尚待 B/D 修改的目标口径，完整责任和复验清单见 [C_V2_PR10_COORDINATION.md](C_V2_PR10_COORDINATION.md)。

### 11.1 默认 AI 与自定义回测继续分离

D 的 AI adapter 仍以 `analyze_quant_dataframe` 获取默认分析并按请求缓存；C 的 `run_backtest_request` 负责用户参数回测。自定义请求不得修改默认 `QuantConfig`，不得将最近一次用户回测保存结果静默放入 AI 报告上下文。即使显式 `{}` 使用相同的 5/20 参数，其 `v2_windowed` 语义也不能冒充默认 AI 的 V1 分析口径。

### 11.2 哈希和数值规范各自适用

| 标识 | 计算对象与用途 |
|---|---|
| 文件 SHA-256 | 交付文件的原始字节，验证下载/传输内容 |
| C `data_hash` | 本文定义的实际计算输入快照；与 `input_snapshot.sha256` 相同 |
| D `context_hash` | 实际送入 AI 的结构化上下文，经 D 的上下文数值规范后计算 |
| Git SHA | 代码提交，不代替算法版本、输入版本或数据哈希 |

PR #10 将 AI 上下文中的浮点数规范为 15 位有效数字、将 `-0.0` 规范为 `0.0`，并让 Prompt 与保存使用同一份规范化上下文。此规则只作用于 AI 上下文副本，不能借此修改 C 的原始结果、输入快照或 `data_hash`。C 的完整 JSON 精度仍按第 7 节执行；是否经真实 MySQL 往返保持一致，需要 B/C 在正式存储路径另行验证。发现精度不一致时先记录差异并共同确定存储方式，不能静默截断 C 数值以使检查通过。

核对默认 C 与 AI 的数值时，先按 D 的字段投影及 15 位规则比较 AI 上下文副本；C 原始输入、默认结果和自定义结果应保持不变。D 报告的 `snapshot_status=complete` 表示 AI 上下文完整，其中保存技术指标末值、评分和默认回测摘要，不包含 C 的全量 bars、全部订单/曲线和完整生效配置；不能以此替代 B 保存 C 回测完整快照的责任。

### 11.3 来源与时间边界

`get_query_provenance()` 记录本次查询的来源，B 的 `stock_daily_sync` 记录持久同步状态。按评审建议两者保留，不能拿当前同步状态补写历史报告来源。C 的 `data_mode` 仅是其快照内已有标记，不替代 provider、数据版本和实际抓取时间；B 应从实际查询路径捕获真实元数据并与结果一起保存。

PR #10 当前 `data_as_of` 和上下文 `provenance.retrieved_at` 由上下文组装时间赋值。对接时保留此含义，不把它们误当最新行情交易日或 provider 抓取时间；行情日期和持久同步时间分别使用对应事实字段。

### 11.4 错误码与迁移待 B/D 落地

协商目标为未知回测 HTTP 404 / `40005`、未知 AI 报告 HTTP 404 / `40006`。在已核对的 PR #10 HEAD 上，`ReportNotFoundError`、AI 契约及 API 文档仍使用 `40005`，需 D/B 同步修正；C 不改这些所有权文件。

迁移由 B 统一负责。评审要求先集成 B 的分步迁移，将 AI 七列纳入 v5，D 采用该基线并删除独立的 v2 迁移冲突。已核对的 PR #10 仍为 `SCHEMA_VERSION=2`，因此不能把 v5 视为本轮已完成验证。C 仅提供回测保存字段需求，不新增独立迁移版本。

本轮独立验证目录使用 PR #10 上述 HEAD 加 C 局部文件叠加，未合入 B 的完整分支，也不是最终组合 SHA。测试与离线检查结果由本轮实施报告记录；三股票真实行情、B 正式参数 API、真实 MySQL v5 迁移及回读、A 页面和最终 SHA 验收继续分别列为待办。旧本地交付包保留为历史产物，不能代表本节之后的最新交付。
