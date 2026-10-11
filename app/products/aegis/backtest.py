"""Deterministic Aegis backtester for product strategies.

Signals are computed from closed bars and filled on the next bar open. Long, short,
and combined results are simulated independently so directional edge is never hidden.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from products.aegis.indicators import IndicatorCache, named, references
from products.aegis.kinds import warmup
from products.aegis.strategy import RuleSpec, StrategySide, StrategySpec
from products.aegis.temporal import entry_permitted, validate
from products.aegis.temporal import tags as temporal_tags


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


class OpenPosition(BaseModel):
    """A position held at the end of one run and carried into the next (walk-forward windows).

    `exit_signal_time`/`exit_tags` are set when the exit signal fired on the run's last bar; the
    next run fills that exit at its first evaluated bar's open, as a continuous run would."""

    model_config = ConfigDict(extra="forbid")
    side: Literal["LONG", "SHORT"]
    entry_time: str
    signal_time: str
    entry_price: float
    quantity: int = Field(gt=0)
    entry_fee: float
    capital_at_entry: float
    entry_tags: list[str]
    origin_window: int | None = None
    exit_signal_time: str | None = None
    exit_tags: list[str] = Field(default_factory=list)


class BacktestSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initial_capital: float = Field(default=100_000, gt=0)
    allocation_fraction: float = Field(default=1.0, gt=0, le=1)
    # Warm-up boundary (walk-forward): before it no entry is permitted and no equity point is
    # reported, while indicators and warm-up proceed normally. Timezone-aware when set.
    evaluate_from: datetime | None = None
    # Carry-over (walk-forward): start holding this position; and, when close_at_end is false,
    # report a position still open at the last bar instead of closing it there.
    initial_position: OpenPosition | None = None
    close_at_end: bool = True

    @field_validator("evaluate_from")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("evaluate_from must be timezone-aware")
        return value


class DataReference(BaseModel):
    """A pinned-archive selection resolved by the worker (symbol, timeframe, inclusive dates)."""

    model_config = ConfigDict(extra="forbid")
    symbol: str
    timeframe: str
    start: date
    end: date


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategySpec
    data: DataReference | None = None
    bars: list[dict] = Field(default_factory=list, max_length=200_000)
    events: list[EventPoint] = Field(default_factory=list, max_length=10_000)
    settings: BacktestSettings = Field(default_factory=BacktestSettings)

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.data is None) == (not self.bars):
            raise ValueError("provide exactly one of data (archive reference) or bars")
        return self


MIN_BARS = 35


def _check_warmup(frame: pd.DataFrame, strategy: StrategySpec) -> None:
    """Every enabled side must have more bars than each indicator's warm-up, or no signal could
    ever fire and a confident zero result would be a lie."""
    for side in (strategy.long_side, strategy.short_side):
        if not side.enabled:
            continue
        for spec in side.indicators:
            needed = warmup(spec.kind, spec.length, spec.effective_params())
            if len(frame) <= needed:
                raise ValueError(
                    f"insufficient bars: {len(frame)} bars cannot complete the warm-up of "
                    f"{spec.kind.upper()}({spec.length}) ({needed} bars); widen the range or "
                    "shorten the length"
                )


def _check_initial_position(request: BacktestRequest) -> None:
    """A carried position belongs to the side of its direction, which must be simulated."""
    position = request.settings.initial_position
    if position is None:
        return
    strategy = request.strategy
    owner = strategy.long_side if position.side == "LONG" else strategy.short_side
    if not owner.enabled:
        enabled = [
            name
            for name, spec in (("long", strategy.long_side), ("short", strategy.short_side))
            if spec.enabled
        ]
        target = f"the {enabled[0]} side" if enabled else "any enabled side"
        raise ValueError(f"initial_position side {position.side} does not match {target}")


def _prepare_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows).copy()
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing required fields: {sorted(missing)}")
    if len(frame) < MIN_BARS:
        raise ValueError(f"at least {MIN_BARS} bars are required to simulate")

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


def _data_key(frame: pd.DataFrame) -> str:
    """Content identity of the prepared bars, used to share indicator arrays across runs."""
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    return format(int(pd.util.hash_pandas_object(frame[columns], index=False).sum()), "x")


def _signal(frame: pd.DataFrame, rule: RuleSpec) -> pd.Series:
    left, right = frame[rule.left], frame[rule.right]
    if rule.operator == "crosses_above":
        return (left > right) & (left.shift(1) <= right.shift(1))
    if rule.operator == "crosses_below":
        return (left < right) & (left.shift(1) >= right.shift(1))
    raise ValueError(f"unsupported rule operator {rule.operator!r}")


