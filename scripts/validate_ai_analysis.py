"""Real AKShare/LLM smoke test; --mysql uses a NEW local acceptance database.

Default mode captures the report in memory. --mysql exercises the actual AI
route and SQLAlchemy repository. Neither mode writes to the configured ai_quant
database. Run this CLI in its own process, never inside a running backend.
"""

import argparse
import asyncio
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.ai.client import OpenAICompatibleLLMClient  # noqa: E402
from backend.app.ai.errors import AIServiceError  # noqa: E402
from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.errors import ApplicationError, InvalidParameterError  # noqa: E402
from backend.app.services.ai_analysis import AIAnalysisService  # noqa: E402
from backend.app.services.ai_context_adapter import StockQuantAnalysisAdapter  # noqa: E402
from backend.app.services.market_data_service import MarketDataService  # noqa: E402
from backend.app.services.news_service import NewsService  # noqa: E402
from backend.app.services.stock_service import StockService  # noqa: E402
from backend.app.services.analysis_context import (  # noqa: E402
    ServiceAnalysisContextProvider,
)


class ValidationRepository:
    """Capture the validated result while leaving MySQL untouched."""

    def __init__(self) -> None:
        self.saved = []

    def save(self, analysis, context, metadata):
        from backend.app.schemas.ai import AIReportDetail

        result = AIReportDetail(
            **analysis.model_dump(),
            report_id=1,
            created_at=datetime.now(timezone.utc),
            data_as_of=metadata.data_as_of,
            source_mode=metadata.source_mode,
            prompt_version=metadata.prompt_version,
            context_schema_version=metadata.context_schema_version,
            output_schema_version=metadata.output_schema_version,
            context_hash=metadata.context_hash,
            snapshot_status="complete",
            context_snapshot=context,
        )
        self.saved.append(result)
        return result

    def list_reports(self, stock_code, page, page_size):
        raise NotImplementedError

    def get_report(self, report_id):
        raise NotImplementedError


class AcceptanceError(RuntimeError):
    """Only fixed, credential-free messages may be supplied to this exception."""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-code", default="600519")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mysql", action="store_true",
                        help="Create an isolated local MySQL DB and validate the actual AI route")
    mode.add_argument("--llm-only", action="store_true",
                      help="Probe real LLM JSON connectivity only; NOT stock/report acceptance")
    mode.add_argument("--migration-only", action="store_true",
                      help="Validate a real MySQL V1-to-current migration in a new isolated database")
    mode.add_argument("--serve", action="store_true",
                      help="Serve live (or explicitly frozen) API on loopback with a new MySQL DB")
    parser.add_argument("--port", type=int, choices=(8000, 8001), default=8000,
                        help="acceptance HTTP port for --serve (default: 8000)")
    parser.add_argument("--frozen-dir", default=None,
                        help="Frozen data package directory for offline acceptance")
    parser.add_argument("--metadata", default=None,
                        help="Frozen metadata JSON path; defaults to metadata.json")
    return parser.parse_args(argv)


def make_llm_client():
    settings = get_settings()
    return OpenAICompatibleLLMClient(
        api_key=settings.llm_api_key, base_url=settings.llm_base_url,
        model_name=settings.llm_model, timeout_seconds=settings.llm_timeout_seconds,
    )


async def validate_llm_connection() -> None:
    client = make_llm_client()
    output = await client.complete_json([
        {"role": "user", "content": 'Connectivity probe only. Return exactly JSON {"ok":true}.'},
    ])
    if json.loads(output) != {"ok": True}:
        raise AcceptanceError("LLM connectivity probe returned unexpected JSON")
    print(json.dumps({"mode": "llm_connectivity_only", "validated": True,
                      "model": client.model_name, "stock_pipeline_verified": False}))


async def validate(stock_code: str) -> None:
    llm_client = make_llm_client()  # check config before contacting the provider
    stock = StockService()
    adapter = StockQuantAnalysisAdapter(
        market_data_source=MarketDataService(stock_service=stock), stock_service=stock,
    )
    context_provider = ServiceAnalysisContextProvider(
        stock_service=adapter,
        quant_service=adapter,
        backtest_service=adapter,
        news_service=NewsService(),
    )
    repository = ValidationRepository()
    service = AIAnalysisService(
        context_provider=context_provider,
        llm_client=llm_client,
        repository=repository,
    )

    result = await service.analyze(stock_code)
    if repository.saved != [result]:
        raise RuntimeError("validated analysis was not passed to the repository")

    print(
        "AI analysis validation succeeded: "
        f"stock_code={result.stock_code}, model={result.model_name}, "
        f"trend={result.trend}, quant_score={result.quant_score}"
    )


