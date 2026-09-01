"""Deterministic, past-only technical indicators for normalized daily data."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.quant.config import ConfigInput, resolve_config
from backend.app.quant.validators import validate_stock_dataframe


INDICATOR_COLUMNS = (
    "trade_date",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "macd",
    "macd_signal",
    "macd_hist",
    "rsi14",
    "boll_upper",
    "boll_middle",
    "boll_lower",
)


def calculate_indicators(data: pd.DataFrame, config: ConfigInput = None) -> pd.DataFrame:
    """Calculate MA, MACD, Wilder RSI14, and Bollinger Bands on a copy."""

    settings = resolve_config(config)
    result = validate_stock_dataframe(data)
    close = result["close"]

    periods = (
        ("ma5", settings.ma_short_period),
        ("ma10", settings.ma_medium_period),
        ("ma20", settings.ma_long_period),
        ("ma60", settings.ma_trend_period),
    )
    for column, period in periods:
        result[column] = close.rolling(window=period, min_periods=period).mean()

    ema_fast = close.ewm(span=settings.macd_fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=settings.macd_slow_period, adjust=False).mean()
    result["macd"] = ema_fast - ema_slow
    result["macd_signal"] = result["macd"].ewm(
        span=settings.macd_signal_period, adjust=False
    ).mean()
    result["macd_hist"] = settings.macd_hist_multiplier * (
        result["macd"] - result["macd_signal"]
    )

    result["rsi14"] = _calculate_wilder_rsi(close, settings.rsi_period)

    boll_middle = close.rolling(
        window=settings.boll_period, min_periods=settings.boll_period
    ).mean()
    boll_std = close.rolling(
        window=settings.boll_period, min_periods=settings.boll_period
    ).std(ddof=settings.boll_std_ddof)
    result["boll_middle"] = boll_middle
    result["boll_upper"] = boll_middle + settings.boll_std_multiplier * boll_std
    result["boll_lower"] = boll_middle - settings.boll_std_multiplier * boll_std
    return result


def _calculate_wilder_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean()
    average_loss = losses.ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean()

    relative_strength = average_gain / average_loss
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    only_gains = (average_gain > 0) & (average_loss == 0)
    only_losses = (average_gain == 0) & (average_loss > 0)
    no_changes = (average_gain == 0) & (average_loss == 0)
    rsi = rsi.mask(only_gains, 100.0)
    rsi = rsi.mask(only_losses, 0.0)
    rsi = rsi.mask(no_changes, 50.0)
    return rsi.clip(lower=0.0, upper=100.0).replace([np.inf, -np.inf], np.nan)
