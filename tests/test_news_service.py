from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.errors import DatabaseOperationError
from backend.app.db.migrations import apply_migrations
from backend.app.models.stock_news import StockNews
from backend.app.schemas.ai import NewsItemContext
from backend.app.services.news_service import NewsRepository, NewsService

STOCK_CODE = "600519"


class FakeNewsProvider:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def get_stock_news(self, stock_code, limit=10):
        self.calls += 1
        return self.items[:limit]


def _session() -> Session:
    engine = create_engine("sqlite://")
    apply_migrations(engine)
    return Session(bind=engine)


def _raw_items():
    # Recent publish times (within the default 6h TTL) so the cache stays fresh.
    now = datetime.now()
    return [
        {
            "stock_code": STOCK_CODE,
            "title": "公司发布年度业绩预告",
            "summary": "业绩预增",
            "source": "东方财富",
            "publish_time": now - timedelta(hours=1),
            "url": "http://finance.eastmoney.com/a/1.html",
        },
        {
            "stock_code": STOCK_CODE,
            "title": "召开临时股东大会",
            "summary": None,
            "source": "交易所",
            "publish_time": now - timedelta(hours=2),
            "url": "http://finance.eastmoney.com/a/2.html",
        },
    ]


def test_get_news_fetches_persists_and_then_serves_from_db():
    provider = FakeNewsProvider(_raw_items())
    with _session() as session:
        repository = NewsRepository(session)
        service = NewsService(provider=provider, repository=repository)

        first = service.get_news(STOCK_CODE, limit=10)

        assert provider.calls == 1
        assert len(first) == 2
        assert all(isinstance(item, NewsItemContext) for item in first)
        assert first[0].title == "公司发布年度业绩预告"

        second = service.get_news(STOCK_CODE, limit=10)

        assert provider.calls == 1  # served from the DB cache, provider not called again
        assert len(second) == 2


def test_get_news_respects_limit():
    provider = FakeNewsProvider(_raw_items())
    with _session() as session:
        service = NewsService(provider=provider, repository=NewsRepository(session))

        items = service.get_news(STOCK_CODE, limit=1)

        assert len(items) == 1


def test_news_service_works_without_repository():
    provider = FakeNewsProvider(_raw_items())
    service = NewsService(provider=provider)

    items = service.get_news(STOCK_CODE, limit=10)

    assert len(items) == 2
    assert isinstance(items[0], NewsItemContext)


def test_get_news_orders_by_publish_time_descending_with_nulls_last():
    # Provider returns out-of-order news (as AKShare actually does).
    provider = FakeNewsProvider(
        [
            {"stock_code": STOCK_CODE, "title": "old", "source": "s1", "publish_time": datetime(2026, 8, 30), "url": "u1"},
            {"stock_code": STOCK_CODE, "title": "no-time", "source": "s2", "publish_time": None, "url": "u2"},
            {"stock_code": STOCK_CODE, "title": "new", "source": "s3", "publish_time": datetime(2026, 9, 2), "url": "u3"},
        ]
    )
    service = NewsService(provider=provider)

    items = service.get_news(STOCK_CODE, limit=10)

    assert [item.title for item in items] == ["new", "old", "no-time"]


def test_get_news_truncates_latest_first():
    provider = FakeNewsProvider(
        [
            {"stock_code": STOCK_CODE, "title": "old", "source": "s1", "publish_time": datetime(2026, 8, 30)},
            {"stock_code": STOCK_CODE, "title": "newest", "source": "s2", "publish_time": datetime(2026, 9, 2)},
        ]
    )
    service = NewsService(provider=provider)

    items = service.get_news(STOCK_CODE, limit=1)

    assert [item.title for item in items] == ["newest"]


