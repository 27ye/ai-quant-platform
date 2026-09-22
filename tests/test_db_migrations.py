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


def test_failed_ai_snapshot_alter_does_not_record_version_five():
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

    assert get_schema_version(engine) == 4


def test_schema_version_tracker_kept_out_of_base_metadata():
    import backend.app.models  # noqa: F401

    assert "schema_version" not in Base.metadata.tables


def test_v1_database_upgrades_without_losing_tables():
    """An existing V1 database must gain every later table through real steps."""
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

    before = set(inspect(engine).get_table_names())
    assert "stock_catalog_sync" not in before
    assert "stock_daily_sync" not in before
    assert get_schema_version(engine) == 1

    assert apply_migrations(engine) == SCHEMA_VERSION

    tables = set(inspect(engine).get_table_names())
    assert {"stock_catalog_sync", "stock_daily_sync"} <= tables
    assert V1_TABLES <= tables  # V1 tables survive the upgrade
    assert get_schema_version(engine) == SCHEMA_VERSION

    apply_migrations(engine)  # re-running must stay a no-op
    assert get_schema_version(engine) == SCHEMA_VERSION


def test_v5_adds_ai_report_snapshot_columns():
    engine = _engine()

    apply_migrations(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("ai_analysis")}
    assert {
        "context_snapshot",
        "context_hash",
        "source_mode",
        "data_as_of",
        "prompt_version",
        "context_schema_version",
        "output_schema_version",
    } <= columns


def test_apply_migrations_converges_when_version_rows_disagree():
    """Two V2 branches both used "v2" for different content.

    A database whose history says "2" while actually containing the AI columns
    (and none of B's V2 artifacts) must still end up with the complete schema
    instead of silently missing the catalog table.
    """
    from sqlalchemy import text

    engine = _engine()
    Base.metadata.create_all(
        bind=engine, tables=[Base.metadata.tables["ai_analysis"]]
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE schema_version ("
                " version INT NOT NULL PRIMARY KEY,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO schema_version (version) VALUES (2)"))

    assert "stock_catalog_sync" not in set(inspect(engine).get_table_names())

    apply_migrations(engine)

    tables = set(inspect(engine).get_table_names())
    assert {"stock_catalog_sync", "stock_daily_sync"} <= tables
    backtest_columns = {
        column["name"] for column in inspect(engine).get_columns("backtest_result")
    }
    assert "equity_curve" in backtest_columns
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


#: ``backtest_result`` exactly as V1 shipped it (tag ``v1-frozen-package-r2``).
#: Frozen history, so hardcoding is correct: it must never change again.
V1_BACKTEST_RESULT_DDL = (
    "CREATE TABLE backtest_result ("
    " id BIGINT NOT NULL PRIMARY KEY,"
    " stock_code VARCHAR(10) NOT NULL,"
    " strategy_name VARCHAR(100) NOT NULL,"
    " start_date DATE NOT NULL,"
    " end_date DATE NOT NULL,"
    " initial_cash DECIMAL(20, 2),"
    " total_return DECIMAL(16, 8),"
    " annual_return DECIMAL(16, 8),"
    " max_drawdown DECIMAL(16, 8),"
    " sharpe_ratio DECIMAL(16, 8),"
    " win_rate DECIMAL(16, 8),"
    " trade_count INTEGER,"
    " benchmark_return DECIMAL(16, 8),"
    " parameters JSON,"
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)

#: ``ai_analysis`` exactly as V1 shipped it (tag ``v1-frozen-package-r2``).
V1_AI_ANALYSIS_DDL = (
    "CREATE TABLE ai_analysis ("
    " id BIGINT NOT NULL PRIMARY KEY,"
    " stock_code VARCHAR(10) NOT NULL,"
    " quant_score INTEGER,"
    " trend VARCHAR(50),"
    " summary TEXT,"
    " technical_analysis TEXT,"
    " quant_analysis TEXT,"
    " news_analysis TEXT,"
    " advantages JSON,"
    " risks JSON,"
    " conclusion TEXT,"
    " model_name VARCHAR(100),"
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)


