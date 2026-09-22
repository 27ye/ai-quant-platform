"""Adapter over C's V2 quant entry points (B never re-implements the算法).

C's V2 contract (PR #10 review, 2026-09-15) is:

    from backend.app.quant import (
        PARAMETERS_UNSET, resolve_backtest_request,
        validate_backtest_window, run_backtest_request,
    )
    request_config = resolve_backtest_request(raw_parameters)
    if request_config.semantics_version == "v2_windowed":
        start_date, end_date = validate_backtest_window(start_date, end_date)
        required_warmup_rows = request_config.required_warmup_rows
    result = run_backtest_request(normalized_dataframe, start_date=..., end_date=...,
                                  parameters=raw_parameters)

C selects the warmup and backtest windows itself: B hands over the whole
normalized frame (warmup + window) and must **not** pre-trim it, nor feed that
frame to the old ``run_backtest`` as if it were the V2 result.

C's code was still local-only when this adapter was written, so it is detected at
import time: when present the V2 path uses it; when absent the service **fails
the request explicitly** (``50004 backtest error``) and persists nothing, rather
than running the old core and labelling its output ``v2_windowed``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

WINDOW_OWNER_C = "C.run_backtest_request"
SEMANTICS_V1_LEGACY = "v1_legacy"
SEMANTICS_V2_WINDOWED = "v2_windowed"


@dataclass(frozen=True)
class CWindowedEntry:
    """The callables C exposes plus the exception classes it documents.

    The exception tuples matter as much as the callables: B must translate C's
    *contract* violations into business codes (``40001`` / ``40003``) while
    letting anything else surface as a real ``500``. Blanket-catching everything
    would disguise B's own wiring bugs as user parameter errors, which C
    explicitly asked us not to do.
    """

    parameters_unset: Any
    resolve_backtest_request: Callable[..., Any]
    validate_backtest_window: Callable[[Any, Any], Any]
    run_backtest_request: Callable[..., Any]
    #: C's "your request violates the parameter contract" errors -> ``40001``.
    parameter_errors: Tuple[type, ...] = field(default_factory=tuple)
    #: C's "the requested window cannot be satisfied" errors -> ``40003``.
    data_errors: Tuple[type, ...] = field(default_factory=tuple)
    #: C's ``STRATEGY_UNSET`` sentinel (V3 F5); ``None`` on a tree that predates it.
    strategy_unset: Any = None
    #: True when C's entry points accept ``strategy=`` (V3 F5).
    supports_strategy: bool = False

    def resolve(self, raw_parameters: Any, strategy: Optional[str] = None) -> Any:
        """C's parameter/strategy resolution - always **before** any data is fetched.

        The ``strategy`` keyword is sent only when the caller actually chose one:
        an omitted strategy must stay omitted (C's sentinel default) and never
        become ``None``, because C rejects a literal ``null`` where only *absence*
        means "use the default".
        """
        if strategy is None or not self.supports_strategy:
            return self.resolve_backtest_request(raw_parameters)
        return self.resolve_backtest_request(raw_parameters, strategy=strategy)

    def validate_window(self, start_date, end_date):
        return self.validate_backtest_window(start_date, end_date)

    def run(
        self,
        frame,
        *,
        start_date,
        end_date,
        parameters,
        strategy: Optional[str] = None,
    ) -> Any:
        if strategy is None or not self.supports_strategy:
            return self.run_backtest_request(
                frame, start_date=start_date, end_date=end_date, parameters=parameters
            )
        return self.run_backtest_request(
            frame,
            start_date=start_date,
            end_date=end_date,
            parameters=parameters,
            strategy=strategy,
        )


def _accepts_strategy(func: Callable[..., Any]) -> bool:
    """True when C's callable takes a ``strategy`` keyword (V3 F5)."""
    try:
        return "strategy" in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return False


def load_c_windowed_entry() -> Optional[CWindowedEntry]:
    """Return C's windowed entry points, or ``None`` when C's code is absent."""
    try:
        from backend.app.quant import (  # noqa: PLC0415 - optional dependency
            PARAMETERS_UNSET,
            BacktestParameterError,
            resolve_backtest_request,
            run_backtest_request,
            validate_backtest_window,
        )
    except ImportError:
        return None

    strategy_unset = None
    try:  # V3 sentinel; absent until C's MACD contract lands in this tree.
        from backend.app.quant import STRATEGY_UNSET  # noqa: PLC0415
    except ImportError:
        pass
    else:
        strategy_unset = STRATEGY_UNSET

    parameter_errors: Tuple[type, ...] = (BacktestParameterError,)
    data_errors: Tuple[type, ...] = ()
    try:  # ``InsufficientDataError`` marks an unsatisfiable window/warmup.
        from backend.app.quant.validators import (  # noqa: PLC0415
            InsufficientDataError,
        )
    except ImportError:  # pragma: no cover - only when C ships a different layout
        pass
    else:
        data_errors = (InsufficientDataError,)

    return CWindowedEntry(
        parameters_unset=PARAMETERS_UNSET,
        resolve_backtest_request=resolve_backtest_request,
        validate_backtest_window=validate_backtest_window,
        run_backtest_request=run_backtest_request,
        parameter_errors=parameter_errors,
        data_errors=data_errors,
        strategy_unset=strategy_unset,
        # Both entry points must accept it: passing ``strategy=`` to only one of them
        # would fail on the *second* call, after data had already been fetched.
        supports_strategy=(
            strategy_unset is not None
            and _accepts_strategy(resolve_backtest_request)
            and _accepts_strategy(run_backtest_request)
        ),
    )


def is_c_windowed_available() -> bool:
    return load_c_windowed_entry() is not None
