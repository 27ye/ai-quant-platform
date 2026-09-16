"""V2 B2: daily-bar provenance plus the data-status endpoint."""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1.dependencies import get_data_status_service
from backend.app.core.errors import DataProviderError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.db.migrations import apply_migrations
from backend.app.main import app
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema
from backend.app.services.data_status_service import (
    MODE_UNKNOWN,
    STATUS_FRESH,
    STATUS_STALE,
    STATUS_UNKNOWN,
    DataStatusService,
)
from backend.app.services.market_data_service import (
    MarketDataRepository,
    MarketDataService,
)
from backend.app.services.stock_catalog_service import (
    StockCatalogRepository,
    StockCatalogService,
)

STOCK_CODE = "600519"


def _session() -> Session:
    engine = create_engine("sqlite://")
    apply_migrations(engine)
    return Session(bind=engine)


def _bar(trade_date, close=100.0):
    return DailyKlineSchema(
        stock_code=STOCK_CODE,
        trade_date=trade_date,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        amount=100000.0,
        turnover_rate=0.01,
        change_pct=0.02,
    )


def _seed_bars(repository: MarketDataRepository, start: date, count: int) -> None:
    repository.upsert_daily([_bar(start + timedelta(days=i)) for i in range(count)])


class _FakeCatalogProvider:
    def search_stocks(self, keyword):  # pragma: no cover - not used here
        return []

    def fetch_stock_catalog(self):
        return [
            {"stock_code": STOCK_CODE, "stock_name": "贵州茅台"},
            {"stock_code": "000001", "stock_name": "平安银行"},
        ]

    last_catalog_source = "fake-catalog"


def _sync_catalog(session, monkeypatch):
    from backend.app.services import stock_catalog_service as module

    monkeypatch.setattr(module, "MIN_CATALOG_ROWS", 2)
    StockCatalogService(
        provider=_FakeCatalogProvider(),
        repository=StockCatalogRepository(session),
    ).sync()


def _service(session, *, trading_days, today=None):
    return DataStatusService(
        market_repository=MarketDataRepository(session),
        catalog_repository=StockCatalogRepository(session),
        trading_days=trading_days,
        today=today or (lambda: date(2026, 9, 14)),
    )


def test_status_reports_catalog_and_kline_provenance(monkeypatch):
    with _session() as session:
        _sync_catalog(session, monkeypatch)
        repository = MarketDataRepository(session)
        start = date(2025, 1, 2)
        _seed_bars(repository, start, 5)
        repository.upsert_daily_sync(
            stock_code=STOCK_CODE,
            mode="live",
            source="akshare.stock_zh_a_hist",
            row_count=5,
            first_trade_date=start,
            last_trade_date=start + timedelta(days=4),
            at=datetime(2026, 9, 14, 1, 0, 0),
        )

        status = _service(session, trading_days=lambda a, b: 5).get_status(STOCK_CODE)

        assert status.catalog.synced is True
        assert status.catalog.row_count == 2
        assert status.catalog.source == "fake-catalog"
        assert status.kline.mode == "live"
        assert status.kline.source == "akshare.stock_zh_a_hist"
        assert status.kline.rows == 5
        assert status.kline.first_trade_date == start
        assert status.kline.last_trade_date == start + timedelta(days=4)
        assert status.kline.last_refreshed_at == datetime(
            2026, 9, 14, 1, 0, 0, tzinfo=status.as_of.tzinfo
        )
        assert status.kline.coverage == "known"
        assert status.kline.expected_trading_days == 5
        assert status.kline.freshness.status == STATUS_STALE  # 2026-09-14 vs 2026-01-06
        assert status.kline.freshness.stale_days == (
            date(2026, 9, 14) - (start + timedelta(days=4))
        ).days
        assert status.as_of.tzinfo is not None  # API always states the zone


def test_freshness_is_fresh_when_within_max_stale_days():
    with _session() as session:
        repository = MarketDataRepository(session)
        last = date(2026, 9, 13)
        repository.upsert_daily([_bar(last - timedelta(days=1)), _bar(last)])

        status = _service(session, trading_days=lambda a, b: 2).get_status(STOCK_CODE)

        assert status.kline.freshness.status == STATUS_FRESH
        assert status.kline.freshness.stale_days == 1
        assert status.kline.freshness.max_stale_days == 3


def test_mode_is_unknown_without_refresh_metadata():
    """Bars loaded before V2 have no provenance: report unknown, never invent."""
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 2)
        _seed_bars(repository, start, 3)

        status = _service(session, trading_days=lambda a, b: 3).get_status(STOCK_CODE)

        assert status.kline.mode == MODE_UNKNOWN
        assert status.kline.source is None
        assert status.kline.rows == 3
        # The bar write time is still honest information to expose.
        assert status.kline.last_refreshed_at is not None


def test_coverage_is_unknown_when_calendar_cannot_prove():
    with _session() as session:
        repository = MarketDataRepository(session)
        _seed_bars(repository, date(2025, 1, 2), 3)

        status = _service(session, trading_days=lambda a, b: None).get_status(STOCK_CODE)

        assert status.kline.coverage == STATUS_UNKNOWN
        assert status.kline.expected_trading_days is None
        assert status.kline.rows == 3  # still reported, just not proven complete


