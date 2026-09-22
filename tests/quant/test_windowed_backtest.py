"""Independent, hand-computable acceptance cases for C's V2 request boundary.

All prices here are synthetic fixtures, never evidence of live-data returns.
"""

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.app.quant.backtest import run_backtest
from backend.app.quant.backtest_config import BacktestParameterError
from backend.app.quant.pipeline import analyze_quant_dataframe
from backend.app.quant.validators import InsufficientDataError
from backend.app.quant.windowed_backtest import run_backtest_request


def _date_at(frame, index):
    return frame.iloc[index]["trade_date"].strftime("%Y-%m-%d")


def _window(frame, start_index=3, end_index=None, **overrides):
    parameters = {
        "ma_short_period": 2,
        "ma_long_period": 3,
        "initial_cash": 1000.0,
        "transaction_cost": 0.0,
        "slippage": 0.0,
    }
    parameters.update(overrides)
    return run_backtest_request(
        frame,
        start_date=_date_at(frame, start_index),
        end_date=_date_at(frame, -1 if end_index is None else end_index),
        parameters=parameters,
    )


@pytest.mark.parametrize("closing_price, expected_equity", [(11.0, 1100.0), (9.0, 900.0)])
def test_single_day_starts_at_cash_and_counts_first_day_gain_or_loss(
    frame_factory, closing_price, expected_equity
):
    # Last warm-up close gives MA2=11.5 > MA3=11. Buy 100 shares at 10.
    frame = frame_factory([10, 11, 12, closing_price], [10, 11, 12, 10])
    result = _window(frame)
    assert result["semantics_version"] == "v2_windowed"
    assert result["initial_equity"] == {
        "trade_date": _date_at(frame, 3),
        "equity": 1000.0,
        "valuation": "before_open",
    }
    assert result["final_equity"] == pytest.approx(expected_equity)
    expected_return = 0.1 if closing_price == 11 else -0.1
    assert result["total_return"] == pytest.approx(expected_return)
    assert result["annual_return"] == pytest.approx((expected_equity / 1000) ** 252 - 1)
    assert result["max_drawdown"] == pytest.approx(min(0, expected_return))
    assert result["drawdown_curve"][0]["drawdown"] == pytest.approx(min(0, expected_return))
    assert result["parameters"]["effective_trading_days"] == 1
    assert result["sharpe_ratio"] is None
    assert result["trade_count"] == 0
    assert result["order_count"] == 1
    assert result["win_rate"] is None
    assert result["current_position"] == 1
    for curve in ("equity_curve", "benchmark_curve", "drawdown_curve"):
        assert len(result[curve]) == 1
        assert result[curve][0]["trade_date"] == _date_at(frame, 3)


def test_two_day_sharpe_includes_first_day_return(frame_factory):
    frame = frame_factory([10, 11, 12, 11, 9.9], [10, 11, 12, 10, 11])
    result = _window(frame)
    # Cash 1000 -> 1100 -> 990: daily returns are +10%, -10%, mean zero.
    assert [point["equity"] for point in result["equity_curve"]] == pytest.approx([1100, 990])
    assert result["sharpe_ratio"] == pytest.approx(0, abs=1e-12)
    assert result["max_drawdown"] == pytest.approx(-0.1)
    assert result["annual_return"] == pytest.approx(0.99 ** 126 - 1)
    assert result["parameters"]["effective_trading_days"] == 2


