# C 独立复核 B PR #21（2026-09-22）

结论：**正常MACD数值与精确快照链路通过预验；两处API契约问题需B修正，暂不签接口全面一致。** C量化算法无需改动。

## 绑定版本及范围

- B 最新远端PR #21：`11a0c03ecca56fe667b845a976afd1cdde9197b7`。没有只沿用B评论中的较早 `219612b`。
- C：远端 `13256729a162c45af5be3fc31ee15e59b4d5287a`；生产算法 `6a84901c82256b7d48dfab3ebee3208633e5058c`。
- 独立detached worktree以B SHA为基，只恢复C的 `backend/app/quant`、两个V3测试、`scripts/validate_v3_macd.py` 和既有C固定包结果。不修改B文件；没有合并PR。
- 本轮 **不含独立PR #19的v9迁移**。此前该PR与C的682项复验是另一个组合，不能混称本次696项包含v9。
- Windows / Python3.12.10 / pandas2.3.3 / numpy2.5.3。临时SQLite采用项目测试同样的BIGINT→INTEGER主键编译适配；真实HTTP路由（TestClient）、Schema、Service、C入口、Repository；行情源替换为固定交付包。无实时Provider、MySQL、真实LLM或浏览器验收。

## 执行结果

`python -m pytest tests -q` → **696 passed, 1 skipped, 2 warnings in 29.96s**。跳过项是实际C已支持strategy时不再适用的缺实现路径；另用支持位关闭注入，独立实测合法MACD请求→HTTP500/50004、取数0次、落库0条。

`probe.py` → **exit 1**，`result.json.status=changes_required`。探针发现契约问题时明确失败，不将全量旧测试绿色作为接口通过。文件包含复现来源与脱敏逐组结果。

固定输入为腾讯qfq交付20260917三股票各437行 normalized，窗口2025-07-04—2026-08-31。直接计算使用B的 `QuantService.rows_to_frame`，与服务实际frame相同，避免仅data_mode不同造成假哈希差异。

| 核查 | 实际结果 |
|---|---|
| 三股×默认12/26/9、自定义6/13/5、20/40/12含成本滑点 | 9/9正常POST成功 |
| C直接结果每一个原始字段与POST | 9/9完整JSON及类型相等 |
| POST后关闭engine、重建engine/session，再HTTP GET `include_c_result=true` | 9/9完整C原结果相等、c_result_exact=true |
| 预热 / 三曲线 | 三组分别34/17/51条；窗口曲线各283点 |
| 历史GET | 取数失败哨兵及C重算失败哨兵下成功，无额外行情调用 |
| 参数错误：strategy=null、parameters=null、串入MA字段、bool周期、周期范围/顺序 | 6/6 HTTP400/40001、取数0、落库0 |
| C支持位关闭、请求合法 | HTTP500/50004、取数0、落库0；确认是部署缺口，不改40001 |
| MACD缺失/null日期 | **5/5错误地200成功，各取数1次、落库1条** |
| POST与历史GET effective_parameters | **9/9字段集合不一致：POST6字段、GET12字段** |

## 问题1：明确日期要求被自动补值绕过

`BacktestService._run_windowed` 在C校验前先执行 `end_date or today`、`start_date or default_window`，导致MACD也继承旧MA日期补值。

最小请求：

```json
{"stock_code":"600519","strategy":"macd"}
```

固定today=2026-08-31时，实际200/0，自动生成2025-08-30—2026-08-31并保存；只缺start、只缺end、start=null、end=null也200并保存。V3计划§5.1、B API_SPEC及C契约要求MACD明确起止日期。

请B在MACD分派时、任何日期默认值/数据I/O前检查两日期均非空；缺失或null应400/40001、取数0、新增记录0。**只约束MACD，旧MA默认日期行为保留。** 补上述5种边界回归。

## 问题2：持久化的实际参数取错了C对象

`_run_windowed` 用 `c_result.parameters` 作为 `stored_parameters`；`_persist_and_return` 把它传给Repository的 `effective_parameters`。C的两个对象语义不同：

- `effective_parameters`：三个macd周期+initial_cash/transaction_cost/slippage，实际6字段。
- `parameters`：6字段加allow_fractional_shares/annualization_days/benchmark_method/contract_status/effective_trading_days/risk_free_rate，含执行说明，共12字段。

因此正常POST为6字段，GET的parameters/effective_parameters变为12字段。A重载参数再提交会因额外字段触发40001，F3/F4也无法依赖统一参数结构。**完整c_result本身没有损坏，精确读回仍通过。**

请B持久化已验证的 `c_result.effective_parameters`，完整执行说明继续在精确C快照中保留；不可改C算法删字段来迁就。补真实C入口下POST→关闭连接→GET的字段及类型完全相等断言，并将历史effective_parameters重新POST验证可用。旧MA行为不变。

## 对B两项确认

1. 合法MACD请求遇到C缺实现：确认HTTP500/业务50004，不是参数40001；不取数、不落库、不降级MA。参数/null错误继续40001。
2. MACD只转发用户显式字段：确认，默认由C解析。解析完保存及响应使用C返回的完整六字段，不把稀疏请求或执行说明替换成实际参数。

精确算法版本保持 `c_algorithm_version` 原文；已有strategy_version过长存NULL而非截断的方向认可。两个阻塞修复后需基于B新完整SHA复验，随后再做MySQL与最终组合验收。本次不代签B报告的其他场景。

## 重现

在新的B `11a0c03...`评审worktree恢复C `1325672...`上述路径。从该评审目录执行本包 `probe.py`（路径可为绝对路径）。输出写到评审目录上级 `b21-c-http-result.json`；现有版本应退出1并得到上述两项findings。之后B修复可复用探针，但须同时更新被测SHA标注；不能在新版本报告中保留旧常量声称版本正确。
