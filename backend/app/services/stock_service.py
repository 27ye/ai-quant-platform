from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from backend.app.core.errors import InsufficientStockDataError
from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProvider,
    StockDataSchemaError,
)
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema

DEFAULT_MIN_KLINE_ROWS = 60
DEFAULT_WINDOW_DAYS = 366
MAX_FETCH_YEARS = 5

_REQUIRED_NUMERIC = ("open", "high", "low", "close", "volume")
_PROVIDER_COLUMNS = (
    "stock_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "change_pct",
)


class StockService:
    """Interface/adapter layer that guarantees a minimum window of cleaned qfq daily K-line.

    C's quant core requires at least ``DEFAULT_MIN_KLINE_ROWS`` (60) rows of
    cleaned qfq daily data. This service:

    * widens the fetch window when the requested range is too short
    * treats an empty first response as zero rows (keeps widening) rather than aborting
    * cleans/validates rows: unique strictly-increasing dates, finite required numerics,
      non-negative volume, and legal OHLC (high >= open/close, low <= open/close)
    * raises ``InsufficientStockDataError`` (business code 40003) when the stock
      does not have enough valid rows
    """

    def __init__(self, provider: Optional[StockDataProvider] = None) -> None:
        self._provider = provider or AKShareStockProvider()

    def get_daily_kline(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
    ) -> List[DailyKlineSchema]:
        frame = self.get_daily_kline_frame(stock_code, start_date, end_date, min_rows)
        return [DailyKlineSchema(**row) for row in frame.to_dict("records")]

    def get_daily_kline_frame(
        self,
        stock_code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        min_rows: int = DEFAULT_MIN_KLINE_ROWS,
    ) -> pd.DataFrame:
        """Return the cleaned qfq daily K-line as a DataFrame (>= ``min_rows`` rows)."""
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=DEFAULT_WINDOW_DAYS))
        hard_start = end_date - timedelta(days=MAX_FETCH_YEARS * 366)

        frame = self._fetch_and_clean(stock_code, start_date, end_date)
        while len(frame) < min_rows and start_date > hard_start:
            start_date = self._widen(start_date, hard_start)
            frame = self._fetch_and_clean(stock_code, start_date, end_date)

        if len(frame) < min_rows:
            raise InsufficientStockDataError(
                f"stock {stock_code} daily kline has {len(frame)} cleaned rows; "
                f"at least {min_rows} required"
            )

        return frame

    def search_stocks(self, keyword: str) -> List[StockBasicSchema]:
        """Search A-share stocks by code or name substring (via AKShare)."""
        items = self._provider.search_stocks(keyword)
        return [
            StockBasicSchema(stock_code=item["stock_code"], stock_name=item["stock_name"])
            for item in items
        ]

    def get_stock_info(self, stock_code: str) -> StockBasicSchema:
        """Return basic stock info (name, industry, market caps) via AKShare."""
        info = self._provider.get_stock_info(stock_code)
        return StockBasicSchema(**info)

    def _fetch_and_clean(self, stock_code: str, start_date: date, end_date: date) -> pd.DataFrame:
        try:
            frame = self._provider.get_daily_kline(stock_code, start_date, end_date, adjust="qfq")
        except EmptyStockDataError:
            return self._empty_frame()
        return self._clean_frame(frame)

    @staticmethod
    def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            return StockService._empty_frame()

        missing = [column for column in _REQUIRED_NUMERIC if column not in frame.columns]
        if missing:
            raise StockDataSchemaError(f"stock daily kline missing required columns: {missing}")

        df = frame.copy()
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date")
            df = df.drop_duplicates(subset=["trade_date"], keep="last")

        numeric = df[list(_REQUIRED_NUMERIC)].apply(pd.to_numeric, errors="coerce")
        finite = np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
        df = df[finite]
        df = df[df["volume"] >= 0]
        df = df[
            (df["high"] >= df["open"])
            & (df["high"] >= df["close"])
            & (df["low"] <= df["open"])
            & (df["low"] <= df["close"])
            & (df["high"] >= df["low"])
        ]
        return df.reset_index(drop=True)

    @staticmethod
    def _empty_frame() -> pd.DataFrame:
        return pd.DataFrame(columns=list(_PROVIDER_COLUMNS))

    @staticmethod
    def _widen(start_date: date, hard_start: date) -> date:
        candidate = start_date - timedelta(days=366)
        return candidate if candidate > hard_start else hard_start
