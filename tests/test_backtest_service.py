"""V2 B3/B4: parameter whitelist, warmup window, snapshots and history."""

from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1.dependencies import (
    get_backtest_repository,
    get_backtest_service,
)
from backend.app.core.errors import (
    BacktestError,
    BacktestNotFoundError,
    InsufficientStockDataError,
    InvalidParameterError,
)
from backend.app.db.migrations import apply_migrations
from backend.app.main import app
from backend.app.models.backtest_result import BacktestResult
from backend.app.quant.config import QuantConfig
from backend.app.schemas.backtest import BacktestParametersSchema, BacktestRequestSchema
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.backtest_service import (
    ALLOWED_PARAMETER_FIELDS,
    SEMANTICS_V1_LEGACY,
    SEMANTICS_V2_WINDOWED,
    SNAPSHOT_MISSING,
    BacktestRepository,
    BacktestService,
    DELIVERY_WARMUP_MIN_BARS,
    frame_digest,
    resolve_effective_parameters,
    warmup_required_days,
    whitelisted_parameters,
)
from backend.app.services.c_quant_entry import WINDOW_OWNER_C
from backend.app.services.quant_service import QuantService
from backend.app.services.stock_service import StockService

STOCK_CODE = "600519"
START = date(2025, 1, 1)
C_DATA_HASH = "c" * 64
#: Sentinel meaning "give the service the default fake C entry".
_DEFAULT_C_ENTRY = object()
#: Stands in for C's ``PARAMETERS_UNSET`` marker object.
_PARAMETERS_UNSET = object()


def _rows(count: int = 400, start: date = START) -> list:
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.1
        rows.append(
            DailyKlineSchema(
                stock_code=STOCK_CODE,
                trade_date=start + timedelta(days=index),
                open=close - 0.05,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=1000,
                amount=100000.0,
                turnover_rate=0.01,
                change_pct=0.02,
            )
        )
    return rows


class _FakeMarketSource:
    """Returns the bars inside the requested window; records every call."""

    def __init__(self, rows) -> None:
        self._rows = rows
        self.calls = []

    def query_daily(self, stock_code, start_date=None, end_date=None, **kwargs):
        self.calls.append((stock_code, start_date, end_date, kwargs))
        return [
            row
            for row in self._rows
            if (start_date is None or row.trade_date >= start_date)
            and (end_date is None or row.trade_date <= end_date)
        ]


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return Session(bind=engine)


def _service(
    market,
    repository=None,
    today=date(2026, 6, 1),
    c_entry=_DEFAULT_C_ENTRY,
) -> BacktestService:
    if c_entry is _DEFAULT_C_ENTRY:
        c_entry = _FakeCWindowedEntry()
    return BacktestService(
        quant_service=QuantService(
            stock_service=StockService(provider=_UnusedProvider()),
            market_data_source=market,
        ),
        market_data_source=market,
        repository=repository,
        today=lambda: today,
        c_entry_loader=lambda: c_entry,
    )


class _UnusedProvider:
    """The windowed path always passes a frame, so this must never be used."""

    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("provider must not be called")


class _FakeBacktestParameterError(ValueError):
    """Mirrors C's ``BacktestParameterError``.

    C's class derives from ``ValueError``, **not** from ``ApplicationError``, which
    is exactly why an unwrapped call surfaced as a plain-text 500.
    """


class _FakeInsufficientDataError(ValueError):
    """Mirrors C's ``InsufficientDataError`` (unsatisfiable window/warmup)."""


class _FakeRequestConfig:
    """Stands in for C's ``request_config`` returned by ``resolve``."""

    def __init__(self, required_warmup_rows: int) -> None:
        self.required_warmup_rows = required_warmup_rows
        self.semantics_version = SEMANTICS_V2_WINDOWED


