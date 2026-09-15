"""Idempotent schema bootstrap and incremental migrations.

The ORM models in ``backend.app.models`` mirror ``docs/DATABASE_DESIGN.md``.
This module creates those tables (and a dedicated ``schema_version`` tracker)
without requiring a full migration framework for the V1 phase.

``schema_version`` is intentionally created with raw SQL rather than an ORM
model, so it does not appear in ``Base.metadata.tables`` (which the test suite
asserts contains exactly the six V1 tables).
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

import backend.app.models  # noqa: F401  (register all six ORM models on Base)
from backend.app.db.base import Base

#: Current schema revision. Bump only when a new migration is added below.
SCHEMA_VERSION = 2

_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " version INT NOT NULL PRIMARY KEY,"
    " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
)


def get_schema_version(bind: Engine) -> int:
    """Return the highest applied schema version (0 on a fresh database)."""
    with bind.begin() as connection:
        connection.execute(text(_SCHEMA_VERSION_DDL))
        row = connection.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar()
        return int(row) if row is not None else 0


_AI_ANALYSIS_V2_COLUMNS = {
    "context_snapshot": "JSON NULL",
    "context_hash": "CHAR(64) NULL",
    "source_mode": "VARCHAR(16) NULL",
    "data_as_of": "DATETIME NULL",
    "prompt_version": "VARCHAR(32) NULL",
    "context_schema_version": "VARCHAR(32) NULL",
    "output_schema_version": "VARCHAR(32) NULL",
}


def _record_version(bind: Engine, version: int) -> None:
    with bind.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_version (version) VALUES (:version)"),
            {"version": version},
        )


def _apply_v2(bind: Engine) -> None:
    """Add nullable report-snapshot fields to an existing V1 database.

    Each column is checked independently. This also makes recovery safe when a
    MySQL DDL statement committed before a later statement failed: rerunning the
    migration only applies the still-missing columns, and version 2 is recorded
    after every column exists.
    """
    existing = {column["name"] for column in inspect(bind).get_columns("ai_analysis")}
    for name, ddl in _AI_ANALYSIS_V2_COLUMNS.items():
        if name in existing:
            continue
        with bind.begin() as connection:
            connection.execute(text(f"ALTER TABLE ai_analysis ADD COLUMN {name} {ddl}"))


def apply_migrations(bind: Engine) -> int:
    """Create fresh tables or incrementally upgrade a V1 database to V2."""
    current = get_schema_version(bind)
    if current < 1:
        Base.metadata.create_all(bind=bind, checkfirst=True)
        _record_version(bind, 1)
        current = 1
    if current < 2:
        _apply_v2(bind)
        _record_version(bind, 2)
    return SCHEMA_VERSION
