# V2 B 侧运行与验证说明

> 适用分支：`feature/v2-b-market-data`（基线 `8062599` = V1 合并后）。
> 本文覆盖 B（后端与数据）负责的迁移、目录同步、行情刷新、数据状态与回测历史。

## 1. 环境准备

```powershell
# 项目根目录；数据库连接来自 .env（MYSQL_HOST/PORT/USER/PASSWORD/DATABASE）
$env:MYSQL_DATABASE="ai_quant_test"   # 本地验证建议用独立库，不要动 ai_quant
```

- MySQL 8（本机可用 `MySQL80` 服务，或 D 的独立验收实例 `127.0.0.1:3307`）。
- Python 依赖已在 `.venv`；LLM Key 只放个人 `.env`，不进入 Git。

## 2. 迁移（schema_version 1 → 8）

```powershell
.\.venv\Scripts\python.exe scripts\migrate_db.py
```

- 分步执行：每步独立事务，**成功后才写版本号**；失败不记录，重跑从失败步恢复。
- 既有 V1 库升级会**保留旧数据**；`apply_migrations` 末尾有收敛遍历，版本行与实际结构不一致时也会补齐。
- 升级演练建议在带 V1 数据的独立库先行执行，保留备份/恢复步骤，脚本不删旧数据。

| 版本 | 内容 |
|---|---|
| v1 | 六张 V1 基础表 |
| v2 | `stock_catalog_sync` |
| v3 | `stock_daily_sync` |
| v4 | `backtest_result` 快照列（曲线/订单/生效参数/数据元信息） |
| v5 | `ai_analysis` 快照列（`context_snapshot`/`context_hash`/`source_mode`/`data_as_of`/`prompt_version`/`context_schema_version`/`output_schema_version`） |
| v6 | `backtest_result.input_snapshot`（交给 C 的确切输入行，含预热） |
| v7 | `backtest_result.c_result`（C 完整结果的 JSON 回退列） |
| v8 | `backtest_result.c_result_text`（**LONGTEXT**，精确原文）+ 旧行回填 |

### 2.1 V1 → v8 全链路已在真实 MySQL 验证

```powershell
.\.venv\Scripts\python.exe scripts\verify_v1_migration_chain.py
```

- 基线不是"当前元数据"，而是**从 tag `v1-frozen-package-r2` 取出的六个 V1 模型**（`backtest_result` 15 列 / `ai_analysis` 13 列，不含任何 V2 列），因此 v4/v6/v7/v8 的 ALTER 真的被执行。
- 覆盖：V1 基线 → 步骤 1..7 → **模拟 v8 中断**（列已提交、回填未跑、版本仍 7）→ 文档入口恢复；全部 V1 列逐一比对不变；重复迁移全表所有行/列与 `schema_version` 每行 `version`+`applied_at` 不变。
- 证据：`docs/evidence/v1-migration-chain-20260917/`（README + 运行输出）。

> **v8 为什么要用 LONGTEXT**：MySQL 的 JSON 列把数值叶子归一化到约 15 位有效数字（实测 `99633.35582084299` → `99633.355820843`），无法精确回读 C 的结果。新记录只写 `c_result_text`（`c_result` 留 NULL），v8 之前的旧行由 JSON 列回填并以 `c_result_exact=false` 如实标注。

## 3. 股票目录同步（搜索不再依赖实时源）

```powershell
.\.venv\Scripts\python.exe scripts\sync_stock_catalog.py            # 同步（低频、手动）
.\.venv\Scripts\python.exe scripts\sync_stock_catalog.py --show-state  # 只看状态
```

- 主站（`stock_zh_a_spot_em`）优先；失败自动回退**同源**延迟主机 `clist` 分页（单页上限 100）。
- 完整性判定：**≥1000 行**且代码唯一才算成功；否则记 `failed` 且**不写部分目录**。
- 实测：5915 只、34.6 秒、来源 `push2delay.eastmoney.com/api/qt/clist/get`。

## 3.1 多股票预热（V01/V02 交付前必做）

```powershell
# 验收三只（600519 / 000001 / 300750），单轮，股票间隔 5 秒
.\.venv\Scripts\python.exe scripts\warm_market_data.py
# 源抖动时的低频重试：3 轮，轮间隔 600 秒；成功即提前结束
.\.venv\Scripts\python.exe scripts\warm_market_data.py --rounds 3 --interval 600
```