class _FakeCWindowedEntry:
    """Stands in for C's V2 entry points, mirroring the published contract.

    Shape verified against ``pop17589822299-coder:codex/v2-c-backtest-params``
    (``92df017``):

    * ``algorithm_version`` / ``warmup`` / ``initial_equity`` /
      ``execution_assumptions`` / ``input_snapshot`` / ``data_hash`` /
      ``semantics_version`` all sit on the **first level** of the result;
    * ``initial_equity`` is an object and ``input_snapshot`` is an envelope;
    * the benchmark identity is ``effective_parameters.benchmark_method`` -
      there is **no** ``execution_assumptions.baseline``;
    * curve value keys are ``equity`` / ``benchmark_equity`` / ``drawdown``;
    * ``trades`` is the成交 array name (``order_count`` counts records,
      ``trade_count`` counts completed round trips).

    Every payload B forwards is recorded, so tests can assert the five-field
    whitelist, that validation happens *before* any data fetch, and that C's
    result envelope is stored verbatim.
    """

    parameters_unset = _PARAMETERS_UNSET
    parameter_errors = (_FakeBacktestParameterError,)
    data_errors = (_FakeInsufficientDataError,)

    def __init__(
        self,
        *,
        required_warmup_rows=None,
        resolve_error=None,
        validate_error=None,
        run_error=None,
    ) -> None:
        self.required_warmup_rows = required_warmup_rows
        self.resolve_error = resolve_error
        self.validate_error = validate_error
        self.run_error = run_error
        self.resolve_calls: list = []
        self.validate_calls: list = []
        self.run_calls: list = []

    def resolve(self, raw_parameters):
        self.resolve_calls.append(dict(raw_parameters))
        if self.resolve_error is not None:
            raise self.resolve_error
        required = self.required_warmup_rows
        if required is None:
            required = int(raw_parameters.get("ma_long_period", 20))
        return _FakeRequestConfig(required_warmup_rows=required)

    def validate_window(self, start_date, end_date):
        self.validate_calls.append((start_date, end_date))
        if self.validate_error is not None:
            raise self.validate_error
        return start_date, end_date

    def run(self, frame, *, start_date, end_date, parameters):
        self.run_calls.append(
            {
                "frame_rows": len(frame),
                "start_date": start_date,
                "end_date": end_date,
                "parameters": dict(parameters),
            }
        )
        if self.run_error is not None:
            raise self.run_error
        initial_cash = float(parameters["initial_cash"])
        day = start_date.isoformat()
        return {
            "strategy_name": "ma_long_only",
            "semantics_version": SEMANTICS_V2_WINDOWED,
            "algorithm_version": "ma_long_only_v2.0.0",
            "start_date": day,
            "end_date": end_date.isoformat(),
            "initial_cash": initial_cash,
            "final_equity": initial_cash * 1.01,
            "total_return": 0.01,
            "annual_return": 0.02,
            "max_drawdown": -0.05,
            "sharpe_ratio": 1.0,
            "win_rate": 0.5,
            "trade_count": 2,
            "order_count": 2,
            "benchmark_return": 0.005,
            # -- first-level envelope fields, exactly as C returns them --------
            "effective_parameters": {
                **parameters,
                "strategy_name": "ma_long_only",
                "benchmark_method": "first_open_to_last_close_no_cost",
            },
            "warmup": {
                "start_date": day,
                "end_date": day,
                "required_rows": 20,
                "used_rows": 20,
            },
            "initial_equity": {
                "trade_date": day,
                "equity": initial_cash,
                "valuation": "before_open",
            },
            "execution_assumptions": {
                "model": "research_fractional_v1",
                "benchmark_includes_costs": False,
                "price_basis": "qfq",
            },
            "input_snapshot": {
                "schema_version": "quant_input_v1",
                "stock_code": STOCK_CODE,
                "frequency": "daily",
                "adjust": "qfq",
                "data_mode": "dataframe",
                "columns": [
                    "stock_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
                "rows": [],
            },
            "data_hash": C_DATA_HASH,
            "equity_curve": [{"trade_date": day, "equity": initial_cash}],
            "benchmark_curve": [{"trade_date": day, "benchmark_equity": initial_cash}],
            "drawdown_curve": [{"trade_date": day, "drawdown": 0.0}],
            "trades": [
                {
                    "order_id": 1,
                    "signal_date": day,
                    "execution_date": day,
                    "side": "buy",
                    "position_after": 1,
                    "round_trip_pnl": None,
                    "round_trip_return": None,
                }
            ],
        }


# -- parameters ------------------------------------------------------------


def test_effective_parameters_use_defaults_and_overrides():
    effective = resolve_effective_parameters({"ma_long_period": 60, "initial_cash": 50000})

    assert isinstance(effective, QuantConfig)
    assert effective.ma_long_period == 60
    assert effective.initial_cash == 50000
    assert effective.ma_short_period == QuantConfig().ma_short_period  # untouched
    assert effective.ma_trend_period == QuantConfig().ma_trend_period


def test_effective_parameters_reject_unknown_field():
    with pytest.raises(InvalidParameterError):
        resolve_effective_parameters({"macd_fast_period": 3})


def test_effective_parameters_reject_short_not_less_than_long():
    with pytest.raises(InvalidParameterError):
        resolve_effective_parameters({"ma_short_period": 60, "ma_long_period": 60})


def test_schema_rejects_unknown_field_and_non_finite_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BacktestParametersSchema(**{"unknown_field": 1})
    with pytest.raises(ValidationError):
        BacktestParametersSchema(initial_cash=float("nan"))
    with pytest.raises(ValidationError):
        BacktestParametersSchema(initial_cash=float("inf"))
    with pytest.raises(ValidationError):
        BacktestParametersSchema(transaction_cost=1.0)
    with pytest.raises(ValidationError):
        BacktestParametersSchema(ma_long_period=121)


def test_schema_rejects_boolean_period():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BacktestParametersSchema(ma_short_period=True)


def test_request_schema_distinguishes_omitted_from_explicit_parameters():
    omitted = BacktestRequestSchema(stock_code=STOCK_CODE)
    explicit_empty = BacktestRequestSchema(stock_code=STOCK_CODE, parameters={})

    assert omitted.parameters_provided is False
    assert explicit_empty.parameters_provided is True
    assert explicit_empty.parameters.provided_overrides() == {}


def test_warmup_requirement_is_the_longest_ma_not_a_fixed_120_floor():
    """C: per-request warmup = the last ``long`` bars; 120 bars is the data package."""
    assert warmup_required_days(QuantConfig()) == 20  # ma_long_period default
    assert warmup_required_days(resolve_effective_parameters({"ma_long_period": 120})) == 120
    assert DELIVERY_WARMUP_MIN_BARS == 120  # acceptance package coverage, not a gate


def test_schema_rejects_numeric_strings_booleans_and_float_periods():
    """C: reject string numbers, booleans and non-integer periods (no coercion)."""
    from pydantic import ValidationError

    rejected = [
        {"ma_short_period": "5"},
        {"ma_long_period": "20"},
        {"initial_cash": "100000"},
        {"transaction_cost": "0.1"},
        {"slippage": "0"},
        {"initial_cash": True},   # bool is an int subclass -> must not mean 1.0
        {"slippage": False},
        {"ma_short_period": 5.0},
        {"initial_cash": float("nan")},
        {"initial_cash": float("inf")},
    ]
    for payload in rejected:
        with pytest.raises(ValidationError):
            BacktestParametersSchema(**payload)

    accepted = BacktestParametersSchema(
        ma_short_period=5,
        ma_long_period=20,
        initial_cash=100000,   # plain int is still fine for a float field
        transaction_cost=0.001,
        slippage=0,
    )
    assert accepted.initial_cash == 100000.0
    assert accepted.provided_overrides()["slippage"] == 0


# -- orchestration ---------------------------------------------------------


def test_legacy_run_persists_snapshot_and_returns_id():
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository).run(
            stock_code=STOCK_CODE, parameters_provided=False
        )

        assert result["semantics_version"] == SEMANTICS_V1_LEGACY
        assert result["warmup_start_date"] is None
        assert isinstance(result["backtest_id"], int)
        saved = repository.get(result["backtest_id"])
        assert saved["equity_curve"] == result["equity_curve"]
        assert saved["trades"] == result["trades"]
        assert saved["semantics_version"] == SEMANTICS_V1_LEGACY


