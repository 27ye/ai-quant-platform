"""News service: fetch (AKShare) -> normalize -> persist (stock_news) -> query.

Satisfies the ``NewsAnalysisService`` protocol consumed by D's AI context
(``get_news(stock_code, limit) -> Sequence[NewsItemContext]``), so the same
unified news structure feeds both the public news API and the AI pipeline.

News results are always returned newest-first (``publish_time`` descending,
``NULL`` last), regardless of the source ordering, so ``limit`` truncates the
latest news rather than whatever order AKShare happened to return.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError
from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import StockDataProvider
from backend.app.models.stock_news import StockNews
from backend.app.schemas.ai import NewsItemContext

DEFAULT_NEWS_LIMIT = 10
MAX_NEWS_LIMIT = 50


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
    """Implements the ``NewsAnalysisService`` protocol over provider + repository."""

    def __init__(
        self,
        provider: Optional[StockDataProvider] = None,
        repository: Optional[NewsRepository] = None,
        limit: int = DEFAULT_NEWS_LIMIT,
    ) -> None:
        self._provider = provider or AKShareStockProvider()
        self._repository = repository
        self._default_limit = min(max(limit, 1), MAX_NEWS_LIMIT)

    def get_news(self, stock_code: str, limit: int = DEFAULT_NEWS_LIMIT) -> Sequence[NewsItemContext]:
        """Return a bounded, normalized news list (newest first, ``NULL`` last).

        Reads from MySQL first; on an empty cache it fetches from AKShare and
        persists the result. The returned sequence is always re-sorted by
        ``publish_time`` descending (``NULL`` last) and then ``limit``-truncated.
        """
        bound = min(max(limit, 1), MAX_NEWS_LIMIT)
        if self._repository is not None:
            stored = self._repository.list_by_stock(stock_code, bound)
            if stored:
                return [self._to_item(record) for record in stored[:bound]]
        # Fetch a superset first: the provider returns items in its own (non
        # time-sorted) order, so requesting only ``bound`` rows would drop the
        # newest items before they can be sorted. Sort + truncate afterwards.
        raw_items = self._provider.get_stock_news(stock_code, limit=MAX_NEWS_LIMIT)
        if self._repository is not None and raw_items:
            self._repository.upsert(raw_items)
        ordered = self._sort_by_publish_time_desc(raw_items)
        return [self._from_raw(item) for item in ordered[:bound]]

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
