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

    def save(self, analysis) -> None:
        self.saved.append(analysis)


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

    if settings.mysql_host not in {"127.0.0.1", "localhost", "::1"}:
        raise AcceptanceError("acceptance database must be on localhost")
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
        if engine.url.database != name:
            raise AcceptanceError("database isolation check failed")
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
            if any(getattr(record, key) != value for key, value in data.items()):
                raise AcceptanceError("persisted report does not match API response")
            print(json.dumps({"validated": True, "database": name,
                              "report_id": record.id, "stock_code": record.stock_code,
                              "model": record.model_name}, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if not re.fullmatch(r"\d{6}", args.stock_code, flags=re.ASCII):
            raise InvalidParameterError()
        if args.llm_only:
            asyncio.run(validate_llm_connection())
        elif args.mysql:
            validate_mysql(args.stock_code)
        else:
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
