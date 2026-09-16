"""V2 B3/B4: parameterised backtests, snapshots and history.

Responsibilities on B's side of the contract:

* reject invalid parameters **before** any data fetch (``40001``);
* translate the requested moving-average windows into a *warmup* window and fetch
  that data explicitly, so ``long=120`` on a short user window still has enough
  bars (``40003`` when even the widest fetch cannot supply them);
* save summary + curves + orders + parameters + data metadata **in one
  transaction**, returning a real ``backtest_id``;
* read history back from the saved snapshot - ``GET`` never refetches or
  recomputes, and old V1 rows are reported as ``snapshot_status="missing"``
  instead of being silently refilled.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import (
    ApplicationError,
    BacktestError,
    BacktestNotFoundError,
    DataProviderError,
    DatabaseOperationError,
    InsufficientStockDataError,
    InvalidParameterError,
)
from backend.app.models.backtest_result import BacktestResult
from backend.app.quant.config import QuantConfig, resolve_config
from backend.app.quant.serialization import to_json_safe
from backend.app.schemas.backtest import BacktestParametersSchema
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.c_quant_entry import (
    WINDOW_OWNER_C,
    CWindowedEntry,
    load_c_windowed_entry,
)
from backend.app.services.market_data_service import (
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataSource,
)
from backend.app.services.stock_service import DEFAULT_WINDOW_DAYS

SEMANTICS_V1_LEGACY = "v1_legacy"
SEMANTICS_V2_WINDOWED = "v2_windowed"

SNAPSHOT_COMPLETE = "complete"
SNAPSHOT_MISSING = "missing"

#: C1 whitelist: the only fields a V2 request may override.
ALLOWED_PARAMETER_FIELDS = (
    "ma_short_period",
    "ma_long_period",
    "initial_cash",
    "transaction_cost",
    "slippage",
)

#: Acceptance **data package** coverage (C): delivered files must carry at least
#: this many valid bars before the backtest start so every allowed MA can be
#: exercised. This is NOT a per-request minimum - see ``warmup_required_days``.
DELIVERY_WARMUP_MIN_BARS = 120

#: Trading days -> calendar days slack when sizing the warmup fetch window.
_WARMUP_CALENDAR_FACTOR = 1.7
_WARMUP_MAX_ATTEMPTS = 3
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def resolve_effective_parameters(overrides: Mapping[str, Any]) -> QuantConfig:
    """C's defaults plus the whitelisted overrides, validated by C's own rules."""
    unknown = sorted(set(overrides) - set(ALLOWED_PARAMETER_FIELDS))
    if unknown:
        raise InvalidParameterError(f"unsupported backtest parameters: {unknown}")
    merged = QuantConfig().to_parameters()
    merged.update({key: value for key, value in overrides.items() if value is not None})
    if merged["ma_short_period"] >= merged["ma_long_period"]:
        raise InvalidParameterError(
            "ma_short_period must be less than ma_long_period"
        )
    try:
        return resolve_config(merged)
    except (ValueError, TypeError) as exc:
        raise InvalidParameterError(str(exc)) from exc


def warmup_required_days(config: QuantConfig) -> int:
    """Per-request warmup: C consumes the last ``ma_long_period`` valid bars.

    C (PR #10 review): "单次 V2 计算：C 只使用开始日前最后 long 条有效日线。
    默认需要 20 条，long=120 时需要 120 条"; ``long=120`` on a one-day window
    therefore needs exactly 120 warmup bars, not 121. The 120-bar figure belongs
    to the acceptance data package (``DELIVERY_WARMUP_MIN_BARS``) and must not
    gate every request. When C's ``resolve_backtest_request`` is available its
    ``request_config.required_warmup_rows`` takes precedence.
    """
    return config.ma_long_period


def whitelisted_parameters(config: QuantConfig) -> Dict[str, Any]:
    """The only five fields C's V2 entry points accept, taken from B's config.

    C (PR #10 review): handing over the whole ``QuantConfig.to_parameters()``
    payload makes C reject the request, because everything outside the whitelist
    (``ma_medium_period``, ``macd_*``, ``benchmark_method``, ...) is C's own
    algorithm configuration - and B's defaults there would silently overwrite
    C's baseline (e.g. ``first_open_to_last_close_no_cost``). C owns those; B
    only forwards the user-overridable five.
    """
    parameters = config.to_parameters()
    return {name: parameters[name] for name in ALLOWED_PARAMETER_FIELDS}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(round(float(value), 8)))


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def frame_digest(rows: Sequence[DailyKlineSchema]) -> str:
    """Stable hash of the exact bars used, so a saved run can be re-checked."""
    payload = [
        [
            row.trade_date.isoformat(),
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume,
            row.amount,
            row.turnover_rate,
            row.change_pct,
        ]
        for row in sorted(rows, key=lambda item: item.trade_date)
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class BacktestRepository:
    """Snapshot storage + history reads for ``backtest_result``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        *,
        stock_code: str,
        result: Mapping[str, Any],
        semantics_version: str,
        effective_parameters: Mapping[str, Any],
        warmup_start_date: Optional[date],
        data_meta: Mapping[str, Any],
        strategy_version: Optional[str] = None,
        input_snapshot: Optional[Sequence[Mapping[str, Any]]] = None,
        c_result: Optional[Mapping[str, Any]] = None,
    ) -> int:
        """Persist summary + curves + orders atomically; returns the new id."""
        try:
            record = BacktestResult(
                stock_code=stock_code,
                strategy_name=str(result.get("strategy_name") or "unknown"),
                start_date=_as_date(result["start_date"]),
                end_date=_as_date(result["end_date"]),
                initial_cash=_decimal(result.get("initial_cash")),
                total_return=_decimal(result.get("total_return")),
                annual_return=_decimal(result.get("annual_return")),
                max_drawdown=_decimal(result.get("max_drawdown")),
                sharpe_ratio=_decimal(result.get("sharpe_ratio")),
                win_rate=_decimal(result.get("win_rate")),
                trade_count=result.get("trade_count"),
                benchmark_return=_decimal(result.get("benchmark_return")),
                parameters=dict(effective_parameters),
                semantics_version=semantics_version,
                strategy_version=strategy_version,
                final_equity=_decimal(result.get("final_equity")),
                order_count=result.get("order_count"),
                warmup_start_date=warmup_start_date,
                equity_curve=list(result.get("equity_curve") or []),
                benchmark_curve=list(result.get("benchmark_curve") or []),
                drawdown_curve=list(result.get("drawdown_curve") or []),
                orders=list(result.get("trades") or []),
                effective_parameters=dict(effective_parameters),
                data_meta=dict(data_meta),
                input_snapshot=list(input_snapshot) if input_snapshot is not None else None,
                c_result=dict(c_result) if c_result is not None else None,
            )
            self._session.add(record)
            self._session.commit()
            return int(record.id)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def get(
        self,
        backtest_id: int,
        *,
        include_input_snapshot: bool = False,
        include_c_result: bool = False,
    ) -> Dict[str, Any]:
        try:
            record = self._session.get(BacktestResult, backtest_id)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        if record is None:
            raise BacktestNotFoundError(f"backtest {backtest_id} not found")
        return self._to_detail(
            record,
            include_input_snapshot=include_input_snapshot,
            include_c_result=include_c_result,
        )

    def list(
        self,
        *,
        stock_code: Optional[str] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Tuple[List[Dict[str, Any]], int]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
        try:
            filters = []
            if stock_code:
                filters.append(BacktestResult.stock_code == stock_code)
            total = int(
                self._session.execute(
                    select(func.count()).select_from(BacktestResult).where(*filters)
                ).scalar()
                or 0
            )
            statement = (
                select(BacktestResult)
                .where(*filters)
                .order_by(BacktestResult.created_at.desc(), BacktestResult.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            records = self._session.execute(statement).scalars().all()
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        return [self._to_summary(record) for record in records], total

    @staticmethod
    def _to_summary(record: BacktestResult) -> Dict[str, Any]:
        return {
            "backtest_id": int(record.id),
            "stock_code": record.stock_code,
            "strategy_name": record.strategy_name,
            "semantics_version": record.semantics_version,
            "start_date": _iso(record.start_date),
            "end_date": _iso(record.end_date),
            "initial_cash": _float(record.initial_cash),
            "final_equity": _float(record.final_equity),
            "total_return": _float(record.total_return),
            "annual_return": _float(record.annual_return),
            "max_drawdown": _float(record.max_drawdown),
            "sharpe_ratio": _float(record.sharpe_ratio),
            "win_rate": _float(record.win_rate),
            "trade_count": record.trade_count,
            "order_count": record.order_count,
            "benchmark_return": _float(record.benchmark_return),
            "snapshot_status": (
                SNAPSHOT_COMPLETE if record.equity_curve else SNAPSHOT_MISSING
            ),
            "created_at": _iso(record.created_at),
        }

    @classmethod
    def _to_detail(
        cls,
        record: BacktestResult,
        *,
        include_input_snapshot: bool = False,
        include_c_result: bool = False,
    ) -> Dict[str, Any]:
        detail = cls._to_summary(record)
        data_meta = record.data_meta or {}
        snapshot = record.input_snapshot or []
        c_result = record.c_result if isinstance(record.c_result, Mapping) else None
        detail.update(
            {
                "warmup_start_date": _iso(record.warmup_start_date),
                "strategy_version": record.strategy_version,
                "current_position": data_meta.get("current_position"),
                "parameters": record.effective_parameters or record.parameters or {},
                "effective_parameters": record.effective_parameters
                or record.parameters
                or {},
                "equity_curve": record.equity_curve or [],
                "benchmark_curve": record.benchmark_curve or [],
                "drawdown_curve": record.drawdown_curve or [],
                "trades": record.orders or [],
                "data_meta": data_meta,
                # The snapshot itself is opt-in: it is the full warmup+window row
                # set, which callers (e.g. C's verification) request explicitly.
                "input_snapshot_available": bool(snapshot),
                "input_snapshot_rows": len(snapshot),
            }
        )
        if include_input_snapshot:
            detail["input_snapshot"] = snapshot
        # C's own result envelope. History reports the algorithm's configuration
        # and hashes from here instead of B's rounded summary columns; the full
        # payload stays opt-in because it repeats the curves and the snapshot.
        detail["c_result_available"] = c_result is not None
        if c_result is not None:
            detail["c_semantics_version"] = c_result.get("semantics_version")
            detail["c_algorithm_version"] = c_result.get("algorithm_version")
            detail["c_data_hash"] = c_result.get("data_hash")
            detail["c_initial_equity"] = c_result.get("initial_equity")
            detail["c_warmup"] = c_result.get("warmup")
            detail["c_execution_assumptions"] = c_result.get("execution_assumptions")
            if include_c_result:
                detail["c_result"] = c_result
        if detail["snapshot_status"] == SNAPSHOT_MISSING:
            detail["snapshot_missing_reason"] = (
                "V1 record stored only summary metrics; curves and orders were "
                "not persisted and are not recomputed from current market data"
            )
        return detail


def _float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class BacktestService:
    """Parameters -> warmup fetch -> C's core -> one-shot snapshot."""

    def __init__(
        self,
        *,
        quant_service,
        market_data_source: Optional[MarketDataSource] = None,
        repository: Optional[BacktestRepository] = None,
        today: Optional[Callable[[], date]] = None,
        c_entry_loader: Callable[[], Optional[CWindowedEntry]] = load_c_windowed_entry,
    ) -> None:
        self._quant = quant_service
        self._market = market_data_source
        self._repository = repository
        self._today = today or date.today
        #: Injectable so tests can exercise both "C is importable" and "C's V2
        #: entry points are absent" without patching the quant package.
        self._load_c_entry = c_entry_loader

    def run(
        self,
        *,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        parameters: Optional[BacktestParametersSchema] = None,
        parameters_provided: bool = False,
    ) -> Dict[str, Any]:
        # 1) Parameters are validated before any data access.
        if parameters_provided and parameters is None:
            # The three request shapes stay distinct (V2 plan matrix):
            # omitted -> v1_legacy, explicit {} -> v2_windowed, explicit null -> 40001.
            raise InvalidParameterError(
                "parameters must not be null; omit it for V1 behaviour or send an object"
            )
        if parameters is not None:
            # C: an explicit ``null`` *value* is not a request to use the default -
            # only omitting the field is. ``provided_overrides()`` drops ``None``,
            # so without this check ``{"ma_long_period": null}`` silently ran on
            # the default and was saved as a success.
            explicit_nulls = parameters.explicit_null_fields()
            if explicit_nulls:
                raise InvalidParameterError(
                    "backtest parameters must not be null: "
                    f"{explicit_nulls}; omit a field to use its default value"
                )
        effective = resolve_effective_parameters(
            parameters.provided_overrides() if parameters is not None else {}
        )
        semantics = (
            SEMANTICS_V2_WINDOWED if parameters_provided else SEMANTICS_V1_LEGACY
        )

        if start_date is not None and end_date is not None and start_date > end_date:
            raise InvalidParameterError("start_date must not be after end_date")

        if semantics == SEMANTICS_V1_LEGACY:
            return self._run_legacy(stock_code, start_date, end_date, effective)

        return self._run_windowed(
            stock_code, start_date, end_date, effective, parameters is not None
        )

    # -- v1_legacy ----------------------------------------------------------

    def _run_legacy(
        self,
        stock_code: str,
        start_date: Optional[date],
        end_date: Optional[date],
        effective: QuantConfig,
    ) -> Dict[str, Any]:
        result = self._quant.run_backtest(stock_code, start_date, end_date)
        result.update(
            {
                "semantics_version": SEMANTICS_V1_LEGACY,
                "effective_parameters": effective.to_parameters(),
                "warmup_start_date": None,
                "warmup_rows": 0,
                "data_meta": {
                    "semantics_version": SEMANTICS_V1_LEGACY,
                    "requested_start_date": _iso(start_date),
                    "requested_end_date": _iso(end_date),
                    "data_source": "MarketDataSource.query_daily (V1 default window)",
                },
            }
        )
        return self._persist_and_return(
            stock_code,
            result,
            stored_parameters=effective.to_parameters(),
            warmup_start_date=None,
            data_meta=result["data_meta"],
        )

    # -- v2_windowed --------------------------------------------------------

    def _run_windowed(
        self,
        stock_code: str,
        start_date: Optional[date],
        end_date: Optional[date],
        effective: QuantConfig,
        explicitly_provided: bool,
    ) -> Dict[str, Any]:
        end = end_date or self._today()
        start = start_date or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
        if start > end:
            raise InvalidParameterError("start_date must not be after end_date")

        c_entry = self._load_c_entry()
        if c_entry is None or c_entry.parameters_unset is None:
            # C (PR #10 review): running the old V1 core here and labelling its
            # output ``v2_windowed`` would report the wrong window semantics.
            # Say V2 is unavailable and persist nothing.
            raise BacktestError(
                "v2_windowed backtest is unavailable: C's run_backtest_request "
                "is not importable; omit `parameters` to use the V1 path"
            )

        # C owns parameter and window validation. Both run BEFORE any data is
        # fetched, and their errors are reported (40001), never swallowed.
        raw_parameters = whitelisted_parameters(effective)
        request_config = self._call_c(c_entry, c_entry.resolve, raw_parameters)

        required = warmup_required_days(effective)
        required = int(
            getattr(request_config, "required_warmup_rows", required) or required
        )
        start, end = self._call_c(c_entry, c_entry.validate_window, start, end)

        rows, warmup_rows, fetch_start = self._fetch_with_warmup(
            stock_code, start, end, required
        )
        window_rows = [row for row in rows if row.trade_date >= start]
        if not window_rows:
            raise InsufficientStockDataError(
                f"stock {stock_code} has no bars inside the requested window "
                f"{start.isoformat()}..{end.isoformat()}"
            )

        frame = self._quant.rows_to_frame(rows)
        # Hand C the WHOLE normalized frame (warmup + window); C selects the actual
        # warmup/backtest windows itself and returns window-only results. B never
        # pre-trims it, and only the five whitelisted parameters are forwarded.
        c_result = to_json_safe(
            self._call_c(
                c_entry,
                c_entry.run,
                frame,
                start_date=start,
                end_date=end,
                parameters=raw_parameters,
            )
        )
        if not isinstance(c_result, Mapping):
            raise BacktestError("C's run_backtest_request did not return a result object")
        result = dict(c_result)

        data_meta = {
            "semantics_version": SEMANTICS_V2_WINDOWED,
            "requested_start_date": start.isoformat(),
            "requested_end_date": end.isoformat(),
            "warmup_start_date": fetch_start.isoformat(),
            "warmup_rows": warmup_rows,
            "warmup_required_days": required,
            "delivery_warmup_min_bars": DELIVERY_WARMUP_MIN_BARS,
            "rows": len(rows),
            "rows_in_window": len(window_rows),
            # B's digest of the exact frame handed to C. Deliberately NOT called
            # ``data_hash``: C's own ``data_hash`` covers C's result, and the two
            # are recorded separately and never substituted for each other.
            "frame_digest": frame_digest(rows),
            "c_data_hash": c_result.get("data_hash"),
            "computed_start_date": _iso(result.get("start_date")),
            "computed_end_date": _iso(result.get("end_date")),
            "current_position": result.get("current_position"),
            "parameters_explicit": explicitly_provided,
            "data_source": "MarketDataSource.query_daily (warmup window)",
            "window_owner": WINDOW_OWNER_C,
        }
        result.update(
            {
                "semantics_version": SEMANTICS_V2_WINDOWED,
                # C owns everything outside the whitelist, so only those five are
                # stored as "effective parameters": B's QuantConfig defaults for
                # the rest must not masquerade as C's algorithm configuration.
                "effective_parameters": raw_parameters,
                "warmup_start_date": fetch_start.isoformat(),
                "warmup_rows": warmup_rows,
                "data_meta": data_meta,
            }
        )
        # C wants exactly what it consumed: the last ``required`` warmup bars plus
        # every window bar - not all the extra history B fetched for widening.
        snapshot_rows = window_rows + [
            row for row in rows if row.trade_date < start
        ][-required:]
        snapshot_rows.sort(key=lambda item: item.trade_date)
        input_snapshot = [row.model_dump(mode="json") for row in snapshot_rows]
        return self._persist_and_return(
            stock_code,
            result,
            stored_parameters=raw_parameters,
            warmup_start_date=fetch_start,
            data_meta=data_meta,
            input_snapshot=input_snapshot,
            c_result=c_result,
        )

    @staticmethod
    def _call_c(
        c_entry: CWindowedEntry,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run one of C's entry points, translating only C's documented failures.

        ``BacktestParameterError`` means the request violates C's parameter
        contract (``40001``); ``InsufficientDataError`` means the window or warmup
        cannot be satisfied (``40003``). Everything else - including a wiring
        mistake on B's side - keeps propagating so it stays a real ``500``. C asked
        explicitly that server/wiring problems not be disguised as user parameter
        errors, so this catches C's declared classes only, never ``Exception``.

        ``parameter_errors``/``data_errors`` may be empty tuples when C ships a
        different layout; ``except ()`` never matches, so an unknown shape
        degrades to ``500`` instead of being mislabelled.
        """
        try:
            return func(*args, **kwargs)
        except ApplicationError:
            raise
        except c_entry.parameter_errors as exc:
            raise InvalidParameterError(str(exc)) from exc
        except c_entry.data_errors as exc:
            raise InsufficientStockDataError(str(exc)) from exc

    def _fetch_with_warmup(
        self, stock_code: str, start: date, end: date, required: int
    ) -> Tuple[List[DailyKlineSchema], int, date]:
        """Fetch warmup + window bars, widening until the warmup is sufficient."""
        fetch_start = start - timedelta(days=int(required * _WARMUP_CALENDAR_FACTOR) + 10)
        rows: List[DailyKlineSchema] = []
        warmup_rows = 0

        for _ in range(_WARMUP_MAX_ATTEMPTS):
            rows = self._query_daily(stock_code, fetch_start, end, required)
            warmup_rows = sum(1 for row in rows if row.trade_date < start)
            if warmup_rows >= required:
                return rows, warmup_rows, fetch_start
            wider = fetch_start - timedelta(days=max(int(required * _WARMUP_CALENDAR_FACTOR), 30))
            if wider >= fetch_start:
                break
            fetch_start = wider

        raise InsufficientStockDataError(
            f"stock {stock_code} has only {warmup_rows} valid bars before "
            f"{start.isoformat()}; the requested moving-average windows require "
            f"{required} warmup bars"
        )

    def _query_daily(
        self, stock_code: str, start: date, end: date, min_rows: int
    ) -> List[DailyKlineSchema]:
        if self._market is None:
            raise DataProviderError(
                "backtest requires a market data source to fetch warmup bars"
            )
        return list(
            self._market.query_daily(
                stock_code,
                start,
                end,
                min_rows=min_rows,
                max_stale_days=DEFAULT_MAX_STALE_DAYS,
                max_gap_days=DEFAULT_MAX_GAP_DAYS,
            )
        )

    # -- persistence --------------------------------------------------------

    def _persist_and_return(
        self,
        stock_code: str,
        result: Dict[str, Any],
        *,
        stored_parameters: Mapping[str, Any],
        warmup_start_date: Optional[date],
        data_meta: Mapping[str, Any],
        input_snapshot: Optional[Sequence[Mapping[str, Any]]] = None,
        c_result: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._repository is None:
            result.setdefault("backtest_id", None)
            return result
        backtest_id = self._repository.save(
            stock_code=stock_code,
            result=result,
            semantics_version=str(result.get("semantics_version")),
            effective_parameters=stored_parameters,
            warmup_start_date=warmup_start_date,
            data_meta=data_meta,
            strategy_version=result.get("strategy_version"),
            input_snapshot=input_snapshot,
            c_result=c_result,
        )
        result["backtest_id"] = backtest_id
        result["snapshot_status"] = SNAPSHOT_COMPLETE
        return result
