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

C's code was still local-only when this adapter was written, so it is detected
at import time: when present the V2 path uses it, and when absent the service
keeps the previous behaviour and *says so* in ``data_meta.window_owner``
instead of pretending the window semantics are already C's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

WINDOW_OWNER_C = "C.run_backtest_request"
WINDOW_OWNER_LEGACY_PENDING = (
    "legacy run_backtest (pending C.run_backtest_request: C V2 code not pushed yet)"
)
SEMANTICS_V1_LEGACY = "v1_legacy"
SEMANTICS_V2_WINDOWED = "v2_windowed"


@dataclass(frozen=True)
class CWindowedEntry:
    """The four callables C exposes for the windowed request semantics."""

    parameters_unset: Any
    resolve_backtest_request: Callable[[Any], Any]
    validate_backtest_window: Callable[[Any, Any], Any]
    run_backtest_request: Callable[..., Any]

    def resolve(self, raw_parameters: Any) -> Any:
        return self.resolve_backtest_request(raw_parameters)

    def validate_window(self, start_date, end_date):
        return self.validate_backtest_window(start_date, end_date)

    def run(self, frame, *, start_date, end_date, parameters) -> Any:
        return self.run_backtest_request(
            frame, start_date=start_date, end_date=end_date, parameters=parameters
        )


def load_c_windowed_entry() -> Optional[CWindowedEntry]:
    """Return C's windowed entry points, or ``None`` when C's code is absent."""
    try:
        from backend.app.quant import (  # noqa: PLC0415 - optional dependency
            PARAMETERS_UNSET,
            resolve_backtest_request,
            run_backtest_request,
            validate_backtest_window,
        )
    except ImportError:
        return None
    return CWindowedEntry(
        parameters_unset=PARAMETERS_UNSET,
        resolve_backtest_request=resolve_backtest_request,
        validate_backtest_window=validate_backtest_window,
        run_backtest_request=run_backtest_request,
    )


def is_c_windowed_available() -> bool:
    return load_c_windowed_entry() is not None
