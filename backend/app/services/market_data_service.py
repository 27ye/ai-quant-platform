"""Market-data (stock_basic / stock_daily) persistence: MySQL upsert + query.

This is the DB half of the V1 data pipeline: the API keeps its existing
contract, while this module lets B pull real qfq data into MySQL and read it
back (System Design :: Service 层：查询 MySQL -> 缺失时调 Provider -> 标准化 ->
Upsert MySQL -> 返回).

Repository methods are portable across the SQLite test database and MySQL 8
(no MySQL-specific DDL is used), so the upsert/query logic is unit-testable
without a running MySQL instance.

All ``SQLAlchemyError`` failures are translated into ``DatabaseOperationError``
(business code 50002) and the session is rolled back, so callers observe a
stable business error instead of a raw driver exception.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Callable, List, Optional, Protocol, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError, InsufficientStockDataError
from backend.app.models.stock_basic import StockBasic
from backend.app.models.stock_daily import StockDaily
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS, StockService

#: A cache is considered fresh only if its latest bar is within this many days
#: of the requested ``end_date`` (also covers the earliest-bar gap to ``start``).
DEFAULT_MAX_STALE_DAYS = 3

#: Maximum allowed gap (in days) between two consecutive cached bars. A larger
#: gap means the middle of the window is missing (a chunk of days was dropped),
#: so the cache is NOT treated as a complete hit. Tolerates normal A-share
#: holidays/long weekends. The definitive rule is to be confirmed with D.
DEFAULT_MAX_GAP_DAYS = 15

#: Canonical decimal precision ("口径") for persisted daily bars. Prices are
#: stored at 4 decimals, amount at 2 and turnover/change at 6, matching the
#: ``DATABASE_DESIGN.md`` DECIMAL columns. Rounding is applied explicitly in
#: Python so both MySQL and SQLite round-trip identically (DB-agnostic), and is
#: also applied to the *returned* rows so the first fetch and subsequent cache
#: hits feed the identical numbers to the quant module.
PRICE_NDIGITS = 4
AMOUNT_NDIGITS = 2
PERCENT_NDIGITS = 6


def _round_value(value: Optional[float], ndigits: int) -> Optional[float]:
    return round(value, ndigits) if value is not None else None


def _round_daily(schema: DailyKlineSchema) -> DailyKlineSchema:
    """Return ``schema`` with numeric fields rounded to the canonical precision."""
    return DailyKlineSchema(
        stock_code=schema.stock_code,
        trade_date=schema.trade_date,
        open=_round_value(schema.open, PRICE_NDIGITS),
        high=_round_value(schema.high, PRICE_NDIGITS),
        low=_round_value(schema.low, PRICE_NDIGITS),
        close=_round_value(schema.close, PRICE_NDIGITS),
        volume=schema.volume,
        amount=_round_value(schema.amount, AMOUNT_NDIGITS),
        turnover_rate=_round_value(schema.turnover_rate, PERCENT_NDIGITS),
        change_pct=_round_value(schema.change_pct, PERCENT_NDIGITS),
    )


def _is_valid_bar(row: DailyKlineSchema) -> bool:
    """True when a bar is acceptable to C's quant input: finite OHLC that are
    strictly positive and satisfy OHLC ordering, and a non-null volume >= 0.
    """
    for field in ("open", "high", "low", "close"):
        value = getattr(row, field)
        if value is None or not math.isfinite(value) or value <= 0:
            return False
    if row.volume is None or row.volume < 0:
        return False
    if (
        row.high < row.open
        or row.high < row.close
        or row.low > row.open
        or row.low > row.close
        or row.high < row.low
    ):
        return False
    return True


class MarketDataSource(Protocol):
    """Injectable market-data source consumed by the AI pipeline / API layer."""

    def query_daily(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
        max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
        max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
        trading_days: Optional[Callable[[date, date], int]] = None,
    ) -> List[DailyKlineSchema]:
        """Return a >= ``min_rows`` valid qfq daily window, filling the cache
        from the provider when the cached range is incomplete or stale. All
        returned values are rounded to the canonical precision口径.

        ``trading_days`` is the authoritative completeness basis: a callable that
        returns the number of trading days in ``[start, end]``. The cache is only
        served when it contains at least that many bars (an exchange trading
        calendar would supply this). When ``trading_days`` is not provided the
        service cannot prove completeness and conservatively refetches.
        """
        ...

    def sync_daily(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
    ) -> List[DailyKlineSchema]:
        """Fetch + clean + widen via ``StockService``, then upsert into MySQL.
        Returns the same rounded rows that are written to the DB.
        """
        ...


class MarketDataRepository:
    """Upsert/read access to ``stock_basic`` and ``stock_daily``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_stock_basic(self, item: StockBasicSchema) -> None:
        try:
            record = self._session.get(StockBasic, item.stock_code)
            if record is None:
                self._session.add(
                    StockBasic(
                        stock_code=item.stock_code,
                        stock_name=item.stock_name,
                        industry=item.industry,
                        total_market_cap=item.total_market_cap,
                        float_market_cap=item.float_market_cap,
                    )
                )
            else:
                record.stock_name = item.stock_name
                record.industry = item.industry
                record.total_market_cap = item.total_market_cap
                record.float_market_cap = item.float_market_cap
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def get_stock_basic(self, stock_code: str) -> Optional[StockBasicSchema]:
        try:
            record = self._session.get(StockBasic, stock_code)
            if record is None:
                return None
            return StockBasicSchema(
                stock_code=record.stock_code,
                stock_name=record.stock_name,
                industry=record.industry,
                total_market_cap=record.total_market_cap,
                float_market_cap=record.float_market_cap,
            )
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def upsert_daily(self, rows: Sequence[DailyKlineSchema]) -> int:
        """Insert or update daily bars keyed by ``(stock_code, trade_date)``.

        Numeric fields are rounded to the canonical precision before writing, so
        the DB round-trip is deterministic on MySQL and SQLite.
        """
        try:
            count = 0
            for row in rows:
                fields = self._rounded_daily_fields(row)
                record = (
                    self._session.query(StockDaily)
                    .filter_by(stock_code=row.stock_code, trade_date=row.trade_date)
                    .one_or_none()
                )
                if record is None:
                    self._session.add(StockDaily(**fields))
                else:
                    fields.pop("stock_code", None)
                    fields.pop("trade_date", None)
                    for field, value in fields.items():
                        setattr(record, field, value)
                count += 1
            self._session.commit()
            return count
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def list_daily(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[DailyKlineSchema]:
        try:
            query = self._session.query(StockDaily).filter(
                StockDaily.stock_code == stock_code
            )
            if start_date is not None:
                query = query.filter(StockDaily.trade_date >= start_date)
            if end_date is not None:
                query = query.filter(StockDaily.trade_date <= end_date)
            records = query.order_by(StockDaily.trade_date.asc()).all()
            return [self._to_schema(record) for record in records]
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    @staticmethod
    def _rounded_daily_fields(row: DailyKlineSchema) -> dict:
        return _round_daily(row).model_dump()

    @staticmethod
    def _to_schema(record: StockDaily) -> DailyKlineSchema:
        return _round_daily(
            DailyKlineSchema(
                stock_code=record.stock_code,
                trade_date=record.trade_date,
                open=record.open,
                high=record.high,
                low=record.low,
                close=record.close,
                volume=record.volume,
                amount=record.amount,
                turnover_rate=record.turnover_rate,
                change_pct=record.change_pct,
            )
        )

    @staticmethod
    def _cached_rows_valid(cached: Sequence[DailyKlineSchema]) -> bool:
        """True when every cached bar is acceptable to C's quant input."""
        return all(_is_valid_bar(row) for row in cached)


class MarketDataService:
    """Orchestrates fetch-from-provider -> upsert -> query for daily bars.

    Reuses :class:`StockService` for cleaning and automatic window-widening, so
    the returned window always satisfies the >= ``min_rows`` valid-day contract;
    ``InsufficientStockDataError`` (40003) is raised when it cannot be met.
    """

    def __init__(
        self,
        stock_service: Optional[StockService] = None,
        repository: Optional[MarketDataRepository] = None,
    ) -> None:
        self._stock = stock_service or StockService()
        self._repository = repository

    def sync_daily(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
    ) -> List[DailyKlineSchema]:
        """Fetch + clean + widen via StockService, then upsert into MySQL.

        Returns the *same rounded* rows that are written to the DB, so a caller
        sees the identical numbers whether it reads fresh from the provider or
        from a later cache hit. Rows that C's quant would reject (non-positive
        price, null volume, illegal OHLC) are dropped using the same rule as the
        cache validity check; if fewer than ``min_rows`` remain, 40003 is raised.
        """
        fetched = self._stock.get_daily_kline(
            stock_code, start_date, end_date, min_rows=min_rows
        )
        rows = [_round_daily(row) for row in fetched]
        rows = [row for row in rows if _is_valid_bar(row)]
        if len(rows) < min_rows:
            raise InsufficientStockDataError(
                f"stock {stock_code} has {len(rows)} valid rows after the "
                f"consistency filter; at least {min_rows} required"
            )
        if self._repository is not None:
            self._repository.upsert_daily(rows)
        return rows

    def query_daily(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
        max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
        max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
        trading_days: Optional[Callable[[date, date], int]] = None,
    ) -> List[DailyKlineSchema]:
        """Query MySQL first, treating the cache as a full hit only when it is
        (a) at least ``min_rows`` bars, (b) all bars are valid for C, (c) there
        is no internal gap larger than ``max_gap_days`` (auxiliary), and (d) it
        is confirmed complete against the authoritative ``trading_days`` basis
        and fresh relative to ``end_date``.

        ``trading_days`` is a ``(start, end) -> expected bars`` callable (an
        exchange trading calendar). When it is not provided the service cannot
        prove completeness, so it conservatively refetches (per C: completeness
        must not be assumed from row count / endpoints / a gap threshold alone).

        Otherwise it fetches via :class:`StockService` (which cleans and widens
        the window to guarantee ``min_rows`` valid rows) and upserts the result.
        Raises ``InsufficientStockDataError`` (40003) when even the widest fetch
        cannot produce ``min_rows`` valid rows.
        """
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=366))
        if self._repository is not None:
            cached = self._repository.list_daily(stock_code, start_date, end_date)
            if self._is_cache_complete(
                cached, start_date, end_date, min_rows, max_stale_days, max_gap_days, trading_days
            ):
                return cached
        return self.sync_daily(stock_code, start_date, end_date, min_rows=min_rows)

    @staticmethod
    def _gaps_valid(cached: Sequence[DailyKlineSchema], max_gap_days: int) -> bool:
        """False when any two consecutive bars are farther apart than ``max_gap_days``
        (an internal chunk of the window is missing). Auxiliary check only."""
        for previous, current in zip(cached, cached[1:]):
            if (current.trade_date - previous.trade_date).days > max_gap_days:
                return False
        return True

    @staticmethod
    def _is_cache_complete(
        cached: Sequence[DailyKlineSchema],
        start: date,
        end: date,
        min_rows: int,
        max_stale_days: int,
        max_gap_days: int,
        trading_days: Optional[Callable[[date, date], int]],
    ) -> bool:
        """Full cache-hit decision. Completeness is only confirmed against the
        authoritative ``trading_days`` count; without it the cache is not served.
        """
        if trading_days is None:
            return False  # cannot prove completeness -> conservative refetch
        if len(cached) < min_rows:
            return False
        if not MarketDataRepository._cached_rows_valid(cached):
            return False  # invalid bars must not count as a full hit
        if not MarketDataService._gaps_valid(cached, max_gap_days):
            return False  # an obvious internal chunk is missing
        if len(cached) < trading_days(start, end):
            return False  # fewer bars than the authoritative trading-day count
        first = cached[0].trade_date
        last = cached[-1].trade_date
        if (first - start).days > max_stale_days:
            return False  # cache does not cover the beginning of the range
        if (end - last).days > max_stale_days:
            return False  # cache is stale relative to the requested end
        return True
