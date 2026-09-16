# -*- coding: utf-8 -*-
"""Check that each ``*_raw_*`` delivery file and its ``*_normalized_*`` twin
describe the same bars.

``raw`` is the provider-native frame kept for source verification; ``normalized``
is the exact row set B hands to C. They are *not* expected to be byte-identical:
``normalized`` is ``raw`` passed through B's canonical 4/2/6 rounding, so this
tool recomputes that rounding with the **production** helper
(:func:`backend.app.services.market_data_service._round_daily`) and compares the
result field by field. Reusing the production helper is deliberate - a second
copy of the rounding rules could silently drift away from what C actually gets,
and widening a tolerance instead would hide exactly the defect this catches.

Structural problems (wrong stock code, duplicate/unsorted dates, non-finite
numbers, differing key sets) are reported separately from value differences and
also fail the check.

Exit codes: 0 = every pair agrees, 1 = at least one pair failed.

Usage:
    python scripts/verify_c_delivery_consistency.py
    python scripts/verify_c_delivery_consistency.py --dir docs/evidence/c-delivery
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.schemas.stock import DailyKlineSchema  # noqa: E402
from backend.app.services.market_data_service import _round_daily  # noqa: E402

DEFAULT_DIR = PROJECT_ROOT / "docs" / "evidence" / "c-delivery"

#: Fields C requires on every row (the rest are optional extras).
REQUIRED_FIELDS = ("stock_code", "trade_date", "open", "high", "low", "close", "volume")
#: Every field the canonical rounding covers, so every field this tool compares.
COMPARED_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "change_pct",
)
SCHEMA_FIELDS = (
    "stock_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "change_pct",
)


class DeliveryFormatError(ValueError):
    """The file is malformed as a delivery artefact (structure, not values)."""


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _load_rows(path: Path) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeliveryFormatError(f"{path.name}: cannot read JSON ({exc})") from exc
    if not isinstance(payload, list):
        raise DeliveryFormatError(f"{path.name}: expected a JSON array of rows")
    if not payload:
        raise DeliveryFormatError(f"{path.name}: contains no rows")
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise DeliveryFormatError(f"{path.name}: row {index} is not an object")
    return payload


def _canonical_row(row: Dict[str, Any], *, source: str) -> DailyKlineSchema:
    """Validate one row and return it as a schema object.

    Rejects missing required fields and non-finite numbers (``NaN`` / ``Infinity``
    survive ``json.loads`` and would otherwise slip through every comparison).
    """
    day = row.get("trade_date")
    missing = [name for name in REQUIRED_FIELDS if row.get(name) is None]
    if missing:
        raise DeliveryFormatError(f"{source}: {day!r}: missing required fields {missing}")
    for name in COMPARED_FIELDS:
        value = row.get(name)
        if value is not None and not _is_finite_number(value):
            raise DeliveryFormatError(
                f"{source}: {day!r}: {name}={value!r} is not a finite number"
            )
    try:
        return DailyKlineSchema(**{name: row[name] for name in SCHEMA_FIELDS if name in row})
    except Exception as exc:  # noqa: BLE001 - pydantic raises ValidationError
        raise DeliveryFormatError(f"{source}: {day!r}: {exc}") from exc


def _index_by_date(rows: Sequence[Dict[str, Any]], *, source: str) -> Dict[str, DailyKlineSchema]:
    """Index rows by ISO date, enforcing one stock, strict ascending order and uniqueness."""
    indexed: Dict[str, DailyKlineSchema] = {}
    previous: Optional[date] = None
    expected_code: Optional[str] = None
    for row in rows:
        schema = _canonical_row(row, source=source)
        key = schema.trade_date.isoformat()
        if key in indexed:
            raise DeliveryFormatError(f"{source}: duplicate trade_date {key}")
        if previous is not None and schema.trade_date <= previous:
            raise DeliveryFormatError(
                f"{source}: trade_date is not strictly ascending at {key}"
            )
        if expected_code is None:
            expected_code = schema.stock_code
        elif schema.stock_code != expected_code:
            raise DeliveryFormatError(
                f"{source}: mixed stock_code {expected_code!r} / {schema.stock_code!r} at {key}"
            )
        indexed[key] = schema
        previous = schema.trade_date
    return indexed


def compare(raw_path: Path, normalized_path: Path) -> Dict[str, Any]:
    """Compare one raw/normalized pair. Structural failures are reported, not raised."""
    report: Dict[str, Any] = {
        "raw_file": raw_path.name,
        "normalized_file": normalized_path.name,
        "rows": None,
        "structural_problems": [],
        "rounding_only_rows": None,
        "materially_different_rows": [],
    }

    try:
        raw = _index_by_date(_load_rows(raw_path), source=raw_path.name)
        normalized = _index_by_date(_load_rows(normalized_path), source=normalized_path.name)
    except DeliveryFormatError as exc:
        report["structural_problems"] = [str(exc)]
        return report

    problems: List[str] = report["structural_problems"]
    raw_codes = sorted({row.stock_code for row in raw.values()})
    normalized_codes = sorted({row.stock_code for row in normalized.values()})
    if raw_codes != normalized_codes:
        problems.append(
            f"stock_code differs: raw={raw_codes} normalized={normalized_codes}"
        )
    only_raw = sorted(set(raw) - set(normalized))
    only_normalized = sorted(set(normalized) - set(raw))
    if only_raw:
        problems.append(f"dates only in raw: {only_raw}")
    if only_normalized:
        problems.append(f"dates only in normalized: {only_normalized}")
    if len(raw) != len(normalized):
        problems.append(f"row count differs: raw={len(raw)} normalized={len(normalized)}")

    material: List[Dict[str, Any]] = []
    for day in sorted(set(raw) & set(normalized)):
        expected = _round_daily(raw[day])
        actual = normalized[day]
        differing = {}
        for name in COMPARED_FIELDS:
            left = getattr(expected, name)
            right = getattr(actual, name)
            if left != right:
                differing[name] = {"expected_from_raw": left, "normalized": right}
        if differing:
            material.append({"trade_date": day, "fields": differing})

    report["rows"] = len(raw)
    report["rounding_only_rows"] = (
        len(set(raw) & set(normalized)) - len(material)
    )
    report["materially_different_rows"] = material
    return report


def _iter_pairs(base: Path) -> List[Any]:
    return sorted(base.glob("*_qfq_raw_*.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    args = parser.parse_args()

    base = Path(args.dir)
    raw_files = _iter_pairs(base)
    if not raw_files:
        print(f"no raw delivery files under {base}")
        return 1

    reports = []
    for raw_path in raw_files:
        normalized_path = Path(str(raw_path).replace("_qfq_raw_", "_qfq_normalized_"))
        if not normalized_path.exists():
            reports.append(
                {
                    "raw_file": raw_path.name,
                    "normalized_file": normalized_path.name,
                    "rows": None,
                    "structural_problems": [f"{normalized_path.name}: normalized twin missing"],
                    "rounding_only_rows": None,
                    "materially_different_rows": [],
                }
            )
            continue
        reports.append(compare(raw_path, normalized_path))

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=1))

    broken = [
        report
        for report in reports
        if report["structural_problems"] or report["materially_different_rows"]
    ]
    if broken:
        print(f"\nFAIL: {len(broken)} of {len(reports)} pair(s) did not agree")
        return 1
    print(f"\nOK: all {len(reports)} raw/normalized pair(s) agree after canonical rounding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
