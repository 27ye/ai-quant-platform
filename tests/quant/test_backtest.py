import numpy as np
import pytest

from backend.app.quant.backtest import run_backtest
from backend.app.quant.metrics import calculate_max_drawdown, calculate_sharpe_ratio
from backend.app.quant.strategy import generate_ma_target_signals


def _gap_frame(frame_factory):
    closes = np.concatenate([np.full(20, 100.0), np.linspace(101.0, 130.0, 40)])
    frame = frame_factory(closes)
    signals = generate_ma_target_signals(frame)
    signal_index = int(signals.index[signals["target_position"] == 1][0])
    execution_index = signal_index + 1
    frame.loc[execution_index, "open"] = 175.0
    frame.loc[execution_index, "high"] = 176.0
    frame.loc[execution_index, "low"] = min(
        frame.loc[execution_index, "close"], 175.0
    ) * 0.99
    return frame, signal_index, execution_index


def test_signal_executes_only_at_next_day_open(frame_factory):
    frame, signal_index, execution_index = _gap_frame(frame_factory)
    result = run_backtest(frame, {"transaction_cost": 0.0})
    buy = result["trades"][0]
    assert buy["signal_date"] == frame.loc[signal_index, "trade_date"].strftime("%Y-%m-%d")
    assert buy["execution_date"] == frame.loc[execution_index, "trade_date"].strftime(
        "%Y-%m-%d"
    )


def test_open_gap_uses_t_plus_one_open_price(frame_factory):
    frame, _, _ = _gap_frame(frame_factory)
    result = run_backtest(frame, {"transaction_cost": 0.0})
    assert result["trades"][0]["execution_price"] == pytest.approx(175.0)


def test_buy_and_sell_fees_are_deducted_once(frame_factory):
    closes = np.concatenate(
        [np.full(20, 100.0), np.linspace(101.0, 120.0, 12), np.linspace(80.0, 70.0, 35)]
    )
    result = run_backtest(
        frame_factory(closes),
        {"initial_cash": 1000.0, "transaction_cost": 0.01, "slippage": 0.0},
    )
    assert result["trade_count"] == 1
    assert result["order_count"] == 2
    buy, sell = result["trades"]
    expected_final = 1000.0 + sell["round_trip_pnl"]
    assert result["final_equity"] == pytest.approx(expected_final)
    assert buy["fee"] == pytest.approx(buy["gross_amount"] * 0.01)
    assert sell["fee"] == pytest.approx(sell["gross_amount"] * 0.01)


def test_no_completed_round_trip_has_none_win_rate(frame_factory):
    result = run_backtest(frame_factory(np.linspace(100.0, 160.0, 80)))
    assert result["current_position"] == 1
    assert result["trade_count"] == 0
    assert result["order_count"] == 1
    assert result["win_rate"] is None


def test_last_open_position_is_marked_at_last_close(frame_factory):
    frame = frame_factory(np.linspace(100.0, 160.0, 80))
    result = run_backtest(frame, {"initial_cash": 1000.0, "transaction_cost": 0.0})
    buy = result["trades"][0]
    expected = buy["shares"] * float(frame.iloc[-1]["close"])
    assert result["final_equity"] == pytest.approx(expected)


def test_known_max_drawdown_is_negative_decimal():
    assert calculate_max_drawdown([100.0, 120.0, 90.0, 108.0]) == pytest.approx(-0.25)


def test_zero_volatility_returns_have_no_sharpe():
    assert calculate_sharpe_ratio([0.01, 0.01, 0.01]) is None
