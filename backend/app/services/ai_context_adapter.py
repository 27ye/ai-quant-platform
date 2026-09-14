from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import pandas as pd

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
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.quant.validators import InsufficientDataError
from backend.app.schemas.ai import (
    BacktestMetricsContext,
    MarketSnapshotContext,
    QuantScoreContext,
    StockAnalysisContext,
    TechnicalIndicatorContext,
)
from backend.app.services.stock_service import StockService
from backend.app.services.market_data_service import MarketDataSource


QuantPipeline = Callable[[pd.DataFrame], Dict[str, Any]]


class StockQuantAnalysisAdapter:
    """Expose stock and quant outputs through the AI context service contracts.

    A FastAPI request receives one adapter instance. Its per-symbol cache ensures
    the context builder fetches daily K-line once and runs the deterministic
    quant pipeline once, even though it asks for several public projections.
    """

    def __init__(
        self,
        *,
        market_data_source: MarketDataSource,
        stock_service: Optional[StockService] = None,
        quant_pipeline: QuantPipeline = analyze_quant_dataframe,
    ) -> None:
        self._stock_service = stock_service or StockService()
        self._market_data_source = market_data_source
        self._quant_pipeline = quant_pipeline
        self._frames: Dict[str, pd.DataFrame] = {}
        self._quant_results: Dict[str, Dict[str, Any]] = {}

    def get_stock(self, stock_code: str) -> StockAnalysisContext:
        try:
            stock = self._stock_service.get_stock_info(stock_code)
        except InvalidStockCodeError as exc:
            raise InvalidParameterError(str(exc)) from exc
        except EmptyStockDataError as exc:
            raise StockNotFoundError(str(exc)) from exc
        except StockDataProviderError as exc:
            raise DataProviderError(str(exc)) from exc

        return StockAnalysisContext(
            stock_code=stock.stock_code,
            stock_name=stock.stock_name,
            industry=stock.industry,
        )

    def get_market_snapshot(self, stock_code: str) -> MarketSnapshotContext:
        frame, _ = self._load_quant_result(stock_code)
        latest = frame.iloc[-1]
        return MarketSnapshotContext(
            trade_date=latest["trade_date"],
            close=_optional_number(latest.get("close")),
            change_pct=_optional_number(latest.get("change_pct")),
            turnover_rate=_optional_number(latest.get("turnover_rate")),
        )

    def get_technical_indicators(
        self,
        stock_code: str,
    ) -> TechnicalIndicatorContext:
        _, result = self._load_quant_result(stock_code)
        latest = result["latest"]
        return TechnicalIndicatorContext(
            trade_date=latest["trade_date"],
            ma5=latest.get("ma5"),
            ma10=latest.get("ma10"),
            ma20=latest.get("ma20"),
            ma60=latest.get("ma60"),
            macd=latest.get("macd"),
            macd_signal=latest.get("macd_signal"),
            macd_hist=latest.get("macd_hist"),
            rsi14=latest.get("rsi14"),
            boll_upper=latest.get("boll_upper"),
            boll_middle=latest.get("boll_middle"),
            boll_lower=latest.get("boll_lower"),
        )

    def get_score(self, stock_code: str) -> QuantScoreContext:
        _, result = self._load_quant_result(stock_code)
        score = result["score"]
        return QuantScoreContext(
            score=score["score"],
            level=score["level"],
            reasons=score.get("reasons", []),
        )

    def get_latest_metrics(self, stock_code: str) -> BacktestMetricsContext:
        _, result = self._load_quant_result(stock_code)
        backtest = result["backtest"]
        return BacktestMetricsContext(
            strategy_name=backtest["strategy_name"],
            start_date=backtest["start_date"],
            end_date=backtest["end_date"],
            total_return=backtest.get("total_return"),
            annual_return=backtest.get("annual_return"),
            max_drawdown=backtest.get("max_drawdown"),
            sharpe_ratio=backtest.get("sharpe_ratio"),
            win_rate=backtest.get("win_rate"),
            trade_count=backtest.get("trade_count"),
            benchmark_return=backtest.get("benchmark_return"),
        )

    def _load_quant_result(
        self,
        stock_code: str,
    ) -> tuple[pd.DataFrame, Dict[str, Any]]:
        if stock_code in self._quant_results:
            return self._frames[stock_code], self._quant_results[stock_code]

        try:
            rows = self._market_data_source.query_daily(
                stock_code, min_rows=60, max_stale_days=3, max_gap_days=15
            )
        except InvalidStockCodeError as exc:
            raise InvalidParameterError(str(exc)) from exc
        except StockDataProviderError as exc:
            raise DataProviderError(str(exc)) from exc

        if not rows:
            raise InsufficientStockDataError()
        # B owns normalization/precision/completeness. Only reshape and order
        # that same data here; never fetch or round a second copy for Quant.
        frame = pd.DataFrame([row.model_dump() for row in rows])
        frame = frame.sort_values("trade_date").reset_index(drop=True)
        try:
            result = self._quant_pipeline(frame)
        except InsufficientStockDataError:
            raise
        except InsufficientDataError as exc:
            raise InsufficientStockDataError(str(exc)) from exc
        except (
            TypeError,
            ValueError,
            ZeroDivisionError,
            OverflowError,
            RuntimeError,
        ) as exc:
            raise QuantCalculationError(str(exc)) from exc

        self._frames[stock_code] = frame
        self._quant_results[stock_code] = result
        return frame, result


def _optional_number(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)
