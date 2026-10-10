"""Rolling walk-forward validation, per side (Mission 4 spec §5): pure functions only.

Windows are cut in bars; each window is optimized in-sample on the side's grid and the chosen
configuration is evaluated out-of-sample behind a warm-up lead (`BacktestSettings.evaluate_from`),
with capital chained from window to window. Nothing here runs threads or touches disk; the job
kind in `jobs.py` drives these functions and the engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis.backtest import MIN_BARS, BacktestSettings, DataReference, _metrics
from products.aegis.optimize import GridPlan, expand_grid
from products.aegis.strategy import StrategySide, StrategySpec

MAX_WINDOWS = 50
MIN_OOS_BARS = 20
Side = Literal["long", "short"]
Objective = Literal["net_pnl", "mar", "max_drawdown", "trade_count"]
SIDE_KEY = {"long": "long_side", "short": "short_side"}


class WalkForwardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategySpec
    side: Side
    data: DataReference
    settings: BacktestSettings = Field(default_factory=BacktestSettings)
    objective: Objective = "net_pnl"
    in_sample_bars: int
    out_of_sample_bars: int

    @field_validator("in_sample_bars")
    @classmethod
    def in_sample_floor(cls, value):
        if value < MIN_BARS:
            raise ValueError(f"in_sample_bars {value} below {MIN_BARS}")
        return value

    @field_validator("out_of_sample_bars")
    @classmethod
    def out_of_sample_floor(cls, value):
        if value < MIN_OOS_BARS:
            raise ValueError(f"out_of_sample_bars {value} below {MIN_OOS_BARS}")
        return value

    @property
    def side_spec(self) -> StrategySide:
        return getattr(self.strategy, SIDE_KEY[self.side])


@dataclass(frozen=True)
class Window:
    """Half-open bar index ranges: in-sample [is_start, is_end), out-of-sample [oos_start, oos_end)."""

    index: int
    is_start: int
    is_end: int
    oos_start: int
    oos_end: int


@dataclass
class WindowPlan:
    windows: list[Window]
    unused_tail_bars: int
    grid: GridPlan
    cells_per_window: int
    total_units: int


def cut_windows(n_bars: int, in_sample: int, out_of_sample: int) -> tuple[list[Window], int]:
    """Rolling windows: window k = IS [k·oos, k·oos+is), OOS [k·oos+is, k·oos+is+oos)."""
    count = (n_bars - in_sample) // out_of_sample if n_bars >= in_sample else 0
    if count < 1:
        raise ValueError(
            f"range too short: {n_bars} bars; one window needs {in_sample} + {out_of_sample} bars"
        )
    windows = [
        Window(
            index=k,
            is_start=k * out_of_sample,
            is_end=k * out_of_sample + in_sample,
            oos_start=k * out_of_sample + in_sample,
            oos_end=k * out_of_sample + in_sample + out_of_sample,
        )
        for k in range(count)
    ]
    return windows, n_bars - in_sample - count * out_of_sample


def longest_length(side: StrategySide) -> int:
    """The longest indicator length any grid cell of this side can carry: current lengths and the
    upper ends of its enabled length ranges."""
    lengths = [spec.length for spec in side.indicators]
    lengths += [
        math.ceil(p.stop) for p in side.optimization if p.enabled and p.path.endswith(".length")
    ]
    return max(lengths, default=0)


def plan(request: WalkForwardRequest, n_bars: int) -> WindowPlan:
    """Validate every bound of spec §5.2 and lay out the windows and units."""
    side = request.side_spec
    floor = MIN_BARS + longest_length(side)
    if request.in_sample_bars < floor:
        raise ValueError(
            f"in_sample_bars {request.in_sample_bars} below {floor} "
            f"(35 bars plus the longest indicator length the grid can visit)"
        )
    grid = expand_grid(side)  # raises "grid too large" over 400 cells
    windows, tail = cut_windows(n_bars, request.in_sample_bars, request.out_of_sample_bars)
    if len(windows) > MAX_WINDOWS:
        raise ValueError(
            f"windows {len(windows)} over cap {MAX_WINDOWS}; lengthen the windows or narrow the range"
        )
    cells = len(grid.cells)
    return WindowPlan(
        windows=windows,
        unused_tail_bars=tail,
        grid=grid,
        cells_per_window=cells,
        total_units=len(windows) * (cells + 1),
    )


def select_best(cells: list[dict], objective: str) -> dict | None:
    """Best in-sample cell: objective maximized (max_drawdown minimized), nulls ignored, ties to
    the lowest grid index."""
    sign = -1.0 if objective == "max_drawdown" else 1.0
    best, best_value = None, None
    for cell in sorted(cells, key=lambda c: c["index"]):
        value = cell.get("metrics", {}).get(objective)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        scored = sign * float(value)
        if best is None or scored > best_value:
            best, best_value = cell, scored
    return best


def efficiency(is_metrics: dict | None, is_bars: int, oos_metrics: dict | None, oos_bars: int):
    """Out-of-sample net return per bar over in-sample net return per bar; null unless the
    in-sample return is positive."""
    if not is_metrics or not oos_metrics or not is_bars or not oos_bars:
        return None
    is_return, oos_return = is_metrics.get("net_return"), oos_metrics.get("net_return")
    if is_return is None or oos_return is None or is_return <= 0:
        return None
    return (oos_return / oos_bars) / (is_return / is_bars)


def lead_bars(chosen_longest: int) -> int:
    """Warm-up lead before an out-of-sample window: the chosen configuration's longest length plus
    one, but never below the engine's bar floor."""
    return max(chosen_longest + 1, MIN_BARS)


