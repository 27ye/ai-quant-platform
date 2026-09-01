"""Performance and risk metrics shared by scoring and backtesting."""

from __future__ import annotations

import math
from typing import Iterable, Optional

import numpy as np
import pandas as pd


def calculate_max_drawdown(values: Iterable[float]) -> float:
    """Return the minimum drawdown as a non-positive decimal."""

    series = pd.Series(values, dtype=float).dropna()
    if series.empty:
        raise ValueError("max drawdown requires at least one finite value")
    if not np.isfinite(series.to_numpy()).all() or (series <= 0).any():
        raise ValueError("max drawdown values must be finite and positive")
    drawdown = series / series.cummax() - 1.0
    return float(drawdown.min())


def calculate_sharpe_ratio(
    daily_returns: Iterable[float],
    annualization_days: int = 252,
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """Calculate sample-standard-deviation annualized Sharpe, or None."""

    returns = pd.Series(daily_returns, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 2:
        return None
    daily_risk_free = risk_free_rate / annualization_days
    excess = returns - daily_risk_free
    standard_deviation = float(excess.std(ddof=1))
    if not math.isfinite(standard_deviation) or math.isclose(
        standard_deviation, 0.0, rel_tol=0.0, abs_tol=1e-15
    ):
        return None
    sharpe = float(excess.mean()) / standard_deviation * math.sqrt(annualization_days)
    return sharpe if math.isfinite(sharpe) else None
