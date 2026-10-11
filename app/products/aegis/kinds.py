"""Indicator kind metadata (Mission 5 spec §5.1, plan ruling P7).

Declared once, with no Aegis imports, so the strategy contract (validation), the engine
(warm-up, outputs) and the generated TypeScript (`INDICATOR_KINDS` in `contracts.ts`) all read
the same table. Compute functions live in `indicators.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class KindInfo:
    """One indicator kind: its outputs (empty for a single series), the chart pane it belongs
    on, the bar columns it reads (`source` means the spec's own source column), the length a new
    indicator starts with, its warm-up (the sum of the named values plus an offset: the number of
    bars after which every output has a value), and its extra parameters with defaults, of which
    `integer_params` must be whole numbers."""

    outputs: tuple[str, ...]
    pane: Literal["price", "own"]
    requires: tuple[str, ...]
    default_length: int
    warmup_terms: tuple[str, ...]
    warmup_offset: int
    params: dict[str, float] = field(default_factory=dict)
    integer_params: frozenset[str] = frozenset()


KINDS: dict[str, KindInfo] = {
    "EMA": KindInfo((), "price", ("source",), 9, ("length",), 0),
    "SMA": KindInfo((), "price", ("source",), 30, ("length",), 0),
    "RSI": KindInfo((), "own", ("source",), 14, ("length",), 1),
    "ATR": KindInfo((), "own", ("high", "low", "close"), 14, ("length",), 1),
    "BB": KindInfo(
        ("upper", "middle", "lower"), "price", ("source",), 20, ("length",), 0, {"multiplier": 2.0}
    ),
    "DONCHIAN": KindInfo(
        ("upper", "lower", "middle"), "price", ("high", "low"), 20, ("length",), 1
    ),
    # Plan ruling P5: all three MACD outputs wait for the signal line, so the warm-up is exact.
    "MACD": KindInfo(
        ("line", "signal", "histogram"),
        "own",
        ("source",),
        12,
        ("slow", "signal"),
        -1,
        {"slow": 26.0, "signal": 9.0},
        frozenset({"slow", "signal"}),
    ),
}

BAND_KINDS = frozenset(k for k, info in KINDS.items() if {"upper", "lower"} <= set(info.outputs))


def kind_info(kind: str) -> KindInfo:
    try:
        return KINDS[kind.upper()]
    except KeyError:
        raise ValueError(f"unknown indicator kind {kind!r}") from None


def warmup(kind: str, length: int, params: dict[str, float] | None = None) -> int:
    """Bars after which every output of this indicator has a value."""
    info = kind_info(kind)
    values = {"length": length, **info.params, **(params or {})}
    return round(sum(float(values[term]) for term in info.warmup_terms)) + info.warmup_offset


__all__ = ["BAND_KINDS", "KINDS", "KindInfo", "kind_info", "warmup"]
