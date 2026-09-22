# -*- coding: utf-8 -*-
"""V3: the explicit catalog-sync trigger (``POST /api/v1/stocks/catalog/sync``).

A (PR #23 review) found that nothing in the running service ever called
``StockCatalogService.sync()`` - only the CLI did. A real backend therefore started with an
empty catalog and answered **every** search with ``50006``. These tests pin the endpoint's
contract: it creates the catalog, unblocks search while search itself still never calls the
provider, is a repeatable refresh, and reports a failed refresh honestly without destroying
an already-synced catalog.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1.dependencies import get_stock_catalog_service
from backend.app.data.providers.base import StockDataProvider, StockDataProviderError
from backend.app.db.migrations import apply_migrations
from backend.app.main import app
from backend.app.services import stock_catalog_service as catalog_module
from backend.app.services.stock_catalog_service import (
    StockCatalogRepository,
    StockCatalogService,
)

SYNC_URL = "/api/v1/stocks/catalog/sync"
SEARCH_URL = "/api/v1/stocks/search"

THREE = [
    {"stock_code": "600519", "stock_name": "贵州茅台"},
    {"stock_code": "000001", "stock_name": "平安银行"},
    {"stock_code": "300750", "stock_name": "宁德时代"},
]


class _FakeProvider(StockDataProvider):
    """Catalog double; ``search_stocks`` must never be reached once a catalog exists."""

    def __init__(self, *, catalog=None, error=None, fail_after=None) -> None:
        self._catalog = catalog or []
        self._error = error
        self._fail_after = fail_after
        self.catalog_calls = 0
        self.search_calls = 0
        self.last_catalog_source = "fake-provider"

    def get_daily_kline(self, *args, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    def fetch_stock_catalog(self):
        self.catalog_calls += 1
        if self._error is not None:
            raise self._error
        if self._fail_after is not None and self.catalog_calls > self._fail_after:
            raise StockDataProviderError("catalog source is down")
        return self._catalog

    def search_stocks(self, keyword):  # pragma: no cover - must never be called
        self.search_calls += 1
        raise AssertionError("search must not call the provider once a catalog exists")


def _session() -> Session:
    # StaticPool + ``check_same_thread=False``: the TestClient runs the request in another
    # thread, and a plain ``sqlite://`` engine would hand it a *different*, empty in-memory
    # database (the tables are created on the first connection only).
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return Session(bind=engine)


def _client(session, provider, monkeypatch) -> TestClient:
    monkeypatch.setattr(catalog_module, "MIN_CATALOG_ROWS", 3)
    service = StockCatalogService(
        provider=provider, repository=StockCatalogRepository(session)
    )
    app.dependency_overrides[get_stock_catalog_service] = lambda: service
    return TestClient(app)


def test_sync_endpoint_creates_the_catalog_and_unblocks_search(monkeypatch):
    provider = _FakeProvider(catalog=THREE)
    with _session() as session:
        client = _client(session, provider, monkeypatch)
        try:
            # Before the trigger there is nothing to read - this is the state A hit.
            before = client.get(SEARCH_URL, params={"keyword": "茅台"})
            assert before.status_code == 503
            assert before.json()["code"] == 50006

            synced = client.post(SYNC_URL)
            assert synced.status_code == 200, synced.text
            data = synced.json()["data"]
            assert data["row_count"] == 3
            assert data["catalog_complete"] is True
            assert data["source"] == "fake-provider"
            assert data["synced_at"]

            after = client.get(SEARCH_URL, params={"keyword": "茅台"})
            assert after.status_code == 200, after.text
            assert [item["stock_code"] for item in after.json()["data"]] == ["600519"]
        finally:
            app.dependency_overrides.clear()

    # Exactly one provider call and it was the sync: the pre-sync search did not
    # download anything, so the frozen "search never syncs" contract still holds.
    assert provider.catalog_calls == 1
    assert provider.search_calls == 0


def test_sync_endpoint_is_a_repeatable_refresh(monkeypatch):
    provider = _FakeProvider(catalog=THREE)
    with _session() as session:
        client = _client(session, provider, monkeypatch)
        try:
            first = client.post(SYNC_URL)
            second = client.post(SYNC_URL)
        finally:
            app.dependency_overrides.clear()

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["row_count"] == 3
    assert second.json()["data"]["row_count"] == 3
    assert provider.catalog_calls == 2


def test_failed_first_sync_is_reported_and_search_stays_at_50006(monkeypatch):
    provider = _FakeProvider(error=StockDataProviderError("catalog source is down"))
    with _session() as session:
        client = _client(session, provider, monkeypatch)
        try:
            failed = client.post(SYNC_URL)
            search = client.get(SEARCH_URL, params={"keyword": "茅台"})
        finally:
            app.dependency_overrides.clear()

    assert failed.status_code == 502, failed.text
    assert failed.json()["code"] == 50001
    assert search.status_code == 503
    assert search.json()["code"] == 50006
    assert provider.search_calls == 0


def test_failed_refresh_keeps_the_previous_catalog_searchable(monkeypatch):
    provider = _FakeProvider(catalog=THREE, fail_after=1)
    with _session() as session:
        client = _client(session, provider, monkeypatch)
        try:
            assert client.post(SYNC_URL).status_code == 200
            failed = client.post(SYNC_URL)
            search = client.get(SEARCH_URL, params={"keyword": "平安"})
        finally:
            app.dependency_overrides.clear()

    assert failed.status_code == 502
    assert failed.json()["code"] == 50001
    # The earlier success still answers searches - and still without the provider.
    assert search.status_code == 200, search.text
    assert [item["stock_code"] for item in search.json()["data"]] == ["000001"]
    assert provider.search_calls == 0
