# -*- coding: utf-8 -*-
"""B1: the field set F3 (same-stock, two-saved-backtest comparison) depends on.

Issue #20 §3 published this table for A. Prose can drift, so the table is asserted
here instead: the **default** ``GET /backtests/{id}`` projection must carry every field
F3 needs - without ``include_c_result=true`` - and a legacy record must report its
missing snapshot rather than fabricate one.

The comparison view is read-only: nothing here recomputes an indicator, refetches
market data or calls the LLM.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.migrations import apply_migrations
from backend.app.models.backtest_result import BacktestResult
from backend.app.services.backtest_service import BacktestRepository

STOCK_CODE = "600519"
C_ALGORITHM_VERSION = "ma_long_only_v2.0.0"
C_DATA_HASH = "c" * 64
FRAME_DIGEST = "f" * 64

#: F3's identifier / strategy / metric block: present on every saved record.
F3_ALWAYS_FIELDS = {
    "backtest_id",
    "stock_code",
    "created_at",
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
    "c_result_available",
    "c_result_exact",
    # the read-only containers F3 renders from
    "strategy_version",
    "warmup_start_date",
    "parameters",
    "effective_parameters",
    "equity_curve",
    "benchmark_curve",
    "drawdown_curve",
    "trades",
    "data_meta",
}

#: F3's execution-semantics block, reached through ``data_meta`` / the C projection.
F3_DATA_META_FIELDS = {
    "requested_start_date",
    "requested_end_date",
    "warmup_rows",
    "warmup_required_days",
    "data_source",
    "frame_digest",  # B's digest of the frame handed to C
    "c_data_hash",  # C's *input snapshot* hash - a different object from the above
    "computed_start_date",
    "computed_end_date",
}


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return Session(bind=engine)


def _save_windowed(session: Session) -> int:
    repository = BacktestRepository(session)
    first_day = "2025-06-03"
    data_meta = {
        "semantics_version": "v2_windowed",
        "requested_start_date": "2025-06-01",
        "requested_end_date": "2025-12-31",
        "warmup_start_date": "2025-05-01",
        "warmup_rows": 20,
        "warmup_required_days": 20,
        "data_source": "MarketDataSource.query_daily (warmup window)",
        "frame_digest": FRAME_DIGEST,
        "c_data_hash": C_DATA_HASH,
        "computed_start_date": first_day,
        "computed_end_date": "2025-12-31",
    }
    result = {
        "strategy_name": "ma_long_only",
        "semantics_version": "v2_windowed",
        "strategy_version": "v2.0.0",
        "start_date": first_day,
        "end_date": "2025-12-31",
        "initial_cash": 100000.0,
        "final_equity": 118000.0,
        "total_return": 0.18,
        "annual_return": 0.22,
        "max_drawdown": -0.05,
        "sharpe_ratio": 1.2,
        "win_rate": 0.5,
        "trade_count": 3,
        "order_count": 6,
        "benchmark_return": 0.19,
        "warmup_start_date": "2025-05-01",
        "warmup_rows": 20,
        "equity_curve": [{"trade_date": first_day, "equity": 100000.0}],
        "benchmark_curve": [{"trade_date": first_day, "benchmark_equity": 100000.0}],
        "drawdown_curve": [{"trade_date": first_day, "drawdown": 0.0}],
        "trades": [{"order_id": 1, "side": "buy"}],
        "data_meta": data_meta,
    }
    return repository.save(
        stock_code=STOCK_CODE,
        result=result,
        semantics_version="v2_windowed",
        effective_parameters={
            "ma_short_period": 5,
            "ma_long_period": 20,
            "initial_cash": 100000.0,
            "transaction_cost": 0.001,
            "slippage": 0.0,
        },
        warmup_start_date=date(2025, 5, 1),
        data_meta=data_meta,
        strategy_version="v2.0.0",
        c_result={"algorithm_version": C_ALGORITHM_VERSION, "data_hash": C_DATA_HASH},
    )


def test_default_detail_carries_every_field_f3_needs():
    with _session() as session:
        repository = BacktestRepository(session)
        backtest_id = _save_windowed(session)
        detail = repository.get(backtest_id)

    assert not (F3_ALWAYS_FIELDS - set(detail)), "F3 fields missing from the default detail"
    assert not (F3_DATA_META_FIELDS - set(detail["data_meta"])), "data_meta is incomplete"

    # Real values, not placeholders: both hashes are distinct objects and both survive.
    assert detail["snapshot_status"] == "complete"
    assert detail["data_meta"]["frame_digest"] == FRAME_DIGEST
    assert detail["data_meta"]["c_data_hash"] == C_DATA_HASH
    assert detail["c_algorithm_version"] == C_ALGORITHM_VERSION
    assert detail["equity_curve"] and detail["benchmark_curve"] and detail["drawdown_curve"]
    assert detail["trades"] == [{"order_id": 1, "side": "buy"}]
    assert {"transaction_cost", "slippage", "initial_cash"} <= set(
        detail["effective_parameters"]
    )

    # F3 must be able to compare without pulling C's whole payload: the expensive field
    # stays opt-in (`include_c_result=true`), which is what keeps the compare view read-only.
    assert "c_result" not in detail


def test_legacy_record_reports_its_missing_snapshot_instead_of_fabricating_one():
    with _session() as session:
        row = BacktestResult(
            stock_code=STOCK_CODE,
            strategy_name="legacy_v1",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            initial_cash=100000.0,
            total_return=0.1,
        )
        session.add(row)
        session.commit()
        detail = BacktestRepository(session).get(int(row.id))

    assert detail["snapshot_status"] == "missing"
    # Missing stays missing: no curves, no warmup, no version, no C projection.
    assert detail["equity_curve"] == []
    assert detail["benchmark_curve"] == []
    assert detail["drawdown_curve"] == []
    assert detail["trades"] == []
    assert detail["warmup_start_date"] is None
    assert detail["strategy_version"] is None
    assert detail["data_meta"] == {}
    assert detail["c_result_available"] is False
    assert detail["c_result_exact"] is False
    assert "c_algorithm_version" not in detail
    # F3 renders this reason, so it must be present and explicit.
    assert detail["snapshot_missing_reason"]


def test_requested_actual_and_computed_dates_are_three_distinct_things():
    """A's mapping (C, PR #23 review): request info is not the actual trading window.

    C measured that a request spanning non-trading days (2025-07-05..2026-08-30) comes
    back with actual 2025-07-07..2025-08-28. The contract is:

    * ``data_meta.requested_start_date`` / ``requested_end_date`` - what the caller asked
      for, reported as asked and never silently rewritten;
    * top-level ``start_date`` / ``end_date`` - the actual first/last bars used, equal to
      ``data_meta.computed_start_date`` / ``computed_end_date``;
    * there is **no** ``actual_*`` field anywhere, so reading one yields nothing - which is
      how A's compare view ended up rendering an empty actual window. B adds no second
      field family for this (C: "B 无需新增另一套字段").
    """
    with _session() as session:
        repository = BacktestRepository(session)
        detail = repository.get(_save_windowed(session))

    meta = detail["data_meta"]
    assert meta["requested_start_date"] == "2025-06-01"  # asked for
    assert detail["start_date"] == "2025-06-03"  # actually used
    assert meta["computed_start_date"] == detail["start_date"]
    assert meta["computed_end_date"] == detail["end_date"]
    assert meta["requested_start_date"] != detail["start_date"]
    # The whole "actual_*" family is absent, by design.
    assert not [key for key in detail if key.startswith("actual_")]
    assert not [key for key in meta if key.startswith("actual_")]