def test_hand_calculated_buy_sell_costs_and_slippage(frame_factory):
    frame = frame_factory([10, 11, 12, 5, 20], [10, 11, 12, 10, 20])
    result = _window(frame, initial_cash=1020.10, transaction_cost=0.01, slippage=0.01)
    # Buy: 100 shares * 10.10 + 10.10 fee = 1020.10.
    # Sell: 100 shares * 19.80 - 19.80 fee = 1960.20.
    assert result["order_count"] == 2
    assert result["trade_count"] == 1
    buy, sell = result["trades"]
    assert buy["side"] == "buy"
    assert buy["signal_date"] == _date_at(frame, 2)
    assert buy["execution_date"] == _date_at(frame, 3)
    assert buy["execution_price"] == pytest.approx(10.10)
    assert buy["shares"] == pytest.approx(100)
    assert buy["gross_amount"] == pytest.approx(1010)
    assert buy["fee"] == pytest.approx(10.10)
    assert buy["cash_after"] == pytest.approx(0, abs=1e-10)
    assert buy["round_trip_pnl"] is None
    assert sell["side"] == "sell"
    assert sell["signal_date"] == _date_at(frame, 3)
    assert sell["execution_date"] == _date_at(frame, 4)
    assert sell["execution_price"] == pytest.approx(19.80)
    assert sell["shares"] == pytest.approx(100)
    assert sell["gross_amount"] == pytest.approx(1980)
    assert sell["fee"] == pytest.approx(19.80)
    assert sell["cash_after"] == pytest.approx(1960.20)
    assert sell["round_trip_pnl"] == pytest.approx(940.10)
    assert sell["round_trip_return"] == pytest.approx(940.10 / 1020.10)
    assert [point["equity"] for point in result["equity_curve"]] == pytest.approx([500, 1960.20])
    assert result["final_equity"] == pytest.approx(1960.20)
    assert result["total_return"] == pytest.approx(940.10 / 1020.10)
    assert result["win_rate"] == 1
    assert result["current_position"] == 0
    # The benchmark pays no costs and buys at the first window open of 10.
    assert [point["benchmark_equity"] for point in result["benchmark_curve"]] == pytest.approx([510.05, 2040.20])
    assert result["benchmark_return"] == pytest.approx(1)
    assert result["parameters"]["benchmark_method"] == "first_open_to_last_close_no_cost"


def test_large_valid_capital_does_not_fail_on_cash_roundoff(frame_factory):
    frame = frame_factory([10, 11, 12, 1])
    result = _window(frame, initial_cash=100000000.0, transaction_cost=0.001)
    # A full allocation at one currency unit leaves a binary floating-point
    # residual around -1.5e-8, not a real overdraft or invalid parameter.
    assert result["order_count"] == 1
    assert result["trades"][0]["cash_after"] == 0
    assert result["final_equity"] == pytest.approx(99900099.9000999)
    assert result["total_return"] == pytest.approx(-0.000999000999001)


@pytest.mark.parametrize("cash, opening_price, slippage", [
    (1000.0, 1e308, 0.99),
    (1e-300, 1e100, 0.0),
])
def test_unrepresentable_execution_fails_instead_of_claiming_no_trade(
    frame_factory, cash, opening_price, slippage
):
    frame = frame_factory([10, 11, 12, 1], [10, 11, 12, opening_price])
    # Both requests use finite inputs, but their execution price overflows or
    # their share quantity underflows. Neither is a successful no-trade result.
    with pytest.raises(RuntimeError, match="numeric precision"):
        _window(frame, initial_cash=cash, slippage=slippage)


def test_no_trades_or_inherited_equity_before_user_window(frame_factory):
    frame = frame_factory([1, 2, 3, 4, 5, 10, 11, 12, 11], [1, 2, 3, 4, 5, 10, 11, 12, 10])
    full = _window(frame, start_index=8)
    minimal = _window(frame.iloc[5:].reset_index(drop=True))
    for field in ("trades", "equity_curve", "benchmark_curve", "drawdown_curve", "final_equity"):
        assert full[field] == minimal[field]
    assert full["initial_cash"] == 1000
    assert full["final_equity"] == pytest.approx(1100)
    assert len(full["trades"]) == 1
    assert full["trades"][0]["order_id"] == 1
    assert full["trades"][0]["execution_date"] == _date_at(frame, 8)
    assert full["trades"][0]["shares"] == pytest.approx(100)


def test_exactly_long_warmup_rows_are_sufficient(frame_factory):
    frame = frame_factory([10, 11, 12, 13])
    result = _window(frame)
    assert len(result["equity_curve"]) == 1
    assert result["order_count"] == 1


def test_one_missing_warmup_row_is_rejected(frame_factory):
    frame = frame_factory([10, 11, 12])
    with pytest.raises(InsufficientDataError):
        _window(frame, start_index=2)


def test_120_day_ma_supports_one_day_user_window(frame_factory):
    frame = frame_factory(np.arange(1, 122, dtype=float))
    result = _window(frame, start_index=120, ma_short_period=2, ma_long_period=120)
    assert result["order_count"] == 1
    assert result["trades"][0]["signal_date"] == _date_at(frame, 119)
    assert len(result["equity_curve"]) == 1
    assert result["final_equity"] == pytest.approx(1000)
    assert result["parameters"]["long_ma"] == 120


def test_120_day_ma_rejects_119_pre_start_rows(frame_factory):
    frame = frame_factory(np.arange(1, 122, dtype=float))
    with pytest.raises(InsufficientDataError):
        _window(frame, start_index=119, ma_long_period=120)


