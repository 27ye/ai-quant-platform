from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class StockBasicSchema(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    stock_name: str
    industry: Optional[str] = None
    total_market_cap: Optional[float] = None
    float_market_cap: Optional[float] = None


class StockNewsSchema(BaseModel):
    """Unified stock-news item returned by the news API."""

    stock_code: str = Field(pattern=r"^\d{6}$")
    title: str
    summary: Optional[str] = None
    source: Optional[str] = None
    publish_time: Optional[datetime] = None
    url: Optional[str] = None


class DailyKlineSchema(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    change_pct: Optional[float] = None


class CatalogStatusSchema(BaseModel):
    """Local stock-catalog state (V2 B1 bookkeeping)."""

    synced: bool
    row_count: int = 0
    last_success_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    source: Optional[str] = None
    last_error: Optional[str] = None


class KlineFreshnessSchema(BaseModel):
    #: ``fresh`` / ``stale`` / ``unknown`` (no usable bars at all).
    status: str
    stale_days: Optional[int] = None
    max_stale_days: int


class KlineStatusSchema(BaseModel):
    #: How the stored bars were produced: ``live`` / ``frozen`` / ``unknown``.
    #: ``unknown`` means no refresh metadata exists - it is never guessed.
    mode: str
    source: Optional[str] = None
    rows: int = 0
    first_trade_date: Optional[date] = None
    last_trade_date: Optional[date] = None
    last_refreshed_at: Optional[datetime] = None
    #: ``known`` only when the trading calendar could prove the expected count.
    coverage: str
    expected_trading_days: Optional[int] = None
    #: Last failed refresh attempt (empty when the last attempt succeeded).
    last_attempt_at: Optional[datetime] = None
    last_error: Optional[str] = None
    freshness: KlineFreshnessSchema


class StockDataStatusSchema(BaseModel):
    """``GET /stocks/{stock_code}/data-status`` payload (V2 B2)."""

    stock_code: str = Field(pattern=r"^\d{6}$")
    catalog: CatalogStatusSchema
    kline: KlineStatusSchema
    as_of: datetime
