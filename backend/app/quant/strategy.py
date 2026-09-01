"""Transparent MA5/MA20 long-only target-position strategy."""

from __future__ import annotations

import pandas as pd

from backend.app.quant.config import ConfigInput, resolve_config
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