- 逐只输出 `rows/window/mode/source/秒数`，失败如实输出错误并**以退出码 1 结束**（不缺报成成功）。
- 只影响"首次取数"：已入库股票走缓存，源不可用时仍能服务。
- 该脚本即 `docs/V2_B_DATA_EVIDENCE.md` 中 300750 恢复方案的落地形式。

## 3.2 交付包导出与校验（C 对接）

```powershell
# 导出（默认来源 = 应用自己的东财 Provider）
.\.venv\Scripts\python.exe scripts\export_c_delivery.py --batch 20260917 `
    --start-date 2024-12-01 --end-date 2026-09-16 --last-complete-trading-day 2026-09-16

# 备用来源：仅当东财 kline 端点不可用时使用（见 §5 与 docs/B_DATASOURCE_DIAGNOSIS.md）
.\.venv\Scripts\python.exe scripts\export_c_delivery.py --source tencent --batch <id> `
    --start-date 2024-12-01 --end-date 2026-09-16 --last-complete-trading-day 2026-09-16

# 校验 raw / normalized 是否只差规范 4/2/6 舍入（复用生产 _round_daily，非第二套规则）
.\.venv\Scripts\python.exe scripts\verify_c_delivery_consistency.py --dir docs\evidence\c-delivery-20260917
```

- `--last-complete-trading-day` **必填**：缺失时在**任何 I/O 之前**以退出码 2 拒绝，避免把未收盘的当日快照当作最终数据发布。
- **一次取数、两处输出**：同一批 provider 行派生 `*_raw`（原精度）与 `*_normalized`（4/2/6），从根上消除"raw 直连 / normalized 走库内缓存"的双源快照差异。
- 批次目录**独占**：目标目录已存在且非空会被拒绝，不会就地覆盖上一批的哈希清单。
- 失败批次只写 `status=failed` 的 manifest、**不落数据文件**；文件名形如 `{code}_qfq_{raw,normalized}_{window}.json`。
- **`--source tencent` 是交付专用备用来源，不改变应用运行时 Provider**：`StockService` 仍是单厂商（东财 + 同源 `push2delay` 回退），Provider 失败仍如实抛 `50001`。该来源与东财**不是等价替代**——436 个共同交易日中 378/209/327 行（600519/000001/300750）OHLC 原值不同（最大 ~0.004 元），成交量一致、仅 2 位舍入后一致，而交付精度是 4 位；`amount`/`turnover_rate` 该端点不发布（C 侧列为可选），`change_pct` 为派生值。这些都写在 manifest 与批次 README 中。

## 4. 启动与验证

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# 前端（frontend 目录）
npm run dev
```

验证入口：

```powershell
# 搜索（本地目录，不再调用全市场 Provider）
curl.exe "http://127.0.0.1:8000/api/v1/stocks/search?keyword=宁德"
# 数据状态（来源/覆盖/新鲜度）
curl.exe "http://127.0.0.1:8000/api/v1/stocks/600519/data-status"
# 回测（v2_windowed：显式 parameters）
curl.exe -X POST "http://127.0.0.1:8000/api/v1/backtests" -H "Content-Type: application/json" `
  -d '{\"stock_code\":\"600519\",\"start_date\":\"2025-09-01\",\"end_date\":\"2026-08-31\",\"parameters\":{\"ma_long_period\":120}}'
# 回测历史（读取快照，不重算）
curl.exe "http://127.0.0.1:8000/api/v1/backtests?stock_code=600519"
```

## 5. 数据源现状与已知限制（重要）

| 现象 | 说明 |
|---|---|
| `push2` / `push2his` 间歇性 `RemoteDisconnected` | 主站可用性呈**间歇窗口**；同一分钟内不同股票可能一个成功一个失败，与股票无关 |
| 延迟主机 `clist` | 可达，但单页硬上限 100 → 只用于**离线目录同步**，不用于在线搜索 |
| 延迟主机 `kline` | `rc=0` 但 `dktotal=0`（限流后恒空）→ 抛 `50001`，不伪装成空数据 |
| 已有缓存 | **缓存优先**：已入库的股票在源不可用时仍可服务；未入库的股票首次取数依赖可用窗口 |
| 失败语义 | 数据源失败 `50001`、数据库失败 `50002`、数据不足 `40003`；三者不互相伪装 |

