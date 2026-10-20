"""Deterministic Aegis backtester for product strategies.

Signals are computed from closed bars and filled on the next bar open. Long, short,
and combined results are simulated independently so directional edge is never hidden.
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from products.aegis import kernel
from products.aegis.indicators import IndicatorCache, named, references
from products.aegis.kinds import warmup
from products.aegis.strategy import (
    BAND_OPERATORS,
    PRICE_OPERANDS,
    Rule,
    RuleSpec,
    StrategySide,
    StrategySpec,
    conditions,
    is_constant,
    referenced_columns,
)
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


class PendingEntry(BaseModel):
    """An entry signalled on one run's last bar, carried into the next run (Mission 8 QA D1): it
    fills at the next run's first evaluated bar open, as a continuous run would fill it."""

    model_config = ConfigDict(extra="forbid")
    side: Literal["LONG", "SHORT"]
    signal_time: str
    entry_tags: list[str] = Field(default_factory=list)


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
    # Carry-over of an entry signalled on the previous run's last bar (no position on that side).
    initial_entry: PendingEntry | None = None
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
    # The compiled kernel is the default (Mission 6 spec §4.2); the reference engine stays as the
    # oracle. Both produce byte-identical canonical payloads; `engine` is never hashed.
    engine: Literal["kernel", "reference"] = "kernel"

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
    """A carried position or entry belongs to the side of its direction, which must be simulated;
    one side never carries both."""
    position = request.settings.initial_position
    pending = request.settings.initial_entry
    strategy = request.strategy
    if pending is not None:
        owner = strategy.long_side if pending.side == "LONG" else strategy.short_side
        if not owner.enabled:
            raise ValueError(f"initial_entry side {pending.side} is not an enabled side")
        if position is not None and position.side == pending.side:
            raise ValueError(
                f"side {pending.side} cannot start with both a carried position and a carried entry"
            )
    if position is None:
        return
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
    return _validated(pd.DataFrame(rows).copy())


def prepare_archive_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """`_prepare_frame(engine_rows(frame, symbol))` without a dict per bar (Mission 10): the same
    columns, order, dtypes and checks, so the data key and every hash are unchanged."""
    out = frame.assign(symbol=symbol)
    if "timestamp" in out.columns:
        # The rows path round-trips through ISO strings, which always parse to nanoseconds.
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True).astype("datetime64[ns, UTC]")
    for name in ("open", "high", "low", "close", "volume"):
        # ... and through Python floats and ints, which widen every float and int column.
        if name in out.columns and out[name].dtype.kind == "f":
            out[name] = out[name].astype("float64")
        elif name in out.columns and out[name].dtype.kind in "iu":
            out[name] = out[name].astype("int64")
    return _validated(out)


