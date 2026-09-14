"""Create the ``ai_quant`` database (if missing) and apply the V1 schema migrations.

Usage:
    python scripts/migrate_db.py
"""

import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.db.migrations import apply_migrations, get_schema_version  # noqa: E402


def _ensure_database(settings) -> None:
    """Create the target MySQL database when it does not yet exist (MySQL only)."""
    server_url = "mysql+pymysql://{u}:{p}@{h}:{port}/?charset=utf8mb4".format(
        u=quote_plus(settings.mysql_user),
        p=quote_plus(settings.mysql_password),
        h=settings.mysql_host,
        port=settings.mysql_port,
    )
    engine = create_engine(server_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE DATABASE IF NOT EXISTS `{db}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci".format(
                        db=settings.mysql_database
                    )
                )
            )
    finally:
        engine.dispose()


def main() -> int:
    settings = get_settings()
    _ensure_database(settings)

    from backend.app.db.session import engine  # noqa: F401

    before = get_schema_version(engine)
    version = apply_migrations(engine)

    from sqlalchemy import inspect

    tables = inspect(engine).get_table_names()
    print(f"schema version: {before} -> {version}")
    print("tables:", ", ".join(sorted(tables)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
