# -*- coding: utf-8 -*-
"""Regression tests for lossless ``c_result`` storage (migration v8).

C reproduced on real MySQL that a ``JSON`` column cannot hold C's envelope exactly:
``SELECT CAST('{"number":99633.35582084299}' AS JSON)`` comes back as
``99633.355820843``. Across nine saved runs every one of 1439 numeric leaves moved by
1 ULP (max abs difference ~2.91e-11), so the "store C's result verbatim" contract was
not met even though the visible numbers barely change.

Storage therefore moved to ``c_result_text`` (LONGTEXT): ``json.dumps`` emits the
shortest string that round-trips a float, so the exact bytes survive and the API
parses them back into the same object shape. Rows saved before v8 stay readable from
the legacy JSON column and are flagged via ``c_result_exact``.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db import migrations
from backend.app.db.migrations import apply_migrations
from backend.app.models.backtest_result import BacktestResult
from backend.app.services.backtest_service import BacktestRepository

STOCK = "600519"


def _engine_and_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return engine, Session(bind=engine)


def _result() -> dict:
    return {
        "strategy_name": "ma_long_only",
        "start_date": "2025-07-04",
        "end_date": "2025-12-31",
        "initial_cash": 100000.0,
        "final_equity": 111544.9,
    }


def _envelope() -> dict:
    """Numbers chosen to break any ~15-significant-digit normalisation."""
    return {
        "algorithm_version": "ma_long_only_v2.0.0",
        "semantics_version": "v2_windowed",
        "initial_equity": {
            "trade_date": "2025-07-04",
            "equity": 99633.35582084299,
            "valuation": "before_open",
        },
        "equity_curve": [
            {"trade_date": "2025-07-04", "equity": 99633.35582084299},
            {"trade_date": "2025-07-05", "equity": 99996.80861249114},
        ],
        "benchmark_curve": [
            {"trade_date": "2025-07-04", "benchmark_equity": 100032.28931223766}
        ],
        "warmup": {"required_rows": 20, "used_rows": 44},
        "execution_assumptions": {"benchmark_includes_costs": False},
        "data_hash": "2337f38a1443e0be81cb26b5e5dc3dd15deb560630b7d7ef94b04ca6f0c43988",
        "tiny": 2.9103830456733704e-11,
    }


# -- exact round-trip ---------------------------------------------------------


def test_c_result_round_trips_leaf_for_leaf_through_the_text_column():
    engine, session = _engine_and_session()
    envelope = _envelope()
    with session:
        repository = BacktestRepository(session)
        backtest_id = repository.save(
            stock_code=STOCK,
            result=_result(),
            semantics_version="v2_windowed",
            effective_parameters={"ma_long_period": 20},
            warmup_start_date=date(2025, 5, 21),
            data_meta={},
            c_result=envelope,
        )
        detail = repository.get(backtest_id)
        full = repository.get(backtest_id, include_c_result=True)

        stored_text = session.execute(
            text("SELECT c_result_text FROM backtest_result WHERE id = :id"), {"id": backtest_id}
        ).scalar()

    assert detail["c_result_available"] is True
    assert detail["c_result_exact"] is True
    assert full["c_result"] == envelope  # exact, every leaf
    assert full["c_result"]["initial_equity"]["equity"] == 99633.35582084299
    assert full["c_result"]["tiny"] == 2.9103830456733704e-11

    # The stored bytes are the compact JSON text and parse back identically.
    assert json.loads(stored_text) == envelope
    assert "99633.35582084299" in stored_text


def test_new_rows_do_not_write_the_lossy_json_column():
    engine, session = _engine_and_session()
    with session:
        repository = BacktestRepository(session)
        backtest_id = repository.save(
            stock_code=STOCK,
            result=_result(),
            semantics_version="v2_windowed",
            effective_parameters={},
            warmup_start_date=None,
            data_meta={},
            c_result=_envelope(),
        )
        legacy = session.execute(
            text("SELECT c_result FROM backtest_result WHERE id = :id"), {"id": backtest_id}
        ).scalar()

    assert legacy is None


def test_saving_without_a_c_result_leaves_both_columns_null():
    engine, session = _engine_and_session()
    with session:
        repository = BacktestRepository(session)
        backtest_id = repository.save(
            stock_code=STOCK,
            result=_result(),
            semantics_version="v1_legacy",
            effective_parameters={},
            warmup_start_date=None,
            data_meta={},
        )
        detail = repository.get(backtest_id)
        stored = session.execute(
            text("SELECT c_result_text, c_result FROM backtest_result WHERE id = :id"),
            {"id": backtest_id},
        ).one()

    assert stored == (None, None)
    assert detail["c_result_available"] is False
    assert detail["c_result_exact"] is False


# -- legacy rows --------------------------------------------------------------


def test_legacy_json_row_is_readable_but_flagged_inexact():
    engine, session = _engine_and_session()
    with session:
        row = BacktestResult(
            stock_code=STOCK,
            strategy_name="legacy",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            c_result={"algorithm_version": "legacy-v1", "equity": 1.0},
        )
        session.add(row)
        session.commit()
        repository = BacktestRepository(session)
        detail = repository.get(int(row.id))
        full = repository.get(int(row.id), include_c_result=True)

    assert detail["c_result_available"] is True
    assert detail["c_result_exact"] is False
    assert full["c_result"]["algorithm_version"] == "legacy-v1"


# -- migration ----------------------------------------------------------------


def test_migration_v8_adds_the_column_backfills_and_is_idempotent():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)

    # A database created by the ORM metadata already carries the new column, but a
    # database *upgraded* from v7 does not - drop it to reproduce that shape, and
    # insert a legacy row through raw SQL because the ORM no longer knows a
    # pre-v8 table.
    payload = {"algorithm_version": "pre-v8", "equity": 1.0}
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE backtest_result DROP COLUMN c_result_text"))
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(stock_code, strategy_name, start_date, end_date, c_result) "
                "VALUES ('600519', 'pre-v8', '2026-01-01', '2026-01-02', :payload)"
            ),
            {"payload": json.dumps(payload)},
        )

    with engine.begin() as connection:
        migrations._migration_v8(connection)
        migrations._migration_v8(connection)  # a second pass must be a no-op

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT c_result_text FROM backtest_result")).scalar()

    assert json.loads(stored) == payload


def test_legacy_row_upgraded_by_v8_still_reports_exact_false():
    """C's chained path: a v7 JSON row, upgraded, read back in a NEW session.

    The two halves were covered separately before - "an old row reads as inexact"
    inserted *after* the migration, and "v8 backfills text" - which missed the path
    where the backfilled text makes an old row look exact.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)

    payload = {"algorithm_version": "pre-v8", "equity": 99633.35582084299}
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE backtest_result DROP COLUMN c_result_text"))
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(stock_code, strategy_name, start_date, end_date, c_result) "
                "VALUES ('600519', 'pre-v8', '2026-01-01', '2026-01-02', :payload)"
            ),
            {"payload": json.dumps(payload)},
        )

    # Upgrade through the documented entry point, then read in a fresh session.
    apply_migrations(engine)
    with Session(bind=engine) as session:
        detail = BacktestRepository(session).get(1)
        full = BacktestRepository(session).get(1, include_c_result=True)

    assert detail["c_result_available"] is True
    assert detail["c_result_exact"] is False  # backfilled from the normalised JSON
    assert full["c_result"] == payload

    # A repeated migration must not change the verdict.
    apply_migrations(engine)
    with Session(bind=engine) as session:
        again = BacktestRepository(session).get(1)

    assert again["c_result_exact"] is False


def test_schema_version_is_eight():
    assert migrations.SCHEMA_VERSION == 8
