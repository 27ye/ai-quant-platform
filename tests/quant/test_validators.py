import pandas as pd
import pytest

from backend.app.quant.validators import (
    InsufficientDataError,
    MissingColumnsError,
    QuantValidationError,
    validate_stock_dataframe,
)


def test_missing_required_field_is_rejected(synthetic_daily_data):
    with pytest.raises(MissingColumnsError, match="missing required columns"):
        validate_stock_dataframe(synthetic_daily_data.drop(columns=["volume"]))


def test_empty_data_is_rejected():
    with pytest.raises(InsufficientDataError, match="empty"):
        validate_stock_dataframe(pd.DataFrame())


def test_unsorted_dates_are_rejected(synthetic_daily_data):
    unsorted = synthetic_daily_data.iloc[::-1].reset_index(drop=True)
    with pytest.raises(QuantValidationError, match="strictly increasing"):
        validate_stock_dataframe(unsorted)


def test_duplicate_dates_are_rejected(synthetic_daily_data):
    duplicate = synthetic_daily_data.copy()
    duplicate.loc[1, "trade_date"] = duplicate.loc[0, "trade_date"]
    with pytest.raises(QuantValidationError, match="duplicate"):
        validate_stock_dataframe(duplicate)


def test_non_numeric_ohlcv_is_rejected(synthetic_daily_data):
    invalid = synthetic_daily_data.copy()
    invalid["close"] = invalid["close"].astype(object)
    invalid.loc[0, "close"] = "not-a-number"
    with pytest.raises(QuantValidationError, match="close must contain finite"):
        validate_stock_dataframe(invalid)


def test_invalid_ohlc_relationship_is_rejected(synthetic_daily_data):
    invalid = synthetic_daily_data.copy()
    invalid.loc[0, "high"] = invalid.loc[0, "close"] - 2
    with pytest.raises(QuantValidationError, match="high must be"):
        validate_stock_dataframe(invalid)


def test_negative_volume_is_rejected(synthetic_daily_data):
    invalid = synthetic_daily_data.copy()
    invalid.loc[0, "volume"] = -1
    with pytest.raises(QuantValidationError, match="volume"):
        validate_stock_dataframe(invalid)


def test_stock_code_must_be_six_digit_string(synthetic_daily_data):
    invalid = synthetic_daily_data.copy()
    invalid["stock_code"] = 600519
    with pytest.raises(QuantValidationError, match="6-digit string"):
        validate_stock_dataframe(invalid)
