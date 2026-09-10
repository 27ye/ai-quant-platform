"""Real AI dependency graph with synthetic data and a mocked HTTP LLM boundary.

SQLite here is a test fixture, never a production fallback. The generated bars
are deliberately synthetic and do not represent an exchange trading calendar.
"""

import asyncio
import json
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.ai.client import OpenAICompatibleLLMClient
from backend.app.api.v1 import dependencies
from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProviderError,
)
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.models.stock_daily import StockDaily
from backend.app.models.stock_news import StockNews
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.market_data_service import MarketDataRepository
from backend.app.services.stock_service import StockService


OUTPUT = {
    "trend": "neutral",
    "summary": "仅解释提供的数据。",
    "technical_analysis": "技术指标来自量化模块。",
    "quant_analysis": "评分由确定性流水线提供。",
    "news_analysis": "仅依据提供的新闻；没有新闻时数据暂不可用。",
    "advantages": ["数据口径已明确"],
    "risks": ["历史表现不能保证未来收益"],
    "conclusion": "审慎分析，注意数据时效。",
}


class SyntheticProvider:
    def __init__(self):
        days = pd.bdate_range(end=date.today(), periods=120)
        closes = [100 + i / 20 + math.sin(i / 5) for i in range(120)]
        self.frame = pd.DataFrame({
            "stock_code": "600519", "trade_date": days.date,
            "open": closes, "high": [v + 1 for v in closes],
            "low": [v - 1 for v in closes], "close": closes,
            "volume": 10000, "amount": 1000000.123,
            "turnover_rate": 0.01234567, "change_pct": 0.00123456,
        })
        self.news = [{
            "stock_code": "600519", "title": "明确标记的模拟新闻",
            "summary": "仅用于自动化测试", "source": "synthetic-test",
            "publish_time": datetime.now(), "url": "https://example.invalid/news",
        }]
        self.events = []
        self.error_at = None
        self.error = None

    def _call(self, stage):
        self.events.append(stage)
        if self.error_at == stage:
            raise self.error

    def get_stock_info(self, stock_code):
        self._call("stock")
        return {"stock_code": stock_code, "stock_name": "贵州茅台", "industry": "白酒"}

    def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
        self._call("market")
        assert adjust == "qfq"
        return self.frame.loc[
            (self.frame.trade_date >= start_date) & (self.frame.trade_date <= end_date)
        ].copy()

    def get_stock_news(self, stock_code, limit):
        self._call("news")
        return list(self.news[:limit])


class SyntheticCalendar:
    """Fixture-only calendar; never reaches AKShare."""

    def __init__(self, state):
        self._state = state
        self.calls = []

    def count_between(self, start, end):
        self.calls.append((start, end))
        if self._state.calendar_mode == "raise":
            raise RuntimeError("secret calendar detail")
        if self._state.calendar_mode == "unknown":
            return None
        dates = set(self._state.provider.frame.trade_date)
        return sum(start <= day <= end for day in dates)