def test_windowed_run_records_warmup_window_and_data_hash():
    market = _FakeMarketSource(_rows())
    start = date(2025, 6, 1)
    end = date(2025, 12, 31)
    c_entry = _FakeCWindowedEntry()
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository, c_entry=c_entry).run(
            stock_code=STOCK_CODE,
            start_date=start,
            end_date=end,
            parameters=BacktestParametersSchema(ma_long_period=120),
            parameters_provided=True,
        )

        assert result["semantics_version"] == SEMANTICS_V2_WINDOWED
        assert result["effective_parameters"]["ma_long_period"] == 120
        warmup_start = date.fromisoformat(result["warmup_start_date"])
        assert warmup_start < start
        assert result["warmup_rows"] >= 120  # C consumes the last 120 for long=120
        meta = result["data_meta"]
        assert meta["requested_start_date"] == start.isoformat()
        assert meta["warmup_required_days"] == 120  # long, not long+1
        assert meta["delivery_warmup_min_bars"] == 120
        assert meta["window_owner"] == WINDOW_OWNER_C
        # B's frame digest and C's own data_hash are recorded separately.
        assert len(meta["frame_digest"]) == 64
        assert meta["c_data_hash"] == C_DATA_HASH
        assert "data_hash" not in meta

        saved = repository.get(result["backtest_id"])
        assert saved["warmup_start_date"] == result["warmup_start_date"]
        assert saved["data_meta"]["frame_digest"] == meta["frame_digest"]
        assert saved["c_data_hash"] == C_DATA_HASH


