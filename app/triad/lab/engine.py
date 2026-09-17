"""Deterministic close-decision/next-open engine; trusted fixture strategies only."""

import math
import time
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from triad.lab.contracts import Experiment, LabLimits
from triad.lab.data import digest, encoded


@dataclass(frozen=True)
class Observation:
    timestamp: object
    available_at: object
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class Strategy(Protocol):
    def generate_signal(self, history, direction): ...
    def position_size(self, equity, price, sizing, symbols): ...
    def entry_logic(self, index, parameters): ...
    def exit_logic(self, index, entry_index, parameters): ...
    def risk_logic(self, equity): ...


class FixtureStrategy:
    def __init__(self, parameters, hold=False):
        self.parameters = parameters
        self.hold = hold

    def generate_signal(self, history, direction):
        # The immutable tuple contains past/current closed observations only.
        return direction if self.entry_logic(len(history) - 1, self.parameters) else None

    def position_size(self, equity, price, sizing, symbols):
        budget = equity / symbols
        if sizing.kind == "fixed_shares":
            return min(math.floor(sizing.value), math.floor(budget / price))
        amount = sizing.value if sizing.kind == "fixed_dollars" else budget * sizing.value
        return math.floor(min(amount, budget) / price)

    def entry_logic(self, index, parameters):
        return index == 0 if self.hold else index % parameters["period"] == 0

    def exit_logic(self, index, entry_index, parameters):
        return False if self.hold else index - entry_index + 1 >= parameters["hold"]

    def risk_logic(self, equity):
        return equity > 0


def commission(price, quantity, model):
    return model.fixed + model.per_share * quantity + price * quantity * model.bps / 10000


