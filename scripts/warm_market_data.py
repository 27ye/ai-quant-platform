"""Low-frequency multi-stock warm-up for the V02 acceptance gate.

The live source is only reachable in intermittent windows, and a stock that has
never been fetched can only be loaded inside one. This script walks a small list
of stocks at low frequency, records what it got (rows, window, provenance), and
reports failures instead of hiding them - it is the practical form of the
documented recovery plan in ``docs/V2_B_DATA_EVIDENCE.md``.

Usage:
    # the acceptance trio, one pass, 5s between stocks
    python scripts/warm_market_data.py

    # explicit list / extra passes (each pass waits --interval seconds)
    python scripts/warm_market_data.py --stock-code 600519 --stock-code 300750 --rounds 3 --interval 600
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.data.providers.base import StockDataProviderError  # noqa: E402
from backend.app.data.trading_calendar import TradingCalendarProvider  # noqa: E402
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402
from backend.app.services.market_data_service import (  # noqa: E402
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataRepository,
    MarketDataService,
)
from backend.app.services.stock_service import (  # noqa: E402
    DEFAULT_MIN_KLINE_ROWS,
    DEFAULT_WINDOW_DAYS,
    StockService,
)

#: Plan §8 V01: the agreed acceptance stocks.
DEFAULT_STOCKS = ("600519", "000001", "300750")
BETWEEN_STOCKS_SECONDS = 5


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stock-code",
        action="append",
        dest="stock_codes",
        help="repeatable; defaults to the acceptance trio",
    )
    parser.add_argument(
        "--start-date", type=date.fromisoformat, default=today - timedelta(days=DEFAULT_WINDOW_DAYS)
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=today)
    parser.add_argument("--rounds", type=int, default=1, help="low-frequency retry passes")
    parser.add_argument(
        "--interval", type=int, default=600, help="seconds between passes (>=60)"
    )
    return parser.parse_args()


def _warm_one(service: MarketDataService, repository: MarketDataRepository, code, start, end):
    started = time.perf_counter()
    try:
        rows = service.query_daily(code, start, end, min_rows=DEFAULT_MIN_KLINE_ROWS)
    except StockDataProviderError as exc:
        return {
            "stock_code": code,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}"[:200],
            "seconds": round(time.perf_counter() - started, 1),
        }
    state = repository.get_daily_sync(code)
    return {
        "stock_code": code,
        "ok": True,
        "rows": len(rows),
        "window": [rows[0].trade_date.isoformat(), rows[-1].trade_date.isoformat()] if rows else None,
        "mode": getattr(state, "mode", None),
        "source": getattr(state, "source", None),
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> int:
    args = parse_args()
    codes = args.stock_codes or list(DEFAULT_STOCKS)
    if args.rounds < 1:
        raise SystemExit("--rounds must be >= 1")
    interval = max(int(args.interval), 60)

    apply_migrations(engine)
    calendar = TradingCalendarProvider()

    def count_trading_days(start, end):
        try:
            return calendar.count_between(start, end)
        except Exception:  # noqa: BLE001 - unknown coverage stays unknown
            return None

    db = SessionLocal()
    results = []
    try:
        repository = MarketDataRepository(db)
        service = MarketDataService(
            stock_service=StockService(),
            repository=repository,
            trading_days=count_trading_days,
        )
        for round_index in range(1, args.rounds + 1):
            print(f"--- pass {round_index}/{args.rounds} ({args.start_date}..{args.end_date})")
            for code in codes:
                outcome = _warm_one(service, repository, code, args.start_date, args.end_date)
                results.append(outcome)
                print("   ", outcome, flush=True)
                time.sleep(BETWEEN_STOCKS_SECONDS)
            pending = [r["stock_code"] for r in results if not r["ok"]]
            if not pending:
                break
            if round_index < args.rounds:
                print(f"    still failing: {pending}; waiting {interval}s", flush=True)
                time.sleep(interval)
    finally:
        db.close()

    failed = sorted({r["stock_code"] for r in results if not r["ok"]})
    print("\nwarm-up summary:")
    for code in codes:
        best = next((r for r in reversed(results) if r["stock_code"] == code and r["ok"]), None)
        print(f"  {code}: {'OK ' + str(best['rows']) + ' rows' if best else 'FAILED'}")
    if failed:
        print(f"failed stocks: {failed} (source unavailable window; see docs/V2_B_DATA_EVIDENCE.md)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
