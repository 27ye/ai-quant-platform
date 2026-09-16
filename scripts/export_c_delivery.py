# -*- coding: utf-8 -*-
"""Export the three-stock market data C asked for (V2 C-B interface).

Refactored 2026-09-16 per C's PR #10 review (§2). One **single** successful
provider response per stock is frozen, and both deliverables are derived from
that same row set:

    one successful response -> frozen un-rounded rows
        |- raw        : the frozen rows, provider-native (no 4/2/6 rounding)
        `- normalized : the SAME rows through B's canonical 4/2/6 rounding
                        -> written to this batch and committed
                        -> read back from the repository in a NEW session

Why this shape: the previous version fetched twice per stock (``raw`` straight
from the provider, ``normalized`` through the DB-backed service). For an
in-progress trading day those two paths can return different intraday snapshots,
which is exactly how ``600519`` ``2026-09-15`` ended up inconsistent in the first
package (its DB row was a 09:46 partial session snapshot while the direct fetch
returned the settled close).

Deliberate boundaries (C's §2):

* the two outputs never fetch separately - one response, two renderings;
* ``query_daily`` is **not** used to produce the second data set (it can return a
  stale cache, or an in-memory normalized list rather than an independent
  write-then-read); the read-back opens a **new session** and only touches the
  repository, never the provider;
* canonical 4/2/6 rounding is B's existing production helper - never re-implemented
  and never loosened to make a comparison pass;
* each batch uses its own directory; a failed or retried batch never promotes old
  files into its own success list.

Usage:
    python scripts/export_c_delivery.py --batch 20260916 --last-complete-trading-day 2026-09-15
    python scripts/export_c_delivery.py --batch 20260916 --last-complete-trading-day 2026-09-15 \
        --start-date 2024-12-01 --end-date 2026-09-15
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.schemas.stock import DailyKlineSchema  # noqa: E402
from backend.app.services.market_data_service import (  # noqa: E402
    AMOUNT_NDIGITS,
    PERCENT_NDIGITS,
    PRICE_NDIGITS,
    MarketDataRepository,
    _round_daily,
)

DEFAULT_STOCKS = ("600519", "000001", "300750")
#: Fields C requires, in order; the extras are kept and listed separately.
REQUIRED_FIELDS = ("stock_code", "trade_date", "open", "high", "low", "close", "volume")
EXTRA_FIELDS = ("amount", "turnover_rate", "change_pct")
#: The order rows are written in, matching the model definition.
ROW_FIELDS = REQUIRED_FIELDS + EXTRA_FIELDS
SOURCE_NOTE = "AKShareStockProvider / stock_zh_a_hist (eastmoney)"
REPRESENTATION_RAW = "provider-native values (no 4/2/6 rounding)"
REPRESENTATION_NORMALIZED = "canonical 4/2/6 rounding; this is what B passes to C"


class BatchError(RuntimeError):
    """The batch cannot be assembled or verified."""


# --------------------------------------------------------------------------- #
# Pure helpers - no I/O, so the tests can drive them with fixed fixtures.
# --------------------------------------------------------------------------- #


def as_schema(row: Mapping[str, Any]) -> DailyKlineSchema:
    """Validate one row and return it as the shared schema object."""
    missing = [name for name in REQUIRED_FIELDS if row.get(name) is None]
    if missing:
        raise BatchError(f"{row.get('trade_date')!r}: missing required fields {missing}")
    return DailyKlineSchema(**{name: row[name] for name in ROW_FIELDS if name in row})


def canonical_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Apply B's canonical 4/2/6 rounding to one provider-native row."""
    return _round_daily(as_schema(row)).model_dump(mode="json")


