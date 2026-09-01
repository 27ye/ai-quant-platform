"""Validate the standalone quant core with synthetic or real AKShare daily data."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.quant.pipeline import analyze_quant_dataframe  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("synthetic", "akshare"), default="synthetic")
    parser.add_argument("--stock-code", default="600519")
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2024, 1, 1))
    parser.add_argument("--end-date", type=date.fromisoformat, default=date(2026, 8, 31))
    return parser.parse_args()


def build_synthetic_daily_data(
    stock_code: str, start_date: date, end_date: date
) -> pd.DataFrame:
    """Create explicitly synthetic, deterministic qfq-like daily test data."""

    dates = pd.bdate_range(start=start_date, end=end_date)
    if len(dates) < 260:
        raise ValueError(
            f"synthetic validation range must contain at least 260 business days; got {len(dates)}"
        )
    index = np.arange(len(dates), dtype=float)
    close = 100.0 + 0.045 * index + 4.0 * np.sin(index / 12.0) + 1.5 * np.cos(index / 5.0)
    open_price = close * (1.0 + 0.0025 * np.sin(index / 3.0))
    high = np.maximum(open_price, close) * (1.008 + 0.001 * np.cos(index / 7.0))
    low = np.minimum(open_price, close) * (0.992 - 0.001 * np.sin(index / 9.0))
    volume = 1_000_000.0 + 120_000.0 * (1.0 + np.sin(index / 8.0))
    result = pd.DataFrame(
        {
            "stock_code": stock_code,
            "trade_date": dates,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "turnover_rate": 0.004 + 0.001 * (1.0 + np.cos(index / 10.0)),
        }
    )
    result["change_pct"] = result["close"].pct_change()
    result.attrs["data_mode"] = "synthetic"
    return result


def load_akshare_daily_data(args: argparse.Namespace) -> pd.DataFrame:
    """Keep the only real-data call in this validation script's Provider boundary."""

    from backend.app.data.providers.akshare_provider import AKShareStockProvider

    provider = AKShareStockProvider()
    result = provider.get_daily_kline(
        stock_code=args.stock_code,
        start_date=args.start_date,
        end_date=args.end_date,
        adjust="qfq",
    )
    result.attrs["data_mode"] = "akshare"
    return result


def main() -> int:
    args = parse_args()
    if args.start_date > args.end_date:
        print("quant validation failed: start_date must not exceed end_date", file=sys.stderr)
        return 1
    try:
        if args.source == "synthetic":
            data = build_synthetic_daily_data(
                args.stock_code, args.start_date, args.end_date
            )
        else:
            data = load_akshare_daily_data(args)
        result = analyze_quant_dataframe(data)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    except Exception as exc:
        print(f"quant validation failed ({args.source}): {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