def test_a_genuine_v1_schema_is_upgraded_column_by_column():
    """The V1 baseline must be V1's real columns, not today's metadata.

    ``test_v1_database_upgrades_without_losing_tables`` builds its baseline with
    ``Base.metadata.create_all`` from *current* models, which already contains every
    later column - so the v4/v6/v7/v8 ALTER steps had nothing to add and were never
    actually exercised. This baseline is the real V1 shape (frozen DDL above, taken
    from the ``v1-frozen-package-r2`` tag), i.e. what
    ``scripts/verify_v1_migration_chain.py`` upgrades against real MySQL.
    """
    from sqlalchemy import text

    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text(V1_BACKTEST_RESULT_DDL))
        connection.execute(text(V1_AI_ANALYSIS_DDL))
        connection.execute(
            text(
                "CREATE TABLE schema_version ("
                " version INT NOT NULL PRIMARY KEY,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(id, stock_code, strategy_name, start_date, end_date, initial_cash, total_return) "
                "VALUES (1, '600519', 'v1_ma', '2024-01-02', '2024-06-28', 100000.00, 0.12345678)"
            )
        )

    baseline = {column["name"] for column in inspect(engine).get_columns("backtest_result")}
    assert "c_result" not in baseline
    assert "c_result_text" not in baseline
    assert "data_meta" not in baseline
    ai_baseline = {column["name"] for column in inspect(engine).get_columns("ai_analysis")}
    assert "context_hash" not in ai_baseline

    assert apply_migrations(engine) == SCHEMA_VERSION

    # Every later migration really had to add its own columns.
    columns = {column["name"] for column in inspect(engine).get_columns("backtest_result")}
    assert {
        "semantics_version",  # v4
        "data_meta",  # v4
        "input_snapshot",  # v6
        "c_result",  # v7
        "c_result_text",  # v8
    } <= columns
    ai_columns = {column["name"] for column in inspect(engine).get_columns("ai_analysis")}
    assert {"context_hash", "context_snapshot", "source_mode"} <= ai_columns  # v5
    assert {"analysis_mode", "backtest_id"} <= ai_columns  # v9
    assert {"stock_catalog_sync", "stock_daily_sync"} <= set(inspect(engine).get_table_names())

    # The V1 row survives the whole chain untouched.
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT strategy_name FROM backtest_result WHERE id = 1")
        ).one()
    assert row[0] == "v1_ma"

    # And the chain converges.
    apply_migrations(engine)
    assert get_schema_version(engine) == SCHEMA_VERSION


# --------------------------------------------------------------------------- #
# v9 (V3 F4): analysis_mode + backtest_id on ai_analysis
# --------------------------------------------------------------------------- #

#: ``ai_analysis`` as it stands **at v8**: V1's real columns plus the v5 snapshot
#: columns. Frozen on purpose - the V3 columns must *not* be here, or the v9 step
#: would have nothing to add and the test would pass for the wrong reason.
V8_AI_ANALYSIS_DDL = (
    "CREATE TABLE ai_analysis ("
    " id BIGINT NOT NULL PRIMARY KEY,"
    " stock_code VARCHAR(10) NOT NULL,"
    " quant_score INTEGER,"
    " trend VARCHAR(50),"
    " summary TEXT,"
    " technical_analysis TEXT,"
    " quant_analysis TEXT,"
    " news_analysis TEXT,"
    " advantages JSON,"
    " risks JSON,"
    " conclusion TEXT,"
    " model_name VARCHAR(100),"
    " context_snapshot TEXT,"
    " context_hash CHAR(64),"
    " source_mode VARCHAR(16),"
    " data_as_of DATETIME,"
    " prompt_version VARCHAR(32),"
    " context_schema_version VARCHAR(32),"
    " output_schema_version VARCHAR(32),"
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)

