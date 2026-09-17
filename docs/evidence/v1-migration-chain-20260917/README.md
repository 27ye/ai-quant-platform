# V1 → v8 迁移全链路证据（独立 MySQL 8）

对应 D 的「真实环境验收」第 1 条：**「在独立 MySQL 8 数据库执行 V1→当前版本迁移和中断恢复场景」**。

- 运行时间：2026-09-17 08:31 (UTC+08) / `2026-09-17T00:31:30Z`
- 被测分支：`feature/v2-b-market-data` @ **`e4ef00060aef7a937c3086617256f9bfceda425a`**
- MySQL：**8.0.44**（独立探针库 `ai_quant_b_probe_v1chain_20260917`，`ai_quant` / `ai_quant_test` 全程未触碰）
- V1 基线来源 tag：`v1-frozen-package-r2` = `7157cf6abcdfba010bbbb164a460ccd9463e837f`
- 复现命令：`python scripts/verify_v1_migration_chain.py`
- 完整输出：[`run-output.txt`](./run-output.txt)　结果：**ALL CHECKS PASSED**

## 这份证据补的是哪个洞

B 之前的真实 MySQL 证据只覆盖 **v7 → v8**（中断恢复专项），我在上一轮回复里把它列为已知限制：
「v7→v8 增量，不是 V1→v8 全链路」。

根因是既有的迁移测试用**当前** ORM 元数据去建「V1」库：

```python
# tests/test_db_migrations.py::test_v1_database_upgrades_without_losing_tables（旧）
v1_tables = [Base.metadata.tables[name] for name in sorted(V1_TABLES)]
Base.metadata.create_all(bind=engine, tables=v1_tables)
```

而当前元数据里 `backtest_result` 已经带着 `semantics_version`、`data_meta`、`input_snapshot`、
`c_result`、`c_result_text` 等全部后续列。也就是说基线本身就已经是「最终形态」，
**v4 / v6 / v7 / v8 的 ALTER 步骤根本没有东西可加，等于从未被真正执行过**。

## 这次怎么做的

不再手写基线，而是**从 V1 的 tag 里把 V1 的六个 ORM 模型原样取出来**，注册到一个一次性的
declarative Base 上，再 `create_all`——即复现 V1 自己的 `apply_migrations` 行为
（`v1-frozen-package-r2:backend/app/db/migrations.py` 正是 `create_all(checkfirst=True)` + 版本 1）。

因此基线是 V1 **真实的列集合**，明确不含任何 V2 列。脚本对此做了可证伪断言：

```
[PASS] V1 created exactly the six V1 tables
[PASS] baseline has NO V2 columns on backtest_result :: 15 V1 columns
[PASS] baseline has NO V2 columns on ai_analysis :: 13 V1 columns
[PASS] baseline version is 1
[PASS] baseline is NOT current metadata :: so the v4/v6/v7 ALTER steps must really run
```

## 走完的链路与断言

```
V1 真实基线
  → 步骤 1..7（v4 快照列 / v5 AI 快照列 / v6 input_snapshot / v7 c_result）
  → 模拟 v8 中断（ALTER 已提交、回填未跑、版本仍未记）
  → 调用文档入口 apply_migrations 恢复
```

关键断言（节选，全部 PASS）：

| 阶段 | 断言 |
| --- | --- |
| 步骤 1..7 之后 | `c_result` 存在、**`c_result_text` 尚不存在**（v8 确实还没跑） |
| 中断态 | 列已存在、`schema_version` **仍为 7**、旧行文本仍为 NULL |
| 恢复 | `apply_migrations` 返回 8、版本记 8、`c_result_text` 为 **longtext**、旧行已回填 |
| 数据保全 | V1 的 `backtest_result` / `ai_analysis` 行**逐字段不变**；V1 行从未被回填触碰 |
| 契约读回 | V1 行 `c_result_available=false`；pre-v8 行 `available=true` / `exact=false`，封套可读 |
| 收敛 | 再跑 2 次迁移，行与版本完全不变 |

回填值即 MySQL 归一化后的 JSON（`99633.35582084299` → `99633.355820843`），旧行保持诚实的
`exact=false`——与 v8 的设计一致，不做「从近似值反推精确值」的伪造。

## 同时补的单元测试

`tests/test_db_migrations.py::test_a_genuine_v1_schema_is_upgraded_column_by_column`
用**冻结的 V1 DDL**（同一 tag 的真实列定义，逐列硬编码）建基线，断言
`c_result` / `c_result_text` / `data_meta` 在基线中**不存在**，迁移后 v4/v5/v6/v7/v8 的列全部出现、
V1 行数据存活。这样即使没有 MySQL 和 git，CI 也会守住「ALTER 步骤真的在跑」。

## 已知限制（如实标注）

- 探针库的步骤 1（`_migration_v1` = `Base.metadata.create_all(checkfirst=True)`）会顺带创建
  当前元数据里的 `stock_catalog_sync` / `stock_daily_sync`，因此 **v2 / v3 的原始 DDL 未被单独走到**。
  这是既有设计（收敛式迁移）的结果，不影响 V1→v8 的结论，但不宣称覆盖 v2/v3 的 DDL 路径。
- 本证据是**迁移链路**专项，不是新数据包验收，也不替代 C 的 9 组 API 复验或 D 的浏览器端到端。
- 未生成新真实数据包（上游数据源间歇性封锁中），600519 `2026-09-15` 旧包差异仍待新包关闭。