def _side_frame(
    frame: pd.DataFrame, side: StrategySide, cache: IndicatorCache, data_key: str
) -> pd.DataFrame:
    """Bars plus this side's own indicator columns and entry/exit signal columns."""
    data = frame.copy()
    columns: list[str] = []
    for spec in side.indicators:
        produced = named(spec, cache.get(data_key, spec, frame))
        for column in produced.columns:
            data[column] = produced[column].to_numpy()
            columns.append(column)
    data["entry_signal"] = _signal(data, side.entry)
    data["exit_signal"] = _signal(data, side.exit)
    data["warm"] = data[columns].notna().all(axis=1) if columns else True
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
    return temporal_tags(timestamp, strategy.temporal, events, symbol)


def _series(data: pd.DataFrame, side: StrategySide) -> dict[str, list[float | None]]:
    """Indicator values the side traded on, aligned to bars; warm-up gaps are None."""
    return {
        column: [None if pd.isna(v) else float(v) for v in data[column].tolist()]
        for spec in side.indicators
        for column in references(spec)
    }


def _simulate_side(
    frame: pd.DataFrame,
    strategy: StrategySpec,
    side: str,
    events: list[EventPoint],
    settings: BacktestSettings,
    symbol: str | None,
    cache: IndicatorCache,
    data_key: str,
) -> dict:
    spec = strategy.long_side if side == "LONG" else strategy.short_side
    if not spec.enabled:
        return {
            "enabled": False,
            "series": {},
            "trades": [],
            "equity": [],
            "metrics": _metrics([], [], settings.initial_capital),
            "open_position": None,
            "ending_cash": settings.initial_capital,
            "ending_equity": settings.initial_capital,
            "_in_position": [],
        }
    data = _side_frame(frame, spec, cache, data_key)
    entry_signal = "entry_signal"
    exit_signal = "exit_signal"
    cash = settings.initial_capital
    position = None
    pending = None
    carried = settings.initial_position
    if carried is not None and carried.side == side:
        position = {
            "entry_time": carried.entry_time,
            "signal_time": carried.signal_time,
            "entry_price": carried.entry_price,
            "quantity": carried.quantity,
            "entry_tags": list(carried.entry_tags),
            "entry_fee": carried.entry_fee,
            "capital_at_entry": carried.capital_at_entry,
            "carried_from_window": carried.origin_window,
        }
        if carried.exit_signal_time is not None:
            # An exit signalled on the previous run's last bar fills at this run's first
            # evaluated bar open (never inside the warm-up lead).
            pending = {
                "action": "EXIT",
                "signal_index": -1,
                "signal_time": carried.exit_signal_time,
                "tags": tuple(carried.exit_tags),
                "carried": True,
            }
    trades = []
    curve = []
    in_position = []
    peak = settings.initial_capital
    exit_carry: dict = {}
    commission = strategy.execution.commission_per_side
    slippage = strategy.execution.slippage_bps

    for i, row in data.iterrows():
        timestamp = row.timestamp
        evaluating = settings.evaluate_from is None or timestamp >= settings.evaluate_from

        if pending and i > pending["signal_index"] and (evaluating or not pending.get("carried")):
            if pending["action"] == "ENTER" and position is None:
                fill = _fill_price(float(row.open), side, True, slippage)
                budget = cash * settings.allocation_fraction
                quantity = math.floor(max(0.0, (budget - commission) / fill))
                if quantity > 0:
                    position = {
                        "entry_time": timestamp.isoformat(),
                        "signal_time": pending["signal_time"],
                        "entry_price": fill,
                        "quantity": quantity,
                        "entry_tags": pending["tags"],
                        "entry_fee": commission,
                        "capital_at_entry": cash,
                    }
            elif pending["action"] == "EXIT" and position is not None:
                fill = _fill_price(float(row.open), side, False, slippage)
                sign = _side_sign(side)
                quantity = position["quantity"]
                gross = sign * quantity * (fill - position["entry_price"])
                net = gross - position["entry_fee"] - commission
                pre_trade_capital = position.get("capital_at_entry", settings.initial_capital)
                trades.append(
                    _carried(
                        position,
                        {
                            "side": side,
                            "signal_time": position["signal_time"],
                            "entry_time": position["entry_time"],
                            "entry_price": position["entry_price"],
                            "exit_signal_time": pending["signal_time"],
                            "exit_time": timestamp.isoformat(),
                            "exit_price": fill,
                            "quantity": quantity,
                            "gross_pnl": gross,
                            "net_pnl": net,
                            "return": net / pre_trade_capital,
                            "temporal_tags": sorted(
                                set(position["entry_tags"]) | set(pending["tags"])
                            ),
                        },
                    )
                )
                # Use realized P&L accounting for both sides to avoid synthetic short cash distortion.
                cash = pre_trade_capital + net
                position = None
            pending = None

        if not evaluating:
            continue  # warm-up lead: indicators accumulate, nothing is counted or permitted

        if position is not None:
            sign = _side_sign(side)
            marked = (
                position["capital_at_entry"]
                + sign * position["quantity"] * (float(row.close) - position["entry_price"])
                - position["entry_fee"]
            )
        else:
            marked = cash

        in_position.append(position is not None)
        peak = max(peak, marked)
        curve.append(
            {
                "timestamp": timestamp.isoformat(),
                "equity": float(marked),
                "drawdown": float(marked / peak - 1) if peak else 0.0,
            }
        )

        if i >= len(data) - 1:
            if (
                not settings.close_at_end
                and position is not None
                and bool(row.warm)
                and bool(row[exit_signal])
            ):
                # No next bar here to fill on: the signal travels with the open position.
                exit_carry = {
                    "exit_signal_time": timestamp.isoformat(),
                    "exit_tags": list(_trade_tags(timestamp, strategy, events, symbol)),
                }
            continue
        if not bool(row.warm):
            continue

        tags = _trade_tags(timestamp, strategy, events, symbol)
        if (
            position is None
            and bool(row[entry_signal])
            and entry_permitted(timestamp, strategy.temporal)
        ):
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

    open_position = None
    if position is not None and not settings.close_at_end:
        open_position = {
            "side": side,
            "entry_time": position["entry_time"],
            "signal_time": position["signal_time"],
            "entry_price": position["entry_price"],
            "quantity": position["quantity"],
            "entry_fee": position["entry_fee"],
            "capital_at_entry": position["capital_at_entry"],
            "entry_tags": list(position["entry_tags"]),
            "origin_window": position.get("carried_from_window"),
            "exit_signal_time": None,
            "exit_tags": [],
            **exit_carry,
        }
    elif position is not None:
        row = data.iloc[-1]
        fill = _fill_price(float(row.close), side, False, slippage)
        sign = _side_sign(side)
        gross = sign * position["quantity"] * (fill - position["entry_price"])
        net = gross - position["entry_fee"] - commission
        capital = position.get("capital_at_entry", settings.initial_capital)
        trades.append(
            _carried(
                position,
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
                    "temporal_tags": sorted(
                        set(position["entry_tags"])
                        | set(_trade_tags(row.timestamp, strategy, events, symbol))
                    ),
                },
            )
        )
        cash = capital + net
        if curve:
            curve[-1]["equity"] = float(cash)

    return {
        "enabled": True,
        "series": _series(data, spec),
        "trades": trades,
        "equity": curve,
        "metrics": _metrics(trades, curve, settings.initial_capital, _fraction(in_position)),
        "open_position": open_position,
        "ending_cash": float(cash),
        "ending_equity": float(curve[-1]["equity"]) if curve else float(settings.initial_capital),
        "_in_position": in_position,
    }


