from datetime import date, datetime

import pytest
from pydantic import ValidationError

from backend.app.schemas.ai import (
    AIAnalysisData,
    AIAnalysisStructuredOutput,
    AIAnalyzeRequest,
    AIReportDetail,
    AIReportMetadata,
    DataProvenance,
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


def test_report_metadata_is_strict_and_hash_is_64_hex_characters():
    payload = {
        "data_as_of": datetime(2026, 8, 31, 15, 0, 0),
        "source_mode": "live",
        "prompt_version": "v2.0",
        "context_schema_version": "v2.0",
        "output_schema_version": "v2.0",
        "context_hash": "a" * 64,
    }
    assert AIReportMetadata(**payload).context_hash == "a" * 64

    with pytest.raises(ValidationError):
        AIReportMetadata(**payload, unexpected=True)
    with pytest.raises(ValidationError):
        AIReportMetadata(**{**payload, "context_hash": "xyz"})


def test_legacy_report_allows_missing_snapshot_and_versions():
    report = AIReportDetail(
        report_id=1,
        stock_code="600519",
        quant_score=50,
        trend="neutral",
        summary="旧报告",
        technical_analysis="旧技术分析",
        quant_analysis="旧量化分析",
        news_analysis="旧新闻分析",
        advantages=["旧优势"],
        risks=["旧风险"],
        conclusion="旧结论",
        model_name="legacy-model",
        created_at=datetime(2025, 1, 1),
        source_mode="unknown",
        snapshot_status="legacy_missing",
    )
    assert report.context_snapshot is None
    assert report.context_hash is None
    assert report.prompt_version is None

    with pytest.raises(ValidationError):
        report.model_copy(update={"report_id": 0}).model_validate(
            {**report.model_dump(), "report_id": 0}
        )
