"""Indicator series calculators for Aegis. Indicators calculate series; strategy sides consume
them. The registry is keyed by `IndicatorSpec.kind`; add a kind by adding a function."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from products.aegis.strategy import IndicatorSpec


def ema(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(span=length, adjust=False, min_periods=length).mean()


def sma(values: pd.Series, length: int) -> pd.Series:
    return values.rolling(length, min_periods=length).mean()


INDICATORS: dict[str, Callable[[pd.Series, int], pd.Series]] = {"EMA": ema, "SMA": sma}


def compute(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.Series:
    """Compute one indicator over `frame[spec.source]`; NaN until the window is warm."""
    try:
        function = INDICATORS[spec.kind.upper()]
    except KeyError:
        raise ValueError(f"unknown indicator kind {spec.kind!r}") from None
    if spec.source not in frame.columns:
        raise ValueError(f"unknown indicator source {spec.source!r}")
    return function(pd.to_numeric(frame[spec.source]), spec.length)


class IndicatorCache:
    """Memoizes indicator series per (data identity, kind, source, length). One array per unique
    period, shared across optimizer cells and runs."""

    def __init__(self, max_data_keys: int | None = None) -> None:
        self._series: dict[tuple[str, str, str, int], pd.Series] = {}
        self._data_keys: list[str] = []  # insertion order; the oldest is evicted first
        self.max_data_keys = max_data_keys
        self.hits = 0

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

    def get(self, data_key: str, spec: IndicatorSpec, frame: pd.DataFrame) -> pd.Series:
        key = (data_key, spec.kind.upper(), spec.source, spec.length)
        series = self._series.get(key)
        if series is None:
            self._admit(data_key)
            series = compute(spec, frame)
            self._series[key] = series
        else:
            self.hits += 1
        return series

    def __len__(self) -> int:
        return len(self._series)