@pytest.fixture
def graph(monkeypatch):
    state = SimpleNamespace(
        provider=SyntheticProvider(), requests=[], responses=[],
        llm_status=200, llm_timeout=False, fail_report=False,
        fail_read=False, rollbacks=0, market_queries=0, sessions=[],
        market_query_calls=[], calendar_mode="unknown",
    )
    state.calendar = SyntheticCalendar(state)

    class RecordingSession(Session):
        def commit(self):
            if state.fail_report and any(isinstance(row, AIAnalysis) for row in self.new):
                raise SQLAlchemyError("secret database detail")
            return super().commit()

        def query(self, *args, **kwargs):
            if state.fail_read:
                raise SQLAlchemyError("secret database read detail")
            return super().query(*args, **kwargs)

        def rollback(self):
            state.rollbacks += 1
            return super().rollback()

    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=RecordingSession)
    state.factory = factory

    def db_override():
        with factory() as db:
            state.sessions.append(db)
            yield db

    def respond(request):
        state.requests.append(json.loads(request.content))
        if state.llm_timeout:
            raise httpx.ReadTimeout("secret upstream timeout detail", request=request)
        if state.llm_status != 200:
            return httpx.Response(state.llm_status, json={"error": "secret upstream detail"})
        content = state.responses.pop(0) if state.responses else json.dumps(OUTPUT)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    llm = OpenAICompatibleLLMClient(api_key="synthetic-key",
                                   base_url="https://example.invalid/v1",
                                   model_name="integration-test-model", http_client=http_client)
    original_query = MarketDataService.query_daily

    def query_once(self, *args, **kwargs):
        state.market_queries += 1
        state.market_query_calls.append((args, kwargs))
        return original_query(self, *args, **kwargs)

    monkeypatch.setattr(MarketDataService, "query_daily", query_once)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[dependencies.get_data_provider] = lambda: state.provider
    app.dependency_overrides[dependencies.get_trading_calendar_provider] = (
        lambda: state.calendar
    )
    app.dependency_overrides[dependencies.get_llm_client] = lambda: llm
    try:
        with TestClient(app) as client:
            state.client = client
            yield state
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        asyncio.run(http_client.aclose())
        engine.dispose()


def analyze(graph):
    return graph.client.post("/api/v1/ai/analyze", json={"stock_code": "600519"})


def context_of(graph, request_index=0):
    prompt = graph.requests[request_index]["messages"][1]["content"]
    return json.loads(prompt.split("analysis_context=", 1)[1])


def _frame_from_api_rows(rows):
    return pd.DataFrame([
        {
            **row,
            "trade_date": date.fromisoformat(row["trade_date"]),
        }
        for row in rows
    ])


def test_real_graph_fetches_quantifies_reads_news_and_persists(graph):
    response = analyze(graph)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    context = context_of(graph)
    assert graph.provider.events == ["stock", "market", "news"]
    assert graph.market_queries == 1
    assert len(graph.sessions) == 1
    assert len(graph.requests) == 1
    assert context["technical_indicators"]["ma60"] is not None
    assert context["backtest_metrics"]["strategy_name"]
    assert context["market_snapshot"]["trade_date"] == str(graph.provider.frame.trade_date.max())
    assert context["market_snapshot"]["turnover_rate"] == 0.012346
    assert context["news"][0]["title"] == "明确标记的模拟新闻"
    assert data["quant_score"] == context["quant_score"]["score"]
    with graph.factory() as db:
        assert db.query(StockDaily).count() == 120
        assert db.query(StockNews).count() == 1
        record = db.query(AIAnalysis).one()
        for key, value in data.items():
            assert getattr(record, key) == value


def test_next_request_gets_new_market_and_reuses_fresh_news_cache(graph):
    assert analyze(graph).status_code == 200
    assert analyze(graph).status_code == 200
    assert graph.market_queries == 2
    assert graph.provider.events.count("market") == 2  # no trusted calendar injected
    assert graph.provider.events.count("news") == 1
    assert len(graph.sessions) == 2
    assert graph.sessions[0] is not graph.sessions[1]
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 2


def test_reliable_fixture_calendar_serves_explicit_window_from_cache(graph):
    graph.calendar_mode = "reliable"
    start = graph.provider.frame.trade_date.min()
    end = graph.provider.frame.trade_date.max()
    url = f"/api/v1/stocks/600519/kline?start_date={start}&end_date={end}"

    assert graph.client.get(url).status_code == 200
    assert graph.client.get(url).status_code == 200

    assert graph.market_queries == 2
    assert graph.provider.events.count("market") == 1
    assert len(graph.calendar.calls) == 2
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 0
        assert db.query(StockDaily).count() == 120


def test_calendar_error_is_50001_and_does_not_return_cache_or_write_report(graph):
    graph.calendar_mode = "reliable"
    assert graph.client.get(f"/api/v1/stocks/600519/kline").status_code == 200
    graph.provider.events.clear()
    graph.calendar_mode = "raise"

    kline = graph.client.get(f"/api/v1/stocks/600519/kline")
    response = analyze(graph)

    assert kline.status_code == 502
    assert kline.json() == {"code": 50001, "message": "data provider error", "data": None}
    assert response.status_code == 502
    assert response.json() == {"code": 50001, "message": "data provider error", "data": None}
    assert graph.provider.events == ["stock"]
    assert not graph.requests
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 0


