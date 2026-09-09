"""Offline unit tests for the frozen-sample verification helpers."""
import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.app.schemas.stock import DailyKlineSchema

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_frozen_mysql.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_frozen_mysql", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _bars(n, start=date(2025, 1, 1), close_offset=0.0):
    import math

    results = []
    for i in range(n):
        close = 100 + i * 0.2 + 5 * math.sin(i / 2.0) + close_offset
        results.append(
            DailyKlineSchema(
                stock_code="600519",
                trade_date=start + timedelta(days=i),
                open=close - 1.0,
                high=close + 2.0,
                low=close - 2.0,
                close=close,
                volume=1000 + i * 10,
                amount=close * 1000,
                turnover_rate=0.01,
                change_pct=0.01,
            )
        )
    return results


def test_metadata_resolution_prefers_metadata_json(tmp_path):
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "metadata(1).json").write_text("{}", encoding="utf-8")

    assert mod.resolve_metadata_path(tmp_path) == tmp_path / "metadata.json"


def test_metadata_resolution_falls_back_to_metadata_star(tmp_path):
    (tmp_path / "metadata(1).json").write_text("{}", encoding="utf-8")

    assert mod.resolve_metadata_path(tmp_path) == tmp_path / "metadata(1).json"


def test_metadata_resolution_errors_on_multiple_star_files(tmp_path):
    (tmp_path / "metadata(1).json").write_text("{}", encoding="utf-8")
    (tmp_path / "metadata(2).json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit):
        mod.resolve_metadata_path(tmp_path)


def test_metadata_resolution_errors_when_none_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        mod.resolve_metadata_path(tmp_path)


def test_metadata_resolution_explicit_wins(tmp_path):
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    explicit = tmp_path / "custom.json"
    explicit.write_text("{}", encoding="utf-8")

    assert mod.resolve_metadata_path(tmp_path, str(explicit)) == explicit


def test_assert_hash_matches_blocks_on_mismatch(tmp_path):
    path = tmp_path / "a.json"
    path.write_bytes(b"hello")

    expected = mod.file_sha256(path)
    mod.assert_hash_matches(path, expected)  # no error
    with pytest.raises(SystemExit):
        mod.assert_hash_matches(path, "0" * 64)


def test_compare_analyses_detects_difference_without_db():
    direct = _bars(60)
    readback = _bars(60, close_offset=5.0)  # different data -> must not compare equal

    result = mod.compare_analyses(direct, readback)

    assert result["data_equal"] is False
    assert result["analysis_equal"] is False


def test_compare_analyses_identical_data_is_equal():
    direct = _bars(60)
    # Simulate the DB read-back as the rounded canonical bars (as list_daily returns).
    direct_frame = mod.build_direct_frame(direct)
    readback = [DailyKlineSchema(**row) for row in direct_frame.to_dict("records")]

    result = mod.compare_analyses(direct, readback)

    assert result["data_equal"] is True
    assert result["analysis_equal"] is True
