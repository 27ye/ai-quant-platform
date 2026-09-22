# -*- coding: utf-8 -*-
"""V1 -> v9 upgrade chain on real MySQL, starting from the *genuine* V1 schema.

D's real-environment acceptance asks for "在独立 MySQL 8 数据库执行 V1→当前版本迁移和
中断恢复场景". B's earlier MySQL evidence was **v7 -> v8 only** (the incremental
interruption-recovery case), because the existing unit test builds its "V1" database
from *current* ORM metadata - which already carries every later column, so the
v4/v6/v7 ALTER steps were never actually exercised.

This script removes that gap. It rebuilds a faithful V1 database the way V1's own code
did: the six V1 ORM models are read straight out of the ``v1-frozen-package-r2`` tag and
registered on a throwaway declarative Base, so the baseline has V1's real column set
(no ``c_result``, no ``c_result_text``, no ``semantics_version``, ...). It then walks:

    V1 baseline -> steps 1..7 -> simulated interrupted v8 -> documented entry point
                 -> v9 (V3: ``analysis_mode`` + ``backtest_id`` on ``ai_analysis``)

and asserts at each stage. Own probe database only; ``ai_quant`` / ``ai_quant_test``
are never touched.

Usage:
    python scripts/verify_v1_migration_chain.py
    python scripts/verify_v1_migration_chain.py --tag v1-frozen-package
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import DeclarativeBase, Session  # noqa: E402

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.db import migrations  # noqa: E402
from backend.app.db.migrations import apply_migrations, get_schema_version  # noqa: E402
from backend.app.services.backtest_service import BacktestRepository  # noqa: E402

DEFAULT_TAG = "v1-frozen-package-r2"
PROBE_DB = "ai_quant_b_probe_v1chain_20260917"

V1_MODELS = (
    "stock_basic",
    "stock_daily",
    "stock_indicator",
    "stock_news",
    "backtest_result",
    "ai_analysis",
)
V1_TABLES = {
    "stock_basic",
    "stock_daily",
    "stock_indicator",
    "stock_news",
    "backtest_result",
    "ai_analysis",
}
#: Columns V2 added to ``backtest_result``; none may exist in the V1 baseline.
V2_ADDED_BACKTEST_COLUMNS = {
    "semantics_version",
    "strategy_version",
    "final_equity",
    "order_count",
    "warmup_start_date",
    "equity_curve",
    "benchmark_curve",
    "drawdown_curve",
    "orders",
    "effective_parameters",
    "data_meta",
    "input_snapshot",
    "c_result",
    "c_result_text",
}
V2_ADDED_AI_COLUMNS = {
    "context_snapshot",
    "context_hash",
    "source_mode",
    "data_as_of",
    "prompt_version",
    "context_schema_version",
    "output_schema_version",
}

HIGH = 99633.35582084299  # MySQL's JSON column cannot hold this exactly

FAILURES: List[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' :: ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --------------------------------------------------------------------------- #
# V1 baseline, taken from the tag itself
# --------------------------------------------------------------------------- #


def _git_show(rev_path: str) -> str:
    """``git show`` into a file handle - never a pipe (so it works when sandboxed)."""
    handle_fd, tmp = tempfile.mkstemp(suffix=".py")
    os.close(handle_fd)
    try:
        with open(tmp, "w", encoding="utf-8") as sink:
            completed = subprocess.run(  # noqa: S603,S607 - local git, fixed args
                ["git", "show", rev_path],
                cwd=PROJECT_ROOT,
                stdout=sink,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(f"git show {rev_path} exited {completed.returncode}")
        return Path(tmp).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp)


def build_v1_base(tag: str) -> Any:
    """Register the tag's six models on a fresh Base and return it.

    Each V1 model file is executed as a *real* module (registered in ``sys.modules``)
    so SQLAlchemy can resolve the ``Mapped[...]`` annotations against that module's
    globals - executing into a bare dict makes it look in ``builtins`` and fail.
    """

    class V1Base(DeclarativeBase):
        pass

    shared: Dict[str, Any] = {"Base": V1Base}
    for name in V1_MODELS:
        source = _git_show(f"{tag}:backend/app/models/{name}.py")
        # The only coupling to the app is this one import; point it at the fresh Base.
        source = source.replace("from backend.app.db.base import Base", "")
        module_name = f"_v1_frozen_{tag.replace('-', '_')}.{name}"
        module = types.ModuleType(module_name)
        module.__dict__.update(shared)
        sys.modules[module_name] = module
        exec(compile(source, f"<{tag}:{name}>", "exec"), module.__dict__)  # noqa: S102
    return V1Base


def create_v1_database(engine: Engine, tag: str) -> Tuple[Set[str], Dict[str, List[str]]]:
    """Reproduce what V1's own ``apply_migrations`` did: create_all + version 1.

    Returns the V1 table set **and** each V1 table's real column list, so the caller can
    compare whole rows instead of a hand-picked subset (C, 5706925540).
    """
    v1_base = build_v1_base(tag)
    v1_base.metadata.create_all(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_version ("
                " version INT NOT NULL PRIMARY KEY,"
                " applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
    columns = {
        name: [column.name for column in table.columns]
        for name, table in v1_base.metadata.tables.items()
    }
    return set(v1_base.metadata.tables), columns


# --------------------------------------------------------------------------- #
# plumbing
# --------------------------------------------------------------------------- #


def _server_url() -> str:
    s = get_settings()
    return (
        f"mysql+pymysql://{s.mysql_user}:{s.mysql_password}"
        f"@{s.mysql_host}:{s.mysql_port}/?charset=utf8mb4"
    )


def _db_url(name: str) -> str:
    s = get_settings()
    return (
        f"mysql+pymysql://{s.mysql_user}:{s.mysql_password}"
        f"@{s.mysql_host}:{s.mysql_port}/{name}?charset=utf8mb4"
    )


def recreate_probe_db(name: str) -> Engine:
    with create_engine(_server_url(), isolation_level="AUTOCOMMIT").begin() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        connection.execute(text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4"))
    return create_engine(_db_url(name), pool_pre_ping=True)


def columns_of(engine: Engine, table: str) -> Dict[str, str]:
    return {c["name"]: str(c["type"]).lower() for c in inspect(engine).get_columns(table)}


def advance_to(engine: Engine, target: int, on_step=None) -> int:
    """Apply the real steps 1..target, recording each version like the entry point.

    ``on_step`` (if given) runs as ``on_step(version)`` **after** that step committed, so
    the caller can assert per-step artifacts - e.g. that v2/v3 created their own tables
    rather than inheriting them from somewhere else.
    """
    current = get_schema_version(engine)
    for version, step in migrations.MIGRATIONS:
        if version > target or version <= current:
            continue
        with engine.begin() as connection:
            step(connection)
            connection.execute(
                text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version}
            )
        if on_step is not None:
            on_step(version)
    return get_schema_version(engine)


def read_v1_row(engine: Engine, table: str, columns: Sequence[str], row_id: int) -> Dict[str, str]:
    """Read **every** V1 column of one row, not a hand-picked subset (C, 5706925540)."""
    names = ", ".join(f"`{name}`" for name in columns)
    with engine.connect() as connection:
        row = connection.execute(
            text(f"SELECT {names} FROM {table} WHERE id = :i"), {"i": row_id}
        ).one()
    return {name: str(value) for name, value in zip(columns, row)}


def read_schema_versions(engine: Engine) -> List[Tuple[str, str]]:
    """The whole ``schema_version`` table, including each row's ``applied_at``."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT version, applied_at FROM schema_version ORDER BY version")
        ).all()
    return [(str(row[0]), str(row[1])) for row in rows]


