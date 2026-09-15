from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class StockDailySync(Base):
    """Per-stock provenance for the daily bars stored in ``stock_daily`` (V2 B2).

    ``stock_daily`` alone cannot say whether its rows came from a live refresh, a
    frozen package, or an older import - so the data-status endpoint would have to
    guess. This table records what the last successful refresh actually was; when
    it has no row (e.g. data loaded before V2) the status endpoint reports
    ``mode="unknown"`` instead of inventing provenance.
    """

    __tablename__ = "stock_daily_sync"

    stock_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    #: ``live`` (fetched from a provider) / ``frozen`` (loaded from a package).
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(200))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_trade_date: Mapped[Optional[date]] = mapped_column(Date)
    last_trade_date: Mapped[Optional[date]] = mapped_column(Date)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(500))
