# -*- coding: utf-8 -*-
"""Deliver the three-stock market data C asked for (V2 C-B interface).

Two artefacts per stock, exactly as C requested:

1. ``<code>_qfq_raw_<window>.json`` — provider-native values, **not** rounded to
   B's canonical 4/2/6 口径 (captured straight from the provider frame).
2. ``<code>_qfq_normalized_<window>.json`` — the exact rows that B hands to C
   (canonical rounding applied), i.e. the normalized input.

Plus ``<code>_metadata.json`` per stock and a ``MANIFEST.json`` with SHA-256 for
every file, and a ``README.md`` stating branch/commit/paths/how to read.

Usage:
    python scripts/export_c_delivery.py --start-date 2024-12-01 --end-date 2026-09-15
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
from backend.app.core.errors import DataProviderError  # noqa: E402
from backend.app.data.trading_calendar import TradingCalendarProvider  # noqa: E402
from backend.app.db.migrations import apply_migrations  # noqa: E402
from backend.app.db.session import SessionLocal, engine  # noqa: E402
from backend.app.services.market_data_service import (  # noqa: E402
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataRepository,
    MarketDataService,
)
from backend.app.services.stock_service import StockService  # noqa: E402

DEFAULT_STOCKS = ("600519", "000001", "300750")
#: Fields C requires, in order; extra fields are kept but listed separately.
REQUIRED_FIELDS = ("stock_code", "trade_date", "open", "high", "low", "close", "volume")
OUTPUT_DIR = PROJECT_ROOT / "frozen" / "c-delivery"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def _rows_in_file(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _artifact_entry(path: Path, representation: str) -> dict | None:
    """Describe a delivery file that exists on disk (never an in-memory only run).

    A later capture round that hits an unavailable window must not erase an
    artefact an earlier round already produced, so the manifest is built from
    what is actually on disk - including its own actual window.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    dates = [row.get("trade_date") for row in payload if row.get("trade_date")]
    captured = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return {
        "path": str(path.relative_to(PROJECT_ROOT)),
        "rows": len(payload),
        "sha256": sha256_of(path),
        "captured_at_utc": captured.isoformat(),
        "actual_window": [min(dates), max(dates)] if dates else None,
        "representation": representation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", action="append", dest="codes")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2024, 12, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 9, 15))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    codes = args.codes or list(DEFAULT_STOCKS)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    apply_migrations(engine)
    calendar = TradingCalendarProvider()
    session = SessionLocal()
    manifest: list = []
    summary: list = []
    try:
        repository = MarketDataRepository(session)
        normalized_source = MarketDataService(
            stock_service=StockService(),
            repository=repository,
            trading_days=lambda start, end: calendar.count_between(start, end),
        )
        raw_source = StockService()

        for code in codes:
            captured_at = datetime.now(timezone.utc).isoformat()
            raw_rows: list = []
            raw_error = None
            try:
                raw_rows = [
                    row.model_dump(mode="json")
                    for row in raw_source.get_daily_kline(
                        code, args.start_date, args.end_date
                    )
                ]
            except (DataProviderError, Exception) as exc:  # noqa: BLE001
                raw_error = f"{type(exc).__name__}: {exc}"[:200]

            normalized_rows: list = []
            normalized_error = None
            try:
                normalized_rows = [
                    row.model_dump(mode="json")
                    for row in normalized_source.query_daily(
                        code,
                        args.start_date,
                        args.end_date,
                        min_rows=1,
                        max_stale_days=DEFAULT_MAX_STALE_DAYS,
                        max_gap_days=DEFAULT_MAX_GAP_DAYS,
                    )
                ]
            except Exception as exc:  # noqa: BLE001
                normalized_error = f"{type(exc).__name__}: {exc}"[:200]

            window = f"{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}"
            raw_path = out_dir / f"{code}_qfq_raw_{window}.json"
            norm_path = out_dir / f"{code}_qfq_normalized_{window}.json"
            if raw_rows:
                write_json(raw_path, raw_rows)
            if normalized_rows:
                write_json(norm_path, normalized_rows)

            # Manifest entries come from disk, so a later round that hits an
            # unavailable window cannot erase an artefact captured earlier.
            files = {
                "raw": _artifact_entry(
                    raw_path, "provider-native values (no 4/2/6 rounding)"
                ),
                "normalized": _artifact_entry(
                    norm_path,
                    "canonical 4/2/6 rounding; this is what B passes to C",
                ),
            }

            def _span(rows):
                if not rows:
                    return None
                return [rows[0]["trade_date"], rows[-1]["trade_date"]]

            meta = {
                "stock_code": code,
                "adjust": "qfq",
                "frequency": "daily",
                "requested_window": [args.start_date.isoformat(), args.end_date.isoformat()],
                "captured_at_utc": captured_at,
                "source": "AKShareStockProvider / stock_zh_a_hist (eastmoney)",
                "required_fields": list(REQUIRED_FIELDS),
                "extra_fields": ["amount", "turnover_rate", "change_pct"],
                "raw": {
                    **(files["raw"] or {}),
                    "actual_window": _span(raw_rows) or (files["raw"] or {}).get("actual_window"),
                    "this_run_error": raw_error,
                    "preserved_from_earlier_round": bool(files["raw"]) and not raw_rows,
                },
                "normalized": {
                    **(files["normalized"] or {}),
                    "actual_window": _span(normalized_rows)
                    or (files["normalized"] or {}).get("actual_window"),
                    "this_run_error": normalized_error,
                    "preserved_from_earlier_round": bool(files["normalized"])
                    and not normalized_rows,
                },
                "missing": {
                    "raw_unavailable": files["raw"] is None,
                    "normalized_unavailable": files["normalized"] is None,
                    "note": "incremental provider availability: retry low-frequency before delivery",
                },
                "database": settings.mysql_database,
            }
            meta_path = out_dir / f"{code}_metadata.json"
            write_json(meta_path, meta)
            meta["metadata_file"] = {
                "path": str(meta_path.relative_to(PROJECT_ROOT)),
                "sha256": sha256_of(meta_path),
            }
            manifest.append(meta)
            summary.append(
                {
                    "stock_code": code,
                    "raw_rows": len(raw_rows),
                    "normalized_rows": len(normalized_rows),
                    "normalized_window": _span(normalized_rows),
                    "raw_error": raw_error,
                    "normalized_error": normalized_error,
                }
            )
            print(f"{code}: raw={len(raw_rows)} normalized={len(normalized_rows)}", flush=True)
    finally:
        session.close()

    manifest_path = out_dir / "MANIFEST.json"
    write_json(
        manifest_path,
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "stocks": manifest,
        },
    )
    print("manifest:", manifest_path)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0 if all(item["normalized_rows"] for item in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
