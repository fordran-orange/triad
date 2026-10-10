"""Temporal context: windows qualify and tag strategy opportunities.

Precedence (spec §2b.5): BLOCK always wins; with one or more ALLOW clock windows an entry
must fall inside at least one ALLOW window and outside every BLOCK window; ANALYZE never
changes execution (tags only); MODIFY_RISK is rejected explicitly. Exits are never suppressed.
Market crossovers are clock-defined windows on the strategy timezone (ANALYZE-only here).
Event windows match hand-supplied events only; no feed exists yet.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from products.aegis.strategy import TemporalContext, WindowMode


def validate(temporal: TemporalContext) -> None:
    """Reject modes this slice does not implement, before any simulation runs."""
    windows = [*temporal.clock_windows, *temporal.event_windows, *temporal.market_crossovers]
    for window in windows:
        if window.mode is WindowMode.MODIFY_RISK:
            raise ValueError("unsupported window mode: MODIFY_RISK")


def _local_hhmm(timestamp: pd.Timestamp, temporal: TemporalContext) -> str:
    return timestamp.tz_convert(ZoneInfo(temporal.timezone)).strftime("%H:%M")


def _inside(hhmm: str, start: str, end: str) -> bool:
    return start <= hhmm < end


def entry_permitted(timestamp: pd.Timestamp, temporal: TemporalContext) -> bool:
    """Whether a new entry whose signal bar is `timestamp` may be taken."""
    hhmm = _local_hhmm(timestamp, temporal)
    clock = [w for w in temporal.clock_windows if w.mode in (WindowMode.BLOCK, WindowMode.ALLOW)]
    if any(w.mode is WindowMode.BLOCK and _inside(hhmm, w.start, w.end) for w in clock):
        return False
    allows = [w for w in clock if w.mode is WindowMode.ALLOW]
    if allows:
        return any(_inside(hhmm, w.start, w.end) for w in allows)
    return True


def tags(timestamp: pd.Timestamp, temporal: TemporalContext, events, symbol: str | None):
    """Sorted analysis tags for a bar: CLOCK:<id>, CROSSOVER:<id>, EVENT:<type>."""
    hhmm = _local_hhmm(timestamp, temporal)
    found: set[str] = set()
    for window in temporal.clock_windows:
        if _inside(hhmm, window.start, window.end):
            found.add(f"CLOCK:{window.id}")
    for crossover in temporal.market_crossovers:
        if crossover.enabled and _inside(hhmm, crossover.start, crossover.end):
            found.add(f"CROSSOVER:{crossover.id}")
    instant = timestamp.to_pydatetime()
    for config in temporal.event_windows:
        if not config.enabled:
            continue
        for event in events:
            if event.event_type != config.event_type:
                continue
            if event.symbol and symbol and event.symbol != symbol:
                continue
            delta_minutes = (instant - event.timestamp).total_seconds() / 60
            if -config.minutes_before <= delta_minutes <= config.minutes_after:
                found.add(f"EVENT:{config.event_type}")
                break
    return tuple(sorted(found))
