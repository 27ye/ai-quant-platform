"""Real-MySQL frozen-sample in/read verification (offline, no AKShare calls).

Reads the frozen 600519 qfq snapshot + real A-share trade-date calendar from
``frozen/`` (JSON, unchanged), loads them into the ``ai_quant_test`` MySQL
database, reads them back through the ORM, and compares the FULL quant output
(direct computation vs DB read-back) via ``analyze_quant_dataframe`` under the
canonical 4/2/6 precision.

It also exports the actual DB read-back data to a JSON file (pure array, same
fields/date format) with its SHA-256 for C to independently recompute.

Runs ONLY against ``ai_quant_test``; refuses to touch any other database.
The pure helper functions here are unit-tested (no DB/network required).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------- pure helpers

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_metadata_path(frozen_dir: Path, explicit: Optional[str] = None) -> Path:
    """Default to ``metadata.json``; only fall back when there is exactly one
    ``metadata*.json``. An explicit ``--metadata`` always wins. When multiple
    ``metadata*.json`` exist (and no ``metadata.json``), require ``--metadata``."""
    if explicit:
        return Path(explicit)
    default = frozen_dir / "metadata.json"
    if default.exists():
        return default
    candidates = sorted(p for p in frozen_dir.glob("metadata*.json") if p.is_file())
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise SystemExit(
            "[verify] multiple metadata files found: "
            + ", ".join(c.name for c in candidates)
            + "; use --metadata to specify one"
        )
    raise FileNotFoundError(f"no metadata.json found in {frozen_dir}")


def assert_hash_matches(path: Path, expected: str) -> None:
    actual = file_sha256(path)
    if actual.lower() != expected.lower():
        raise SystemExit(f"[verify] hash mismatch for {path.name}: {actual} != {expected}")


def load_bars(path: Path) -> List["DailyKlineSchema"]:
    from backend.app.schemas.stock import DailyKlineSchema

    kline = json.load(path.open(encoding="utf-8"))
    return [DailyKlineSchema(**record) for record in kline]


def load_calendar(path: Path) -> "TradingCalendarProvider":
    from backend.app.data.trading_calendar import TradingCalendarProvider
    from datetime import date

    days = json.load(path.open(encoding="utf-8"))
    return TradingCalendarProvider(trade_dates=[date.fromisoformat(day) for day in days])


def build_direct_frame(bars: List["DailyKlineSchema"]) -> pd.DataFrame:
    from backend.app.services.market_data_service import _round_daily

    return pd.DataFrame([_round_daily(bar).model_dump() for bar in bars])


def build_readback_frame(readback: List["DailyKlineSchema"]) -> pd.DataFrame:
    return pd.DataFrame([bar.model_dump() for bar in readback])


def compare_analyses(direct_bars, readback, config=None) -> dict:
    """Compare full indicator/score/backtest between direct and read-back data."""
    from backend.app.quant.pipeline import analyze_quant_dataframe

    direct_frame = build_direct_frame(direct_bars)
    readback_frame = build_readback_frame(readback)
    data_equal = direct_frame.reset_index(drop=True).equals(readback_frame.reset_index(drop=True))
    direct_analysis = analyze_quant_dataframe(direct_frame, config)
    readback_analysis = analyze_quant_dataframe(readback_frame, config)
    return {
        "data_equal": data_equal,
        "analysis_equal": direct_analysis == readback_analysis,
        "direct": direct_analysis,
        "readback": readback_analysis,
    }


def export_readback(readback, out_path: Path) -> str:
    """Write DB read-back as a pure JSON array (same fields, ISO dates) + SHA-256."""
    records = [bar.model_dump(mode="json") for bar in readback]
    out_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return file_sha256(out_path)


# ------------------------------------------------------------------ CLI runner

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", default=str(PROJECT_ROOT / "frozen"))
    parser.add_argument("--metadata", default=None, help="metadata.json path")
    parser.add_argument("--output", default=None, help="read-back JSON output path")
    args = parser.parse_args()

    os.environ.setdefault("MYSQL_DATABASE", "ai_quant_test")

    from backend.app.core.config import get_settings
    from backend.app.db.migrations import apply_migrations
    from backend.app.db.session import SessionLocal, engine
    from backend.app.services.market_data_service import MarketDataRepository

    settings = get_settings()
    database = settings.mysql_database
    if database != "ai_quant_test":
        raise SystemExit(f"[verify] refusing to run against non-test database: {database}")

    frozen = Path(args.frozen_dir)
    metadata_path = resolve_metadata_path(frozen, args.metadata)
    metadata = json.load(metadata_path.open(encoding="utf-8"))
    kline_file = frozen / metadata["kline"]["file"]
    calendar_file = frozen / metadata["calendar"]["file"]

    # 1) Block before writing on any hash mismatch.
    assert_hash_matches(kline_file, metadata["kline"]["sha256"])
    assert_hash_matches(calendar_file, metadata["calendar"]["sha256"])

    bars = load_bars(kline_file)
    cal = load_calendar(calendar_file)
    print("frozen kline rows:", len(bars), "| calendar dates:", len(cal.get_trade_dates()))

    apply_migrations(engine)

    start = min(b.trade_date for b in bars)
    end = max(b.trade_date for b in bars)
    print("actual window:", start, "->", end,
          "| expected trading days:", cal.count_between(start, end))

    db = SessionLocal()
    try:
        repository = MarketDataRepository(db)
        repository.upsert_daily(bars)
        readback = repository.list_daily("600519", start, end)
    finally:
        db.close()
    print("rows read back from stock_daily:", len(readback))

    result = compare_analyses(bars, readback)
    print("data_equal:", result["data_equal"], "| analysis_equal:", result["analysis_equal"])

    out = Path(args.output) if args.output else frozen / "mysql_readback_600519.json"
    readback_sha = export_readback(readback, out)
    print("read-back exported:", out, "| sha256:", readback_sha)

    params = result["direct"]["meta"]["parameters"]
    print("strategy parameters:", json.dumps(params, ensure_ascii=False))
    print("meta:", json.dumps(result["direct"]["meta"], ensure_ascii=False))
    print("score direct/readback:", result["direct"]["score"]["score"],
          "/", result["readback"]["score"]["score"])
    print("backtest direct/readback total_return:",
          result["direct"]["backtest"]["total_return"], "/",
          result["readback"]["backtest"]["total_return"])

    ok = result["data_equal"] and result["analysis_equal"]
    print("RESULT:", "PASS" if ok else "FAIL",
          "(data_equal=%s analysis_equal=%s)" % (result["data_equal"], result["analysis_equal"]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
