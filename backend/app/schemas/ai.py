from datetime import date, datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

PROMPT_VERSION = "v2.0"
CONTEXT_SCHEMA_VERSION = "v2.0"
OUTPUT_SCHEMA_VERSION = "v2.0"
BACKTEST_CONTEXT_VERSION = "v3.backtest.1"
BACKTEST_NEWS_DISCLOSURE = "本报告未纳入新闻数据"
AnalysisMode = Literal["standard", "custom_backtest"]


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=(), allow_inf_nan=False)


class AIAnalyzeRequest(StrictSchema):
    stock_code: str = Field(pattern=r"^\d{6}$")
    backtest_id: Optional[StrictInt] = Field(
        default=None, gt=0, le=9_223_372_036_854_775_807
    )

    @field_validator("backtest_id", mode="before")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("backtest_id must be omitted or a positive integer")
        return value


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


class BacktestParametersContext(StrictSchema):
    ma_short_period: StrictInt = Field(ge=2, le=120)
    ma_long_period: StrictInt = Field(ge=2, le=120)
    initial_cash: float = Field(gt=0)
    transaction_cost: float = Field(ge=0, lt=1)
    slippage: float = Field(ge=0, lt=1)

    @model_validator(mode="after")
    def ordered_periods(self):
        if self.ma_short_period >= self.ma_long_period:
            raise ValueError("short MA must be less than long MA")
        return self


class BacktestWarmupContext(StrictSchema):
    start_date: date
    end_date: date
    required_rows: StrictInt = Field(gt=0)
    used_rows: StrictInt = Field(gt=0)


class BacktestInitialEquityContext(StrictSchema):
    trade_date: date
    equity: float = Field(gt=0)
    valuation: Literal["before_open"]


class SavedBacktestMetricsContext(StrictSchema):
    initial_cash: float = Field(gt=0)
    final_equity: float = Field(ge=0)
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    win_rate: Optional[float] = Field(ge=0, le=1)
    trade_count: StrictInt = Field(ge=0)
    order_count: StrictInt = Field(ge=0)
    benchmark_return: float


class BacktestInterpretationContext(StrictSchema):
    stock_code: str = Field(pattern=r"^\d{6}$")
    backtest_id: StrictInt = Field(gt=0)
    backtest_created_at: datetime
    data_as_of: datetime
    strategy_name: Literal["ma_long_only"]
    semantics_version: Literal["v2_windowed"]
    algorithm_version: Literal["ma_long_only_v2.0.0"]
    effective_parameters: BacktestParametersContext
    requested_start_date: date
    requested_end_date: date
    start_date: date
    end_date: date
    warmup: BacktestWarmupContext
    execution_assumptions: dict[str, Union[StrictStr, StrictBool]]
    metrics: SavedBacktestMetricsContext
    initial_equity: BacktestInitialEquityContext
    data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: MarketDataProvenance

    @model_validator(mode="after")
    def consistent_saved_context(self):
        if not (self.requested_start_date <= self.start_date <= self.end_date <= self.requested_end_date):
            raise ValueError("inconsistent saved backtest window")
        if not (self.warmup.start_date <= self.warmup.end_date < self.requested_start_date):
            raise ValueError("inconsistent saved warmup window")
        if self.warmup.required_rows != self.effective_parameters.ma_long_period or self.warmup.used_rows != self.warmup.required_rows:
            raise ValueError("inconsistent warmup row count")
        if self.data_as_of != self.backtest_created_at:
            raise ValueError("data_as_of must identify the saved backtest")
        if self.initial_equity.trade_date != self.start_date or self.initial_equity.equity != self.metrics.initial_cash or self.metrics.initial_cash != self.effective_parameters.initial_cash:
            raise ValueError("inconsistent initial equity")
        return self


ReportContext = Union[AnalysisContext, BacktestInterpretationContext]


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
    analysis_mode: AnalysisMode = "standard"
    backtest_id: Optional[StrictInt] = Field(default=None, gt=0)
    data_as_of: datetime
    source_mode: SourceMode
    prompt_version: str = Field(min_length=1, max_length=32)
    context_schema_version: str = Field(min_length=1, max_length=32)
    output_schema_version: str = Field(min_length=1, max_length=32)
    context_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class AIReportSummary(StrictSchema):
    analysis_mode: AnalysisMode = "standard"
    backtest_id: Optional[StrictInt] = Field(default=None, gt=0)
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
    analysis_mode: AnalysisMode = "standard"
    backtest_id: Optional[StrictInt] = Field(default=None, gt=0)
    report_id: int = Field(gt=0)
    created_at: datetime
    data_as_of: Optional[datetime] = None
    source_mode: SourceMode
    prompt_version: Optional[str] = None
    context_schema_version: Optional[str] = None
    output_schema_version: Optional[str] = None
    context_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    snapshot_status: SnapshotStatus
    context_snapshot: Optional[ReportContext] = None


class PaginatedAIReports(StrictSchema):
    items: List[AIReportSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
