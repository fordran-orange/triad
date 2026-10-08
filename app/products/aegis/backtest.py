"""Deterministic Aegis backtester for product strategies.

Signals are computed from closed bars and filled on the next bar open. Long, short,
and combined results are simulated independently so directional edge is never hidden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from products.aegis.strategy import StrategySpec


class EventPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    timestamp: datetime
    symbol: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str | None = None

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must be timezone-aware")
        return value


class BacktestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_capital: float = Field(default=100_000, gt=0)
    allocation_fraction: float = Field(default=1.0, gt=0, le=1)


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategySpec
    bars: list[dict]
    events: list[EventPoint] = Field(default_factory=list)
    settings: BacktestSettings = Field(default_factory=BacktestSettings)


@dataclass(frozen=True)
class Signal:
    timestamp: pd.Timestamp
    bar_index: int
    side: str
    action: str
    tags: tuple[str, ...]


def _prepare_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows).copy()
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing required fields: {sorted(missing)}")
    if len(frame) < 35:
        raise ValueError("at least 35 bars are required for the 30-period reference strategy")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if frame.timestamp.duplicated().any():
        raise ValueError("duplicate timestamps are not allowed")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    if (
        (frame[["open", "high", "low", "close"]] <= 0).any().any()
        or (frame["volume"] < 0).any()
        or (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise ValueError("invalid OHLCV data")
    return frame


def _indicator_lengths(strategy: StrategySpec) -> tuple[int, int]:
    ema = next((i for i in strategy.indicators if i.kind.upper() == "EMA"), None)
    sma = next((i for i in strategy.indicators if i.kind.upper() == "SMA"), None)
    if not ema or not sma:
        raise ValueError("reference backtester requires one EMA and one SMA")
    return ema.length, sma.length


def _clock_tags(timestamp: pd.Timestamp, strategy: StrategySpec) -> list[str]:
    local = timestamp.tz_convert(ZoneInfo(strategy.temporal.timezone))
    hhmm = local.strftime("%H:%M")
    tags = []
    for window in strategy.temporal.clock_windows:
        if window.start <= hhmm < window.end:
            tags.append(f"CLOCK:{window.id}")
    return tags


def _event_tags(
    timestamp: pd.Timestamp, strategy: StrategySpec, events: list[EventPoint], symbol: str | None
) -> list[str]:
    tags = []
    instant = timestamp.to_pydatetime()
    for config in strategy.temporal.event_windows:
        if not config.enabled:
            continue
        for event in events:
            if event.event_type != config.event_type:
                continue
            if event.symbol and symbol and event.symbol != symbol:
                continue
            delta_minutes = (instant - event.timestamp).total_seconds() / 60
            if -config.minutes_before <= delta_minutes <= config.minutes_after:
                tags.append(f"EVENT:{config.event_type}")
                break
    return tags


def _crosses(frame: pd.DataFrame, strategy: StrategySpec) -> pd.DataFrame:
    ema_length, sma_length = _indicator_lengths(strategy)
    data = frame.copy()
    data["ema"] = data.close.ewm(span=ema_length, adjust=False, min_periods=ema_length).mean()
    data["sma"] = data.close.rolling(sma_length, min_periods=sma_length).mean()
    data["cross_up"] = (data.ema > data.sma) & (data.ema.shift(1) <= data.sma.shift(1))
    data["cross_down"] = (data.ema < data.sma) & (data.ema.shift(1) >= data.sma.shift(1))
    return data


def _side_sign(side: str) -> int:
    return 1 if side == "LONG" else -1


def _fill_price(raw: float, side: str, entering: bool, slippage_bps: float) -> float:
    sign = _side_sign(side)
    direction = sign if entering else -sign
    return raw * (1 + direction * slippage_bps / 10_000)


def _trade_tags(
    timestamp: pd.Timestamp,
    strategy: StrategySpec,
    events: list[EventPoint],
    symbol: str | None,
) -> tuple[str, ...]:
    return tuple(sorted(set(_clock_tags(timestamp, strategy) + _event_tags(timestamp, strategy, events, symbol))))


def _simulate_side(
    data: pd.DataFrame,
    strategy: StrategySpec,
    side: str,
    events: list[EventPoint],
    settings: BacktestSettings,
    symbol: str | None,
) -> dict:
    enabled = strategy.long_side.enabled if side == "LONG" else strategy.short_side.enabled
    if not enabled:
        return {"trades": [], "equity": [], "metrics": _metrics([], [], settings.initial_capital)}

    entry_signal = "cross_up" if side == "LONG" else "cross_down"
    exit_signal = "cross_down" if side == "LONG" else "cross_up"
    cash = settings.initial_capital
    position = None
    pending = None
    trades = []
    curve = []
    peak = settings.initial_capital
    commission = strategy.execution.commission_per_side
    slippage = strategy.execution.slippage_bps

    for i, row in data.iterrows():
        timestamp = row.timestamp

        if pending and i > pending["signal_index"]:
            if pending["action"] == "ENTER" and position is None:
                fill = _fill_price(float(row.open), side, True, slippage)
                budget = cash * settings.allocation_fraction
                quantity = math.floor(max(0.0, (budget - commission) / fill))
                if quantity > 0:
                    cash -= quantity * fill + commission
                    position = {
                        "entry_time": timestamp,
                        "signal_time": pending["signal_time"],
                        "entry_price": fill,
                        "quantity": quantity,
                        "entry_tags": pending["tags"],
                        "entry_fee": commission,
                    }
            elif pending["action"] == "EXIT" and position is not None:
                fill = _fill_price(float(row.open), side, False, slippage)
                sign = _side_sign(side)
                quantity = position["quantity"]
                cash += quantity * fill - commission if side == "LONG" else -(quantity * fill) - commission
                # Short accounting above uses negative proceeds only if treated as a cash liability.
                # For stable single-position research accounting, reconstruct final equity from P&L.
                gross = sign * quantity * (fill - position["entry_price"])
                net = gross - position["entry_fee"] - commission
                pre_trade_capital = position.get("capital_at_entry", settings.initial_capital)
                trades.append(
                    {
                        "side": side,
                        "signal_time": position["signal_time"],
                        "entry_time": position["entry_time"],
                        "entry_price": position["entry_price"],
                        "exit_signal_time": pending["signal_time"],
                        "exit_time": timestamp,
                        "exit_price": fill,
                        "quantity": quantity,
                        "gross_pnl": gross,
                        "net_pnl": net,
                        "return": net / pre_trade_capital,
                        "temporal_tags": sorted(set(position["entry_tags"]) | set(pending["tags"])),
                    }
                )
                # Use realized P&L accounting for both sides to avoid synthetic short cash distortion.
                cash = pre_trade_capital + net
                position = None
            pending = None

        if position is not None:
            sign = _side_sign(side)
            marked = cash + sign * position["quantity"] * float(row.close)
            if side == "SHORT":
                marked = position.get("capital_at_entry", settings.initial_capital) + sign * position["quantity"] * (
                    float(row.close) - position["entry_price"]
                ) - position["entry_fee"]
        else:
            marked = cash

        peak = max(peak, marked)
        curve.append(
            {
                "timestamp": timestamp.isoformat(),
                "equity": float(marked),
                "drawdown": float(marked / peak - 1) if peak else 0.0,
            }
        )

        if i >= len(data) - 1 or pd.isna(row.ema) or pd.isna(row.sma):
            continue

        tags = _trade_tags(timestamp, strategy, events, symbol)
        if position is None and bool(row[entry_signal]):
            pending = {
                "action": "ENTER",
                "signal_index": i,
                "signal_time": timestamp.isoformat(),
                "tags": tags,
            }
            # store capital at entry when the fill happens
        elif position is not None and bool(row[exit_signal]):
            pending = {
                "action": "EXIT",
                "signal_index": i,
                "signal_time": timestamp.isoformat(),
                "tags": tags,
            }

        if position is not None and "capital_at_entry" not in position:
            position["capital_at_entry"] = marked

    if position is not None:
        row = data.iloc[-1]
        fill = _fill_price(float(row.close), side, False, slippage)
        sign = _side_sign(side)
        gross = sign * position["quantity"] * (fill - position["entry_price"])
        net = gross - position["entry_fee"] - commission
        capital = position.get("capital_at_entry", settings.initial_capital)
        trades.append(
            {
                "side": side,
                "signal_time": position["signal_time"],
                "entry_time": position["entry_time"],
                "entry_price": position["entry_price"],
                "exit_signal_time": row.timestamp.isoformat(),
                "exit_time": row.timestamp.isoformat(),
                "exit_price": fill,
                "quantity": position["quantity"],
                "gross_pnl": gross,
                "net_pnl": net,
                "return": net / capital,
                "temporal_tags": sorted(set(position["entry_tags"]) | set(_trade_tags(row.timestamp, strategy, events, symbol))),
            }
        )
        cash = capital + net
        curve[-1]["equity"] = float(cash)

    return {"trades": trades, "equity": curve, "metrics": _metrics(trades, curve, settings.initial_capital)}


def _metrics(trades: list[dict], curve: list[dict], initial_capital: float) -> dict:
    ending = curve[-1]["equity"] if curve else initial_capital
    profits = [float(t["net_pnl"]) for t in trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    max_dd = max((-float(p["drawdown"]) for p in curve), default=0.0)
    if curve:
        start = pd.Timestamp(curve[0]["timestamp"])
        end = pd.Timestamp(curve[-1]["timestamp"])
        days = max((end - start).total_seconds() / 86400, 0)
    else:
        days = 0
    cagr = (
        (ending / initial_capital) ** (365.25 / days) - 1
        if days >= 365 and ending > 0
        else None
    )
    return {
        "net_pnl": ending - initial_capital,
        "net_return": ending / initial_capital - 1,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "mar": cagr / max_dd if cagr is not None and max_dd > 0 else None,
        "win_rate": len(wins) / len(profits) if profits else None,
        "expectancy": sum(profits) / len(profits) if profits else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "trade_count": len(trades),
    }


def _combine(long_result: dict, short_result: dict, initial_capital: float) -> dict:
    trades = sorted(long_result["trades"] + short_result["trades"], key=lambda t: t["exit_time"])
    running = initial_capital
    curve = []
    peak = initial_capital
    for trade in trades:
        running += trade["net_pnl"]
        peak = max(peak, running)
        curve.append(
            {
                "timestamp": trade["exit_time"],
                "equity": running,
                "drawdown": running / peak - 1,
            }
        )
    return {"trades": trades, "equity": curve, "metrics": _metrics(trades, curve, initial_capital)}


def _temporal_breakdown(trades: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {"ALL": trades}
    for trade in trades:
        for tag in trade["temporal_tags"]:
            groups.setdefault(tag, []).append(trade)
    output = {}
    for tag, rows in groups.items():
        profits = [float(t["net_pnl"]) for t in rows]
        output[tag] = {
            "trades": len(rows),
            "net_pnl": sum(profits),
            "win_rate": len([p for p in profits if p > 0]) / len(profits) if profits else None,
            "expectancy": sum(profits) / len(profits) if profits else None,
        }
    return output


def run_backtest(request: BacktestRequest) -> dict:
    frame = _crosses(_prepare_frame(request.bars), request.strategy)
    symbol = str(frame.iloc[0].get("symbol")) if "symbol" in frame.columns else None

    long_result = _simulate_side(
        frame, request.strategy, "LONG", request.events, request.settings, symbol
    )
    short_result = _simulate_side(
        frame, request.strategy, "SHORT", request.events, request.settings, symbol
    )
    combined = _combine(long_result, short_result, request.settings.initial_capital)

    return {
        "strategy_id": request.strategy.id,
        "symbol": symbol,
        "bars": len(frame),
        "long": long_result,
        "short": short_result,
        "combined": combined,
        "temporal": {
            "long": _temporal_breakdown(long_result["trades"]),
            "short": _temporal_breakdown(short_result["trades"]),
            "combined": _temporal_breakdown(combined["trades"]),
        },
        "execution": request.strategy.execution.model_dump(mode="json"),
        "lookahead_policy": "closed-bar signal; next-bar-open fill",
    }
