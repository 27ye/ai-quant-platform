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
| v9 | `ai_analysis.analysis_mode`（`VARCHAR(16) NULL`）+ `ai_analysis.backtest_id`（`BIGINT NULL`）——V3 F4；**两列均可空，旧报告不回溯填充** |

### 2.1 V1 → v9 全链路已在真实 MySQL 验证

```powershell
.\.venv\Scripts\python.exe scripts\verify_v1_migration_chain.py
```

- 基线不是"当前元数据"，而是**从 tag `v1-frozen-package-r2` 取出的六个 V1 模型**（`backtest_result` 15 列 / `ai_analysis` 13 列，不含任何 V2 列），因此 v4/v6/v7/v8/v9 的 ALTER 真的被执行。
- 覆盖：V1 基线 → 步骤 1..7 → **模拟 v8 中断**（列已提交、回填未跑、版本仍 7）→ 文档入口恢复 → **v9 一并生效**；全部 V1 列逐一比对不变；重复迁移全表所有行/列与 `schema_version` 每行 `version`+`applied_at` 不变。
- V3 新增的阶段 5b：v9 两列以 `varchar(16)` / `bigint` 出现，且 **V1 旧报告的两列仍为 `NULL`（不回溯填 `standard`）**。
- 证据：V2 期 V1→v8 见 `docs/evidence/v1-migration-chain-20260917/`；**V3 期 V1→v9 运行输出见 `docs/evidence/v3-b-v9-migration-20260922/`**（同一脚本、真实 MySQL）。

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
- **交付工具与运行时分别溯源**：`--source tencent` 只决定本次导出批次的来源；从 D 的 `0c66c7d` 起，运行时 Provider 也可在东财 K 线瞬时失败后独立请求腾讯 qfq。两者不能相互证明成功；运行时失败仍抛 `50001`。腾讯与东财**不是等价替代**——436 个共同交易日中 378/209/327 行（600519/000001/300750）OHLC 原值不同（最大 ~0.004 元），成交量一致、仅 2 位舍入后一致，而交付精度是 4 位；`amount`/`turnover_rate` 该端点不发布（C 侧列为可选），`change_pct` 为派生值。这些都写在 manifest 与批次 README 中。混源缓存及盘中完整性判据仍按 `V2_B_DATA_CONTRACT.md` §2.1 追踪。

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
| V09 | 空库初始化、**V1 库升级 1→9**（全部 V1 列逐一比对不变）、重复执行、**v8 中断恢复**、**v9 旧报告不回溯填充**、旧记录缺快照标注；证据 `docs/evidence/v1-migration-chain-20260917/`（V1→v8）与 `docs/evidence/v3-b-v9-migration-20260922/`（V1→v9） |
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

## 8. V3 变化：strategy 接线（B3）

基线 `main 26f422a6`（V3 计划 PR #17 合并后）。B 只在既有文件上接线，不改 C 的算法。

### 8.1 请求矩阵（V3 计划 §5.1）

| `strategy` | `parameters` | 语义 | 结果 |
|---|---|---|---|
| 省略 | 省略 | `v1_legacy` | 与 V1/V2 完全一致 |
| 省略 | `{}` 或对象 | `v2_windowed` | 与 V2 完全一致（B 仍转发五个 MA 字段） |
| `ma_cross` | 省略 | `v1_legacy` | 同上（C 的口径：`ma_cross` 即现有 MA 实现） |
| `ma_cross` | `{}` 或对象 | `v2_windowed` | 同上 |
| `macd` | 省略 / `{}` / MACD 对象 | `v2_windowed` | 必须给出明确起止日期；B **只转发调用方真正给出的字段**，MACD 六字段的默认值由 C 决定 |
| `null` / 未知值 / 非字符串 | 任意 | — | `400 / 40001`，**取数前**失败 |
| 合法 strategy | `null` / 未知字段 / 串用另一策略的字段 | — | `400 / 40001`，**取数前**失败 |

### 8.2 B 的具体做法

- `schemas/backtest.py`：新增可选 `strategy`，保留「省略 vs 显式 null」的区分（`strategy_provided`）。未知值/非字符串由 schema 拒绝，显式 `null` 由服务层拒绝。
- `services/c_quant_entry.py`：`resolve`/`run` 透传 `strategy`，但**只有调用方真的选了策略才传该关键字**——省略必须保持省略（C 的 sentinel 默认才代表"用默认"，传 `None` 是另一种含义）。是否支持由 feature-detect 判断。
- `services/backtest_service.py`：MA 与 MACD 各用一份白名单；MACD 的**数值范围与 `fast < slow` 交叉规则不在 B 重复实现**，交给 C 的 `resolve`（取数前执行），避免两套规则漂移。MACD 的结果参数取 C 返回的 `effective_parameters` / `parameters`，B 不用自己的稀疏请求覆盖。
- `api/v1/quant.py`：透传 `strategy` / `strategy_provided`。

### 8.3 C 的 V3 入口尚未进入 `main` 时的行为（重要）

- `macd`：**明确拒绝**，按「C 入口不可用」口径返回 `50004`，**不**按 MA 跑、不写库。请求本身合法，这是部署缺口而非参数错误，所以不用 `40001`。
- `ma_cross` / 省略：与 V2 一致（`ma_cross` 就是现有 MA 实现，不需要 C 的新参数）。
- 判据来自运行期探测而非写死：`load_c_windowed_entry().supports_strategy` 与 C 的实际签名一致（由 `tests/test_strategy_entry_integration.py` 断言）。

### 8.4 验证命令与当前结果

```powershell
./.venv/Scripts/python.exe -m pytest tests -q                       # 580 passed
./.venv/Scripts/python.exe -m compileall -q backend scripts tests    # exit 0
git diff upstream/main --check                                       # 0 findings
```

- 策略矩阵单测在 `tests/test_backtest_service.py`：省略不传 sentinel、`ma_cross` 透传、`macd` 强制 `v2_windowed`、MACD 只转发显式字段、显式 `null` / 混用参数 / C 无 strategy 支持均在取数前失败、API 层 `null` 与未知值映射 `40001`。
- 真实 C 入口集成在 `tests/test_strategy_entry_integration.py`：当前 `main` 实测 `supports_strategy=False`，真实 MA 路径仍可用（`strategy_name=ma_long_only`、`total_return=0.18438710355268406`），`macd` 被拒且不落库；C 合入后同一文件会断言支持位翻转，拒绝用例自动 skip。

### 8.5 未完成 / 依赖他人

- **MACD 端到端未验证**：C 的 `quant/**` 尚未进入 `main`，B 只能在真实 V2 入口上验证 MA 与拒绝路径；C 合入后按 §9 复跑 MACD 真实请求（B 侧无需改代码）。
- `40007`（历史回测合法但不满足解读条件）属 AI 链路，等 D 给出精确片段后再由 B 落到 `core/errors.py`。
