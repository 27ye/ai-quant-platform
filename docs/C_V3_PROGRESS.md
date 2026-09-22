# C V3 进度

分支：`feature/v3-c-macd`；基线 main `26f422a6ebd64295a632cee5a92492ed3aacb62c`；日期2026-09-22。

| 任务 | 当前状态 | 证据 / 下一步 |
|---|---|---|
| C1 MACD契约与手算 | 已完成，PR #18 | C_V3_MACD_CONTRACT.md；B可按新签名并行适配 |
| C2 引擎及回归 | 完成；全量677通过 | 代码SHA `6a84901c82256b7d48dfab3ebee3208633e5058c`；三股15份旧MA/默认评分结果完整JSON指纹不变 |
| C3 对照/AI数值口径 | B21闭环；D22原三项闭环但新增除零错误响应回归；A23区间投影待修 | B+C 703通过/1跳过；D新+C 716通过；专项回归证据见下 |
| C4 最终数值验收 | B19/B21已合入；新main+C兼容预验通过，最终组合待集成/门禁 | main10283b0+C：708通过/1跳过，九组HTTP/精确GET/历史参数再次POST通过；最终签字待D冻结SHA |

今日C可独立交付部分已完成：算法、117项新增测试、既有回归、三股三组MACD参数证据、数值对接示例。详见 [模块验收记录](evidence/c-v3-macd-20260922/README.md)。前端类型/构建、compileall和既有量化/AI历史兼容脚本通过。只补文档/证据的提交与被测代码SHA分开记录；任何生产代码变动需重新验证。
未宣称：HTTP已支持MACD、数据库新增字段已保存、页面/真实AI已验证或V3整站已完成。没有合并任何PR。

追加远端核对：B PR #19 `fa91f4c...`（v9迁移）与C隔离组合 **682 passed**；10份MACD/MA结果经临时SQLite新engine/session完整读回一致。但B当前HTTP仍拒绝strategy，MACD接线明确待完成。详见 [远端接口对接清单与证据](evidence/c-v3-remote-contract-20260922/README.md)。C已发布签名/错误码/六参数/版本及精确快照边界，并请求B/D按实现SHA闭环。

**最新状态（替代上一条“strategy尚未接线”的状态）：** B PR #21 `11a0c03ecca56fe667b845a976afd1cdde9197b7`已接线；C独立叠加复验 **696 passed, 1 skipped**。三股九组直接计算→HTTP POST→新SQLite连接HTTP GET的精确C结果一致；但MACD缺失/null日期被自动补齐落库，历史GET实际参数12字段与POST6字段不一致，已记录为需修改，不能签全面对齐。确认缺C实现50004及只转发显式MACD字段。详见 [PR21实测与两项整改](evidence/c-v3-b21-review-20260922/README.md)。C算法仍为6a84901，等待B修复SHA；未修改B生产文件。

**D 新交付复核：** PR #22 `bf7cd54a7694728e48937ce9d8f54a5ae4a12714`原版596通过，叠加C quant后713通过；两种环境各9组MA数值→归一化Prompt→快照→新SQLite连接GET一致，独立context_hash验证通过，MACD按首版范围拒绝40007。发现保存结果的收益/回撤/往返数与曲线或订单矛盾时仍会调用LLM并保存，已形成D整改证据；不修改C算法或D生产代码。详见 [PR22数值复核](evidence/c-v3-d22-review-20260922/README.md)。B PR21仍未出修复SHA，最终接口对齐与C4签字继续等待对应修复及最终集成版本。

**当前最新状态（替代上文B两项待修状态）：** B21 `0360b699f6530aefd5afe5e11e859f4c179146d8` + C独立复验 **703 passed, 1 skipped**；三股九组精确结果、六参数历史回读及再次POST均一致，五种日期缺失/null全部40001且取数/落库0，MA默认补值保留。C对B两项整改已闭环。A23 `6daa211...` 对照页把顶层实际日期显示为请求区间，并读取不存在的actual_*而显示实际区间为空，已用真实HTTP字段与A原始投影函数复现，需A修正。D22尚无新SHA，数值矛盾拦截问题仍待修。详见 [B修复与A字段复核](evidence/c-v3-b21-fixed-20260922/README.md)。算法保持6a84901，最终组合C4未签。

**D修复最新复验：** D22 `7530d0180c32377fc763951e4ece828fc59b63c0` + C **716 passed**；三股九组正常链路通过，原收益/回撤/往返数三项反例均50002/LLM0/新报告0，已闭环。新增除法对损坏记录initial_cash=0抛出未捕获ZeroDivisionError（旧版为JSON50002），请D补除法前校验。D已决定v9以B PR19为唯一来源，去重/rebase是后续集成动作，不宣称已完成。A区间映射待修，B批准保持。详见 [D修复及零资金回归](evidence/c-v3-d22-fixed-20260922/README.md)。C算法不变。

**D22文档跟进：** 当前远端头为`44ca75aaa0c1908fb41a7ee11d620f17cfb43488`，相对7530d01仅修改`docs/V3_D_AI_BACKTEST_ACCEPTANCE.md`；`git diff --exit-code 7530d01 44ca75a -- backend tests scripts frontend`为0。不是新的代码修复，无需重复全量测试。D comment5776901638要求的7530d01复验已完成（716项及三项原反例通过）；文档“C需按7530d01复验”应更新为“C已复验，待D补零资金损坏记录50002错误契约”。仍保留review5278362407，待真正代码修复SHA；不把本次文档SHA标为新跑716项。A/B独立审阅及迁移去重为其他成员待办，C不代签。

**B合入后最新状态：** D已合并PR19/PR21，main为`10283b079f686cb8310bf18125d7992b60979293`。C对干净main的入口兼容4项通过；隔离叠加C quant后 **708 passed, 1 skipped**，三股九组POST/新SQLite连接GET及历史六参数再次POST一致。C18尚未合入，main当前缺C MACD时50004为预期部署缺口；本次预验支持D后续审阅/集成C18，不自动合并。D22零资金回归及A23窗口映射仍待修，D22迁移去重待执行。详见 [实际main+C兼容证据](evidence/c-v3-main-bc-20260922/README.md)。C算法不变，最终C4未签。