def test_stock_quant_and_ai_routes_project_same_pipeline_window_and_params(graph):
    graph.calendar_mode = "reliable"
    client = graph.client

    kline = client.get("/api/v1/stocks/600519/kline")
    indicators = client.get("/api/v1/stocks/600519/indicators")
    score = client.get("/api/v1/stocks/600519/score")
    backtest = client.post("/api/v1/backtests", json={"stock_code": "600519"})
    ai = analyze(graph)

    assert kline.status_code == 200, kline.text
    assert indicators.status_code == 200, indicators.text
    assert score.status_code == 200, score.text
    assert backtest.status_code == 200, backtest.text
    assert ai.status_code == 200, ai.text
    for args, kwargs in graph.market_query_calls:
        assert args[0] == "600519"
        assert kwargs == {"min_rows": 60, "max_stale_days": 3, "max_gap_days": 15}

    pipeline = analyze_quant_dataframe(_frame_from_api_rows(kline.json()["data"]))
    context = context_of(graph)
    backtest_data = backtest.json()["data"].copy()
    backtest_data.pop("stock_code")

    assert indicators.json()["data"] == pipeline["series"]["indicators"]
    assert score.json()["data"] == pipeline["score"]
    assert backtest_data == pipeline["backtest"]
    assert context["technical_indicators"] == {
        key: pipeline["latest"].get(key)
        for key in (
            "trade_date", "ma5", "ma10", "ma20", "ma60", "macd",
            "macd_signal", "macd_hist", "rsi14", "boll_upper",
            "boll_middle", "boll_lower",
        )
    }
    assert context["quant_score"] == {
        "score": pipeline["score"]["score"],
        "level": pipeline["score"]["level"],
        "reasons": pipeline["score"]["reasons"],
    }
    assert context["backtest_metrics"] == {
        key: pipeline["backtest"].get(key)
        for key in (
            "strategy_name", "start_date", "end_date", "total_return",
            "annual_return", "max_drawdown", "sharpe_ratio", "win_rate",
            "trade_count", "benchmark_return",
        )
    }


@pytest.mark.parametrize("empty_provider", [False, True])
def test_stale_news_refresh_or_real_cached_fallback(graph, empty_provider):
    old_time = datetime.now() - timedelta(days=10)
    with graph.factory() as db:
        db.add(StockNews(stock_code="600519", title="旧的模拟新闻", publish_time=old_time))
        db.commit()
    if empty_provider:
        graph.provider.news = []
    assert analyze(graph).status_code == 200
    assert graph.provider.events.count("news") == 1
    item = context_of(graph)["news"][0]
    assert item["title"] == ("旧的模拟新闻" if empty_provider else "明确标记的模拟新闻")
    if empty_provider:
        assert datetime.fromisoformat(item["publish_time"]) == old_time


def test_genuinely_empty_news_is_not_fabricated(graph):
    graph.provider.news = []
    assert analyze(graph).status_code == 200
    assert context_of(graph)["news"] == []
    assert "新闻数据暂不可用" in graph.requests[0]["messages"][1]["content"]


@pytest.mark.parametrize("stage,error,code,status", [
    ("stock", InvalidStockCodeError("private"), 40001, 400),
    ("stock", EmptyStockDataError("private"), 40002, 404),
    ("market", StockDataProviderError("private"), 50001, 502),
    ("news", StockDataProviderError("private"), 50001, 502),
    ("news", InvalidStockCodeError("private"), 40001, 400),
])
def test_provider_errors_propagate_without_llm_or_report(graph, stage, error, code, status):
    graph.provider.error_at, graph.provider.error = stage, error
    response = analyze(graph)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["data"] is None
    assert "private" not in response.text
    assert not graph.requests
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 0