def snapshot_table(engine: Engine, table: str) -> List[Tuple[str, ...]]:
    """Every column of every row, so 'unchanged' means the whole table."""
    with engine.connect() as connection:
        rows = connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
    return [tuple(str(value) for value in row) for row in rows]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=DEFAULT_TAG, help="V1 source tag")
    parser.add_argument("--database", default=PROBE_DB, help="probe database name")
    args = parser.parse_args()

    if args.database in {"ai_quant", "ai_quant_test"}:
        print("REFUSED: never run this against the application database", file=sys.stderr)
        return 2

    print("=" * 78)
    print(f"1. Rebuild a faithful V1 database from tag {args.tag}")
    print("=" * 78)
    engine = recreate_probe_db(args.database)
    v1_tables, v1_columns = create_v1_database(engine, args.tag)
    check("V1 created exactly the six V1 tables", v1_tables == V1_TABLES, str(sorted(v1_tables)))
    v2_tables = {"stock_catalog_sync", "stock_daily_sync"}
    check(
        "V1 baseline does NOT yet have the V2 tables",
        not (v2_tables & set(inspect(engine).get_table_names())),
        "so v2/v3 have to create them themselves",
    )

    bt_before = columns_of(engine, "backtest_result")
    ai_before = columns_of(engine, "ai_analysis")
    missing = V2_ADDED_BACKTEST_COLUMNS & set(bt_before)
    check(
        "baseline has NO V2 columns on backtest_result",
        not missing,
        f"unexpected: {sorted(missing)}" if missing else f"{len(bt_before)} V1 columns",
    )
    missing_ai = V2_ADDED_AI_COLUMNS & set(ai_before)
    check("baseline has NO V2 columns on ai_analysis", not missing_ai, f"{len(ai_before)} V1 columns")
    check("baseline version is 1", get_schema_version(engine) == 1)
    check(
        "baseline is NOT current metadata",
        "c_result" not in bt_before and "context_hash" not in ai_before,
        "so the v4/v6/v7 ALTER steps must really run",
    )

    print()
    print("=" * 78)
    print("2. Seed genuine V1 rows (V1 column set only)")
    print("=" * 78)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(stock_code, strategy_name, start_date, end_date, initial_cash, "
                " total_return, max_drawdown, trade_count, created_at) "
                "VALUES ('600519', 'v1_ma', '2024-01-02', '2024-06-28', 100000.00, "
                " 0.12345678, -0.04567890, 17, NOW())"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis "
                "(stock_code, quant_score, trend, summary, created_at) "
                "VALUES ('600519', 72, 'bullish', 'V1 report body', NOW())"
            )
        )
    # Whole V1 rows, so "unchanged" covers every V1 column rather than a chosen few.
    v1_bt_before = read_v1_row(engine, "backtest_result", v1_columns["backtest_result"], 1)
    v1_ai_before = read_v1_row(engine, "ai_analysis", v1_columns["ai_analysis"], 1)
    check("V1 backtest row seeded", v1_bt_before["strategy_name"] == "v1_ma",
          f"{len(v1_bt_before)} V1 columns")
    check("V1 AI row seeded", v1_ai_before["quant_score"] == "72",
          f"{len(v1_ai_before)} V1 columns")

    print()
    print("=" * 78)
    print("3. Run the real steps 1..7 (stop where v8 begins)")
    print("=" * 78)
    per_step: List[Tuple[str, bool]] = []

    def after_step(version: int) -> None:
        tables = set(inspect(engine).get_table_names())
        if version == 2:
            per_step.append(("v2 step created stock_catalog_sync", "stock_catalog_sync" in tables))
        elif version == 3:
            per_step.append(("v3 step created stock_daily_sync", "stock_daily_sync" in tables))

    check("advanced to 7", advance_to(engine, 7, on_step=after_step) == 7)
    for label, ok in per_step:
        check(label, ok)
    bt_at_7 = columns_of(engine, "backtest_result")
    check("v4/v6/v7 columns now exist", V2_ADDED_BACKTEST_COLUMNS - {"c_result_text"} <= set(bt_at_7),
          f"{len(bt_at_7)} columns")
    check("v5 columns now exist on ai_analysis", V2_ADDED_AI_COLUMNS <= set(columns_of(engine, "ai_analysis")))
    check("c_result_text does NOT exist yet", "c_result_text" not in bt_at_7)
    tables_at_7 = set(inspect(engine).get_table_names())
    check("V2 tables present", {"stock_catalog_sync", "stock_daily_sync"} <= tables_at_7)

    # A row written by pre-v8 V2 code: JSON column only, no text column.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO backtest_result "
                "(stock_code, strategy_name, start_date, end_date, c_result) "
                "VALUES ('600519', 'pre_v8', '2025-01-02', '2025-06-30', :p)"
            ),
            {"p": json.dumps({"algorithm_version": "pre-v8", "equity": HIGH})},
        )
    with engine.connect() as connection:
        legacy_id = connection.execute(
            text("SELECT id FROM backtest_result WHERE strategy_name = 'pre_v8'")
        ).scalar()
    check("pre-v8 legacy row seeded", isinstance(legacy_id, int) and legacy_id > 1, f"id={legacy_id}")

    print()
    print("=" * 78)
    print("4. Simulate the interrupted v8 (column committed, backfill did not run)")
    print("=" * 78)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE backtest_result ADD COLUMN c_result_text LONGTEXT NULL"))
    bt_interrupted = columns_of(engine, "backtest_result")
    check("column exists after the interrupted run", "c_result_text" in bt_interrupted)
    check("version is STILL 7 (never recorded)", get_schema_version(engine) == 7)
    with engine.connect() as connection:
        still_null = connection.execute(
            text("SELECT c_result_text FROM backtest_result WHERE id = :i"), {"i": legacy_id}
        ).scalar()
    check("legacy text still NULL", still_null is None)

    print()
    print("=" * 78)
    print("5. Re-run the documented entry point - it must resume, not skip")
    print("=" * 78)
    check("apply_migrations returns the current revision",
          apply_migrations(engine) == migrations.SCHEMA_VERSION)
    check("version recorded as the current revision",
          get_schema_version(engine) == migrations.SCHEMA_VERSION)
    check("c_result_text is LONGTEXT", columns_of(engine, "backtest_result").get("c_result_text") == "longtext",
          columns_of(engine, "backtest_result").get("c_result_text"))

    with engine.connect() as connection:
        backfilled = connection.execute(
            text("SELECT c_result_text FROM backtest_result WHERE id = :i"), {"i": legacy_id}
        ).scalar()
    check("legacy row backfilled", backfilled is not None)
    check("backfilled text parses as JSON", isinstance(json.loads(backfilled), dict),
          str(backfilled)[:60])

    print()
    print("=" * 78)
    print("5b. V3 v9 rode along: analysis_mode + backtest_id on ai_analysis")
    print("=" * 78)
    ai_after_v9 = columns_of(engine, "ai_analysis")
    check(
        "analysis_mode exists with the frozen type",
        ai_after_v9.get("analysis_mode") == "varchar(16)",
        ai_after_v9.get("analysis_mode"),
    )
    check(
        "backtest_id exists with the frozen type",
        ai_after_v9.get("backtest_id") == "bigint",
        ai_after_v9.get("backtest_id"),
    )
    with engine.connect() as connection:
        legacy_ai = connection.execute(
            text("SELECT analysis_mode, backtest_id FROM ai_analysis WHERE id = 1")
        ).one()
    check(
        "pre-v9 report is NOT backfilled (both columns stay NULL)",
        legacy_ai[0] is None and legacy_ai[1] is None,
        f"analysis_mode={legacy_ai[0]!r} backtest_id={legacy_ai[1]!r}",
    )

    print()
    print("=" * 78)
    print("6. V1 data survived the whole chain, unchanged")
    print("=" * 78)
    v1_bt_after = read_v1_row(engine, "backtest_result", v1_columns["backtest_result"], 1)
    v1_ai_after = read_v1_row(engine, "ai_analysis", v1_columns["ai_analysis"], 1)
    with engine.connect() as connection:
        v1_still_no_c_result = connection.execute(
            text("SELECT (c_result IS NULL AND c_result_text IS NULL) FROM backtest_result WHERE id = 1")
        ).scalar()
    check(
        "every V1 column of the backtest row is unchanged",
        v1_bt_before == v1_bt_after,
        f"{len(v1_bt_before)} columns compared",
    )
    check(
        "every V1 column of the AI row is unchanged",
        v1_ai_before == v1_ai_after,
        f"{len(v1_ai_before)} columns compared",
    )
    check("V1 row was never touched by the backfill", bool(v1_still_no_c_result))

    print()
    print("=" * 78)
    print("7. Repository reads the upgraded rows the way the contract says")
    print("=" * 78)
    with Session(bind=engine) as session:
        repo = BacktestRepository(session)
        v1_detail = repo.get(1)
        legacy_detail = repo.get(int(legacy_id))
        legacy_full = repo.get(int(legacy_id), include_c_result=True)
    check("V1 row: no envelope available", v1_detail["c_result_available"] is False)
    check("V1 row: exact=False", v1_detail["c_result_exact"] is False)
    check("pre-v8 row: available + exact=False", legacy_detail["c_result_available"] is True
          and legacy_detail["c_result_exact"] is False)
    check("pre-v8 row reads back through the envelope",
          legacy_full["c_result"]["algorithm_version"] == "pre-v8")

    print()
    print("=" * 78)
    print("8. Re-running the whole migration is a no-op")
    print("=" * 78)
    versions_before = read_schema_versions(engine)
    backtest_before = snapshot_table(engine, "backtest_result")
    ai_before = snapshot_table(engine, "ai_analysis")
    for _ in range(2):
        apply_migrations(engine)
    versions_after = read_schema_versions(engine)
    backtest_after = snapshot_table(engine, "backtest_result")
    ai_after = snapshot_table(engine, "ai_analysis")
    check(
        "every column of every backtest_result row is unchanged",
        backtest_before == backtest_after,
        f"{len(backtest_before)} rows x all columns",
    )
    check(
        "every column of every ai_analysis row is unchanged",
        ai_before == ai_after,
        f"{len(ai_before)} rows x all columns",
    )
    check(
        "schema_version rows unchanged, applied_at included",
        versions_before == versions_after,
        f"{len(versions_before)} version rows compared",
    )
    check("version still the current revision",
          get_schema_version(engine) == migrations.SCHEMA_VERSION)

    print()
    print("=" * 78)
    if FAILURES:
        print(f"RESULT: {len(FAILURES)} FAILED -> {FAILURES}")
        return 1
    print(f"RESULT: ALL CHECKS PASSED (real MySQL, V1 -> v{migrations.SCHEMA_VERSION})")
    print(f"  probe database : {args.database}")
    print(f"  V1 source tag  : {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
