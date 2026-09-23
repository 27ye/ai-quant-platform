"""Local A-share stock catalog: explicit sync plus MySQL-backed search (V2 B1).

V1 answered ``GET /stocks/search`` by downloading the entire market snapshot on
every request, so any upstream failure surfaced as ``50001`` and search simply
stopped working. V2 keeps a catalog in MySQL instead:

* an explicit, low-frequency sync writes ``stock_basic`` and records whether the
  catalog is actually complete (``stock_catalog_sync``);
* search is answered locally, so it no longer depends on the realtime quote
  cluster;
* when the catalog was never synced successfully, search reports ``50006 catalog not
  synced`` (HTTP 503) rather than downloading the market snapshot: the fallback could
  never fit the provider's retry budget, so it only ever produced a misleading
  ``50001`` after a multi-second wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from sqlalchemy import bindparam, func, insert, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import (
    CatalogNotSyncedError,
    DatabaseOperationError,
    InvalidParameterError,
)
from backend.app.data.providers.base import StockDataProvider, StockDataProviderError
from backend.app.models.stock_basic import StockBasic
from backend.app.models.stock_catalog_sync import StockCatalogSync
from backend.app.schemas.stock import StockBasicSchema

#: A catalog smaller than this is treated as partial and never marked complete.
MIN_CATALOG_ROWS = 1000
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 50

_SYNC_ROW_ID = 1
_STATUS_SUCCESS = "success"
_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class CatalogSyncState:
    """Bookkeeping row for the local catalog (``None`` when never attempted)."""

    status: str
    row_count: int
    last_success_at: Optional[datetime]
    last_attempt_at: Optional[datetime]
    source: Optional[str]
    last_error: Optional[str]

    @property
    def is_complete(self) -> bool:
        """True when a successful sync has left a usable catalog behind.

        Deliberately **not** ``status == "success"``: :meth:`StockCatalogRepository.mark_failure`
        keeps ``last_success_at``/``row_count`` and records the error separately, so a
        failed *refresh* must not discard a catalog that is still sitting in
        ``stock_basic``. Search keeps answering from those rows while the refresh error
        stays visible in ``last_error``. Only "never had a successful sync" means there
        is nothing to search (``50006``).
        """
        return self.last_success_at is not None and self.row_count >= MIN_CATALOG_ROWS


@dataclass(frozen=True)
class CatalogSyncResult:
    row_count: int
    source: Optional[str]
    synced_at: datetime


class StockCatalogRepository:
    """Persistence for the catalog and its sync metadata."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def count(self) -> int:
        try:
            statement = select(func.count()).select_from(StockBasic)
            return int(self._session.execute(statement).scalar() or 0)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc

    def search(
        self, keyword: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> List[StockBasicSchema]:
        pattern = f"%{keyword}%"
        try:
            statement = (
                select(StockBasic)
                .where(
                    or_(
                        StockBasic.stock_code.like(pattern),
                        StockBasic.stock_name.like(pattern),
                    )
                )
                .order_by(StockBasic.stock_code)
                .limit(limit)
            )
            rows = self._session.execute(statement).scalars().all()
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        return [
            StockBasicSchema(stock_code=row.stock_code, stock_name=row.stock_name)
            for row in rows
        ]

    def upsert_many(self, items: Sequence[StockBasicSchema]) -> int:
        """Insert new codes and refresh renamed ones, without per-row round trips."""
        try:
            existing: Dict[str, str] = {
                code: name
                for code, name in self._session.execute(
                    select(StockBasic.stock_code, StockBasic.stock_name)
                ).all()
            }
            inserts = [
                {"stock_code": item.stock_code, "stock_name": item.stock_name}
                for item in items
                if item.stock_code not in existing
            ]
            updates = [
                {"code": item.stock_code, "name": item.stock_name}
                for item in items
                if existing.get(item.stock_code) not in (None, item.stock_name)
            ]
            if inserts:
                self._session.execute(insert(StockBasic), inserts)
            if updates:
                # Refresh renamed codes through the Core table statement.
                #
                # The ORM form (``update(StockBasic)`` + executemany) is rejected by
                # SQLAlchemy 2.0 whenever the statement carries extra WHERE criteria:
                # "bulk synchronize of persistent objects not supported when using
                # bulk update with additional WHERE criteria". Turning synchronisation
                # off does not help either - it moves the failure to "per-row ORM Bulk
                # UPDATE by Primary Key requires that records contain primary key
                # values", because these params are named ``code``/``name``.
                #
                # This branch runs whenever a code already exists with a changed name,
                # i.e. on every refresh of a populated catalog - which is why the
                # insert-only tests never reached it and the API answered
                # 500/50002 on merged main 83bcbd11.
                #
                # Nothing here needs the identity map refreshed: the existing codes
                # are read as column tuples, not ORM entities.
                self._session.execute(
                    StockBasic.__table__.update()
                    .where(StockBasic.__table__.c.stock_code == bindparam("code"))
                    .values(stock_name=bindparam("name")),
                    updates,
                )
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc
        return len(items)

    def get_state(self) -> Optional[CatalogSyncState]:
        try:
            row = self._session.get(StockCatalogSync, _SYNC_ROW_ID)
        except SQLAlchemyError as exc:
            raise DatabaseOperationError() from exc
        if row is None:
            return None
        return CatalogSyncState(
            status=row.status,
            row_count=int(row.row_count or 0),
            last_success_at=row.last_success_at,
            last_attempt_at=row.last_attempt_at,
            source=row.source,
            last_error=row.last_error,
        )

    def mark_success(
        self, *, row_count: int, source: Optional[str], at: datetime
    ) -> None:
        self._record(
            status=_STATUS_SUCCESS,
            row_count=row_count,
            source=source,
            error=None,
            at=at,
            update_success_at=True,
        )

    def mark_failure(self, *, error: str, at: datetime) -> None:
        """Record a failed attempt without touching ``last_success_at``."""
        self._record(
            status=_STATUS_FAILED,
            row_count=None,
            source=None,
            error=error[:500],
            at=at,
            update_success_at=False,
        )

    def _record(
        self,
        *,
        status: str,
        row_count: Optional[int],
        source: Optional[str],
        error: Optional[str],
        at: datetime,
        update_success_at: bool,
    ) -> None:
        try:
            row = self._session.get(StockCatalogSync, _SYNC_ROW_ID)
            if row is None:
                row = StockCatalogSync(
                    id=_SYNC_ROW_ID,
                    status=status,
                    last_attempt_at=at,
                    row_count=row_count or 0,
                )
                self._session.add(row)
            row.status = status
            row.last_attempt_at = at
            row.last_error = error
            if source is not None:
                row.source = source
            if update_success_at:
                row.last_success_at = at
                row.row_count = row_count or 0
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc


class StockCatalogService:
    """Sync the catalog and answer searches from MySQL."""

    def __init__(
        self,
        *,
        provider: StockDataProvider,
        repository: StockCatalogRepository,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._now = now or (lambda: datetime.now(timezone.utc))

    # -- sync ---------------------------------------------------------------

    def sync(self) -> CatalogSyncResult:
        """Fetch the full catalog, validate it, and persist it.

        A partial or malformed catalog is a failure: it is recorded as such and
        raised as ``StockDataProviderError`` so callers cannot mistake a broken
        source for a small market.
        """
        at = self._now()
        try:
            raw = self._provider.fetch_stock_catalog()
            items = self._validate_catalog(raw)
        except StockDataProviderError as exc:
            # A partial/invalid catalog is a failed sync, not a small market.
            self._repository.mark_failure(error=str(exc), at=at)
            raise

        source = getattr(self._provider, "last_catalog_source", None)
        self._repository.upsert_many(items)
        self._repository.mark_success(row_count=len(items), source=source, at=at)
        return CatalogSyncResult(row_count=len(items), source=source, synced_at=at)

    @staticmethod
    def _validate_catalog(raw) -> List[StockBasicSchema]:
        if raw is None:
            raise StockDataProviderError("stock catalog source returned nothing")
        items: Dict[str, StockBasicSchema] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("stock_code") or "").strip()
            name = str(item.get("stock_name") or "").strip()
            if len(code) != 6 or not code.isdigit() or not name:
                continue
            items[code] = StockBasicSchema(stock_code=code, stock_name=name)
        if len(items) < MIN_CATALOG_ROWS:
            raise StockDataProviderError(
                f"stock catalog looks partial ({len(items)} rows, "
                f"at least {MIN_CATALOG_ROWS} expected)"
            )
        return [items[code] for code in sorted(items)]

    # -- read ---------------------------------------------------------------

    def state(self) -> Optional[CatalogSyncState]:
        return self._repository.get_state()

    def is_catalog_usable(self) -> bool:
        state = self._repository.get_state()
        return bool(state and state.is_complete)

    def search(
        self, keyword: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> List[StockBasicSchema]:
        keyword = (keyword or "").strip()
        if not keyword:
            raise InvalidParameterError("keyword must not be empty")
        limit = max(1, min(int(limit), MAX_SEARCH_LIMIT))

        if self.is_catalog_usable():
            # Synced catalog: answer locally, no provider call. An empty result
            # here is a genuine "no match".
            return self._repository.search(keyword, limit)

        # Never synced: the catalog is the only viable source. Downloading the whole
        # market snapshot inside a search request is not an option - it measured ~34 s
        # for 5915 rows while the provider's retry budget is 4 s, so the old fallback
        # always ended in 50001 after ~4.7 s without ever succeeding. Report the state
        # explicitly instead, so the caller can trigger a sync and retry.
        raise CatalogNotSyncedError(
            "stock catalog has never been synced successfully; sync it "
            "(scripts/sync_stock_catalog.py) and retry"
        )
