from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import BIGINT, DECIMAL, Date, DateTime, Index, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class BacktestResult(Base):
    __tablename__ = "backtest_result"
    __table_args__ = (
        Index("idx_backtest_stock", "stock_code"),
        Index("idx_backtest_strategy", "strategy_name"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_cash: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(20, 2))
    total_return: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    annual_return: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    max_drawdown: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    sharpe_ratio: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    win_rate: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    trade_count: Mapped[Optional[int]] = mapped_column(Integer)
    benchmark_return: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(16, 8))
    parameters: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime, server_default=func.now())

    # -- V2 result snapshot (migration v4) ---------------------------------
    #: ``v1_legacy`` or ``v2_windowed`` (see the V2 request-semantics matrix).
    semantics_version: Mapped[Optional[str]] = mapped_column(String(20))
    strategy_version: Mapped[Optional[str]] = mapped_column(String(20))
    final_equity: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(20, 2))
    order_count: Mapped[Optional[int]] = mapped_column(Integer)
    warmup_start_date: Mapped[Optional[date]] = mapped_column(Date)
    #: Saved curves/orders: history is read from these, never recomputed.
    equity_curve: Mapped[Optional[list]] = mapped_column(JSON)
    benchmark_curve: Mapped[Optional[list]] = mapped_column(JSON)
    drawdown_curve: Mapped[Optional[list]] = mapped_column(JSON)
    orders: Mapped[Optional[list]] = mapped_column(JSON)
    effective_parameters: Mapped[Optional[dict]] = mapped_column(JSON)
    data_meta: Mapped[Optional[dict]] = mapped_column(JSON)
    #: Exact rows handed to C's core (warmup included) - migration v6.
    input_snapshot: Mapped[Optional[list]] = mapped_column(JSON)
