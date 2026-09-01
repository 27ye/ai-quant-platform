"""Deterministic transparent 40/25/20/15 quantitative scoring."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.app.quant.config import ConfigInput, QuantConfig, resolve_config
from backend.app.quant.indicators import calculate_indicators
from backend.app.quant.metrics import calculate_max_drawdown
from backend.app.quant.validators import InsufficientDataError, validate_stock_dataframe


def calculate_quant_score(
    data: pd.DataFrame, config: ConfigInput = None
) -> Dict[str, Any]:
    """Score the latest daily row using documented provisional rules."""

    settings = resolve_config(config)
    minimum_rows = max(settings.ma_trend_period, settings.volume_ma_period)
    validated = validate_stock_dataframe(data, min_rows=minimum_rows)
    indicators = calculate_indicators(validated, settings)
    latest = indicators.iloc[-1]
    required_latest = ("ma20", "ma60", "macd", "macd_signal", "macd_hist", "rsi14")
    missing_latest = [column for column in required_latest if pd.isna(latest[column])]
    if missing_latest:
        raise InsufficientDataError(
            f"latest score inputs are not warmed up: {missing_latest}"
        )

    trend_score, trend_reasons = _score_trend(latest)
    momentum_score, momentum_reasons = _score_momentum(indicators, settings)
    volume_score, volume_reasons = _score_volume(indicators, settings)
    risk_score, risk_reasons = _score_risk(indicators, settings)
    total_score = trend_score + momentum_score + volume_score + risk_score

    _validate_score_limits(
        total_score, trend_score, momentum_score, volume_score, risk_score, settings
    )
    return {
        "stock_code": str(latest["stock_code"]),
        "score": total_score,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "volume_score": volume_score,
        "risk_score": risk_score,
        "level": _score_level(total_score),
        "reasons": trend_reasons + momentum_reasons + volume_reasons + risk_reasons,
        "contract_status": settings.contract_status,
    }


def _score_trend(latest: pd.Series) -> Tuple[int, List[str]]:
    score = 0
    reasons = []
    rules = (
        (latest["close"] > latest["ma20"], 10, "收盘价高于MA20"),
        (latest["ma5"] > latest["ma20"], 10, "MA5高于MA20"),
        (latest["ma20"] > latest["ma60"], 10, "MA20高于MA60"),
        (latest["macd"] > latest["macd_signal"], 10, "MACD高于信号线"),
    )
    for matched, points, description in rules:
        if bool(matched):
            score += points
            reasons.append(f"趋势 +{points}: {description}")
        else:
            reasons.append(f"趋势 +0: 未满足{description}")
    return score, reasons


def _score_momentum(
    indicators: pd.DataFrame, settings: QuantConfig
) -> Tuple[int, List[str]]:
    latest = indicators.iloc[-1]
    rsi = float(latest["rsi14"])
    reasons = []
    if settings.rsi_strong_lower <= rsi <= settings.rsi_strong_upper:
        rsi_score = 10
    elif (
        settings.rsi_neutral_lower <= rsi < settings.rsi_strong_lower
        or settings.rsi_strong_upper < rsi <= settings.rsi_neutral_upper
    ):
        rsi_score = 5
    else:
        rsi_score = 0
    reasons.append(f"动量 +{rsi_score}: RSI14={rsi:.2f}")

    hist_score = 10 if float(latest["macd_hist"]) > 0 else 0
    reasons.append(
        f"动量 +{hist_score}: MACD柱{'为正' if hist_score else '不为正'}"
    )
    recent_hist = indicators["macd_hist"].dropna().tail(settings.macd_rising_periods)
    rising = len(recent_hist) == settings.macd_rising_periods and bool(
        (recent_hist.diff().dropna() > 0).all()
    )
    rising_score = 5 if rising else 0
    reasons.append(
        f"动量 +{rising_score}: 最近{settings.macd_rising_periods}个有效MACD柱"
        f"{'严格递增' if rising else '未严格递增'}"
    )
    return rsi_score + hist_score + rising_score, reasons


def _score_volume(
    indicators: pd.DataFrame, settings: QuantConfig
) -> Tuple[int, List[str]]:
    latest = indicators.iloc[-1]
    volume_mean = float(indicators["volume"].tail(settings.volume_ma_period).mean())
    volume_ratio: Optional[float]
    if volume_mean > 0:
        volume_ratio = float(latest["volume"]) / volume_mean
    else:
        volume_ratio = None

    change_value = latest.get("change_pct", np.nan)
    if pd.isna(change_value):
        change_value = indicators["close"].pct_change().iloc[-1]
    price_change = float(change_value)
    if not math.isfinite(price_change):
        raise InsufficientDataError("latest price change is unavailable for volume scoring")

    if volume_ratio is not None and price_change > 0 and volume_ratio >= settings.volume_high_ratio:
        score, rule = 20, "上涨且放量"
    elif (
        volume_ratio is not None
        and price_change > 0
        and settings.volume_normal_ratio <= volume_ratio < settings.volume_high_ratio
    ):
        score, rule = 15, "上涨且量能正常"
    elif (
        volume_ratio is not None
        and abs(price_change) <= settings.flat_price_change_threshold
        and settings.volume_normal_ratio <= volume_ratio <= settings.volume_high_ratio
    ):
        score, rule = 10, "价格平稳且量能正常"
    elif volume_ratio is not None and price_change < 0 and volume_ratio >= settings.volume_high_ratio:
        score, rule = 0, "下跌且放量"
    else:
        score, rule = 5, "其他量价组合"
    ratio_text = "不可用(20日均量为0)" if volume_ratio is None else f"{volume_ratio:.4f}"
    reason = (
        f"成交量 +{score}: {rule}; volume_ratio={ratio_text}, "
        f"price_change={price_change:.6f}"
    )
    return score, [reason]


def _score_risk(
    indicators: pd.DataFrame, settings: QuantConfig
) -> Tuple[int, List[str]]:
    returns = indicators["close"].pct_change().dropna().tail(settings.volatility_lookback)
    if len(returns) < 2:
        raise InsufficientDataError("risk scoring requires at least two valid daily returns")
    volatility = float(returns.std(ddof=settings.volatility_std_ddof)) * math.sqrt(
        settings.annualization_days
    )
    if volatility <= settings.low_volatility_threshold:
        volatility_score = 8
    elif volatility <= settings.medium_volatility_threshold:
        volatility_score = 4
    else:
        volatility_score = 0

    recent_prices = indicators["close"].tail(settings.drawdown_lookback)
    max_drawdown = calculate_max_drawdown(recent_prices)
    if max_drawdown >= settings.low_drawdown_threshold:
        drawdown_score = 7
    elif max_drawdown >= settings.medium_drawdown_threshold:
        drawdown_score = 4
    else:
        drawdown_score = 0
    reasons = [
        f"风险 +{volatility_score}: 年化波动率={volatility:.6f}",
        f"风险 +{drawdown_score}: 价格最大回撤={max_drawdown:.6f}",
    ]
    return volatility_score + drawdown_score, reasons


def _score_level(score: int) -> str:
    if score >= 75:
        return "技术面偏强"
    if score >= 50:
        return "技术面中性"
    if score >= 25:
        return "技术面偏弱"
    return "技术面较弱"


def _validate_score_limits(
    total: int,
    trend: int,
    momentum: int,
    volume: int,
    risk: int,
    settings: QuantConfig,
) -> None:
    limits = (
        ("trend_score", trend, settings.trend_max_score),
        ("momentum_score", momentum, settings.momentum_max_score),
        ("volume_score", volume, settings.volume_max_score),
        ("risk_score", risk, settings.risk_max_score),
    )
    for name, value, maximum in limits:
        if not 0 <= value <= maximum:
            raise RuntimeError(f"{name}={value} exceeds [0, {maximum}]")
    if total != trend + momentum + volume + risk or not 0 <= total <= 100:
        raise RuntimeError("quant score components do not sum to a valid 0-100 total")