def test_windowed_run_is_unavailable_when_c_entry_is_absent_and_saves_nothing():
    """C: never run the old core and label it ``v2_windowed``; fail explicitly."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(BacktestError) as excinfo:
            _service(market, repository, c_entry=None).run(
                stock_code=STOCK_CODE,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 12, 31),
                parameters=BacktestParametersSchema(),
                parameters_provided=True,
            )

        assert excinfo.value.code == 50004
        assert "unavailable" in str(excinfo.value)
        assert market.calls == []          # no data was fetched
        items, total = repository.list()
        assert total == 0 and items == []  # and nothing was saved


def test_legacy_path_still_works_when_c_entry_is_absent():
    """C: omitting ``parameters`` keeps the V1 behaviour untouched."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository, c_entry=None).run(
            stock_code=STOCK_CODE, parameters_provided=False
        )

    assert result["semantics_version"] == SEMANTICS_V1_LEGACY
    assert isinstance(result["backtest_id"], int)
    assert market.calls  # V1 still fetches its own default window


def test_windowed_run_forwards_only_the_five_whitelisted_parameters():
    """C: B must not forward the whole QuantConfig payload to ``resolve``/``run``."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry()
    with _session() as session:
        _service(market, BacktestRepository(session), c_entry=c_entry).run(
            stock_code=STOCK_CODE,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 12, 31),
            parameters=BacktestParametersSchema(ma_long_period=60),
            parameters_provided=True,
        )

    assert set(c_entry.resolve_calls[0]) == set(ALLOWED_PARAMETER_FIELDS)
    assert set(c_entry.run_calls[0]["parameters"]) == set(ALLOWED_PARAMETER_FIELDS)
    # Defaults B resolved are still forwarded...
    assert c_entry.run_calls[0]["parameters"]["ma_long_period"] == 60
    assert c_entry.run_calls[0]["parameters"]["ma_short_period"] == 5
    # ...but nothing outside the whitelist is.
    assert "benchmark_method" not in c_entry.run_calls[0]["parameters"]
    assert "ma_medium_period" not in c_entry.run_calls[0]["parameters"]


def test_windowed_run_validates_parameters_and_window_before_fetching():
    """C: parameter and date validation must complete before any data access."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry()
    with _session() as session:
        _service(market, BacktestRepository(session), c_entry=c_entry).run(
            stock_code=STOCK_CODE,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 12, 31),
            parameters=BacktestParametersSchema(),
            parameters_provided=True,
        )

    assert c_entry.resolve_calls          # parameters validated
    assert c_entry.validate_calls         # window validated
    assert market.calls                   # and only then did the fetch happen
    assert c_entry.resolve_calls[0] == c_entry.run_calls[0]["parameters"]


