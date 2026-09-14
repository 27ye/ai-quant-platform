"""Frozen-sample acceptance helpers for the real AI route.

The frozen mode replaces only external stock/news/calendar inputs and the
default date window. It keeps B's MarketDataService, C's quant pipeline, the
FastAPI route, LLM client, migrations and SQLAlchemy repository in the path.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional, Sequence

import pandas as pd
from fastapi import Depends

from backend.app.quant.config import QuantConfig
from scripts import verify_frozen_mysql


class FrozenAcceptanceError(RuntimeError):
    """Use only fixed, credential-free messages."""


@dataclass(frozen=True)
class FrozenPackage:
    root: Path
    metadata_path: Path
    metadata: dict
    stock_code: str
    start_date: date
    end_date: date
    bars: list
    calendar: Any
    stock_info: dict
    readback: list
    news: list[dict]


def load_package(frozen_dir: str, metadata: Optional[str] = None) -> FrozenPackage:
    try:
        root = Path(frozen_dir).resolve()
        if not root.is_dir():
            raise FrozenAcceptanceError("frozen directory is unavailable")
        metadata_path = verify_frozen_mysql.resolve_metadata_path(root, metadata).resolve()
        _assert_inside(root, metadata_path)
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        _validate_metadata_contract(meta)

        stock_code = str(meta["stock_code"])
        start_date = date.fromisoformat(meta["actual_start_date"])
        end_date = date.fromisoformat(meta["actual_end_date"])
        kline_path = _checked_file(root, meta["kline"])
        calendar_path = _checked_file(root, meta["calendar"])
        stock_path = _checked_file(root, meta["stock"])
        readback_path = _checked_file(root, meta["readback"])
        news_path = _optional_checked_file(root, meta.get("news"))

        bars = verify_frozen_mysql.load_bars(kline_path)
        calendar = verify_frozen_mysql.load_calendar(calendar_path)
        stock_info = json.loads(stock_path.read_text(encoding="utf-8"))
        readback = verify_frozen_mysql.load_bars(readback_path)
        news = json.loads(news_path.read_text(encoding="utf-8")) if news_path else []
    except FrozenAcceptanceError:
        raise
    except SystemExit as exc:
        raise FrozenAcceptanceError("frozen package verification failed") from exc
    except Exception as exc:
        raise FrozenAcceptanceError("frozen package is invalid") from exc

    if len(bars) != int(meta["rows"]) or len(readback) != int(meta["rows"]):
        raise FrozenAcceptanceError("frozen row count does not match metadata")
    if any(row.stock_code != stock_code for row in bars + readback):
        raise FrozenAcceptanceError("frozen stock code does not match metadata")
    if min(row.trade_date for row in bars) != start_date or max(row.trade_date for row in bars) != end_date:
        raise FrozenAcceptanceError("frozen date window does not match metadata")
    if calendar.count_between(start_date, end_date) != int(meta["rows"]):
        raise FrozenAcceptanceError("frozen calendar cannot prove the data window")
    if stock_info.get("stock_code") != stock_code or not stock_info.get("stock_name"):
        raise FrozenAcceptanceError("frozen stock snapshot is incomplete")

    return FrozenPackage(
        root=root,
        metadata_path=metadata_path,
        metadata=meta,
        stock_code=stock_code,
        start_date=start_date,
        end_date=end_date,
        bars=bars,
        calendar=calendar,
        stock_info=stock_info,
        readback=readback,
        news=news,
    )


def compare_package_quant(package: FrozenPackage) -> dict:
    result = verify_frozen_mysql.compare_analyses(package.bars, package.readback)
    if not result["data_equal"] or not result["analysis_equal"]:
        raise FrozenAcceptanceError("frozen direct/readback quant comparison failed")
    expectations = package.metadata["quant_expectations"]
    direct = result["direct"]
    if direct["meta"]["parameters"] != package.metadata["quant_config"]:
        raise FrozenAcceptanceError("frozen quant config expectation mismatch")
    _assert_expected("rows", direct["meta"]["rows"], package.metadata["rows"])
    _assert_expected("score", direct["score"]["score"], expectations.get("score"))
    _assert_expected("order_count", direct["backtest"].get("order_count"), expectations.get("order_count"))
    _assert_expected(
        "equity_curve_points",
        len(direct["backtest"].get("equity_curve", [])),
        expectations.get("equity_curve_points"),
    )
    _assert_expected("total_return", direct["backtest"].get("total_return"), expectations.get("total_return"))
    _assert_expected("final_equity", direct["backtest"].get("final_equity"), expectations.get("final_equity"))
    return result


def validate_mysql_frozen(stock_code: str, frozen_dir: str, metadata: Optional[str], create_db) -> None:
    if "backend.app.db.session" in sys.modules:
        raise FrozenAcceptanceError("run frozen mysql validation in a fresh process")
    package = load_package(frozen_dir, metadata)
    if stock_code != package.stock_code:
        raise FrozenAcceptanceError("requested stock does not match frozen package")
    comparison = compare_package_quant(package)

    name = create_db()
    os.environ["MYSQL_DATABASE"] = name

    from backend.app.core.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from backend.app.db.migrations import apply_migrations
    from backend.app.db.session import SessionLocal, engine
    from backend.app.main import create_app
    from backend.app.models.ai_analysis import AIAnalysis
    from backend.app.services.market_data_service import MarketDataRepository

    try:
        from scripts.validate_ai_analysis import verify_database_identity

        verify_database_identity(engine, name)
        apply_migrations(engine)
        app = create_app()
        install_frozen_overrides(app, package)

        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.get(f"/api/v1/stocks/{stock_code}/kline")
            second = client.get(f"/api/v1/stocks/{stock_code}/kline")
            _assert_api_success(first, "first frozen kline query failed")
            _assert_api_success(second, "cached frozen kline query failed")
            _assert_kline_matches_package(first.json()["data"], package, "first query")
            _assert_kline_matches_package(second.json()["data"], package, "cache hit")

            # Exercise B's completeness policy against the isolated acceptance
            # database: remove a real middle segment, then require the real
            # MarketDataService/calendar/provider path to restore it.
            from backend.app.models.stock_daily import StockDaily
            missing_dates = [row.trade_date for row in package.bars[100:105]]
            with SessionLocal() as db:
                deleted = db.query(StockDaily).filter(
                    StockDaily.stock_code == stock_code,
                    StockDaily.trade_date.in_(missing_dates),
                ).delete(synchronize_session=False)
                db.commit()
            if deleted != len(missing_dates):
                raise FrozenAcceptanceError("frozen gap preparation did not remove expected rows")
            repaired = client.get(f"/api/v1/stocks/{stock_code}/kline")
            _assert_api_success(repaired, "frozen middle-gap refresh failed")
            _assert_kline_matches_package(repaired.json()["data"], package, "gap repair")
            response = client.post("/api/v1/ai/analyze", json={"stock_code": stock_code})
        _assert_api_success(response, "frozen AI API did not return success")

        with SessionLocal() as db:
            db_readback = MarketDataRepository(db).list_daily(stock_code, package.start_date, package.end_date)
            _assert_analysis_matches_package(db_readback, package, "mysql readback")
            records = db.query(AIAnalysis).filter_by(stock_code=stock_code).all()
            if len(records) != 1:
                raise FrozenAcceptanceError("expected exactly one persisted frozen report")
            record = records[0]
            data = response.json()["data"]
            if any(getattr(record, key) != value for key, value in data.items()):
                raise FrozenAcceptanceError("persisted report does not match API response")
            print(json.dumps({
                "validated": True,
                "mode": "frozen_api_mysql",
                "database": name,
                "stock_code": stock_code,
                "report_id": record.id,
                "score": comparison["direct"]["score"]["score"],
                "rows": len(package.bars),
                "news_items": len(package.news),
            }, ensure_ascii=False), flush=True)
    finally:
        engine.dispose()


def install_frozen_overrides(app, package: FrozenPackage) -> None:
    """Install frozen external-source overrides while preserving real routes/services."""
    from backend.app.api.v1 import dependencies
    from backend.app.db.session import get_db
    from backend.app.services.market_data_service import MarketDataRepository, MarketDataService
    from backend.app.services.news_service import NewsRepository, NewsService
    from backend.app.services.stock_service import StockService

    provider = FrozenStockProvider(package)
    app.dependency_overrides[dependencies.get_data_provider] = lambda: provider
    app.dependency_overrides[dependencies.get_stock_service] = lambda: StockService(provider=provider)
    app.dependency_overrides[dependencies.get_trading_calendar_provider] = lambda: package.calendar

    def market_override(db=Depends(get_db)):
        return FrozenMarketDataSource(
            MarketDataService(
                stock_service=StockService(provider=provider),
                repository=MarketDataRepository(db),
                trading_days=package.calendar.as_callable(),
            ),
            package,
        )

    def news_override(db=Depends(get_db)):
        return NewsService(provider=provider, repository=NewsRepository(db))

    app.dependency_overrides[dependencies.get_market_data_source] = market_override
    app.dependency_overrides[dependencies.get_news_analysis_service] = news_override


class FrozenStockProvider:
    def __init__(self, package: FrozenPackage) -> None:
        self.package = package

    def get_daily_kline(self, stock_code: str, start_date: date, end_date: date, adjust: str = "qfq") -> pd.DataFrame:
        if stock_code != self.package.stock_code or adjust != "qfq":
            from backend.app.data.providers.base import InvalidStockCodeError

            raise InvalidStockCodeError("stock code is outside the frozen package")
        _assert_in_window(start_date, end_date, self.package)
        frame = pd.DataFrame([row.model_dump() for row in self.package.bars])
        return frame[(frame["trade_date"] >= start_date) & (frame["trade_date"] <= end_date)]

    def get_stock_info(self, stock_code: str) -> dict:
        if stock_code != self.package.stock_code:
            from backend.app.data.providers.base import InvalidStockCodeError

            raise InvalidStockCodeError("stock code is outside the frozen package")
        return dict(self.package.stock_info)

    def search_stocks(self, keyword: str) -> List[dict]:
        info = self.package.stock_info
        if keyword in info["stock_code"] or keyword in info["stock_name"]:
            return [{"stock_code": info["stock_code"], "stock_name": info["stock_name"]}]
        return []

    def get_stock_news(self, stock_code: str, limit: int = 10) -> List[dict]:
        if stock_code != self.package.stock_code:
            from backend.app.data.providers.base import InvalidStockCodeError

            raise InvalidStockCodeError("stock code is outside the frozen package")
        return self.package.news[:limit]


class FrozenMarketDataSource:
    def __init__(self, service: Any, package: FrozenPackage) -> None:
        self._service = service
        self._package = package

    def query_daily(self, stock_code: str, start_date: Optional[date] = None, end_date: Optional[date] = None, **kwargs):
        start = start_date or self._package.start_date
        end = end_date or self._package.end_date
        _assert_in_window(start, end, self._package)
        return self._service.query_daily(stock_code, start, end, **kwargs)

    def sync_daily(self, stock_code: str, start_date: date, end_date: date, **kwargs):
        _assert_in_window(start_date, end_date, self._package)
        return self._service.sync_daily(stock_code, start_date, end_date, **kwargs)


def _validate_metadata_contract(meta: dict) -> None:
    required = [
        "stock_code", "actual_start_date", "actual_end_date", "captured_at",
        "rows", "kline", "calendar", "stock", "readback", "quant_config",
        "quant_expectations",
    ]
    if any(key not in meta for key in required):
        raise FrozenAcceptanceError("frozen metadata is missing required fields")
    if str(meta["stock_code"]) != "600519":
        raise FrozenAcceptanceError("frozen metadata stock must be 600519 for V1 acceptance")
    if not re.fullmatch(r"\d{6}", str(meta["stock_code"])):
        raise FrozenAcceptanceError("frozen stock code is invalid")
    captured = datetime.fromisoformat(str(meta["captured_at"]).replace("Z", "+00:00"))
    if captured.tzinfo is None:
        raise FrozenAcceptanceError("frozen captured_at must include timezone")
    if int(meta["rows"]) != 403:
        raise FrozenAcceptanceError("frozen metadata rows must be 403 for V1 600519 acceptance")
    if meta.get("adjust", meta.get("qfq", "qfq")) != "qfq":
        raise FrozenAcceptanceError("frozen metadata adjust must be qfq")
    if meta["quant_config"] != QuantConfig().to_parameters():
        raise FrozenAcceptanceError("frozen metadata quant_config must match default QuantConfig")
    expectations = meta["quant_expectations"]
    required_expectations = {
        "score": 33,
        "order_count": 24,
        "equity_curve_points": 403,
        "total_return": -0.09165774117956027,
        "final_equity": 90834.22588204397,
    }
    if expectations != required_expectations:
        raise FrozenAcceptanceError("frozen metadata quant expectations do not match V1 acceptance")


def _checked_file(root: Path, spec: dict) -> Path:
    path = (root / spec["file"]).resolve()
    _assert_inside(root, path)
    verify_frozen_mysql.assert_hash_matches(path, spec["sha256"])
    return path


def _optional_checked_file(root: Path, spec: Optional[dict]) -> Optional[Path]:
    if not spec:
        return None
    return _checked_file(root, spec)


def _assert_inside(root: Path, path: Path) -> None:
    if root != path and root not in path.parents:
        raise FrozenAcceptanceError("frozen file path escapes the package directory")


def _assert_in_window(start: date, end: date, package: FrozenPackage) -> None:
    if start < package.start_date or end > package.end_date or start > end:
        raise FrozenAcceptanceError("requested date range is outside the frozen package")


def _assert_expected(name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise FrozenAcceptanceError(f"frozen {name} expectation mismatch")


def _assert_api_success(response, detail: str) -> None:
    try:
        body = response.json()
    except ValueError as exc:
        raise FrozenAcceptanceError(detail) from exc
    if response.status_code != 200 or body.get("code") != 0:
        raise FrozenAcceptanceError(detail)


def _assert_kline_matches_package(records: list[dict], package: FrozenPackage, stage: str) -> None:
    from backend.app.schemas.stock import DailyKlineSchema

    try:
        rows = [DailyKlineSchema.model_validate(record) for record in records]
    except Exception as exc:
        raise FrozenAcceptanceError(f"frozen {stage} kline schema mismatch") from exc
    _assert_analysis_matches_package(rows, package, stage)


def _assert_analysis_matches_package(rows: list, package: FrozenPackage, stage: str) -> None:
    result = verify_frozen_mysql.compare_analyses(package.bars, rows)
    if not result["data_equal"] or not result["analysis_equal"]:
        raise FrozenAcceptanceError(f"frozen {stage} full quant comparison failed")
