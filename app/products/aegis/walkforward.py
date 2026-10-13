"""Rolling walk-forward validation, per side (Mission 4 spec §5): pure functions only.

Windows are cut in bars; each window is optimized in-sample on the side's grid and the chosen
configuration is evaluated out-of-sample on the full history before the window, counted from its
first bar (`BacktestSettings.evaluate_from`), so its indicators equal a continuous run's; capital
and any open position chain from window to window. Nothing here runs threads or touches disk; the job
kind in `jobs.py` drives these functions and the engine.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, pstdev
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis import kernel
from products.aegis.backtest import (
    MIN_BARS,
    BacktestRequest,
    BacktestSettings,
    DataReference,
    OpenPosition,
    _metrics,
    run_backtest,
)
from products.aegis.indicators import IndicatorCache
from products.aegis.optimize import GridPlan, engine_rows, expand_grid, provenance
from products.aegis.results import result_hash, strategy_hash, walkforward_payload
from products.aegis.strategy import StrategySide, StrategySpec, apply_parameters, side_warmup

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

    @field_validator("settings")
    @classmethod
    def no_boundary_of_its_own(cls, value):
        if value.evaluate_from is not None:
            raise ValueError(
                "settings.evaluate_from is set by the walk-forward itself; leave it unset"
            )
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


def plan(
    request: WalkForwardRequest, n_bars: int, timestamps: list[str] | None = None
) -> WindowPlan:
    """Validate every bound of spec §5.2 and lay out the windows and units.

    Dead ends knowable now are refused now: a grid with no valid cell, and the `mar` objective
    on in-sample windows shorter than a year (the engine reports CAGR and MAR only from 365 days,
    so every cell would be null and every window `no_valid_cell`).
    """
    side = request.side_spec
    floor = MIN_BARS + side_warmup(side)
    if request.in_sample_bars < floor:
        raise ValueError(
            f"in_sample_bars {request.in_sample_bars} below {floor} "
            f"(35 bars plus the longest warm-up the grid can visit)"
        )
    grid = expand_grid(side)  # raises "grid too large" over 400 cells
    if not grid.cells:
        raise ValueError("grid has no valid cell: every cell has fast >= slow; widen the ranges")
    windows, tail = cut_windows(n_bars, request.in_sample_bars, request.out_of_sample_bars)
    if len(windows) > MAX_WINDOWS:
        raise ValueError(
            f"windows {len(windows)} over cap {MAX_WINDOWS}; lengthen the windows or narrow the range"
        )
    if request.objective == "mar" and timestamps:
        first = windows[0]
        span = (
            datetime.fromisoformat(timestamps[first.is_end - 1])
            - datetime.fromisoformat(timestamps[first.is_start])
        ).days
        if span < 365:
            raise ValueError(
                f"objective mar needs an in-sample span of at least 365 days; "
                f"window 0 spans {span} days; lengthen in_sample_bars or choose another objective"
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
        "carried_in": False,
        "open_at_end": False,
        "ending_cash": None,
        "ending_equity": None,
        "inherited_from": None,
    }


def flag_edge_exits(trades: list[dict]) -> list[dict]:
    """Mark trades the engine closed at a window's last bar (its end-of-data close fills on the
    signal bar itself, so `exit_signal_time == exit_time` identifies them). Copies, never mutates."""
    return [
        {**t, "window_edge_exit": t.get("exit_signal_time") == t.get("exit_time")} for t in trades
    ]


def rebase(trades: list[dict], equity: list[dict], baseline: float, exposure: float) -> dict:
    """A window's out-of-sample equity and metrics measured from `baseline`, the previous
    window's ending equity (plan ruling P3): a position carried across the join contributes its
    unrealized gain to the window that held it at the join and only the rest to the next one."""
    curve, peak = [], float(baseline)
    for point in equity:
        value = float(point["equity"])
        peak = max(peak, value)
        curve.append({**point, "drawdown": value / peak - 1 if peak else 0.0})
    return {"equity": curve, "metrics": _metrics(trades, curve, baseline, exposure)}


def _done(records: list[dict]) -> list[dict]:
    return sorted(
        (r for r in records if r.get("status") == "done" and r.get("oos")), key=lambda r: r["index"]
    )


def stitch(records: list[dict], initial_capital: float) -> dict:
    """Out-of-sample trades and equity of the done windows in order, with the full metric set;
    exposure is the bar-weighted mean of the windows' exposures."""
    done = _done(records)
    trades = [t for r in done for t in r["oos"]["trades"]]
    # Drawdown over the whole stitched curve with one running peak (each window's own points
    # measure from that window's starting capital, which hides a drawdown spanning a join).
    curve: list[dict] = []
    peak = float(initial_capital)
    for record in done:
        for point in record["oos"]["equity"]:
            equity = float(point["equity"])
            peak = max(peak, equity)
            curve.append({**point, "drawdown": equity / peak - 1 if peak else 0.0})
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


