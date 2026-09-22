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
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, ClassVar, List, Optional, Protocol, Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError, InsufficientStockDataError
from backend.app.data.providers.base import StockDataProviderError
from backend.app.models.stock_basic import StockBasic
from backend.app.models.stock_daily import StockDaily
from backend.app.models.stock_daily_sync import StockDailySync
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


@dataclass(frozen=True)
class DailySyncState:
    """Recorded provenance of the last refresh attempt for one stock (V2 B2)."""

    stock_code: str
    mode: str
    source: Optional[str]
    row_count: int
    first_trade_date: Optional[date]
    last_trade_date: Optional[date]
    last_success_at: Optional[datetime]
    last_attempt_at: Optional[datetime]
    last_error: Optional[str]


@dataclass(frozen=True)
class DailyWindow:
    """Aggregates over the stored bars themselves, independent of metadata."""

    row_count: int
    first_trade_date: Optional[date]
    last_trade_date: Optional[date]
    last_updated_at: Optional[datetime]


def _utc_now() -> datetime:
    """Naive UTC, matching the plain DATETIME columns used across the schema."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        trading_days: Optional[Callable[[date, date], Optional[int]]] = None,
    ) -> List[DailyKlineSchema]:
        """Return a >= ``min_rows`` valid qfq daily window, filling the cache
        from the provider when the cached range is incomplete or stale. All
        returned values are rounded to the canonical precision口径.

        ``trading_days`` is the authoritative completeness basis: a callable that
        returns the number of trading days in ``[start, end]`` (an exchange
        trading calendar supplies this) or ``None`` when it cannot prove coverage.
        The cache is only served when a non-``None`` expected count is available
        and the cache meets it. Without it the service cannot prove completeness
        and conservatively refetches.
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

    def get_query_provenance(self, stock_code: str) -> dict[str, str]:
        """Return ``source_mode``/``provider`` for the last query of a stock.

        Persisted into AI report snapshots, so a source that cannot attest its
        own provenance must fail loudly instead of silently omitting it.
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

    def refresh_snapshot(self) -> None:
        """End the current read-only transaction so the next query starts a
        fresh snapshot. On MySQL (REPEATABLE READ) a session keeps serving the
        snapshot established by its first read, so a cache re-check after
        waiting on the per-stock sync lock would not see another request's
        just-committed rows without this. Repository methods always commit or
        roll back their own writes, so no pending changes are ever discarded.
        """
        self._session.rollback()

    # -- refresh provenance (V2 B2) -----------------------------------------

    def upsert_daily_sync(
        self,
        *,
        stock_code: str,
        mode: str,
        source: Optional[str],
        row_count: int,
        first_trade_date: Optional[date],
        last_trade_date: Optional[date],
        at: datetime,
    ) -> None:
        """Record a *successful* refresh (only called after the bars are stored)."""
        try:
            self._apply_daily_sync(
                stock_code=stock_code,
                mode=mode,
                source=source,
                row_count=row_count,
                first_trade_date=first_trade_date,
                last_trade_date=last_trade_date,
                at=at,
            )
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def replace_daily_snapshot(
        self,
        rows: Sequence[DailyKlineSchema],
        *,
        source: Optional[str],
        at: datetime,
    ) -> int:
        """Atomically replace one stock's bars and successful provenance.

        A qfq source switch or a provider rebase cannot leave an older prefix
        in the table. The delete, full insert and sync metadata share one
        transaction; any failure restores the previous data and source.
        """
        if not rows:
            raise ValueError("daily snapshot cannot be empty")
        stock_code = rows[0].stock_code
        if any(row.stock_code != stock_code for row in rows):
            raise ValueError("daily snapshot must contain exactly one stock")
        try:
            self._session.query(StockDaily).filter(
                StockDaily.stock_code == stock_code
            ).delete(synchronize_session=False)
            self._session.add_all(
                [StockDaily(**self._rounded_daily_fields(row)) for row in rows]
            )
            self._apply_daily_sync(
                stock_code=stock_code,
                mode="live",
                source=source,
                row_count=len(rows),
                first_trade_date=rows[0].trade_date,
                last_trade_date=rows[-1].trade_date,
                at=at,
            )
            self._session.commit()
            return len(rows)
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def _apply_daily_sync(
        self,
        *,
        stock_code: str,
        mode: str,
        source: Optional[str],
        row_count: int,
        first_trade_date: Optional[date],
        last_trade_date: Optional[date],
        at: datetime,
    ) -> None:
        record = self._session.get(StockDailySync, stock_code)
        if record is None:
            record = StockDailySync(stock_code=stock_code, mode=mode, last_attempt_at=at)
            self._session.add(record)
        record.mode = mode
        record.source = source
        record.row_count = row_count
        record.first_trade_date = first_trade_date
        record.last_trade_date = last_trade_date
        record.last_success_at = at
        record.last_attempt_at = at
        record.last_error = None

    def mark_daily_sync_failure(
        self, *, stock_code: str, error: str, at: datetime
    ) -> None:
        """Record a failed refresh without touching the previous success time."""
        try:
            record = self._session.get(StockDailySync, stock_code)
            if record is None:
                record = StockDailySync(
                    stock_code=stock_code, mode="unknown", last_attempt_at=at
                )
                self._session.add(record)
            record.last_attempt_at = at
            record.last_error = error[:500]
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def get_daily_sync(self, stock_code: str) -> Optional[DailySyncState]:
        try:
            record = self._session.get(StockDailySync, stock_code)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        if record is None:
            return None
        return DailySyncState(
            stock_code=record.stock_code,
            mode=record.mode,
            source=record.source,
            row_count=int(record.row_count or 0),
            first_trade_date=record.first_trade_date,
            last_trade_date=record.last_trade_date,
            last_success_at=record.last_success_at,
            last_attempt_at=record.last_attempt_at,
            last_error=record.last_error,
        )

    def daily_window(self, stock_code: str) -> DailyWindow:
        """Row count / first / last trade date / last write time from the bars."""
        try:
            row = self._session.execute(
                select(
                    func.count(StockDaily.id),
                    func.min(StockDaily.trade_date),
                    func.max(StockDaily.trade_date),
                    func.max(StockDaily.updated_at),
                ).where(StockDaily.stock_code == stock_code)
            ).one()
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        row_count = int(row[0] or 0)
        if row_count == 0:
            return DailyWindow(
                row_count=0,
                first_trade_date=None,
                last_trade_date=None,
                last_updated_at=None,
            )
        return DailyWindow(
            row_count=row_count,
            first_trade_date=row[1],
            last_trade_date=row[2],
            last_updated_at=row[3],
        )

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
        trading_days: Optional[Callable[[date, date], Optional[int]]] = None,
        completed_through: Optional[Callable[[], Optional[date]]] = None,
    ) -> None:
        self._stock = stock_service or StockService()
        self._repository = repository
        self._trading_days = trading_days
        self._completed_through = completed_through
        self._query_source_modes: dict[str, str] = {}

    #: Per-stock sync locks, shared across instances: ``get_market_data_source``
    #: builds a fresh service per request, so instance-level locks would not
    #: exclude concurrent first-load syncs of the same stock.
    _sync_locks: ClassVar[dict[str, threading.Lock]] = {}
    _sync_locks_guard: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _sync_lock_for(cls, stock_code: str) -> threading.Lock:
        """Return the class-shared lock serializing cache-miss syncs of one stock.

        Two concurrent cold-start queries for the same stock otherwise both
        fetch and race the non-atomic ``upsert_daily``; the loser fails with a
        duplicate-key IntegrityError (the cold-start blank K-line card).
        """
        with cls._sync_locks_guard:
            return cls._sync_locks.setdefault(stock_code, threading.Lock())

    def sync_daily(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
        trading_days: Optional[Callable[[date, date], Optional[int]]] = None,
        completed_through: Optional[date] = None,
    ) -> List[DailyKlineSchema]:
        """Fetch one same-source snapshot and atomically publish it to MySQL.

        Returns the *same rounded* rows that are written to the DB, so a caller
        sees the identical numbers whether it reads fresh from the provider or
        from a later cache hit. Rows that C's quant would reject (non-positive
        price, null volume, illegal OHLC) are dropped using the same rule as the
        cache validity check; if fewer than ``min_rows`` remain, 40003 is raised.

        On success the refresh provenance (mode/source/rows/window/time) is
        recorded in ``stock_daily_sync`` so ``data-status`` can report where the
        stored bars came from; a failed attempt records only the error and keeps
        the previous success time.
        """
        fetch_start, fetch_end = start_date, end_date
        if self._repository is not None:
            existing = self._repository.daily_window(stock_code)
            if existing.first_trade_date is not None:
                fetch_start = min(fetch_start, existing.first_trade_date)
            if existing.last_trade_date is not None:
                fetch_end = max(fetch_end, existing.last_trade_date)
        if completed_through is None and self._completed_through is not None:
            completed_through = self._completed_through()
            if completed_through is None:
                error = StockDataProviderError(
                    "trading calendar cannot determine the latest completed daily bar"
                )
                self._record_sync_failure(stock_code, error)
                raise error
        if completed_through is not None:
            fetch_end = min(fetch_end, completed_through)
        expected = None
        if trading_days is not None:
            expected = trading_days(fetch_start, fetch_end)
            if expected is None:
                error = StockDataProviderError(
                    f"trading calendar cannot verify the replacement window for {stock_code}"
                )
                self._record_sync_failure(stock_code, error)
                raise error
        try:
            fetched = self._stock.get_daily_kline(
                stock_code, fetch_start, fetch_end, min_rows=min_rows
            )
        except Exception as exc:  # noqa: BLE001 - re-raised below
            self._record_sync_failure(stock_code, exc)
            raise
        rows = [_round_daily(row) for row in fetched if row.trade_date <= fetch_end]
        rows = [row for row in rows if _is_valid_bar(row)]
        if len(rows) < min_rows:
            self._record_sync_failure(
                stock_code,
                InsufficientStockDataError(
                    f"stock {stock_code} has {len(rows)} valid rows after the "
                    f"consistency filter; at least {min_rows} required"
                ),
            )
            raise InsufficientStockDataError(
                f"stock {stock_code} has {len(rows)} valid rows after the "
                f"consistency filter; at least {min_rows} required"
            )
        if expected is not None:
            covered = [row for row in rows if fetch_start <= row.trade_date <= fetch_end]
            if len(covered) < expected:
                error = StockDataProviderError(
                    f"provider returned {len(covered)} completed rows for {stock_code}; "
                    f"calendar requires {expected}"
                )
                self._record_sync_failure(stock_code, error)
                raise error
        if self._repository is not None:
            source = self._stock.last_kline_source
            try:
                self._repository.replace_daily_snapshot(rows, source=source, at=_utc_now())
            except DatabaseOperationError as exc:
                self._record_sync_failure(stock_code, exc)
                raise
        self._query_source_modes[stock_code] = "live"
        return rows

    def _record_sync_failure(self, stock_code: str, exc: Exception) -> None:
        """Best-effort failure note: never mask the original error."""
        if self._repository is None:
            return
        try:
            self._repository.mark_daily_sync_failure(
                stock_code=stock_code,
                error=f"{type(exc).__name__}: {exc}",
                at=_utc_now(),
            )
        except DatabaseOperationError:
            pass

    def query_daily(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
        max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
        max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
        trading_days: Optional[Callable[[date, date], Optional[int]]] = None,
    ) -> List[DailyKlineSchema]:
        """Query MySQL first, treating the cache as a full hit only when it is
        (a) at least ``min_rows`` bars, (b) all bars are valid for C, (c) there
        is no internal gap larger than ``max_gap_days`` (auxiliary), and (d) it
        is confirmed complete against the authoritative ``trading_days`` basis
        and fresh relative to ``end_date``.

        ``trading_days`` is a ``(start, end) -> expected bars`` callable returning
        ``None`` when it cannot prove coverage. A ``None`` expected count is
        treated as "coverage unknown" and the cache is NOT served (conservative
        refetch), per C: completeness must not be assumed from row count /
        endpoints / a gap threshold alone, and an empty/expired calendar must not
        be trusted as a count of 0.

        Otherwise it fetches via :class:`StockService` (which cleans and widens
        the window to guarantee ``min_rows`` valid rows) and upserts the result.
        Raises ``InsufficientStockDataError`` (40003) when even the widest fetch
        cannot produce ``min_rows`` valid rows.

        Concurrent first-load queries for the same stock are serialized on a
        class-level per-stock lock: the waiter re-checks the cache on a fresh
        snapshot and serves the rows the winner just synced, instead of
        re-fetching and racing the non-atomic upsert.
        """
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=366))
        trading_days = trading_days if trading_days is not None else self._trading_days
        completed_through = None
        if self._completed_through is not None:
            completed_through = self._completed_through()
            if completed_through is None:
                raise StockDataProviderError(
                    "trading calendar cannot determine the latest completed daily bar"
                )
            end_date = min(end_date, completed_through)
            start_date = min(start_date, end_date)
        cached = self._complete_cache(
            stock_code, start_date, end_date, min_rows, max_stale_days, max_gap_days, trading_days
        )
        if cached is not None:
            return cached
        with self._sync_lock_for(stock_code):
            # A concurrent request may have finished the sync while we waited
            # on the lock; re-check on a fresh snapshot before fetching again
            # (MySQL REPEATABLE READ would otherwise keep serving the stale
            # snapshot established by the fast-path read above).
            if self._repository is not None:
                self._repository.refresh_snapshot()
            cached = self._complete_cache(
                stock_code, start_date, end_date, min_rows, max_stale_days, max_gap_days, trading_days
            )
            if cached is not None:
                return cached
            return self.sync_daily(
                stock_code,
                start_date,
                end_date,
                min_rows=min_rows,
                trading_days=trading_days,
                completed_through=completed_through,
            )

    def _complete_cache(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        min_rows: int,
        max_stale_days: int,
        max_gap_days: int,
        trading_days: Optional[Callable[[date, date], Optional[int]]],
    ) -> Optional[List[DailyKlineSchema]]:
        """Return the cached window when it is a verified complete hit, else ``None``."""
        if self._repository is None:
            return None
        cached = self._repository.list_daily(stock_code, start_date, end_date)
        if self._is_cache_complete(
            cached, start_date, end_date, min_rows, max_stale_days, max_gap_days, trading_days
        ):
            self._query_source_modes[stock_code] = "cache"
            return cached
        return None

    def get_query_provenance(self, stock_code: str) -> dict[str, str]:
        mode = self._query_source_modes.get(stock_code, "unknown")
        if mode == "live":
            provider = self._stock.last_kline_source or self._stock.provider_name
        elif mode == "cache" and self._repository is not None:
            sync = self._repository.get_daily_sync(stock_code)
            provider = sync.source if sync and sync.source else "unknown"
        else:
            provider = "unknown"
        return {
            "source_mode": mode,
            "provider": provider,
        }

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
        trading_days: Optional[Callable[[date, date], Optional[int]]],
    ) -> bool:
        """Full cache-hit decision. Completeness is only confirmed when the
        authoritative ``trading_days`` basis returns a non-``None`` expected count
        and the cache meets it; otherwise the cache is not served.
        """
        if trading_days is None:
            return False  # no completeness basis -> conservative refetch
        expected = trading_days(start, end)
        if expected is None:
            return False  # calendar cannot prove coverage -> conservative refetch
        if len(cached) < min_rows:
            return False
        if not MarketDataRepository._cached_rows_valid(cached):
            return False  # invalid bars must not count as a full hit
        if not MarketDataService._gaps_valid(cached, max_gap_days):
            return False  # an obvious internal chunk is missing
        if len(cached) < expected:
            return False  # fewer bars than the authoritative trading-day count
        first = cached[0].trade_date
        last = cached[-1].trade_date
        if (first - start).days > max_stale_days:
            return False  # cache does not cover the beginning of the range
        if (end - last).days > max_stale_days:
            return False  # cache is stale relative to the requested end
        return True
