"""Request/parameter contracts for ``POST /api/v1/backtests`` (V2 B3).

The whitelist is deliberately small: a V2 request may only override the
financial inputs the plan allows (C1). Everything else stays on C's defaults, so
a request can never smuggle an arbitrary ``QuantConfig`` field through the API.

``extra="forbid"`` + ``allow_inf_nan=False`` mean unknown fields and
NaN/Infinity are rejected by the schema (``40001``) **before** any data fetch.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Shortest/longest MA windows a caller may request (C1 boundary proposal).
MIN_MA_PERIOD = 2
MAX_MA_PERIOD = 120


class BacktestParametersSchema(BaseModel):
    """Optional V2 parameter overrides; omitted fields keep C's defaults.

    ``strict=True`` enforces C's contract exactly: numeric **strings** (``"5"``),
    booleans (``True`` is an ``int`` subclass) and float periods are rejected
    instead of silently coerced - otherwise ``initial_cash=true`` would run a
    1-unit backtest. Plain integers are still accepted for float fields
    (``100000`` -> ``100000.0``).
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    ma_short_period: Optional[int] = Field(
        default=None, ge=MIN_MA_PERIOD, le=MAX_MA_PERIOD
    )
    ma_long_period: Optional[int] = Field(
        default=None, ge=MIN_MA_PERIOD, le=MAX_MA_PERIOD
    )
    initial_cash: Optional[float] = Field(default=None, gt=0)
    transaction_cost: Optional[float] = Field(default=None, ge=0, lt=1)
    slippage: Optional[float] = Field(default=None, ge=0, lt=1)

    @field_validator("ma_short_period", "ma_long_period", mode="before")
    @classmethod
    def _reject_bool_periods(cls, value: Any) -> Any:
        # ``bool`` is an ``int`` subclass; ``true`` must not mean period 1.
        if isinstance(value, bool):
            raise ValueError("period must be an integer, not a boolean")
        return value

    def provided_overrides(self) -> Dict[str, Any]:
        """Only the fields the caller actually sent (``None`` means 'not set')."""
        return {
            key: value
            for key, value in self.model_dump().items()
            if value is not None
        }


class BacktestRequestSchema(BaseModel):
    """``POST /backtests`` body.

    ``parameters`` keeps the *presence* distinction: omitted means
    ``v1_legacy`` semantics, an explicit ``{}``/value means ``v2_windowed``.
    """

    model_config = ConfigDict(extra="forbid")

    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    parameters: Optional[BacktestParametersSchema] = None

    @property
    def parameters_provided(self) -> bool:
        """True when the caller explicitly sent ``parameters`` (even as null)."""
        return "parameters" in self.model_fields_set