#: The two V3 columns frozen with D (V3 plan section 5.3).
V3_AI_COLUMNS = ("analysis_mode", "backtest_id")

_AI_LEGACY_SELECT = (
    "SELECT id, stock_code, summary, context_hash, source_mode, context_snapshot "
    "FROM ai_analysis ORDER BY id"
)


def _rows(engine, statement, parameters=None):
    with engine.connect() as connection:
        return [
            tuple(row) for row in connection.execute(text(statement), parameters or {})
        ]


def _ai_columns(engine):
    return {column["name"] for column in inspect(engine).get_columns("ai_analysis")}


#: ``backtest_result`` as it stands at **v8**: V1's columns plus the v4/v6/v7/v8 ones,
#: so the convergence pass has nothing left to repair on this table and the v9 test
#: cannot pass by accidentally measuring someone else's ALTER.
V8_BACKTEST_RESULT_DDL = (
    "CREATE TABLE backtest_result ("
    " id BIGINT NOT NULL PRIMARY KEY,"
    " stock_code VARCHAR(10) NOT NULL,"
    " strategy_name VARCHAR(100) NOT NULL,"
    " start_date DATE NOT NULL,"
    " end_date DATE NOT NULL,"
    " initial_cash DECIMAL(20, 2),"
    " total_return DECIMAL(16, 8),"
    " annual_return DECIMAL(16, 8),"
    " max_drawdown DECIMAL(16, 8),"
    " sharpe_ratio DECIMAL(16, 8),"
    " win_rate DECIMAL(16, 8),"
    " trade_count INTEGER,"
    " benchmark_return DECIMAL(16, 8),"
    " parameters JSON,"
    " semantics_version VARCHAR(20),"  # v4
    " strategy_version VARCHAR(20),"  # v4
    " final_equity DECIMAL(20, 2),"  # v4
    " order_count INTEGER,"  # v4
    " warmup_start_date DATE,"  # v4
    " equity_curve JSON,"  # v4
    " benchmark_curve JSON,"  # v4
    " drawdown_curve JSON,"  # v4
    " orders JSON,"  # v4
    " effective_parameters JSON,"  # v4
    " data_meta JSON,"  # v4
    " input_snapshot JSON,"  # v6
    " c_result JSON,"  # v7
    " c_result_text TEXT,"  # v8
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)


def _v8_engine(*, reports=1):
    """A database that says v8 and really is v8 (V3 columns absent, rows present)."""
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(text(V8_AI_ANALYSIS_DDL))
        connection.execute(text(V8_BACKTEST_RESULT_DDL))
        connection.execute(
            text(
                "CREATE TABLE schema_version ("
                " version INT NOT NULL PRIMARY KEY,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        for version in range(1, 9):
            connection.execute(
                text("INSERT INTO schema_version (version) VALUES (:version)"),
                {"version": version},
            )
        for index in range(reports):
            connection.execute(
                text(
                    "INSERT INTO ai_analysis "
                    "(id, stock_code, summary, context_hash, source_mode, context_snapshot) "
                    "VALUES (:id, '600519', :summary, :hash, 'realtime', "
                    "'{\"legacy\": true, \"data_as_of\": \"2026-09-19\"}')"
                ),
                {
                    "id": index + 1,
                    "summary": f"legacy report {index + 1}",
                    "hash": "a" * 64,
                },
            )
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(id, stock_code, strategy_name, start_date, end_date, c_result_text) "
                "VALUES (1, '600519', 'ma_long_only', '2024-01-02', '2024-06-28', :text)"
            ),
            {"text": '{"algorithm_version": "c.v2", "equity": [1.0, 1.2345678901234567]}'},
        )
    return engine