def frozen_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalise the row *shape* only - values stay provider-native."""
    return [as_schema(row).model_dump(mode="json") for row in rows]


def verify_pair(
    raw_rows: Sequence[Mapping[str, Any]], normalized_rows: Sequence[Mapping[str, Any]]
) -> List[str]:
    """Confirm ``normalized`` really is ``raw`` after canonical rounding.

    Returns a (possibly empty) list of problems; never raises, so callers can put
    the result straight into the manifest.
    """
    problems: List[str] = []
    if len(raw_rows) != len(normalized_rows):
        problems.append(f"row count differs: raw={len(raw_rows)} normalized={len(normalized_rows)}")
        return problems
    for raw, normalized in zip(raw_rows, normalized_rows):
        expected = canonical_row(raw)
        if expected != normalized:
            differing = [
                name
                for name in ROW_FIELDS
                if expected.get(name) != normalized.get(name)
            ]
            problems.append(f"{raw.get('trade_date')}: {differing}")
    return problems


def actual_window(rows: Sequence[Mapping[str, Any]]) -> Optional[List[str]]:
    days = [row["trade_date"] for row in rows if row.get("trade_date")]
    return [min(days), max(days)] if days else None


@dataclass(frozen=True)
class StockBatch:
    """One frozen provider response rendered as the two deliverables."""

    stock_code: str
    requested_window: Tuple[str, str]
    fetched_at_utc: str
    source: str
    raw_rows: Tuple[Dict[str, Any], ...]
    normalized_rows: Tuple[Dict[str, Any], ...]
    window: Optional[Tuple[str, str]]
    rounding_problems: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return bool(self.raw_rows) and not self.rounding_problems


def build_stock_batch(
    *,
    stock_code: str,
    requested_window: Tuple[str, str],
    rows: Sequence[Mapping[str, Any]],
    fetched_at_utc: str,
    source: str = SOURCE_NOTE,
) -> StockBatch:
    """Freeze ONE provider response into the two deliverables.

    Called exactly once per stock - it is the only place that consumes a provider
    response, which is what keeps the two outputs on the same snapshot.
    """
    raw = frozen_rows(rows)
    normalized = [canonical_row(row) for row in raw]
    problems = verify_pair(raw, normalized)
    window = actual_window(raw)
    return StockBatch(
        stock_code=stock_code,
        requested_window=requested_window,
        fetched_at_utc=fetched_at_utc,
        source=source,
        raw_rows=tuple(raw),
        normalized_rows=tuple(normalized),
        window=(window[0], window[1]) if window else None,
        rounding_problems=tuple(problems),
    )


def fetch_stock_batch(
    provider,
    *,
    stock_code: str,
    start_date: date,
    end_date: date,
    now: Callable[[], datetime],
) -> StockBatch:
    """Fetch **once** and freeze. The provider must not be touched again."""
    fetched_at = now()
    rows = [
        row.model_dump(mode="json")
        for row in provider.get_daily_kline(stock_code, start_date, end_date)
    ]
    return build_stock_batch(
        stock_code=stock_code,
        requested_window=(start_date.isoformat(), end_date.isoformat()),
        rows=rows,
        fetched_at_utc=fetched_at.isoformat(),
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_entry(path: Path, representation: str) -> Optional[Dict[str, Any]]:
    """Describe a file that is on disk right now (never an in-memory run)."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    return {
        "path": str(path),
        "rows": len(payload),
        "sha256": sha256_file(path),
        "captured_at_utc": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
        "actual_window": actual_window(payload),
        "representation": representation,
    }


