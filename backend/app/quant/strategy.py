"""Transparent MA5/MA20 long-only target-position strategy."""

from __future__ import annotations

import pandas as pd

from backend.app.quant.config import ConfigInput, resolve_config
from backend.app.quant.backtest_config import MacdBacktestParameters, BacktestRequestConfig
from backend.app.quant.indicators import calculate_indicators
from backend.app.quant.validators import InsufficientDataError


def generate_ma_target_signals(
    data: pd.DataFrame, config: ConfigInput = None
) -> pd.DataFrame:
    """Return close-known target positions; execution is deferred to T+1."""

    settings = resolve_config(config)
    if len(data) < settings.ma_long_period:
        raise InsufficientDataError(
            f"MA strategy requires at least {settings.ma_long_period} rows; received {len(data)}"
        )
    result = calculate_indicators(data, settings)
    valid = result["ma5"].notna() & result["ma20"].notna()
    result["target_position"] = (
        valid & (result["ma5"] > result["ma20"])
    ).astype(int)
    return result


def generate_macd_target_signals(
    data: pd.DataFrame, parameters: MacdBacktestParameters
) -> pd.DataFrame:
    """Fixed-seed, close-known DIF > DEA target; the execution engine handles T+1."""

    request = BacktestRequestConfig("v2_windowed", parameters, "macd")
    required = request.required_warmup_rows
    if len(data) < required:
        raise InsufficientDataError(
            f"MACD strategy requires at least {required} rows; received {len(data)}"
        )
    result = calculate_indicators(data, parameters.to_quant_config())
    eligible = pd.Series(range(len(result)), index=result.index) >= required - 1
    result["target_position"] = (
        eligible & (result["macd"] > result["macd_signal"])
    ).astype(int)
    return result
