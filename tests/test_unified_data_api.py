from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.app.api.v1.dependencies import get_market_data_source
from backend.app.main import app
from backend.app.schemas.stock import DailyKlineSchema
from backend.app.services.market_data_service import (
    DEFAULT_MAX_GAP_DAYS,
    DEFAULT_MAX_STALE_DAYS,
)
from backend.app.services.stock_service import DEFAULT_MIN_KLINE_ROWS


STOCK_CODE = "600519"


def _rows(stock_code: str, count: int = 80):
    start = date(2025, 1, 1)
    rows = []
    for index in range(count):
        close = 100.0 + index
        rows.append(
            DailyKlineSchema(
                stock_code=stock_code,
                trade_date=start + timedelta(days=index),
                open=close - 1.0,
                high=close + 1.0,
                low=close - 2.0,
                close=close,
                volume=1000 + index,
                amount=100000.0 + index,
                turnover_rate=0.01,
                change_pct=0.02,
            )
        )
    return rows


class RecordingMarketDataSource:
    def __init__(self) -> None:
        self.calls = []

    def query_daily(self, stock_code, start_date=None, end_date=None, **kwargs):
        self.calls.append((stock_code, start_date, end_date, kwargs))
        return _rows(stock_code)


def test_stock_kline_and_quant_api_use_unified_market_data_source():
    source = RecordingMarketDataSource()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_market_data_source] = lambda: source

    try:
        with TestClient(app) as client:
            kline = client.get(f"/api/v1/stocks/{STOCK_CODE}/kline")
            score = client.get(f"/api/v1/stocks/{STOCK_CODE}/score")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)

    assert kline.status_code == 200
    assert score.status_code == 200
    assert kline.json()["data"][0]["trade_date"] == "2025-01-01"
    assert [call[0] for call in source.calls] == [STOCK_CODE, STOCK_CODE]
    assert source.calls[0][3] == {
        "min_rows": DEFAULT_MIN_KLINE_ROWS,
        "max_stale_days": DEFAULT_MAX_STALE_DAYS,
        "max_gap_days": DEFAULT_MAX_GAP_DAYS,
    }
    assert source.calls[1][3] == source.calls[0][3]
