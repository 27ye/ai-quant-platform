import pytest
from sqlalchemy import create_engine, inspect

import backend.app.models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.migrations import SCHEMA_VERSION, apply_migrations, get_schema_version

V1_TABLES = {
    "stock_basic",
    "stock_daily",
    "stock_indicator",
    "stock_news",
    "backtest_result",
    "ai_analysis",
}


def _engine():
    return create_engine("sqlite://")


def test_apply_migrations_creates_all_six_tables_and_records_version():
    engine = _engine()

    assert get_schema_version(engine) == 0  # fresh database reports version 0
    version = apply_migrations(engine)

    assert version == SCHEMA_VERSION
    assert get_schema_version(engine) == SCHEMA_VERSION
    tables = set(inspect(engine).get_table_names())
    assert V1_TABLES <= tables
    assert "schema_version" in tables


def test_apply_migrations_is_idempotent():
    engine = _engine()

    apply_migrations(engine)
    apply_migrations(engine)

    assert get_schema_version(engine) == SCHEMA_VERSION


def test_schema_version_tracker_kept_out_of_base_metadata():
    import backend.app.models  # noqa: F401

    assert "schema_version" not in Base.metadata.tables


def test_v1_database_upgrades_to_v2_without_losing_tables():
    """An existing V1 database must gain the V2 table through a real step."""
    from sqlalchemy import text

    engine = _engine()
    v1_tables = [Base.metadata.tables[name] for name in sorted(V1_TABLES)]
    Base.metadata.create_all(bind=engine, tables=v1_tables)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_version ("
                " version INT NOT NULL PRIMARY KEY,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))

    assert "stock_catalog_sync" not in set(inspect(engine).get_table_names())
    assert get_schema_version(engine) == 1

    assert apply_migrations(engine) == SCHEMA_VERSION

    tables = set(inspect(engine).get_table_names())
    assert "stock_catalog_sync" in tables
    assert V1_TABLES <= tables  # V1 tables survive the upgrade
    assert get_schema_version(engine) == SCHEMA_VERSION

    apply_migrations(engine)  # re-running must stay a no-op
    assert get_schema_version(engine) == SCHEMA_VERSION


def test_failed_migration_step_is_not_recorded(monkeypatch):
    """A failing step must not be recorded, so a re-run resumes from it."""
    from backend.app.db import migrations as migrations_module

    engine = _engine()

    def _boom(connection):  # noqa: ANN001
        raise RuntimeError("migration exploded")

    monkeypatch.setattr(
        migrations_module,
        "MIGRATIONS",
        list(migrations_module.MIGRATIONS) + [(SCHEMA_VERSION + 1, _boom)],
    )
    monkeypatch.setattr(migrations_module, "SCHEMA_VERSION", SCHEMA_VERSION + 1)

    with pytest.raises(RuntimeError):
        apply_migrations(engine)

    # Steps 1..N applied, the failing step was not recorded.
    assert get_schema_version(engine) == SCHEMA_VERSION
