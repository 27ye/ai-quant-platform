from datetime import date, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas.ai import (
    AIAnalysisData,
    AIAnalysisStructuredOutput,
    AIAnalyzeRequest,
    AnalysisContext,
    MarketSnapshotContext,
    StockAnalysisContext,
)


def test_ai_analyze_request_requires_six_digit_string():
    assert AIAnalyzeRequest(stock_code="600519").stock_code == "600519"

    with pytest.raises(ValidationError):
        AIAnalyzeRequest(stock_code="60051")

    with pytest.raises(ValidationError):
        AIAnalyzeRequest(stock_code=600519)


def test_analysis_context_serializes_dates_for_prompt_input():
    context = AnalysisContext(
        stock=StockAnalysisContext(stock_code="600519", stock_name="贵州茅台"),
        market_snapshot=MarketSnapshotContext(
            trade_date=date(2026, 8, 31),
            close=1450.5,
            change_pct=0.012,
        ),
        data_as_of=datetime(2026, 8, 31, 15, 0, 0),
    )

    payload = context.model_dump(mode="json")

    assert payload["stock"]["stock_code"] == "600519"
    assert payload["market_snapshot"]["trade_date"] == "2026-08-31"
    assert payload["data_as_of"] == "2026-08-31T15:00:00"


def test_structured_output_rejects_unknown_or_blank_fields():
    payload = {
        "trend": "bullish",
        "summary": "趋势保持强势。",
        "technical_analysis": "均线结构偏多。",
        "quant_analysis": "量化评分较高。",
        "news_analysis": "新闻情绪中性。",
        "advantages": ["品牌优势"],
        "risks": ["估值波动"],
        "conclusion": "关注风险并结合自身情况判断。",
    }

    result = AIAnalysisStructuredOutput.model_validate(payload)
    assert result.trend == "bullish"

    with pytest.raises(ValidationError):
        AIAnalysisStructuredOutput.model_validate({**payload, "summary": " "})

    with pytest.raises(ValidationError):
        AIAnalysisStructuredOutput.model_validate({**payload, "unexpected": True})


def test_api_response_schema_keeps_quant_score_from_context():
    result = AIAnalysisData(
        stock_code="600519",
        quant_score=82,
        trend="neutral",
        summary="基本面和技术面信号混合。",
        technical_analysis="技术指标暂未形成一致方向。",
        quant_analysis="量化评分为 82 分。",
        news_analysis="未发现足以改变判断的重大新闻。",
        advantages=["品牌护城河"],
        risks=["估值波动"],
        conclusion="保持审慎，持续关注量价变化。",
        model_name="test-model",
    )

    assert result.quant_score == 82
