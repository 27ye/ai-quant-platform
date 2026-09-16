"""Idempotent, step-based schema migrations.

V1 shipped ``create_all`` plus a version row, which cannot ALTER an existing
table. V2 turns this into an explicit ordered migration list: every step runs
in its own transaction and its version row is written **only after the step
succeeded**, so a partially applied migration can be re-run safely and never
pretends to be complete.

``schema_version`` is created with raw SQL rather than an ORM model, so it does
not appear in ``Base.metadata.tables``.
"""

from __future__ import annotations

from typing import Callable, List, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

import backend.app.models  # noqa: F401  (register all ORM models on Base)
from backend.app.db.base import Base

#: Current schema revision. Bump only when a new migration step is added below.
SCHEMA_VERSION = 7

_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " version INT NOT NULL PRIMARY KEY,"
    " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
)

# Mirrors ``backend.app.models.stock_catalog_sync.StockCatalogSync``; kept as
# raw DDL so an existing V1 database can be upgraded without create_all.
_STOCK_CATALOG_SYNC_DDL = (
    "CREATE TABLE IF NOT EXISTS stock_catalog_sync ("
    " id INT NOT NULL PRIMARY KEY,"
    " status VARCHAR(20) NOT NULL,"
    " last_success_at DATETIME NULL,"
    " last_attempt_at DATETIME NOT NULL,"
    " row_count INT NOT NULL DEFAULT 0,"
    " source VARCHAR(200) NULL,"
    " last_error VARCHAR(500) NULL)"
)


def get_schema_version(bind: Engine) -> int:
    """Return the highest applied schema version (0 on a fresh database)."""
    with bind.begin() as connection:
        connection.execute(text(_SCHEMA_VERSION_DDL))
        row = connection.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar()
        return int(row) if row is not None else 0


def _migration_v1(connection: Connection) -> None:
    """V1 baseline: create the six core tables registered on ``Base.metadata``."""
    Base.metadata.create_all(bind=connection, checkfirst=True)


def _migration_v2(connection: Connection) -> None:
    """V2: local stock catalog bookkeeping (search stops calling the provider)."""
    connection.execute(text(_STOCK_CATALOG_SYNC_DDL))


# Mirrors ``backend.app.models.stock_daily_sync.StockDailySync``.
_STOCK_DAILY_SYNC_DDL = (
    "CREATE TABLE IF NOT EXISTS stock_daily_sync ("
    " stock_code VARCHAR(10) NOT NULL PRIMARY KEY,"
    " mode VARCHAR(20) NOT NULL,"
    " source VARCHAR(200) NULL,"
    " row_count INT NOT NULL DEFAULT 0,"
    " first_trade_date DATE NULL,"
    " last_trade_date DATE NULL,"
    " last_success_at DATETIME NULL,"
    " last_attempt_at DATETIME NOT NULL,"
    " last_error VARCHAR(500) NULL)"
)


def _migration_v3(connection: Connection) -> None:
    """V2 B2: per-stock daily-bar provenance for the data-status endpoint."""
    connection.execute(text(_STOCK_DAILY_SYNC_DDL))


#: Columns V2 B3 adds to the existing ``backtest_result`` table. ``create_all``
#: cannot alter an existing table, so an explicit, idempotent ALTER is required
#: for databases created by V1.
_V4_BACKTEST_COLUMNS = (
    ("semantics_version", "VARCHAR(20) NULL"),
    ("strategy_version", "VARCHAR(20) NULL"),
    ("final_equity", "DECIMAL(20, 2) NULL"),
    ("order_count", "INT NULL"),
    ("warmup_start_date", "DATE NULL"),
    ("equity_curve", "JSON NULL"),
    ("benchmark_curve", "JSON NULL"),
    ("drawdown_curve", "JSON NULL"),
    ("orders", "JSON NULL"),
    ("effective_parameters", "JSON NULL"),
    ("data_meta", "JSON NULL"),
)


