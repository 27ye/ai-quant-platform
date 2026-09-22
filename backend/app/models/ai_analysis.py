from datetime import datetime
from typing import Optional

from sqlalchemy import BIGINT, CHAR, DateTime, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AIAnalysis(Base):
    __tablename__ = "ai_analysis"
    __table_args__ = (
        Index("idx_ai_stock", "stock_code"),
        Index("idx_ai_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    quant_score: Mapped[Optional[int]] = mapped_column(Integer)
    trend: Mapped[Optional[str]] = mapped_column(String(50))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    technical_analysis: Mapped[Optional[str]] = mapped_column(Text)
    quant_analysis: Mapped[Optional[str]] = mapped_column(Text)
    news_analysis: Mapped[Optional[str]] = mapped_column(Text)
    advantages: Mapped[Optional[list]] = mapped_column(JSON)
    risks: Mapped[Optional[list]] = mapped_column(JSON)
    conclusion: Mapped[Optional[str]] = mapped_column(Text)
    model_name: Mapped[Optional[str]] = mapped_column(String(100))
    # -- V2 report snapshot (migration v5; fields owned by D, migration by B) --
    context_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    context_hash: Mapped[Optional[str]] = mapped_column(CHAR(64))
    source_mode: Mapped[Optional[str]] = mapped_column(String(16))
    data_as_of: Mapped[Optional[datetime]] = mapped_column(DateTime)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32))
    context_schema_version: Mapped[Optional[str]] = mapped_column(String(32))
    output_schema_version: Mapped[Optional[str]] = mapped_column(String(32))
    # -- V3 saved-backtest interpretation (migration v9) --
    #: NULL on reports written before V3; readers interpret that legacy shape as
    #: ``standard`` only when ``backtest_id`` is also NULL.
    analysis_mode: Mapped[Optional[str]] = mapped_column(String(16))
    backtest_id: Mapped[Optional[int]] = mapped_column(BIGINT)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