def test_windowed_run_reports_c_validation_errors_instead_of_swallowing_them():
    """A failing ``resolve`` is a 40001, not a silently-ignored fallback."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry(
        resolve_error=_FakeBacktestParameterError(
            "ma_short_period must be less than ma_long_period"
        )
    )
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(InvalidParameterError) as excinfo:
            _service(market, repository, c_entry=c_entry).run(
                stock_code=STOCK_CODE,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 12, 31),
                parameters=BacktestParametersSchema(),
                parameters_provided=True,
            )
        items, total = repository.list()

    assert "ma_short_period must be less than ma_long_period" in str(excinfo.value)
    assert market.calls == []
    assert c_entry.validate_calls == []
    assert items == [] and total == 0


def test_windowed_run_stores_c_result_verbatim_and_never_rewrites_its_baseline():
    """C: keep the complete result JSON; do not re-round or restate its config."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry()
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository, c_entry=c_entry).run(
            stock_code=STOCK_CODE,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 12, 31),
            parameters=BacktestParametersSchema(),
            parameters_provided=True,
        )

        detail = repository.get(result["backtest_id"])
        assert detail["c_result_available"] is True
        assert detail["c_algorithm_version"] == "ma_long_only_v2.0.0"
        assert detail["c_data_hash"] == C_DATA_HASH
        # C returns ``initial_equity`` as an object, not as the cash number.
        assert detail["c_initial_equity"] == {
            "trade_date": "2025-06-01",
            "equity": 100000.0,
            "valuation": "before_open",
        }
        assert detail["c_warmup"]["required_rows"] == 20
        assert detail["c_data_hash"] != detail["data_meta"]["frame_digest"]
        assert "c_result" not in detail  # full envelope stays opt-in

        full = repository.get(result["backtest_id"], include_c_result=True)
        c_result = full["c_result"]
        assert c_result["algorithm_version"] == "ma_long_only_v2.0.0"
        assert c_result["data_hash"] == C_DATA_HASH
        # C's benchmark identity lives in ``effective_parameters.benchmark_method``;
        # B's QuantConfig default (first_close_to_last_close) must NOT replace it.
        assert (
            c_result["effective_parameters"]["benchmark_method"]
            == "first_open_to_last_close_no_cost"
        )
        # The real envelope has no ``execution_assumptions.baseline`` key at all.
        assert "baseline" not in c_result["execution_assumptions"]
        # The stored "effective parameters" are C's five-field view, not B's.
        assert set(detail["effective_parameters"]) == set(ALLOWED_PARAMETER_FIELDS)


@pytest.mark.parametrize("field", ALLOWED_PARAMETER_FIELDS)
def test_explicit_null_parameter_value_is_rejected_before_any_fetch(field):
    """C: an explicit ``null`` value is invalid; only omission uses the default.

    Regression: ``provided_overrides()`` dropped ``None``, so
    ``{"ma_long_period": null}`` silently became ``{}``, ran on defaults and was
    saved as a success.
    """
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry()
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(InvalidParameterError) as excinfo:
            _service(market, repository, c_entry=c_entry).run(
                stock_code=STOCK_CODE,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 12, 31),
                parameters=BacktestParametersSchema(**{field: None}),
                parameters_provided=True,
            )
        items, total = repository.list()

    assert field in str(excinfo.value)
    assert market.calls == []           # no data was fetched
    assert c_entry.resolve_calls == []  # and C was never called
    assert items == [] and total == 0   # nothing was saved


