"""V2 V03: error-code contract at the API layer.

Each failure mode must stay recognisable and must never be reported as a
successful-but-empty result:

* provider/source failure  -> ``50001`` (HTTP 502)
* database failure         -> ``50002`` (HTTP 500)
* V2 engine unavailable    -> ``50004`` (HTTP 500)
* insufficient warmup/data -> ``40003`` (HTTP 422)
* unknown backtest id      -> ``40005`` (HTTP 404)
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1.dependencies import (
    get_backtest_repository,
    get_backtest_service,
    get_data_status_service,
    get_stock_catalog_service,
)
from backend.app.data.providers.base import StockDataProvider, StockDataProviderError
from backend.app.db.migrations import apply_migrations
from backend.app.main import app
from backend.app.models.stock_basic import StockBasic
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.backtest_service import BacktestRepository, BacktestService
from backend.app.services.data_status_service import DataStatusService
from backend.app.services.market_data_service import MarketDataRepository
from backend.app.services.quant_service import QuantService
from backend.app.services.stock_catalog_service import (
    StockCatalogRepository,
    StockCatalogService,
)
from backend.app.services.stock_service import StockService

STOCK_CODE = "600519"


class _FailingProvider(StockDataProvider):
    def get_daily_kline(self, *args, **kwargs):
        raise StockDataProviderError("spot snapshot unavailable")

    def search_stocks(self, keyword):
        raise StockDataProviderError("spot snapshot unavailable")


class _NoopStockService:
    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("not used")


def _engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_search_reports_50006_when_the_catalog_was_never_synced():
    """V2 B1: a cold start reports the catalog state instead of guessing.

    The removed provider fallback could never succeed - a full-market spot snapshot
    needs ~34 s against a 4 s retry budget - so it only produced a 50001 after a
    multi-second wait. The provider must not be touched at all.
    """
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)
    provider = _FailingProvider()
    service = StockCatalogService(
        provider=provider, repository=StockCatalogRepository(session)
    )
    app.dependency_overrides[get_stock_catalog_service] = lambda: service
    try:
        response = TestClient(app).get("/api/v1/stocks/search?keyword=贵州")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 503
    assert response.json()["code"] == 50006
    assert response.json()["data"] is None


def test_search_still_works_after_a_failed_refresh(monkeypatch):
    """C's chained HTTP case: a failed refresh is not "never synced".

    The catalog rows and ``last_success_at`` survive a failed refresh, so search must
    keep answering locally instead of turning that transient error into 50006.
    """
    from backend.app.services import stock_catalog_service as catalog_module

    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 1)
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)

    class _CatalogProvider(StockDataProvider):
        last_catalog_source = "probe"

        def __init__(self) -> None:
            self.fail = False

        def get_daily_kline(self, *args, **kwargs):  # pragma: no cover - unused
            raise NotImplementedError

        def search_stocks(self, keyword):  # pragma: no cover - must not be called
            raise AssertionError("search must not reach the provider")

        def fetch_stock_catalog(self):
            if self.fail:
                raise StockDataProviderError("upstream unavailable")
            return [{"stock_code": STOCK_CODE, "stock_name": "贵州茅台"}]

    provider = _CatalogProvider()
    service = StockCatalogService(
        provider=provider, repository=StockCatalogRepository(session)
    )
    service.sync()

    provider.fail = True  # the next refresh fails
    with pytest.raises(StockDataProviderError):
        service.sync()

    app.dependency_overrides[get_stock_catalog_service] = lambda: service
    try:
        response = TestClient(app).get("/api/v1/stocks/search?keyword=茅台")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 200, response.text
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["stock_code"] == STOCK_CODE


def test_search_reports_50002_when_the_catalog_table_is_missing(monkeypatch):
    from backend.app.services import stock_catalog_service as catalog_module

    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 1)
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)

    class _CatalogProvider(StockDataProvider):
        last_catalog_source = "probe"

        def get_daily_kline(self, *args, **kwargs):  # pragma: no cover - unused
            raise NotImplementedError

        def search_stocks(self, keyword):  # pragma: no cover - not used
            raise AssertionError("search must not reach the provider")

        def fetch_stock_catalog(self):
            return [{"stock_code": STOCK_CODE, "stock_name": "贵州茅台"}]

    # A complete sync state, and then the table it points at disappears.
    StockCatalogService(
        provider=_CatalogProvider(), repository=StockCatalogRepository(session)
    ).sync()
    StockBasic.__table__.drop(engine)

    service = StockCatalogService(
        provider=_FailingProvider(), repository=StockCatalogRepository(session)
    )
    app.dependency_overrides[get_stock_catalog_service] = lambda: service
    try:
        response = TestClient(app).get("/api/v1/stocks/search?keyword=贵州")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 500
    assert response.json()["code"] == 50002


def test_data_status_reports_50002_when_the_bars_table_is_missing():
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)
    from backend.app.models.stock_daily import StockDaily

    StockDaily.__table__.drop(engine)
    service = DataStatusService(
        market_repository=MarketDataRepository(session),
        catalog_repository=StockCatalogRepository(session),
        trading_days=lambda a, b: 0,
    )
    app.dependency_overrides[get_data_status_service] = lambda: service
    try:
        response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/data-status")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 500
    assert response.json()["code"] == 50002


def test_backtest_history_reports_50002_when_the_table_is_missing():
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)
    from backend.app.models.backtest_result import BacktestResult

    BacktestResult.__table__.drop(engine)
    app.dependency_overrides[get_backtest_repository] = lambda: BacktestRepository(session)
    try:
        response = TestClient(app).get("/api/v1/backtests")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 500
    assert response.json()["code"] == 50002


class _ShortHistorySource:
    """Provides only 20 bars, far fewer than the warmup a long=120 window needs."""

    def query_daily(self, stock_code, start_date=None, end_date=None, **kwargs):
        rows = []
        for index in range(20):
            close = 100.0 + index
            rows.append(
                DailyKlineSchema(
                    stock_code=stock_code,
                    trade_date=date(2025, 1, 1) + timedelta(days=index),
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=1000,
                    amount=100000.0,
                    turnover_rate=0.01,
                    change_pct=0.02,
                )
            )
        return rows


class _StubCWindowedEntry:
    """Minimal stand-in for C's V2 entry points.

    C's code is still local-only, so without a stub a ``v2_windowed`` request
    fails earlier with ``50004`` - a different failure mode from the warmup check
    this test exercises.
    """

    parameters_unset = object()
    #: C's exception classes; empty here because this stub never violates them.
    parameter_errors: tuple = ()
    data_errors: tuple = ()

    def resolve(self, raw_parameters):
        required = int(raw_parameters.get("ma_long_period", 20))
        return type("_RequestConfig", (), {"required_warmup_rows": required})()

    def validate_window(self, start_date, end_date):
        return start_date, end_date

    def run(self, frame, *, start_date, end_date, parameters):  # pragma: no cover
        raise AssertionError("warmup must fail before C is called")


def test_backtest_reports_40003_when_warmup_data_is_insufficient():
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)
    repository = BacktestRepository(session)
    service = BacktestService(
        quant_service=QuantService(
            stock_service=StockService(provider=_FailingProvider()),
            market_data_source=_ShortHistorySource(),
        ),
        market_data_source=_ShortHistorySource(),
        repository=repository,
        c_entry_loader=_StubCWindowedEntry,
    )
    app.dependency_overrides[get_backtest_service] = lambda: service
    app.dependency_overrides[get_backtest_repository] = lambda: repository
    try:
        response = TestClient(app).post(
            "/api/v1/backtests",
            json={
                "stock_code": STOCK_CODE,
                "start_date": "2025-01-15",
                "end_date": "2025-01-20",
                "parameters": {"ma_long_period": 120},
            },
        )
        history = TestClient(app).get("/api/v1/backtests")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 422
    assert response.json()["code"] == 40003
    # A rejected run must not leave a success record behind.
    assert history.json()["data"]["total"] == 0


def test_backtest_reports_50004_when_c_v2_entry_is_unavailable():
    """C: unavailable V2 must fail loudly, never masquerade as a V1 success."""
    engine = _engine()
    apply_migrations(engine)
    session = Session(bind=engine)
    repository = BacktestRepository(session)
    service = BacktestService(
        quant_service=QuantService(
            stock_service=StockService(provider=_FailingProvider()),
            market_data_source=_ShortHistorySource(),
        ),
        market_data_source=_ShortHistorySource(),
        repository=repository,
        c_entry_loader=lambda: None,
    )
    app.dependency_overrides[get_backtest_service] = lambda: service
    app.dependency_overrides[get_backtest_repository] = lambda: repository
    try:
        response = TestClient(app).post(
            "/api/v1/backtests",
            json={"stock_code": STOCK_CODE, "parameters": {}},
        )
        history = TestClient(app).get("/api/v1/backtests")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 500
    assert response.json()["code"] == 50004
    assert history.json()["data"]["total"] == 0
