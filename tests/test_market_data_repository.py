import math
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError, InsufficientStockDataError
from backend.app.db.migrations import apply_migrations
from backend.app.quant.scoring import calculate_quant_score
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

        rows = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=400), min_rows=60,
            trading_days=lambda s, e: 60,
        )

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

        # Query the exact range the cache covers so it counts as complete+fresh.
        rows = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59),
            min_rows=60, trading_days=lambda s, e: 60,
        )

        assert len(rows) == 60


def test_query_daily_refetches_when_cache_is_stale():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        # 60 bars, but the latest is far behind the requested end_date.
        repository.upsert_daily([_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(60)])

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=79),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # stale (last bar 20d before end) -> refetch
        assert len(rows) >= 60


def test_query_daily_refetches_when_cache_does_not_cover_start_of_range():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        # Bars do not reach back to ``start`` (earliest is 10 days later).
        repository.upsert_daily([_bar(STOCK_CODE, start + timedelta(days=10 + i)) for i in range(60)])

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=69),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # first bar is 10d after start -> refetch
        assert len(rows) >= 60


def _invalid_bar(stock_code, trade_date):
    """A bar with illegal OHLC (high < open/low) that must never be a full hit."""
    return DailyKlineSchema(
        stock_code=stock_code,
        trade_date=trade_date,
        open=100.0,
        high=80.0,
        low=90.0,
        close=105.0,
        volume=1000,
        amount=100000.0,
        turnover_rate=0.01,
        change_pct=0.02,
    )


def test_query_daily_refetches_when_cache_contains_invalid_ohlc():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        rows = [_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(59)]
        rows.append(_invalid_bar(STOCK_CODE, start + timedelta(days=59)))  # 60 rows, 1 invalid

        repository.upsert_daily(rows)
        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows_out = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # 60 rows but invalid bar -> refetch
        assert all(
            r.high >= r.open
            and r.high >= r.close
            and r.low <= r.open
            and r.low <= r.close
            for r in rows_out
        )


def test_sync_daily_returns_40003_when_only_59_valid_rows():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)

        class OneBadLowProvider:
            def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
                frame = _provider_frame(60, start_date)
                frame.loc[0, "low"] = 0.0  # invalid: non-positive price
                return frame

        service = MarketDataService(
            stock_service=StockService(provider=OneBadLowProvider()), repository=repository
        )

        with pytest.raises(InsufficientStockDataError):  # only 59 valid rows -> 40003
            service.query_daily(STOCK_CODE, start, start + timedelta(days=59), min_rows=60)


def test_daily_persistence_roundtrip_uses_decimal_precision():
    with _session() as session:
        repository = MarketDataRepository(session)
        trade_date = date(2025, 1, 1)
        bar = DailyKlineSchema(
            stock_code=STOCK_CODE,
            trade_date=trade_date,
            open=100.1234567,
            high=110.9876543,
            low=90.1234567,
            close=105.9876543,
            volume=1000,
            amount=100000.1234567,
            turnover_rate=0.0123456789,
            change_pct=0.023456789,
        )

        repository.upsert_daily([bar])

        back = repository.list_daily(STOCK_CODE, trade_date, trade_date)
        result = back[0]
        assert result.open == round(100.1234567, 4)
        assert result.high == round(110.9876543, 4)
        assert result.low == round(90.1234567, 4)
        assert result.close == round(105.9876543, 4)
        assert result.amount == round(100000.1234567, 2)
        assert result.turnover_rate == round(0.0123456789, 6)
        assert result.change_pct == round(0.023456789, 6)


def _high_precision_frame(n, start_date):
    dates = [start_date + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "stock_code": [STOCK_CODE] * n,
            "trade_date": dates,
            "open": [100.1234567] * n,
            "high": [110.9876543] * n,
            "low": [90.1234567] * n,
            "close": [105.9876543] * n,
            "volume": [1000] * n,
            "amount": [100000.1234567] * n,
            "turnover_rate": [0.0123456789] * n,
            "change_pct": [0.023456789] * n,
        }
    )


def test_first_query_and_cache_hit_return_identical_rounded_rows():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)

        class HighPrecisionProvider:
            def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
                return _high_precision_frame(60, start_date)

        service = MarketDataService(
            stock_service=StockService(provider=HighPrecisionProvider()), repository=repository
        )

        first = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59), min_rows=60, trading_days=lambda s, e: 60
        )
        second = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59), min_rows=60, trading_days=lambda s, e: 60
        )

        # First fetch (sync_daily) and cache hit feed the identical rounded data
        # to the quant module, so scores/trades cannot differ between the two.
        assert first == second
        assert first[0].close == round(105.9876543, 4)