def write_stock_batch(batch: StockBatch, out_dir: Path, window_token: str) -> Dict[str, Any]:
    """Write this batch's two files. An empty batch writes nothing.

    ``artifact_entry`` only runs when this batch actually produced rows: otherwise a
    leftover file from an earlier round at the same path would be reported as this
    batch's success - the exact mix-up C asked us to prevent.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{batch.stock_code}_qfq_raw_{window_token}.json"
    normalized_path = out_dir / f"{batch.stock_code}_qfq_normalized_{window_token}.json"
    if batch.raw_rows:
        write_json(raw_path, list(batch.raw_rows))
    if batch.normalized_rows:
        write_json(normalized_path, list(batch.normalized_rows))
    return {
        "raw": artifact_entry(raw_path, REPRESENTATION_RAW) if batch.raw_rows else None,
        "normalized": (
            artifact_entry(normalized_path, REPRESENTATION_NORMALIZED)
            if batch.normalized_rows
            else None
        ),
    }


# --------------------------------------------------------------------------- #
# Batch write + independent read-back
# --------------------------------------------------------------------------- #


def persist_normalized(session, batch: StockBatch) -> int:
    """Write this batch's normalized rows and commit them."""
    if not batch.normalized_rows:
        return 0
    repository = MarketDataRepository(session)
    rows = [DailyKlineSchema(**row) for row in batch.normalized_rows]
    repository.upsert_daily(rows)
    session.commit()
    return len(rows)


def readback_and_verify(
    batch: StockBatch,
    *,
    session_factory: Callable[[], Any],
) -> Dict[str, Any]:
    """Re-read this batch from the repository in a **new** session.

    No provider is consulted, and nothing is compared against a cache: the window
    is read straight out of the repository this batch just committed to.
    """
    if batch.window is None:
        return {"ok": False, "reason": "batch has no rows to read back", "rows": 0}
    start = date.fromisoformat(batch.window[0])
    end = date.fromisoformat(batch.window[1])
    try:
        with session_factory() as session:
            repository = MarketDataRepository(session)
            stored = repository.list_daily(batch.stock_code, start, end)
    except Exception as exc:  # noqa: BLE001 - a failed read-back means a failed batch
        return {
            "ok": False,
            "rows": 0,
            "window": None,
            "problems": [f"read-back failed: {type(exc).__name__}: {exc}"[:200]],
        }
    actual = [row.model_dump(mode="json") for row in stored]

    problems: List[str] = []
    expected = list(batch.normalized_rows)
    if len(actual) != len(expected):
        problems.append(f"row count differs: file={len(expected)} mysql={len(actual)}")
    expected_days = [row["trade_date"] for row in expected]
    actual_days = [row["trade_date"] for row in actual]
    if expected_days != actual_days:
        problems.append("date keys differ between the file and the read-back")
    else:
        for want, got in zip(expected, actual):
            differing = [name for name in ROW_FIELDS if want.get(name) != got.get(name)]
            if differing:
                problems.append(f"{want['trade_date']}: {differing}")
    return {
        "ok": not problems,
        "rows": len(actual),
        "window": [actual_days[0], actual_days[-1]] if actual_days else None,
        "problems": problems,
    }


# --------------------------------------------------------------------------- #
# Delivery gates and per-stock orchestration
# --------------------------------------------------------------------------- #


def ensure_publishable_dir(out_dir: Path) -> None:
    """Refuse to publish into a directory a previous batch already produced.

    Re-running a batch in place used to overwrite the files while the earlier
    ``status=ok`` manifest stayed behind with hashes that no longer matched the new
    files. A batch therefore owns a fresh directory; moving an old one away is an
    explicit human action, never a side effect of this script.
    """
    if out_dir.exists() and any(out_dir.iterdir()):
        raise BatchError(
            f"batch directory {out_dir} already exists and is not empty; use a new "
            "--batch id (or move the old directory away) - this script never "
            "overwrites a previous batch in place"
        )


def require_settled_day(settled_day: Optional[str]) -> str:
    """The batch's last complete trading day is mandatory.

    A delivery batch must state which settled session its window ends on: without it
    a provider response that reaches into an in-progress session would be published
    as final, which is exactly the defect C reproduced on 843f513.
    """
    if not settled_day:
        raise BatchError(
            "--last-complete-trading-day is required: state the last settled trading "
            "day (ISO date) this batch's window ends on, so an in-progress session "
            "can never be published as final"
        )
    return settled_day


