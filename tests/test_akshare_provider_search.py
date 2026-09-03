from datetime import date

import pandas as pd
import pytest

from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import StockDataProviderError


def _spot_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "代码": ["600519", "000001", "300750"],
            "名称": ["贵州茅台", "平安银行", "宁德[时代]"],
        }
    )


def _info_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "item": ["股票简称", "行业", "总市值", "流通市值"],
            "value": ["贵州茅台", "酿酒行业", "123456789000.0", "90000000000.0"],
        }
    )


def test_search_stocks_regex_special_char_keyword(monkeypatch):
    """keyword like '[' must not crash (regex=False) and match literal text."""
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: _spot_df())
    provider = AKShareStockProvider()

    result = provider.search_stocks("[")

    assert isinstance(result, list)
    assert {"stock_code": "300750", "stock_name": "宁德[时代]"} in result


def test_search_stocks_matches_plain_text(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: _spot_df())
    provider = AKShareStockProvider()

    result = provider.search_stocks("[")

    assert len(result) == 1
    assert result[0]["stock_code"] == "300750"


def test_search_stocks_normal_matches(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: _spot_df())
    provider = AKShareStockProvider()

    result = provider.search_stocks("茅台")

    assert len(result) == 1
    assert result[0]["stock_code"] == "600519"


def test_search_stocks_empty_keyword_raises(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(ak, "stock_zh_a_spot_em", lambda: _spot_df())
    provider = AKShareStockProvider()

    with pytest.raises(StockDataProviderError):
        provider.search_stocks("   ")


def test_get_stock_info_normalizes(monkeypatch):
    import akshare as ak

    monkeypatch.setattr(ak, "stock_individual_info_em", lambda symbol: _info_df())
    provider = AKShareStockProvider()

    info = provider.get_stock_info("600519")

    assert info["stock_code"] == "600519"
    assert info["stock_name"] == "贵州茅台"
    assert info["industry"] == "酿酒行业"
    assert info["total_market_cap"] == 123456789000.0
    assert info["float_market_cap"] == 90000000000.0
