"""Deterministic quantitative calculation module."""

from backend.app.quant.backtest import run_backtest
from backend.app.quant.backtest_config import (
    PARAMETERS_UNSET,
    BacktestParameterError,
    BacktestParameters,
    resolve_backtest_request,
)
from backend.app.quant.config import QuantConfig
from backend.app.quant.indicators import calculate_indicators
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.quant.scoring import calculate_quant_score
from backend.app.quant.windowed_backtest import run_backtest_request, validate_backtest_window

__all__ = [
    "QuantConfig",
    "PARAMETERS_UNSET",
    "BacktestParameterError",
    "BacktestParameters",
    "analyze_quant_dataframe",
    "calculate_indicators",
    "calculate_quant_score",
    "run_backtest",
    "resolve_backtest_request",
    "run_backtest_request",
    "validate_backtest_window",
]
