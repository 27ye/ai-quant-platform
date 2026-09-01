"""Event-style MA5/MA20 backtest with strict T-close/T+1-open execution."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.app.quant.config import ConfigInput, resolve_config
from backend.app.quant.metrics import calculate_max_drawdown, calculate_sharpe_ratio
from backend.app.quant.strategy import generate_ma_target_signals
from backend.app.quant.validators import InsufficientDataError, validate_stock_dataframe


def run_backtest(data: pd.DataFrame, config: ConfigInput = None) -> Dict[str, Any]:
    """Run the long-only strategy without using a same-day close signal."""

    settings = resolve_config(config)
    minimum_rows = settings.ma_long_period + 1
    validated = validate_stock_dataframe(data, min_rows=minimum_rows)
    signals = generate_ma_target_signals(validated, settings)

    cash = float(settings.initial_cash)
    shares = 0.0
    entry_total_cost: Optional[float] = None
    completed_round_trip_pnls: List[float] = []
    trades: List[Dict[str, Any]] = []
    equity_values: List[float] = []
    benchmark_values: List[float] = []
    curve_dates: List[str] = []
    benchmark_base_close = float(signals.iloc[0]["close"])

    for index, row in signals.iterrows():
        if index > 0:
            signal_row = signals.iloc[index - 1]
            desired_position = int(signal_row["target_position"])
            signal_date = _date_text(signal_row["trade_date"])
            execution_date = _date_text(row["trade_date"])
            if desired_position == 1 and shares == 0:
                execution_price = float(row["open"]) * (1.0 + settings.slippage)
                quantity = _buy_quantity(cash, execution_price, settings)
                if quantity > 0:
                    gross_amount = quantity * execution_price
                    fee = gross_amount * settings.transaction_cost
                    total_cost = gross_amount + fee
                    cash -= total_cost
                    if cash < -1e-8:
                        raise RuntimeError("buy execution produced negative cash")
                    cash = max(cash, 0.0)
                    shares = quantity
                    entry_total_cost = total_cost
                    trades.append(
                        _trade_record(
                            order_id=len(trades) + 1,
                            signal_date=signal_date,
                            execution_date=execution_date,
                            side="buy",
                            execution_price=execution_price,
                            shares=quantity,
                            gross_amount=gross_amount,
                            fee=fee,
                            cash_after=cash,
                            position_after=1,
                            round_trip_pnl=None,
                            round_trip_return=None,
                        )
                    )
            elif desired_position == 0 and shares > 0:
                execution_price = float(row["open"]) * (1.0 - settings.slippage)
                quantity = shares
                gross_amount = quantity * execution_price
                fee = gross_amount * settings.transaction_cost
                net_proceeds = gross_amount - fee
                cash += net_proceeds
                if entry_total_cost is None:
                    raise RuntimeError("sell execution is missing its buy cost basis")
                round_trip_pnl = net_proceeds - entry_total_cost
                round_trip_return = round_trip_pnl / entry_total_cost
                completed_round_trip_pnls.append(round_trip_pnl)
                shares = 0.0
                entry_total_cost = None
                trades.append(
                    _trade_record(
                        order_id=len(trades) + 1,
                        signal_date=signal_date,
                        execution_date=execution_date,
                        side="sell",
                        execution_price=execution_price,
                        shares=quantity,
                        gross_amount=gross_amount,
                        fee=fee,
                        cash_after=cash,
                        position_after=0,
                        round_trip_pnl=round_trip_pnl,
                        round_trip_return=round_trip_return,
                    )
                )

        close_price = float(row["close"])
        equity = cash + shares * close_price
        if not math.isfinite(equity) or equity <= 0:
            raise RuntimeError("backtest equity must remain finite and positive")
        trade_date = _date_text(row["trade_date"])
        curve_dates.append(trade_date)
        equity_values.append(equity)
        benchmark_values.append(
            settings.initial_cash * close_price / benchmark_base_close
        )

    equity_series = pd.Series(equity_values, dtype=float)
    daily_returns = equity_series.pct_change().dropna()
    drawdowns = equity_series / equity_series.cummax() - 1.0
    final_equity = float(equity_values[-1])
    total_return = final_equity / settings.initial_cash - 1.0
    effective_trading_days = max(len(equity_values) - 1, 1)
    annual_return = (
        (final_equity / settings.initial_cash)
        ** (settings.annualization_days / effective_trading_days)
        - 1.0
    )
    trade_count = len(completed_round_trip_pnls)
    win_rate = (
        sum(pnl > 0 for pnl in completed_round_trip_pnls) / trade_count
        if trade_count
        else None
    )

    return {
        "strategy_name": settings.strategy_name,
        "start_date": curve_dates[0],
        "end_date": curve_dates[-1],
        "initial_cash": float(settings.initial_cash),
        "final_equity": final_equity,
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": calculate_max_drawdown(equity_values),
        "sharpe_ratio": calculate_sharpe_ratio(
            daily_returns,
            annualization_days=settings.annualization_days,
            risk_free_rate=settings.risk_free_rate,
        ),
        "win_rate": win_rate,
        "trade_count": trade_count,
        "order_count": len(trades),
        "benchmark_return": benchmark_values[-1] / settings.initial_cash - 1.0,
        "current_position": 1 if shares > 0 else 0,
        "parameters": {
            "contract_status": settings.contract_status,
            "short_ma": settings.ma_short_period,
            "long_ma": settings.ma_long_period,
            "initial_cash": float(settings.initial_cash),
            "transaction_cost": float(settings.transaction_cost),
            "slippage": float(settings.slippage),
            "allow_fractional_shares": settings.allow_fractional_shares,
            "risk_free_rate": float(settings.risk_free_rate),
            "annualization_days": settings.annualization_days,
            "benchmark_method": settings.benchmark_method,
            "effective_trading_days": effective_trading_days,
        },
        "equity_curve": [
            {"trade_date": date, "equity": float(value)}
            for date, value in zip(curve_dates, equity_values)
        ],
        "benchmark_curve": [
            {"trade_date": date, "benchmark_equity": float(value)}
            for date, value in zip(curve_dates, benchmark_values)
        ],
        "drawdown_curve": [
            {"trade_date": date, "drawdown": float(value)}
            for date, value in zip(curve_dates, drawdowns)
        ],
        "trades": trades,
    }


def _buy_quantity(cash: float, execution_price: float, settings: Any) -> float:
    affordable = cash / (execution_price * (1.0 + settings.transaction_cost))
    if settings.allow_fractional_shares:
        return float(affordable)
    return float(math.floor(affordable))


def _trade_record(
    order_id: int,
    signal_date: str,
    execution_date: str,
    side: str,
    execution_price: float,
    shares: float,
    gross_amount: float,
    fee: float,
    cash_after: float,
    position_after: int,
    round_trip_pnl: Optional[float],
    round_trip_return: Optional[float],
) -> Dict[str, Any]:
    return {
        "order_id": order_id,
        "signal_date": signal_date,
        "execution_date": execution_date,
        "side": side,
        "execution_price": float(execution_price),
        "shares": float(shares),
        "gross_amount": float(gross_amount),
        "fee": float(fee),
        "cash_after": float(cash_after),
        "position_after": position_after,
        "round_trip_pnl": None if round_trip_pnl is None else float(round_trip_pnl),
        "round_trip_return": (
            None if round_trip_return is None else float(round_trip_return)
        ),
    }


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")
