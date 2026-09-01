from __future__ import annotations

from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd
import pytest


def make_daily_frame(
    closes: Iterable[float],
    opens: Optional[Iterable[float]] = None,
    stock_code: str = "600519",
) -> pd.DataFrame:
    close = np.asarray(list(closes), dtype=float)
    open_price = close.copy() if opens is None else np.asarray(list(opens), dtype=float)
    dates = pd.bdate_range("2024-01-01", periods=len(close))
    high = np.maximum(open_price, close) * 1.01
    low = np.minimum(open_price, close) * 0.99
    frame = pd.DataFrame(
        {
            "stock_code": stock_code,
            "trade_date": dates,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.linspace(900_000, 1_100_000, len(close)),
        }
    )
    frame["amount"] = frame["volume"] * frame["close"]
    frame["turnover_rate"] = 0.005
    frame["change_pct"] = frame["close"].pct_change()
    frame.attrs["data_mode"] = "synthetic_test_fixture"
    return frame


@pytest.fixture
def frame_factory() -> Callable[..., pd.DataFrame]:
    return make_daily_frame


@pytest.fixture
def synthetic_daily_data() -> pd.DataFrame:
    index = np.arange(320, dtype=float)
    close = 100.0 + 0.05 * index + 3.0 * np.sin(index / 11.0)
    open_price = close * (1.0 + 0.002 * np.cos(index / 5.0))
    return make_daily_frame(close, open_price)