def test_calendar_failure_is_a_provider_error():
    def _boom(start, end):
        raise RuntimeError("calendar down")

    with _session() as session:
        _seed_bars(MarketDataRepository(session), date(2025, 1, 2), 3)
        with pytest.raises(DataProviderError):
            _service(session, trading_days=_boom).get_status(STOCK_CODE)


def test_empty_stock_reports_zero_and_unknown_freshness():
    with _session() as session:
        status = _service(session, trading_days=lambda a, b: 0).get_status("000001")

        assert status.kline.rows == 0
        assert status.kline.mode == MODE_UNKNOWN
        assert status.kline.coverage == STATUS_UNKNOWN
        assert status.kline.freshness.status == STATUS_UNKNOWN
        assert status.catalog.synced is False


def test_invalid_code_is_rejected():
    with _session() as session:
        with pytest.raises(InvalidStockCodeError):
            _service(session, trading_days=lambda a, b: 0).get_status("60051")


class _FakeStockService:
    def __init__(self, rows=None, error=None, source="akshare.stock_zh_a_hist"):
        self._rows = rows or []
        self._error = error
        self.last_kline_source = source

    def get_daily_kline(self, stock_code, start_date=None, end_date=None, min_rows=60):
        if self._error is not None:
            raise self._error
        return self._rows


def test_sync_daily_records_provenance_on_success():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 2)
        rows = [_bar(start + timedelta(days=i)) for i in range(3)]
        service = MarketDataService(
            stock_service=_FakeStockService(rows=rows),
            repository=repository,
        )

        service.sync_daily(STOCK_CODE, start, start + timedelta(days=2), min_rows=3)

        state = repository.get_daily_sync(STOCK_CODE)
        assert state is not None
        assert state.mode == "live"
        assert state.source == "akshare.stock_zh_a_hist"
        assert state.row_count == 3
        assert state.first_trade_date == start
        assert state.last_trade_date == start + timedelta(days=2)
        assert state.last_success_at is not None
        assert state.last_error is None


def test_sync_daily_failure_keeps_previous_success():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 2)
        rows = [_bar(start + timedelta(days=i)) for i in range(3)]
        ok = MarketDataService(stock_service=_FakeStockService(rows=rows), repository=repository)
        ok.sync_daily(STOCK_CODE, start, start + timedelta(days=2), min_rows=3)
        first = repository.get_daily_sync(STOCK_CODE)
        assert first is not None and first.last_success_at is not None

        failing = MarketDataService(
            stock_service=_FakeStockService(error=StockDataProviderError("kline host down")),
            repository=repository,
        )
        with pytest.raises(StockDataProviderError):
            failing.sync_daily(STOCK_CODE, start, start + timedelta(days=2), min_rows=3)

        after = repository.get_daily_sync(STOCK_CODE)
        assert after is not None
        assert after.last_success_at == first.last_success_at  # success kept
        assert after.last_attempt_at >= first.last_attempt_at
        assert "kline host down" in (after.last_error or "")


def test_status_exposes_last_failed_attempt_without_losing_success():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 2)
        _seed_bars(repository, start, 3)
        repository.upsert_daily_sync(
            stock_code=STOCK_CODE,
            mode="live",
            source="akshare.stock_zh_a_hist",
            row_count=3,
            first_trade_date=start,
            last_trade_date=start + timedelta(days=2),
            at=datetime(2026, 9, 13, 1, 0, 0),
        )
        repository.mark_daily_sync_failure(
            stock_code=STOCK_CODE,
            error="StockDataProviderError: kline host down",
            at=datetime(2026, 9, 14, 2, 0, 0),
        )

        status = _service(session, trading_days=lambda a, b: 3).get_status(STOCK_CODE)

        # The last SUCCESS still describes the stored bars ...
        assert status.kline.mode == "live"
        assert status.kline.source == "akshare.stock_zh_a_hist"
        assert status.kline.last_refreshed_at == datetime(
            2026, 9, 13, 1, 0, 0, tzinfo=status.as_of.tzinfo
        )
        # ... while the failed attempt is visible instead of silently swallowed.
        assert status.kline.last_attempt_at == datetime(
            2026, 9, 14, 2, 0, 0, tzinfo=status.as_of.tzinfo
        )
        assert "kline host down" in (status.kline.last_error or "")


def test_data_status_endpoint_returns_payload(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    session = Session(bind=engine)
    repository = MarketDataRepository(session)
    start = date(2025, 1, 2)
    _seed_bars(repository, start, 3)
    service = DataStatusService(
        market_repository=repository,
        catalog_repository=StockCatalogRepository(session),
        trading_days=lambda a, b: 3,
        today=lambda: date(2026, 9, 14),
    )
    app.dependency_overrides[get_data_status_service] = lambda: service

    try:
        response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/data-status")
        bad = TestClient(app).get("/api/v1/stocks/abc/data-status")
    finally:
        app.dependency_overrides.clear()
        session.close()

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["stock_code"] == STOCK_CODE
    assert body["data"]["kline"]["rows"] == 3
    assert body["data"]["kline"]["coverage"] == "known"
    assert body["data"]["kline"]["mode"] == "unknown"  # no metadata written
    assert bad.status_code == 400
    assert bad.json()["code"] == 40001