class WalkForwardJob:
    """A walk-forward as a job kind (spec §6.1–6.2): unit u is cell (u mod (cells+1)) of window
    (u div (cells+1)), the last unit of each window being its out-of-sample run."""

    name = "walkforward"

    def __init__(self, request: WalkForwardRequest, frame, pinned: Any):
        self.request = request
        self.side = request.side
        self.rows = engine_rows(frame, request.data.symbol)
        self.timestamps = [row["timestamp"] for row in self.rows]
        self.plan = plan(request, len(self.rows), self.timestamps)
        self.data = provenance(pinned)
        self.records = [pending_record(w, self.timestamps) for w in self.plan.windows]
        self.cells: dict[int, list[dict]] = {w.index: [] for w in self.plan.windows}
        self.bars_per_unit = request.in_sample_bars
        self.total_units = self.plan.total_units
        self.cache = IndicatorCache()
        self.cache_hits = 0
        self.result_hash: str | None = None
        self._per_window = self.plan.cells_per_window + 1
        self._side_key = SIDE_KEY[request.side]
        self._other_key = SIDE_KEY["short" if request.side == "long" else "long"]
        self._base_side: StrategySide = getattr(request.strategy, self._side_key)
        self._other_side: StrategySide = getattr(request.strategy, self._other_key).model_copy(
            update={"enabled": False}
        )
        # Carry-over state between out-of-sample units (spec §4.2): the cash the next window
        # starts with, the equity its metrics are measured from, and the open position, if any.
        self._chained_cash = request.settings.initial_capital
        self._chained_equity = request.settings.initial_capital
        self._carry: dict | None = None

    # -- units ----------------------------------------------------------------------------
    def _locate(self, index: int) -> tuple[int, int]:
        return index // self._per_window, index % self._per_window

    def _strategy_with(self, side: StrategySide) -> StrategySpec:
        return self.request.strategy.model_copy(
            update={self._side_key: side, self._other_key: self._other_side}
        )

    def run_unit(self, index: int) -> dict:
        window_index, unit = self._locate(index)
        window = self.plan.windows[window_index]
        if unit < self.plan.cells_per_window:
            params = self.plan.grid.cells[unit]
            result = run_backtest(
                BacktestRequest(
                    strategy=self._strategy_with(apply_parameters(self._base_side, params)),
                    bars=self.rows[window.is_start : window.is_end],
                    settings=self.request.settings,
                ),
                cache=self.cache,
            )
            return {
                "unit": "cell",
                "cell": {"index": unit, "params": params, "metrics": result[self.side]["metrics"]},
            }
        best = self.records[window_index]["best"]  # chosen at the last cell's commit
        carry = self._carry
        inherited_from = None
        if best is None and carry is not None:
            # Plan ruling P12: a carried position is never orphaned; the window keeps the most
            # recent earlier window's configuration to manage it.
            earlier = next(
                (r for r in reversed(self.records[:window_index]) if r["best"] is not None), None
            )
            if earlier is not None:
                best, inherited_from = earlier["best"], earlier["index"]
        if best is None:
            return {"unit": "oos", "oos": None}
        chosen = apply_parameters(self._base_side, best["params"])
        last = window_index == len(self.plan.windows) - 1
        settings = self.request.settings.model_copy(
            update={
                "evaluate_from": datetime.fromisoformat(self.timestamps[window.oos_start]),
                "initial_capital": self._chained_cash,
                "initial_position": OpenPosition(**carry) if carry is not None else None,
                "close_at_end": last,
            }
        )
        result = run_backtest(
            BacktestRequest(
                strategy=self._strategy_with(chosen),
                # The whole history before the window (review finding #2): recursive
                # indicators (EMA, RSI, ATR, MACD) then hold the values a continuous run holds;
                # a short lead would cold-start them and move the window's signals.
                bars=self.rows[: window.oos_end],
                settings=settings,
            ),
            cache=self.cache,
        )
        side = result[self.side]
        rebased = rebase(
            side["trades"], side["equity"], self._chained_equity, side["metrics"]["exposure"]
        )
        return {
            "unit": "oos",
            "oos": {
                "trades": flag_edge_exits(side["trades"]),
                "equity": rebased["equity"],
                "metrics": rebased["metrics"],
            },
            "carried_in": carry is not None,
            "inherited_from": inherited_from,
            "open_position": side["open_position"],
            "ending_cash": side["ending_cash"],
            "ending_equity": side["ending_equity"],
        }

    def commit(self, index: int, result: dict) -> None:
        window_index, _ = self._locate(index)
        record = self.records[window_index]
        self.cache_hits = self.cache.hits
        if result["unit"] == "cell":
            self.cells[window_index].append(result["cell"])
            record["cells_evaluated"] = len(self.cells[window_index])
            if record["cells_evaluated"] == self.plan.cells_per_window:
                best = select_best(self.cells[window_index], self.request.objective)
                record["best"] = (
                    {"params": best["params"], "metrics": best["metrics"]} if best else None
                )
                if best is None:
                    record["status"] = "no_valid_cell"
            return
        oos = result["oos"]
        if oos is None:
            record["status"] = "no_valid_cell"
            return
        record["oos"] = oos
        record["status"] = "done"
        record["inherited_from"] = result["inherited_from"]
        record["efficiency"] = (
            efficiency(
                record["best"]["metrics"], record["is_bars"], oos["metrics"], record["oos_bars"]
            )
            if record["best"] is not None
            else None
        )
        record["carried_in"] = result["carried_in"]
        record["ending_cash"] = result["ending_cash"]
        record["ending_equity"] = result["ending_equity"]
        open_position = result["open_position"]
        record["open_at_end"] = open_position is not None
        if open_position is not None and open_position.get("origin_window") is None:
            open_position = {**open_position, "origin_window": window_index}
        self._carry = open_position
        self._chained_cash = float(result["ending_cash"])
        self._chained_equity = float(result["ending_equity"])

    def release(self) -> None:
        """Drop the bar rows and the indicator cache once the job is terminal and persisted;
        the records, stitched series and stability stay for status reads."""
        self.rows = []
        self.cache = IndicatorCache()

    # -- documents ------------------------------------------------------------------------
    def _paths(self) -> list[str]:
        return [p.path for p in self._base_side.optimization if p.enabled]

    def snapshot(self) -> dict:
        records = copy.deepcopy(self.records)
        finished = sum(1 for r in records if r["status"] in ("done", "no_valid_cell"))
        return {
            "objective": self.request.objective,
            "in_sample_bars": self.request.in_sample_bars,
            "out_of_sample_bars": self.request.out_of_sample_bars,
            "windows": {"done": finished, "total": len(records)},
            "current_window": min(finished, len(records) - 1),
            "cells_per_window": self.plan.cells_per_window,
            "unused_tail_bars": self.plan.unused_tail_bars,
            "window_records": records,
            "stitched": stitch(records, self.request.settings.initial_capital),
            "stability": stability(records, self._paths()),
            "cache_hits": self.cache_hits,
            "data": self.data,
            "engine": "kernel" if kernel.AVAILABLE else "reference",
            "strategy_id": self.request.strategy.id,
            "strategy_hash": strategy_hash(self.request.strategy),
            "strategy": self.request.strategy.model_dump(mode="json"),
            "settings": self.request.settings.model_dump(mode="json"),
            "result_hash": self.result_hash,
        }

    def finalize(self, status: str) -> dict:
        if status != "done":
            return {"result_hash": None}
        records = copy.deepcopy(self.records)
        payload = walkforward_payload(
            records,
            stitch(records, self.request.settings.initial_capital),
            stability(records, self._paths()),
            self.request,
            self.data,
            self.plan.unused_tail_bars,
        )
        self.result_hash = result_hash(payload)
        return {"result_hash": self.result_hash}


__all__ = [
    "MAX_WINDOWS",
    "MIN_OOS_BARS",
    "SIDE_KEY",
    "WalkForwardJob",
    "WalkForwardRequest",
    "Window",
    "WindowPlan",
    "cut_windows",
    "efficiency",
    "flag_edge_exits",
    "pending_record",
    "plan",
    "rebase",
    "select_best",
    "side_warmup",
    "stability",
    "stitch",
]
