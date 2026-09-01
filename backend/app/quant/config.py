"""Central configuration for the provisional deterministic quant prototype."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Mapping, Optional, Union


@dataclass(frozen=True)
class QuantConfig:
    """Parameters not fixed by the formal V1 contracts remain provisional here."""

    contract_status: str = "provisional"
    frequency: str = "daily"
    adjust: str = "qfq"

    ma_short_period: int = 5
    ma_medium_period: int = 10
    ma_long_period: int = 20
    ma_trend_period: int = 60

    # PROVISIONAL: MACD display convention uses twice the DIF/DEA difference.
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    macd_hist_multiplier: float = 2.0

    # PROVISIONAL: Wilder-style exponential smoothing for RSI14.
    rsi_period: int = 14

    # PROVISIONAL: population standard deviation for 20-day Bollinger Bands.
    boll_period: int = 20
    boll_std_multiplier: float = 2.0
    boll_std_ddof: int = 0

    # The category maxima are fixed by the formal V1 specification.
    trend_max_score: int = 40
    momentum_max_score: int = 25
    volume_max_score: int = 20
    risk_max_score: int = 15

    # PROVISIONAL transparent scoring thresholds.
    rsi_strong_lower: float = 50.0
    rsi_strong_upper: float = 70.0
    rsi_neutral_lower: float = 40.0
    rsi_neutral_upper: float = 80.0
    macd_rising_periods: int = 3
    volume_ma_period: int = 20
    volume_high_ratio: float = 1.2
    volume_normal_ratio: float = 0.8
    flat_price_change_threshold: float = 0.005
    volatility_lookback: int = 60
    volatility_std_ddof: int = 1
    low_volatility_threshold: float = 0.20
    medium_volatility_threshold: float = 0.35
    drawdown_lookback: int = 120
    low_drawdown_threshold: float = -0.10
    medium_drawdown_threshold: float = -0.20

    # PROVISIONAL MA5/MA20 long-only backtest settings.
    strategy_name: str = "ma5_ma20_long_only"
    initial_cash: float = 100000.0
    transaction_cost: float = 0.001
    slippage: float = 0.0
    allow_fractional_shares: bool = True
    risk_free_rate: float = 0.0
    annualization_days: int = 252
    benchmark_method: str = "first_close_to_last_close"

    def to_parameters(self) -> Dict[str, Any]:
        """Return a JSON-ready parameter mapping with explicit provisional status."""

        return asdict(self)


ConfigInput = Optional[Union[QuantConfig, Mapping[str, Any]]]


def resolve_config(config: ConfigInput = None) -> QuantConfig:
    """Resolve a config object or a validated mapping of field overrides."""

    if config is None:
        resolved = QuantConfig()
    elif isinstance(config, QuantConfig):
        resolved = config
    elif isinstance(config, Mapping):
        known_fields = {field.name for field in fields(QuantConfig)}
        unknown_fields = sorted(set(config) - known_fields)
        if unknown_fields:
            raise ValueError(f"unknown quant config fields: {unknown_fields}")
        resolved = QuantConfig(**dict(config))
    else:
        raise TypeError("config must be QuantConfig, a mapping, or None")

    _validate_config(resolved)
    return resolved


def _validate_config(config: QuantConfig) -> None:
    positive_periods = {
        "ma_short_period": config.ma_short_period,
        "ma_medium_period": config.ma_medium_period,
        "ma_long_period": config.ma_long_period,
        "ma_trend_period": config.ma_trend_period,
        "macd_fast_period": config.macd_fast_period,
        "macd_slow_period": config.macd_slow_period,
        "macd_signal_period": config.macd_signal_period,
        "rsi_period": config.rsi_period,
        "boll_period": config.boll_period,
        "volume_ma_period": config.volume_ma_period,
        "volatility_lookback": config.volatility_lookback,
        "drawdown_lookback": config.drawdown_lookback,
        "annualization_days": config.annualization_days,
    }
    invalid_periods = [name for name, value in positive_periods.items() if value <= 0]
    if invalid_periods:
        raise ValueError(f"quant periods must be positive: {invalid_periods}")
    if config.macd_fast_period >= config.macd_slow_period:
        raise ValueError("macd_fast_period must be less than macd_slow_period")
    if config.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if not 0 <= config.transaction_cost < 1:
        raise ValueError("transaction_cost must be in [0, 1)")
    if not 0 <= config.slippage < 1:
        raise ValueError("slippage must be in [0, 1)")
    if config.adjust != "qfq" or config.frequency != "daily":
        raise ValueError("V1 quant core only supports qfq daily data")
