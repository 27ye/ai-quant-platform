"""Validation for normalized stock daily-kline DataFrames."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = (
    "stock_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
OPTIONAL_NUMERIC_COLUMNS = ("amount", "turnover_rate", "change_pct")
REQUIRED_NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


class QuantValidationError(ValueError):
    """Base exception for deterministic quant input validation."""


class MissingColumnsError(QuantValidationError):
    """Raised when a normalized input field is missing."""


class InsufficientDataError(QuantValidationError):
    """Raised when an operation has too few daily rows."""


def validate_stock_dataframe(data: pd.DataFrame, min_rows: int = 1) -> pd.DataFrame:
    """Return a validated deep copy without mutating the caller's DataFrame."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas.DataFrame")
    if data.empty:
        raise InsufficientDataError("stock daily data is empty")

    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise MissingColumnsError(f"stock daily data missing required columns: {missing}")

    validated = data.copy(deep=True)
    validated.attrs = dict(data.attrs)
    if len(validated) < min_rows:
        raise InsufficientDataError(
            f"stock daily data requires at least {min_rows} rows; received {len(validated)}"
        )

    _validate_stock_codes(validated)
    _validate_trade_dates(validated)
    _convert_numeric_columns(validated)
    _validate_price_volume_rules(validated)
    return validated.reset_index(drop=True)


def _validate_stock_codes(data: pd.DataFrame) -> None:
    values = data["stock_code"]
    invalid_type = ~values.map(lambda value: isinstance(value, str))
    if invalid_type.any():
        raise QuantValidationError("stock_code must be a 6-digit string on every row")
    normalized = values.str.strip()
    if (~normalized.str.fullmatch(r"\d{6}")).any():
        raise QuantValidationError("stock_code must be a 6-digit string on every row")
    if normalized.nunique(dropna=False) != 1:
        raise QuantValidationError("quant analysis requires exactly one stock_code")
    data["stock_code"] = normalized


def _validate_trade_dates(data: pd.DataFrame) -> None:
    parsed = pd.to_datetime(data["trade_date"], errors="coerce")
    if parsed.isna().any():
        raise QuantValidationError("trade_date contains unparseable values")
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_localize(None)
    parsed = parsed.dt.normalize()
    if parsed.duplicated().any():
        raise QuantValidationError("trade_date contains duplicate dates")
    if not parsed.is_monotonic_increasing:
        raise QuantValidationError("trade_date must be strictly increasing")
    differences = parsed.diff().dropna()
    if (differences <= pd.Timedelta(0)).any():
        raise QuantValidationError("trade_date must be strictly increasing")
    data["trade_date"] = parsed


def _convert_numeric_columns(data: pd.DataFrame) -> None:
    for column in REQUIRED_NUMERIC_COLUMNS:
        converted = pd.to_numeric(data[column], errors="coerce")
        if converted.isna().any() or not np.isfinite(converted.to_numpy(dtype=float)).all():
            raise QuantValidationError(f"{column} must contain finite numeric values")
        data[column] = converted.astype(float)

    for column in _present_columns(data, OPTIONAL_NUMERIC_COLUMNS):
        original = data[column]
        converted = pd.to_numeric(original, errors="coerce")
        invalid = original.notna() & converted.isna()
        finite_values = converted.dropna().to_numpy(dtype=float)
        if invalid.any() or not np.isfinite(finite_values).all():
            raise QuantValidationError(f"{column} must contain finite numeric values or null")
        data[column] = converted.astype(float)


def _validate_price_volume_rules(data: pd.DataFrame) -> None:
    for column in ("open", "high", "low", "close"):
        if (data[column] <= 0).any():
            raise QuantValidationError(f"{column} must be greater than zero")
    if (data["volume"] < 0).any():
        raise QuantValidationError("volume must be greater than or equal to zero")
    if ((data["high"] < data["open"]) | (data["high"] < data["close"])).any():
        raise QuantValidationError("high must be greater than or equal to open and close")
    if ((data["low"] > data["open"]) | (data["low"] > data["close"])).any():
        raise QuantValidationError("low must be less than or equal to open and close")
    if (data["high"] < data["low"]).any():
        raise QuantValidationError("high must be greater than or equal to low")


def _present_columns(data: pd.DataFrame, columns: Iterable[str]) -> Iterable[str]:
    return (column for column in columns if column in data.columns)
