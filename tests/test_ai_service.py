import asyncio
from datetime import date, datetime

import pytest

from backend.app.ai.errors import LLMOutputValidationError
from backend.app.schemas.ai import (
    AnalysisContext,
    AIReportDetail,
    DataProvenance,
    MarketSnapshotContext,
    QuantScoreContext,
    StockAnalysisContext,
    PaginatedAIReports,
)
from backend.app.services.ai_analysis import AIAnalysisService


VALID_OUTPUT = """{
  "trend": "bullish",
  "summary": "趋势偏强。",
  "technical_analysis": "技术指标整体偏强。",
  "quant_analysis": "量化评分较高。",
  "news_analysis": "新闻信息整体中性。",
  "advantages": ["品牌优势"],
  "risks": ["市场波动"],
  "conclusion": "结合风险承受能力审慎判断。"
}"""


class FakeContextProvider:
    def get_context(self, stock_code):
        return AnalysisContext(
            stock=StockAnalysisContext(
                stock_code=stock_code,
                stock_name="贵州茅台",
            ),
            market_snapshot=MarketSnapshotContext(
                trade_date=date(2026, 8, 31),
                close=1450.5,
            ),
            quant_score=QuantScoreContext(
                score=82,
                level="strong",
                reasons=["趋势得分较高"],
            ),
            data_as_of=datetime(2026, 8, 31, 15, 0, 0),
            provenance=DataProvenance(
                source_mode="live",
                provider="test",
                market_start_date=date(2026, 1, 1),
                market_end_date=date(2026, 8, 31),
                market_rows=120,
                news_status="empty",
                news_count=0,
                retrieved_at=datetime(2026, 8, 31, 15, 0, 0),
            ),
        )


class FakeLLMClient:
    model_name = "test-model"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    async def complete_json(self, messages):
        self.calls.append(messages)
        return next(self.outputs)


class RecordingRepository:
    def __init__(self):
        self.saved = []

    def save(self, analysis, context, metadata):
        self.saved.append((analysis, context, metadata))
        return AIReportDetail(
            **analysis.model_dump(),
            report_id=1,
            created_at=datetime(2026, 8, 31, 15, 1, 0),
            data_as_of=context.data_as_of,
            source_mode=metadata.source_mode,
            prompt_version=metadata.prompt_version,
            context_schema_version=metadata.context_schema_version,
            output_schema_version=metadata.output_schema_version,
            context_hash=metadata.context_hash,
            snapshot_status="complete",
            context_snapshot=context,
        )

    def list_reports(self, stock_code, page, page_size):
        raise AssertionError("not used")

    def get_report(self, report_id):
        raise AssertionError("not used")


def test_ai_service_builds_validated_result_and_persists_it():
    repository = RecordingRepository()
    client = FakeLLMClient([VALID_OUTPUT])
    service = AIAnalysisService(
        context_provider=FakeContextProvider(),
        llm_client=client,
        repository=repository,
    )

    result = asyncio.run(service.analyze("600519"))

    assert result.stock_code == "600519"
    assert result.quant_score == 82
    assert result.model_name == "test-model"
    assert result.report_id == 1
    assert repository.saved[0][0].stock_code == result.stock_code
    assert repository.saved[0][1] == result.context_snapshot
    assert repository.saved[0][2].context_hash == result.context_hash
    assert len(client.calls) == 1


def test_ai_service_retries_invalid_output_once():
    repository = RecordingRepository()
    client = FakeLLMClient(["not-json", VALID_OUTPUT])
    service = AIAnalysisService(
        context_provider=FakeContextProvider(),
        llm_client=client,
        repository=repository,
    )

    result = asyncio.run(service.analyze("600519"))

    assert result.trend == "bullish"
    assert len(client.calls) == 2
    assert "未通过 JSON Schema 校验" in client.calls[1][-1]["content"]


def test_ai_service_stops_after_second_invalid_output():
    repository = RecordingRepository()
    client = FakeLLMClient(["not-json", "still-not-json"])
    service = AIAnalysisService(
        context_provider=FakeContextProvider(),
        llm_client=client,
        repository=repository,
    )

    with pytest.raises(LLMOutputValidationError):
        asyncio.run(service.analyze("600519"))

    assert len(client.calls) == 2
    assert repository.saved == []


def test_history_methods_only_delegate_to_repository():
    class ForbiddenContextProvider:
        def get_context(self, stock_code):
            raise AssertionError("history read must not build context")

    class ForbiddenLLM:
        model_name = "unused"

        async def complete_json(self, messages):
            raise AssertionError("history read must not call LLM")

    class HistoryRepository:
        def __init__(self):
            self.calls = []

        def list_reports(self, stock_code, page, page_size):
            self.calls.append(("list", stock_code, page, page_size))
            return PaginatedAIReports(items=[], total=0, page=page, page_size=page_size)

        def get_report(self, report_id):
            self.calls.append(("get", report_id))
            return None

    repository = HistoryRepository()
    service = AIAnalysisService(
        context_provider=ForbiddenContextProvider(),
        llm_client=ForbiddenLLM(),
        repository=repository,
    )

    assert service.list_reports("600519", 2, 10).items == []
    assert service.get_report(99) is None
    assert repository.calls == [("list", "600519", 2, 10), ("get", 99)]
