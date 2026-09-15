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

## 2. 迁移（schema_version 1 → 4）

```powershell
.\.venv\Scripts\python.exe scripts\migrate_db.py
```

- 分步执行：每步独立事务，**成功后才写版本号**；失败不记录，重跑从失败步恢复。
- 既有 V1 库升级会**保留旧数据**（实测：403 行行情在 v1→v2→v3→v4 后不变）。
- 升级演练建议在带 V1 数据的独立库先行执行，保留备份/恢复步骤，脚本不删旧数据。

| 版本 | 内容 |
|---|---|
| v1 | 六张 V1 基础表 |
| v2 | `stock_catalog_sync` |
| v3 | `stock_daily_sync` |
| v4 | `backtest_result` 快照列（曲线/订单/生效参数/数据元信息） |

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
| 编号 | 证据 |
|---|---|
| V01 | 600519 / 000001 各 243 行真实日线（2025-09-15~2026-09-15）；300750 在源不可用窗口返回 `50001`，等待下一轮重试 |
| V02 | 两轮低频探测（间隔 32 分钟）结果见 `docs/V2_B_DATA_EVIDENCE.md` |
| V03 | 注入超时/畸形报文/数据库失败的用例见 `tests/test_provider_retry.py`、`tests/test_stock_catalog.py`、`tests/test_data_status.py`；**API 层错误码契约**见 `tests/test_v2_error_contract.py`（`50001`/`50002`/`40003`/`40005`，且失败不留下成功记录） |
| V04 | 省略 `parameters` 的旧请求与 V1 冻结基线一致（`final_equity 90834.22588204397`、12 次往返/24 条订单） |
| V05 | 两组参数产生独立 `backtest_id`；详情 0.02s 读快照；未知 ID `404/40005` |
| V09 | 空库初始化、V1 库升级（1→5，旧数据保留）、重复执行、旧记录缺快照标注均有用例与真库演练 |

## 7. 与 D 的 V2 分支（`feature/v2-d-report-history`）集成注意事项

B 已在本机做了一次集成预演（`feature/v2-b-market-data` + D 分支，**结果 308 passed**）。合并时需处理三处：

| 冲突/缺陷 | 处理 |
|---|---|
| `db/migrations.py` | 采用 **B 的统一分步迁移**（D 分支独立重写的 v1→v2 被取代）。AI 快照列已作为 **v5** 纳入同一序列；`apply_migrations` 末尾有收敛步骤，即使版本行与实际结构不一致（两边都曾用「v2」表示不同内容）也会补齐缺失表/列 |
| `core/errors.py` | **D 的 `ReportNotFoundError` 需从 `40005` 改为 `40006`**：`40005` 已被 `BacktestNotFoundError` 占用。契约口径：`40005 = backtest not found`、`40006 = report not found` |
| `services/market_data_service.py` | 保留双方：D 的 `get_query_provenance()`（请求内来源，供 AI 快照）与 B 的 `stock_daily_sync`（持久来源，供 data-status）并存，互不替代 |
| 相关测试 | `tests/test_db_migrations.py`（AI 列现在是第 5 步）、`tests/test_ai_api.py`（报告不存在断言改为 `40006`） |

建议合并次序：**先合 B 的迁移与数据服务，再让 D 的分支 rebase/合并**，由 D 按上表调整三处即可全绿。
