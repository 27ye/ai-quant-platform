# C V3 进度

分支：`feature/v3-c-macd`；基线 main `26f422a6ebd64295a632cee5a92492ed3aacb62c`；日期2026-09-22。

| 任务 | 当前状态 | 证据 / 下一步 |
|---|---|---|
| C1 MACD契约与手算 | 已完成，PR #18 | C_V3_MACD_CONTRACT.md；B可按新签名并行适配 |
| C2 引擎及回归 | 完成；全量677通过 | 代码SHA `6a84901c82256b7d48dfab3ebee3208633e5058c`；三股15份旧MA/默认评分结果完整JSON指纹不变 |
| C3 对照/AI数值口径 | 契约、MA/MACD数值示例已交付；跨模块复核待实现 | C_V3_NUMERIC_MAPPING.md；证据目录的两个numeric_example.json |
| C4 最终数值验收 | C离线三股三参数通过；最终组合待B/D/A | 每组283曲线点、完整快照重放一致；最终POST/GET、AI隔离、浏览器需按集成SHA复验 |

今日C可独立交付部分已完成：算法、117项新增测试、既有回归、三股三组MACD参数证据、数值对接示例。详见 [模块验收记录](evidence/c-v3-macd-20260922/README.md)。前端类型/构建、compileall和既有量化/AI历史兼容脚本通过。只补文档/证据的提交与被测代码SHA分开记录；任何生产代码变动需重新验证。
未宣称：HTTP已支持MACD、数据库新增字段已保存、页面/真实AI已验证或V3整站已完成。没有合并任何PR。

追加远端核对：B PR #19 `fa91f4c...`（v9迁移）与C隔离组合 **682 passed**；10份MACD/MA结果经临时SQLite新engine/session完整读回一致。但B当前HTTP仍拒绝strategy，MACD接线明确待完成。详见 [远端接口对接清单与证据](evidence/c-v3-remote-contract-20260922/README.md)。C已发布签名/错误码/六参数/版本及精确快照边界，并请求B/D按实现SHA闭环。
