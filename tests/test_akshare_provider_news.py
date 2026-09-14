"""Tests for AKShare news normalization in the provider."""
import sys
import types
from datetime import datetime, timedelta

import pandas as pd
import pytest

from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import InvalidStockCodeError, StockDataSchemaError

NEWS_COLUMNS = ["关键词", "新闻标题", "新闻内容", "发布时间", "文章来源", "新闻链接"]


def _fake_akshare(frame: pd.DataFrame) -> types.ModuleType:
    module = types.ModuleType("akshare")
    module.stock_news_em = lambda symbol: frame
    return module


def _rows(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "关键词": ["600519"] * n,
            "新闻标题": [f"标题{i}" for i in range(n)],
            "新闻内容": [f"内容{i}" for i in range(n)],
            "发布时间": ["2026-08-31 09:30:00"] * n,
            "文章来源": ["东方财富"] * n,
            "新闻链接": [f"http://finance.eastmoney.com/a/{i}.html" for i in range(n)],
        }
    )


def test_normalizes_chinese_columns_to_unified_fields(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(_rows(1)))

    items = AKShareStockProvider().get_stock_news("600519")

    assert len(items) == 1
    item = items[0]
    assert item["stock_code"] == "600519"
    assert item["title"] == "标题0"
    assert item["summary"] == "内容0"
    assert item["source"] == "东方财富"
    assert isinstance(item["publish_time"], datetime)
    assert item["url"].startswith("http://finance.eastmoney.com/")


def test_respects_limit_and_drops_blank_titles(monkeypatch):
    frame = _rows(3)
    frame.loc[1, "新闻标题"] = None
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(frame))

    items = AKShareStockProvider().get_stock_news("600519", limit=2)

    assert len(items) == 2
    assert {item["title"] for item in items} == {"标题0", "标题2"}


def test_empty_frame_returns_empty_list(monkeypatch):
    frame = pd.DataFrame(columns=NEWS_COLUMNS)
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(frame))

    assert AKShareStockProvider().get_stock_news("600519") == []


def test_missing_columns_raise_schema_error(monkeypatch):
    frame = pd.DataFrame({"新闻标题": ["x"]})
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(frame))

    with pytest.raises(StockDataSchemaError):
        AKShareStockProvider().get_stock_news("600519")


def test_rejects_invalid_stock_code(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(_rows(1)))

    with pytest.raises(InvalidStockCodeError):
        AKShareStockProvider().get_stock_news("abc")


def test_sorts_all_news_before_applying_limit_newest_at_tail(monkeypatch):
    # 51 items, newest (index 50 / title "n50") at the very end of the raw order.
    n = 51
    base = datetime(2026, 8, 1, 0, 0)
    frame = pd.DataFrame(
        {
            "关键词": ["600519"] * n,
            "新闻标题": [f"n{i}" for i in range(n)],
            "新闻内容": ["内容"] * n,
            "发布时间": [(base + timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M:%S") for i in range(n)],
            "文章来源": ["来源"] * n,
            "新闻链接": [f"http://finance.eastmoney.com/a/{i}.html" for i in range(n)],
        }
    )
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(frame))

    items = AKShareStockProvider().get_stock_news("600519", limit=1)

    assert len(items) == 1
    assert items[0]["title"] == "n50"  # newest (at raw tail) survives the sort

