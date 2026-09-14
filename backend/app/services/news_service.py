"""News service: fetch (AKShare) -> normalize -> persist (stock_news) -> query.

Satisfies the ``NewsAnalysisService`` protocol consumed by D's AI context
(``get_news(stock_code, limit) -> Sequence[NewsItemContext]``), so the same
unified news structure feeds both the public news API and the AI pipeline.

News results are always returned newest-first (``publish_time`` descending,
``NULL`` last), regardless of the source ordering, so ``limit`` truncates the
latest news rather than whatever order AKShare happened to return.

Refresh policy: a non-empty cache is only served when its newest ``publish_time``
is recent (within ``max_age_seconds``); a stale cache (or ``refresh=True``)
triggers a fresh provider fetch that is upserted. This ensures new news keeps
flowing in instead of the cache being frozen at its first fetch.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError
from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import StockDataProvider
from backend.app.models.stock_news import StockNews
from backend.app.schemas.ai import NewsItemContext

DEFAULT_NEWS_LIMIT = 10
MAX_NEWS_LIMIT = 50
#: Default cache freshness window: refetch when the newest cached news is older.
DEFAULT_NEWS_TTL_SECONDS = 6 * 60 * 60


class NewsSource(Protocol):
    """Injectable news source consumed by the AI pipeline / API layer."""

    def get_news(
        self,
        stock_code: str,
        limit: int = DEFAULT_NEWS_LIMIT,
        max_age_seconds: Optional[int] = None,
        refresh: bool = False,
    ) -> Sequence[NewsItemContext]:
        """Return a bounded, normalized news list (newest first, ``NULL`` last).

        ``max_age_seconds`` caps the cache age; ``refresh=True`` bypasses the
        cache and always fetches from the provider.
        """
        ...


class NewsRepository:
    """Persist and read ``stock_news`` records.

    All ``SQLAlchemyError`` failures are translated into ``DatabaseOperationError``
    (business code 50002) and the session is rolled back, so callers observe a
    stable business error instead of a raw driver exception.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, items: Sequence[dict]) -> int:
        """Insert or update news items, deduplicated by stock + url/title."""
        try:
            count = 0
            for item in items:
                record = self._find(item)
                if record is None:
                    self._session.add(
                        StockNews(
                            stock_code=item["stock_code"],
                            title=item["title"],
                            summary=item.get("summary"),
                            source=item.get("source"),
                            publish_time=item.get("publish_time"),
                            url=item.get("url"),
                        )
                    )
                else:
                    record.title = item["title"]
                    record.summary = item.get("summary")
                    record.source = item.get("source")
                    record.publish_time = item.get("publish_time")
                    record.url = item.get("url")
                count += 1
            self._session.commit()
            return count
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def list_by_stock(self, stock_code: str, limit: int) -> List[StockNews]:
        try:
            records = (
                self._session.query(StockNews)
                .filter(StockNews.stock_code == stock_code)
                .order_by(StockNews.publish_time.desc())
                .limit(limit)
                .all()
            )
            return records
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc

    def _find(self, item: dict) -> Optional[StockNews]:
        try:
            query = self._session.query(StockNews).filter(
                StockNews.stock_code == item["stock_code"]
            )
            url = item.get("url")
            if url:
                query = query.filter(StockNews.url == url)
            else:
                query = query.filter(StockNews.title == item["title"])
            return query.first()
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseOperationError() from exc


class NewsService:
    """Implements the ``NewsSource`` / ``NewsAnalysisService`` protocol."""

    def __init__(
        self,
        provider: Optional[StockDataProvider] = None,
        repository: Optional[NewsRepository] = None,
        limit: int = DEFAULT_NEWS_LIMIT,
        max_age_seconds: int = DEFAULT_NEWS_TTL_SECONDS,
    ) -> None:
        self._provider = provider or AKShareStockProvider()
        self._repository = repository
        self._default_limit = min(max(limit, 1), MAX_NEWS_LIMIT)
        self._default_max_age = max_age_seconds

    def get_news(
        self,
        stock_code: str,
        limit: int = DEFAULT_NEWS_LIMIT,
        max_age_seconds: Optional[int] = None,
        refresh: bool = False,
    ) -> Sequence[NewsItemContext]:
        """Return a bounded, normalized news list (newest first, ``NULL`` last).

        * ``refresh=False`` and cache non-empty and not stale -> serve the cache;
        * otherwise -> fetch from the provider, upsert, and return the newest
          ``limit`` items (falling back to the cache only if the provider returns
          nothing).
        """
        bound = min(max(limit, 1), MAX_NEWS_LIMIT)
        max_age = (
            max_age_seconds if max_age_seconds is not None else self._default_max_age
        )
        if self._repository is not None and not refresh:
            cached = self._repository.list_by_stock(stock_code, bound)
            if cached and not self._is_stale(cached, max_age):
                return [self._to_item(record) for record in cached[:bound]]

        raw_items = self._provider.get_stock_news(stock_code, limit=MAX_NEWS_LIMIT)
        if self._repository is not None and raw_items:
            self._repository.upsert(raw_items)
        if raw_items:
            ordered = self._sort_by_publish_time_desc(raw_items)
            return [self._from_raw(item) for item in ordered[:bound]]

        # Provider returned nothing; still serve any cached rows rather than empty.
        if self._repository is not None:
            cached = self._repository.list_by_stock(stock_code, bound)
            if cached:
                return [self._to_item(record) for record in cached[:bound]]
        return []

    @staticmethod
    def _is_stale(cached: Sequence[StockNews], max_age: int) -> bool:
        newest = None
        for record in cached:
            if record.publish_time is not None:
                newest = record.publish_time
                break
        if newest is None:
            return True
        try:
            return (datetime.now() - newest).total_seconds() > max_age
        except TypeError:
            return True

    @staticmethod
    def _sort_by_publish_time_desc(items: List[dict]) -> List[dict]:
        def key(item: dict) -> datetime:
            # ``None`` is treated as the smallest timestamp so it sorts last
            # in descending order.
            return item.get("publish_time") or datetime.min

        return sorted(items, key=key, reverse=True)

    @staticmethod
    def _from_raw(item: dict) -> NewsItemContext:
        return NewsItemContext(
            title=item["title"],
            summary=item.get("summary"),
            source=item.get("source"),
            publish_time=item.get("publish_time"),
            url=item.get("url"),
        )

    @staticmethod
    def _to_item(record: StockNews) -> NewsItemContext:
        return NewsItemContext(
            title=record.title,
            summary=record.summary,
            source=record.source,
            publish_time=record.publish_time,
            url=record.url,
        )
