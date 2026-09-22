# -*- coding: utf-8 -*-
"""V3 F5 integration: B's strategy wiring against the **real** C entry in this tree.

The unit tests in ``test_backtest_service.py`` inject fakes, so they cannot show that
B's new call arity still matches C's *actual* published entry points, nor that the
feature-detect reports the right thing on a tree where C's MACD contract has not
landed yet. These tests use ``load_c_windowed_entry()`` unchanged.

They are written to hold on **both** trees: while C's V3 entry is absent, ``macd``
must be refused; once it lands, the support flag flips and the refusal case skips
instead of silently passing.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.core.errors import BacktestError
from backend.app.db.migrations import apply_migrations
from backend.app.models.backtest_result import BacktestResult
from backend.app.schemas.backtest import BacktestParametersSchema
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.backtest_service import (
    SEMANTICS_V2_WINDOWED,
    BacktestRepository,
    BacktestService,
)
from backend.app.services.c_quant_entry import load_c_windowed_entry
from backend.app.services.quant_service import QuantService
from backend.app.services.stock_service import StockService

STOCK_CODE = "600519"
WINDOW = {"start_date": date(2025, 6, 1), "end_date": date(2025, 12, 31)}
MA_FIELDS = {
    "ma_short_period",
    "ma_long_period",
    "initial_cash",
    "transaction_cost",
    "slippage",
}


def _rows(count: int = 400) -> list:
    rows = []
    start = date(2025, 1, 1)
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


class _MarketSource:
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


class _UnusedProvider:
    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("provider must not be called on the windowed path")


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return Session(bind=engine)


def _service(market, repository) -> BacktestService:
    return BacktestService(
        quant_service=QuantService(
            stock_service=StockService(provider=_UnusedProvider()),
            market_data_source=market,
        ),
        market_data_source=market,
        repository=repository,
        today=lambda: date(2026, 6, 1),
        c_entry_loader=load_c_windowed_entry,  # the REAL loader, never a fake
    )


def test_feature_detect_matches_the_real_entry_signatures():
    """B's ``supports_strategy`` must reflect what C's callables actually accept."""
    from backend.app.quant import resolve_backtest_request, run_backtest_request

    entry = load_c_windowed_entry()
    assert entry is not None  # C's V2 entry is part of main

    accepts = (
        "strategy" in inspect.signature(resolve_backtest_request).parameters
        and "strategy" in inspect.signature(run_backtest_request).parameters
    )
    if entry.strategy_unset is None:
        assert not accepts, "C exposes STRATEGY_UNSET but B failed to import it"
    assert entry.supports_strategy == (accepts and entry.strategy_unset is not None)


def test_real_ma_request_runs_through_the_real_c_entry():
    """The V2 MA path must keep working with B's new call arity (no strategy sent)."""
    market = _MarketSource(_rows())
    with _session() as session:
        result = _service(market, BacktestRepository(session)).run(
            stock_code=STOCK_CODE,
            parameters=BacktestParametersSchema(ma_long_period=20),
            parameters_provided=True,
            **WINDOW,
        )

    assert result["semantics_version"] == SEMANTICS_V2_WINDOWED
    assert result["strategy_name"] == "ma_long_only"
    assert set(result["effective_parameters"]) == MA_FIELDS


def test_real_tree_treats_ma_cross_as_the_existing_ma_implementation():
    """C's matrix: ``ma_cross`` is the existing MA implementation, on every tree."""
    market = _MarketSource(_rows())
    with _session() as session:
        result = _service(market, BacktestRepository(session)).run(
            stock_code=STOCK_CODE,
            parameters=BacktestParametersSchema(ma_long_period=20),
            parameters_provided=True,
            strategy="ma_cross",
            strategy_provided=True,
            **WINDOW,
        )

    assert result["semantics_version"] == SEMANTICS_V2_WINDOWED
    assert result["strategy_name"] == "ma_long_only"


def test_real_tree_refuses_macd_until_c_accepts_strategy():
    """Never run MA under a ``macd`` label: refuse, fetch nothing, persist nothing."""
    if load_c_windowed_entry().supports_strategy:
        pytest.skip("C's V3 entry accepts strategy; this tree can run macd for real")

    market = _MarketSource(_rows())
    with _session() as session:
        repository = BacktestRepository(session)
        with pytest.raises(BacktestError, match="macd backtest is unavailable"):
            _service(market, repository).run(
                stock_code=STOCK_CODE,
                strategy="macd",
                strategy_provided=True,
                **WINDOW,
            )
        assert session.query(BacktestResult).count() == 0

    assert market.calls == []  # refused before any data fetch
