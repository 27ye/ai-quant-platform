"""Input provenance and exact replay invariants for a saved C result."""

import hashlib
import json
from datetime import date

import pandas as pd
import pytest

from backend.app.quant.backtest_config import BacktestParameterError
from backend.app.quant.windowed_backtest import (
    run_backtest_request,
    validate_backtest_window,
)


def _result(frame):
    return run_backtest_request(
        frame, start_date="2024-01-08", end_date="2024-01-09",
        parameters={"ma_short_period": 2, "ma_long_period": 3},
    )


def test_snapshot_contains_only_the_actual_input_and_no_arbitrary_metadata(frame_factory):
    frame = frame_factory([10, 10, 10, 11, 12, 11, 10, 9, 8])
    frame["display_only"] = "unused"
    frame.attrs["unrelated_metadata"] = "not part of the calculation"
    result = _result(frame)
    snapshot = result["input_snapshot"]
    assert [row["trade_date"] for row in snapshot["rows"]] == [
        "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"
    ]
    assert result["warmup"] == {
        "start_date": "2024-01-03", "end_date": "2024-01-05",
        "required_rows": 3, "used_rows": 3,
    }
    assert "display_only" not in snapshot["columns"]
    assert "unrelated_metadata" not in snapshot
    assert snapshot["data_mode"] == "synthetic_test_fixture"
    payload = {key: value for key, value in snapshot.items() if key != "sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert result["data_hash"] == snapshot["sha256"] == hashlib.sha256(encoded).hexdigest()


def test_snapshot_null_and_precision_survive_json_readback(frame_factory):
    frame = frame_factory([10, 10, 10, 11, 12, 11, 10, 9, 8])
    frame.loc[2, "amount"] = float("nan")
    frame.loc[3, "turnover_rate"] = 0.123456789012345
    result = _result(frame)
    restored = json.loads(json.dumps(result, allow_nan=False))
    rows = restored["input_snapshot"]["rows"]
    assert rows[0]["amount"] is None
    assert rows[1]["turnover_rate"] == 0.123456789012345
    replay = pd.DataFrame(rows)
    replay.attrs["data_mode"] = restored["input_snapshot"]["data_mode"]
    assert _result(replay) == result


def test_column_order_and_unused_history_do_not_change_snapshot(frame_factory):
    frame = frame_factory([10, 10, 10, 11, 12, 11, 10, 9, 8])
    result = _result(frame)
    altered = frame.loc[:, list(reversed(frame.columns))].copy()
    # Both rows are outside the selected warmup/window. Keep OHLC legal.
    for index in (0, 8):
        for column in ("open", "high", "low", "close"):
            altered.loc[index, column] *= 2
    assert _result(altered) == result


def test_input_changes_are_detectable_even_if_trades_are_unchanged(frame_factory):
    frame = frame_factory([10] * 9)
    before = _result(frame)
    frame.loc[5, "volume"] += 1
    after = _result(frame)
    assert before["trades"] == after["trades"] == []
    assert before["equity_curve"] == after["equity_curve"]
    assert before["data_hash"] != after["data_hash"]


def test_request_validation_rejects_bad_values_before_touching_data():
    with pytest.raises(BacktestParameterError):
        run_backtest_request(object(), parameters={"initial_cash": True})
    with pytest.raises(BacktestParameterError):
        run_backtest_request(object(), start_date="2024-02-30", end_date="2024-03-01", parameters={})
    assert validate_backtest_window("2024-02-29", date(2029, 2, 28)) == (
        date(2024, 2, 29), date(2029, 2, 28)
    )
    with pytest.raises(BacktestParameterError):
        validate_backtest_window("2024-02-29", "2029-03-01")


def test_non_string_provenance_is_rejected_instead_of_dumping_arbitrary_attrs(frame_factory):
    frame = frame_factory([10] * 9)
    frame.attrs["data_mode"] = {"unexpected": "object"}
    with pytest.raises(BacktestParameterError, match="data_mode"):
        _result(frame)
