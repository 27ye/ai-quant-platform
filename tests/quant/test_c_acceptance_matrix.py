"""Synthetic-only fixtures for the fixed-window C delivery acceptance runner."""

import hashlib
import json
import socket

import pandas as pd
import pytest

from scripts import validate_v2_c_acceptance as acceptance


def _write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def synthetic_delivery(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("offline C matrix attempted network I/O")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(acceptance, "_source_provenance", lambda: {
        "git_base_head": "synthetic-test-base-not-a-real-sha",
        "source_fingerprint_sha256": "synthetic-test-source-fingerprint",
        "affected_source_status": "synthetic-test-fixture",
        "affected_source_dirty": True,
    })
    delivery = tmp_path / "synthetic-delivery"
    delivery.mkdir()
    # The three files intentionally have different amounts of pre-window data;
    # choosing row 120 as the start would give three wrong/different windows.
    starts = {"600519": "2024-12-02", "000001": "2024-10-01", "300750": "2024-08-01"}
    for code, start in starts.items():
        rows = []
        for index, day in enumerate(pd.bdate_range(start, "2026-09-15")):
            price = 100.0 + (index % 45) * 0.3
            rows.append({
                "stock_code": code, "trade_date": day.strftime("%Y-%m-%d"),
                "open": price, "high": price + 1, "low": price - 1,
                "close": price + 0.25, "volume": 1000.0,
            })
        _write_json(delivery / acceptance.FILENAME_TEMPLATE.format(code=code), rows)
    hashes_path = tmp_path / "independently-confirmed-synthetic-hashes.json"

    def refresh_hashes():
        _write_json(hashes_path, {
            acceptance.FILENAME_TEMPLATE.format(code=code): hashlib.sha256(
                (delivery / acceptance.FILENAME_TEMPLATE.format(code=code)).read_bytes()
            ).hexdigest()
            for code in acceptance.STOCK_CODES
        })

    refresh_hashes()
    return delivery, hashes_path, refresh_hashes


def _run(tmp_path, synthetic_delivery, extra=()):
    delivery, hashes, _ = synthetic_delivery
    output = tmp_path / "matrix-evidence"
    code = acceptance.main([
        "--delivery-dir", str(delivery), "--expected-hashes", str(hashes),
        "--output-dir", str(output), "--data-mode", "synthetic_fixture",
        *extra,
    ])
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    return code, output, report


def test_three_stocks_nine_cases_use_fixed_dates_and_exact_saved_replay(tmp_path, synthetic_delivery):
    code, output, report = _run(tmp_path, synthetic_delivery)
    assert code == 0
    assert report["status"] == "passed"
    assert report["completed_cases"] == 9
    assert report["data_mode"] == "synthetic_fixture"
    assert report["requested_window"] == {"start_date": "2025-07-04", "end_date": "2026-08-31"}
    assert report["source"]["affected_source_dirty"] is True
    assert "MySQL persistence/readback" in report["not_verified"]
    assert len({item["available_prior_rows"] for item in report["inputs"].values()}) == 3
    expected_days = pd.bdate_range("2025-07-04", "2026-08-31").strftime("%Y-%m-%d").tolist()
    for case in report["matrix"]:
        result = json.loads((output / case["result_file"]).read_text(encoding="utf-8"))
        request = json.loads((output / case["request_file"]).read_text(encoding="utf-8"))
        assert request == case["request"]
        assert request["start_date"] == "2025-07-04"
        assert request["end_date"] == "2026-08-31"
        assert result["semantics_version"] == "v2_windowed"
        assert result["start_date"] == "2025-07-04"
        assert result["end_date"] == "2026-08-31"
        assert result["input_snapshot"]["data_mode"] == "synthetic_fixture"
        assert result["data_hash"] == case["c_data_hash"]
        assert [point["trade_date"] for point in result["equity_curve"]] == expected_days
        assert case["warmup"]["used_rows"] in (20, 30, 60)
        assert case["full_saved_json_replay_equal"] is True
        assert acceptance.replay_backtest_result(result) == result
    for name, details in report["files"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == details["sha256"]


def test_explicit_dates_override_defaults_for_all_nine_cases(tmp_path, synthetic_delivery):
    code, _, report = _run(tmp_path, synthetic_delivery, ("--start-date", "2025-08-01", "--end-date", "2025-08-04"))
    assert code == 0
    assert len(report["matrix"]) == 9
    assert all(case["curve_points"]["equity_curve"] == 2 for case in report["matrix"])
    assert all(case["request"]["start_date"] == "2025-08-01" for case in report["matrix"])


def test_tampered_file_rejected_even_when_package_manifest_agrees(tmp_path, synthetic_delivery):
    delivery, _, _ = synthetic_delivery
    filename = acceptance.FILENAME_TEMPLATE.format(code="600519")
    path = delivery / filename
    rows = json.loads(path.read_text(encoding="utf-8"))
    rows[0]["volume"] += 1
    _write_json(path, rows)
    _write_json(delivery / "MANIFEST.json", {filename: hashlib.sha256(path.read_bytes()).hexdigest()})
    code, output, report = _run(tmp_path, synthetic_delivery)
    assert code == 1
    assert report["status"] == "failed"
    assert "SHA256 mismatch" in report["failure"]["message"]
    assert report["matrix"] == []
    assert not list(output.glob("*.result.json"))


@pytest.mark.parametrize("change, message", [
    ("wrong_stock", "stock_code"),
    ("numeric_stock", "stock_code"),
    ("duplicate_date", "strictly increasing and unique"),
    ("out_of_order", "strictly increasing and unique"),
    ("short_warmup", "at least 120"),
    ("empty_window", "no valid daily rows"),
    ("invalid_ohlc", "high must be greater"),
    ("boolean_price", "finite JSON number"),
    ("string_price", "finite JSON number"),
    ("bad_date", "valid calendar date"),
])
def test_malformed_delivery_rejected_before_any_case(tmp_path, synthetic_delivery, change, message):
    delivery, _, refresh = synthetic_delivery
    path = delivery / acceptance.FILENAME_TEMPLATE.format(code="000001")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if change == "wrong_stock":
        rows[0]["stock_code"] = "600519"
    elif change == "numeric_stock":
        rows[0]["stock_code"] = 1
    elif change == "duplicate_date":
        rows[1]["trade_date"] = rows[0]["trade_date"]
    elif change == "out_of_order":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "short_warmup":
        prior = [row for row in rows if row["trade_date"] < "2025-07-04"]
        window = [row for row in rows if row["trade_date"] >= "2025-07-04"]
        rows = prior[-119:] + window
    elif change == "empty_window":
        rows = [row for row in rows if row["trade_date"] < "2025-07-04"]
    elif change == "invalid_ohlc":
        rows[0]["high"] = 1
    elif change == "boolean_price":
        rows[0]["open"] = True
    elif change == "string_price":
        rows[0]["open"] = "100"
    elif change == "bad_date":
        rows[0]["trade_date"] = "2024-02-30"
    _write_json(path, rows)
    refresh()
    code, output, report = _run(tmp_path, synthetic_delivery)
    assert code == 1
    assert report["status"] == "failed"
    assert message in report["failure"]["message"]
    assert report["matrix"] == []
    assert not list(output.glob("*.result.json"))


def test_missing_stock_is_not_replaced_by_another_file(tmp_path, synthetic_delivery):
    delivery, _, _ = synthetic_delivery
    (delivery / acceptance.FILENAME_TEMPLATE.format(code="300750")).unlink()
    code, output, report = _run(tmp_path, synthetic_delivery)
    assert code == 1
    assert report["status"] == "failed"
    assert "missing required normalized file" in report["failure"]["message"]
    assert "300750" in report["failure"]["message"]
    assert not list(output.glob("*.result.json"))


def test_missing_independently_confirmed_hash_fails(tmp_path, synthetic_delivery):
    _, hashes, _ = synthetic_delivery
    values = json.loads(hashes.read_text(encoding="utf-8"))
    del values[acceptance.FILENAME_TEMPLATE.format(code="300750")]
    _write_json(hashes, values)
    code, _, report = _run(tmp_path, synthetic_delivery)
    assert code == 1
    assert "expected hashes missing" in report["failure"]["message"]


def test_existing_output_never_overwritten(tmp_path, synthetic_delivery):
    delivery, hashes, _ = synthetic_delivery
    output = tmp_path / "already-exists"
    output.mkdir()
    marker = output / "report.json"
    marker.write_text("original evidence", encoding="utf-8")
    assert acceptance.main([
        "--delivery-dir", str(delivery), "--expected-hashes", str(hashes), "--output-dir", str(output),
    ]) == 1
    assert marker.read_text(encoding="utf-8") == "original evidence"
    assert list(output.iterdir()) == [marker]


def test_saved_result_tampering_fails_replay(tmp_path, synthetic_delivery, monkeypatch):
    original_save = acceptance._save_json

    def tamper(output, name, value, report):
        saved = original_save(output, name, value, report)
        if name.endswith(".result.json"):
            saved["equity_curve"][0]["equity"] += 1
        return saved

    monkeypatch.setattr(acceptance, "_save_json", tamper)
    code, _, report = _run(tmp_path, synthetic_delivery)
    assert code == 1
    assert report["status"] == "failed"
    assert "equity_curve" in report["failure"]["message"]
