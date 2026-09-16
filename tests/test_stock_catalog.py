"""V2 B1: local stock catalog sync and MySQL-backed search."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.core.errors import CatalogNotSyncedError, InvalidParameterError
from backend.app.data.providers.base import StockDataProvider, StockDataProviderError
from backend.app.db.migrations import apply_migrations
from backend.app.schemas.stock import StockBasicSchema
from backend.app.services import stock_catalog_service as catalog_module
from backend.app.services.stock_catalog_service import (
    MIN_CATALOG_ROWS,
    StockCatalogRepository,
    StockCatalogService,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    apply_migrations(engine)
    return Session(bind=engine)


def _catalog(*pairs):
    return [{"stock_code": code, "stock_name": name} for code, name in pairs]


class _FakeProvider(StockDataProvider):
    """Provider double that records whether it was called at all."""

    def __init__(self, *, catalog=None, catalog_error=None, search_items=None,
                 search_error=None) -> None:
        self._catalog = catalog
        self._catalog_error = catalog_error
        self._search_items = search_items or []
        self._search_error = search_error
        self.catalog_calls = 0
        self.search_calls = 0
        self.last_catalog_source = "fake-provider"

    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    def fetch_stock_catalog(self):
        self.catalog_calls += 1
        if self._catalog_error is not None:
            raise self._catalog_error
        return self._catalog

    def search_stocks(self, keyword):
        self.search_calls += 1
        if self._search_error is not None:
            raise self._search_error
        return self._search_items


def _service(session, provider, *, now=None):
    return StockCatalogService(
        provider=provider,
        repository=StockCatalogRepository(session),
        now=now,
    )


def test_sync_persists_catalog_and_marks_success(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 3)
    provider = _FakeProvider(catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行"), ("300750", "宁德时代")))

    with _session() as session:
        service = _service(session, provider)
        result = service.sync()

        assert result.row_count == 3
        assert result.source == "fake-provider"
        repository = StockCatalogRepository(session)
        assert repository.count() == 3
        state = repository.get_state()
        assert state is not None and state.status == "success"
        assert state.row_count == 3
        assert state.last_success_at is not None
        assert state.last_error is None


def test_sync_rejects_partial_catalog_with_default_threshold():
    """10 rows is a broken source, not a small market: never marked complete."""
    provider = _FakeProvider(catalog=_catalog(*[(f"{i:06d}", f"股票{i}") for i in range(10)]))

    with _session() as session:
        service = _service(session, provider)
        with pytest.raises(StockDataProviderError):
            service.sync()

        repository = StockCatalogRepository(session)
        state = repository.get_state()
        assert state is not None
        assert state.status == "failed"
        assert state.last_success_at is None
        assert state.is_complete is False
        assert str(MIN_CATALOG_ROWS) in (state.last_error or "")
        assert repository.count() == 0  # nothing partial written


def test_failed_sync_keeps_previous_success(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    ok_provider = _FakeProvider(catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行")))

    with _session() as session:
        service = _service(session, ok_provider)
        service.sync()
        repository = StockCatalogRepository(session)
        first = repository.get_state()
        assert first is not None and first.last_success_at is not None

        failing = _FakeProvider(catalog_error=StockDataProviderError("upstream down"))
        with pytest.raises(StockDataProviderError):
            _service(session, failing).sync()

        after = repository.get_state()
        assert after is not None
        assert after.status == "failed"
        assert after.last_success_at == first.last_success_at  # success time preserved
        assert after.row_count == first.row_count
        assert after.last_error == "upstream down"


def test_search_uses_local_catalog_without_calling_provider(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    provider = _FakeProvider(
        catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行")),
        search_error=AssertionError("provider must not be called when the catalog is synced"),
    )

    with _session() as session:
        service = _service(session, provider)
        service.sync()
        provider.search_calls = 0

        results = service.search("600519")

        assert [item.stock_code for item in results] == ["600519"]
        assert provider.search_calls == 0


def test_search_returns_empty_for_genuine_no_match_when_synced(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    provider = _FakeProvider(
        catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行")),
        search_error=AssertionError("provider must not be called"),
    )

    with _session() as session:
        service = _service(session, provider)
        service.sync()
        assert service.search("贵州银行") == []
        assert provider.search_calls == 0


def test_search_matches_code_and_name_and_respects_limit(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    pairs = [(f"60000{i}", f"测试股票{i}") for i in range(10)]
    provider = _FakeProvider(catalog=_catalog(*pairs))

    with _session() as session:
        service = _service(session, provider)
        service.sync()

        by_name = service.search("测试股票")
        assert len(by_name) == len(pairs)  # cats below the cap
        assert len(service.search("测试股票", limit=3)) == 3
        by_code = service.search("600005")
        assert [item.stock_code for item in by_code] == ["600005"]


def test_search_without_a_synced_catalog_reports_50006_and_skips_the_provider():
    """V2 B1: a cold-start search no longer attempts a full-market snapshot.

    That fallback could never fit the provider's bounded retry budget (a spot
    snapshot measured ~34 s against a 4 s budget), so it only ever produced a
    misleading 50001 after a multi-second wait. The state is reported explicitly.
    """
    provider = _FakeProvider(
        search_items=[{"stock_code": "600519", "stock_name": "贵州茅台"}]
    )

    with _session() as session:
        service = _service(session, provider)
        with pytest.raises(CatalogNotSyncedError) as excinfo:
            service.search("600519")

    assert excinfo.value.code == 50006
    assert provider.search_calls == 0


def test_failed_refresh_keeps_the_previous_catalog_searchable(monkeypatch):
    """C's chained case: a failed *refresh* must not mean "never synced".

    ``mark_failure`` leaves ``last_success_at``/``row_count`` untouched, so the
    catalog is still complete and search keeps answering from it instead of
    reporting 50006.
    """
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    provider = _FakeProvider(
        catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行"))
    )
    moment = [datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)]

    with _session() as session:
        service = _service(session, provider, now=lambda: moment[0])
        service.sync()

        # The next refresh fails.
        provider._catalog_error = StockDataProviderError("upstream unavailable")
        with pytest.raises(StockDataProviderError):
            service.sync()

        state = service.state()
        assert state.status == "failed"
        assert state.last_error is not None
        assert state.last_success_at is not None  # the previous success is kept
        assert state.is_complete is True
        assert service.is_catalog_usable() is True

        # Search still answers from the local catalog, without the provider.
        results = service.search("600519")

    assert [item.stock_code for item in results] == ["600519"]
    assert provider.search_calls == 0


def test_synced_catalog_answers_locally_without_touching_the_provider(monkeypatch):
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 2)
    provider = _FakeProvider(
        catalog=_catalog(("600519", "贵州茅台"), ("000001", "平安银行")),
        search_items=[{"stock_code": "999999", "stock_name": "must not be used"}],
    )

    with _session() as session:
        service = _service(session, provider)
        service.sync()
        results = service.search("茅台")

    assert [item.stock_code for item in results] == ["600519"]
    assert provider.search_calls == 0


def test_search_rejects_empty_keyword():
    provider = _FakeProvider(search_items=[])

    with _session() as session:
        service = _service(session, provider)
        with pytest.raises(InvalidParameterError):
            service.search("   ")
        assert provider.search_calls == 0


def test_repository_search_normalizes_schema():
    with _session() as session:
        repository = StockCatalogRepository(session)
        repository.upsert_many(
            [StockBasicSchema(stock_code="600519", stock_name="贵州茅台")]
        )
        rows = repository.search("茅台")
        assert isinstance(rows[0], StockBasicSchema)
        assert rows[0].stock_code == "600519"
