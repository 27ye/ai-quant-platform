"""Offline evidence must fail on mismatches and never overwrite previous runs."""

import json
import socket
from datetime import date

import pytest

from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.quant.serialization import dataframe_records
from scripts import validate_v2_backtest as delivery
from scripts.validate_quant_core import build_synthetic_daily_data


@pytest.fixture
def small_data():
    return build_synthetic_daily_data("600519", date(2024, 1, 1), date(2025, 1, 1)).iloc[:130].copy()


@pytest.fixture
def offline(monkeypatch, small_data):
    def deny_network(*args, **kwargs):
        raise AssertionError("offline evidence attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(delivery, "build_synthetic_daily_data", lambda *args: small_data.copy())
    # Isolate tests from other agents editing unrelated working-tree files. The
    # standalone CLI additionally checks the actual git/source provenance.
    monkeypatch.setattr(delivery, "_source_provenance", lambda: {
        "git_head": "fixture", "tracked_source_diff": "", "tracked_source_diff_sha256": "fixture",
        "source_fingerprint_sha256": "fixture", "source_files_sha256": {},
    })


def test_complete_evidence_and_json_only_replay(tmp_path, offline, small_data):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(analyze_quant_dataframe(small_data), allow_nan=False), encoding="utf-8")
    output = tmp_path / "evidence"
    assert delivery.main(["--output-dir", str(output), "--expected-v1-json", str(baseline)]) == 0
    manifest = delivery._load_json(output / "manifest.json")
    assert manifest["status"] == "passed"
    assert manifest["evidence_scope"] == "offline_quant_only"
    assert manifest["source_mode"] == "synthetic"
    assert manifest["expected_v1_baseline"]["full_json_equal"] is True
    assert len(manifest["not_verified"]) == 4
    for name, item in manifest["files"].items():
        assert delivery._sha256((output / name).read_bytes()) == item["sha256"]
    results = [
        delivery._load_json(output / name)
        for name in ("v1-legacy.json", "v2-default.json", "v2-ma10-30.json", "v2-ma20-60-cost.json", "v2-long120-one-day.json")
    ]
    for result in results:
        assert delivery.replay_backtest_result(result) == result
    assert len(results[-1]["equity_curve"]) == 1
    assert results[-1]["warmup"]["used_rows"] == 120
    assert len(results[1]["equity_curve"]) == 10
    assert results[3]["initial_cash"] == 200000
    assert results[3]["effective_parameters"]["slippage"] == 0.001


def test_baseline_mismatch_fails_beyond_headline_numbers(tmp_path, offline, small_data):
    baseline = analyze_quant_dataframe(small_data)
    baseline["series"]["indicators"][-1]["ma5"] += 0.001
    path = tmp_path / "wrong-baseline.json"
    path.write_text(json.dumps(baseline, allow_nan=False), encoding="utf-8")
    output = tmp_path / "evidence"
    assert delivery.main(["--output-dir", str(output), "--expected-v1-json", str(path)]) == 1
    manifest = delivery._load_json(output / "manifest.json")
    assert manifest["status"] == "failed"
    assert "series.indicators[129].ma5" in manifest["failure"]["message"]
    assert "expected_v1_baseline" not in manifest


def test_existing_directory_is_never_overwritten(tmp_path, offline):
    marker = tmp_path / "manifest.json"
    marker.write_text("previous evidence", encoding="utf-8")
    assert delivery.main(["--output-dir", str(tmp_path)]) == 1
    assert marker.read_text(encoding="utf-8") == "previous evidence"
    assert list(tmp_path.iterdir()) == [marker]


def test_external_short_input_fails_without_fetching_more_rows(tmp_path, offline, small_data):
    path = tmp_path / "short.json"
    path.write_text(json.dumps(dataframe_records(small_data.iloc[:121]), allow_nan=False), encoding="utf-8")
    output = tmp_path / "evidence"
    assert delivery.main(["--output-dir", str(output), "--input-json", str(path)]) == 1
    manifest = delivery._load_json(output / "manifest.json")
    assert manifest["status"] == "failed"
    assert "122 valid rows" in manifest["failure"]["message"]


def test_snapshot_replay_rejects_changed_curve_point(small_data):
    result = delivery.run_backtest_request(
        small_data, start_date="2024-06-17", end_date="2024-06-28", parameters={}
    )
    result["equity_curve"][-1]["equity"] += 0.001
    with pytest.raises(AssertionError, match="equity_curve"):
        delivery.replay_backtest_result(result)


def test_external_json_data_mode_is_preserved(tmp_path, offline, small_data):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(dataframe_records(small_data), allow_nan=False), encoding="utf-8")
    output = tmp_path / "evidence"
    assert delivery.main(["--output-dir", str(output), "--input-json", str(path), "--data-mode", "frozen_fixture"]) == 0
    manifest = delivery._load_json(output / "manifest.json")
    saved = delivery._load_json(output / "v2-default.json")
    assert manifest["source_mode"] == "input_json"
    assert manifest["data_mode"] == "frozen_fixture"
    assert saved["input_snapshot"]["data_mode"] == "frozen_fixture"
