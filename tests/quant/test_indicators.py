import numpy as np
import pandas as pd
import pytest

from backend.app.quant.indicators import calculate_indicators
from backend.app.quant.strategy import generate_ma_target_signals


def test_ma5_known_value(frame_factory):
    result = calculate_indicators(frame_factory(range(1, 81)))
    assert result.loc[4, "ma5"] == pytest.approx(3.0)


def test_ma60_preserves_59_row_warmup(frame_factory):
    result = calculate_indicators(frame_factory(range(1, 81)))
    assert result.loc[:58, "ma60"].isna().all()
    assert result.loc[59, "ma60"] == pytest.approx(30.5)


def test_macd_fields_are_finite(synthetic_daily_data):
    result = calculate_indicators(synthetic_daily_data)
    for column in ("macd", "macd_signal", "macd_hist"):
        assert np.isfinite(result[column].dropna()).all()


def test_rsi_stays_in_zero_to_one_hundred(synthetic_daily_data):
    rsi = calculate_indicators(synthetic_daily_data)["rsi14"].dropna()
    assert rsi.between(0, 100, inclusive="both").all()


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        (range(1, 81), 100.0),
        (range(80, 0, -1), 0.0),
        ([50.0] * 80, 50.0),
    ],
)
def test_rsi_boundary_cases(frame_factory, closes, expected):
    result = calculate_indicators(frame_factory(closes))
    assert result["rsi14"].dropna().iloc[-1] == pytest.approx(expected)


def test_bollinger_band_order(synthetic_daily_data):
    result = calculate_indicators(synthetic_daily_data).dropna(
        subset=["boll_upper", "boll_middle", "boll_lower"]
    )
    assert (result["boll_upper"] >= result["boll_middle"]).all()
    assert (result["boll_middle"] >= result["boll_lower"]).all()


def test_indicator_calculation_does_not_mutate_caller(synthetic_daily_data):
    original = synthetic_daily_data.copy(deep=True)
    calculate_indicators(synthetic_daily_data)
    pd.testing.assert_frame_equal(synthetic_daily_data, original)


def test_future_prices_do_not_change_past_indicators_or_signals(synthetic_daily_data):
    cutoff = 200
    changed = synthetic_daily_data.copy(deep=True)
    changed.loc[cutoff + 1 :, "close"] *= 1.75
    changed.loc[cutoff + 1 :, "open"] = changed.loc[cutoff + 1 :, "close"]
    changed.loc[cutoff + 1 :, "high"] = changed.loc[cutoff + 1 :, "close"] + 1
    changed.loc[cutoff + 1 :, "low"] = changed.loc[cutoff + 1 :, "close"] - 1
    baseline = generate_ma_target_signals(synthetic_daily_data)
    modified = generate_ma_target_signals(changed)
    columns = ["ma5", "ma20", "macd", "macd_signal", "rsi14", "target_position"]
    pd.testing.assert_frame_equal(
        baseline.loc[:cutoff, columns], modified.loc[:cutoff, columns]
    )
