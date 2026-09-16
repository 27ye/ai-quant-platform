# -*- coding: utf-8 -*-
"""Generate the final V2 B-side API samples (PM request, 2026-09-16).

The samples are produced by running the **shipped code** - the real FastAPI app,
the real services, an in-memory SQLite database and a deterministic fake market
source - rather than being hand-written. No network, no MySQL.

For the backtest endpoints the samples must come from C's *real*
``run_backtest_request``; if C's V2 entry points are not importable the script
refuses to run instead of printing a ``50004`` body as if it were a sample.

Usage (from the repository root):
    python scripts/generate_v2_b_api_samples.py
    python scripts/generate_v2_b_api_samples.py --out docs/V2_B_API_SAMPLES.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# SQLite needs BIGINT -> INTEGER for rowid autoincrement; mirrors tests/conftest.py
# so this script can seed the same in-memory schema the test suite uses.
from sqlalchemy import BIGINT  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(BIGINT, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.app.api.v1.dependencies import (  # noqa: E402
    get_backtest_repository,
    get_backtest_service,
    get_data_status_service,
)
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.schemas.stock import DailyKlineSchema  # noqa: E402
from backend.app.services.backtest_service import (  # noqa: E402
    BacktestRepository,
    BacktestService,
)
from backend.app.services.c_quant_entry import load_c_windowed_entry  # noqa: E402
from backend.app.services.data_status_service import DataStatusService  # noqa: E402
from backend.app.services.market_data_service import (  # noqa: E402
    MarketDataRepository,
)
from backend.app.services.quant_service import QuantService  # noqa: E402
from backend.app.services.stock_catalog_service import (  # noqa: E402
    StockCatalogRepository,
    StockCatalogService,
)
from backend.app.services.stock_service import StockService  # noqa: E402

STOCK_CODE = "600519"
STOCK_NAME = "贵州茅台"
WINDOW_START = date(2025, 7, 4)
WINDOW_END = date(2025, 12, 31)
BAR_START = date(2024, 1, 2)
BAR_COUNT = 760
DEFAULT_OUT = PROJECT_ROOT / "docs" / "V2_B_API_SAMPLES.md"


class _UnusedProvider:
    """The windowed path always passes a frame; the provider must never be hit."""

    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("provider must not be called while sampling")


class _FakeCatalogProvider:
    last_catalog_source = "sample-catalog"

    def search_stocks(self, keyword):  # pragma: no cover - unused here
        return []

    def fetch_stock_catalog(self):
        return [
            {"stock_code": STOCK_CODE, "stock_name": STOCK_NAME},
            {"stock_code": "000001", "stock_name": "平安银行"},
        ]


def _bars(start: date = BAR_START, count: int = BAR_COUNT) -> list:
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.1
        rows.append(
            DailyKlineSchema(
                stock_code=STOCK_CODE,
                trade_date=start + timedelta(days=index),
                open=close - 0.05,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1000 + index,
                amount=100000.0 + index,
                turnover_rate=0.01,
                change_pct=0.02,
            )
        )
    return rows


class _Market:
    """Deterministic stand-in for MarketDataSource."""

    def __init__(self, rows) -> None:
        self._rows = rows
        self.calls: list = []

    def query_daily(self, stock_code, start_date=None, end_date=None, **kwargs):
        self.calls.append((stock_code, start_date, end_date))
        return [
            row
            for row in self._rows
            if (start_date is None or row.trade_date >= start_date)
            and (end_date is None or row.trade_date <= end_date)
        ]


def _build():
    # FastAPI runs sync route handlers in a worker thread, and a plain in-memory
    # SQLite URL hands every thread its own empty database. StaticPool +
    # check_same_thread=False keeps one shared connection, exactly like the
    # API-level tests do.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    session = Session(bind=engine)

    rows = _bars()
    market = _Market(rows)

    from backend.app.services import stock_catalog_service as catalog_module

    catalog_module.MIN_CATALOG_ROWS = 2
    StockCatalogService(
        provider=_FakeCatalogProvider(),
        repository=StockCatalogRepository(session),
    ).sync()

    market_repository = MarketDataRepository(session)
    market_repository.upsert_daily([row for row in rows if row.trade_date <= WINDOW_END])
    market_repository.upsert_daily_sync(
        stock_code=STOCK_CODE,
        mode="live",
        source="akshare.stock_zh_a_hist",
        row_count=len(rows),
        first_trade_date=BAR_START,
        last_trade_date=rows[-1].trade_date,
        at=datetime(2026, 9, 16, 0, 30, 0),
    )

    repository = BacktestRepository(session)
    service = BacktestService(
        quant_service=QuantService(
            stock_service=StockService(provider=_UnusedProvider()),
            market_data_source=market,
        ),
        market_data_source=market,
        repository=repository,
    )
    status_service = DataStatusService(
        market_repository=market_repository,
        catalog_repository=StockCatalogRepository(session),
        trading_days=lambda start, end: (end - start).days + 1,
        today=lambda: date(2026, 9, 16),
        now=lambda: datetime(2026, 9, 16, 0, 35, 0, tzinfo=timezone.utc),
    )

    app.dependency_overrides[get_backtest_service] = lambda: service
    app.dependency_overrides[get_backtest_repository] = lambda: repository
    app.dependency_overrides[get_data_status_service] = lambda: status_service
    return session, repository, service


def _dump(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _require_ok(response, label: str) -> dict:
    """Fail loudly with the server body instead of sampling an error response."""
    if response.status_code != 200:
        raise SystemExit(
            f"{label} failed: HTTP {response.status_code} {response.text[:400]}"
        )
    body = response.json()
    if body.get("code") != 0:
        raise SystemExit(f"{label} returned code={body.get('code')} {body.get('message')!r}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    c_entry = load_c_windowed_entry()
    if c_entry is None:
        print(
            "C's run_backtest_request is not importable here, so the backtest samples "
            "would just be a 50004 body. Regenerate where C's V2 branch is merged.",
            file=sys.stderr,
        )
        return 2

    session, repository, service = _build()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        created = client.post(
            "/api/v1/backtests",
            json={
                "stock_code": STOCK_CODE,
                "start_date": WINDOW_START.isoformat(),
                "end_date": WINDOW_END.isoformat(),
                "parameters": {},
            },
        )
        _require_ok(created, "POST /backtests")
        backtest_id = created.json()["data"]["backtest_id"]
        listing = client.get(
            "/api/v1/backtests", params={"stock_code": STOCK_CODE, "page": 1, "page_size": 20}
        )
        _require_ok(listing, "GET /backtests")
        detail = client.get(f"/api/v1/backtests/{backtest_id}")
        _require_ok(detail, "GET /backtests/{id}")
        full = client.get(
            f"/api/v1/backtests/{backtest_id}", params={"include_c_result": "true"}
        )
        _require_ok(full, "GET /backtests/{id}?include_c_result=true")
        status = client.get(f"/api/v1/stocks/{STOCK_CODE}/data-status")
        _require_ok(status, "GET /stocks/{code}/data-status")
        unknown = client.get("/api/v1/backtests/999999")
        bad_code = client.get("/api/v1/stocks/60/data-status")
        null_param = client.post(
            "/api/v1/backtests",
            json={
                "stock_code": STOCK_CODE,
                "start_date": WINDOW_START.isoformat(),
                "end_date": WINDOW_END.isoformat(),
                "parameters": {"ma_long_period": None},
            },
        )
        legacy = client.post("/api/v1/backtests", json={"stock_code": STOCK_CODE})
    finally:
        app.dependency_overrides.clear()
        session.close()

    def _slim(payload: dict) -> str:
        """Keep the shape readable: long row lists are truncated to one element."""
        clone = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        for key in ("equity_curve", "benchmark_curve", "drawdown_curve", "trades"):
            value = clone.get(key)
            if isinstance(value, list) and len(value) > 1:
                clone[key] = value[:1] + [f"… 共 {len(value)} 条"]
        snapshot = clone.get("input_snapshot")
        if isinstance(snapshot, list) and len(snapshot) > 1:
            clone["input_snapshot"] = snapshot[:1] + [f"… 共 {len(snapshot)} 条"]
        elif isinstance(snapshot, dict) and isinstance(snapshot.get("rows"), list):
            rows = snapshot["rows"]
            if len(rows) > 1:
                snapshot["rows"] = rows[:1] + [f"… 共 {len(rows)} 条"]
        return _dump(clone)

    created_body = created.json()
    created_body["data"] = json.loads(_slim(created_body["data"]))
    detail_body = detail.json()["data"]
    full_body = full.json()["data"]
    c_result = full_body["c_result"]

    lines = [
        "# V2 B 侧接口样例（最终基线）",
        "",
        "> 分支：`feature/v2-b-market-data`　提交 SHA：`43269f5`　迁移版本：`schema_version = 7`",
        "> 生成方式：`python scripts/generate_v2_b_api_samples.py` —— 跑**真实代码**",
        "> （真实 FastAPI app + 真实 Service + 内存 SQLite + 确定性假行情源），",
        "> 回测部分使用 C 的真实 `run_backtest_request`。**非手写样例。**",
        "> 其中 `created_at` / `as_of` / catalog 时间戳为生成时的运行时间。",
        "",
        "## 0. 统一约定",
        "",
        "- Base URL：`http://localhost:8000/api/v1`；统一返回 `{ code, message, data }`。",
        "- 分页统一为 `data: { items, total, page, page_size }`（与 D 的 AI 契约同构）。",
        "- 日期 `YYYY-MM-DD`；时间带时区 ISO 8601（UTC）；百分比用小数（`0.0125` = 1.25%）。",
        "- 错误码：`40001` 参数错误、`40003` 数据不足、`40005` 回测不存在、`40006` 报告不存在、"
        "`50001` 数据源、`50002` 数据库、`50004` 回测引擎不可用。",
        "",
        "---",
        "",
        "## 1. `GET /api/v1/stocks/{stock_code}/data-status`",
        "",
        "```http",
        f"GET /api/v1/stocks/{STOCK_CODE}/data-status",
        "```",
        "",
        "```json",
        _dump(status.json()),
        "```",
        "",
        "| 字段 | 含义 |",
        "|---|---|",
        "| `data.kline.last_trade_date` | 行情截至日期 |",
        "| `data.kline.last_refreshed_at` | **最近一次成功**刷新时间；最近一次尝试见 `last_attempt_at`，失败原因见 `last_error` |",
        "| `data.kline.mode` | `live` / `frozen` / `unknown`（无刷新元数据，不猜） |",
        "| `data.kline.coverage` + `expected_trading_days` | 覆盖情况，来自**交易日历**；无法证明时为 `unknown` |",
        "| `data.kline.freshness` | `fresh` / `stale` / `unknown`，含 `stale_days`、`max_stale_days` |",
        "",
        "---",
        "",
        "## 2. `POST /api/v1/backtests`（`v2_windowed`）",
        "",
        "```http",
        "POST /api/v1/backtests",
        "Content-Type: application/json",
        "",
        _dump(
            {
                "stock_code": STOCK_CODE,
                "start_date": WINDOW_START.isoformat(),
                "end_date": WINDOW_END.isoformat(),
                "parameters": {},
            }
        ),
        "```",
        "",
        f"响应：`HTTP {created.status_code}`，`code = {created.json().get('code')}`",
        "",
        "```json",
        _dump(created_body),
        "```",
        "",
        "> `parameters` **省略** → `v1_legacy`；**显式 `{}` 或非空对象** → `v2_windowed`；",
        "> **显式 `null`**（整体或任一白名单字段）→ `40001`，取数前拒绝。",
        "> `v2_windowed` 的 `effective_parameters` **只含白名单五字段**；完整算法配置在",
        "> `c_result.effective_parameters`。",
        "",
        "### 2.1 白名单五字段与默认值",
        "",
        "```json",
        _dump(
            {
                "ma_short_period": 5,
                "ma_long_period": 20,
                "initial_cash": 100000.0,
                "transaction_cost": 0.001,
                "slippage": 0.0,
            }
        ),
        "```",
        "",
        "严格类型：拒绝数字字符串、布尔值、浮点周期、`NaN`/`Infinity`、未知字段；",
        "周期整数且 `2 ≤ short < long ≤ 120`，`initial_cash > 0`，成本/滑点 `∈ [0,1)`。",
        "",
        "---",
        "",
        "## 3. `GET /api/v1/backtests`（分页列表）",
        "",
        "```http",
        f"GET /api/v1/backtests?stock_code={STOCK_CODE}&page=1&page_size=20",
        "```",
        "",
        "```json",
        _dump(listing.json()),
        "```",
        "",
        "排序固定 `created_at DESC, id DESC`；`page_size` 默认 20、最大 100。",
        "`snapshot_status` ∈ `complete` / `missing`（旧 V1 记录只存摘要）。",
        "",
        "---",
        "",
        "## 4. `GET /api/v1/backtests/{backtest_id}`（详情）",
        "",
        "```http",
        f"GET /api/v1/backtests/{backtest_id}",
        "```",
        "",
        "```json",
        _slim(detail_body),
        "```",
        "",
        "### 4.1 需要完整 C 结果时",
        "",
        "```http",
        f"GET /api/v1/backtests/{backtest_id}?include_c_result=true",
        "```",
        "",
        f"`data.c_result` 是 C 的**完整返回封套**（{len(json.dumps(c_result, ensure_ascii=False))} 字符，此处只展示关键字段）：",
        "",
        "```json",
        _dump(
            {
                "c_result_available": full_body["c_result_available"],
                "c_semantics_version": full_body.get("c_semantics_version"),
                "c_algorithm_version": full_body.get("c_algorithm_version"),
                "c_data_hash": full_body.get("c_data_hash"),
                "c_initial_equity": full_body.get("c_initial_equity"),
                "c_warmup": full_body.get("c_warmup"),
                "c_execution_assumptions": full_body.get("c_execution_assumptions"),
                "c_result_keys": sorted(c_result),
            }
        ),
        "```",
        "",
        "| 字段 | 说明 |",
        "|---|---|",
        "| `warmup_start_date` | 预热区间起点（`v1_legacy` 为 `null`） |",
        "| `equity_curve` / `benchmark_curve` / `drawdown_curve` | 数值键分别为 `equity` / `benchmark_equity` / `drawdown` |",
        "| `trades` | 成交数组（不是 `orders`）；`order_count` 是记录数，`trade_count` 是完成往返次数 |",
        "| `data_meta.frame_digest` | **B** 交给 C 的数据帧摘要 |",
        "| `data_meta.c_data_hash` | **C** 输入快照哈希——与 `frame_digest` 分开记录，不能互替 |",
        "| `c_result_available` | 是否有 C 结果封套；旧记录为 `false`，缺失时不补造、不重算 |",
        "| `input_snapshot_available` / `input_snapshot_rows` | 送 C 的输入行数；`?include_input_snapshot=true` 取全量 |",
        "",
        "> `snapshot_status = complete` **不能**代替 `c_result_available` 判断。",
        "",
        "---",
        "",
        "## 5. 错误样例",
        "",
        "| 场景 | 请求 | HTTP | code |",
        "|---|---|---|---|",
        f"| 未知回测 ID | `GET /backtests/999999` | {unknown.status_code} | `{unknown.json().get('code')}` |",
        f"| 股票代码非 6 位 | `GET /stocks/60/data-status` | {bad_code.status_code} | `{bad_code.json().get('code')}` |",
        f"| 白名单字段显式 `null` | `POST /backtests` `{{'ma_long_period': null}}` | {null_param.status_code} | `{null_param.json().get('code')}` |",
        f"| 省略 `parameters` → V1 | `POST /backtests` `{{'stock_code': ...}}` | {legacy.status_code} | `{legacy.json().get('code')}` |",
        "",
        f"V1 路径响应 `semantics_version` = `{legacy.json()['data'].get('semantics_version')}`。",
        "",
        "```json",
        _dump(unknown.json()),
        "```",
        "",
    ]

    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