def _add_missing_columns(connection: Connection, table: str, columns) -> None:
    """Add only the columns that are actually absent (portable + re-runnable).

    Creates the table from the ORM metadata first when it does not exist yet, so
    a step stays correct even if an earlier version row was recorded by a
    different branch (version numbers are not a reliable description of content).
    """
    inspector = inspect(connection)
    if not inspector.has_table(table):
        Base.metadata.tables[table].create(bind=connection, checkfirst=True)
    existing = {column["name"] for column in inspect(connection).get_columns(table)}
    for name, ddl_type in columns:
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def _migration_v4(connection: Connection) -> None:
    """V2 B3: saved backtest snapshots (curves/orders) so history never recomputes."""
    _add_missing_columns(connection, "backtest_result", _V4_BACKTEST_COLUMNS)


#: AI report-snapshot columns for V2 (fields specified by D, migration owned by B).
_V5_AI_ANALYSIS_COLUMNS = (
    ("context_snapshot", "JSON NULL"),
    ("context_hash", "CHAR(64) NULL"),
    ("source_mode", "VARCHAR(16) NULL"),
    ("data_as_of", "DATETIME NULL"),
    ("prompt_version", "VARCHAR(32) NULL"),
    ("context_schema_version", "VARCHAR(32) NULL"),
    ("output_schema_version", "VARCHAR(32) NULL"),
)


def _migration_v5(connection: Connection) -> None:
    """V2 D1: AI report snapshot/provenance columns on ``ai_analysis``."""
    _add_missing_columns(connection, "ai_analysis", _V5_AI_ANALYSIS_COLUMNS)


def _migration_v6(connection: Connection) -> None:
    """V2 C 对接: persist the exact input rows handed to C (warmup included)."""
    _add_missing_columns(
        connection, "backtest_result", (("input_snapshot", "JSON NULL"),)
    )


def _migration_v7(connection: Connection) -> None:
    """V2 C 对接: keep C's complete ``run_backtest_request`` result verbatim.

    C (PR #10 review): "建议原样保存 C 完整结果 JSON，历史详情从该快照读取，不用
    舍入后的摘要列重新拼装". The summary columns stay for list queries, but they are
    B's rounding of C's numbers; ``c_result`` is what C actually returned, so
    ``algorithm_version`` / ``warmup`` / ``initial_equity`` / ``execution_assumptions``
    / the ``input_snapshot`` envelope / ``data_hash`` all survive the round trip.
    """
    _add_missing_columns(connection, "backtest_result", (("c_result", "JSON NULL"),))


#: Ordered ``(version, step)`` pairs. Append new steps; never reorder.
#: Every step must be idempotent and artifact-based (create-if-missing /
#: add-column-if-missing): the convergence pass in :func:`apply_migrations`
#: re-runs them, so a database whose version rows disagree with its actual
#: artifacts (e.g. two branches that both used "v2" for different content)
#: still ends up with the complete schema instead of silently missing a table.
MIGRATIONS: List[Tuple[int, Callable[[Connection], None]]] = [
    (1, _migration_v1),
    (2, _migration_v2),
    (3, _migration_v3),
    (4, _migration_v4),
    (5, _migration_v5),
    (6, _migration_v6),
    (7, _migration_v7),
]


def apply_migrations(bind: Engine) -> int:
    """Apply every pending step, then converge the schema, and return the version.

    Each step is transactional: if it raises, its version row is not written and
    the caller sees the error, so re-running resumes from the failed step.
    Afterwards every step runs once more in a single pass. Because the steps only
    ever create missing artifacts, that pass is a no-op on an already-correct
    database and a repair on a mismatched one.
    """
    current = get_schema_version(bind)
    for version, step in MIGRATIONS:
        if version <= current:
            continue
        with bind.begin() as connection:
            step(connection)
            connection.execute(
                text("INSERT INTO schema_version (version) VALUES (:version)"),
                {"version": version},
            )

    with bind.begin() as connection:
        for _version, step in MIGRATIONS:
            step(connection)

    return SCHEMA_VERSION
