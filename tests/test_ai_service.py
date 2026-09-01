import asyncio
from datetime import date, datetime

from backend.app.schemas.ai import (
    AnalysisContext,
    MarketSnapshotContext,
    QuantScoreContext,
    StockAnalysisContext,
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

    def save(self, analysis):
        self.saved.append(analysis)


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
    assert repository.saved == [result]
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
