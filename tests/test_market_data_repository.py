from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError, InsufficientStockDataError
from backend.app.db.migrations import apply_migrations
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema
from backend.app.services.market_data_service import MarketDataRepository, MarketDataService
from backend.app.services.stock_service import StockService

STOCK_CODE = "600519"


def _session() -> Session:
    engine = create_engine("sqlite://")
    apply_migrations(engine)
    return Session(bind=engine)


def _bar(stock_code, trade_date, close=105.0):
    return DailyKlineSchema(
        stock_code=stock_code,
        trade_date=trade_date,
        open=100.0,
        high=110.0,
        low=90.0,
        close=close,
        volume=1000,
        amount=100000.0,
        turnover_rate=0.01,
        change_pct=0.02,
    )


def test_upsert_daily_inserts_and_queries_back():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        rows = [_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(3)]

        count = repository.upsert_daily(rows)

        assert count == 3
        back = repository.list_daily(STOCK_CODE, start, date(2025, 1, 3))
        assert len(back) == 3
        assert back[0].trade_date == start
        # ascending by trade_date
        assert back == sorted(back, key=lambda r: r.trade_date)


def test_upsert_daily_updates_instead_of_duplicating():
    with _session() as session:
        repository = MarketDataRepository(session)
        trade_date = date(2025, 1, 1)
        repository.upsert_daily([_bar(STOCK_CODE, trade_date, close=105.0)])
        repository.upsert_daily([_bar(STOCK_CODE, trade_date, close=108.5)])

        back = repository.list_daily(STOCK_CODE, trade_date, trade_date)
        assert len(back) == 1
        assert back[0].close == 108.5


def test_get_stock_basic_round_trips_and_returns_none_when_absent():
    with _session() as session:
        repository = MarketDataRepository(session)

        assert repository.get_stock_basic(STOCK_CODE) is None

        repository.upsert_stock_basic(
            StockBasicSchema(
                stock_code=STOCK_CODE,
                stock_name="贵州茅台",
                industry="酿酒行业",
                total_market_cap=1.0,
                float_market_cap=1.0,
            )
        )

        stored = repository.get_stock_basic(STOCK_CODE)
        assert stored is not None
        assert stored.stock_name == "贵州茅台"
        assert stored.industry == "酿酒行业"


def _provider_frame(n, start_date):
    dates = [start_date + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "stock_code": [STOCK_CODE] * n,
            "trade_date": dates,
            "open": [100.0] * n,
            "high": [110.0] * n,
            "low": [90.0] * n,
            "close": [105.0] * n,
            "volume": [1000] * n,
            "amount": [100000.0] * n,
            "turnover_rate": [0.01] * n,
            "change_pct": [0.02] * n,
        }
    )


class RecordingProvider:
    def __init__(self, n):
        self.n = n
        self.calls = []

    def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
        self.calls.append((stock_code, start_date, end_date, adjust))
        return _provider_frame(self.n, start_date)


def test_query_daily_does_not_treat_partial_cache_as_full_hit():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        repository.upsert_daily([_bar(STOCK_CODE, start)])  # only 1 cached row

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows = service.query_daily(STOCK_CODE, start, start + timedelta(days=400), min_rows=60)

        assert len(provider.calls) == 1  # partial cache -> provider called
        assert len(rows) >= 60


def test_query_daily_serves_complete_cache_without_refetch():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        repository.upsert_daily([_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(60)])

        class FailingProvider:
            def get_daily_kline(self, *args, **kwargs):
                raise AssertionError("provider must not be called when cache is complete")

        service = MarketDataService(
            stock_service=StockService(provider=FailingProvider()), repository=repository
        )

        rows = service.query_daily(STOCK_CODE, start, start + timedelta(days=400), min_rows=60)

        assert len(rows) == 60


def test_query_daily_raises_40003_when_provider_still_returns_too_few():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        repository.upsert_daily([_bar(STOCK_CODE, start)])  # partial cache

        class ShortProvider:
            def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
                return _provider_frame(2, start_date)

        service = MarketDataService(
            stock_service=StockService(provider=ShortProvider()), repository=repository
        )

        with pytest.raises(InsufficientStockDataError):  # business code 40003
            service.query_daily(STOCK_CODE, start, start + timedelta(days=400), min_rows=60)


def test_query_daily_drops_invalid_ohlc_rows():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)

        class PartiallyInvalidProvider:
            def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
                frame = _provider_frame(70, start_date)
                for i in range(65, 70):
                    frame.loc[i, "high"] = 80.0  # invalid: high < open/close
                return frame

        service = MarketDataService(
            stock_service=StockService(provider=PartiallyInvalidProvider()),
            repository=repository,
        )

        rows = service.query_daily(STOCK_CODE, start, start + timedelta(days=400), min_rows=60)

        assert len(rows) >= 60
        assert all(r.high >= r.open and r.high >= r.close for r in rows)
        assert all(r.low <= r.open and r.low <= r.close for r in rows)


class FailingSession:
    def __init__(self):
        self.rolled_back = False

    def query(self, *args, **kwargs):
        raise SQLAlchemyError("db down")

    def rollback(self):
        self.rolled_back = True


def test_market_data_repository_converts_db_failure_to_database_operation_error():
    session = FailingSession()
    repository = MarketDataRepository(session)

    with pytest.raises(DatabaseOperationError):
        repository.list_daily(STOCK_CODE)
    assert session.rolled_back is True

    with pytest.raises(DatabaseOperationError):
        repository.upsert_daily([_bar(STOCK_CODE, date(2025, 1, 1))])
    assert session.rolled_back is True