def create_acceptance_database(settings) -> str:
    """Create only a new generated database, never reuse or drop an existing one."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    if settings.mysql_host != "127.0.0.1" or settings.mysql_port not in {3307, 3308}:
        raise AcceptanceError("acceptance database must target loopback port 3307 or 3308")
    name = "ai_quant_v1_acceptance_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    if not re.fullmatch(r"ai_quant_v1_acceptance_\d{8}_\d{6}_\d{6}", name):
        raise AcceptanceError("invalid acceptance database name")
    server = create_engine(
        URL.create("mysql+pymysql", username=settings.mysql_user,
                   password=settings.mysql_password, host=settings.mysql_host,
                   port=settings.mysql_port, query={"charset": "utf8mb4"}),
        connect_args={"connect_timeout": 5, "read_timeout": 30, "write_timeout": 30},
    )
    try:
        with server.begin() as connection:
            identity = connection.execute(
                text("SELECT VERSION(), @@port")
            ).one()
            version_text = str(identity[0])
            if not version_text.startswith("8.0.") or "MariaDB" in version_text:
                raise AcceptanceError("acceptance database must be MySQL 8.0")
            if int(identity[1]) != settings.mysql_port:
                raise AcceptanceError("acceptance database port check failed")
            existing = connection.execute(text(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=:name"
            ), {"name": name}).scalar()
            if existing is not None:
                raise AcceptanceError("acceptance database already exists; refusing to reuse it")
            # Name is generated above and allowlisted. Deliberately no IF NOT EXISTS.
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    finally:
        server.dispose()
    print(json.dumps({"acceptance_database": name, "retained": True}), flush=True)
    return name


def validate_mysql(stock_code: str) -> None:
    # db.session builds its engine at import time; refuse ambiguous in-process use.
    if "backend.app.db.session" in sys.modules:
        raise AcceptanceError("run --mysql in a fresh process before importing the backend")
    make_llm_client()
    name = create_acceptance_database(get_settings())
    os.environ["MYSQL_DATABASE"] = name
    get_settings.cache_clear()

    from fastapi.testclient import TestClient
    from backend.app.db.session import SessionLocal, engine
    from backend.app.db.migrations import apply_migrations
    from backend.app.main import create_app
    from backend.app.models.ai_analysis import AIAnalysis

    try:
        verify_database_identity(engine, name)
        version = apply_migrations(engine)
        print(json.dumps({"schema_version": version, "mode": "live_api_mysql"}), flush=True)
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            response = client.post("/api/v1/ai/analyze", json={"stock_code": stock_code})
        body = response.json()
        if response.status_code != 200 or body.get("code") != 0:
            code = body.get("code")
            print(json.dumps({"api_status": response.status_code,
                              "business_code": code if isinstance(code, int) else None}), flush=True)
            raise AcceptanceError("AI API did not return success; database retained")
        data = body["data"]
        with SessionLocal() as db:
            records = db.query(AIAnalysis).filter_by(stock_code=stock_code).all()
            if len(records) != 1:
                raise AcceptanceError("expected exactly one persisted report")
            record = records[0]
            mismatches = record_response_mismatches(record, data)
            if mismatches:
                raise AcceptanceError(
                    "persisted report mismatch fields: " + ",".join(mismatches)
                )
            print(json.dumps({"validated": True, "database": name,
                              "report_id": record.id, "stock_code": record.stock_code,
                              "model": record.model_name}, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()


def validate_mysql_v1_upgrade() -> None:
    """Prove the incremental migration against a real isolated MySQL 8 schema."""
    if "backend.app.db.session" in sys.modules:
        raise AcceptanceError("run --migration-only in a fresh process")
    name = create_acceptance_database(get_settings())
    os.environ["MYSQL_DATABASE"] = name
    get_settings.cache_clear()

    from sqlalchemy import inspect, text
    from backend.app.db.migrations import SCHEMA_VERSION, apply_migrations, get_schema_version
    from backend.app.db.session import engine

    try:
        verify_database_identity(engine, name)
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE schema_version ("
                "version INT NOT NULL PRIMARY KEY, "
                "applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ))
            connection.execute(text("INSERT INTO schema_version (version) VALUES (1)"))
            connection.execute(text("""
                CREATE TABLE ai_analysis (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    stock_code VARCHAR(10) NOT NULL,
                    quant_score INT,
                    trend VARCHAR(50),
                    summary TEXT,
                    technical_analysis TEXT,
                    quant_analysis TEXT,
                    news_analysis TEXT,
                    advantages JSON,
                    risks JSON,
                    conclusion TEXT,
                    model_name VARCHAR(100),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ai_stock (stock_code),
                    INDEX idx_ai_created_at (created_at)
                )
            """))
            connection.execute(text("""
                INSERT INTO ai_analysis (
                    stock_code, trend, summary, technical_analysis,
                    quant_analysis, news_analysis, advantages, risks,
                    conclusion, model_name
                ) VALUES (
                    '600519', 'neutral', 'legacy', 'technical',
                    'quant', 'news', JSON_ARRAY('advantage'), JSON_ARRAY('risk'),
                    'conclusion', 'legacy-model'
                )
            """))

        version = apply_migrations(engine)
        columns = {column["name"]: column for column in inspect(engine).get_columns("ai_analysis")}
        required = {
            "context_snapshot", "context_hash", "source_mode", "data_as_of",
            "prompt_version", "context_schema_version", "output_schema_version",
        }
        if (
            version != SCHEMA_VERSION
            or get_schema_version(engine) != SCHEMA_VERSION
            or not required <= columns.keys()
        ):
            raise AcceptanceError("V1-to-current migration contract failed")
        if str(columns["context_hash"]["type"]).upper() != "CHAR(64)":
            raise AcceptanceError("V2 context hash type mismatch")
        with engine.connect() as connection:
            legacy = connection.execute(text(
                "SELECT stock_code, context_snapshot FROM ai_analysis WHERE id=1"
            )).one()
        if legacy.stock_code != "600519" or legacy.context_snapshot is not None:
            raise AcceptanceError("legacy report changed during migration")
        print(json.dumps({
            "validated": True,
            "mode": "mysql_v1_to_current_migration",
            "database": name,
            "schema_version": version,
            "legacy_report_preserved": True,
        }), flush=True)
    finally:
        engine.dispose()


def validate_mysql_frozen(stock_code: str, frozen_dir: str, metadata: str | None) -> None:
    from scripts.frozen_acceptance import (
        FrozenAcceptanceError,
        validate_mysql_frozen as run_frozen,
    )

    make_llm_client()
    try:
        run_frozen(
            stock_code,
            frozen_dir,
            metadata,
            lambda: create_acceptance_database(get_settings()),
        )
    except FrozenAcceptanceError as exc:
        raise AcceptanceError(str(exc)) from exc


def verify_database_identity(engine, name: str) -> None:
    """Check the actual connection, not just the configured URL, before migration."""
    from sqlalchemy import text

    if (engine.url.host != "127.0.0.1" or engine.url.port not in {3307, 3308}
            or engine.url.database != name
            or not re.fullmatch(r"ai_quant_v1_acceptance_\d{8}_\d{6}_\d{6}", name)):
        raise AcceptanceError("database isolation check failed")
    with engine.connect() as connection:
        version, port, database = connection.execute(
            text("SELECT VERSION(), @@port, DATABASE()")
        ).one()
    if not str(version).startswith("8.0.") or "MariaDB" in str(version) or int(port) != engine.url.port or database != name:
        raise AcceptanceError("connected database identity check failed")
    print(json.dumps({"mysql_version": version, "port": port, "database": database}), flush=True)


def record_response_mismatches(record, data: dict) -> list[str]:
    """Shared with ``scripts/frozen_acceptance.py``; keep the name stable."""
    mismatches = []
    if record.id != data.get("report_id"):
        mismatches.append("report_id")
    ignored = {"report_id", "snapshot_status", "created_at", "data_as_of"}
    mismatches.extend(
        key
        for key, value in data.items()
        if key not in ignored and getattr(record, key) != value
    )
    api_data_as_of = datetime.fromisoformat(data["data_as_of"].replace("Z", "+00:00"))
    if record.data_as_of != api_data_as_of.replace(tzinfo=None):
        mismatches.append("data_as_of")
    return mismatches


def _record_matches_response(record, data: dict) -> bool:
    return not record_response_mismatches(record, data)


def install_acceptance_headers(app, package=None) -> None:
    @app.middleware("http")
    async def acceptance_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Acceptance-Mode"] = "frozen" if package else "live"
        if package:
            response.headers["X-Acceptance-Start"] = package.start_date.isoformat()
            response.headers["X-Acceptance-End"] = package.end_date.isoformat()
        return response


def serve_acceptance(frozen_dir: str | None, metadata: str | None, port: int = 8000) -> None:
    if "backend.app.db.session" in sys.modules:
        raise AcceptanceError("run --serve in a fresh process before importing the backend")
    # Reserve the socket throughout preparation to avoid a check/bind race.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise AcceptanceError(f"HTTP port {port} is occupied or unavailable") from exc
        package = None
        if frozen_dir:
            from scripts.frozen_acceptance import load_package, compare_package_quant
            package = load_package(frozen_dir, metadata)
            compare_package_quant(package)
        make_llm_client()
        name = create_acceptance_database(get_settings())
        os.environ["MYSQL_DATABASE"] = name
        os.environ["APP_DEBUG"] = "false"
        get_settings.cache_clear()
        from backend.app.db.session import engine
        from backend.app.db.migrations import apply_migrations
        from backend.app.main import create_app
        import uvicorn

        try:
            verify_database_identity(engine, name)
            version = apply_migrations(engine)
            app = create_app()
            if package:
                from scripts.frozen_acceptance import install_frozen_overrides
                install_frozen_overrides(app, package)
            install_acceptance_headers(app, package)
            print(json.dumps({"schema_version": version, "mode": "frozen" if package else "live",
                              "url": f"http://127.0.0.1:{port}", "database": name}), flush=True)
            # Server errors are represented by sanitized API error codes. Avoid
            # third-party traceback logs containing database connection details.
            config = uvicorn.Config(app, host="127.0.0.1", port=port, reload=False,
                                    log_level="critical", access_log=False)
            uvicorn.Server(config).run(sockets=[listener])
        finally:
            engine.dispose()


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.metadata and not args.frozen_dir:
            raise AcceptanceError("--metadata requires --frozen-dir")
        if not re.fullmatch(r"\d{6}", args.stock_code, flags=re.ASCII):
            raise InvalidParameterError()
        if args.llm_only:
            if args.frozen_dir:
                raise AcceptanceError("--llm-only cannot be combined with a frozen package")
            asyncio.run(validate_llm_connection())
        elif args.migration_only:
            if args.frozen_dir:
                raise AcceptanceError("--migration-only cannot use a frozen package")
            validate_mysql_v1_upgrade()
        elif args.serve:
            serve_acceptance(args.frozen_dir, args.metadata, args.port)
        elif args.mysql:
            if args.frozen_dir:
                validate_mysql_frozen(args.stock_code, args.frozen_dir, args.metadata)
            else:
                validate_mysql(args.stock_code)
        else:
            if args.frozen_dir:
                raise AcceptanceError("--frozen-dir requires --mysql or --serve")
            asyncio.run(validate(args.stock_code))
    except Exception as exc:
        # Raw SQLAlchemy/provider exceptions may embed passwords, URLs or headers.
        detail = str(exc) if isinstance(exc, AcceptanceError) else "upstream validation failed"
        code = exc.code if isinstance(exc, ApplicationError) else (
            50005 if isinstance(exc, AIServiceError) else None
        )
        original = getattr(exc, "orig", None)
        driver_args = getattr(original, "args", ())
        driver_code = driver_args[0] if driver_args and isinstance(driver_args[0], int) else None
        print(json.dumps({"validated": False, "error_type": type(exc).__name__,
                          "business_code": code, "driver_code": driver_code,
                          "detail": detail}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
