from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class AnalysisContext(StrictSchema):
    stock: StockAnalysisContext
    market_snapshot: MarketSnapshotContext
    technical_indicators: Optional[TechnicalIndicatorContext] = None
    quant_score: Optional[QuantScoreContext] = None
    backtest_metrics: Optional[BacktestMetricsContext] = None
    news: List[NewsItemContext] = Field(default_factory=list)
    data_as_of: datetime


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
