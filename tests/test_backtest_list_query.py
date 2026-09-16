# -*- coding: utf-8 -*-
"""Regression tests for the backtest-list projection fix.

C reproduced ``HTTP 500 / 50002`` on the combined branch with nine realistic
records: ``GET /api/v1/backtests`` returned ``1038 Out of sort memory`` because
``BacktestRepository.list`` selected the **whole row** - including ``equity_curve``,
``benchmark_curve``, ``drawdown_curve``, ``orders``, ``input_snapshot`` and
``c_result`` (~150 KB per row) - and then filesorted it against a 256 KB
``sort_buffer_size``.

The fix projects only the scalar summary columns and derives ``snapshot_status``
in SQL, so the curve JSON is never fetched and never enters the sort buffer.
These tests pin that shape on SQLite; the real-MySQL run is recorded separately.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.migrations import apply_migrations
from backend.app.models.backtest_result import BacktestResult
from backend.app.services.backtest_service import (
    SNAPSHOT_COMPLETE,
    SNAPSHOT_MISSING,
    BacktestRepository,
)

STOCK = "600519"
#: Columns whose values are large JSON and must never be projected by ``list``.
BIG_JSON_COLUMNS = (
    "c_result",
    "input_snapshot",
    "orders",
    "benchmark_curve",
    "drawdown_curve",
)


def _engine_and_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return engine, Session(bind=engine)


def _add(
    session,
    *,
    stock: str = STOCK,
    equity_curve=None,
    created_at=None,
    strategy_name: str = "row",
):
    row = BacktestResult(
        stock_code=stock,
        strategy_name=strategy_name,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        initial_cash=100000,
        equity_curve=equity_curve,
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    session.commit()
    return row


def _select_statements(engine, call) -> list:
    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        captured.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    return captured


# -- projection ---------------------------------------------------------------


def test_list_projection_excludes_every_large_json_column():
    engine, session = _engine_and_session()
    with session:
        _add(session, equity_curve=[{"trade_date": "2026-01-01", "equity": 1.0}])
        statements = _select_statements(
            engine, lambda: BacktestRepository(session).list(page=1, page_size=20)
        )

    select_sql = next(
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "count(" not in statement.lower()
    )
    head = select_sql.split("FROM")[0]

    for name in BIG_JSON_COLUMNS:
        assert f"backtest_result.{name}" not in head, name
    # ``equity_curve`` may only appear inside the status expression.
    assert "json_array_length(backtest_result.equity_curve)" in head


def test_list_issues_exactly_two_queries_and_never_lazy_loads():
    """One COUNT plus one projected SELECT - a lazy load would add a third."""
    engine, session = _engine_and_session()
    with session:
        for index in range(3):
            _add(session, equity_curve=[{"equity": index}], strategy_name=f"row{index}")
        statements = _select_statements(
            engine, lambda: BacktestRepository(session).list(page=1, page_size=20)
        )

    assert len(statements) == 2, statements


# -- snapshot_status covers all four states -----------------------------------


def test_list_snapshot_status_covers_null_json_null_empty_and_non_empty():
    engine, session = _engine_and_session()
    with session:
        _add(session, equity_curve=None, strategy_name="SQL NULL")
        _add(session, equity_curve=JSON.NULL, strategy_name="JSON null")
        _add(session, equity_curve=[], strategy_name="empty array")
        _add(
            session,
            equity_curve=[{"trade_date": "2026-01-01", "equity": 1.0}],
            strategy_name="non-empty array",
        )

        items, total = BacktestRepository(session).list(stock_code=STOCK, page=1, page_size=10)

    assert total == 4
    status = {item["strategy_name"]: item["snapshot_status"] for item in items}
    assert status == {
        "SQL NULL": SNAPSHOT_MISSING,
        "JSON null": SNAPSHOT_MISSING,
        "empty array": SNAPSHOT_MISSING,
        "non-empty array": SNAPSHOT_COMPLETE,
    }


# -- filter / order / pagination semantics unchanged ---------------------------


def test_list_keeps_filter_order_and_pagination_semantics():
    engine, session = _engine_and_session()
    base = date(2026, 1, 1)
    with session:
        for index in range(5):
            _add(
                session,
                equity_curve=[{"equity": index}],
                created_at=base + timedelta(days=index),
                strategy_name=f"row{index}",
            )
        _add(session, stock="000001", equity_curve=[{"equity": 9}], strategy_name="other")

        repository = BacktestRepository(session)
        page1, total = repository.list(stock_code=STOCK, page=1, page_size=2)
        page2, _ = repository.list(stock_code=STOCK, page=2, page_size=2)
        page3, _ = repository.list(stock_code=STOCK, page=3, page_size=2)
        other, other_total = repository.list(stock_code="999999", page=1, page_size=10)

    assert total == 5
    ids = [item["backtest_id"] for item in page1 + page2 + page3]
    assert len(ids) == 5
    assert len(set(ids)) == 5  # pages do not overlap or drop rows
    assert ids == sorted(ids, reverse=True)  # newest first, stable
    assert other_total == 0 and other == []


def test_list_summary_shape_is_unchanged():
    engine, session = _engine_and_session()
    with session:
        _add(session, equity_curve=[{"equity": 1.0}])
        items, _ = BacktestRepository(session).list(page=1, page_size=10)

    assert set(items[0]) == {
        "backtest_id",
        "stock_code",
        "strategy_name",
        "semantics_version",
        "start_date",
        "end_date",
        "initial_cash",
        "final_equity",
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "trade_count",
        "order_count",
        "benchmark_return",
        "snapshot_status",
        "created_at",
    }


# -- the detail path still loads everything -----------------------------------


def test_detail_still_returns_curves_and_the_c_result_envelope():
    engine, session = _engine_and_session()
    curve = [{"trade_date": "2026-01-01", "equity": 100000.0}]
    with session:
        row = BacktestResult(
            stock_code=STOCK,
            strategy_name="detail",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            initial_cash=100000,
            equity_curve=curve,
            benchmark_curve=[{"trade_date": "2026-01-01", "benchmark_equity": 1.0}],
            drawdown_curve=[{"trade_date": "2026-01-01", "drawdown": 0.0}],
            orders=[{"order_id": 1}],
            input_snapshot=[{"trade_date": "2026-01-01"}],
            c_result={"algorithm_version": "ma_long_only_v2.0.0", "data_hash": "abc"},
        )
        session.add(row)
        session.commit()
        backtest_id = int(row.id)

        repository = BacktestRepository(session)
        detail = repository.get(backtest_id)
        full = repository.get(backtest_id, include_c_result=True)

    assert detail["equity_curve"] == curve
    assert len(detail["trades"]) == 1
    assert detail["snapshot_status"] == SNAPSHOT_COMPLETE
    assert detail["c_result_available"] is True
    assert full["c_result"]["data_hash"] == "abc"
