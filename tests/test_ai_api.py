from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from backend.app.api.v1.dependencies import (
    get_ai_analysis_service,
    get_analysis_context_provider,
    get_backtest_analysis_service,
    get_news_analysis_service,
    get_quant_analysis_service,
    get_stock_analysis_service,
    get_data_provider,
    get_stock_service,
    get_trading_calendar_provider,
    get_market_data_source,
    get_stock_quant_analysis_adapter,
)
from backend.app.ai.errors import LLMResponseError
from backend.app.core.errors import DatabaseOperationError, StockNotFoundError
from backend.app.main import app
from backend.app.schemas.ai import (
    AIReportDetail,
    AIReportSummary,
    AnalysisContext,
    DataProvenance,
    MarketSnapshotContext,
    PaginatedAIReports,
    StockAnalysisContext,
)
from backend.app.services.ai_context_adapter import StockQuantAnalysisAdapter
from backend.app.services.market_data_service import MarketDataService
from backend.app.services.news_service import NewsService
from backend.app.services.analysis_context import ServiceAnalysisContextProvider


class FakeAIAnalysisService:
    async def analyze(self, stock_code):
        return _detail(stock_code)

    def list_reports(self, stock_code, page, page_size):
        item = AIReportSummary(
            report_id=1,
            stock_code=stock_code or "600519",
            quant_score=82,
            trend="bullish",
            summary="趋势偏强。",
            model_name="test-model",
            data_as_of=_timestamp(),
            created_at=_timestamp(),
            source_mode="live",
            snapshot_status="complete",
        )
        return PaginatedAIReports(items=[item], total=1, page=page, page_size=page_size)

    def get_report(self, report_id):
        return _detail("600519", report_id=report_id)


def _timestamp():
    return datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)


def _context(stock_code="600519"):
    return AnalysisContext(
        stock=StockAnalysisContext(stock_code=stock_code, stock_name="贵州茅台"),
        market_snapshot=MarketSnapshotContext(trade_date=date(2026, 8, 31), close=1450.5),
        data_as_of=_timestamp(),
        provenance=DataProvenance(
            source_mode="live",
            provider="test",
            market_start_date=date(2026, 1, 1),
            market_end_date=date(2026, 8, 31),
            market_rows=120,
            news_status="empty",
            news_count=0,
            retrieved_at=_timestamp(),
        ),
    )


def _detail(stock_code, report_id=1):
    return AIReportDetail(
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
            report_id=report_id,
            created_at=_timestamp(),
            data_as_of=_timestamp(),
            source_mode="live",
            prompt_version="v2.0",
            context_schema_version="v2.0",
            output_schema_version="v2.0",
            context_hash="a" * 64,
            snapshot_status="complete",
            context_snapshot=_context(stock_code),
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
    assert response.json()["data"]["report_id"] == 1
    assert response.json()["data"]["snapshot_status"] == "complete"


def test_ai_report_list_contract_and_validation():
    app.dependency_overrides[get_ai_analysis_service] = lambda: FakeAIAnalysisService()
    client = TestClient(app)
    try:
        response = client.get("/api/v1/ai/reports?stock_code=600519&page=2&page_size=10")
        invalid = client.get("/api/v1/ai/reports?page=0&page_size=101")
        invalid_stock = client.get("/api/v1/ai/reports?stock_code=abc")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["page"] == 2
    assert response.json()["data"]["page_size"] == 10
    assert "context_snapshot" not in response.json()["data"]["items"][0]
    assert invalid.status_code == 400
    assert invalid.json()["code"] == 40001
    assert invalid_stock.status_code == 400


def test_ai_report_detail_not_found_and_invalid_id():
    class MissingReportService(FakeAIAnalysisService):
        def get_report(self, report_id):
            return None

    app.dependency_overrides[get_ai_analysis_service] = lambda: MissingReportService()
    client = TestClient(app)
    try:
        missing = client.get("/api/v1/ai/reports/9")
        invalid = client.get("/api/v1/ai/reports/0")
    finally:
        app.dependency_overrides.clear()

    assert missing.status_code == 404
    assert missing.json() == {"code": 40005, "message": "report not found", "data": None}
    assert invalid.status_code == 400
    assert invalid.json()["code"] == 40001


def test_ai_report_history_maps_database_error():
    class FailingHistoryService(FakeAIAnalysisService):
        def list_reports(self, stock_code, page, page_size):
            raise DatabaseOperationError()

    app.dependency_overrides[get_ai_analysis_service] = lambda: FailingHistoryService()
    client = TestClient(app)
    try:
        response = client.get("/api/v1/ai/reports")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {"code": 50002, "message": "database error", "data": None}


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


def test_ai_dependency_graph_installs_real_context_adapters():
    db = object()  # constructors must not connect; request get_db supplies a real Session
    provider = get_data_provider()
    stock = get_stock_service(provider)
    calendar = get_trading_calendar_provider()
    market = get_market_data_source(stock, db, calendar)
    adapter = get_stock_quant_analysis_adapter(market, stock)
    stock_service = get_stock_analysis_service(adapter)
    quant_service = get_quant_analysis_service(adapter)
    backtest_service = get_backtest_analysis_service(adapter)
    news_service = get_news_analysis_service(provider, db)
    context_provider = get_analysis_context_provider(
        stock_service,
        quant_service,
        backtest_service,
        news_service,
    )

    assert isinstance(stock_service, StockQuantAnalysisAdapter)
    assert quant_service is stock_service
    assert backtest_service is stock_service
    assert isinstance(news_service, NewsService)
    assert isinstance(market, MarketDataService)
    assert news_service._repository._session is db
    assert market._repository._session is db
    assert isinstance(context_provider, ServiceAnalysisContextProvider)
