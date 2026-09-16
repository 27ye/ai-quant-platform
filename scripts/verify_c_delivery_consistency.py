# -*- coding: utf-8 -*-
"""Check that each ``*_raw_*`` delivery file and its ``*_normalized_*`` twin
describe the same bars.

The two artefacts answer different questions - ``raw`` is the provider-native
frame kept for source verification, ``normalized`` is the exact row set B hands
to C - but for every **settled** trading day they must differ only by B's
canonical 4/2/6 rounding. A larger difference means the two files were captured
from different snapshots of a still-open session. That is exactly how the 600519
``2026-09-15`` row ended up materially inconsistent (``low`` 1271.28 vs 1273.0,
``volume`` 13762 vs 2942, ...) in the first delivered package: the export script
fetches ``raw`` straight from the provider while ``normalized`` comes through the
DB-backed service, so an in-progress day can legitimately differ between them.

Exit code 1 when a material difference is found, so this can gate a delivery.

Usage:
    python scripts/verify_c_delivery_consistency.py
    python scripts/verify_c_delivery_consistency.py --dir docs/evidence/c-delivery
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = PROJECT_ROOT / "docs" / "evidence" / "c-delivery"
NUMERIC_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "change_pct",
)
#: Larger than float noise, far smaller than a real tick/rounding difference.
TOLERANCE = 1e-6


def load_rows(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path.name}: expected a JSON array of rows")
    return {row["trade_date"]: row for row in payload}


def compare(raw_path: Path, normalized_path: Path) -> dict:
    raw = load_rows(raw_path)
    normalized = load_rows(normalized_path)
    dates = sorted(set(raw) | set(normalized))
    only_in_one = sorted(day for day in dates if day not in raw or day not in normalized)

    material = []
    for day in dates:
        left, right = raw.get(day), normalized.get(day)
        if left is None or right is None:
            continue
        differing = {
            name: {"raw": left[name], "normalized": right[name]}
            for name in NUMERIC_FIELDS
            if abs(float(left[name]) - float(right[name])) > TOLERANCE
        }
        if differing:
            material.append({"trade_date": day, "fields": differing})

    return {
        "raw_file": raw_path.name,
        "normalized_file": normalized_path.name,
        "rows": len(dates),
        "rounding_only_rows": len(dates) - len(material) - len(only_in_one),
        "dates_only_in_one_file": only_in_one,
        "materially_different_rows": material,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    args = parser.parse_args()

    base = Path(args.dir)
    raw_files = sorted(base.glob("*_qfq_raw_*.json"))
    if not raw_files:
        print(f"no raw delivery files under {base}")
        return 1

    reports = []
    for raw_path in raw_files:
        normalized_path = Path(str(raw_path).replace("_qfq_raw_", "_qfq_normalized_"))
        if not normalized_path.exists():
            reports.append({"raw_file": raw_path.name, "error": "normalized twin missing"})
            continue
        reports.append(compare(raw_path, normalized_path))

    print(
        json.dumps(
            {"tolerance": TOLERANCE, "reports": reports}, ensure_ascii=False, indent=1
        )
    )

    broken = [
        report
        for report in reports
        if report.get("error")
        or report.get("materially_different_rows")
        or report.get("dates_only_in_one_file")
    ]
    if broken:
        print(f"\nFAIL: {len(broken)} stock(s) with material raw/normalized differences")
        return 1
    print("\nOK: every raw/normalized pair agrees within rounding for all rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
