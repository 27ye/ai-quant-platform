"""Read and validate an exact saved MA result without any runtime data service."""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, timezone

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import (
    BacktestInterpretationUnavailableError, BacktestNotFoundError,
    DatabaseOperationError, InvalidParameterError,
)
from backend.app.models.backtest_result import BacktestResult
from backend.app.schemas.ai import (
    BacktestInterpretationContext, BacktestParametersContext,
    SavedBacktestMetricsContext,
)

logger = logging.getLogger(__name__)


class BacktestInterpretationContextProvider:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_context(self, stock_code: str, backtest_id: int) -> BacktestInterpretationContext:
        try:
            record = self._db.get(BacktestResult, backtest_id)
            if record is None:
                raise BacktestNotFoundError()
            if record.stock_code != stock_code:
                raise InvalidParameterError("stock_code does not match saved backtest")
            if record.semantics_version != "v2_windowed" or record.strategy_name != "ma_long_only":
                raise BacktestInterpretationUnavailableError()
            # Legacy JSON was rounded by MySQL, even when v8 backfilled text.
            if record.c_result is not None or not record.c_result_text:
                raise BacktestInterpretationUnavailableError()
            result = json.loads(record.c_result_text)
            self._validate_snapshot(record, result)
            saved_at = record.created_at
            saved_at = saved_at.replace(tzinfo=timezone.utc) if saved_at.tzinfo is None else saved_at.astimezone(timezone.utc)
            meta = record.data_meta or {}
            source_mode = meta.get("source_mode", "unknown")
            provider = meta.get("provider") or "unknown"
            return BacktestInterpretationContext(
                stock_code=stock_code, backtest_id=backtest_id,
                backtest_created_at=saved_at, data_as_of=saved_at,
                strategy_name=result["strategy_name"],
                semantics_version=result["semantics_version"],
                algorithm_version=result["algorithm_version"],
                effective_parameters={name: result["effective_parameters"][name] for name in BacktestParametersContext.model_fields},
                requested_start_date=result["requested_start_date"],
                requested_end_date=result["requested_end_date"],
                start_date=result["start_date"], end_date=result["end_date"],
                warmup=result["warmup"],
                execution_assumptions=result["execution_assumptions"],
                metrics={name: result[name] for name in SavedBacktestMetricsContext.model_fields},
                initial_equity=result["initial_equity"], data_hash=result["data_hash"],
                provenance={
                    "source_mode": source_mode, "provider": provider,
                    "market_start_date": result["start_date"],
                    "market_end_date": result["end_date"],
                    "market_rows": len(result["equity_curve"]),
                },
            )
        except (SQLAlchemyError, ValidationError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self._db.rollback()
            logger.error("saved backtest cannot be interpreted", extra={"backtest_id": backtest_id})
            raise DatabaseOperationError() from exc

    @staticmethod
    def _validate_snapshot(record: BacktestResult, result: dict) -> None:
        if not isinstance(result, dict):
            raise ValueError("invalid exact C result")
        json.dumps(result, allow_nan=False)
        if result["stock_code"] != record.stock_code or result["semantics_version"] != record.semantics_version or result["strategy_name"] != record.strategy_name:
            raise ValueError("saved backtest identity mismatch")
        if result["algorithm_version"] != "ma_long_only_v2.0.0":
            raise BacktestInterpretationUnavailableError("saved algorithm is not supported")
        if not record.equity_curve or not record.input_snapshot:
            raise ValueError("exact result has incomplete persisted snapshots")
        snapshot = result["input_snapshot"]
        content = {key: value for key, value in snapshot.items() if key != "sha256"}
        digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        if snapshot["sha256"] != digest or result["data_hash"] != digest:
            raise ValueError("C input snapshot hash mismatch")
        if snapshot["schema_version"] != "quant_input_v1" or snapshot["stock_code"] != record.stock_code or snapshot["frequency"] != "daily" or snapshot["adjust"] != "qfq":
            raise ValueError("unsupported C input snapshot")
        if set(snapshot) != {"schema_version", "stock_code", "frequency", "adjust", "data_mode", "columns", "rows", "sha256"} or not isinstance(snapshot["data_mode"], str):
            raise ValueError("invalid input snapshot envelope")
        columns = snapshot["columns"]
        required_columns = {"stock_code", "trade_date", "open", "high", "low", "close", "volume"}
        if not isinstance(columns, list) or len(columns) != len(set(columns)) or not required_columns.issubset(columns) or set(columns) - required_columns - {"amount", "turnover_rate", "change_pct"}:
            raise ValueError("invalid input snapshot columns")
        rows = snapshot["rows"]
        if not rows or not isinstance(rows, list):
            raise ValueError("empty C input snapshot")
        dates = []
        for row in rows:
            if set(row) != set(columns) or row["stock_code"] != record.stock_code:
                raise ValueError("invalid C input row")
            dates.append(date.fromisoformat(row["trade_date"]))
            for field in required_columns - {"stock_code", "trade_date"}:
                if type(row[field]) not in (int, float) or row[field] < 0 or (field != "volume" and row[field] == 0):
                    raise ValueError("invalid input price or volume")
            if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
                raise ValueError("invalid OHLC range")
        if dates != sorted(set(dates)):
            raise ValueError("input dates not strictly increasing")
        start = date.fromisoformat(result["start_date"])
        end = date.fromisoformat(result["end_date"])
        if start != record.start_date or end != record.end_date:
            raise ValueError("saved window mismatch")
        window_dates = [item.isoformat() for item in dates if start <= item <= end]
        for curve, value_field in (("equity_curve", "equity"), ("benchmark_curve", "benchmark_equity"), ("drawdown_curve", "drawdown")):
            if [point["trade_date"] for point in result[curve]] != window_dates:
                raise ValueError("incomplete saved curve")
            if any(type(point[value_field]) not in (int, float) for point in result[curve]):
                raise ValueError("non-numeric saved curve")
        if result["equity_curve"][-1]["equity"] != result["final_equity"]:
            raise ValueError("saved final equity mismatch")
        # Saved summary metrics must agree with the curves/orders they summarize.
        # The engine derives them from the same doubles, so a genuine result matches
        # bit-for-bit; the tolerance only guards serializer noise, never corruption.
        # Rel 1e-12 on a metric of magnitude ~1 allows ~1e-12 absolute drift.
        _rel_tol = 1e-12
        expected_return = result["final_equity"] / result["initial_cash"] - 1.0
        if not math.isclose(result["total_return"], expected_return, rel_tol=_rel_tol):
            raise ValueError("saved total return contradicts equity")
        # Windowed metrics anchor at the dropped pre-open initial_cash point (0.0),
        # so the summary is the minimum of that anchor and the stored curve.
        curve_min = min(point["drawdown"] for point in result["drawdown_curve"])
        expected_drawdown = min(0.0, curve_min)
        if not math.isclose(result["max_drawdown"], expected_drawdown, rel_tol=_rel_tol):
            raise ValueError("saved max drawdown contradicts drawdown curve")
        # Each sell completes exactly one round trip in this long-only engine.
        sell_count = sum(1 for trade in result["trades"] if trade["side"] == "sell")
        if result["trade_count"] != sell_count:
            raise ValueError("saved trade count contradicts orders")
        warmup_dates = [item for item in dates if item < start]
        warmup = result["warmup"]
        if not warmup_dates or len(warmup_dates) != warmup["used_rows"] or warmup_dates[0].isoformat() != warmup["start_date"] or warmup_dates[-1].isoformat() != warmup["end_date"] or dates[-1] != end:
            raise ValueError("saved warmup does not match input snapshot")
        assumptions = result["execution_assumptions"]
        expected_assumptions = {
            "model": "research_fractional_v1", "signal": "previous_observation_close",
            "execution": "next_observation_open", "first_day_signal": "last_warmup_close",
            "transaction_cost": "proportional_on_each_buy_and_sell",
            "slippage": "buy_price_increased_sell_price_decreased",
            "fractional_shares": True, "forced_final_sale": False,
            "benchmark_includes_costs": False, "exchange_execution_constraints": "not_modelled",
            "price_basis": "qfq",
        }
        if assumptions != expected_assumptions or any(type(assumptions[key]) is not type(value) for key, value in expected_assumptions.items()):
            raise ValueError("missing or inconsistent execution assumptions")
        if len(result["trades"]) != result["order_count"]:
            raise ValueError("incomplete saved orders")
        if result["effective_parameters"]["strategy_name"] != result["strategy_name"]:
            raise ValueError("strategy parameters mismatch")
        for key in BacktestParametersContext.model_fields:
            value = result["effective_parameters"][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("non-numeric saved parameter")
        for key in SavedBacktestMetricsContext.model_fields:
            value = result[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise ValueError("non-numeric saved metric")
