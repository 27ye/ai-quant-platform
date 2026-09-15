from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.app.core.errors import InsufficientStockDataError, QuantCalculationError
from backend.app.quant.backtest import run_backtest
from backend.app.quant.config import ConfigInput
from backend.app.quant.indicators import INDICATOR_COLUMNS, calculate_indicators
from backend.app.quant.scoring import calculate_quant_score
from backend.app.quant.serialization import dataframe_records, to_json_safe
from backend.app.quant.validators import InsufficientDataError as QuantInsufficientDataError
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.market_data_service import (
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
    MarketDataSource,
)
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS, StockService


class QuantService:
    """FastAPI-layer wrapper around C's deterministic quant core.

    This service fetches normalized qfq daily data through the unified market
    data source when one is injected, then delegates indicators / scoring /
    backtest computation to C's quant module. It never re-implements the
    calculation.
    """

    def __init__(
        self,
        stock_service: Optional[StockService] = None,
        config: ConfigInput = None,
        *,
        market_data_source: Optional[MarketDataSource] = None,
    ) -> None:
        self._stock = stock_service or StockService()
        self._market = market_data_source
        self._config = config

    def get_indicators(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        frame = self._daily_frame(stock_code, start_date, end_date)
        indicators = self._run(calculate_indicators, frame, self._config)
        return dataframe_records(indicators.loc[:, INDICATOR_COLUMNS])

    def get_score(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        frame = self._daily_frame(stock_code, start_date, end_date)
        return to_json_safe(self._run(calculate_quant_score, frame, self._config))

    def run_backtest(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        *,
        config: ConfigInput = None,
        frame: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Run C's backtest, optionally on a caller-supplied frame/config.

        ``frame`` lets the V2 windowed path pass the exact warmup+window rows it
        already fetched (and hashed), instead of fetching twice; ``config`` lets
        a parameterised request use its effective parameters without mutating the
        request-scoped service.
        """
        data = frame if frame is not None else self._daily_frame(stock_code, start_date, end_date)
        result = to_json_safe(
            self._run(run_backtest, data, config if config is not None else self._config)
        )
        result["stock_code"] = stock_code
        return result

    @staticmethod
    def rows_to_frame(rows: List[DailyKlineSchema]) -> pd.DataFrame:
        """Canonical frame builder shared with the V2 windowed backtest path."""
        return QuantService._rows_to_frame(rows)

    def _daily_frame(
        self,
        stock_code: str,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> pd.DataFrame:
        if self._market is None:
            return self._stock.get_daily_kline_frame(stock_code, start_date, end_date)
        rows = self._market.query_daily(
            stock_code,
            start_date,
            end_date,
            min_rows=DEFAULT_MIN_KLINE_ROWS,
            max_stale_days=DEFAULT_MAX_STALE_DAYS,
            max_gap_days=DEFAULT_MAX_GAP_DAYS,
        )
        return self._rows_to_frame(rows)

    @staticmethod
    def _rows_to_frame(rows: List[DailyKlineSchema]) -> pd.DataFrame:
        return pd.DataFrame(
            [row.model_dump() for row in sorted(rows, key=lambda item: item.trade_date)]
        )

    @staticmethod
    def _run(func, frame: pd.DataFrame, config: ConfigInput):
        try:
            return func(frame, config)
        except InsufficientStockDataError:
            raise
        except QuantInsufficientDataError as exc:
            raise InsufficientStockDataError(str(exc)) from exc
        except (ValueError, ZeroDivisionError, OverflowError, RuntimeError) as exc:
            raise QuantCalculationError(str(exc)) from exc
