# C 对 B821 交付与 D 集成缺口的复核

2026-09-17。B 三处逐股 source 残留已关闭，六份数据文件内容不变。当前需要 D 完成集成、公布最终 SHA 后，C 才能出最终验收结论。本轮只更新 C 文档与证据，算法保持不变。

## 版本与证据范围

| 对象 | 完整 SHA / 结论 |
|---|---|
| B 当前交付 | `821f322b988e8c1b1e3b6408185a41403e8b2cf4` |
| D PR #10 当前头 | `b4800149eeaa19037e665e3e40821462a6eabae6`，尚非本轮 C 最终签字版本 |
| C 核心 | `92df017404126e9af920e1ad82e4a136d813f8d1`，未改 |
| C 新批次验收工具 | `b2c372ebca1176194880e2eb88ab8b447b218fd8`，支持 `--filename-template` |
| A PR #13 本轮读取头 | `d7ba01c63eed07b23fff6939753d7ee591c140fb` |

与 B74c 相比，B821 只改四份文档和 manifest，无代码/测试变化。C 本轮核对逐股 source、六文件 SHA-256、D 递归目录树、导出/验收脚本与跨 fork 提交历史；不重复运行测试。此前 **369 tests / 真实 MySQL 35 项**仍绑定 [B74c 复核](C_V2_B74C_CORRECTION_REVIEW_20260917.md)；**三股九组 direct/POST/重建连接 GET**仍绑定 [D cc57482 + 新腾讯包候选预验](C_V2_B_TENCENT_REVIEW_20260917.md)，不能转写为 D b480014 或最终版本已通过。

## D 需要合入的实际范围

跨 fork 比较的共同 B 祖先为 `e4ef00060aef7a937c3086617256f9bfceda425a`。D 当前尚缺以下 **六个** B 提交，B 消息中的五项漏列了 `b7cb06a`：

1. `b7cb06a39f56142e51cbf6c8054b03785a9881a4`：真实 V1 迁移证据/基线测试。
2. `dedad60977511aae8237fc4bb84e7a5321490df1`：腾讯导出支持及新批次。
3. `5404c25c52f909ba603ed8be2513101fb5cb3419`：溯源与精度更正。
4. `74c74fb3370555aaf94d02bdbb0547c70ffe8b00`：迁移报告/断言补齐。
5. `d63aaa051e7e3f2426ebb806c36e2942e8664d31`：逐股来源说明更正。
6. `821f322b988e8c1b1e3b6408185a41403e8b2cf4`：B 文档更新。

D 树中尚无 `docs/evidence/c-delivery-20260917/`、`docs/evidence/v1-migration-chain-20260917/`、`scripts/verify_v1_migration_chain.py`；导出脚本无 `TencentQfqSource/--source`；B runbook 仍写 schema 1→4。建议 D 合入 B821 并保留来源历史，避免按不完整的五提交清单移植。

D 当前 `scripts/validate_v2_c_acceptance.py` 也尚无 C 已发布的 `--filename-template` 支持。建议一并集成 C 工具提交 b2c372e；若有冲突或采用外部验证工具，明确绑定工具 SHA，不能重命名原始证据文件来迁就旧脚本。新 C 进度文档可通过固定提交链接引用，无须为每条文档更新重新冻结代码。

外部 D 代码 + 外部 B 数据已能执行候选预验；此缺口影响最终交付树的可复现性和最终签字，不代表无法进行任何计算。

## 已关闭及需保留的口径

- B 的三处 `stocks[].source` 已与更正后的顶层 source_note 一致；旧错误句仅在显式历史更正记录内保留，关闭此前该项待办。
- 六份 raw/normalized 文件 SHA-256 均与首次交付相同，逐文件哈希见 [audit.json](evidence/c-b821-20260917/audit.json)。每股 437 行，区间 2024-12-02～2026-09-16。
- 腾讯是交付备用来源，不是东财四位价格精度的等价替代；amount/turnover_rate 为 null，change_pct 为派生值。应用运行时 Provider 未因此切换。
- 按 [B 转达的 D 采用决定](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5707362287)推进。当前读取的 PR #10/Issue #11 中未定位到 D 原始批准留言，请 D 在最终集成说明记录来源决定以便追溯，不要求重复审批。

## 两处交接说明需避免回退

1. **B 文档**：`docs/backend_status.md:81` 仍写 `max(ma_trend_period, ma_long_period+1)` 且称“C 已复验”。B 实际 `warmup_required_days` 与 C `required_warmup_rows` 均已按 **单次 V2 使用开始日前最后 long 条有效日线**实现；验收数据包 **≥120 条**是独立覆盖要求。请只修正文档，完整参数约束为 `2 ≤ short < long ≤ 120`。同文档第80行“已并入 PR #10”应区分早期已合入部分与本轮六项待集成内容。
2. **A 页面**：PR #13 上述 SHA 的 `frontend/src/views/BacktestDetailView.vue:134–135` 把 `data_meta.c_data_hash` 注释/标签写作“C 结果哈希”。应沿用已定契约 **“C 输入快照哈希”**，字段路径不变；请 A/D 合入时保留正确语义。见 [源码摘录](evidence/c-b821-20260917/A-hash-label.json)。

以上为文档/标签协调，不要求新增算法，也不否定 B 已通过的代码测试。C 不代改其他成员代码。

## 下一步

D 完成 B/C 必需内容集成并公布最终 40 位 SHA、批次及来源说明；A/D 收尾页面、真实 AI 与 CI。C 随后按固定 SHA + 数据批次执行三股三参数验收，比较完整结果、类型、输入哈希、订单、曲线、历史零重算与 AI/参数回测隔离，再签字。当前结论仍为候选技术预验通过，最终验收待完成。

[C 进度看板](C_PROGRESS.md) · [本轮证据摘要](evidence/c-b821-20260917/summary.json)