def test_window_validation_error_from_c_is_reported_as_40001():
    """C's ``BacktestParameterError`` is a ``ValueError``, not an ApplicationError.

    Regression: ``validate_backtest_window`` was called outside the translation
    block, so the error escaped as a plain-text ``500 Internal Server Error``.
    """
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry(
        validate_error=_FakeBacktestParameterError(
            "v2_windowed supports at most five calendar years"
        )
    )
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(InvalidParameterError) as excinfo:
            _service(market, repository, c_entry=c_entry).run(
                stock_code=STOCK_CODE,
                start_date=date(2019, 1, 1),
                end_date=date(2026, 1, 1),
                parameters=BacktestParametersSchema(),
                parameters_provided=True,
            )
        items, total = repository.list()

    assert "at most five calendar years" in str(excinfo.value)
    assert market.calls == []          # window validation still precedes the fetch
    assert items == [] and total == 0


def test_c_insufficient_data_error_is_reported_as_40003():
    """C's ``InsufficientDataError`` maps to ``40003``, not to ``40001``."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry(
        run_error=_FakeInsufficientDataError(
            "no valid daily rows inside the requested window"
        )
    )
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(InsufficientStockDataError):
            _service(market, repository, c_entry=c_entry).run(
                stock_code=STOCK_CODE,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 12, 31),
                parameters=BacktestParametersSchema(),
                parameters_provided=True,
            )
        items, total = repository.list()

    assert items == [] and total == 0


def test_unexpected_c_failure_is_not_disguised_as_a_parameter_error():
    """C: server/wiring failures must stay 500 - never masquerade as ``40001``."""
    market = _FakeMarketSource(_rows())
    c_entry = _FakeCWindowedEntry(run_error=RuntimeError("boom: wiring bug"))
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(RuntimeError):
            _service(market, repository, c_entry=c_entry).run(
                stock_code=STOCK_CODE,
                start_date=date(2025, 6, 1),
                end_date=date(2025, 12, 31),
                parameters=BacktestParametersSchema(),
                parameters_provided=True,
            )
        items, total = repository.list()

    assert items == [] and total == 0


def test_windowed_run_persists_the_c_input_snapshot():
    """C asks for the exact rows handed to their core (warmup included)."""
    market = _FakeMarketSource(_rows())
    start = date(2025, 6, 1)
    end = date(2025, 12, 31)
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository).run(
            stock_code=STOCK_CODE,
            start_date=start,
            end_date=end,
            parameters=BacktestParametersSchema(),
            parameters_provided=True,
        )

        summary = repository.get(result["backtest_id"])
        assert summary["input_snapshot_available"] is True
        # C's snapshot = every window bar + the last ``long`` warmup bars B passed
        # (never all the extra history fetched for window widening).
        meta = result["data_meta"]
        assert summary["input_snapshot_rows"] == meta["rows_in_window"] + min(
            result["warmup_rows"], meta["warmup_required_days"]
        )
        assert summary["input_snapshot_rows"] <= meta["rows"]
        assert "input_snapshot" not in summary  # opt-in only

        detail = repository.get(result["backtest_id"], include_input_snapshot=True)
        snapshot = detail["input_snapshot"]
        assert len(snapshot) == summary["input_snapshot_rows"]
        dates = [row["trade_date"] for row in snapshot]
        assert dates == sorted(dates)  # ascending, as delivered to C
        assert {"stock_code", "trade_date", "open", "high", "low", "close", "volume"} <= set(
            snapshot[0]
        )
        # Only the last ``long`` warmup bars are in the snapshot (not the extra
        # history B fetched to widen the window).
        snapshot_warmup = sum(1 for value in dates if date.fromisoformat(value) < start)
        assert snapshot_warmup == min(result["warmup_rows"], meta["warmup_required_days"])
        assert snapshot_warmup < result["warmup_rows"] or result["warmup_rows"] == meta["warmup_required_days"]


def test_legacy_run_does_not_claim_a_c_input_snapshot():
    """v1_legacy keeps V1 behaviour: no window split, no warmup snapshot."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        result = _service(market, repository).run(
            stock_code=STOCK_CODE, parameters_provided=False
        )
        detail = repository.get(result["backtest_id"])
        assert detail["input_snapshot_available"] is False
        assert detail["input_snapshot_rows"] == 0