def rows_beyond_settled_day(batch: StockBatch, settled_day: Optional[str]) -> List[str]:
    """Rows the provider returned after the batch's last complete trading day."""
    if not settled_day:
        return []
    return [row["trade_date"] for row in batch.raw_rows if row["trade_date"] > settled_day]


def export_stock(
    *,
    code: str,
    provider,
    session,
    session_factory: Callable[[], Any],
    out_dir: Path,
    window_token: str,
    start_date: date,
    end_date: date,
    now: Callable[[], datetime],
    database: str,
    settled_day: Optional[str],
) -> Dict[str, Any]:
    """Run one stock end to end and return its manifest entry.

    Nothing is written to disk or to the database until the fetch, the canonical
    rounding check and the settled-day gate have all passed, and every failure mode
    returns an entry with a non-``ok`` status so the manifest can never advertise a
    success that did not happen.
    """
    entry: Dict[str, Any] = {
        "stock_code": code,
        "requested_window": [start_date.isoformat(), end_date.isoformat()],
        "last_complete_trading_day": settled_day,
        "source": SOURCE_NOTE,
        "required_fields": list(REQUIRED_FIELDS),
        "extra_fields": list(EXTRA_FIELDS),
        "database": database,
        "raw": None,
        "normalized": None,
    }

    # Enforced here as well as in the CLI so the invariant cannot be bypassed by
    # calling export_stock directly - and before the provider is touched.
    if not settled_day:
        entry["status"] = "missing_settled_day"
        entry["error"] = "--last-complete-trading-day is required"
        entry["readback"] = {"ok": False, "reason": "gate rejected the batch"}
        return entry

    try:
        batch = fetch_stock_batch(
            provider, stock_code=code, start_date=start_date, end_date=end_date, now=now
        )
    except Exception as exc:  # noqa: BLE001 - a failed fetch is manifest data
        entry["status"] = "fetch_failed"
        entry["error"] = f"{type(exc).__name__}: {exc}"[:200]
        entry["readback"] = {"ok": False, "reason": "no rows fetched"}
        return entry

    entry["fetched_at_utc"] = batch.fetched_at_utc
    entry["actual_window"] = list(batch.window) if batch.window else None
    entry["rows"] = len(batch.raw_rows)
    entry["rounding_problems"] = list(batch.rounding_problems)

    if not batch.raw_rows:
        entry["status"] = "empty"
        entry["readback"] = {"ok": False, "reason": "provider returned no rows"}
        return entry

    # Gate before any side effect: a window that reaches past the settled day would
    # publish an in-progress session as if it were final.
    beyond = rows_beyond_settled_day(batch, settled_day)
    entry["rows_beyond_settled_day"] = beyond
    if beyond:
        entry["status"] = "beyond_settled_day"
        entry["error"] = (
            f"provider returned {len(beyond)} row(s) after {settled_day} "
            f"(first: {beyond[0]}); refusing to write files or database rows"
        )
        entry["readback"] = {"ok": False, "reason": "gate rejected the batch"}
        return entry

    try:
        files = write_stock_batch(batch, out_dir, window_token)
        entry["raw"] = files["raw"]
        entry["normalized"] = files["normalized"]
        entry["rows_written"] = persist_normalized(session, batch)
        entry["readback"] = readback_and_verify(batch, session_factory=session_factory)
    except Exception as exc:  # noqa: BLE001 - a failure must still be recorded
        entry["status"] = "export_failed"
        entry["error"] = f"{type(exc).__name__}: {exc}"[:300]
        entry.setdefault("readback", {"ok": False, "reason": "export raised"})
        return entry

    entry["status"] = (
        "ok"
        if entry["readback"]["ok"] and not batch.rounding_problems
        else "verification_failed"
    )
    return entry


# --------------------------------------------------------------------------- #
# Orchestration (live provider + real MySQL; exercised only by the CLI)
# --------------------------------------------------------------------------- #


