"""Strict, request-local parameters for the V2 single-stock MA backtest.

This module is independent of HTTP schemas. Call the resolver before fetching
market data and preserve whether the caller omitted ``parameters`` entirely.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import isfinite
from typing import Any, Dict

from backend.app.quant.config import QuantConfig
from backend.app.quant.validators import QuantValidationError


PARAMETERS_UNSET = object()


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
class BacktestRequestConfig:
    """Resolved parameter values and the distinct legacy/windowed semantics."""

    semantics_version: str
    parameters: BacktestParameters

    def __post_init__(self) -> None:
        if type(self.semantics_version) is not str or self.semantics_version not in (
            "v1_legacy",
            "v2_windowed",
        ):
            raise BacktestParameterError(
                "semantics_version must be v1_legacy or v2_windowed"
            )
        if type(self.parameters) is not BacktestParameters:
            raise BacktestParameterError("parameters must be BacktestParameters")
        if self.semantics_version == "v1_legacy" and self.parameters != BacktestParameters():
            raise BacktestParameterError("v1_legacy requires default backtest parameters")

    @property
    def required_warmup_rows(self) -> int:
        """Required valid trading rows strictly before the requested window."""

        if self.semantics_version == "v1_legacy":
            return 0
        return self.parameters.ma_long_period


def resolve_backtest_request(parameters: Any = PARAMETERS_UNSET) -> BacktestRequestConfig:
    """Distinguish omitted, empty and custom parameter objects before I/O.

    Omission retains V1 behavior. Explicit mappings, including an empty mapping,
    select V2 window semantics. Explicit null and non-whitelisted fields fail.
    """

    if parameters is PARAMETERS_UNSET:
        return BacktestRequestConfig("v1_legacy", BacktestParameters())
    if not isinstance(parameters, Mapping):
        raise BacktestParameterError("parameters must be an object; null is not allowed")

    supplied = dict(parameters)
    if any(type(key) is not str for key in supplied):
        raise BacktestParameterError("parameter names must be strings")
    known_fields = set(BacktestParameters().to_parameters())
    unknown = sorted(set(supplied) - known_fields)
    if unknown:
        raise BacktestParameterError(f"unknown backtest parameters: {unknown}")

    return BacktestRequestConfig("v2_windowed", BacktestParameters(**supplied))
