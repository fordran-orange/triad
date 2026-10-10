"""Per-side grid optimizer (spec §2b.9, §7): grid expansion, heatmap, and the optimizer job kind.

One side at a time: the grid is the cartesian product of that side's enabled optimization
parameters; cells whose entry-rule fast length is not below the slow length are skipped and
reported. Cells run as units of a `JobRunner` job (`jobs.py`): one worker thread, progressive
results, cooperative cancel, persistence from start, `lost` on restart, learned per-bar cost.
No process pools, no vectorized rewrite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from products.aegis.backtest import BacktestRequest, BacktestSettings, DataReference, run_backtest
from products.aegis.indicators import IndicatorCache
from products.aegis.jobs import MS_PER_BAR, UNFINISHED, JobBusy, JobRunner, estimate_seconds
from products.aegis.runs import RunRepository
from products.aegis.strategy import StrategySide, StrategySpec, apply_parameters

MAX_CELLS = 400
OBJECTIVES = ("net_pnl", "mar", "max_drawdown", "trade_count")

Side = Literal["long", "short"]
Objective = Literal["net_pnl", "mar", "max_drawdown", "trade_count"]
SIDE_KEY = {"long": "long_side", "short": "short_side"}


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategySpec
    side: Side
    data: DataReference
    settings: BacktestSettings = Field(default_factory=BacktestSettings)
    objective: Objective = "net_pnl"


@dataclass
class GridPlan:
    cells: list[dict[str, float]]
    skipped: list[dict[str, float]]
    fast_values: list[float]
    slow_values: list[float]
    fast_path: str = ""
    slow_path: str = ""


def _values(start: float, stop: float, step: float) -> list[float]:
    count = math.floor((stop - start) / step + 1e-9) + 1
    return [float(start + i * step) for i in range(max(count, 0))]


def expand_grid(side: StrategySide) -> GridPlan:
    """Cartesian product of the side's enabled parameters, split into cells and skipped cells.

    The entry rule's left indicator is the fast axis and its right indicator the slow axis;
    a cell with fast length >= slow length is skipped. More than MAX_CELLS total is rejected.
    A grid with only one enabled axis is valid; its heatmap has no columns.
    """
    parameters = [p for p in side.optimization if p.enabled]
    if not parameters:
        raise ValueError("no enabled optimization parameters on this side")
    axes = [(p.path, _values(p.start, p.stop, p.step)) for p in parameters]
    total = math.prod(len(values) for _, values in axes)
    if total > MAX_CELLS:
        raise ValueError(f"grid too large: {total} cells over cap {MAX_CELLS}; narrow the ranges")
    fast_path = f"indicators.{side.entry.left}.length"
    slow_path = f"indicators.{side.entry.right}.length"
    by_path = dict(axes)
    cells: list[dict[str, float]] = [{}]
    for path, values in axes:
        cells = [{**cell, path: value} for cell in cells for value in values]
    kept, skipped = [], []
    for cell in cells:
        fast, slow = cell.get(fast_path), cell.get(slow_path)
        if fast is not None and slow is not None and round(fast) >= round(slow):
            skipped.append(cell)
        else:
            kept.append(cell)
    return GridPlan(
        cells=kept,
        skipped=skipped,
        fast_values=by_path.get(fast_path, []),
        slow_values=by_path.get(slow_path, []),
        fast_path=fast_path if fast_path in by_path else "",
        slow_path=slow_path if slow_path in by_path else "",
    )


def heatmap(
    cells: list[dict], fast_values: list[float], slow_values: list[float], metric: str
) -> list[list[float | None]]:
    """Rows fast ascending, columns slow ascending; None where skipped, pending or undefined.

    Cells without both axis values (a one-axis grid) have no place in a matrix and are ignored.
    """
    lookup: dict[tuple[float, float], float | None] = {}
    for cell in cells:
        if cell.get("fast") is None or cell.get("slow") is None:
            continue
        value = cell.get("metrics", {}).get(metric)
        lookup[(float(cell["fast"]), float(cell["slow"]))] = (
            None
            if value is None or (isinstance(value, float) and math.isnan(value))
            else float(value)
        )
    return [
        [lookup.get((fast, slow)) for slow in sorted(slow_values)] for fast in sorted(fast_values)
    ]


def engine_rows(frame: pd.DataFrame, symbol: str) -> list[dict]:
    """Archive frame rows in the engine's input shape (ISO timestamps, symbol attached)."""
    rows = frame.to_dict("records")
    for row in rows:
        row["timestamp"] = row["timestamp"].isoformat()
        row["symbol"] = symbol
    return rows


