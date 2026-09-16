# -*- coding: utf-8 -*-
"""Regression tests for ``scripts/verify_c_delivery_consistency.py``.

C loaded the first version of that tool (the ``abs(raw - normalized) > 1e-6``
implementation) and reported five concrete counterexamples:

1. a legal 4-decimal rounding (``10.123456 -> 10.1235``) was misreported as a
   material difference;
2. a wrong ``stock_code`` on the normalized side passed;
3. a duplicate date in ``raw`` passed because the dict silently overwrote it;
4. ``NaN`` in ``raw.close`` passed;
5. ``turnover_rate = null`` on both sides raised ``TypeError``.

Each is reproduced below, together with missing rows, unsorted dates and
``Infinity``. The root cause was comparing ``raw`` against ``normalized``
directly instead of recomputing B's canonical 4/2/6 rounding first; the tool now
reuses the production ``_round_daily`` helper so the two can never drift.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "verify_c_delivery_consistency.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_c_delivery_consistency", _SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _row(day: str, *, code: str = "600519", **overrides):
    row = {
        "stock_code": code,
        "trade_date": day,
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 1000,
        "amount": 100000.0,
        "turnover_rate": 0.01,
        "change_pct": 0.02,
    }
    row.update(overrides)
    return row


def _pair(tmp_path, raw_rows, normalized_rows):
    raw = tmp_path / "600519_qfq_raw_20241201_20260915.json"
    normalized = tmp_path / "600519_qfq_normalized_20241201_20260915.json"
    raw.write_text(json.dumps(raw_rows), encoding="utf-8")
    normalized.write_text(json.dumps(normalized_rows), encoding="utf-8")
    return mod.compare(raw, normalized)


def _agrees(report) -> bool:
    return not report["structural_problems"] and not report["materially_different_rows"]


# -- C's five counterexamples -------------------------------------------------


def test_canonical_rounding_is_not_a_material_difference(tmp_path):
    """C1: ``10.123456`` canonicalises to ``10.1235`` and must pass."""
    report = _pair(
        tmp_path,
        [_row("2026-09-14", open=10.1, high=10.2, low=10.0, close=10.123456)],
        [_row("2026-09-14", open=10.1, high=10.2, low=10.0, close=10.1235)],
    )

    assert _agrees(report), report
    assert report["rounding_only_rows"] == 1


def test_wrong_stock_code_on_normalized_side_fails(tmp_path):
    """C2: a mismatched code must fail, not pass."""
    report = _pair(
        tmp_path,
        [_row("2026-09-14")],
        [_row("2026-09-14", code="000001")],
    )

    assert not _agrees(report)
    assert any("stock_code differs" in item for item in report["structural_problems"])


def test_duplicate_trade_date_in_raw_fails(tmp_path):
    """C3: a duplicate date must fail instead of being silently overwritten."""
    report = _pair(
        tmp_path,
        [_row("2026-09-14"), _row("2026-09-14", close=100.5)],
        [_row("2026-09-14")],
    )

    assert not _agrees(report)
    assert any("duplicate trade_date" in item for item in report["structural_problems"])


def test_non_finite_close_fails(tmp_path):
    """C4: ``NaN`` survives ``json.loads`` and must be rejected."""
    raw = [_row("2026-09-14")]
    raw[0]["close"] = float("nan")

    report = _pair(tmp_path, raw, [_row("2026-09-14")])

    assert not _agrees(report)
    assert any("finite" in item for item in report["structural_problems"])


def test_optional_null_on_both_sides_is_accepted(tmp_path):
    """C5: optional fields may be ``null`` on both sides - no ``TypeError``."""
    raw = [_row("2026-09-14", amount=None, turnover_rate=None, change_pct=None)]
    normalized = [_row("2026-09-14", amount=None, turnover_rate=None, change_pct=None)]

    report = _pair(tmp_path, raw, normalized)

    assert _agrees(report), report


# -- further structural boundaries -------------------------------------------


def test_row_missing_from_normalized_fails(tmp_path):
    report = _pair(
        tmp_path,
        [_row("2026-09-14"), _row("2026-09-15")],
        [_row("2026-09-14")],
    )

    assert not _agrees(report)
    assert any("only in raw" in item for item in report["structural_problems"])
    assert any("row count differs" in item for item in report["structural_problems"])


def test_unsorted_dates_fail(tmp_path):
    report = _pair(
        tmp_path,
        [_row("2026-09-15"), _row("2026-09-14")],
        [_row("2026-09-14"), _row("2026-09-15")],
    )

    assert not _agrees(report)
    assert any("strictly ascending" in item for item in report["structural_problems"])


def test_infinite_value_fails(tmp_path):
    raw = [_row("2026-09-14")]
    raw[0]["volume"] = float("inf")

    report = _pair(tmp_path, raw, [_row("2026-09-14")])

    assert not _agrees(report)
    assert any("finite" in item for item in report["structural_problems"])


def test_missing_required_field_fails(tmp_path):
    raw = [_row("2026-09-14")]
    del raw[0]["close"]

    report = _pair(tmp_path, raw, [_row("2026-09-14")])

    assert not _agrees(report)
    assert any("missing required fields" in item for item in report["structural_problems"])


def test_genuine_second_snapshot_is_still_reported(tmp_path):
    """The real 600519 ``2026-09-15`` shape must still fail.

    Canonical rounding must not paper over two different intraday snapshots.
    """
    report = _pair(
        tmp_path,
        [
            _row(
                "2026-09-15",
                open=1281.0,
                high=1284.5,
                low=1271.28,
                close=1272.75,
                volume=13762,
                amount=1756915149.0,
                turnover_rate=0.0011,
                change_pct=-0.0041,
            )
        ],
        [
            _row(
                "2026-09-15",
                open=1281.0,
                high=1284.5,
                low=1273.0,
                close=1278.66,
                volume=2942,
                amount=376338636.0,
                turnover_rate=0.0002,
                change_pct=0.0005,
            )
        ],
    )

    assert not _agrees(report)
    fields = report["materially_different_rows"][0]["fields"]
    assert set(fields) == {
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "change_pct",
    }


# -- the shipped package ------------------------------------------------------


def test_shipped_package_matches_the_known_findings():
    """Pin the current package state: only 600519 ``2026-09-15`` disagrees.

    Reproduces C's independent result on the committed artefacts. **Update this
    expectation when the package is regenerated from a single frozen fetch** -
    a failure here after regenerating means the new package really is cleaner.
    """
    base = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "c-delivery"
    if not base.is_dir():
        pytest.skip("delivery package is not present in this checkout")

    results = {}
    for raw_path in sorted(base.glob("*_qfq_raw_*.json")):
        normalized_path = Path(str(raw_path).replace("_qfq_raw_", "_qfq_normalized_"))
        results[raw_path.name.split("_")[0]] = mod.compare(raw_path, normalized_path)

    assert set(results) == {"000001", "300750", "600519"}
    for report in results.values():
        assert report["structural_problems"] == [], report
        assert report["rows"] == 436

    assert results["000001"]["materially_different_rows"] == []
    assert results["300750"]["materially_different_rows"] == []
    assert [
        row["trade_date"] for row in results["600519"]["materially_different_rows"]
    ] == ["2026-09-15"]
