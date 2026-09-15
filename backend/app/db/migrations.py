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

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

import backend.app.models  # noqa: F401  (register all ORM models on Base)
from backend.app.db.base import Base

#: Current schema revision. Bump only when a new migration step is added below.
SCHEMA_VERSION = 2

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


#: Ordered ``(version, step)`` pairs. Append new steps; never reorder.
MIGRATIONS: List[Tuple[int, Callable[[Connection], None]]] = [
    (1, _migration_v1),
    (2, _migration_v2),
]


def apply_migrations(bind: Engine) -> int:
    """Apply every pending step in order and return the resulting version.

    Each step is transactional: if it raises, its version row is not written and
    the caller sees the error, so re-running resumes from the failed step.
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
    return SCHEMA_VERSION