def _carried(position: dict, trade: dict) -> dict:
    """A trade closing a position that was carried in names the window it came from; trades of
    plain runs are left exactly as before so their hashes do not move."""
    if "carried_from_window" in position:
        return {**trade, "carried_from_window": position["carried_from_window"]}
    return trade


def _fraction(flags: list[bool]) -> float:
    return sum(1 for f in flags if f) / len(flags) if flags else 0.0


def _metrics(
    trades: list[dict], curve: list[dict], initial_capital: float, exposure: float = 0.0
) -> dict:
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
    cagr = (ending / initial_capital) ** (365.25 / days) - 1 if days >= 365 and ending > 0 else None
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
        "exposure": exposure,
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


def markers(result: dict) -> list[dict]:
    """Chart markers derived from trades: one entry and one exit per trade, epoch ms."""
    points = []
    for side in ("long", "short"):
        for trade in result[side]["trades"]:
            for kind, time_key, price_key in (
                ("entry", "entry_time", "entry_price"),
                ("exit", "exit_time", "exit_price"),
            ):
                millis = int(pd.Timestamp(trade[time_key]).value // 1_000_000)
                points.append(
                    {
                        "time": millis,
                        "price": float(trade[price_key]),
                        "side": side.upper(),
                        "kind": kind,
                    }
                )
    return sorted(points, key=lambda p: (p["time"], p["side"], p["kind"]))


def run_backtest(request: BacktestRequest, cache: IndicatorCache | None = None) -> dict:
    validate(request.strategy.temporal)
    _check_initial_position(request)
    cache = cache if cache is not None else IndicatorCache()
    frame = _prepare_frame(request.bars)
    _check_warmup(frame, request.strategy)
    data_key = _data_key(frame)
    symbol = str(frame.iloc[0].get("symbol")) if "symbol" in frame.columns else None

    long_result = _simulate_side(
        frame, request.strategy, "LONG", request.events, request.settings, symbol, cache, data_key
    )
    short_result = _simulate_side(
        frame, request.strategy, "SHORT", request.events, request.settings, symbol, cache, data_key
    )
    combined = _combine(long_result, short_result, request.settings.initial_capital)
    long_flags = long_result.pop("_in_position")
    short_flags = short_result.pop("_in_position")
    length = max(len(long_flags), len(short_flags))
    union = [
        (long_flags[i] if i < len(long_flags) else False)
        or (short_flags[i] if i < len(short_flags) else False)
        for i in range(length)
    ]
    combined["metrics"]["exposure"] = _fraction(union)

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
