"""V3 MACD contract, independent rational oracle and execution regressions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from fractions import Fraction
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from backend.app.quant import (
    PARAMETERS_UNSET, STRATEGY_UNSET, BacktestParameterError,
    MacdBacktestParameters, analyze_quant_dataframe,
    resolve_backtest_request, run_backtest_request,
)
from backend.app.quant.backtest_config import BacktestParameters, BacktestRequestConfig
from backend.app.quant.strategy import generate_macd_target_signals
from backend.app.quant.validators import InsufficientDataError


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def macd_run(frame, params=None, start=4, end=None):
    return run_backtest_request(
        frame, strategy="macd", parameters=params if params is not None else {
            "macd_fast_period": 2, "macd_slow_period": 3, "macd_signal_period": 2,
            "initial_cash": 1000, "transaction_cost": 0, "slippage": 0,
        },
        start_date=frame.iloc[start].trade_date.strftime("%Y-%m-%d"),
        end_date=frame.iloc[-1 if end is None else end].trade_date.strftime("%Y-%m-%d"),
    )


@pytest.mark.parametrize("strategy", [STRATEGY_UNSET, "ma_cross"])
@pytest.mark.parametrize("parameters,version", [(PARAMETERS_UNSET, "v1_legacy"), ({}, "v2_windowed")])
def test_old_request_matrix(strategy, parameters, version):
    assert resolve_backtest_request(parameters, strategy=strategy).semantics_version == version


@pytest.mark.parametrize("parameters", [PARAMETERS_UNSET, {}])
def test_macd_omitted_and_empty_resolve_same_windowed_defaults(parameters):
    request = resolve_backtest_request(parameters, strategy="macd")
    assert request == BacktestRequestConfig("v2_windowed", MacdBacktestParameters(), "macd")
    assert request.required_warmup_rows == 34
    assert request.parameters.to_parameters() == {
        "macd_fast_period": 12, "macd_slow_period": 26, "macd_signal_period": 9,
        "initial_cash": 100000.0, "transaction_cost": 0.001, "slippage": 0.0,
    }


@pytest.mark.parametrize("strategy", [None, "MACD", "", "unknown", False, 1, {}, []])
def test_invalid_strategy_rejected_before_frame_access(strategy):
    with pytest.raises(BacktestParameterError, match="strategy"):
        run_backtest_request(object(), strategy=strategy)


@pytest.mark.parametrize("strategy", [STRATEGY_UNSET, "ma_cross", "macd"])
@pytest.mark.parametrize("parameters", [None, [], False, "{}", 1])
def test_bad_parameter_container_rejected_before_data(strategy, parameters):
    with pytest.raises(BacktestParameterError):
        run_backtest_request(object(), parameters=parameters, strategy=strategy)


@pytest.mark.parametrize("field", ["macd_fast_period", "macd_slow_period", "macd_signal_period"])
@pytest.mark.parametrize("value", [None, True, False, "12", 12.0, float("nan"), float("inf")])
def test_macd_periods_are_strict(field, value):
    with pytest.raises(BacktestParameterError):
        resolve_backtest_request({field: value}, strategy="macd")


@pytest.mark.parametrize("fast,slow,signal", [(1, 26, 9), (26, 26, 9), (27, 26, 9), (2, 121, 9), (12, 26, 1), (12, 26, 121)])
def test_macd_period_bounds(fast, slow, signal):
    with pytest.raises(BacktestParameterError):
        MacdBacktestParameters(fast, slow, signal)


@pytest.mark.parametrize("field", ["initial_cash", "transaction_cost", "slippage"])
@pytest.mark.parametrize("value", [None, True, "0.001", float("nan"), float("inf"), -float("inf"), 10**400, -1])
def test_financial_values_strict_and_finite(field, value):
    with pytest.raises(BacktestParameterError):
        resolve_backtest_request({field: value}, strategy="macd")


@pytest.mark.parametrize("payload", [{"initial_cash": 0}, {"transaction_cost": 1}, {"slippage": 1}, {"ma_short_period": 5}, {"ma_long_period": 20}, {"risk_free_rate": 0}, {1: 5}])
def test_macd_whitelist_and_exclusive_financial_bounds(payload):
    with pytest.raises(BacktestParameterError):
        run_backtest_request(object(), parameters=payload, strategy="macd")


@pytest.mark.parametrize("field", ["macd_fast_period", "macd_slow_period", "macd_signal_period"])
def test_ma_cannot_accept_macd_fields(field):
    with pytest.raises(BacktestParameterError):
        resolve_backtest_request({field: 12}, strategy="ma_cross")


@pytest.mark.parametrize("args", [("v1_legacy", MacdBacktestParameters(), "macd"), ("v2_windowed", BacktestParameters(), "macd"), ("v2_windowed", MacdBacktestParameters(), "ma_cross")])
def test_direct_constructor_cannot_bypass_strategy_type_or_semantics(args):
    with pytest.raises(BacktestParameterError):
        BacktestRequestConfig(*args)


@pytest.mark.parametrize("start,end", [(None, None), ("2025-01-01", None), (None, "2025-01-01"), ("2025-02-02", "2025-01-01"), ("2025-02-30", "2025-03-01"), ("2020-02-29", "2025-03-01"), ("2025/01/01", "2025-02-01")])
def test_macd_requires_valid_explicit_window_before_frame_access(start, end):
    with pytest.raises(BacktestParameterError):
        run_backtest_request(object(), strategy="macd", start_date=start, end_date=end)


@pytest.mark.parametrize("fast,slow,signal", [(2, 3, 2), (12, 26, 9), (119, 120, 120)])
def test_exact_warmup_boundary_no_hidden_ma_requirement(frame_factory, fast, slow, signal):
    n = slow + signal - 1
    params = dict(macd_fast_period=fast, macd_slow_period=slow, macd_signal_period=signal)
    frame = frame_factory([10] * (n + 1))
    result = macd_run(frame, params, start=n)
    assert result["warmup"]["used_rows"] == n
    assert len(result["equity_curve"]) == 1
    assert len(result["input_snapshot"]["rows"]) == n + 1
    with pytest.raises(InsufficientDataError, match=f"{n} valid warmup"):
        macd_run(frame, params, start=n - 1)


def rational_signals(closes, fast, slow, signal):
    """Independent exact arithmetic oracle: no pandas or production indicator calls."""
    f = s = Fraction(str(closes[0]))
    dea = Fraction(0)
    rows = []
    for i, close in enumerate(closes):
        if i:
            f += Fraction(2, fast + 1) * (Fraction(str(close)) - f)
            s += Fraction(2, slow + 1) * (Fraction(str(close)) - s)
        dif = f - s
        if i:
            dea += Fraction(2, signal + 1) * (dif - dea)
        rows.append((dif, dea, 2 * (dif - dea), int(i >= slow + signal - 2 and dif > dea)))
    return rows


@pytest.mark.parametrize("periods", [(2, 3, 2), (12, 26, 9), (6, 13, 5)])
def test_indicators_against_independent_rational_recursion(frame_factory, periods):
    closes = [10 + i % 7 for i in range(80)]
    params = MacdBacktestParameters(*periods)
    result = generate_macd_target_signals(frame_factory(closes), params)
    expected = rational_signals(closes, *periods)
    for column, offset in [("macd", 0), ("macd_signal", 1), ("macd_hist", 2)]:
        assert result[column].tolist() == pytest.approx([float(row[offset]) for row in expected], abs=1e-12)
    assert result.target_position.tolist() == [row[3] for row in expected]


def test_hand_calculated_signals_costs_and_complete_round_trip(frame_factory):
    frame = frame_factory([10, 11, 12, 13, 5, 20], [10, 11, 12, 13, 10, 20])
    params = dict(macd_fast_period=2, macd_slow_period=3, macd_signal_period=2,
                  initial_cash=1020.10, transaction_cost=0.01, slippage=0.01)
    result = macd_run(frame, params)
    buy, sell = result["trades"]
    assert buy["execution_price"] == pytest.approx(10.1)
    assert buy["shares"] == pytest.approx(100)
    assert buy["fee"] == pytest.approx(10.1)
    assert sell["execution_price"] == pytest.approx(19.8)
    assert sell["fee"] == pytest.approx(19.8)
    assert sell["round_trip_pnl"] == pytest.approx(940.1)
    assert result["final_equity"] == pytest.approx(1960.2)
    assert [x["equity"] for x in result["equity_curve"]] == pytest.approx([500, 1960.2])
    assert [x["benchmark_equity"] for x in result["benchmark_curve"]] == pytest.approx([510.05, 2040.2])
    assert (result["order_count"], result["trade_count"], result["win_rate"]) == (2, 1, 1.0)
    assert result["max_drawdown"] == pytest.approx(500 / 1020.1 - 1)
    assert buy["signal_date"] == frame.iloc[3].trade_date.strftime("%Y-%m-%d")
    assert buy["execution_date"] == result["start_date"]
    assert sell["signal_date"] == buy["execution_date"]
    assert sell["execution_date"] == result["end_date"]
    assert "short_ma" not in result["parameters"]
    assert set(result["effective_parameters"]) == set(params)


def test_equal_signals_no_trades_null_metrics(frame_factory):
    result = macd_run(frame_factory([10] * 10))
    assert result["trades"] == []
    assert result["order_count"] == result["trade_count"] == 0
    assert result["win_rate"] is None and result["sharpe_ratio"] is None
    assert result["total_return"] == result["annual_return"] == result["max_drawdown"] == 0


def test_last_window_signal_is_not_executed_and_position_not_forced_closed(frame_factory):
    frame = frame_factory([10, 11, 12, 13, 5], [10, 11, 12, 13, 10])
    result = macd_run(frame)
    assert result["order_count"] == 1 and result["trade_count"] == 0
    assert result["current_position"] == 1
    assert result["final_equity"] == pytest.approx(500)
    assert result["win_rate"] is None
    assert result["sharpe_ratio"] is None


def test_no_lookahead_prefix_and_unused_earlier_data_do_not_change_result(frame_factory):
    frame = frame_factory([10, 11, 12, 13, 5, 20, 2, 40, 3, 30])
    short = macd_run(frame.iloc[:6].copy(), end=5)
    extended = macd_run(frame, end=5)
    assert canonical(short) == canonical(extended)
    long_result = macd_run(frame)
    for key in ("equity_curve", "benchmark_curve", "drawdown_curve"):
        assert long_result[key][:2] == short[key]
    assert long_result["trades"][:2] == short["trades"]
    # Moving the seed earlier would change all recursive MACD values: prove trimming.
    with_extra = pd.concat([frame.iloc[:1].assign(trade_date=pd.Timestamp("2023-12-29"),
        open=999., high=999., low=999., close=999.), frame], ignore_index=True)
    with_extra.attrs = dict(frame.attrs)
    assert canonical(macd_run(with_extra, start=5, end=6)) == canonical(short)


def test_hash_covers_only_consumed_input_and_replay_is_exact(frame_factory):
    frame = frame_factory([10, 11, 12, 13, 5, 20])
    result = macd_run(frame)
    snapshot = dict(result["input_snapshot"])
    claimed = snapshot.pop("sha256")
    assert claimed == result["data_hash"] == hashlib.sha256(canonical(snapshot).encode()).hexdigest()
    replay = pd.DataFrame(snapshot["rows"])
    replay.attrs["data_mode"] = snapshot["data_mode"]
    repeated = run_backtest_request(replay, strategy="macd", parameters=result["effective_parameters"],
        start_date=result["requested_start_date"], end_date=result["requested_end_date"])
    assert canonical(repeated) == canonical(result)
    altered = frame.copy()
    altered.loc[0, "volume"] += 1
    assert macd_run(altered)["data_hash"] != result["data_hash"]


def test_request_isolation_under_interleaved_calls(synthetic_daily_data):
    frame = synthetic_daily_data
    before = frame.copy(deep=True)
    default_before = canonical(analyze_quant_dataframe(frame))
    configs = [{}, {"macd_fast_period": 6, "macd_slow_period": 13, "macd_signal_period": 5},
               {"macd_fast_period": 20, "macd_slow_period": 40, "macd_signal_period": 12, "initial_cash": 250000}]
    def execute(params):
        return canonical(macd_run(frame, params, start=120))
    expected = [execute(x) for x in configs]
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(execute, configs * 2)) == expected * 2
    pd.testing.assert_frame_equal(frame, before)
    assert canonical(analyze_quant_dataframe(frame)) == default_before
    parameters = MacdBacktestParameters()
    with pytest.raises(FrozenInstanceError):
        parameters.initial_cash = 1


def test_all_pre_v3_results_equal_captured_main_baseline():
    """Full JSON baseline captured before edits at main 26f422a (not same-code oracle)."""
    root = Path(__file__).resolve().parents[2] / "docs/evidence/c-delivery-20260917"
    results = {}
    for code in ("600519", "000001", "300750"):
        frame = pd.DataFrame(json.loads(next(root.glob(code + "*normalized*.json")).read_text(encoding="utf-8")))
        frame.attrs["data_mode"] = "c_delivery_20260917_normalized"
        results[code] = {"default_pipeline": analyze_quant_dataframe(frame), "legacy": run_backtest_request(frame)}
        assert canonical(run_backtest_request(frame, strategy="ma_cross")) == canonical(results[code]["legacy"])
        for name, params in [("default", {}), ("10_30", {"ma_short_period": 10, "ma_long_period": 30}),
            ("20_60_cost", {"ma_short_period": 20, "ma_long_period": 60, "initial_cash": 200000, "transaction_cost": 0.002, "slippage": 0.001})]:
            result = run_backtest_request(frame, start_date="2025-07-04", end_date="2026-08-31", parameters=params)
            results[code][name] = result
            assert canonical(run_backtest_request(frame, strategy="ma_cross", start_date="2025-07-04", end_date="2026-08-31", parameters=params)) == canonical(result)
    # 3 default pipelines + 3 legacy backtests + 9 windowed MA results, all fields/types.
    assert hashlib.sha256(canonical(results).encode()).hexdigest() == "7f2cb64ed9d82527978a6f8b088b6249a82d3afa25c4a83adf0132ba99f96095"
