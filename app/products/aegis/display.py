"""Aegis display candles (Mission 10 spec §7).

A long selection is drawn as at most MAX_DISPLAY_BARS candles: the native bars when they fit,
else the finest coarser standard timeframe whose candles over the window fit. Indicators are
computed on the native bars of the whole selection (warm-up unchanged) and each displayed candle
carries the native value at its bucket's last bar, so the series stay index-aligned to what is
drawn. Nothing here touches what is simulated or hashed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from products.aegis.data import TIMEFRAMES, TIMEZONE

MAX_DISPLAY_BARS = 20_000


def choose_timeframe(native: str, counts: dict[str, int], max_bars: int) -> str:
    """The finest standard timeframe at or above `native` whose count over the window fits
    `max_bars`; the coarsest counted one when none does."""
    counted = [tf for tf in TIMEFRAMES[TIMEFRAMES.index(native) :] if tf in counts]
    for timeframe in counted:
        if counts[timeframe] <= max_bars:
            return timeframe
    return counted[-1] if counted else native


def times_ms(frame: pd.DataFrame) -> np.ndarray:
    """Each bar's epoch milliseconds, as the bars route reports them."""
    return frame["timestamp"].astype("int64").to_numpy() // 1_000_000


def bucket_starts_ms(frame: pd.DataFrame, timeframe: str) -> np.ndarray:
    """Where each candle's bucket of native bars starts: the candle's own time intraday (the
    buckets are anchored at the candles), local midnight of its session day for 1D."""
    if timeframe != "1D":
        return times_ms(frame)
    days = frame["timestamp"].dt.tz_convert(TIMEZONE).dt.normalize()
    return days.astype("int64").to_numpy() // 1_000_000


def sample_at_buckets(
    native_times_ms: np.ndarray,
    values: Sequence[float | None],
    bucket_times_ms: np.ndarray,
    window_end_ms: int,
) -> list[float | None]:
    """The value at each bucket's last native bar - bucket k runs from its start to the next
    bucket's start, the last one through `window_end_ms` - and None for an empty bucket."""
    native = np.asarray(native_times_ms, dtype=np.int64)
    starts = np.asarray(bucket_times_ms, dtype=np.int64)
    if not len(starts):
        return []
    ends = np.append(starts[1:], np.int64(window_end_ms) + 1)
    first = np.searchsorted(native, starts, side="left")
    last = np.searchsorted(native, ends, side="left") - 1
    held = np.asarray(values, dtype=np.float64)
    picked = (
        held[np.clip(last, 0, max(len(held) - 1, 0))] if len(held) else np.full(len(starts), np.nan)
    )
    keep = (last >= first) & ~np.isnan(picked)
    return [float(v) if k else None for v, k in zip(picked.tolist(), keep.tolist(), strict=True)]


def native_window(native_ms: np.ndarray, from_ms: int, to_ms: int) -> tuple[int, int]:
    """The index range of the native bars inside [from_ms, to_ms]."""
    return (
        int(np.searchsorted(native_ms, from_ms, side="left")),
        int(np.searchsorted(native_ms, to_ms, side="right")),
    )


def candle_window(starts_ms: np.ndarray, from_ms: int, to_ms: int) -> tuple[int, int]:
    """The index range of the candles whose buckets overlap [from_ms, to_ms]."""
    first = max(int(np.searchsorted(starts_ms, from_ms, side="right")) - 1, 0)
    return first, int(np.searchsorted(starts_ms, to_ms, side="right"))


@dataclass(frozen=True)
class Shown:
    """What a window of a selection is drawn as."""

    timeframe: str
    frame: pd.DataFrame  # the drawn timeframe's bars over the whole selection
    first: int  # the window's candles are frame.iloc[first:last]
    last: int
    starts_ms: np.ndarray | None  # the candles' bucket starts when aggregated; None when native
    window: dict


def choose(
    native: pd.DataFrame,
    timeframe: str,
    max_bars: int | None,
    from_ms: int | None,
    to_ms: int | None,
    frame_for: Callable[[str], pd.DataFrame],
) -> Shown:
    """The native bars of the window when they fit `max_bars` (or no bound is asked), else the
    candles of the finest coarser timeframe that fits; `frame_for(tf)` selects a timeframe over
    the same selection."""
    native_ms = times_ms(native)
    if not len(native_ms):
        return Shown(timeframe, native, 0, 0, None, {"from_ms": from_ms, "to_ms": to_ms})
    lo = int(native_ms[0]) if from_ms is None else int(from_ms)
    hi = int(native_ms[-1]) if to_ms is None else int(to_ms)
    window = {"from_ms": lo, "to_ms": hi}
    first, last = native_window(native_ms, lo, hi)
    if max_bars is None or last - first <= max_bars:
        return Shown(timeframe, native, first, last, None, window)
    counts, candidates = {timeframe: last - first}, {}
    for coarser in TIMEFRAMES[TIMEFRAMES.index(timeframe) + 1 :]:
        frame = frame_for(coarser)
        starts = bucket_starts_ms(frame, coarser)
        span = candle_window(starts, lo, hi)
        counts[coarser], candidates[coarser] = span[1] - span[0], (frame, span, starts)
        if counts[coarser] <= max_bars:
            break
    chosen = choose_timeframe(timeframe, counts, max_bars)
    if chosen == timeframe:  # a native 1D selection is never aggregated
        return Shown(timeframe, native, first, last, None, window)
    frame, (first, last), starts = candidates[chosen]
    return Shown(chosen, frame, first, last, starts, window)


__all__ = [
    "MAX_DISPLAY_BARS",
    "Shown",
    "bucket_starts_ms",
    "candle_window",
    "choose",
    "choose_timeframe",
    "native_window",
    "sample_at_buckets",
    "times_ms",
]
