# C V2 固定批次最终量化验收结论

2026-09-17。**C 对组合 SHA `85b7617149fbff67189e52f6527c9921ff09d388` + `c-delivery-20260917` 的三股票×三参数验收通过。该结论仅覆盖下述固定批次数值、存储和隔离契约，不代表 V2 实时链路或整体合并门槛通过。**

已同时阅读D的 [首条验收分工](https://github.com/27ye/ai-quant-platform/issues/11#issuecomment-5710957724) 和 [后续状态说明](https://github.com/27ye/ai-quant-platform/issues/11#issuecomment-5710993739)，两者绑定同一SHA。按D要求保留Draft，不转Ready、不合并。

## 绑定版本与输入

- A `d7ba01c63eed07b23fff6939753d7ee591c140fb`、B `540a00f604044bd046cd3935f4df9d018063b44b`、C `87785788fed0a4f08bf5bd5b7a39a57010318666` 均已验证是组合SHA的祖先，来源历史保留。
- B包三股600519/000001/300750各437行，2024-12-02～2026-09-16；六份raw/normalized SHA-256与此前独立确认值一致，三对仅有4/2/6规范舍入差异。量化输入使用normalized；腾讯为交付来源，运行时东财未改。
- 请求固定窗口2025-07-04～2026-08-31；参数分别为默认5/20、10/30、20/60且资金200000/成本0.002/滑点0.001。前两组资金100000/成本0.001/滑点0。
- 核心12个文件仍逐字节匹配C算法92df017；新批次工具及B数据/迁移证据已在D树，关闭此前缺失项。页面源码的标签已是“C输入快照哈希”，关闭源码标签项，实际页面总体验收仍由A负责。

## C 独立执行结果

| 检查 | 本轮实际结果 |
|---|---|
| 精确D归档完整pytest | **542 passed**，compileall exit0；原始295文件未修改 |
| 新批次离线工具 | **9/9**；保存JSON重新读取及输入快照重算一致 |
| 直接计算 vs POST | 全部C结果字段值和类型精确一致；API五参数投影单独精确核对；完整437行直接计算与B取出窗口计算也一致 |
| MySQL持久化/GET | **MySQL 8.0.31**，仅新建唯一隔离库；9组分别dispose engine、重建engine/session再经实际FastAPI GET读取；完整c_result与direct递归值/类型一致，exact=true |
| 输入哈希、订单、三曲线 | 各路径输入哈希一致，完整订单及三条曲线逐值/类型一致；每条283点 |
| 历史不重算 | 详情及列表GET禁用回测服务解析仍成功；11条记录=2条迁移夹具+9条新回测 |
| 数据独立回读 | 三股各437行重建会话仓储读回与normalized值一致，amount/turnover_rate的null保留 |
| 默认AI隔离 | C/D **7项**兼容检查通过：SQLite、合成数据、假LLM，包含自定义回测不污染默认AI、历史重建连接读取和禁止外部重算 |
| 真实V1→v8附加检查 | 真实V1六模型基线，旧15/13列保全；v2/v3在本步骤创建；注入v8回填失败仍版本7，重试恢复8；旧记录状态正确；重复迁移结果文本和版本时间不变 |
| 日历刷新回归 | 同一确定性探针 **6/6**，原静态trade_dates.refresh()失败项已修复 |

HTTP检查使用ASGI transport调用实际路由并接入真实MySQL；市场输入使用只读MySQL仓储适配器固定为交付包。它不验证运行时Eastmoney、交易日历完整性、真实TCP服务器重启或浏览器链路。未触碰已有应用库，未执行DROP。

## 九组结果

| 股票/参数 | 收益率 | 订单 | 已完成往返 | 实际预热条数 | 每条曲线点数 | 对账 |
|---|---:|---:|---:|---:|---:|---|
| 600519-default | -10.4591% | 18 | 9 | 20 | 283 | 通过 |
| 600519-ma10-30 | -20.4053% | 14 | 7 | 30 | 283 | 通过 |
| 600519-ma20-60-cost | -12.6368% | 7 | 3 | 60 | 283 | 通过 |
| 000001-default | -4.5805% | 21 | 10 | 20 | 283 | 通过 |
| 000001-ma10-30 | -6.2144% | 11 | 5 | 30 | 283 | 通过 |
| 000001-ma20-60-cost | -3.6215% | 7 | 3 | 60 | 283 | 通过 |
| 300750-default | 7.5449% | 18 | 9 | 20 | 283 | 通过 |
| 300750-ma10-30 | 17.2570% | 12 | 6 | 30 | 283 | 通过 |
| 300750-ma20-60-cost | 25.4583% | 5 | 2 | 60 | 283 | 通过 |

订单为奇数时存在未平仓头寸，策略不强制期末卖出；不将订单数直接当往返数。此窗口结果不应被V1的33分/24订单/12往返/403点替代。

## 复验说明与证据范围

离线工具默认`data_mode=input_json`，B实际传入frame标为`dataframe`；该字段进入输入快照哈希，因此初轮离线哈希与API不同，金融结果不变。随后明确使用`--data-mode dataframe`重跑，**九组离线完整对象与direct/POST/GET精确一致**，包括哈希。此标签是输入元信息，不改变manifest的腾讯来源。首次在无Git元数据的归档运行离线工具时仅失败于工具的Git溯源步骤；随后在同一SHA的独立detached worktree执行成功，未改验收工具。

```powershell
python scripts/validate_v2_c_acceptance.py --delivery-dir docs/evidence/c-delivery-20260917 --expected-hashes CONFIRMED_HASHES.json --output-dir NEW_OUTPUT --filename-template '{code}_qfq_normalized_20241201_20260916.json' --data-mode dataframe --start-date 2025-07-04 --end-date 2026-08-31
```

CONFIRMED_HASHES取[独立六哈希记录](evidence/c-final85-20260917/package-audit.json)中的six_hashes映射。完整27份direct/POST/GET原始对象保留在本地隔离证据目录；其SHA-256索引、逐案断言与公开精简结果见[跨路径一致性](evidence/c-final85-20260917/cross-path-equality.json)、[MySQL证据](evidence/c-final85-20260917/mysql-acceptance.json)、[离线矩阵](evidence/c-final85-20260917/offline-summary.json)。公开记录已去除本机绝对路径、隔离库名和连接信息。

**C可以对以上SHA及批次签署固定样本量化验收通过。** D新留言中的实时三股K线HTTP502、实时AI502/50001仍未通过；B复审并发实现、A最终页面、用户最终验收仍由对应方完成。保留PR #10 Draft。后续组合代码或输入数据变化，须按新SHA/新数据复验受影响项，不能沿用本签字宣称新版本通过。仅追加C证据文档不要求D再合入后重新冻结同一已测代码。

[进度看板](C_PROGRESS.md) · [机器可读证据摘要](evidence/c-final85-20260917/summary.json)
