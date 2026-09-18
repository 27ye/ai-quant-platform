# -*- coding: utf-8 -*-
"""MySQL read-back verification for the C delivery package.

C asked for "API／MySQL 回读结果供 C 核对": for every delivered stock this reads
the same window back from MySQL and compares it with the delivered **normalized**
file at row level (same ``frame_digest`` B uses for backtest snapshots), so the
comparison is about values, not about JSON formatting.

Writes ``<output-dir>/mysql_readback.json``.

Usage:
    python scripts/verify_c_delivery_mysql.py --start-date 2024-12-01 --end-date 2026-09-15
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402
from backend.app.schemas.stock import DailyKlineSchema  # noqa: E402
from backend.app.services.backtest_service import frame_digest  # noqa: E402
from backend.app.services.market_data_service import MarketDataRepository  # noqa: E402

DEFAULT_STOCKS = ("600519", "000001", "300750")
OUTPUT_DIR = PROJECT_ROOT / "frozen" / "c-delivery"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows_from_file(path: Path) -> list:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", action="append", dest="codes")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2024, 12, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 9, 15))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    codes = args.codes or list(DEFAULT_STOCKS)
    out_dir = Path(args.output_dir)
    settings = get_settings()
    apply_migrations(engine)
    session = SessionLocal()
    report: list = []
    try:
        repository = MarketDataRepository(session)
        for code in codes:
            window = f"{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}"
            entry: dict = {"stock_code": code}
            db_rows = repository.list_daily(code, args.start_date, args.end_date)
            stored = repository.daily_window(code)
            state = repository.get_daily_sync(code)
            entry["mysql"] = {
                "rows_in_window": len(db_rows),
                "window": [db_rows[0].trade_date.isoformat(), db_rows[-1].trade_date.isoformat()]
                if db_rows
                else None,
                "stored_rows": stored.row_count,
                "stored_window": [str(stored.first_trade_date), str(stored.last_trade_date)],
                "data_digest": frame_digest(db_rows) if db_rows else None,
                "provenance": {
                    "mode": getattr(state, "mode", None),
                    "source": getattr(state, "source", None),
                    "last_success_at": str(getattr(state, "last_success_at", None)),
                },
            }

            norm_path = out_dir / f"{code}_qfq_normalized_{window}.json"
            if norm_path.exists():
                norm_rows = _rows_from_file(norm_path)
                schemas = [DailyKlineSchema(**row) for row in norm_rows]
                entry["normalized_file"] = {
                    "path": str(norm_path.relative_to(PROJECT_ROOT)),
                    "rows": len(norm_rows),
                    "sha256": _sha256_file(norm_path),
                    "data_digest": frame_digest(schemas) if schemas else None,
                }
                entry["match"] = entry["normalized_file"]["data_digest"] == entry["mysql"]["data_digest"]
            else:
                entry["normalized_file"] = None
                entry["match"] = False

            raw_path = out_dir / f"{code}_qfq_raw_{window}.json"
            entry["raw_file"] = (
                {
                    "path": str(raw_path.relative_to(PROJECT_ROOT)),
                    "sha256": _sha256_file(raw_path),
                    "rows": len(_rows_from_file(raw_path)),
                }
                if raw_path.exists()
                else None
            )
            report.append(entry)
            print(
                f"{code}: mysql_rows={entry['mysql']['rows_in_window']} "
                f"normalized_match={entry['match']} raw={'yes' if entry['raw_file'] else 'no'}",
                flush=True,
            )
    finally:
        session.close()

    out_path = out_dir / "mysql_readback.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "database": settings.mysql_database,
                "window": [args.start_date.isoformat(), args.end_date.isoformat()],
                "note": (
                    "data_digest is B's frame_digest over the normalized rows, so the "
                    "delivered file and the MySQL read-back are compared by value"
                ),
                "stocks": report,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("read-back written:", out_path)
    return 0 if all(item["match"] for item in report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