def pending_record(window: Window, timestamps: list[str]) -> dict:
    """The window record of spec §5.3 before any work: bar ranges by timestamp, everything else null."""
    return {
        "index": window.index,
        "status": "pending",
        "is_start": timestamps[window.is_start],
        "is_end": timestamps[window.is_end - 1],
        "oos_start": timestamps[window.oos_start],
        "oos_end": timestamps[window.oos_end - 1],
        "is_bars": window.is_end - window.is_start,
        "oos_bars": window.oos_end - window.oos_start,
        "cells_evaluated": 0,
        "best": None,
        "oos": None,
        "efficiency": None,
    }


def _done(records: list[dict]) -> list[dict]:
    return sorted(
        (r for r in records if r.get("status") == "done" and r.get("oos")), key=lambda r: r["index"]
    )


def stitch(records: list[dict], initial_capital: float) -> dict:
    """Out-of-sample trades and equity of the done windows in order, with the full metric set;
    exposure is the bar-weighted mean of the windows' exposures."""
    done = _done(records)
    trades = [t for r in done for t in r["oos"]["trades"]]
    curve = [p for r in done for p in r["oos"]["equity"]]
    bars = sum(r["oos_bars"] for r in done)
    exposure = (
        sum(float(r["oos"]["metrics"].get("exposure") or 0.0) * r["oos_bars"] for r in done) / bars
        if bars
        else 0.0
    )
    return {
        "trades": trades,
        "equity": curve,
        "metrics": _metrics(trades, curve, initial_capital, exposure),
    }


def stability(records: list[dict], paths: list[str]) -> dict:
    """Spread of each chosen parameter across the done windows, how many windows made money
    out-of-sample, and the mean efficiency."""
    done = [r for r in _done(records) if r.get("best")]
    parameters = {}
    for path in paths:
        values = [float(r["best"]["params"][path]) for r in done if path in r["best"]["params"]]
        parameters[path] = (
            {"min": min(values), "max": max(values), "mean": fmean(values), "std": pstdev(values)}
            if values
            else {"min": None, "max": None, "mean": None, "std": None}
        )
    efficiencies = [r["efficiency"] for r in done if r.get("efficiency") is not None]
    return {
        "parameters": parameters,
        "positive_oos_windows": sum(
            1 for r in done if (r["oos"]["metrics"].get("net_pnl") or 0.0) > 0
        ),
        "windows_evaluated": len(done),
        "mean_efficiency": fmean(efficiencies) if efficiencies else None,
    }


__all__ = [
    "MAX_WINDOWS",
    "MIN_OOS_BARS",
    "SIDE_KEY",
    "WalkForwardRequest",
    "Window",
    "WindowPlan",
    "cut_windows",
    "efficiency",
    "lead_bars",
    "longest_length",
    "pending_record",
    "plan",
    "select_best",
    "stability",
    "stitch",
]
