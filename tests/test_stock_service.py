from datetime import date, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.core.errors import InsufficientStockDataError
from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProvider,
    StockDataSchemaError,
)
from backend.app.main import app
from backend.app.schemas.stock import DailyKlineSchema, StockBasicSchema
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS, StockService

STOCK_CODE = "600519"
END_DATE = date(2026, 1, 1)


def _make_frame(rows, start_date, stock_code=STOCK_CODE, num_bad=0):
    rows = int(rows)
    num_bad = min(int(num_bad), rows)
    dates = [start_date + timedelta(days=i) for i in range(rows)]
    data = {
        "stock_code": [stock_code] * rows,
        "trade_date": dates,
        "open": [100.0] * rows,
        "high": [110.0] * rows,
        "low": [90.0] * rows,
        "close": [105.0] * rows,
        "volume": [1000] * rows,
        "amount": [100000.0] * rows,
        "turnover_rate": [0.01] * rows,
        "change_pct": [0.02] * rows,
    }
    for i in range(rows - num_bad, rows):
        data["volume"][i] = -1  # invalid: negative volume
        data["high"][i] = 80.0  # invalid: high < open/low/close
    return pd.DataFrame(data)


class FakeProvider(StockDataProvider):
    """Deterministic provider stub returning a preset sequence of row counts."""

    def __init__(self, row_counts, num_bad=0, raise_empty_on_calls=()):
        self.row_counts = list(row_counts)
        self.num_bad = num_bad
        self.raise_empty_on_calls = set(raise_empty_on_calls)
        self.calls = []

    def get_daily_kline(self, stock_code, start_date, end_date, adjust="qfq"):
        index = len(self.calls)
        self.calls.append((stock_code, start_date, end_date, adjust))
        if index in self.raise_empty_on_calls:
            raise EmptyStockDataError("no data")
        rows = self.row_counts.pop(0) if self.row_counts else 0
        return _make_frame(rows, start_date, stock_code, num_bad=self.num_bad)


def test_min_rows_default_is_60():
    assert DEFAULT_MIN_KLINE_ROWS == 60


def test_returns_records_when_enough_data():
    provider = FakeProvider([120])
    service = StockService(provider=provider)

    result = service.get_daily_kline(STOCK_CODE, date(2025, 1, 1), END_DATE)

    assert len(result) == 120
    assert all(isinstance(row, DailyKlineSchema) for row in result)
    assert result[0].stock_code == STOCK_CODE
    assert len(provider.calls) == 1


def test_widens_window_when_initial_window_insufficient():
    provider = FakeProvider([30, 90])
    service = StockService(provider=provider)

    result = service.get_daily_kline(STOCK_CODE, date(2025, 1, 1), END_DATE)

    assert len(result) == 90
    assert len(provider.calls) == 2
    assert provider.calls[1][1] < provider.calls[0][1]


def test_widens_when_first_response_empty():
    provider = FakeProvider([70], raise_empty_on_calls=(0,))
    service = StockService(provider=provider)

    result = service.get_daily_kline(STOCK_CODE, date(2025, 1, 1), END_DATE)

    assert len(result) == 70
    assert len(provider.calls) == 2


def test_cleaning_drops_invalid_rows():
    provider = FakeProvider([70], num_bad=5)
    service = StockService(provider=provider)

    result = service.get_daily_kline(STOCK_CODE, date(2025, 1, 1), END_DATE)

    assert len(result) == 65
    for row in result:
        assert row.volume >= 0
        assert row.high >= row.open and row.high >= row.close
        assert row.low <= row.open and row.low <= row.close


def test_raises_core_error_when_never_reaches_min_rows():
    provider = FakeProvider([20])
    service = StockService(provider=provider)

    with pytest.raises(InsufficientStockDataError):
        service.get_daily_kline(STOCK_CODE, date(2025, 1, 1), END_DATE)


def test_endpoint_returns_kline():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_daily_kline(self, stock_code, start_date=None, end_date=None):
            return [
                DailyKlineSchema(
                    stock_code=stock_code,
                    trade_date=date(2025, 1, 1),
                    open=100.0,
                    high=110.0,
                    low=90.0,
                    close=105.0,
                    volume=1000,
                )
            ]

    stocks_module._service = FakeService()

    response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/kline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert len(payload["data"]) == 1
    assert payload["data"][0]["stock_code"] == STOCK_CODE


def test_endpoint_returns_business_code_40003_for_insufficient_data():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_daily_kline(self, stock_code, start_date=None, end_date=None):
            raise InsufficientStockDataError("not enough history")

    stocks_module._service = FakeService()

    response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/kline")

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == 40003
    assert payload["data"] is None


def test_endpoint_rejects_non_daily_period():
    response = TestClient(app).get(
        f"/api/v1/stocks/{STOCK_CODE}/kline?period=weekly"
    )

    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_endpoint_invalid_stock_code_returns_40001():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_daily_kline(self, stock_code, start_date=None, end_date=None):
            raise InvalidStockCodeError("stock_code must be a 6-digit string")

    stocks_module._service = FakeService()

    response = TestClient(app).get("/api/v1/stocks/abc/kline")

    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_endpoint_provider_error_returns_50001():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_daily_kline(self, stock_code, start_date=None, end_date=None):
            raise StockDataSchemaError("missing required columns")

    stocks_module._service = FakeService()

    response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}/kline")

    assert response.status_code == 502
    assert response.json()["code"] == 50001


def test_search_stocks_returns_list():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def search_stocks(self, keyword):
            return [StockBasicSchema(stock_code=STOCK_CODE, stock_name="贵州茅台")]

    stocks_module._service = FakeService()

    response = TestClient(app).get("/api/v1/stocks/search?keyword=茅台")

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"][0]["stock_code"] == STOCK_CODE


def test_search_empty_keyword_returns_40001():
    response = TestClient(app).get("/api/v1/stocks/search?keyword=")

    assert response.status_code == 400
    assert response.json()["code"] == 40001


def test_stock_info_returns_basic_info():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_stock_info(self, stock_code):
            return StockBasicSchema(
                stock_code=stock_code,
                stock_name="贵州茅台",
                industry="酿酒行业",
                total_market_cap=1.0,
                float_market_cap=1.0,
            )

    stocks_module._service = FakeService()

    response = TestClient(app).get(f"/api/v1/stocks/{STOCK_CODE}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stock_code"] == STOCK_CODE
    assert data["stock_name"] == "贵州茅台"


def test_stock_info_invalid_code_returns_40001():
    import backend.app.api.v1.stocks as stocks_module

    class FakeService:
        def get_stock_info(self, stock_code):
            raise InvalidStockCodeError("stock_code must be a 6-digit string")

    stocks_module._service = FakeService()

    response = TestClient(app).get("/api/v1/stocks/abc")

    assert response.status_code == 400
    assert response.json()["code"] == 40001
