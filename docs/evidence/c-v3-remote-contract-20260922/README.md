# C V3 远端契约核对及 B2 兼容复验

日期2026-09-22。此为 GitHub 实际代码的本地隔离联测，不是已部署服务器验收。

- 官方 main：`26f422a6ebd64295a632cee5a92492ed3aacb62c`。
- B PR #19：`fa91f4ca7477cc28db4df4021e32e40a42870fe6`，只含v9迁移及对应测试/文档，未实现F5接线。
- C PR #18远端头：`a79155e23e63ce1d8f01c56e41bdedc0c3a07c68`；量化代码提交 `6a84901c82256b7d48dfab3ebee3208633e5058c`。
- `git ls-remote` 已确认C分支与本地一致。此次没有修改B文件、没有合并PR；使用独立detached worktree，B保持上述SHA的文件，仅覆盖C的quant、两个新测试、验收脚本及固定证据。

## 已验证

1. 组合目录 `python -m pytest tests -q`：**682 passed, 2 warnings in 30.52s**（C单独677+B新增5）。不宣称存在一个已发布的最终组合SHA。
2. 使用B真实 `BacktestRepository.save/get`，把C的9份MACD+1份MA完整结果保存至临时SQLite，逐份关闭并重建engine/session读回：完整 `c_result` JSON含类型相等，`c_result_exact=true`；实际参数、`c_algorithm_version`、输入哈希、预热、三曲线、订单及数值示例投影一致。
3. Repository GET期间挂载C重算失败哨兵，读回无需调用C。SQLite主键沿用项目tests/conftest.py的 `BIGINT→INTEGER` 测试编译规则。该替代只适用临时SQLite，**未验证真实MySQL、HTTP创建或LLM/Provider调用隔离**。
4. `TestClient` 实测现有远端B代码的 `POST /api/v1/backtests`：显式 `strategy="macd"` 和 `"ma_cross"` 均为 **HTTP400 / 40001**，没有进入service.run。原因是当前Schema禁止未知strategy，Adapter/Service也未透传；这是F5待开发项，不是C已打通接口。

`result.json` 为脱敏逐项结果；`probe.py` 为本次探针来源。曾因独立探针未引入项目SQLite BIGINT编译适配而建库失败，按现有测试规则补齐后复跑通过；没有据此修改B生产代码或冒称MySQL证据。

## B 需接入的最小边界

入口沿用 `POST /api/v1/backtests`，请求示例（**接线后**才应成功）：

```json
{"stock_code":"600519","start_date":"2025-07-04","end_date":"2026-08-31","strategy":"macd","parameters":{}}
```

- Schema：新增严格strategy及按策略区分的参数白名单；保存字段是否提供的信息，不能将省略当null，不能把MACD六字段经MA五字段过滤。
- Adapter：`resolve_backtest_request(parameters, strategy=...)` 和 `run_backtest_request(frame, ..., strategy=...)`；省略策略用 `STRATEGY_UNSET`；省略参数用 `PARAMETERS_UNSET`。
- Service：数据I/O前完成resolve及日期验证；MACD省略parameters也须走windowed。由C `required_warmup_rows`决定取数，不固定120/20条；不要重复裁剪或套MA配置。
- 保存：实际六参数、策略名、算法版本、C完整输入/结果及快照hash原样保存；不得用默认评分/MA结果代替。`c_algorithm_version`应来自精确C快照；现有独立 `strategy_version` 列仅VARCHAR(20)，MACD算法版本超过20字符，不要截短写入，是否扩列由B/D决定，本次不要求新增映射。
- 错误：参数错误HTTP400/40001；预热/窗口无有效数据HTTP422/40003；内部算法故障不得伪装成成功或吞成参数错误。
- 读取：`GET /api/v1/backtests/{id}?include_c_result=true&include_input_snapshot=true` 对照精确结果；普通详情保留现有flat投影，历史GET不取数、不重算。公共summary有DECIMAL舍入，不能拿其展示精度声称C原文逐位一致。
- A/D消费：MA仍使用原参数名；MACD使用三个macd周期。收益/回撤/胜率是小数，Sharpe无单位，null不补零；订单数和往返数分开。自定义AI只读同一已保存快照，无默认量化评分。

完整参数/预热/时序/结果契约：[C_V3_MACD_CONTRACT.md](../../C_V3_MACD_CONTRACT.md)。C侧已通过，B/A/D的接线后须按其新SHA重复三股三参数直接计算→POST→新连接MySQL GET，并核对AI上下文。没有部署地址或服务器版本证据，因此不宣称远端运行服务已通过。

## 重现本次隔离组合（不要在开发分支覆盖B代码）

在全新的评审worktree，以B `fa91f4c...`为HEAD，仅从C `a79155e...`恢复 `backend/app/quant`、`tests/quant/test_v3_macd.py`、`tests/quant/test_v3_macd_evidence.py`、`scripts/validate_v3_macd.py`、`docs/evidence/c-v3-macd-20260922`。运行全量测试；在该目录执行本包 `probe.py`，结果写在评审目录上级的 `remote-contract-result.json`。此探针固定验证当前“strategy尚未接线”的状态，B实现后应用新验收矩阵替换本次状态探针，不能把旧预期失败保留为新功能通过条件。
