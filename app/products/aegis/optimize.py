"""Per-side grid optimizer (spec §2b.9, §7): grid expansion, heatmap, and the optimizer job kind.

One side at a time: the grid is the cartesian product of that side's enabled optimization
parameters; cells whose entry-rule fast length is not below the slow length are skipped and
reported. Cells run as units of a `JobRunner` job (`jobs.py`): one worker thread, progressive
results, cooperative cancel, persistence from start, `lost` on restart, learned per-bar cost.

A grid of more than SERIAL_MAX_CELLS cells (the limits change, 2026-10-20) runs in chunks on the
experiments' process pool instead: a unit is a chunk of `workers x CHUNK_PER_WORKER` cells, and
progress, cancel and the save follow the chunk. Its cells equal the serial path's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis import kernel
from products.aegis.backtest import BacktestRequest, BacktestSettings, DataReference, run_backtest
from products.aegis.indicators import IndicatorCache
from products.aegis.jobs import MS_PER_BAR, UNFINISHED, JobBusy, JobRunner, estimate_seconds
from products.aegis.kinds import kind_info
from products.aegis.results import strategy_hash
from products.aegis.runs import RunRepository
from products.aegis.strategy import RuleSpec, StrategySide, StrategySpec, apply_parameters

SERIAL_MAX_CELLS = 400  # up to here a grid runs serially, one cell per unit, as before
MAX_CELLS = 100_000  # a grid is enumerated in memory; larger surfaces are an experiment's
CHUNK_PER_WORKER = 32  # cells per pool worker in one unit of a pooled grid
OBJECTIVES = ("net_pnl", "mar", "max_drawdown", "trade_count")

Side = Literal["long", "short"]
Objective = Literal["net_pnl", "mar", "max_drawdown", "trade_count"]
SIDE_KEY = {"long": "long_side", "short": "short_side"}


def plain_settings(value: BacktestSettings, *fields: str) -> BacktestSettings:
    """Refuse the settings a job sets for its own units (P14 item 5): every cell runs over the
    whole range from a flat start and closes at the end; the walk-forward also owns the warm-up
    boundary. The message names the field so the form can point at it."""
    clean = {
        "evaluate_from": value.evaluate_from is None,
        "initial_position": value.initial_position is None,
        "close_at_end": value.close_at_end,
    }
    for name in fields:
        if not clean[name]:
            raise ValueError(f"settings.{name} is set by the job itself; leave it unset")
    return value


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: StrategySpec
    side: Side
    data: DataReference
    settings: BacktestSettings = Field(default_factory=BacktestSettings)
    objective: Objective = "net_pnl"

    @field_validator("settings")
    @classmethod
    def plain(cls, value):
        return plain_settings(value, "initial_position", "close_at_end")


@dataclass
class GridPlan:
    cells: list[dict[str, float]]
    skipped: list[dict[str, float]]
    fast_values: list[float]
    slow_values: list[float]
    fast_path: str = ""  # the heatmap's row axis
    slow_path: str = ""  # the heatmap's column axis
    skip_reason: str | None = None


def step_decimals(step: float) -> int:
    """Decimal places of a grid step, so values read as the operator typed them (P14 item 7)."""
    text = repr(float(step))
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


def _values(start: float, stop: float, step: float) -> list[float]:
    count = math.floor((stop - start) / step + 1e-9) + 1
    decimals = step_decimals(step)
    return [round(float(start + i * step), decimals) for i in range(max(count, 0))]


def expand_grid(side: StrategySide) -> GridPlan:
    """Cartesian product of the side's enabled parameters, split into cells and skipped cells.

    Axes (plan ruling P6): a single crossover entry rule between two single-series indicators
    whose lengths are both in the grid keeps the fast (left) / slow (right) axes, and cells with
    fast length >= slow length are skipped; otherwise the axes are the first two enabled paths.
    Cells whose parameters make the side invalid (MACD fast >= slow) are skipped too. More than
    MAX_CELLS total is rejected. A grid with only one enabled axis is valid; its heatmap has no
    columns.
    """
    parameters = [p for p in side.optimization if p.enabled]
    if not parameters:
        raise ValueError("no enabled optimization parameters on this side")
    axes = [(p.path, _values(p.start, p.stop, p.step)) for p in parameters]
    total = math.prod(len(values) for _, values in axes)
    if total > MAX_CELLS:
        raise ValueError(
            f"grid too large: {total} cells over cap {MAX_CELLS}; narrow the ranges, or run an "
            "experiment, which samples a larger surface and refines it"
        )
    by_path = dict(axes)
    crossover = _crossover_axes(side, by_path)
    if crossover is not None:
        rows, columns = crossover
    else:
        rows = axes[0][0]
        columns = axes[1][0] if len(axes) > 1 else ""
    cells: list[dict[str, float]] = [{}]
    for path, values in axes:
        cells = [{**cell, path: value} for cell in cells for value in values]
    kept, skipped, reasons = [], [], []
    for cell in cells:
        if crossover is not None and round(cell[rows]) >= round(cell[columns]):
            skipped.append(cell)
            reasons.append("fast ≥ slow")
            continue
        try:
            apply_parameters(side, cell)
        except ValueError:
            skipped.append(cell)
            reasons.append("invalid parameter combinations")
            continue
        kept.append(cell)
    return GridPlan(
        cells=kept,
        skipped=skipped,
        fast_values=by_path.get(rows, []),
        slow_values=by_path.get(columns, []),
        fast_path=rows,
        slow_path=columns,
        skip_reason="; ".join(dict.fromkeys(reasons)) or None,
    )


def _crossover_axes(side: StrategySide, by_path: dict) -> tuple[str, str] | None:
    """(fast path, slow path) when the entry rule is the classic crossover of two single-series
    indicators whose lengths are both in the grid; otherwise None."""
    rule = side.entry
    if not isinstance(rule, RuleSpec) or rule.operator not in ("crosses_above", "crosses_below"):
        return None
    ids = {spec.id: spec for spec in side.indicators}
    for operand in (rule.left, rule.right):
        if operand not in ids or kind_info(ids[operand].kind).outputs:
            return None
    fast, slow = f"indicators.{rule.left}.length", f"indicators.{rule.right}.length"
    return (fast, slow) if fast in by_path and slow in by_path else None


def plan_seconds(
    cells: int,
    bars: int,
    ms_per_bar: float,
    pool_ms_per_cell_bar: float | None,
    workers: int,
) -> float:
    """A grid's estimate: serial at the host's per-bar cost, or on the pool at its measured cost
    per cell-bar (the host's until the pool has one) spread across its workers."""
    if cells <= SERIAL_MAX_CELLS:
        return estimate_seconds(cells, bars, ms_per_bar)
    rate = pool_ms_per_cell_bar or ms_per_bar
    return cells * bars * rate / max(1, workers) / 1000.0


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
    """One grid optimization as a job kind; the other side is disabled. A unit is one cell, or
    for a grid of more than SERIAL_MAX_CELLS cells one chunk run on the process pool."""

    name = "optimization"

    def __init__(
        self, request: OptimizeRequest, frame: pd.DataFrame, pinned: Any, pool_factory=None
    ):
        self.request = request
        self.side = request.side
        self.plan = expand_grid(getattr(request.strategy, SIDE_KEY[request.side]))
        self.rows = engine_rows(frame, request.data.symbol)
        self.data = provenance(pinned)
        self.bars = len(self.rows)
        self.pooled = len(self.plan.cells) > SERIAL_MAX_CELLS
        self.pool = None
        if self.pooled:
            from products.aegis.pool import Pool, default_workers

            self._pool_factory = pool_factory or Pool
            workers = getattr(self._pool_factory(), "max_workers", None) or default_workers()
            self.chunk = max(1, workers * CHUNK_PER_WORKER)
            self.total_units = math.ceil(len(self.plan.cells) / self.chunk)
            # The pool prices itself; a pooled job never teaches the host its serial cost.
            self.bars_per_unit = 0
        else:
            self.chunk = 1
            self.total_units = len(self.plan.cells)
            self.bars_per_unit = len(self.rows)
        self.cells: list[dict] = []
        self.planned_seconds: float | None = None  # a pooled job's estimate until a chunk is done
        self.cache = IndicatorCache()
        self.cache_hits = 0
        self._side_key = SIDE_KEY[request.side]
        self._other_key = SIDE_KEY["short" if request.side == "long" else "long"]
        self._base_side: StrategySide = getattr(request.strategy, self._side_key)
        self._other_side: StrategySide = getattr(request.strategy, self._other_key).model_copy(
            update={"enabled": False}
        )

    def _pooled_unit(self, index: int) -> list[dict]:
        if self.pool is None:
            spec = self.request.strategy.model_copy(update={self._other_key: self._other_side})
            self.pool = self._pool_factory()
            self.pool.start(
                self.rows,
                self.request.data.symbol,
                spec.model_dump(mode="json"),
                self.request.settings.model_dump(mode="json"),
            )
        first = index * self.chunk
        batch = self.plan.cells[first : first + self.chunk]
        rows = self.pool.run_chunk(
            [
                (first + i, {f"{self._side_key}.{path}": value for path, value in params.items()})
                for i, params in enumerate(batch)
            ],
            want_curve=False,
        )
        cells = []
        for params, row in zip(batch, sorted(rows, key=lambda r: r["cell"]), strict=True):
            metrics = row["metrics"][self.side] if row["valid"] else dict.fromkeys(OBJECTIVES)
            cell = {
                "params": params,
                "fast": params.get(self.plan.fast_path),
                "slow": params.get(self.plan.slow_path),
                "metrics": metrics,
            }
            if not row["valid"]:
                cell["skip_reason"] = row["skip_reason"]
            cells.append(cell)
        return cells

    def run_unit(self, index: int):
        if self.pooled:
            return self._pooled_unit(index)
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

    def commit(self, index: int, cell) -> None:
        if self.pooled:
            self.cells.extend(cell)
        else:
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
            "cells_done": len(cells),
            "pooled": self.pooled,
            **({"bars": self.bars} if self.pooled else {}),
            **(
                {"estimated_seconds": round(self.planned_seconds, 3)}
                if self.pooled and not cells and self.planned_seconds is not None
                else {}
            ),
            "data": self.data,
            "engine": "kernel" if kernel.AVAILABLE else "reference",
            "strategy_id": self.request.strategy.id,
            "strategy_hash": strategy_hash(self.request.strategy),
            "strategy": self.request.strategy.model_dump(mode="json"),
            "settings": self.request.settings.model_dump(mode="json"),
        }

    def finalize(self, status: str) -> dict:
        return {}

    def release(self) -> None:
        """Drop the bar rows, the cache and the pool once terminal and persisted; cells and
        matrices stay."""
        if self.pool is not None:
            self.pool.shutdown()
            self.pool = None
        self.rows = []
        self.cache = IndicatorCache()


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
    "CHUNK_PER_WORKER",
    "MAX_CELLS",
    "MS_PER_BAR",
    "OBJECTIVES",
    "SERIAL_MAX_CELLS",
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
    "plan_seconds",
    "provenance",
]
