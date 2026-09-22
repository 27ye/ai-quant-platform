"""Evidence verification must detect tampering and avoid overwriting artifacts."""
from copy import deepcopy

import pytest

from scripts import validate_v3_macd as evidence
from backend.app.quant import run_backtest_request


def example(frame_factory):
    frame = frame_factory([10] * 40)
    return run_backtest_request(frame, strategy="macd",
        start_date=frame.iloc[34].trade_date.strftime("%Y-%m-%d"),
        end_date=frame.iloc[-1].trade_date.strftime("%Y-%m-%d"))


def test_replay_detects_result_and_input_changes(frame_factory):
    result = example(frame_factory)
    evidence.replay(result)
    changed = deepcopy(result)
    changed["equity_curve"][-1]["equity"] += 0.001
    with pytest.raises(ValueError, match="full replay"):
        evidence.replay(changed)
    changed = deepcopy(result)
    changed["input_snapshot"]["rows"][0]["volume"] += 1
    with pytest.raises(ValueError, match="input hash"):
        evidence.replay(changed)


def test_existing_output_is_never_overwritten(tmp_path):
    marker = tmp_path / "manifest.json"
    marker.write_text("previous evidence", encoding="utf-8")
    assert evidence.main(["--output-dir", str(tmp_path)]) == 1
    assert marker.read_text(encoding="utf-8") == "previous evidence"


def test_missing_or_failed_evidence_is_not_accepted(tmp_path):
    assert evidence.main(["--verify", str(tmp_path)]) == 1
    evidence.write_json(tmp_path / "manifest.json", {"status": "running"})
    assert evidence.main(["--verify", str(tmp_path)]) == 1


def test_numeric_fixture_retains_null_and_real_zero(frame_factory):
    result = example(frame_factory)
    exported = evidence.numeric_example(result)
    values = exported["values_from_same_result"]
    assert values["sharpe_ratio"] is None and values["win_rate"] is None
    assert values["order_count"] == values["trade_count"] == 0
    assert values["total_return"] == 0
    assert exported["quant_score"] is None
    assert exported["curve_summary"]["normalized_last_return"] == result["total_return"]
    assert exported["curve_summary"]["minimum_drawdown"] == result["max_drawdown"]
