"""Offline contract tests for the frozen package builder.

Encodes D's ``scripts/frozen_acceptance.py::load_package`` metadata contract
(no network / no DB): required top-level fields, tz-aware ``captured_at``,
exact ``quant_expectations``, and file entries with ``file`` + ``sha256``.
"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_frozen_package.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_frozen_package", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _source_meta():
    return {
        "kline": {
            "stock_code": "600519",
            "actual_start_date": "2025-01-02",
            "actual_end_date": "2026-08-31",
            "fetch_finished_at_utc": "2026-09-09T02:05:50.619248+00:00",
            "rows": 403,
            "period": "daily",
            "adjust": "qfq",
            "file": "600519_qfq_20250101_20260831.json",
            "sha256": "fe6622",
        },
        "calendar": {
            "file": "a_share_trade_dates.json",
            "sha256": "20ea7c",
        },
    }


def _build():
    return mod.build_metadata(
        _source_meta(),
        stock_entry={"file": "stock_basic_600519.json", "sha256": "aa"},
        readback_entry={"file": "mysql_readback_600519.json", "sha256": "bb"},
        quant_config={"contract_status": "provisional"},
    )


def test_metadata_has_all_required_top_level_keys():
    meta = _build()
    for key in mod.REQUIRED_TOP_LEVEL:
        assert key in meta


def test_metadata_matches_d_contract_values():
    meta = _build()

    assert meta["stock_code"] == "600519"
    assert meta["actual_start_date"] == "2025-01-02"
    assert meta["actual_end_date"] == "2026-08-31"
    assert int(meta["rows"]) == 403
    assert meta["adjust"] == "qfq"
    captured = datetime.fromisoformat(str(meta["captured_at"]).replace("Z", "+00:00"))
    assert captured.tzinfo is not None  # must be timezone-aware
    assert meta["quant_expectations"] == {
        "score": 33,
        "order_count": 24,
        "equity_curve_points": 403,
        "total_return": -0.09165774117956027,
        "final_equity": 90834.22588204397,
    }


def test_metadata_file_entries_carry_file_and_sha256():
    meta = _build()
    for key in ("kline", "calendar", "stock", "readback"):
        assert meta[key]["file"]
        assert meta[key]["sha256"]


def test_stock_snapshot_from_raw_maps_eastmoney_fields():
    raw = {
        "data": {
            "f57": "600519",
            "f58": "贵州茅台",
            "f116": 1.0,
            "f117": 2.0,
            "f127": "白酒Ⅱ",
        }
    }

    snapshot = mod.stock_snapshot_from_raw(raw)

    assert snapshot == {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "total_market_cap": 1.0,
        "float_market_cap": 2.0,
        "industry": "白酒Ⅱ",
    }


def test_resolve_source_metadata_prefers_original_and_honours_explicit(tmp_path):
    original = tmp_path / "metadata(1).json"
    original.write_text("{}", encoding="utf-8")
    explicit = tmp_path / "other.json"
    explicit.write_text("{}", encoding="utf-8")

    assert mod.resolve_source_metadata(tmp_path) == original
    assert mod.resolve_source_metadata(tmp_path, str(explicit)) == explicit


def test_assert_source_hashes_blocks_on_mismatch(tmp_path):
    (tmp_path / "k.json").write_text("k", encoding="utf-8")
    (tmp_path / "c.json").write_text("c", encoding="utf-8")
    meta = {
        "kline": {"file": "k.json", "sha256": mod.sha256(tmp_path / "k.json")},
        "calendar": {"file": "c.json", "sha256": mod.sha256(tmp_path / "c.json")},
    }
    mod.assert_source_hashes(meta, tmp_path)  # no error

    meta["kline"]["sha256"] = "0" * 64
    with pytest.raises(SystemExit):
        mod.assert_source_hashes(meta, tmp_path)