def frame_slice(frame: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """Bars [start, end) of a prepared frame: what `_prepare_frame` makes of those rows (a
    walk-forward window, an out-of-sample lead or a study window)."""
    part = frame.iloc[start:end].reset_index(drop=True)
    if len(part) < MIN_BARS:
        raise ValueError(f"at least {MIN_BARS} bars are required to simulate")
    return part


def prepare_bars(bars: list[dict] | pd.DataFrame, symbol: str) -> pd.DataFrame:
    """A job's bars as one prepared frame: an archive frame for `symbol`, or supplied rows as
    given (the rows path, unchanged)."""
    if isinstance(bars, pd.DataFrame):
        return prepare_archive_frame(bars, symbol)
    return _prepare_frame(bars)


def prepared_request(
    strategy: StrategySpec, settings: BacktestSettings, engine: str = "kernel"
) -> BacktestRequest:
    """A request whose bars are already a prepared frame (`run_prepared` reads neither bars
    nor the archive reference)."""
    return BacktestRequest.model_construct(
        strategy=strategy, data=None, bars=[], events=[], settings=settings, engine=engine
    )


def _validated(frame: pd.DataFrame) -> pd.DataFrame:
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


def _operand(frame: pd.DataFrame, operand: str) -> pd.Series:
    """An operand as a series aligned to the bars: a price column, a constant, or an indicator
    column named by its reference spelling."""
    if operand in PRICE_OPERANDS:
        return frame[PRICE_OPERANDS[operand]].astype(float)
    if is_constant(operand):
        return pd.Series(float(operand), index=frame.index)
    return frame[operand]


def _condition(frame: pd.DataFrame, rule: RuleSpec) -> pd.Series:
    left = _operand(frame, rule.left)
    if rule.operator in BAND_OPERATORS:
        upper, lower = frame[f"{rule.right}.upper"], frame[f"{rule.right}.lower"]
        if rule.operator == "inside_band":
            return (left >= lower) & (left <= upper)
        return (left < lower) | (left > upper)
    right = _operand(frame, rule.right)
    if rule.operator == "crosses_above":
        return (left > right) & (left.shift(1) <= right.shift(1))
    if rule.operator == "crosses_below":
        return (left < right) & (left.shift(1) >= right.shift(1))
    if rule.operator == "greater_than":
        return left > right
    if rule.operator == "less_than":
        return left < right
    raise ValueError(f"unsupported rule operator {rule.operator!r}")


def evaluate(frame: pd.DataFrame, rule: Rule) -> pd.Series:
    """A rule as a boolean series over the bars: one condition, or two joined by AND / OR."""
    parts = [_condition(frame, condition) for condition in conditions(rule)]
    combined = parts[0]
    for part in parts[1:]:
        combined = (combined | part) if getattr(rule, "any_of", None) else (combined & part)
    return combined.fillna(False).astype(bool)


def _side_frame(
    frame: pd.DataFrame, side: StrategySide, cache: IndicatorCache, data_key: str
) -> pd.DataFrame:
    """Bars plus this side's own indicator columns and entry/exit signal columns."""
    data = frame.copy()
    for spec in side.indicators:
        produced = named(spec, cache.get(data_key, spec, frame))
        for column in produced.columns:
            data[column] = produced[column].to_numpy()
    data["entry_signal"] = evaluate(data, side.entry)
    data["exit_signal"] = evaluate(data, side.exit)
    # Warm where every indicator column the rules read has a value (spec §6).
    columns = sorted(referenced_columns(side))
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
            "pending_entry": None,
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
    entry_waiting = settings.initial_entry
    if position is None and entry_waiting is not None and entry_waiting.side == side:
        # An entry signalled on the previous run's last bar fills at this run's first evaluated
        # bar open (Mission 8 QA D1), exactly as a continuous run fills it.
        pending = {
            "action": "ENTER",
            "signal_index": -1,
            "signal_time": entry_waiting.signal_time,
            "tags": tuple(entry_waiting.entry_tags),
            "carried": True,
        }
    trades = []
    curve = []
    in_position = []
    peak = settings.initial_capital
    exit_carry: dict = {}
    entry_carry: dict | None = None
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
            elif (
                not settings.close_at_end
                and position is None
                and bool(row.warm)
                and bool(row[entry_signal])
                and entry_permitted(timestamp, strategy.temporal)
            ):
                # No next bar here to fill on: the entry signal travels to the next run.
                entry_carry = {
                    "side": side,
                    "signal_time": timestamp.isoformat(),
                    "entry_tags": list(_trade_tags(timestamp, strategy, events, symbol)),
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
        "pending_entry": entry_carry,
        "ending_cash": float(cash),
        "ending_equity": float(curve[-1]["equity"]) if curve else float(settings.initial_capital),
        "_in_position": in_position,
    }


_PERMITTED_CACHE: dict[tuple[str, str], np.ndarray] = {}
_PERMITTED_LOCK = threading.Lock()
_PERMITTED_LIMIT = 32


def permitted_mask(frame: pd.DataFrame, temporal, data_key: str | None = None) -> np.ndarray:
    """`entry_permitted` for every bar as one boolean array (plan ruling P9): a pure function
    of the bar timestamp and the temporal context, so it is cached per data identity."""
    key = (data_key, temporal.model_dump_json()) if data_key is not None else None
    if key is not None:
        with _PERMITTED_LOCK:
            cached = _PERMITTED_CACHE.get(key)
        if cached is not None:
            return cached
    mask = np.fromiter(
        (entry_permitted(stamp, temporal) for stamp in frame["timestamp"]),
        dtype=np.bool_,
        count=len(frame),
    )
    if key is not None:
        with _PERMITTED_LOCK:
            if len(_PERMITTED_CACHE) >= _PERMITTED_LIMIT:
                _PERMITTED_CACHE.pop(next(iter(_PERMITTED_CACHE)))
            _PERMITTED_CACHE[key] = mask
    return mask


def _simulate_side_kernel(
    frame: pd.DataFrame,
    strategy: StrategySpec,
    side: str,
    events: list[EventPoint],
    settings: BacktestSettings,
    symbol: str | None,
    cache: IndicatorCache,
    data_key: str,
) -> dict:
    """The reference engine's result from the compiled loop (Mission 6 spec §4.2)."""
    spec = strategy.long_side if side == "LONG" else strategy.short_side
    if not spec.enabled:
        return _simulate_side(frame, strategy, side, events, settings, symbol, cache, data_key)
    data = _side_frame(frame, spec, cache, data_key)
    timestamps = data["timestamp"]
    if settings.evaluate_from is None:
        evaluating = np.ones(len(data), dtype=np.bool_)
    else:
        evaluating = (timestamps >= settings.evaluate_from).to_numpy(dtype=np.bool_)
    carried = settings.initial_position
    carried_array = np.zeros(7)
    if carried is not None and carried.side == side:
        carried_array[:6] = (
            1.0,
            carried.entry_price,
            float(carried.quantity),
            carried.entry_fee,
            carried.capital_at_entry,
            1.0 if carried.exit_signal_time is not None else 0.0,
        )
    else:
        carried = None
    waiting = settings.initial_entry
    if carried is None and waiting is not None and waiting.side == side:
        carried_array[6] = 1.0  # an entry carried in fills at the first evaluated bar
    else:
        waiting = None
    sign = _side_sign(side)
    trades_array, n_trades, equity, drawdown, in_flags, n_points, scalars, _ = (
        kernel.simulate_arrays(
            data["open"].to_numpy(dtype=np.float64),
            data["high"].to_numpy(dtype=np.float64),
            data["low"].to_numpy(dtype=np.float64),
            data["close"].to_numpy(dtype=np.float64),
            data["entry_signal"].to_numpy(dtype=np.bool_),
            data["exit_signal"].to_numpy(dtype=np.bool_),
            data["warm"].to_numpy(dtype=np.bool_),
            evaluating,
            permitted_mask(frame, strategy.temporal, data_key),
            sign,
            settings.initial_capital,
            settings.allocation_fraction,
            strategy.execution.commission_per_side,
            strategy.execution.slippage_bps,
            settings.close_at_end,
            carried_array,
        )
    )
    iso = [stamp.isoformat() for stamp in timestamps]

    def tags_at(index: int) -> tuple[str, ...]:
        return _trade_tags(timestamps.iloc[index], strategy, events, symbol)

    trades = []
    for row in trades_array[:n_trades]:
        entry_index, exit_index = int(row[0]), int(row[1])
        signal_index, exit_signal_index = int(row[2]), int(row[3])
        carried_in = row[10] > 0.0
        if carried_in:
            entry_time, signal_time = carried.entry_time, carried.signal_time
            entry_tags = set(carried.entry_tags)
        elif signal_index < 0:  # filled from the entry carried in
            entry_time, signal_time = iso[entry_index], waiting.signal_time
            entry_tags = set(waiting.entry_tags)
        else:
            entry_time, signal_time = iso[entry_index], iso[signal_index]
            entry_tags = set(tags_at(signal_index))
        if exit_signal_index < 0:
            exit_signal_time, exit_tags = carried.exit_signal_time, set(carried.exit_tags)
        else:
            exit_signal_time, exit_tags = iso[exit_signal_index], set(tags_at(exit_signal_index))
        trade = {
            "side": side,
            "signal_time": signal_time,
            "entry_time": entry_time,
            "entry_price": float(row[4]),
            "exit_signal_time": exit_signal_time,
            "exit_time": iso[exit_index],
            "exit_price": float(row[5]),
            "quantity": int(row[6]),
            "gross_pnl": float(row[7]),
            "net_pnl": float(row[8]),
            "return": float(row[9]),
            "temporal_tags": sorted(entry_tags | exit_tags),
        }
        if carried_in:
            trade["carried_from_window"] = carried.origin_window
        trades.append(trade)

    evaluated = np.flatnonzero(evaluating)[:n_points]
    curve = [
        {"timestamp": iso[int(bar)], "equity": float(equity[k]), "drawdown": float(drawdown[k])}
        for k, bar in enumerate(evaluated)
    ]
    in_position = [bool(flag) for flag in in_flags[:n_points]]

    open_position = None
    if scalars[2] > 0.0:
        new_position = scalars[4] >= 0.0
        from_waiting = new_position and scalars[3] < 0.0  # filled from the entry carried in
        exit_index = int(scalars[9])
        if from_waiting:
            signal_time, entry_tags = waiting.signal_time, list(waiting.entry_tags)
        elif new_position:
            signal_time, entry_tags = iso[int(scalars[3])], list(tags_at(int(scalars[3])))
        else:
            signal_time, entry_tags = carried.signal_time, list(carried.entry_tags)
        open_position = {
            "side": side,
            "entry_time": iso[int(scalars[4])] if new_position else carried.entry_time,
            "signal_time": signal_time,
            "entry_price": float(scalars[5]),
            "quantity": int(scalars[6]),
            "entry_fee": float(scalars[7]),
            "capital_at_entry": float(scalars[8]),
            "entry_tags": entry_tags,
            "origin_window": None if new_position else carried.origin_window,
            "exit_signal_time": iso[exit_index] if exit_index >= 0 else None,
            "exit_tags": list(tags_at(exit_index)) if exit_index >= 0 else [],
        }

    entry_index = int(scalars[10])
    pending_entry = (
        {"side": side, "signal_time": iso[entry_index], "entry_tags": list(tags_at(entry_index))}
        if entry_index >= 0
        else None
    )
    return {
        "enabled": True,
        "series": _series(data, spec),
        "trades": trades,
        "equity": curve,
        "metrics": _metrics(trades, curve, settings.initial_capital, _fraction(in_position)),
        "open_position": open_position,
        "pending_entry": pending_entry,
        "ending_cash": float(scalars[0]),
        "ending_equity": float(scalars[1]),
        "_in_position": in_position,
    }


def _metrics_arrays(
    net_pnls: list[float],
    equity: np.ndarray,
    drawdown: np.ndarray,
    first_stamp,
    last_stamp,
    initial_capital: float,
    exposure: float,
) -> dict:
    """`_metrics` from the kernel's arrays, formula for formula (the experiment pool's path)."""
    n = len(equity)
    ending = float(equity[-1]) if n else initial_capital
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    max_dd = max((-float(v) for v in drawdown), default=0.0)
    if n:
        days = max((last_stamp - first_stamp).total_seconds() / 86400, 0)
    else:
        days = 0
    cagr = (ending / initial_capital) ** (365.25 / days) - 1 if days >= 365 and ending > 0 else None
    return {
        "net_pnl": ending - initial_capital,
        "net_return": ending / initial_capital - 1,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "mar": cagr / max_dd if cagr is not None and max_dd > 0 else None,
        "win_rate": len(wins) / len(net_pnls) if net_pnls else None,
        "expectancy": sum(net_pnls) / len(net_pnls) if net_pnls else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "trade_count": len(net_pnls),
        "exposure": exposure,
    }


def _side_metrics(
    frame: pd.DataFrame,
    strategy: StrategySpec,
    side: str,
    settings: BacktestSettings,
    cache: IndicatorCache,
    data_key: str,
) -> tuple[list[dict], dict, list[bool]]:
    """(lite trades, metrics, exposure flags) of one side from the kernel; no series, no
    per-bar dicts, no tags. Carried positions are not supported here (experiments never carry)."""
    spec = strategy.long_side if side == "LONG" else strategy.short_side
    if not spec.enabled:
        return [], _metrics([], [], settings.initial_capital), []
    data = _side_frame(frame, spec, cache, data_key)
    n = len(data)
    trades_array, n_trades, equity, drawdown, in_flags, n_points, _scalars, _ = (
        kernel.simulate_arrays(
            data["open"].to_numpy(dtype=np.float64),
            data["high"].to_numpy(dtype=np.float64),
            data["low"].to_numpy(dtype=np.float64),
            data["close"].to_numpy(dtype=np.float64),
            data["entry_signal"].to_numpy(dtype=np.bool_),
            data["exit_signal"].to_numpy(dtype=np.bool_),
            data["warm"].to_numpy(dtype=np.bool_),
            np.ones(n, dtype=np.bool_),
            permitted_mask(frame, strategy.temporal, data_key),
            _side_sign(side),
            settings.initial_capital,
            settings.allocation_fraction,
            strategy.execution.commission_per_side,
            strategy.execution.slippage_bps,
            True,
            np.zeros(7),
        )
    )
    timestamps = data["timestamp"]
    trades = [
        {"exit_time": timestamps.iloc[int(row[1])].isoformat(), "net_pnl": float(row[8])}
        for row in trades_array[:n_trades]
    ]
    flags = [bool(flag) for flag in in_flags[:n_points]]
    metrics = _metrics_arrays(
        [t["net_pnl"] for t in trades],
        equity[:n_points],
        drawdown[:n_points],
        timestamps.iloc[0],
        timestamps.iloc[n - 1],
        settings.initial_capital,
        _fraction(flags),
    )
    return trades, metrics, flags


def run_metrics(
    request: BacktestRequest,
    frame: pd.DataFrame,
    data_key: str,
    cache: IndicatorCache,
    want_curve: bool = False,
) -> dict:
    """Metrics only, for the experiment pool (Mission 6): equal to `run_backtest`'s metrics for
    the same request, at a fraction of the cost. Falls back to the full reference path when the
    kernel is unavailable."""
    validate(request.strategy.temporal)
    _check_initial_position(request)
    _check_warmup(frame, request.strategy)
    if not kernel.AVAILABLE:
        full = run_prepared(request, frame, data_key, cache)
        curve = [float(p["equity"]) for p in full["combined"]["equity"]] if want_curve else None
        return {
            "long": full["long"]["metrics"],
            "short": full["short"]["metrics"],
            "combined": full["combined"]["metrics"],
            "engine": full["engine"],
            "curve": curve,
            "first_time": frame["timestamp"].iloc[0].isoformat(),
            "last_time": frame["timestamp"].iloc[-1].isoformat(),
        }
    long_trades, long_metrics, long_flags = _side_metrics(
        frame, request.strategy, "LONG", request.settings, cache, data_key
    )
    short_trades, short_metrics, short_flags = _side_metrics(
        frame, request.strategy, "SHORT", request.settings, cache, data_key
    )
    combined = _combine(
        {"trades": long_trades}, {"trades": short_trades}, request.settings.initial_capital
    )
    length = max(len(long_flags), len(short_flags))
    union = [
        (long_flags[i] if i < len(long_flags) else False)
        or (short_flags[i] if i < len(short_flags) else False)
        for i in range(length)
    ]
    combined["metrics"]["exposure"] = _fraction(union)
    return {
        "long": long_metrics,
        "short": short_metrics,
        "combined": combined["metrics"],
        "engine": "kernel",
        "curve": [float(p["equity"]) for p in combined["equity"]] if want_curve else None,
        "first_time": frame["timestamp"].iloc[0].isoformat(),
        "last_time": frame["timestamp"].iloc[-1].isoformat(),
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
    frame = _prepare_frame(request.bars)
    return run_prepared(request, frame, _data_key(frame), cache)


def run_prepared(
    request: BacktestRequest,
    frame: pd.DataFrame,
    data_key: str,
    cache: IndicatorCache | None = None,
) -> dict:
    """`run_backtest` on bars already prepared once (the pool reuses one frame per worker)."""
    validate(request.strategy.temporal)
    _check_initial_position(request)
    cache = cache if cache is not None else IndicatorCache()
    _check_warmup(frame, request.strategy)
    symbol = str(frame.iloc[0].get("symbol")) if "symbol" in frame.columns else None
    engine = "kernel" if request.engine == "kernel" and kernel.AVAILABLE else "reference"
    simulate = _simulate_side_kernel if engine == "kernel" else _simulate_side

    long_result = simulate(
        frame, request.strategy, "LONG", request.events, request.settings, symbol, cache, data_key
    )
    short_result = simulate(
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
        "engine": engine,
    }