def summarize(trades, curve, initial):
    equity = np.array([initial] + [p["equity"] for p in curve], dtype=float)
    peaks = np.maximum.accumulate(equity)
    drawdown = equity / peaks - 1
    returns = [t["return"] for t in trades]
    profits = [t["net_pnl"] for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    streak = longest = 0
    for p in profits:
        streak = streak + 1 if p < 0 else 0
        longest = max(longest, streak)
    geometric = (
        math.expm1(sum(math.log1p(r) for r in returns) / len(returns))
        if returns and min(returns) > -1
        else None
    )
    daily = pd.DataFrame(curve)
    daily_returns = (
        daily.groupby(pd.to_datetime(daily.timestamp, utc=True).dt.date)
        .equity.last()
        .pct_change()
        .dropna()
    )
    sufficiently_long = len(daily_returns) >= 20
    annual_vol = float(daily_returns.std(ddof=1) * math.sqrt(252)) if sufficiently_long else None
    downside = (
        math.sqrt(float(np.mean(np.minimum(daily_returns, 0) ** 2))) * math.sqrt(252)
        if sufficiently_long
        else None
    )
    duration = (
        pd.Timestamp(curve[-1]["timestamp"]) - pd.Timestamp(curve[0]["timestamp"])
    ).total_seconds() / 86400
    cagr = (
        (equity[-1] / initial) ** (365.25 / duration) - 1
        if duration >= 365 and equity[-1] > 0
        else None
    )
    return {
        "net_return": equity[-1] / initial - 1,
        "cagr": cagr,
        "geometric_mean_trade_return": geometric,
        "arithmetic_average_trade_return": float(np.mean(returns)) if returns else None,
        "max_drawdown": float(-min(drawdown)),
        "volatility": annual_vol,
        "sharpe": float(daily_returns.mean() * 252 / annual_vol) if annual_vol else None,
        "sortino": float(daily_returns.mean() * 252 / downside) if downside else None,
        "calmar": cagr / (-min(drawdown)) if cagr is not None and min(drawdown) < 0 else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "expectancy": float(np.mean(profits)) if profits else None,
        "win_rate": len(wins) / len(profits) if profits else None,
        "average_win": float(np.mean(wins)) if wins else None,
        "average_loss": float(np.mean(losses)) if losses else None,
        "trade_count": len(trades),
        "turnover": sum((t["entry_price"] + t["exit_price"]) * t["quantity"] for t in trades)
        / initial,
        "exposure": float(
            np.mean([p["gross_exposure"] / p["equity"] if p["equity"] > 0 else 0 for p in curve])
        ),
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "maximum_consecutive_losses": longest,
        "mae": float(np.mean([t["mae"] for t in trades])) if trades else None,
        "mfe": float(np.mean([t["mfe"] for t in trades])) if trades else None,
        "holding_minutes": float(np.mean([t["holding_period_minutes"] for t in trades]))
        if trades
        else None,
        "time_to_profit_minutes": [t["time_to_profit_minutes"] for t in trades],
        "time_to_failure_minutes": [t["time_to_failure_minutes"] for t in trades],
        "cost_sensitivity": {
            "fees": sum(t["fees"] for t in trades),
            "slippage_and_half_spread": sum(t["slippage"] for t in trades),
            "extra_1bp_each_side_pnl_drag": sum(
                (t["entry_price"] + t["exit_price"]) * t["quantity"] for t in trades
            )
            / 10000,
            "method": "fixed fills/quantity sensitivity, not an optimized rerun",
        },
        "undefined_metric_policy": "null for zero denominators, no trades, CAGR under one year, annualized ratios under 20 daily returns; no risk-free rate assumption beyond zero",
    }


def run_engine(frame, experiment: Experiment, limits=None, guard=lambda: None, strategy=None):
    limits = limits or LabLimits()
    started = time.monotonic()
    if (
        len(frame) > limits.max_rows
        or frame.memory_usage(deep=True).sum() > limits.memory_mb * 1024 * 1024 / 4
    ):
        raise ValueError("Backtest data resource ceiling")
    if (
        not frame.timestamp.is_monotonic_increasing
        or frame.duplicated(["timestamp", "symbol"]).any()
    ):
        raise ValueError("Ordered unique canonical bars required")
    if "partial_dataset_bucket" in frame and frame.partial_dataset_bucket.any():
        raise ValueError("Incomplete derived bucket cannot enter a backtest")
    window = next(p for p in experiment.partitions if p.name == experiment.selected_partition)
    frame = frame[
        (frame.timestamp >= window.start)
        & (frame.bar_end <= window.end)
        & frame.symbol.isin(experiment.symbols)
    ]
    if len(frame) < 3 or set(frame.symbol) != set(experiment.symbols):
        raise ValueError("Selected window lacks required symbols/bars")
    strategy = strategy or FixtureStrategy(
        experiment.parameters, experiment.strategy_version == "hold-fixture-v1"
    )
    all_trades, all_equity, decisions, metrics = [], [], [], {}
    for direction in experiment.directions:
        sign = 1 if direction == "LONG" else -1
        cash = experiment.initial_capital
        histories = {s: [] for s in experiment.symbols}
        positions, pending, last, indexes = {}, {}, {}, {s: 0 for s in experiment.symbols}
        trades, curve = [], []
        grouped = list(frame.groupby("timestamp", sort=False))
        last_times = frame.groupby("symbol").timestamp.max().to_dict()
        peak = previous_equity = experiment.initial_capital
        for n, (timestamp, bars) in enumerate(grouped):
            if n % 20 == 0:
                guard()
                if time.monotonic() - started > limits.runtime_seconds:
                    raise TimeoutError("Backtest runtime ceiling")
            rows = bars.to_dict("records")
            for row in rows:
                symbol = row["symbol"]
                final = timestamp == last_times[symbol]
                action = pending.pop(symbol, None)
                if final:
                    action = (
                        {
                            "action": "EXIT",
                            "signal_time": positions[symbol]["signal_time"],
                            "reason": "predeclared end-window liquidation at final open",
                        }
                        if symbol in positions
                        else None
                    )
                if action and action["action"] == "EXIT" and symbol in positions:
                    p = positions.pop(symbol)
                    fill = row["open"] * (
                        1
                        - sign
                        * (experiment.slippage_model.bps + experiment.slippage_model.spread_bps / 2)
                        / 10000
                    )
                    fee = commission(fill, p["quantity"], experiment.fees_model)
                    cash += sign * p["quantity"] * fill - fee
                    gross = sign * p["quantity"] * (row["open"] - p["raw_entry"])
                    slip = abs(fill - row["open"]) * p["quantity"] + p["entry_slippage"]
                    net = gross - slip - fee - p["entry_fee"]
                    trades.append(
                        {
                            "trade_id": f"{direction}-{len(trades) + 1}",
                            "symbol": symbol,
                            "direction": direction,
                            "signal_time": p["signal_time"],
                            "entry_time": p["entry_time"],
                            "entry_price": p["fill"],
                            "exit_signal_time": action["signal_time"],
                            "exit_time": timestamp,
                            "exit_price": fill,
                            "quantity": p["quantity"],
                            "gross_pnl": gross,
                            "fees": fee + p["entry_fee"],
                            "slippage": slip,
                            "net_pnl": net,
                            "return": net / (p["quantity"] * p["fill"]),
                            "mae": p["mae"],
                            "mfe": p["mfe"],
                            "holding_period_minutes": (timestamp - p["entry_time"]).total_seconds()
                            / 60,
                            "time_to_profit_minutes": p["ttp"],
                            "time_to_failure_minutes": p["ttf"],
                            "entry_reason": "fixture signal using closed-bar history",
                            "exit_reason": action["reason"],
                        }
                    )
                elif (
                    action and action["action"] == "ENTER" and symbol not in positions and not final
                ):
                    fill = row["open"] * (
                        1
                        + sign
                        * (experiment.slippage_model.bps + experiment.slippage_model.spread_bps / 2)
                        / 10000
                    )
                    quantity = strategy.position_size(
                        previous_equity,
                        fill,
                        experiment.position_sizing_model,
                        len(experiment.symbols),
                    )
                    fee = commission(fill, quantity, experiment.fees_model)
                    # No leverage: reserve notional and both-side commission headroom.
                    allocated = sum(p["quantity"] * p["fill"] for p in positions.values())
                    if (
                        quantity > 0
                        and quantity * fill + 2 * fee <= previous_equity - allocated
                        and strategy.risk_logic(previous_equity)
                    ):
                        cash -= sign * quantity * fill + fee
                        positions[symbol] = {
                            "quantity": quantity,
                            "fill": fill,
                            "raw_entry": row["open"],
                            "entry_time": timestamp,
                            "signal_time": action["signal_time"],
                            "entry_index": indexes[symbol],
                            "entry_fee": fee,
                            "entry_slippage": abs(fill - row["open"]) * quantity,
                            "mae": 0.0,
                            "mfe": 0.0,
                            "ttp": None,
                            "ttf": None,
                        }
                last[symbol] = row["close"]
                history = histories[symbol]
                history.append(
                    Observation(
                        timestamp,
                        row["bar_end"],
                        symbol,
                        row["open"],
                        row["high"],
                        row["low"],
                        row["close"],
                        row["volume"],
                    )
                )
                if symbol in positions:
                    p = positions[symbol]
                    adverse = (
                        (row["low"] / p["fill"] - 1) if sign == 1 else (1 - row["high"] / p["fill"])
                    )
                    favorable = (
                        (row["high"] / p["fill"] - 1) if sign == 1 else (1 - row["low"] / p["fill"])
                    )
                    p["mae"], p["mfe"] = min(p["mae"], adverse), max(p["mfe"], favorable)
                    pnl = sign * (row["close"] - p["fill"]) * p["quantity"] - p["entry_fee"]
                    elapsed = (row["bar_end"] - p["entry_time"]).total_seconds() / 60
                    if pnl > 0 and p["ttp"] is None:
                        p["ttp"] = elapsed
                    if pnl < 0 and p["ttf"] is None:
                        p["ttf"] = elapsed
                    if strategy.exit_logic(
                        indexes[symbol], p["entry_index"], experiment.parameters
                    ):
                        pending[symbol] = {
                            "action": "EXIT",
                            "signal_time": row["bar_end"],
                            "reason": "fixture hold duration elapsed",
                        }
                elif not final and strategy.generate_signal(tuple(history), direction):
                    pending[symbol] = {
                        "action": "ENTER",
                        "signal_time": row["bar_end"],
                        "reason": "fixture periodic entry",
                    }
                if symbol in pending:
                    decisions.append(
                        {
                            "direction": direction,
                            "symbol": symbol,
                            "decision_time": row["bar_end"],
                            "information_through": row["bar_end"],
                            "history_hash": digest(encoded([o.__dict__ for o in history])),
                            "rule": experiment.strategy_version,
                            **pending[symbol],
                            "quality_assessment": "NOT_INFERRED_FROM_OUTCOME",
                        }
                    )
                indexes[symbol] += 1
            net_exposure = sum(sign * p["quantity"] * last[s] for s, p in positions.items())
            equity = cash + net_exposure
            if equity <= 0:
                raise ValueError("Portfolio insolvency; no continued compounding")
            peak = max(peak, equity)
            curve.append(
                {
                    "timestamp": max(r["bar_end"] for r in rows),
                    "direction": direction,
                    "equity": equity,
                    "cash": cash,
                    "gross_exposure": sum(
                        abs(p["quantity"] * last[s]) for s, p in positions.items()
                    ),
                    "net_exposure": net_exposure,
                    "drawdown": equity / peak - 1,
                    "log_return": math.log(equity / previous_equity),
                }
            )
            previous_equity = equity
        if positions:
            raise ValueError("Unclosed terminal positions")
        metrics[direction] = summarize(trades, curve, experiment.initial_capital)
        all_trades.extend(trades)
        all_equity.extend(curve)
    output = {
        "trades": all_trades,
        "equity": all_equity,
        "decisions": decisions,
        "metrics": metrics,
    }
    output["content_hash"] = digest(encoded(output))
    return output


def sequence_analysis(returns):
    """Order changes drawdown/loss clustering, not the product for fixed percentage returns."""
    equity = peak = 1.0
    drawdown = 0.0
    for value in returns:
        if not math.isfinite(value) or value <= -1:
            raise ValueError("Invalid compound return")
        equity *= 1 + value
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
    return {"compound_return": equity - 1, "max_drawdown": drawdown, "sequence": list(returns)}
