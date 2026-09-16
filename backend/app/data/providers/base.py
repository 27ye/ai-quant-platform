from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


class StockDataProviderError(RuntimeError):
    """Base exception for stock data provider failures."""


class InvalidStockCodeError(StockDataProviderError):
    """Raised when stock code format is invalid."""


class EmptyStockDataError(StockDataProviderError):
    """Raised when the data source returns no rows."""


class StockDataSchemaError(StockDataProviderError):
    """Raised when the data source schema is unexpected."""


class StockDataProvider(ABC):
    @abstractmethod
    def get_daily_kline(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Fetch daily kline data and return normalized snake_case columns."""

    def fetch_stock_catalog(self) -> list:
        """Return the full A-share catalog as ``[{stock_code, stock_name}]``.

        Used by the V2 catalog sync, not by online search. Providers that cannot
        enumerate the market keep this default and fail loudly instead of
        returning an empty catalog (which would look like "no stocks exist").
        """
        raise StockDataProviderError(
            "stock catalog fetch is not supported by this provider"
        )
