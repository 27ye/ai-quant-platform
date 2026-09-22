from datetime import date

import pandas as pd
import pytest

from backend.app.core.errors import (
    DataProviderError,
    InsufficientStockDataError,
    InvalidParameterError,
    QuantCalculationError,
    StockNotFoundError,
)
from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProviderError,
)
from backend.app.quant.validators import InsufficientDataError
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema
from backend.app.services.ai_context_adapter import StockQuantAnalysisAdapter
from backend.app.services.news_service import NewsService


def _quant_result():
    return {
        "latest": {
            "trade_date": "2026-08-31",
            "close": 1450.5,
            "ma5": 1440.0,
            "ma10": 1430.0,
            "ma20": 1420.0,
            "ma60": None,
            "macd": 4.5,
            "macd_signal": 4.0,
            "macd_hist": 0.5,
            "rsi14": 61.0,
            "boll_upper": 1500.0,
            "boll_middle": 1420.0,
            "boll_lower": None,
        },
        "score": {
            "score": 82,
            "level": "strong",
            "reasons": ["trend is strong"],
        },
        "backtest": {
            "strategy_name": "ma5_ma20_long_only",
            "start_date": "2025-01-01",
            "end_date": "2026-08-31",
            "total_return": 0.21,
            "annual_return": 0.12,
            "max_drawdown": -0.08,
            "sharpe_ratio": None,
            "win_rate": None,
            "trade_count": 0,
            "benchmark_return": 0.15,
        },
    }


class FakeStockService:
    def __init__(self):
        self.kline_calls = 0

    def get_stock_info(self, stock_code):
        return StockBasicSchema(
            stock_code=stock_code,
            stock_name="贵州茅台",
            industry="白酒",
        )

    def query_daily(self, stock_code, **kwargs):
        assert kwargs == {"min_rows": 60, "max_stale_days": 3, "max_gap_days": 15}
        self.kline_calls += 1
        frame = pd.DataFrame(
            {
                "stock_code": [stock_code, stock_code],
                "trade_date": [date(2026, 8, 28), date(2026, 8, 31)],
                "close": [1440.0, 1450.5],
                "change_pct": [0.001, 0.012],
                "turnover_rate": [0.002, None],
            }
        )
        return [DailyKlineSchema(**row) for row in frame.iloc[::-1].to_dict("records")]

    def get_query_provenance(self, stock_code):
        return {"source_mode": "cache", "provider": "test-provider"}


def test_adapter_maps_all_context_fields_and_reuses_one_quant_run():
    stock_service = FakeStockService()
    pipeline_calls = []

    def pipeline(frame):
        pipeline_calls.append(frame)
        return _quant_result()

    adapter = StockQuantAnalysisAdapter(
        market_data_source=stock_service, stock_service=stock_service, quant_pipeline=pipeline,
    )

    stock = adapter.get_stock("600519")
    snapshot = adapter.get_market_snapshot("600519")
    indicators = adapter.get_technical_indicators("600519")
    score = adapter.get_score("600519")
    backtest = adapter.get_latest_metrics("600519")

    assert stock.stock_name == "贵州茅台"
    assert stock.industry == "白酒"
    assert snapshot.trade_date == date(2026, 8, 31)
    assert snapshot.close == 1450.5
    assert snapshot.change_pct == 0.012
    assert snapshot.turnover_rate is None
    assert indicators.trade_date == date(2026, 8, 31)
    assert indicators.ma5 == 1440.0
    assert indicators.ma60 is None
    assert indicators.boll_lower is None
    assert score.score == 82
    assert score.reasons == ["trend is strong"]
    assert backtest.total_return == 0.21
    assert backtest.sharpe_ratio is None
    assert backtest.win_rate is None
    provenance = adapter.get_market_provenance("600519")
    assert provenance.source_mode == "cache"
    assert provenance.provider == "test-provider"
    assert provenance.market_rows == 2
    assert provenance.market_start_date == date(2026, 8, 28)
    assert provenance.market_end_date == date(2026, 8, 31)
    assert stock_service.kline_calls == 1
    assert len(pipeline_calls) == 1


