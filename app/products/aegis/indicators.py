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

    def __init__(self) -> None:
        self._series: dict[tuple[str, str, str, int], pd.Series] = {}
        self.hits = 0

    def get(self, data_key: str, spec: IndicatorSpec, frame: pd.DataFrame) -> pd.Series:
        key = (data_key, spec.kind.upper(), spec.source, spec.length)
        series = self._series.get(key)
        if series is None:
            series = compute(spec, frame)
            self._series[key] = series
        else:
            self.hits += 1
        return series

    def __len__(self) -> int:
        return len(self._series)
