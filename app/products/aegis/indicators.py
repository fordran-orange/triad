"""Indicator series calculators for Aegis. Indicators calculate series; strategy sides consume
them. Kind metadata (outputs, panes, parameters, warm-up) lives in `kinds.py`; the functions
here compute a kind's outputs from bars. Every output is NaN until its warm-up is complete."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
import pandas as pd

from products.aegis.kinds import kind_info
from products.aegis.strategy import IndicatorSpec

SINGLE = "value"  # the output column name of single-series kinds inside the cache


def ema(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(values: pd.Series, length: int) -> pd.Series:
    return values.rolling(length, min_periods=length).mean()


def wilder(values: pd.Series, length: int) -> pd.Series:
    """Wilder smoothing: the first value is the mean of the first `length` non-null inputs, then
    avg = (avg·(length−1) + x) / length."""
    data = values.to_numpy(dtype=float)
    out = np.full(len(data), np.nan)
    valid = np.flatnonzero(~np.isnan(data))
    if len(valid) < length:
        return pd.Series(out, index=values.index)
    first = valid[0]
    seed = first + length - 1
    out[seed] = data[first : seed + 1].mean()
    for i in range(seed + 1, len(data)):
        out[i] = (out[i - 1] * (length - 1) + data[i]) / length
    return pd.Series(out, index=values.index)


def _source(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.Series:
    if spec.source not in frame.columns:
        raise ValueError(f"unknown indicator source {spec.source!r}")
    return pd.to_numeric(frame[spec.source])


def _rsi(spec: IndicatorSpec, frame: pd.DataFrame, params: dict[str, float]) -> dict:
    change = _source(spec, frame).diff()
    gains = wilder(change.clip(lower=0), spec.length)
    losses = wilder(-change.clip(upper=0), spec.length)
    rsi = (100 - 100 / (1 + gains / losses)).where(losses != 0, 100.0)
    return {SINGLE: rsi.where(gains.notna())}


def _atr(spec: IndicatorSpec, frame: pd.DataFrame, params: dict[str, float]) -> dict:
    high, low, close = (pd.to_numeric(frame[c]) for c in ("high", "low", "close"))
    previous = close.shift(1)
    ranges = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1)
    true_range = ranges.max(axis=1).where(previous.notna())
    return {SINGLE: wilder(true_range, spec.length)}


def _bb(spec: IndicatorSpec, frame: pd.DataFrame, params: dict[str, float]) -> dict:
    values = _source(spec, frame)
    middle = sma(values, spec.length)
    deviation = values.rolling(spec.length, min_periods=spec.length).std(ddof=0)
    width = params["multiplier"] * deviation
    return {"upper": middle + width, "middle": middle, "lower": middle - width}


def _donchian(spec: IndicatorSpec, frame: pd.DataFrame, params: dict[str, float]) -> dict:
    window = spec.length
    upper = pd.to_numeric(frame["high"]).shift(1).rolling(window, min_periods=window).max()
    lower = pd.to_numeric(frame["low"]).shift(1).rolling(window, min_periods=window).min()
    return {"upper": upper, "lower": lower, "middle": (upper + lower) / 2}


def _macd(spec: IndicatorSpec, frame: pd.DataFrame, params: dict[str, float]) -> dict:
    values = _source(spec, frame)
    span = int(params["signal"])
    line = ema(values, spec.length) - ema(values, int(params["slow"]))
    signal = line.ewm(span=span, adjust=False, min_periods=span).mean()
    ready = signal.notna()
    return {"line": line.where(ready), "signal": signal, "histogram": (line - signal).where(ready)}


COMPUTE: dict[str, Callable[[IndicatorSpec, pd.DataFrame, dict[str, float]], dict]] = {
    "EMA": lambda spec, frame, params: {SINGLE: ema(_source(spec, frame), spec.length)},
    "SMA": lambda spec, frame, params: {SINGLE: sma(_source(spec, frame), spec.length)},
    "RSI": _rsi,
    "ATR": _atr,
    "BB": _bb,
    "DONCHIAN": _donchian,
    "MACD": _macd,
}


def references(spec: IndicatorSpec) -> list[str]:
    """How rules and the chart name this indicator's series: `id`, or `id.output` per output."""
    produced = kind_info(spec.kind).outputs
    return [f"{spec.id}.{name}" for name in produced] if produced else [spec.id]


def outputs(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """The kind's outputs as columns named by output (`value` for single-series kinds)."""
    info = kind_info(spec.kind)
    produced = COMPUTE[spec.kind.upper()](spec, frame, spec.effective_params())
    names = list(info.outputs) or [SINGLE]
    return pd.DataFrame({name: produced[name] for name in names}, index=frame.index)


def named(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """An outputs frame relabelled with the spec's reference spellings."""
    renamed = frame.copy()
    renamed.columns = references(spec)
    return renamed


def compute(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """Compute one indicator; columns are its reference spellings (see `references`)."""
    return named(spec, outputs(spec, frame))


class IndicatorCache:
    """Memoizes indicator outputs per (data identity, kind, source, length, parameters): one frame
    per configuration, shared across optimizer cells, runs and indicator ids."""

    def __init__(self, max_data_keys: int | None = None) -> None:
        self._series: dict[tuple, pd.DataFrame] = {}
        self._data_keys: list[str] = []  # insertion order; the oldest is evicted first
        self.max_data_keys = max_data_keys
        self.hits = 0
        self._lock = threading.Lock()  # the worker-wide backtest cache is shared across requests

    @property
    def data_keys(self) -> list[str]:
        return list(self._data_keys)

    def _admit(self, data_key: str) -> None:
        if data_key in self._data_keys:
            return
        self._data_keys.append(data_key)
        while self.max_data_keys is not None and len(self._data_keys) > self.max_data_keys:
            evicted = self._data_keys.pop(0)
            for key in [k for k in self._series if k[0] == evicted]:
                del self._series[key]

    def get(self, data_key: str, spec: IndicatorSpec, frame: pd.DataFrame) -> pd.DataFrame:
        """The outputs frame, columns named by output; relabel it with `named`."""
        params = tuple(sorted(spec.effective_params().items()))
        key = (data_key, spec.kind.upper(), spec.source, spec.length, params)
        with self._lock:
            series = self._series.get(key)
            if series is None:
                self._admit(data_key)
                series = outputs(spec, frame)
                self._series[key] = series
            else:
                self.hits += 1
            return series

    def __len__(self) -> int:
        return len(self._series)
