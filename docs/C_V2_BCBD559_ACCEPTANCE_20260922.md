# C：bcbd559 验收结论与 B 方案对比

2026-09-22。**组合 `bcbd559acb67d3435fe7a840f34ad73bbe35bbad` + `c-delivery-20260917`：C 固定批次九组通过，C 提出的两处运行时阻塞关闭。** 不代表实时 Provider、真实 LLM、浏览器或整体 V2 已通过。

## 版本与证据边界

本轮开始时 D 为 f465ee3，C 已完成该树复验，两处运行时问题仍存在；随后 D 发布 `fe8c0b4` 修复与 `bcbd559` 集成头，C 在新独立检出目录重新执行。先前 [f465ee3 阶段报告](C_V2_F465EE3_REVIEW_20260922.md) 保留历史范围，当前结论以本页为准。

B 同期在 [5769671207](https://github.com/27ye/ai-quant-platform/issues/15#issuecomment-5769671207) 发布独立方案 `cb2cfeb6a495c5311108b5cad3c7179448b1a0aa`，C 已获取其完整树并运行同一扩展探针。未合入/修改 B 或 D 的生产代码。

## C 独立通过项

- **557 pytest passed**，1 条既有 AnyIO 弃用提示，compileall 通过；Python 3.12.10。
- 12 个 C 核心文件及固定包未变，六份 JSON SHA-256 与原始记录一致。
- **MySQL 8.0.31** 新建隔离库：三股各 437 行回读一致，V1→v8、中断恢复、原列与旧记录保全、重复迁移通过。未修改原项目库。
- **三股×三参数 9/9**：完整包 direct = B 取数窗口 direct；实际 FastAPI ASGI POST 与 C 字段值/类型一致（参数五字段投影单独验证）；dispose 并重建 engine/连接后 GET 的完整 c_result、类型、哈希、订单和三条曲线一致，每曲线 283 点。九组 direct 与 119a10c 逐字节一致，历史 GET/列表禁用回测服务解析仍成功。
- **SQLite 与真实 MySQL 各 12/12 运行时探针通过**：双向切源/同源重定基整段替换、成功来源 SQL 失败后完整回滚、正常已完成日缓存/缺日回源、已知上游缺日拒绝、上海 18:00/周末边界，以及下面两处原缺陷和新增中间/末端缺日变体。
- **历史读取无 LLM 依赖**：空 LLM 配置，实际 ASGI+MySQL 完整合成 legacy 报告列表/详情 200，缺失 404/40006；禁止构造生成/LLM/Provider/上下文依赖，调用数为零。生成入口缺配置为 500/50005，重连后 AI 行不变。此检查不是生成两份真实报告。
- **另 7 项 C/D 离线兼容检查通过**：SQLite、合成输入、假 LLM；默认 AI/参数回测隔离与历史快照验证。

固定九组使用冻结仓储适配器与实际 ASGI 路由；运行时探针使用严格按日期范围返回的合成 Provider，经真实 StockService/MarketDataService。未把这些结果记作实时网络或浏览器通过。

## 原两处阻塞关闭

1. 旧缓存 09-16/09-18、缺 09-17，completed_through=09-17：新实现把同一次 query 的完成日传给 sync，union 后再次限制上限，并在校验前过滤超过 fetch_end 的行。探针返回 16/17 日；项目新增回归同时断言落库脏尾删除。
2. union 的可信日历覆盖返回 None：新实现在回源/破坏性替换之前拒绝，原日期、价格、成功来源保留。旧“仅缺少 callable”与“Provider 越界”不是本次触发前提。

新实现没有因为旧测试期待未知覆盖时成功回源，就放弃覆盖门槛；相关测试已按新整段破坏性替换的保守失败语义调整。

## B 方案：起点保护不足以替代覆盖证明

B `cb2cfeb` 已通过 C 原始两条场景，但仍跳过 expected=None，只检查新起点是否晚于旧起点。我们补测两个有相同起点的反例：

| 场景 | B cb2cfeb（SQLite） | D bcbd559（SQLite/MySQL） |
|---|---|---|
| 原缓存 01-06/07/08/09，新批次 06/08/09，union 覆盖未知 | 成功替换，07 日丢失 | 拒绝，旧四行与来源保留 |
| 原缓存 01-06/07/08/09，新批次 06/07，union 覆盖未知 | 成功替换，08/09 日丢失 | 拒绝，旧四行与来源保留 |

两例均已注入 TradingCalendarProvider，日历可确定完成日但不能包住 union 开始日；Provider 严格遵守请求范围，返回数量满足 min_rows。因此“末端已被日历管住”在 expected=None 时不成立，保留起点也不能证明中间数据完整。B 比较仅新增 SQLite 定向实测，未重复其全量 557 项或声称在 MySQL 验证 B 分支。

**建议保留 D 已集成并经 C 复验的实现，不把 B cb2cfeb 整包覆盖回 D。** B 可保留独立分支供审阅，转为复审 D 当前头；无需继续两套实现并行。起点/端点保护可以是额外检查，不能用来撤销未知覆盖的拒绝规则。

## 后续与签字

C 本页签字仅绑定本 SHA、固定批次和列出的定向场景；原两项 C 阻塞关闭，C 不再以它们阻挡当前组合。直接 sync 无可信日历注入等额外入口加固、data-status 与展示一致性不因本轮场景通过而自动宣称覆盖。

请 D 同步 PR #10 的实际 SHA（处理期间页面正文仍写 f465ee3），登记 C 已通过范围；B 复审当前 D 实现；A/D 按原分工完成实时三股、真实 LLM/报告重启回读和关闭 Mock 页面验收。剩余整体门槛完成前 PR #10 继续 Draft，不执行合并。若生产代码再变，C 依据新 SHA 复验受影响项。

## 证据

[结论](evidence/c-bcbd559-20260922/summary.json) · [九组/迁移](evidence/c-bcbd559-20260922/mysql-acceptance.json) · [MySQL 12 场景](evidence/c-bcbd559-20260922/runtime-mysql.json) · [SQLite 12 场景](evidence/c-bcbd559-20260922/runtime-sqlite.json) · [B 对比反例](evidence/c-bcbd559-20260922/B-cb2cfeb-comparison.json) · [历史依赖](evidence/c-bcbd559-20260922/history-dependency-probe.json) · [源码与包](evidence/c-bcbd559-20260922/source-audit.json)

SQLite 复现：`python docs/evidence/c-bcbd559-20260922/runtime_probe.py --source CHECKOUT --output NEW_JSON`。CHECKOUT 使用上述 D 或 B 完整 SHA；探针读取 git HEAD 写入结果。退出 0 表示诊断完成，须读取 `all_contracts_met`：D 为 true、B 为 false。MySQL/历史探针需各自隔离连接配置与夹具；没有公开本机库名或凭据。