def _varying_frame(n, start_date):
    dates = [start_date + timedelta(days=i) for i in range(n)]
    closes = [100 + i * 0.2 + 5 * math.sin(i / 2.0) for i in range(n)]
    return pd.DataFrame(
        {
            "stock_code": [STOCK_CODE] * n,
            "trade_date": dates,
            "open": [c - 1.0 for c in closes],
            "high": [c + 2.0 for c in closes],
            "low": [c - 2.0 for c in closes],
            "close": closes,
            "volume": [1000 + i * 10 for i in range(n)],
            "amount": [c * 1000 for c in closes],
            "turnover_rate": [0.01] * n,
            "change_pct": [0.01] * n,
        }
    )


def _to_quant_frame(rows):
    return pd.DataFrame([row.model_dump() for row in rows])


def test_first_query_and_cache_hit_give_identical_quant_score():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)

        class VaryingProvider:
            def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
                return _varying_frame(60, start_date)

        service = MarketDataService(
            stock_service=StockService(provider=VaryingProvider()), repository=repository
        )

        first = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59), min_rows=60, trading_days=lambda s, e: 60
        )
        second = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59), min_rows=60, trading_days=lambda s, e: 60
        )

        score_first = calculate_quant_score(_to_quant_frame(first))
        score_second = calculate_quant_score(_to_quant_frame(second))

        # Identical data -> identical full quant output (not just DB decimals).
        assert score_first == score_second
        assert score_first["score"] == score_second["score"]


def test_query_daily_refetches_when_cache_has_nonpositive_price():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        rows = [_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(59)]
        rows.append(
            DailyKlineSchema(
                stock_code=STOCK_CODE,
                trade_date=start + timedelta(days=59),
                open=0.0,  # invalid: non-positive price
                high=110.0,
                low=90.0,
                close=105.0,
                volume=1000,
                amount=100000.0,
                turnover_rate=0.01,
                change_pct=0.02,
            )
        )
        repository.upsert_daily(rows)

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows_out = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # price<=0 in cache -> refetch
        assert all(r.open > 0 and r.close > 0 for r in rows_out)


def test_query_daily_refetches_when_cache_has_null_volume():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        rows = [_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(59)]
        rows.append(
            DailyKlineSchema(
                stock_code=STOCK_CODE,
                trade_date=start + timedelta(days=59),
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=None,  # invalid: null volume
                amount=100000.0,
                turnover_rate=0.01,
                change_pct=0.02,
            )
        )
        repository.upsert_daily(rows)

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows_out = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=59),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # null volume in cache -> refetch
        assert all(r.volume is not None and r.volume >= 0 for r in rows_out)


def test_query_daily_refetches_when_cache_has_internal_gap():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        rows = []
        for i in range(40):
            rows.append(_bar(STOCK_CODE, start + timedelta(days=i)))
        for i in range(60, 80):  # drops days 40..59 (a 21-day internal gap)
            rows.append(_bar(STOCK_CODE, start + timedelta(days=i)))
        repository.upsert_daily(rows)

        provider = RecordingProvider(60)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows_out = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=79),
            min_rows=60, max_stale_days=3, trading_days=lambda s, e: 60,
        )

        assert len(provider.calls) == 1  # internal gap -> refetch
        assert len(rows_out) >= 60


def test_query_daily_refetches_when_cache_has_fewer_bars_than_expected_trading_days():
    with _session() as session:
        repository = MarketDataRepository(session)
        start = date(2025, 1, 1)
        # The cache only holds 100 bars for a range the calendar says has 120.
        repository.upsert_daily([_bar(STOCK_CODE, start + timedelta(days=i)) for i in range(100)])

        provider = RecordingProvider(120)
        service = MarketDataService(
            stock_service=StockService(provider=provider), repository=repository
        )

        rows_out = service.query_daily(
            STOCK_CODE, start, start + timedelta(days=119),
            min_rows=60, trading_days=lambda s, e: 120,
        )

        assert len(provider.calls) == 1  # fewer than expected -> refetch
        assert len(rows_out) >= 60


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
