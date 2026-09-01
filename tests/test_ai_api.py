from fastapi.testclient import TestClient

from backend.app.api.v1.dependencies import get_ai_analysis_service
from backend.app.ai.errors import LLMResponseError
from backend.app.core.errors import StockNotFoundError
from backend.app.main import app
from backend.app.schemas.ai import AIAnalysisData


class FakeAIAnalysisService:
    async def analyze(self, stock_code):
        return AIAnalysisData(
            stock_code=stock_code,
            quant_score=82,
            trend="bullish",
            summary="趋势偏强。",
            technical_analysis="技术指标整体偏强。",
            quant_analysis="量化评分较高。",
            news_analysis="新闻信息整体中性。",
            advantages=["品牌优势"],
            risks=["市场波动"],
            conclusion="结合风险承受能力审慎判断。",
            model_name="test-model",
        )


def test_ai_analyze_response_contract():
    app.dependency_overrides[get_ai_analysis_service] = lambda: FakeAIAnalysisService()
    client = TestClient(app)
    try:
        response = client.post("/api/v1/ai/analyze", json={"stock_code": "600519"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["message"] == "success"
    assert response.json()["data"]["stock_code"] == "600519"
    assert response.json()["data"]["quant_score"] == 82


def test_ai_analyze_uses_unified_invalid_parameter_error():
    app.dependency_overrides[get_ai_analysis_service] = lambda: FakeAIAnalysisService()
    client = TestClient(app)
    try:
        response = client.post("/api/v1/ai/analyze", json={"stock_code": 600519})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {
        "code": 40001,
        "message": "invalid parameter",
        "data": None,
    }


def test_ai_analyze_maps_stock_not_found_error():
    class MissingStockService:
        async def analyze(self, stock_code):
            raise StockNotFoundError()

    app.dependency_overrides[get_ai_analysis_service] = lambda: MissingStockService()
    client = TestClient(app)
    try:
        response = client.post("/api/v1/ai/analyze", json={"stock_code": "600519"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["code"] == 40002


def test_ai_analyze_hides_llm_error_details():
    class FailingLLMService:
        async def analyze(self, stock_code):
            raise LLMResponseError("upstream detail must stay private")

    app.dependency_overrides[get_ai_analysis_service] = lambda: FailingLLMService()
    client = TestClient(app)
    try:
        response = client.post("/api/v1/ai/analyze", json={"stock_code": "600519"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {
        "code": 50005,
        "message": "ai service error",
        "data": None,
    }


def test_ai_analyze_reports_missing_upstream_service_integration():
    app.dependency_overrides.clear()
    client = TestClient(app)

    response = client.post("/api/v1/ai/analyze", json={"stock_code": "600519"})

    assert response.status_code == 422
    assert response.json() == {
        "code": 40003,
        "message": "insufficient stock data",
        "data": None,
    }
