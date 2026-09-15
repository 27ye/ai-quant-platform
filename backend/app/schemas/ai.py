from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PROMPT_VERSION = "v2.0"
CONTEXT_SCHEMA_VERSION = "v2.0"
OUTPUT_SCHEMA_VERSION = "v2.0"


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=(), allow_inf_nan=False)


class AIAnalyzeRequest(StrictSchema):
    stock_code: str = Field(pattern=r"^\d{6}$")


class StockAnalysisContext(StrictSchema):
    stock_code: str = Field(pattern=r"^\d{6}$")
    stock_name: str = Field(min_length=1)
    industry: Optional[str] = None


class MarketSnapshotContext(StrictSchema):
    trade_date: date
    close: Optional[float] = None
    change_pct: Optional[float] = None
    turnover_rate: Optional[float] = None


class TechnicalIndicatorContext(StrictSchema):
    trade_date: date
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    rsi14: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_middle: Optional[float] = None
    boll_lower: Optional[float] = None


class QuantScoreContext(StrictSchema):
    score: int = Field(ge=0, le=100)
    level: str = Field(min_length=1)
    reasons: List[str] = Field(default_factory=list)


class BacktestMetricsContext(StrictSchema):
    strategy_name: str = Field(min_length=1)
    start_date: date
    end_date: date
    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    win_rate: Optional[float] = None
    trade_count: Optional[int] = Field(default=None, ge=0)
    benchmark_return: Optional[float] = None


class NewsItemContext(StrictSchema):
    title: str = Field(min_length=1)
    summary: Optional[str] = None
    source: Optional[str] = None
    publish_time: Optional[datetime] = None
    url: Optional[str] = None


SourceMode = Literal["live", "cache", "frozen", "unknown"]
SnapshotStatus = Literal["complete", "legacy_missing"]


class MarketDataProvenance(StrictSchema):
    source_mode: SourceMode
    provider: str = Field(min_length=1)
    market_start_date: date
    market_end_date: date
    market_rows: int = Field(ge=1)


class DataProvenance(MarketDataProvenance):
    news_status: Literal["available", "empty"]
    news_count: int = Field(ge=0)
    retrieved_at: datetime


class AnalysisContext(StrictSchema):
    stock: StockAnalysisContext
    market_snapshot: MarketSnapshotContext
    technical_indicators: Optional[TechnicalIndicatorContext] = None
    quant_score: Optional[QuantScoreContext] = None
    backtest_metrics: Optional[BacktestMetricsContext] = None
    news: List[NewsItemContext] = Field(default_factory=list)
    data_as_of: datetime
    provenance: DataProvenance


class AIAnalysisStructuredOutput(StrictSchema):
    trend: Literal["bullish", "neutral", "bearish"]
    summary: str = Field(min_length=1)
    technical_analysis: str = Field(min_length=1)
    quant_analysis: str = Field(min_length=1)
    news_analysis: str = Field(min_length=1)
    advantages: List[str]
    risks: List[str]
    conclusion: str = Field(min_length=1)

    @field_validator(
        "summary",
        "technical_analysis",
        "quant_analysis",
        "news_analysis",
        "conclusion",
    )
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("analysis text must not be blank")
        return normalized

    @field_validator("advantages", "risks")
    @classmethod
    def normalize_text_items(cls, value: List[str]) -> List[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized:
            raise ValueError("analysis list must contain at least one non-blank item")
        return normalized


class AIAnalysisData(AIAnalysisStructuredOutput):
    stock_code: str = Field(pattern=r"^\d{6}$")
    quant_score: Optional[int] = Field(default=None, ge=0, le=100)
    model_name: str = Field(min_length=1)


class AIReportMetadata(StrictSchema):
    data_as_of: datetime
    source_mode: SourceMode
    prompt_version: str = Field(min_length=1, max_length=32)
    context_schema_version: str = Field(min_length=1, max_length=32)
    output_schema_version: str = Field(min_length=1, max_length=32)
    context_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class AIReportSummary(StrictSchema):
    report_id: int = Field(gt=0)
    stock_code: str = Field(pattern=r"^\d{6}$")
    quant_score: Optional[int] = Field(default=None, ge=0, le=100)
    trend: Literal["bullish", "neutral", "bearish"]
    summary: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    data_as_of: Optional[datetime] = None
    created_at: datetime
    source_mode: SourceMode
    snapshot_status: SnapshotStatus


class AIReportDetail(AIAnalysisData):
    report_id: int = Field(gt=0)
    created_at: datetime
    data_as_of: Optional[datetime] = None
    source_mode: SourceMode
    prompt_version: Optional[str] = None
    context_schema_version: Optional[str] = None
    output_schema_version: Optional[str] = None
    context_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    snapshot_status: SnapshotStatus
    context_snapshot: Optional[AnalysisContext] = None


class PaginatedAIReports(StrictSchema):
    items: List[AIReportSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