def test_last_day_new_buy_signal_is_not_executed(frame_factory):
    # Flat warmup gives no position. The last close rises sharply but has no next open.
    frame = frame_factory([10, 10, 10, 20], [10, 10, 10, 10])
    result = _window(frame)
    assert result["trades"] == []
    assert result["order_count"] == result["trade_count"] == 0
    assert result["current_position"] == 0
    assert result["final_equity"] == 1000
    assert result["total_return"] == 0
    assert result["win_rate"] is None
    assert result["sharpe_ratio"] is None
    assert result["benchmark_return"] == pytest.approx(1)


def test_last_day_sell_signal_does_not_force_liquidation(frame_factory):
    # Buy at 10 using the warmup signal. Last close=5 changes target to flat,
    # but the closing mark remains 100 shares * 5 until a later open exists.
    frame = frame_factory([10, 11, 12, 5], [10, 11, 12, 10])
    result = _window(frame)
    assert [trade["side"] for trade in result["trades"]] == ["buy"]
    assert result["current_position"] == 1
    assert result["final_equity"] == pytest.approx(500)
    assert result["trade_count"] == 0
    assert result["win_rate"] is None


def test_new_signal_executes_on_next_valid_row_across_year_boundary(frame_factory):
    frame = frame_factory([10, 10, 10, 20, 21], [10, 10, 10, 10, 30])
    frame["trade_date"] = pd.to_datetime(["2024-12-26", "2024-12-27", "2024-12-30", "2024-12-31", "2025-01-02"])
    result = run_backtest_request(
        frame, start_date=date(2024, 12, 31), end_date="2025-01-05",
        parameters={"ma_short_period": 2, "ma_long_period": 3, "transaction_cost": 0.0},
    )
    assert result["start_date"] == "2024-12-31"
    assert result["end_date"] == "2025-01-02"
    assert [point["trade_date"] for point in result["equity_curve"]] == ["2024-12-31", "2025-01-02"]
    assert len(result["trades"]) == 1
    assert result["trades"][0]["signal_date"] == "2024-12-31"
    assert result["trades"][0]["execution_date"] == "2025-01-02"
    assert result["trades"][0]["execution_price"] == 30


def test_weekend_start_uses_next_available_daily_row(frame_factory):
    frame = frame_factory([10, 11, 12, 13])
    frame["trade_date"] = pd.to_datetime(["2024-12-25", "2024-12-26", "2024-12-27", "2024-12-30"])
    result = run_backtest_request(
        frame, start_date="2024-12-28", end_date="2024-12-30",
        parameters={"ma_short_period": 2, "ma_long_period": 3},
    )
    assert result["start_date"] == result["end_date"] == "2024-12-30"
    assert result["trades"][0]["signal_date"] == "2024-12-27"


@pytest.mark.parametrize("start_date, end_date", [
    (None, "2024-01-04"), ("2024-01-04", None),
    ("2024/01/04", "2024-01-05"), ("2024-1-4", "2024-01-05"),
    ("2024-01-04T00:00:00", "2024-01-05"),
    (datetime(2024, 1, 4), date(2024, 1, 5)),
    (date(2024, 1, 4), datetime(2024, 1, 5)),
    ("2024-02-30", "2024-03-01"), ("2024-01-05", "2024-01-04"),
    (20240104, "2024-01-05"), (True, "2024-01-05"),
    ("2024-01-04", "2029-01-05"),
    ("2020-02-29", "2025-03-01"),
])
def test_invalid_explicit_window_dates_are_parameter_errors(frame_factory, start_date, end_date):
    frame = frame_factory([10, 11, 12, 13, 14])
    with pytest.raises(BacktestParameterError):
        run_backtest_request(frame, start_date=start_date, end_date=end_date, parameters={})


def test_five_calendar_year_limit_handles_leap_day(frame_factory):
    frame = frame_factory([10, 11, 12, 13])
    frame["trade_date"] = pd.to_datetime(["2020-02-26", "2020-02-27", "2020-02-28", "2020-03-02"])
    result = run_backtest_request(
        frame, start_date="2020-02-29", end_date="2025-02-28",
        parameters={"ma_short_period": 2, "ma_long_period": 3},
    )
    assert result["start_date"] == result["end_date"] == "2020-03-02"


def test_empty_user_window_is_insufficient_data(frame_factory):
    frame = frame_factory([10, 11, 12, 13])
    with pytest.raises(InsufficientDataError):
        run_backtest_request(
            frame, start_date="2025-01-01", end_date="2025-01-31",
            parameters={"ma_short_period": 2, "ma_long_period": 3},
        )


