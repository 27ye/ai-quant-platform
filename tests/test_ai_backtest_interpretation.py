"""V3 custom report contract, exact snapshot integrity and external isolation."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1 import dependencies
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.models.backtest_result import BacktestResult
from backend.app.quant.windowed_backtest import run_backtest_request
from backend.app.schemas.ai import BACKTEST_NEWS_DISCLOSURE
from backend.app.services.backtest_service import BacktestRepository

OUTPUT = {
    "trend": "bullish", "summary": "保存的回测表现。", "technical_analysis": "MA 策略。",
    "quant_analysis": "仅解释保存的结果。", "news_analysis": "不应保留这段新闻。",
    "advantages": ["参数明确"], "risks": ["历史不代表未来"], "conclusion": "谨慎解释。",
}


class FakeLLM:
    model_name = "saved-backtest-test"

    def __init__(self):
        self.calls = []
        self.responses = []

    async def complete_json(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0) if self.responses else json.dumps(OUTPUT)


@pytest.fixture
def custom_graph(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    frame = pd.DataFrame([
        {"stock_code": "600519", "trade_date": item.date(), "open": 100.0 + i, "high": 102.0 + i,
         "low": 99.0 + i, "close": 101.0 + i, "volume": 1000.0}
        for i, item in enumerate(pd.bdate_range("2025-01-01", periods=45))
    ])
    result = run_backtest_request(frame, start_date=frame.iloc[25].trade_date, end_date=frame.iloc[-1].trade_date, parameters={})
    with Session(engine) as db:
        backtest_id = BacktestRepository(db).save(
            stock_code="600519", result=result, semantics_version="v2_windowed",
            effective_parameters=result["effective_parameters"], warmup_start_date=frame.iloc[5].trade_date,
            data_meta={}, strategy_version=result["algorithm_version"],
            input_snapshot=result["input_snapshot"]["rows"], c_result=result,
        )
    llm = FakeLLM()

    def session_override():
        with Session(engine) as db:
            yield db

    def forbidden(*args, **kwargs):
        raise AssertionError("custom/history must not construct an external dependency")

    monkeypatch.setattr(dependencies, "get_data_provider", forbidden)
    monkeypatch.setattr(dependencies, "get_trading_calendar_provider", forbidden)
    monkeypatch.setattr(dependencies, "build_standard_ai_context", forbidden)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[dependencies.get_llm_client] = lambda: llm
    try:
        with TestClient(app) as client:
            yield client, engine, backtest_id, llm
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def generate(graph, **kwargs):
    client, _, backtest_id, _ = graph
    return client.post("/api/v1/ai/analyze", json={"stock_code": "600519", "backtest_id": backtest_id, **kwargs})


def test_custom_generate_readback_uses_exact_saved_context_without_external_services(custom_graph):
    client, engine, backtest_id, llm = custom_graph
    first = generate(custom_graph)
    assert first.status_code == 200, first.text
    report = first.json()["data"]
    assert report["analysis_mode"] == "custom_backtest"
    assert report["backtest_id"] == backtest_id
    assert report["quant_score"] is None
    assert report["trend"] == "neutral"
    assert report["news_analysis"] == BACKTEST_NEWS_DISCLOSURE
    assert report["source_mode"] == "unknown"
    assert report["prompt_version"] == report["context_schema_version"] == "v3.backtest.1"
    context = report["context_snapshot"]
    prompt_context = json.loads(llm.calls[0][1]["content"].split("analysis_context=", 1)[1])
    assert prompt_context == context
    assert context["data_as_of"] == context["backtest_created_at"]
    with Session(engine) as db:
        stored = db.get(AIAnalysis, report["report_id"])
        assert stored.context_snapshot == context
        saved = json.loads(db.get(BacktestResult, backtest_id).c_result_text)
        assert context["data_hash"] == saved["data_hash"]
        # The context hash is separate from C's input hash.
        assert report["context_hash"] != context["data_hash"]
        assert context["metrics"]["trade_count"] == saved["trade_count"]
    second = generate(custom_graph).json()["data"]
    assert second["report_id"] != report["report_id"]

    def forbidden_llm():
        raise AssertionError("history must not construct LLM")

    app.dependency_overrides[dependencies.get_llm_client] = forbidden_llm
    listed = client.get("/api/v1/ai/reports").json()["data"]
    assert [item["report_id"] for item in listed["items"]] == [second["report_id"], report["report_id"]]
    assert "context_snapshot" not in listed["items"][0]
    assert listed["items"][0]["analysis_mode"] == "custom_backtest"
    assert client.get(f"/api/v1/ai/reports/{report['report_id']}").json()["data"] == report
    assert len(llm.calls) == 2


@pytest.mark.parametrize(
    "value", [None, True, False, "1", 1.0, 0, -1, 9_223_372_036_854_775_808]
)
def test_custom_request_rejects_invalid_backtest_id(custom_graph, value):
    response = generate(custom_graph, backtest_id=value)
    assert response.status_code == 400
    assert response.json()["code"] == 40001
    assert custom_graph[-1].calls == []


@pytest.mark.parametrize("changes,status,code", [
    ({"backtest_id": 999}, 404, 40005),
    ({"stock_code": "000001"}, 400, 40001),
])
def test_custom_request_missing_and_stock_mismatch(custom_graph, changes, status, code):
    response = generate(custom_graph, **changes)
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert custom_graph[-1].calls == []


@pytest.mark.parametrize("mutation", ["legacy", "strategy", "inexact"])
def test_unsupported_saved_backtests_fail_before_llm(custom_graph, mutation):
    _, engine, backtest_id, llm = custom_graph
    with Session(engine) as db:
        row = db.get(BacktestResult, backtest_id)
        if mutation == "legacy":
            row.semantics_version = "v1_legacy"
        elif mutation == "strategy":
            row.strategy_name = "macd"
        else:
            row.c_result = json.loads(row.c_result_text)
        db.commit()
    response = generate(custom_graph)
    assert (response.status_code, response.json()["code"]) == (422, 40007)
    assert llm.calls == []


@pytest.mark.parametrize("mutation", ["text", "hash", "row", "metric", "curve", "warmup", "snapshot", "assumptions", "final_equity"])
def test_corrupt_exact_backtests_are_database_errors(custom_graph, mutation):
    _, engine, backtest_id, llm = custom_graph
    with Session(engine) as db:
        row = db.get(BacktestResult, backtest_id)
        result = json.loads(row.c_result_text)
        if mutation == "text":
            row.c_result_text = "broken"
        else:
            if mutation == "hash":
                result["data_hash"] = "0" * 64
            elif mutation == "row":
                result["input_snapshot"]["rows"][0]["close"] += 1
            elif mutation == "metric":
                del result["total_return"]
            elif mutation == "curve":
                result["equity_curve"].pop()
            elif mutation == "assumptions":
                result["execution_assumptions"] = {}
            elif mutation == "final_equity":
                result["final_equity"] += 1
            elif mutation == "warmup":
                result["warmup"]["used_rows"] = 1
            else:
                row.input_snapshot = None
            row.c_result_text = json.dumps(result)
        db.commit()
    response = generate(custom_graph)
    assert (response.status_code, response.json()["code"]) == (500, 50002), response.text
    assert llm.calls == []
    with Session(engine) as db:
        assert db.query(AIAnalysis).count() == 0


def test_custom_output_repairs_only_once_and_never_saves_failure(custom_graph):
    _, engine, _, llm = custom_graph
    llm.responses = ["not-json", "still-not-json"]
    response = generate(custom_graph)
    assert response.json()["code"] == 50005
    assert len(llm.calls) == 2
    with Session(engine) as db:
        assert db.query(AIAnalysis).count() == 0
    llm.responses = ["not-json", json.dumps(OUTPUT)]
    assert generate(custom_graph).status_code == 200
    assert len(llm.calls) == 4


@pytest.mark.parametrize("mutation", ["version", "mode", "id", "score", "trend", "hash", "news"])
def test_custom_history_rejects_inconsistent_saved_reports(custom_graph, mutation):
    client, engine, _, _ = custom_graph
    report = generate(custom_graph).json()["data"]
    with Session(engine) as db:
        row = db.get(AIAnalysis, report["report_id"])
        if mutation == "version":
            row.context_schema_version = "future"
        elif mutation == "mode":
            row.analysis_mode = "invalid"
        elif mutation == "id":
            row.backtest_id = None
        elif mutation == "score":
            row.quant_score = 50
        elif mutation == "trend":
            row.trend = "bullish"
        elif mutation == "hash":
            row.context_hash = "0" * 64
        else:
            row.news_analysis = "latest news"
        db.commit()
    response = client.get(f"/api/v1/ai/reports/{report['report_id']}")
    assert response.status_code == 500
    assert response.json()["code"] == 50002
    if mutation in {"version", "mode", "id", "score", "trend"}:
        assert client.get("/api/v1/ai/reports").json()["code"] == 50002


def test_custom_save_failure_rolls_back(custom_graph, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    _, engine, _, _ = custom_graph
    original = Session.commit

    def fail_ai_commit(self):
        if any(isinstance(item, AIAnalysis) for item in self.identity_map.values()):
            raise SQLAlchemyError("synthetic failure")
        return original(self)

    monkeypatch.setattr(Session, "commit", fail_ai_commit)
    response = generate(custom_graph)
    assert response.json()["code"] == 50002
    with Session(engine) as db:
        assert db.query(AIAnalysis).count() == 0


def test_custom_provenance_comes_only_from_saved_metadata(custom_graph):
    _, engine, backtest_id, _ = custom_graph
    with Session(engine) as db:
        row = db.get(BacktestResult, backtest_id)
        row.data_meta = {"source_mode": "frozen", "provider": "saved-fixture"}
        db.commit()
    response = generate(custom_graph)
    assert response.status_code == 200
    report = response.json()["data"]
    assert report["source_mode"] == "frozen"
    assert report["context_snapshot"]["provenance"]["provider"] == "saved-fixture"


def test_custom_metrics_use_exact_c_result_instead_of_rounded_summary(custom_graph):
    _, engine, backtest_id, _ = custom_graph
    with Session(engine) as db:
        row = db.get(BacktestResult, backtest_id)
        saved_value = json.loads(row.c_result_text)["total_return"]
        row.total_return = -0.5
        db.commit()
    report = generate(custom_graph).json()["data"]
    assert report["context_snapshot"]["metrics"]["total_return"] == float(format(saved_value, ".15g"))
    assert report["context_snapshot"]["metrics"]["total_return"] != -0.5