@pytest.mark.parametrize("low", [0, 0.000049])
def test_invalid_price_after_rounding_is_40003_not_quant_error(graph, low):
    graph.provider.frame = graph.provider.frame.tail(60).copy()
    graph.provider.frame.loc[graph.provider.frame.index[0], "low"] = low
    response = analyze(graph)
    assert response.status_code == 422
    assert response.json()["code"] == 40003
    assert not graph.requests
    with graph.factory() as db:
        assert db.query(StockDaily).count() == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_llm_http_failures_are_private_50005(graph, status):
    graph.llm_status = status
    response = analyze(graph)
    assert response.status_code == 500
    assert response.json() == {"code": 50005, "message": "ai service error", "data": None}
    assert len(graph.requests) == 1
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 0


def test_llm_timeout_maps_to_50005_without_retry(graph):
    graph.llm_timeout = True
    response = analyze(graph)
    assert response.json()["code"] == 50005
    assert "secret" not in response.text
    assert len(graph.requests) == 1


@pytest.mark.parametrize("second_valid", [False, True])
def test_invalid_json_and_schema_allow_exactly_one_repair(graph, second_valid):
    graph.responses = ["not json", json.dumps(OUTPUT) if second_valid else "{}"]
    response = analyze(graph)
    assert response.json()["code"] == (0 if second_valid else 50005)
    assert len(graph.requests) == 2
    assert graph.market_queries == 1
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == int(second_valid)


def test_report_commit_failure_rolls_back_and_returns_50002(graph):
    graph.fail_report = True
    response = analyze(graph)
    assert response.json() == {"code": 50002, "message": "database error", "data": None}
    assert graph.rollbacks == 1
    with graph.factory() as db:
        assert db.query(AIAnalysis).count() == 0


def test_market_database_read_failure_has_no_provider_fallback(graph):
    graph.fail_read = True
    response = analyze(graph)
    assert response.json() == {"code": 50002, "message": "database error", "data": None}
    assert graph.provider.events == ["stock"]
    assert graph.rollbacks == 1
    assert not graph.requests


def test_full_quant_results_match_normalized_first_query_and_cache(graph):
    from backend.app.quant.pipeline import analyze_quant_dataframe

    provider = graph.provider
    stock = StockService(provider)
    start, end = provider.frame.trade_date.min(), provider.frame.trade_date.max()
    normalized = MarketDataService(stock_service=stock).sync_daily("600519", start, end)
    with graph.factory() as db:
        market = MarketDataService(stock_service=stock, repository=MarketDataRepository(db))
        # Exact known synthetic fixture dates, NOT a guessed production calendar.
        expected_dates = set(provider.frame.trade_date)
        def count_fixture_dates(first, last):
            return sum(first <= day <= last for day in expected_dates)

        first = market.query_daily("600519", start, end, trading_days=count_fixture_dates)
        calls = provider.events.count("market")
        cached = market.query_daily("600519", start, end, trading_days=count_fixture_dates)
        assert provider.events.count("market") == calls
        results = [analyze_quant_dataframe(pd.DataFrame([row.model_dump() for row in rows]))
                   for rows in (normalized, first, cached)]
        assert results[0] == results[1] == results[2]


@pytest.mark.parametrize("missing_indices", [range(40, 45), range(5, 105, 5)])
def test_unknown_cache_completeness_refetches_middle_holes(graph, missing_indices):
    assert analyze(graph).status_code == 200
    dates = graph.provider.frame.trade_date.iloc[list(missing_indices)].tolist()
    with graph.factory() as db:
        # Deletes only records in this test's fresh in-memory SQLite database.
        db.query(StockDaily).filter(StockDaily.trade_date.in_(dates)).delete(synchronize_session=False)
        db.commit()
    assert analyze(graph).status_code == 200
    assert graph.provider.events.count("market") == 2
    with graph.factory() as db:
        assert db.query(StockDaily).count() == 120
    assert context_of(graph, 0)["backtest_metrics"] == context_of(graph, 1)["backtest_metrics"]
