"""Tests for the AKShare provider's transient retry + delayed-host fallback."""
import sys
import types
from datetime import date

import pandas as pd
import pytest

from backend.app.data.providers.akshare_provider import AKShareStockProvider
from backend.app.data.providers.base import StockDataProviderError, StockDataSchemaError


def _kline_frame():
    return pd.DataFrame(
        {
            "日期": ["2025-01-02", "2025-01-03"],
            "股票代码": ["600519", "600519"],
            "开盘": [100.0, 101.0],
            "收盘": [105.0, 106.0],
            "最高": [110.0, 111.0],
            "最低": [90.0, 91.0],
            "成交量": [1000, 1100],
            "成交额": [100000.0, 110000.0],
            "换手率": [1.0, 1.1],
            "涨跌幅": [0.5, 0.6],
        }
    )


def _fake_akshare(**funcs):
    module = types.ModuleType("akshare")
    for name, func in funcs.items():
        setattr(module, name, func)
    return module


def test_kline_retries_transient_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)
    calls = {"n": 0}

    def hist(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("connection reset")
        return _kline_frame()

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))

    frame = AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))

    assert len(frame) == 2
    assert calls["n"] == 2  # one transient failure, then success


def test_kline_raises_after_retries_exhausted(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)
    monkeypatch.setattr(AKShareStockProvider, "retry_attempts", 3)
    monkeypatch.setattr(AKShareStockProvider, "retry_total_budget_seconds", 30)
    calls = {"hist": 0, "fallback": 0}

    def hist(**kwargs):
        calls["hist"] += 1
        raise ConnectionError("connection reset")

    def failing_get(*args, **kwargs):
        calls["fallback"] += 1
        raise ConnectionError("fallback down")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))
    monkeypatch.setattr(requests, "get", failing_get)  # isolate the fallback request

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))

    assert calls["hist"] == 3  # bounded primary attempts
    assert calls["fallback"] == 1  # fallback attempted exactly once, no real network


def test_stock_info_falls_back_to_delayed_host(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))

    class _Response:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "f57": "600519",
                    "f58": "贵州茅台",
                    "f116": 1606517367893.13,
                    "f117": 1606517367893.13,
                    "f127": "白酒Ⅱ",
                }
            }

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response())

    result = AKShareStockProvider().get_stock_info("600519")

    assert result["stock_code"] == "600519"
    assert result["stock_name"] == "贵州茅台"
    assert result["industry"] == "白酒Ⅱ"
    assert result["total_market_cap"] == 1606517367893.13


def test_stock_info_raises_when_fallback_also_fails(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))

    def failing_get(*args, **kwargs):
        raise ConnectionError("fallback down")

    monkeypatch.setattr(requests, "get", failing_get)

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_kline_falls_back_to_delayed_host(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def hist(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))

    class _Response:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2025-01-02,100.0,105.0,110.0,90.0,1000,100000.0,5.0,0.5,0.5,1.0",
                        "2025-01-03,101.0,106.0,111.0,91.0,1100,110000.0,5.0,0.6,0.6,1.1",
                    ]
                }
            }

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _Response())

    frame = AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))

    assert list(frame["trade_date"]) == [date(2025, 1, 2), date(2025, 1, 3)]
    assert list(frame["close"]) == [105.0, 106.0]


def test_call_budget_returns_quickly_when_upstream_hangs(monkeypatch):
    import time as _time

    import requests

    monkeypatch.setattr(AKShareStockProvider, "call_timeout_seconds", 0.2)
    monkeypatch.setattr(AKShareStockProvider, "retry_total_budget_seconds", 0.5)
    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def hanging_hist(**kwargs):
        _time.sleep(5)  # upstream hangs
        return _kline_frame()

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hanging_hist))

    def failing_get(*args, **kwargs):
        raise ConnectionError("fallback down")

    monkeypatch.setattr(requests, "get", failing_get)

    start = _time.monotonic()
    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))
    elapsed = _time.monotonic() - start

    assert elapsed < 2.0  # bounded, must not hang for the full retry budget chain


def _response_with(payload, status_code=200):
    class _Response:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return payload

    return _Response(status_code)


def test_stock_info_fallback_rejects_non_dict_data(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _response_with({"data": [1]}))

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_stock_info_fallback_rejects_nonzero_rc(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": -1, "data": {"error": "upstream throttled"}}),
    )

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_stock_info_fallback_rejects_missing_required_fields(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _response_with({"rc": 0, "data": {}}))

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_kline_fallback_rejects_malformed_row(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def hist(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))

    good = "2025-01-02,100.0,105.0,110.0,90.0,1000,100000.0,5.0,0.5,0.5,1.0"
    malformed = "2025-01-03,101.0,106.0"  # only 3 columns -> corrupt upstream row
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _response_with({"rc": 0, "data": {"klines": [good, malformed]}})
    )

    with pytest.raises(StockDataSchemaError):
        AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))