def test_legacy_request_keeps_every_original_result_field_and_expanded_rows(synthetic_daily_data):
    frame = synthetic_daily_data
    expected = run_backtest(frame)
    result = run_backtest_request(frame, start_date=_date_at(frame, 100), end_date=_date_at(frame, -10))
    assert result["semantics_version"] == "v1_legacy"
    for field, value in expected.items():
        assert result[field] == value, field
    assert result["start_date"] == _date_at(frame, 0)
    assert result["end_date"] == _date_at(frame, -1)


def test_explicit_empty_parameters_selects_windowed_defaults(frame_factory):
    frame = frame_factory(np.arange(100, 126, dtype=float))
    legacy = run_backtest_request(frame, start_date=_date_at(frame, 20), end_date=_date_at(frame, 24))
    windowed = run_backtest_request(frame, start_date=_date_at(frame, 20), end_date=_date_at(frame, 24), parameters={})
    assert legacy["semantics_version"] == "v1_legacy"
    assert windowed["semantics_version"] == "v2_windowed"
    assert len(legacy["equity_curve"]) == 26
    assert len(windowed["equity_curve"]) == 5
    assert windowed["parameters"]["short_ma"] == 5
    assert windowed["parameters"]["long_ma"] == 20
    assert windowed["parameters"]["initial_cash"] == 100000
    assert windowed["parameters"]["transaction_cost"] == 0.001
    assert windowed["parameters"]["slippage"] == 0


def test_future_rows_cannot_change_completed_orders_or_curve_prefix(frame_factory):
    frame = frame_factory([10, 11, 12, 5, 20, 21, 3, 4, 20], [10, 11, 12, 10, 20, 21, 3, 4, 20])
    earlier = _window(frame.iloc[:6].copy())
    with_unused_future = _window(frame, end_index=5)
    longer = _window(frame)
    for curve in ("equity_curve", "benchmark_curve", "drawdown_curve"):
        assert earlier[curve] == with_unused_future[curve]
        assert earlier[curve] == longer[curve][:3]
    assert earlier["trades"] == with_unused_future["trades"]
    assert earlier["trades"] == [trade for trade in longer["trades"] if trade["execution_date"] <= _date_at(frame, 5)]


def test_windowed_request_preserves_frame_and_parameter_inputs(synthetic_daily_data):
    frame = synthetic_daily_data
    original_frame = frame.copy(deep=True)
    original_attrs = dict(frame.attrs)
    parameters = {"ma_short_period": 3, "ma_long_period": 30, "initial_cash": 2345.0}
    original_parameters = dict(parameters)
    first = run_backtest_request(frame, start_date=_date_at(frame, 130), end_date=_date_at(frame, 160), parameters=parameters)
    second = run_backtest_request(frame, start_date=_date_at(frame, 130), end_date=_date_at(frame, 160), parameters=parameters)
    pd.testing.assert_frame_equal(frame, original_frame)
    assert frame.attrs == original_attrs
    assert parameters == original_parameters
    assert first == second


def test_custom_backtest_does_not_change_default_pipeline_or_ai_projections(synthetic_daily_data):
    from backend.app.services.ai_context_adapter import StockQuantAnalysisAdapter

    frame = synthetic_daily_data
    records = frame.to_dict(orient="records")
    source = SimpleNamespace(
        query_daily=lambda *args, **kwargs: [
            SimpleNamespace(model_dump=lambda record=record: dict(record)) for record in records
        ],
        # PR #10 requires provenance from the same request's market source.
        # These are fixed synthetic test rows, never live-market evidence.
        get_query_provenance=lambda stock_code: {
            "source_mode": "frozen", "provider": "synthetic_c_test_fixture",
        },
    )

    def default_ai_projection():
        # A new adapter prevents its per-request cache from hiding a global mutation.
        adapter = StockQuantAnalysisAdapter(market_data_source=source, stock_service=object())
        return (
            adapter.get_technical_indicators("600519").model_dump(),
            adapter.get_score("600519").model_dump(),
            adapter.get_latest_metrics("600519").model_dump(),
        )

    default_before = analyze_quant_dataframe(frame)
    ai_before = default_ai_projection()
    _window(frame, start_index=130, ma_short_period=7, ma_long_period=40, initial_cash=2345.0, transaction_cost=0.02, slippage=0.03)
    assert analyze_quant_dataframe(frame) == default_before
    assert default_ai_projection() == ai_before
