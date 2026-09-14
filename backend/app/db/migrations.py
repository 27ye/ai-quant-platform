"""Idempotent schema bootstrap/migrations for the six V1 tables.

The ORM models in ``backend.app.models`` mirror ``docs/DATABASE_DESIGN.md``.
This module creates those tables (and a dedicated ``schema_version`` tracker)
without requiring a full migration framework for the V1 phase.

``schema_version`` is intentionally created with raw SQL rather than an ORM
model, so it does not appear in ``Base.metadata.tables`` (which the test suite
asserts contains exactly the six V1 tables).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

import backend.app.models  # noqa: F401  (register all six ORM models on Base)
from backend.app.db.base import Base

#: Current schema revision. Bump only when a new migration is added below.
SCHEMA_VERSION = 1

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


def apply_migrations(bind: Engine) -> int:
    """Create the six V1 tables idempotently and record the applied version.

    ``checkfirst=True`` leaves any pre-existing table untouched, so calling this
    repeatedly is safe. Returns the resulting schema version.
    """
    current = get_schema_version(bind)
    if current < SCHEMA_VERSION:
        Base.metadata.create_all(bind=bind, checkfirst=True)
        with bind.begin() as connection:
            connection.execute(
                text("INSERT INTO schema_version (version) VALUES (:version)"),
                {"version": SCHEMA_VERSION},
            )
    return SCHEMA_VERSION