def _git_sha() -> Optional[str]:
    try:
        result = subprocess.run(  # noqa: S603,S607 - local git, fixed args
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - env dependent
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", action="append", dest="codes")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2024, 12, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 9, 15))
    parser.add_argument(
        "--batch",
        default=date.today().strftime("%Y%m%d"),
        help="batch id; the output directory defaults to docs/evidence/c-delivery-<batch>",
    )
    parser.add_argument(
        "--last-complete-trading-day",
        default=None,
        help=(
            "REQUIRED. The settled trading day (ISO date) this batch's window ends "
            "on; a provider row after this day aborts the batch before any write"
        ),
    )
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    codes = args.codes or list(DEFAULT_STOCKS)
    window_token = f"{args.start_date:%Y%m%d}_{args.end_date:%Y%m%d}"
    out_dir = Path(args.output_dir or PROJECT_ROOT / "docs" / "evidence" / f"c-delivery-{args.batch}")

    # All gates run before any provider call, file write or database write.
    try:
        settled_day = require_settled_day(args.last_complete_trading_day)
        ensure_publishable_dir(out_dir)
    except BatchError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    settled = date.fromisoformat(settled_day)
    if args.end_date > settled:
        print(
            f"REFUSED: --end-date {args.end_date} is after "
            f"--last-complete-trading-day {settled_day}",
            file=sys.stderr,
        )
        return 2

    # Imported lazily so the pure helpers stay importable without a DB/provider.
    from backend.app.db.migrations import apply_migrations  # noqa: PLC0415
    from backend.app.db.session import SessionLocal, engine  # noqa: PLC0415
    from backend.app.services.stock_service import StockService  # noqa: PLC0415

    apply_migrations(engine)
    provider = StockService()
    now = lambda: datetime.now(timezone.utc)  # noqa: E731
    settings = get_settings()

    manifest: List[Dict[str, Any]] = []
    aborted: Optional[str] = None
    session = None
    try:
        session = SessionLocal()
        for code in codes:
            entry = export_stock(
                code=code,
                provider=provider,
                session=session,
                session_factory=SessionLocal,
                out_dir=out_dir,
                window_token=window_token,
                start_date=args.start_date,
                end_date=args.end_date,
                now=now,
                database=settings.mysql_database,
                settled_day=settled_day,
            )
            manifest.append(entry)
            print(
                f"{code}: status={entry['status']} rows={entry.get('rows')} "
                f"readback_ok={(entry.get('readback') or {}).get('ok')}",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001 - never exit without a manifest
        aborted = f"{type(exc).__name__}: {exc}"[:300]
        print(f"BATCH ABORTED: {aborted}", file=sys.stderr)
    finally:
        if session is not None:
            session.close()
        # Written on every path - a crash must not leave an older success manifest
        # standing next to files it no longer describes.
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "MANIFEST.json"
        write_json(
            manifest_path,
            {
                "batch": args.batch,
                "status": (
                    "aborted"
                    if aborted
                    else (
                        "ok"
                        if manifest and all(item["status"] == "ok" for item in manifest)
                        else "failed"
                    )
                ),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "code_sha": _git_sha(),
                "requested_window": [args.start_date.isoformat(), args.end_date.isoformat()],
                "last_complete_trading_day": settled_day,
                "aborted_reason": aborted,
                "canonical_precision": {
                    "price_ndigits": PRICE_NDIGITS,
                    "amount_ndigits": AMOUNT_NDIGITS,
                    "percent_ndigits": PERCENT_NDIGITS,
                },
                "note": (
                    "raw and normalized are derived from ONE frozen provider response per "
                    "stock; readback is an independent repository read in a new session"
                ),
                "stocks": manifest,
            },
        )
        print("manifest:", manifest_path)

    ok = aborted is None and bool(manifest) and all(item["status"] == "ok" for item in manifest)
    print("BATCH OK" if ok else "BATCH FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
