"""Strict, request-local parameters for single-stock MA and MACD backtests.

This module is independent of HTTP schemas. Call the resolver before fetching
market data and preserve whether the caller omitted ``parameters`` entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any, Dict, Union

from backend.app.quant.config import QuantConfig
from backend.app.quant.validators import QuantValidationError


PARAMETERS_UNSET = object()
STRATEGY_UNSET = object()


class BacktestParameterError(QuantValidationError):
    """A backtest request violates the parameter contract (business 40001)."""


def _finite_number(name: str, value: Any) -> float:
    # Do not coerce strings, booleans, Decimal or numpy scalars into JSON numbers.
    if type(value) not in (int, float):
        raise BacktestParameterError(f"{name} must be an int or float, not bool")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise BacktestParameterError(f"{name} must be finite") from None
    if not isfinite(number):
        raise BacktestParameterError(f"{name} must be finite")
    return number


@dataclass(frozen=True)
class BacktestParameters:
    """The only five user-configurable fields; other quant settings stay fixed."""

    ma_short_period: int = 5
    ma_long_period: int = 20
    initial_cash: float = 100000.0
    transaction_cost: float = 0.001
    slippage: float = 0.0

    def __post_init__(self) -> None:
        for name in ("ma_short_period", "ma_long_period"):
            if type(getattr(self, name)) is not int:
                raise BacktestParameterError(f"{name} must be an integer, not bool")
        if not 2 <= self.ma_short_period < self.ma_long_period <= 120:
            raise BacktestParameterError(
                "MA periods must satisfy 2 <= ma_short_period < ma_long_period <= 120"
            )

        for name in ("initial_cash", "transaction_cost", "slippage"):
            number = _finite_number(name, getattr(self, name))
            if name == "initial_cash":
                if number <= 0:
                    raise BacktestParameterError("initial_cash must be greater than zero")
            elif not 0 <= number < 1:
                raise BacktestParameterError(f"{name} must be in [0, 1)")
            object.__setattr__(self, name, number)

    def to_parameters(self) -> Dict[str, Any]:
        """Return a fresh, JSON-ready mapping of the five accepted parameters."""

        return asdict(self)

    def to_quant_config(self) -> QuantConfig:
        """Make an isolated config without changing default scoring settings."""

        return replace(QuantConfig(), **self.to_parameters())


@dataclass(frozen=True)
class MacdBacktestParameters:
    """MACD's six-field whitelist; no changes to the default scoring config."""

    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    initial_cash: float = 100000.0
    transaction_cost: float = 0.001
    slippage: float = 0.0

    def __post_init__(self) -> None:
        for name in ("macd_fast_period", "macd_slow_period", "macd_signal_period"):
            if type(getattr(self, name)) is not int:
                raise BacktestParameterError(f"{name} must be an integer, not bool")
        if not 2 <= self.macd_fast_period < self.macd_slow_period <= 120:
            raise BacktestParameterError(
                "MACD periods must satisfy 2 <= macd_fast_period < macd_slow_period <= 120"
            )
        if not 2 <= self.macd_signal_period <= 120:
            raise BacktestParameterError("macd_signal_period must satisfy 2 <= period <= 120")
        # Share the exact financial validation with MA without accepting MA fields.
        financial = BacktestParameters(
            initial_cash=self.initial_cash,
            transaction_cost=self.transaction_cost,
            slippage=self.slippage,
        )
        for name in ("initial_cash", "transaction_cost", "slippage"):
            object.__setattr__(self, name, getattr(financial, name))

    def to_parameters(self) -> Dict[str, Any]:
        return asdict(self)

    def to_quant_config(self) -> QuantConfig:
        return replace(QuantConfig(), **self.to_parameters())


@dataclass(frozen=True)
class BacktestRequestConfig:
    """Resolved parameter values and the distinct legacy/windowed semantics."""

    semantics_version: str
    parameters: Union[BacktestParameters, MacdBacktestParameters]
    strategy: str = "ma_cross"

    def __post_init__(self) -> None:
        if type(self.semantics_version) is not str or self.semantics_version not in (
            "v1_legacy",
            "v2_windowed",
        ):
            raise BacktestParameterError(
                "semantics_version must be v1_legacy or v2_windowed"
            )
        if type(self.strategy) is not str or self.strategy not in ("ma_cross", "macd"):
            raise BacktestParameterError("strategy must be ma_cross or macd")
        expected = MacdBacktestParameters if self.strategy == "macd" else BacktestParameters
        if type(self.parameters) is not expected:
            raise BacktestParameterError(f"parameters must be {expected.__name__}")
        if self.strategy == "macd" and self.semantics_version != "v2_windowed":
            raise BacktestParameterError("macd requires v2_windowed semantics")
        if self.semantics_version == "v1_legacy" and self.parameters != BacktestParameters():
            raise BacktestParameterError("v1_legacy requires default backtest parameters")

    @property
    def required_warmup_rows(self) -> int:
        """Required valid trading rows strictly before the requested window."""

        if self.semantics_version == "v1_legacy":
            return 0
        if self.strategy == "macd":
            return self.parameters.macd_slow_period + self.parameters.macd_signal_period - 1
        return self.parameters.ma_long_period


def resolve_backtest_request(
    parameters: Any = PARAMETERS_UNSET, *, strategy: Any = STRATEGY_UNSET
) -> BacktestRequestConfig:
    """Distinguish omitted, empty and custom parameter objects before I/O.

    Omission retains V1 behavior. Explicit mappings, including an empty mapping,
    select V2 window semantics. Explicit null and non-whitelisted fields fail.
    """

    if strategy is STRATEGY_UNSET:
        strategy = "ma_cross"
    if type(strategy) is not str or strategy not in ("ma_cross", "macd"):
        raise BacktestParameterError("strategy must be ma_cross or macd; null is not allowed")
    if parameters is PARAMETERS_UNSET:
        if strategy == "ma_cross":
            return BacktestRequestConfig("v1_legacy", BacktestParameters())
        parameters = {}
    if not isinstance(parameters, Mapping):
        raise BacktestParameterError("parameters must be an object; null is not allowed")

    supplied = dict(parameters)
    if any(type(key) is not str for key in supplied):
        raise BacktestParameterError("parameter names must be strings")
    parameter_type = MacdBacktestParameters if strategy == "macd" else BacktestParameters
    known_fields = set(parameter_type().to_parameters())
    unknown = sorted(set(supplied) - known_fields)
    if unknown:
        raise BacktestParameterError(f"unknown backtest parameters: {unknown}")

    return BacktestRequestConfig("v2_windowed", parameter_type(**supplied), strategy)