运维建议：目录同步与多股票取数**低频执行**；不要在源抖动时高频重试（会加重限流）。

## 6. 当前证据（B 侧）

> 下表为**当前**状态。早期版本（243 行、300750 取数失败、迁移只到 v4/v5）已被后续验证取代；
> 历史口径保留在 `docs/V2_B_DATA_EVIDENCE.md` 对应段落，不静默改写。

| 编号 | 证据 |
|---|---|
| V01 | 600519 / 000001 / 300750 **各 437 行**真实日线（2024-12-02 ~ 2026-09-16），见交付包 |
| V02 | 两轮低频探测（间隔 32 分钟）见 `docs/V2_B_DATA_EVIDENCE.md`；2026-09-16/17 东财 **kline 端点**长时段不可用与替代来源分析见 `docs/B_DATASOURCE_DIAGNOSIS.md`。**⚠️ 那两轮证据绑定的是当时的被测 SHA，不是最终候选**；实时链路当前不可用（D 的门禁同因此为红），**V02 必须在最终 SHA 上复验**，不得把旧证据当作最终通过 |
| V03 | 注入超时/畸形报文/数据库失败的用例见 `tests/test_provider_retry.py`、`tests/test_stock_catalog.py`、`tests/test_data_status.py`；**API 层错误码契约**见 `tests/test_v2_error_contract.py`（B 侧实际码：`40001`/`40002`/`40003`/`40005` backtest not found/`50001`/`50002`/`50003`/`50004` backtest error/`50005`/`50006` 目录从未同步；**`40006` report not found 属 D 侧 AI 报告链路，B 分支上不存在**），且失败不留下成功记录 |
| V04 | 省略 `parameters` 的旧请求与 V1 冻结基线一致（`final_equity 90834.22588204397`、12 次往返/24 条订单） |
| V05 | 两组参数产生独立 `backtest_id`；详情 0.02s 读快照；未知 ID `404/40005` |
| V09 | 空库初始化、**V1 库升级 1→8**（全部 V1 列逐一比对不变）、重复执行、**v8 中断恢复**、旧记录缺快照标注；证据 `docs/evidence/v1-migration-chain-20260917/` |
| 交付包（新） | `docs/evidence/c-delivery-20260917/`：三股×437 行，`raw`/`normalized` **三对全部一致**、`rounding_problems` 空、独立 MySQL 回读 `ok`。**来源为 `tencent`（备用来源，非东财）**，溯源与精度差异见包内 README |
| 交付包（旧） | `docs/evidence/c-delivery/`：**保留为历史证据，未修改**。其三对中有 1 对（600519 `2026-09-15`）不一致——该行 `normalized` 是库内 09:46 盘中快照 |

## 7. 与 D 的 V2 分支（`feature/v2-d-report-history`）集成注意事项

> **状态（2026-09-17）**：下表的四项均已按 D 的阶段计划收口，保留在此作为历史记录；
> 当前集成以 PR #10 为唯一入口，B 的分支供 D 合并。

B 曾在本机做集成预演（`feature/v2-b-market-data` + D 分支）。当时需处理三处：

| 冲突/缺陷 | 处理 |
|---|---|
| `db/migrations.py` | 采用 **B 的统一分步迁移**（D 分支独立重写的 v1→v2 被取代）。AI 快照列已作为 **v5** 纳入同一序列；`apply_migrations` 末尾有收敛步骤，即使版本行与实际结构不一致（两边都曾用「v2」表示不同内容）也会补齐缺失表/列 |
| `core/errors.py` | **D 的 `ReportNotFoundError` 需从 `40005` 改为 `40006`**：`40005` 已被 `BacktestNotFoundError` 占用。契约口径：`40005 = backtest not found`、`40006 = report not found` |
| `services/market_data_service.py` | 保留双方：D 的 `get_query_provenance()`（请求内来源，供 AI 快照）与 B 的 `stock_daily_sync`（持久来源，供 data-status）并存，互不替代 |
| 相关测试 | `tests/test_db_migrations.py`（AI 列现在是第 5 步）、`tests/test_ai_api.py`（报告不存在断言改为 `40006`） |

建议合并次序：**先合 B 的迁移与数据服务，再让 D 的分支 rebase/合并**，由 D 按上表调整三处即可全绿。
