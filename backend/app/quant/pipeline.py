"""Unified deterministic quant-core entry point for a normalized DataFrame."""

from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from backend.app.quant.backtest import run_backtest
from backend.app.quant.config import ConfigInput, resolve_config
from backend.app.quant.indicators import INDICATOR_COLUMNS, calculate_indicators
from backend.app.quant.scoring import calculate_quant_score
from backend.app.quant.serialization import dataframe_records, to_json_safe
from backend.app.quant.validators import validate_stock_dataframe


def analyze_quant_dataframe(
    data: pd.DataFrame, config: ConfigInput = None
) -> Dict[str, Any]:
    """Validate, calculate, score, backtest, and return strict JSON-safe output."""

    settings = resolve_config(config)
    minimum_rows = max(settings.ma_trend_period, settings.ma_long_period + 1)
    validated = validate_stock_dataframe(data, min_rows=minimum_rows)
    indicators = calculate_indicators(validated, settings)
    score = calculate_quant_score(validated, settings)
    backtest = run_backtest(validated, settings)
    latest_row = indicators.iloc[-1]
    latest_fields = (
        "trade_date",
        "close",
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
    indicator_series = dataframe_records(indicators.loc[:, INDICATOR_COLUMNS])
    result = {
        "meta": {
            "stock_code": str(validated.iloc[0]["stock_code"]),
            "frequency": settings.frequency,
            "adjust": settings.adjust,
            "contract_status": settings.contract_status,
            "data_mode": data.attrs.get("data_mode", "dataframe"),
            "actual_start_date": validated.iloc[0]["trade_date"],
            "actual_end_date": validated.iloc[-1]["trade_date"],
            "rows": len(validated),
            "parameters": settings.to_parameters(),
        },
        "latest": {field: latest_row[field] for field in latest_fields},
        "score": score,
        "backtest": backtest,
        "series": {
            "indicators": indicator_series,
            "equity_curve": backtest["equity_curve"],
            "benchmark_curve": backtest["benchmark_curve"],
            "drawdown_curve": backtest["drawdown_curve"],
        },
    }
    return to_json_safe(result)
