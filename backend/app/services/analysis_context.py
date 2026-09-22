from datetime import datetime, timezone
from typing import List, Optional, Protocol, Sequence

from backend.app.core.errors import DataProviderError, InvalidParameterError
from backend.app.data.providers.base import InvalidStockCodeError, StockDataProviderError
from backend.app.schemas.ai import (
    AnalysisContext,
    BacktestMetricsContext,
    DataProvenance,
    MarketDataProvenance,
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

    def get_market_provenance(self, stock_code: str) -> MarketDataProvenance:
        """Return source and date metadata for the request-cached market frame."""


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
        stock = self._stock_service.get_stock(stock_code)
        snapshot = self._stock_service.get_market_snapshot(stock_code)
        indicators = self._stock_service.get_technical_indicators(stock_code)
        score = self._quant_service.get_score(stock_code)
        backtest = self._backtest_service.get_latest_metrics(stock_code)
        try:
            news: List[NewsItemContext] = list(
                self._news_service.get_news(stock_code, self.NEWS_LIMIT)
            )
        except InvalidStockCodeError as exc:
            raise InvalidParameterError() from exc
        except StockDataProviderError as exc:
            raise DataProviderError() from exc
        # MySQL DATETIME stores second precision in the V2 schema. Freeze the
        # timestamp at that precision before it enters either the prompt or the
        # snapshot so POST and later history reads remain byte-consistent.
        assembled_at = datetime.now(timezone.utc).replace(microsecond=0)
        market_provenance = self._stock_service.get_market_provenance(stock_code)
        provenance = DataProvenance(
            **market_provenance.model_dump(),
            news_status="available" if news else "empty",
            news_count=len(news),
            retrieved_at=assembled_at,
        )
        return AnalysisContext(
            stock=stock,
            market_snapshot=snapshot,
            technical_indicators=indicators,
            quant_score=score,
            backtest_metrics=backtest,
            news=news,
            data_as_of=assembled_at,
            provenance=provenance,
        )
