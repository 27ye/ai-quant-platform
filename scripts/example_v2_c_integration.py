"""Runnable C handoff example using synthetic rows and an in-memory loader.

This is not an HTTP endpoint, B's service implementation or real-market evidence.
Run from the repository root; optionally give a NEW --output-dir for JSON examples.
The adapter assumes B has validated the stock code and resolved default dates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.quant import (  # noqa: E402
    PARAMETERS_UNSET,
    BacktestParameterError,
    resolve_backtest_request,
    run_backtest_request,
    validate_backtest_window,
)


def call_c_example(body: Dict[str, Any], load_daily: Callable[..., pd.DataFrame]) -> Dict[str, Any]:
    """Preserve raw JSON types/presence; validate parameters before data I/O.

    B supplies its own loader. It returns canonical rows including warmup, not a
    frame already trimmed to the user's window. Keep B's V1 fetch path unchanged;
    required_warmup_rows is a pre-start requirement only for v2_windowed.
    """

    parameters = body["parameters"] if "parameters" in body else PARAMETERS_UNSET
    request = resolve_backtest_request(parameters)
    start, end = body.get("start_date"), body.get("end_date")
    if request.semantics_version == "v2_windowed":
        start, end = validate_backtest_window(start, end)
    data = load_daily(
        stock_code=body["stock_code"],
        start_date=start,
        end_date=end,
        semantics_version=request.semantics_version,
        required_warmup_rows=request.required_warmup_rows,
    )
    return run_backtest_request(data, start_date=start, end_date=end, parameters=parameters)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is not None:
        # Never replace an existing delivery or its results.
        args.output_dir.mkdir(parents=True, exist_ok=False)

    # Synthetic weekdays are fixture labels, not a verified exchange calendar.
    dates = pd.bdate_range("2025-01-01", periods=125)
    prices = [100.0 + index for index in range(len(dates))]
    frame = pd.DataFrame({
        "stock_code": ["000001"] * len(dates),
        "trade_date": dates,
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1000000.0] * len(dates),
    })
    frame.attrs["data_mode"] = "synthetic_c_handoff"
    start, end = dates[120].strftime("%Y-%m-%d"), dates[121].strftime("%Y-%m-%d")
    base = {"stock_code": "000001", "start_date": start, "end_date": end}
    loader_calls = []

    def load_fixture(**kwargs: Any) -> pd.DataFrame:
        loader_calls.append(kwargs)
        return frame.copy(deep=True)

    cases = [
        ("v1-omitted", dict(base)),
        ("v2-empty", {**base, "parameters": {}}),
        ("v2-custom", {**base, "parameters": {"ma_short_period": 10, "ma_long_period": 30}}),
        ("v2-long120-one-day", {
            **base, "end_date": start,
            "parameters": {"ma_short_period": 20, "ma_long_period": 120},
        }),
    ]
    summaries = []
    for name, body in cases:
        result = call_c_example(body, load_fixture)
        expected_points = 125 if name == "v1-omitted" else (1 if name.endswith("one-day") else 2)
        expected_warmup = {"v1-omitted": 0, "v2-empty": 20, "v2-custom": 30, "v2-long120-one-day": 120}[name]
        actual_warmup = result["warmup"]["used_rows"] if result["warmup"] else 0
        if actual_warmup != expected_warmup:
            raise AssertionError("unexpected warmup in " + name)
        for curve in ("equity_curve", "benchmark_curve", "drawdown_curve"):
            if len(result[curve]) != expected_points:
                raise AssertionError("unexpected curve window in " + name)
        if len(result["input_snapshot"]["rows"]) != expected_warmup + expected_points:
            raise AssertionError("unexpected snapshot window in " + name)
        if name != "v1-omitted":
            if any(not start <= row["execution_date"] <= body["end_date"] for row in result["trades"]):
                raise AssertionError("order outside window in " + name)
        saved = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
        if saved != result:
            raise AssertionError("JSON round trip changed the result")
        summary = {
            "case": name, "request": body,
            "semantics_version": result["semantics_version"],
            "required_warmup_rows": loader_calls[-1]["required_warmup_rows"],
            "used_warmup_rows": actual_warmup,
            "curve_points": len(result["equity_curve"]),
            "snapshot_rows": len(result["input_snapshot"]["rows"]),
            "first_order": result["trades"][0] if result["trades"] else None,
            "result_fields": sorted(result), "json_readback_equal": True,
        }
        summaries.append(summary)
        if args.output_dir is not None:
            for suffix, value in (("request", body), ("result", result)):
                with (args.output_dir / (name + "-" + suffix + ".json")).open("x", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
                    stream.write("\n")

    rejections = []
    for parameters in ({"ma_short_period": "5"}, {"initial_cash": "100000"}, {"initial_cash": True}, None):
        before = len(loader_calls)
        try:
            call_c_example({**base, "parameters": parameters}, load_fixture)
        except BacktestParameterError as exc:
            if len(loader_calls) != before:
                raise AssertionError("invalid parameters reached the loader")
            rejections.append({"parameters": parameters, "error": str(exc), "loader_calls": 0})
        else:
            raise AssertionError("invalid parameters were accepted")

    report = {
        "status": "passed", "evidence_scope": "synthetic_c_call_example_only",
        "not_verified": ["B HTTP schema", "real market data", "MySQL persistence", "frontend"],
        "cases": summaries, "rejected_before_loader": rejections,
    }
    text = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output_dir is not None:
        with (args.output_dir / "summary.json").open("x", encoding="utf-8") as stream:
            stream.write(text)
        print(json.dumps({"status": "passed", "summary": str(args.output_dir / "summary.json")}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
