# V3 B2 证据：v9 迁移（`analysis_mode` + `backtest_id`）独立验证

- 代码基线：`main` `26f422a6ebd64295a632cee5a92492ed3aacb62c`（V3 计划 PR #17 合并后）
- 变更：`backend/app/db/migrations.py`，`SCHEMA_VERSION` 8 → 9，新增 `_migration_v9`
- 契约：`docs/V3_DEVELOPMENT_PLAN.md` §5.3（D 拥有 ORM，B 独占迁移）
- 冻结列：`ai_analysis.analysis_mode VARCHAR(16) NULL`、`ai_analysis.backtest_id BIGINT NULL`

## 1. 真实 MySQL：V1 → v9 全链路

```powershell
.\.venv\Scripts\python.exe scripts\verify_v1_migration_chain.py
```

完整输出见 `mysql-v1-to-v9-run.txt`（未删改）。要点：

| 检查 | 结果 |
|---|---|
| 基线是 tag `v1-frozen-package-r2` 的真实 V1 结构 | PASS（`backtest_result` 15 列 / `ai_analysis` 13 列） |
| 步骤 1..7 之后 `c_result_text` 仍不存在 | PASS（v8 确实还没跑） |
| 模拟 v8 中断（列已提交、回填未跑）时版本仍为 7 | PASS |
| 文档入口恢复 → 当前版本（9） | PASS |
| **阶段 5b**：`analysis_mode` = `varchar(16)`、`backtest_id` = `bigint` | PASS |
| **阶段 5b**：V1 旧报告两列仍为 `NULL`（**未**回溯填 `standard`） | PASS（`analysis_mode=None backtest_id=None`） |
| V1 行全部原始列不变 | PASS（15 / 13 列逐一比对） |
| 重复迁移：全表所有行/列 + `schema_version` 每行 `version`+`applied_at` 不变 | PASS（9 个版本行） |

## 2. 离线回归（SQLite）

命令与输出见 `pytest-v9-run.txt`。新增/更新的用例集中在 `tests/test_db_migrations.py`：

- `test_v9_adds_mode_and_backtest_link_to_a_fresh_database`（**空库**，并断言两列可空）
- `test_v9_leaves_legacy_reports_and_c_exact_text_untouched`（**v8 存量库**：旧报告每个原值不变、两列保持 `NULL`、C 原文不重写、`backtest_result` 列集合不变）
- `test_v9_resumes_when_only_the_first_column_was_committed`（**只加完第一列就中断**：只补第二列，已提交的值不被覆盖）
- `test_v9_failure_mid_step_is_not_recorded`（**步骤全部成功后才记 v9**：中途失败版本仍为 8，重跑成功）
- `test_v9_is_repeatable_and_records_one_version_row`（**重复执行**只留一行 v9）
- `test_a_genuine_v1_schema_is_upgraded_column_by_column` 追加 v9 列断言（真实 V1 链）

`tests/test_c_result_lossless.py` 的两个 v8 中断用例按 v9 调整：回退版本时改为删除 `version >= 8` 的**所有**行。只删第 8 行会让 `MAX(version)` 仍报 9，文档入口于是跳过 v8——那恰好使这两个用例失去覆盖对象。

## 3. 边界与未覆盖项

- 真实 MySQL 上**没有**单独构造「v9 只加完第一列」的中断库；该场景由 SQLite 用例覆盖（`_add_missing_columns` 按列存在性判断，与方言无关），MySQL 侧的同类中断由 v8 阶段实测。
- D 的 ORM 列（`models/ai_analysis.py`）不在本次变更内。迁移对「ORM 是否已带该列」两种情形都收敛：空库由 v1 建表后 v9 补齐，ORM 已带列时 `ALTER` 为空操作。
- 未跑 `docs/V3_DEVELOPMENT_PLAN.md` §9 的浏览器/前端项（非 B 范围）。
- 探针库 `ai_quant_b_probe_v1chain_20260917` 为独立库，`ai_quant` / `ai_quant_test` 未被触碰。
