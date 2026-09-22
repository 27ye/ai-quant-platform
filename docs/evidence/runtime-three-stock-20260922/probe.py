import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


STOCKS = ("600519", "000001", "300750")
START_DATE = "2025-09-01"
END_DATE = "2026-09-21"
BACKTEST_START = "2025-07-04"
BACKTEST_END = "2026-08-31"


def response_summary(response):
    try:
        payload = response.json()
    except Exception:
        return {"http": response.status_code, "body": response.text[:500]}
    result = {
        "http": response.status_code,
        "code": payload.get("code"),
        "message": payload.get("message"),
    }
    data = payload.get("data")
    if isinstance(data, list):
        result["rows"] = len(data)
        if data and isinstance(data[0], dict):
            result["first_trade_date"] = data[0].get("trade_date")
            result["last_trade_date"] = data[-1].get("trade_date")
    elif isinstance(data, dict):
        result["data"] = data
    return result


app = create_app()
evidence = {
    "head": "851146e6a810a37f728a233a839ccd617aa4ee77",
    "production_code": "bcbd559acb67d3435fe7a840f34ad73bbe35bbad",
    "database_mode": "isolated_mysql_8_port3308",
    "window": {"start_date": START_DATE, "end_date": END_DATE},
    "backtest_window": {"start_date": BACKTEST_START, "end_date": BACKTEST_END},
    "stocks": {},
}

with TestClient(app, raise_server_exceptions=False) as client:
    evidence["catalog_search"] = response_summary(
        client.get("/api/v1/stocks/search", params={"keyword": "茅台"})
    )
    for stock_code in STOCKS:
        kline = client.get(
            f"/api/v1/stocks/{stock_code}/kline",
            params={"start_date": START_DATE, "end_date": END_DATE},
        )
        status = client.get(f"/api/v1/stocks/{stock_code}/data-status")
        backtest = client.post(
            "/api/v1/backtests",
            json={
                "stock_code": stock_code,
                "start_date": BACKTEST_START,
                "end_date": BACKTEST_END,
                "parameters": {},
            },
        )
        evidence["stocks"][stock_code] = {
            "kline": response_summary(kline),
            "data_status": response_summary(status),
            "backtest": response_summary(backtest),
        }

output = Path(".tmp/live-three-stock-851146e.json")
output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(evidence, ensure_ascii=False, indent=2))