def test_windowed_run_rejects_insufficient_warmup_and_saves_nothing():
    market = _FakeMarketSource(_rows(count=120))  # nothing before 2025-05-01
    start = date(2025, 4, 1)
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(InsufficientStockDataError) as excinfo:
            _service(market, repository).run(
                stock_code=STOCK_CODE,
                start_date=start,
                end_date=date(2025, 4, 30),
                parameters=BacktestParametersSchema(ma_long_period=120),
                parameters_provided=True,
            )

        assert "warmup" in str(excinfo.value)
        items, total = repository.list()
        assert total == 0 and items == []


def test_invalid_parameters_are_rejected_before_any_fetch():
    market = _FakeMarketSource(_rows())
    with _session() as session:
        service = _service(market, BacktestRepository(session))
        with pytest.raises(InvalidParameterError):
            service.run(
                stock_code=STOCK_CODE,
                parameters=BacktestParametersSchema(ma_short_period=100, ma_long_period=50),
                parameters_provided=True,
            )
        assert market.calls == []


def test_explicit_null_parameters_are_rejected_before_any_fetch():
    """V2 matrix: omitted -> v1_legacy, {} -> v2_windowed, null -> 40001."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        service = _service(market, BacktestRepository(session))
        with pytest.raises(InvalidParameterError):
            service.run(
                stock_code=STOCK_CODE,
                parameters=None,
                parameters_provided=True,  # the key was present with a null value
            )
        assert market.calls == []


def test_frame_digest_is_order_independent_and_content_sensitive():
    rows = _rows(count=5)
    assert frame_digest(rows) == frame_digest(list(reversed(rows)))
    changed = list(rows)
    changed[0] = changed[0].model_copy(update={"close": 999.0})
    assert frame_digest(rows) != frame_digest(changed)


# -- history ---------------------------------------------------------------


def test_repository_list_filters_paginates_and_orders_newest_first():
    with _session() as session:
        repository = BacktestRepository(session)
        market = _FakeMarketSource(_rows())
        service = _service(market, repository)
        first = service.run(stock_code=STOCK_CODE, parameters_provided=False)["backtest_id"]
        second = service.run(stock_code=STOCK_CODE, parameters_provided=False)["backtest_id"]

        items, total = repository.list(stock_code=STOCK_CODE)
        assert total == 2
        assert [item["backtest_id"] for item in items] == [second, first]

        page, total = repository.list(stock_code=STOCK_CODE, page=2, page_size=1)
        assert total == 2
        assert [item["backtest_id"] for item in page] == [first]

        other, other_total = repository.list(stock_code="000001")
        assert other_total == 0 and other == []


def test_repository_get_unknown_id_raises_not_found():
    with _session() as session:
        with pytest.raises(BacktestNotFoundError):
            BacktestRepository(session).get(987654)


def test_legacy_v1_row_reports_missing_snapshot():
    """A V1 row (summary only) must be labelled, never refilled from today's data."""
    with _session() as session:
        session.add(
            BacktestResult(
                stock_code=STOCK_CODE,
                strategy_name="ma5_ma20_long_only",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 6, 30),
                initial_cash=100000,
                total_return=0.1,
            )
        )
        session.commit()

        detail = BacktestRepository(session).get(1)

        assert detail["snapshot_status"] == SNAPSHOT_MISSING
        assert detail["equity_curve"] == []
        assert "not persisted and are not recomputed" in detail["snapshot_missing_reason"]


# -- API -------------------------------------------------------------------


def _api_client(repository, service):
    app.dependency_overrides[get_backtest_repository] = lambda: repository
    app.dependency_overrides[get_backtest_service] = lambda: service
    return TestClient(app)