def provenance(pinned: Any) -> dict:
    return pinned.model_dump(mode="json") if hasattr(pinned, "model_dump") else dict(pinned)


class OptimizerJob:
    """One grid optimization as a job kind: a unit is one cell; the other side is disabled."""

    name = "optimization"

    def __init__(self, request: OptimizeRequest, frame: pd.DataFrame, pinned: Any):
        self.request = request
        self.side = request.side
        self.plan = expand_grid(getattr(request.strategy, SIDE_KEY[request.side]))
        self.rows = engine_rows(frame, request.data.symbol)
        self.data = provenance(pinned)
        self.bars_per_unit = len(self.rows)
        self.total_units = len(self.plan.cells)
        self.cells: list[dict] = []
        self.cache = IndicatorCache()
        self.cache_hits = 0
        self._side_key = SIDE_KEY[request.side]
        self._other_key = SIDE_KEY["short" if request.side == "long" else "long"]
        self._base_side: StrategySide = getattr(request.strategy, self._side_key)
        self._other_side: StrategySide = getattr(request.strategy, self._other_key).model_copy(
            update={"enabled": False}
        )

    def run_unit(self, index: int) -> dict:
        params = self.plan.cells[index]
        strategy = self.request.strategy.model_copy(
            update={
                self._side_key: apply_parameters(self._base_side, params),
                self._other_key: self._other_side,
            }
        )
        result = run_backtest(
            BacktestRequest(strategy=strategy, bars=self.rows, settings=self.request.settings),
            cache=self.cache,
        )
        return {
            "params": params,
            "fast": params.get(self.plan.fast_path),
            "slow": params.get(self.plan.slow_path),
            "metrics": result[self.side]["metrics"],
        }

    def commit(self, index: int, cell: dict) -> None:
        self.cells.append(cell)
        self.cache_hits = self.cache.hits

    def snapshot(self) -> dict:
        plan, cells = self.plan, list(self.cells)
        return {
            "objective": self.request.objective,
            "total_cells": len(plan.cells),
            "skipped_cells": len(plan.skipped),
            "skipped": list(plan.skipped),
            "cells": cells,
            "matrices": {
                metric: {self.side: heatmap(cells, plan.fast_values, plan.slow_values, metric)}
                for metric in OBJECTIVES
            },
            "fast_values": list(plan.fast_values),
            "slow_values": list(plan.slow_values),
            "fast_path": plan.fast_path,
            "slow_path": plan.slow_path,
            "cache_hits": self.cache_hits,
            "data": self.data,
            "strategy": self.request.strategy.model_dump(mode="json"),
            "settings": self.request.settings.model_dump(mode="json"),
        }

    def finalize(self, status: str) -> dict:
        return {}


class OptimizerRunner(JobRunner):
    """The Mission 3 entry point, kept for the optimizer tests and the API dependency override:
    `start()` accepts either an optimizer request triple or any job kind."""

    def __init__(self, repository: RunRepository, max_workers: int = 1, after_cell=None):
        super().__init__(repository, max_workers=max_workers, after_unit=after_cell)

    def start(self, kind_or_request, frame: pd.DataFrame | None = None, pinned: Any = None) -> str:
        if isinstance(kind_or_request, OptimizeRequest):
            return super().start(OptimizerJob(kind_or_request, frame, pinned))
        return super().start(kind_or_request)


__all__ = [
    "MAX_CELLS",
    "MS_PER_BAR",
    "OBJECTIVES",
    "UNFINISHED",
    "GridPlan",
    "JobBusy",
    "OptimizeRequest",
    "OptimizerJob",
    "OptimizerRunner",
    "engine_rows",
    "estimate_seconds",
    "expand_grid",
    "heatmap",
    "provenance",
]
