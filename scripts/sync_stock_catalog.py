"""Sync the local A-share stock catalog used by ``GET /api/v1/stocks/search`` (V2 B1).

Runs at low frequency and on demand - never on the request path. A partial or
malformed upstream catalog is reported as a failure and is **not** recorded as a
successful sync, so search never treats "the source is broken" as "no such stock".

Usage:
    python scripts/sync_stock_catalog.py
    python scripts/sync_stock_catalog.py --show-state
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.data.providers.akshare_provider import AKShareStockProvider  # noqa: E402
from backend.app.data.providers.base import StockDataProviderError  # noqa: E402
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402
from backend.app.services.stock_catalog_service import (  # noqa: E402
    StockCatalogRepository,
    StockCatalogService,
)


def _print_state(repository: StockCatalogRepository) -> None:
    state = repository.get_state()
    if state is None:
        print("catalog state: never attempted")
        return
    print(
        "catalog state: status={status} rows={rows} last_success={ok} "
        "last_attempt={attempt} source={source}".format(
            status=state.status,
            rows=state.row_count,
            ok=state.last_success_at,
            attempt=state.last_attempt_at,
            source=state.source,
        )
    )
    if state.last_error:
        print(f"last error: {state.last_error}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-state",
        action="store_true",
        help="only print the recorded sync state, do not hit the data source",
    )
    args = parser.parse_args(argv)

    apply_migrations(engine)
    session = SessionLocal()
    try:
        repository = StockCatalogRepository(session)
        if args.show_state:
            _print_state(repository)
            print(f"stock_basic rows: {repository.count()}")
            return 0

        service = StockCatalogService(
            provider=AKShareStockProvider(), repository=repository
        )
        try:
            result = service.sync()
        except StockDataProviderError as exc:
            print(f"catalog sync FAILED: {exc}", file=sys.stderr)
            _print_state(repository)
            return 1

        print(
            "catalog sync OK: rows={rows} source={source} at={at}".format(
                rows=result.row_count, source=result.source, at=result.synced_at
            )
        )
        print(f"stock_basic rows: {repository.count()}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