def _primed_info_provider(monkeypatch):
    def info(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))


def test_stock_info_fallback_rejects_non_string_fields(monkeypatch):
    import requests

    _primed_info_provider(monkeypatch)

    # f58 as a list must not raise a bare 500; it must map to 50001.
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": 0, "data": {"f57": "600519", "f58": ["A", "B"]}}),
    )
    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")

    # f57 as a list must map to 50001 too.
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": 0, "data": {"f57": ["600519"], "f58": "贵州茅台"}}),
    )
    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_stock_info_fallback_rejects_mismatched_stock_code(monkeypatch):
    import requests

    _primed_info_provider(monkeypatch)

    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": 0, "data": {"f57": "000001", "f58": "平安银行"}}),
    )

    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")


def test_fallbacks_reject_non_200_status(monkeypatch):
    import requests

    _primed_info_provider(monkeypatch)
    # stock info: HTTP 503 with a valid-looking body must still fail.
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with(
            {"rc": 0, "data": {"f57": "600519", "f58": "贵州茅台"}}, status_code=503
        ),
    )
    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_stock_info("600519")

    # kline: HTTP 503 with valid-looking klines must still fail.
    def hist(**kwargs):
        raise ConnectionError("connection reset")

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)
    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with(
            {"rc": 0, "data": {"klines": ["2025-01-02,100.0,105.0,110.0,90.0,1000,1,0,0.5,0.5,1.0"]}},
            status_code=503,
        ),
    )
    with pytest.raises(StockDataProviderError):
        AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))


def test_background_workers_are_capped(monkeypatch):
    import threading
    import time as _time

    import requests

    release = threading.Event()
    monkeypatch.setattr(AKShareStockProvider, "call_timeout_seconds", 0.05)
    monkeypatch.setattr(AKShareStockProvider, "retry_total_budget_seconds", 5)
    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)
    monkeypatch.setattr(AKShareStockProvider, "retry_attempts", 1)
    monkeypatch.setattr(AKShareStockProvider, "max_background_workers", 2)
    AKShareStockProvider._active_workers = 0

    def hanging(**kwargs):
        release.wait(timeout=5)
        return _kline_frame()

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hanging))

    def failing_get(*args, **kwargs):
        raise ConnectionError("fallback down")

    monkeypatch.setattr(requests, "get", failing_get)

    seen = []
    try:
        for _ in range(5):
            try:
                AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))
            except StockDataProviderError:
                pass
            seen.append(AKShareStockProvider._active_workers)
        assert max(seen) <= 2  # never exceeds the cap
        assert seen[-1] == 2  # capped: no further hung workers spawned
    finally:
        release.set()
        for _ in range(100):
            if AKShareStockProvider._active_workers == 0:
                break
            _time.sleep(0.05)

    assert AKShareStockProvider._active_workers == 0


def test_kline_error_reports_the_fallback_reason(monkeypatch):
    """An empty delayed-host payload must not be reported as the primary error."""
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def hist(**kwargs):
        raise ConnectionError("primary host unreachable")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_zh_a_hist=hist))
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": 0, "data": {"dktotal": 0, "klines": []}}),
    )

    with pytest.raises(StockDataProviderError) as excinfo:
        AKShareStockProvider().get_daily_kline("600519", date(2025, 1, 1), date(2025, 1, 5))

    message = str(excinfo.value)
    assert "primary host unreachable" in message  # the primary cause is kept
    assert "delayed-host fallback also failed" in message  # ... and the real reason
    assert "no klines" in message


def test_stock_info_error_reports_the_fallback_reason(monkeypatch):
    import requests

    monkeypatch.setattr(AKShareStockProvider, "retry_delay_seconds", 0)

    def info(**kwargs):
        raise ConnectionError("primary host unreachable")

    monkeypatch.setitem(sys.modules, "akshare", _fake_akshare(stock_individual_info_em=info))
    monkeypatch.setattr(
        requests,
        "get",
        lambda *a, **k: _response_with({"rc": -1, "data": {"error": "throttled"}}),
    )

    with pytest.raises(StockDataProviderError) as excinfo:
        AKShareStockProvider().get_stock_info("600519")

    message = str(excinfo.value)
    assert "primary host unreachable" in message
    assert "delayed-host fallback also failed" in message
    assert "rc=-1" in message

