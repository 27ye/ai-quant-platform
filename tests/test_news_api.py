from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.migrations import apply_migrations
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.stock_news import StockNews

STOCK_CODE = "600519"


def _session_with_news() -> Session:
    # SQLite in-memory is thread-bound; StaticPool + check_same_thread=False lets
    # the same in-memory DB be shared with FastAPI's TestClient worker thread.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    session = Session(bind=engine)
    session.add(
        StockNews(
            stock_code=STOCK_CODE,
            title="贵州茅台发布年度业绩预告",
            summary="业绩预增",
            source="交易所",
            publish_time=datetime(2026, 8, 31, 9, 30),
            url="http://finance.eastmoney.com/a/1.html",
        )
    )
    session.commit()
    return session


def test_news_endpoint_returns_unified_schema():
    with _session_with_news() as session:
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/news")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["message"] == "success"
    data = payload["data"]
    assert len(data) == 1
    assert data[0]["stock_code"] == STOCK_CODE
    assert data[0]["title"] == "贵州茅台发布年度业绩预告"
    assert data[0]["source"] == "交易所"
    assert data[0]["publish_time"].startswith("2026-08-31")
    assert data[0]["url"].startswith("http://")


def test_news_endpoint_rejects_out_of_range_limit():
    with _session_with_news() as session:
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/news?limit=0")
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_news_endpoint_returns_50002_on_database_error():
    class FailingSession:
        def __init__(self):
            self.rolled_back = False

        def query(self, *args, **kwargs):
            raise SQLAlchemyError("db down")

        def rollback(self):
            self.rolled_back = True

    app.dependency_overrides[get_db] = lambda: FailingSession()
    try:
        response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/news")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {
        "code": 50002,
        "message": "database error",
        "data": None,
    }
