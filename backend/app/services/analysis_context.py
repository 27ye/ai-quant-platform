from datetime import datetime, timezone
from typing import List, Optional, Protocol, Sequence

from backend.app.schemas.ai import (
    AnalysisContext,
    BacktestMetricsContext,
    MarketSnapshotContext,
    NewsItemContext,
    QuantScoreContext,
    StockAnalysisContext,
    TechnicalIndicatorContext,
)


class StockAnalysisService(Protocol):
    def get_stock(self, stock_code: str) -> StockAnalysisContext:
        """Return validated stock identity data."""

    def get_market_snapshot(self, stock_code: str) -> MarketSnapshotContext:
        """Return the latest normalized qfq market snapshot."""

    def get_technical_indicators(
        self,
        stock_code: str,
    ) -> Optional[TechnicalIndicatorContext]:
        """Return deterministic technical indicator output when available."""


class QuantAnalysisService(Protocol):
    def get_score(self, stock_code: str) -> Optional[QuantScoreContext]:
        """Return the deterministic Quant Service output when available."""


class BacktestAnalysisService(Protocol):
    def get_latest_metrics(
        self,
        stock_code: str,
    ) -> Optional[BacktestMetricsContext]:
        """Return validated backtest metrics without recalculating them."""


class NewsAnalysisService(Protocol):
    def get_news(self, stock_code: str, limit: int) -> Sequence[NewsItemContext]:
        """Return a bounded list of normalized news records."""


class AnalysisContextProvider(Protocol):
    def get_context(self, stock_code: str) -> AnalysisContext:
        """Build the structured input consumed by the AI module."""


class ServiceAnalysisContextProvider:
    NEWS_LIMIT = 10

    def __init__(
        self,
        *,
        stock_service: StockAnalysisService,
        quant_service: QuantAnalysisService,
        backtest_service: BacktestAnalysisService,
        news_service: NewsAnalysisService,
    ) -> None:
        self._stock_service = stock_service
        self._quant_service = quant_service
        self._backtest_service = backtest_service
        self._news_service = news_service

    def get_context(self, stock_code: str) -> AnalysisContext:
        news: List[NewsItemContext] = list(
            self._news_service.get_news(stock_code, self.NEWS_LIMIT)
        )
        return AnalysisContext(
            stock=self._stock_service.get_stock(stock_code),
            market_snapshot=self._stock_service.get_market_snapshot(stock_code),
            technical_indicators=self._stock_service.get_technical_indicators(
                stock_code
            ),
            quant_score=self._quant_service.get_score(stock_code),
            backtest_metrics=self._backtest_service.get_latest_metrics(stock_code),
            news=news,
            data_as_of=datetime.now(timezone.utc),
        )
