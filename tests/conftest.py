"""Shared pytest fixtures/compiler overrides for the backend test suite.

SQLAlchemy maps ``BIGINT`` to ``BIGINT`` on SQLite, which does NOT participate
in SQLite's rowid autoincrement (only ``INTEGER PRIMARY KEY`` does). Since the
six V1 tables use ``BIGINT`` PRIMARY KEY AUTOINCREMENT columns, tests that insert
into a SQLite database would fail with ``NOT NULL constraint failed``. This
override compiles ``BIGINT`` to ``INTEGER`` on the SQLite dialect only, keeping
the ORM/metadata unchanged while letting the in-memory SQLite test database
auto-assign primary keys. MySQL (the real DB) is unaffected.
"""

from sqlalchemy import BIGINT
from sqlalchemy.ext.compiler import compiles


@compiles(BIGINT, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "INTEGER"