def test_api_parameters_flow_creates_and_reads_history():
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        service = _service(market, repository)
        client = _api_client(repository, service)
        try:
            created = client.post(
                "/api/v1/backtests",
                json={
                    "stock_code": STOCK_CODE,
                    "start_date": "2025-06-01",
                    "end_date": "2025-12-31",
                    "parameters": {"ma_long_period": 60, "initial_cash": 200000},
                },
            )
            listed = client.get("/api/v1/backtests", params={"stock_code": STOCK_CODE})
            detail = client.get(f"/api/v1/backtests/{created.json()['data']['backtest_id']}")
            legacy = client.post("/api/v1/backtests", json={"stock_code": STOCK_CODE})
            unknown = client.get("/api/v1/backtests/999999")
            bad = client.post(
                "/api/v1/backtests",
                json={"stock_code": STOCK_CODE, "parameters": {"macd_fast_period": 3}},
            )
        finally:
            app.dependency_overrides.clear()

    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["semantics_version"] == SEMANTICS_V2_WINDOWED
    assert body["effective_parameters"]["initial_cash"] == 200000
    assert body["initial_cash"] == 200000
    assert isinstance(body["backtest_id"], int)

    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1

    assert detail.status_code == 200
    assert detail.json()["data"]["trades"] == body["trades"]
    assert detail.json()["data"]["effective_parameters"]["ma_long_period"] == 60

    # Omitted parameters keep the V1 window/behaviour and are labelled as such.
    assert legacy.status_code == 200
    assert legacy.json()["data"]["semantics_version"] == SEMANTICS_V1_LEGACY

    assert unknown.status_code == 404
    assert unknown.json()["code"] == 40005

    assert bad.status_code == 400
    assert bad.json()["code"] == 40001


def test_api_windowed_backtest_returns_50004_when_c_entry_is_missing():
    """V2 unavailability is explicit on the wire, and no row is created."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        service = _service(market, repository, c_entry=None)
        client = _api_client(repository, service)
        try:
            response = client.post(
                "/api/v1/backtests",
                json={
                    "stock_code": STOCK_CODE,
                    "start_date": "2025-06-01",
                    "end_date": "2025-12-31",
                    "parameters": {},
                },
            )
            items, total = repository.list()
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 500, response.text
    assert response.json()["code"] == 50004
    assert items == [] and total == 0


def test_api_detail_returns_c_result_envelope_only_on_request():
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        service = _service(market, repository)
        client = _api_client(repository, service)
        try:
            created = client.post(
                "/api/v1/backtests",
                json={
                    "stock_code": STOCK_CODE,
                    "start_date": "2025-06-01",
                    "end_date": "2025-12-31",
                    "parameters": {},
                },
            ).json()["data"]
            plain = client.get(
                f"/api/v1/backtests/{created['backtest_id']}"
            ).json()["data"]
            full = client.get(
                f"/api/v1/backtests/{created['backtest_id']}",
                params={"include_c_result": "true"},
            ).json()["data"]
        finally:
            app.dependency_overrides.clear()

    assert plain["c_result_available"] is True
    assert plain["c_data_hash"] == C_DATA_HASH
    assert "c_result" not in plain
    assert full["c_result"]["data_hash"] == C_DATA_HASH


def test_api_explicit_null_parameter_returns_json_40001_and_saves_nothing():
    """Regression: ``{"ma_long_period": null}`` used to return 200 and persist."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        service = _service(market, repository)
        client = _api_client(repository, service)
        try:
            response = client.post(
                "/api/v1/backtests",
                json={
                    "stock_code": STOCK_CODE,
                    "start_date": "2025-06-01",
                    "end_date": "2025-12-31",
                    "parameters": {"ma_long_period": None},
                },
            )
            items, total = repository.list()
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
    assert response.json()["code"] == 40001
    assert items == [] and total == 0


def test_api_reports_c_window_validation_as_json_40001():
    """Regression: this used to surface as plain-text ``500 Internal Server Error``."""
    market = _FakeMarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        c_entry = _FakeCWindowedEntry(
            validate_error=_FakeBacktestParameterError("window too long")
        )
        service = _service(market, repository, c_entry=c_entry)
        client = _api_client(repository, service)
        try:
            response = client.post(
                "/api/v1/backtests",
                json={
                    "stock_code": STOCK_CODE,
                    "start_date": "2019-01-01",
                    "end_date": "2026-01-01",
                    "parameters": {},
                },
            )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 400, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["code"] == 40001
