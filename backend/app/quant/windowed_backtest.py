"""Versioned C-only backtest entry point, independent of HTTP and persistence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import date
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from backend.app.quant.backtest import _run_ma_backtest, run_backtest
from backend.app.quant.backtest_config import (
    PARAMETERS_UNSET,
    BacktestParameterError,
    resolve_backtest_request,
)
from backend.app.quant.serialization import dataframe_records, to_json_safe
from backend.app.quant.strategy import generate_ma_target_signals
from backend.app.quant.validators import (
    OPTIONAL_NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
    InsufficientDataError,
    validate_stock_dataframe,
)


ALGORITHM_VERSIONS = {
    "v1_legacy": "ma_long_only_v1",
    "v2_windowed": "ma_long_only_v2.0.0",
}
INPUT_SNAPSHOT_VERSION = "quant_input_v1"
WINDOWED_BENCHMARK = "first_open_to_last_close_no_cost"


def run_backtest_request(
    data: pd.DataFrame,
    *,
    start_date: Any = None,
    end_date: Any = None,
    parameters: Any = PARAMETERS_UNSET,
) -> Dict[str, Any]:
    """Run legacy or windowed semantics without changing the existing V1 API.

    B resolves dates and obtains complete, normalized daily data before calling
    this function. In legacy mode the supplied frame is used unchanged, including
    any historical expansion performed by the V1 service. Explicit parameters
    require an inclusive date window and long-MA valid observations before it.
    The previous observation's close signal may execute at the first window open.
    """

    request = resolve_backtest_request(parameters)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise BacktestParameterError("start_date must not exceed end_date")
    windowed = request.semantics_version == "v2_windowed"
    if windowed:
        start, end = validate_backtest_window(start, end)

    validated = validate_stock_dataframe(data)
    settings = request.parameters.to_quant_config()
    warmup = None
    if windowed:
        prior = validated.loc[validated["trade_date"].dt.date < start]
        window = validated.loc[
            (validated["trade_date"].dt.date >= start)
            & (validated["trade_date"].dt.date <= end)
        ]
        if window.empty:
            raise InsufficientDataError("no valid daily rows inside the requested window")
        required = request.required_warmup_rows
        if len(prior) < required:
            raise InsufficientDataError(
                f"window requires {required} valid warmup rows before start_date; "
                f"received {len(prior)}"
            )
        prior = prior.tail(required)
        calculation_data = pd.concat([prior, window], ignore_index=True)
        calculation_data.attrs = dict(validated.attrs)
        warmup = {
            "start_date": prior.iloc[0]["trade_date"].strftime("%Y-%m-%d"),
            "end_date": prior.iloc[-1]["trade_date"].strftime("%Y-%m-%d"),
            "required_rows": required,
            "used_rows": len(prior),
        }
        settings = replace(
            settings,
            strategy_name="ma_long_only",
            benchmark_method=WINDOWED_BENCHMARK,
        )
        signals = generate_ma_target_signals(calculation_data, settings)
        result = _run_ma_backtest(
            signals, settings, first_trading_index=len(prior), windowed=True
        )
    else:
        calculation_data = validated
        result = run_backtest(calculation_data)

    # Keep all legacy result fields intact. Additional fields describe this call
    # and give B an input/result snapshot to store without recomputation on GET.
    snapshot = _input_snapshot(calculation_data)
    result.update(
        stock_code=snapshot["stock_code"],
        semantics_version=request.semantics_version,
        algorithm_version=ALGORITHM_VERSIONS[request.semantics_version],
        requested_start_date=None if start is None else start.isoformat(),
        requested_end_date=None if end is None else end.isoformat(),
        effective_parameters=settings.to_parameters(),
        warmup=warmup,
        initial_equity={
            "trade_date": result["start_date"],
            "equity": float(settings.initial_cash),
            "valuation": "before_open" if windowed else "first_close",
        },
        execution_assumptions={
            "model": "research_fractional_v1",
            "signal": "previous_observation_close",
            "execution": "next_observation_open",
            "first_day_signal": "last_warmup_close" if windowed else "none",
            "transaction_cost": "proportional_on_each_buy_and_sell",
            "slippage": "buy_price_increased_sell_price_decreased",
            "fractional_shares": True,
            "forced_final_sale": False,
            "benchmark_includes_costs": False,
            "exchange_execution_constraints": "not_modelled",
            "price_basis": "qfq",
        },
        input_snapshot=snapshot,
        data_hash=snapshot["sha256"],
    )
    # Do not silently turn an overflowing financial result into a successful null.
    json.dumps(result, ensure_ascii=False, allow_nan=False)
    return result


def validate_backtest_window(start_date: Any, end_date: Any) -> Tuple[date, date]:
    """Validate a resolved V2 window before B performs any market-data I/O."""

    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if start is None or end is None:
        raise BacktestParameterError("v2_windowed requires resolved start_date and end_date")
    if start > end:
        raise BacktestParameterError("start_date must not exceed end_date")
    _validate_window_length(start, end)
    return start, end


def _parse_date(value: Any, field: str) -> Optional[date]:
    if value is None:
        return None
    if type(value) is date:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise BacktestParameterError(f"{field} must be a date or YYYY-MM-DD string")


def _validate_window_length(start: date, end: date) -> None:
    if end.year - start.year < 5:
        return
    # Leap-day anniversary is February 28 in a non-leap target year.
    try:
        last_allowed = start.replace(year=start.year + 5)
    except ValueError:
        last_allowed = start.replace(year=start.year + 5, day=28)
    if end > last_allowed:
        raise BacktestParameterError("v2_windowed supports at most five calendar years")


def _input_snapshot(data: pd.DataFrame) -> Dict[str, Any]:
    columns = list(REQUIRED_COLUMNS) + [
        column for column in OPTIONAL_NUMERIC_COLUMNS if column in data.columns
    ]
    data_mode = data.attrs.get("data_mode", "dataframe")
    if not isinstance(data_mode, str):
        raise BacktestParameterError("data_mode must be a string when supplied")
    content = {
        "schema_version": INPUT_SNAPSHOT_VERSION,
        "stock_code": str(data.iloc[0]["stock_code"]),
        "frequency": "daily",
        "adjust": "qfq",
        "data_mode": data_mode,
        "columns": columns,
        "rows": dataframe_records(data.loc[:, columns]),
    }
    # The validator converts numeric input to float; optional missing cells become
    # null. No rounding is introduced. B must retain this exact JSON numeric value.
    canonical = json.dumps(
        to_json_safe(content), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    return {**content, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
