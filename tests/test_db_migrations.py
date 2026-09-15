import pytest
from sqlalchemy import create_engine, event, inspect, text

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


def test_v1_database_is_upgraded_without_changing_legacy_rows():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ai_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code VARCHAR(10) NOT NULL,
                quant_score INTEGER,
                trend VARCHAR(50),
                summary TEXT,
                technical_analysis TEXT,
                quant_analysis TEXT,
                news_analysis TEXT,
                advantages JSON,
                risks JSON,
                conclusion TEXT,
                model_name VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        connection.execute(text("""
            INSERT INTO ai_analysis (
                stock_code, trend, summary, technical_analysis, quant_analysis,
                news_analysis, advantages, risks, conclusion, model_name
            ) VALUES (
                '600519', 'neutral', 'legacy', 'technical', 'quant', 'news',
                '["advantage"]', '["risk"]', 'conclusion', 'legacy-model'
            )
        """))

    apply_migrations(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("ai_analysis")}
    assert {
        "context_snapshot", "context_hash", "source_mode", "data_as_of",
        "prompt_version", "context_schema_version", "output_schema_version",
    } <= columns
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT stock_code, context_snapshot FROM ai_analysis")
        ).one()
    assert row.stock_code == "600519"
    assert row.context_snapshot is None


def test_failed_v2_alter_does_not_record_version_two():
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ai_analysis (id INTEGER PRIMARY KEY, stock_code VARCHAR(10))"))

    def fail_one_column(conn, cursor, statement, parameters, context, executemany):
        if "ADD COLUMN context_hash" in statement:
            raise RuntimeError("simulated migration failure")

    event.listen(engine, "before_cursor_execute", fail_one_column)
    with pytest.raises(RuntimeError, match="simulated migration failure"):
        apply_migrations(engine)
    event.remove(engine, "before_cursor_execute", fail_one_column)

    assert get_schema_version(engine) == 1


def test_schema_version_tracker_kept_out_of_base_metadata():
    import backend.app.models  # noqa: F401

    assert "schema_version" not in Base.metadata.tables