class FailingWriteSession:
    def __init__(self):
        self.rolled_back = False

    def add(self, record):  # noqa: ANN001
        pass

    def query(self, *args, **kwargs):
        class _Query:
            def filter(self, *a, **k):
                return self

            def first(self):
                return None

            def one_or_none(self):
                return None

            def order_by(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def all(self):
                return []

        return _Query()

    def commit(self):
        raise SQLAlchemyError("commit failed")

    def rollback(self):
        self.rolled_back = True


def test_news_repository_converts_db_failure_to_database_operation_error():
    session = FailingWriteSession()
    repository = NewsRepository(session)

    with pytest.raises(DatabaseOperationError):
        repository.upsert(
            [
                {
                    "stock_code": STOCK_CODE,
                    "title": "公告",
                    "source": "交易所",
                    "publish_time": datetime(2026, 8, 31, 9, 30),
                    "url": "http://x/1.html",
                }
            ]
        )

    assert session.rolled_back is True


def test_get_news_refreshes_when_cache_is_stale():
    with _session() as session:
        session.add(
            StockNews(
                stock_code=STOCK_CODE,
                title="旧新闻",
                source="交易所",
                publish_time=datetime.now() - timedelta(days=2),  # older than TTL
                url="http://x/old.html",
            )
        )
        session.commit()
        provider = FakeNewsProvider(
            [
                {
                    "stock_code": STOCK_CODE,
                    "title": "新新闻",
                    "source": "东方财富",
                    "publish_time": datetime.now(),
                    "url": "http://x/new.html",
                }
            ]
        )
        service = NewsService(
            provider=provider, repository=NewsRepository(session), max_age_seconds=6 * 3600
        )

        items = service.get_news(STOCK_CODE, limit=10)

        assert provider.calls == 1  # stale cache -> refetch from provider
        assert items[0].title == "新新闻"


def test_get_news_uses_fresh_cache_without_refetch():
    with _session() as session:
        session.add(
            StockNews(
                stock_code=STOCK_CODE,
                title="缓存新闻",
                source="交易所",
                publish_time=datetime.now() - timedelta(hours=1),  # within TTL
                url="http://x/cached.html",
            )
        )
        session.commit()

        class RaiseProvider:
            def get_stock_news(self, *args, **kwargs):
                raise AssertionError("fresh cache must not hit the provider")

        service = NewsService(
            provider=RaiseProvider(), repository=NewsRepository(session), max_age_seconds=6 * 3600
        )

        items = service.get_news(STOCK_CODE, limit=10)

        assert items[0].title == "缓存新闻"


def test_get_news_refresh_flag_bypasses_fresh_cache():
    with _session() as session:
        session.add(
            StockNews(
                stock_code=STOCK_CODE,
                title="缓存新闻",
                source="交易所",
                publish_time=datetime.now(),
                url="http://x/cached.html",
            )
        )
        session.commit()
        provider = FakeNewsProvider(
            [
                {
                    "stock_code": STOCK_CODE,
                    "title": "强制刷新的新新闻",
                    "source": "东方财富",
                    "publish_time": datetime.now(),
                    "url": "http://x/forced.html",
                }
            ]
        )
        service = NewsService(
            provider=provider, repository=NewsRepository(session), max_age_seconds=6 * 3600
        )

        items = service.get_news(STOCK_CODE, limit=10, refresh=True)

        assert provider.calls == 1  # refresh=True bypasses the (fresh) cache
        assert items[0].title == "强制刷新的新新闻"


def test_get_news_falls_back_to_cache_when_provider_returns_nothing():
    with _session() as session:
        session.add(
            StockNews(
                stock_code=STOCK_CODE,
                title="兜底缓存",
                source="交易所",
                publish_time=datetime.now() - timedelta(hours=1),
                url="http://x/fallback.html",
            )
        )
        session.commit()

        class EmptyProvider:
            def get_stock_news(self, *args, **kwargs):
                return []

        service = NewsService(
            provider=EmptyProvider(), repository=NewsRepository(session), max_age_seconds=6 * 3600
        )

        items = service.get_news(STOCK_CODE, limit=10, refresh=True)

        assert items[0].title == "兜底缓存"