def test_empty_news_service_returns_no_synthetic_items():
    class EmptyProvider:
        def get_stock_news(self, stock_code, limit):
            return []

    service = NewsService(provider=EmptyProvider())

    assert service.get_news("600519", limit=10) == []


def test_adapter_maps_missing_stock_to_40002_error():
    class MissingStockService(FakeStockService):
        def get_stock_info(self, stock_code):
            raise EmptyStockDataError("missing")

    adapter = StockQuantAnalysisAdapter(
        stock_service=MissingStockService(), market_data_source=FakeStockService(),
    )

    with pytest.raises(StockNotFoundError) as captured:
        adapter.get_stock("600519")

    assert captured.value.code == 40002


def test_adapter_maps_provider_failure_to_50001_error():
    class FailingStockService(FakeStockService):
        def query_daily(self, stock_code, **kwargs):
            raise StockDataProviderError("provider unavailable")

    adapter = StockQuantAnalysisAdapter(market_data_source=FailingStockService())

    with pytest.raises(DataProviderError) as captured:
        adapter.get_market_snapshot("600519")

    assert captured.value.code == 50001


def test_adapter_maps_provider_parameter_failure_to_40001_error():
    class InvalidCodeStockService(FakeStockService):
        def query_daily(self, stock_code, **kwargs):
            raise InvalidStockCodeError("invalid code")

    adapter = StockQuantAnalysisAdapter(market_data_source=InvalidCodeStockService())

    with pytest.raises(InvalidParameterError) as captured:
        adapter.get_market_snapshot("invalid")

    assert captured.value.code == 40001


@pytest.mark.parametrize(
    ("pipeline_error", "expected_error", "expected_code"),
    [
        (InsufficientDataError("too few rows"), InsufficientStockDataError, 40003),
        (TypeError("invalid dataframe"), QuantCalculationError, 50003),
        (RuntimeError("calculation failed"), QuantCalculationError, 50003),
    ],
)
def test_adapter_maps_quant_pipeline_errors(
    pipeline_error,
    expected_error,
    expected_code,
):
    def failing_pipeline(frame):
        raise pipeline_error

    adapter = StockQuantAnalysisAdapter(
        market_data_source=FakeStockService(), quant_pipeline=failing_pipeline,
    )

    with pytest.raises(expected_error) as captured:
        adapter.get_score("600519")

    assert captured.value.code == expected_code


def test_real_quant_pipeline_and_request_local_cache():
    """Synthetic dates are test input, not an authoritative exchange calendar."""
    from backend.app.quant.pipeline import analyze_quant_dataframe

    rows = [DailyKlineSchema(
        stock_code="600519", trade_date=day.date(),
        open=100 + i, high=102 + i, low=99 + i, close=101 + i,
        volume=1000, change_pct=None, turnover_rate=0.001234,
    ) for i, day in enumerate(pd.bdate_range("2025-01-01", periods=80))]
    calls = []

    class Source:
        def query_daily(self, stock_code, **kwargs):
            calls.append("market")
            return list(reversed(rows))

        def get_query_provenance(self, stock_code):
            return {"source_mode": "cache", "provider": "test-provider"}

    def pipeline(frame):
        calls.append("quant")
        return analyze_quant_dataframe(frame)

    for _ in range(2):
        adapter = StockQuantAnalysisAdapter(market_data_source=Source(), quant_pipeline=pipeline)
        assert adapter.get_market_snapshot("600519").trade_date == rows[-1].trade_date
        assert adapter.get_market_snapshot("600519").change_pct is None
        assert adapter.get_market_snapshot("600519").turnover_rate == 0.001234
        assert adapter.get_technical_indicators("600519").ma60 is not None
        assert adapter.get_score("600519").score >= 0
        assert adapter.get_latest_metrics("600519").end_date == rows[-1].trade_date
    assert calls == ["market", "quant", "market", "quant"]


def test_empty_market_data_returns_40003():
    class EmptySource:
        def query_daily(self, stock_code, **kwargs):
            return []

    with pytest.raises(InsufficientStockDataError):
        StockQuantAnalysisAdapter(market_data_source=EmptySource()).get_score("600519")
