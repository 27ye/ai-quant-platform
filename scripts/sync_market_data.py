"""Fetch real qfq daily bars for a stock and upsert them into MySQL.

Demonstrates B's V1 data pipeline (Provider -> upsert stock_daily -> query back).
This script intentionally requires a reachable MySQL instance.

Usage:
    python scripts/sync_market_data.py --stock-code 600519 --start-date 2025-01-01 --end-date 2026-08-31
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402
from backend.app.services.market_data_service import (  # noqa: E402
    MarketDataRepository,
    MarketDataService,
)


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", default="600519")
    parser.add_argument(
        "--start-date", type=date.fromisoformat, default=today - timedelta(days=366)
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=today)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    get_settings()
    apply_migrations(engine)  # ensure the six tables exist

    db = SessionLocal()
    try:
        repository = MarketDataRepository(db)
        service = MarketDataService(repository=repository)

        synced = service.sync_daily(args.stock_code, args.start_date, args.end_date)
        print(f"synced {len(synced)} rows -> stock_daily for {args.stock_code}")

        queried = repository.list_daily(args.stock_code, args.start_date, args.end_date)
        print(f"queried back {len(queried)} rows from stock_daily")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
