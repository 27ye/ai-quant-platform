from datetime import date

from backend.app.schemas.ai import (
    BacktestMetricsContext,
    MarketSnapshotContext,
    NewsItemContext,
    QuantScoreContext,
    StockAnalysisContext,
    TechnicalIndicatorContext,
)
from backend.app.services.analysis_context import ServiceAnalysisContextProvider


class FakeStockService:
    def get_stock(self, stock_code):
        return StockAnalysisContext(
            stock_code=stock_code,
            stock_name="贵州茅台",
            industry="白酒",
        )

    def get_market_snapshot(self, stock_code):
        return MarketSnapshotContext(
            trade_date=date(2026, 8, 31),
            close=1450.5,
            change_pct=0.012,
        )

    def get_technical_indicators(self, stock_code):
        return TechnicalIndicatorContext(
            trade_date=date(2026, 8, 31),
            ma5=1440.0,
        )


class FakeQuantService:
    def get_score(self, stock_code):
        return QuantScoreContext(
            score=82,
            level="strong",
            reasons=["趋势得分较高"],
        )


class FakeBacktestService:
    def get_latest_metrics(self, stock_code):
        return BacktestMetricsContext(
            strategy_name="ma_cross",
            start_date=date(2025, 1, 1),
            end_date=date(2026, 8, 31),
            total_return=0.21,
        )


class FakeNewsService:
    def __init__(self):
        self.requested_limit = None

    def get_news(self, stock_code, limit):
        self.requested_limit = limit
        return [NewsItemContext(title="公司发布公告", source="交易所")]


def test_service_context_provider_calls_all_public_service_interfaces():
    news_service = FakeNewsService()
    provider = ServiceAnalysisContextProvider(
        stock_service=FakeStockService(),
        quant_service=FakeQuantService(),
        backtest_service=FakeBacktestService(),
        news_service=news_service,
    )

    context = provider.get_context("600519")

    assert context.stock.stock_name == "贵州茅台"
    assert context.market_snapshot.change_pct == 0.012
    assert context.technical_indicators is not None
    assert context.quant_score is not None
    assert context.quant_score.score == 82
    assert context.backtest_metrics is not None
    assert context.backtest_metrics.total_return == 0.21
    assert context.news[0].source == "交易所"
    assert news_service.requested_limit == 10