def test_v9_adds_mode_and_backtest_link_to_a_fresh_database():
    engine = _engine()

    assert apply_migrations(engine) == SCHEMA_VERSION

    columns = {
        column["name"]: column for column in inspect(engine).get_columns("ai_analysis")
    }
    assert set(V3_AI_COLUMNS) <= set(columns)
    # Both are optional: a report without a linked backtest is a first-class state.
    assert columns["analysis_mode"]["nullable"] is True
    assert columns["backtest_id"]["nullable"] is True
    assert get_schema_version(engine) == SCHEMA_VERSION


def test_v9_leaves_legacy_reports_and_c_exact_text_untouched():
    engine = _v8_engine(reports=2)
    before_ai = _rows(engine, _AI_LEGACY_SELECT)
    before_bt = _rows(engine, "SELECT id, c_result_text FROM backtest_result")
    before_bt_columns = {
        column["name"] for column in inspect(engine).get_columns("backtest_result")
    }
    assert not set(V3_AI_COLUMNS) & _ai_columns(engine)

    apply_migrations(engine)

    assert set(V3_AI_COLUMNS) <= _ai_columns(engine)
    assert get_schema_version(engine) == SCHEMA_VERSION

    # Every original value survives...
    assert _rows(engine, _AI_LEGACY_SELECT) == before_ai
    # ...and the new columns stay NULL: the migration must not stamp 'standard' onto a
    # report whose mode was never recorded (V3 plan 5.3: no backfill, no recompute).
    assert _rows(
        engine, "SELECT analysis_mode, backtest_id FROM ai_analysis ORDER BY id"
    ) == [(None, None), (None, None)]

    # A migration that only adds AI columns must not rewrite C's verbatim result text.
    assert _rows(engine, "SELECT id, c_result_text FROM backtest_result") == before_bt
    assert {
        column["name"] for column in inspect(engine).get_columns("backtest_result")
    } == before_bt_columns


def test_v9_resumes_when_only_the_first_column_was_committed():
    """MySQL commits ``ALTER`` implicitly, so v8 + ``analysis_mode`` is a real state."""
    engine = _v8_engine(reports=1)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE ai_analysis ADD COLUMN analysis_mode VARCHAR(16) NULL")
        )
        connection.execute(
            text("UPDATE ai_analysis SET analysis_mode = 'custom_backtest' WHERE id = 1")
        )
    assert get_schema_version(engine) == 8

    assert apply_migrations(engine) == SCHEMA_VERSION

    assert set(V3_AI_COLUMNS) <= _ai_columns(engine)
    assert get_schema_version(engine) == SCHEMA_VERSION
    # The already-committed column is left alone; only the missing one is added.
    assert _rows(engine, "SELECT analysis_mode FROM ai_analysis WHERE id = 1") == [
        ("custom_backtest",)
    ]


def test_v9_failure_mid_step_is_not_recorded():
    """v9 is recorded only after the whole step succeeded, so a re-run resumes it."""
    engine = _v8_engine(reports=1)

    def fail_second_column(conn, cursor, statement, parameters, context, executemany):
        if "ADD COLUMN backtest_id" in statement:
            raise RuntimeError("simulated v9 interruption")

    event.listen(engine, "before_cursor_execute", fail_second_column)
    with pytest.raises(RuntimeError, match="simulated v9 interruption"):
        apply_migrations(engine)
    event.remove(engine, "before_cursor_execute", fail_second_column)

    assert get_schema_version(engine) == 8

    assert apply_migrations(engine) == SCHEMA_VERSION
    assert set(V3_AI_COLUMNS) <= _ai_columns(engine)
    assert get_schema_version(engine) == SCHEMA_VERSION


def test_v9_is_repeatable_and_records_one_version_row():
    engine = _v8_engine(reports=1)

    apply_migrations(engine)
    apply_migrations(engine)

    assert get_schema_version(engine) == SCHEMA_VERSION
    assert _rows(
        engine,
        "SELECT COUNT(*) FROM schema_version WHERE version = :version",
        {"version": SCHEMA_VERSION},
    ) == [(1,)]
    assert _rows(engine, "SELECT COUNT(*) FROM schema_version") == [(SCHEMA_VERSION,)]
