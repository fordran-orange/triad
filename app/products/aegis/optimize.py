"""Per-side grid optimizer (spec §2b.9, §7).

One side at a time: the grid is the cartesian product of that side's enabled optimization
parameters; cells whose entry-rule fast length is not below the slow length are skipped and
reported. Cells run on a single dedicated worker thread (one job at a time), results are
appended progressively under a lock, cancel is cooperative between cells, and finished or
cancelled jobs are persisted through the RunRepository. Unfinished persisted jobs are marked
`lost` on startup. No process pools, no vectorized rewrite: cell cost is measured and estimated.
"""

from __future__ import annotations

import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from products.aegis.backtest import BacktestRequest, BacktestSettings, DataReference, run_backtest
from products.aegis.indicators import IndicatorCache
from products.aegis.runs import RunRepository
from products.aegis.strategy import StrategySide, StrategySpec, apply_parameters

MAX_CELLS = 400
OBJECTIVES = ("net_pnl", "mar", "max_drawdown", "trade_count")
# Measured in Task 10 on this host: 4.7 s for 3,493 bars with both sides simulated, i.e. about
# 0.7 ms per bar per side with the current per-row engine loop. An optimizer cell runs one side.
MS_PER_BAR = 0.7
UNFINISHED = ("queued", "running")

Side = Literal["long", "short"]
Objective = Literal["net_pnl", "mar", "max_drawdown", "trade_count"]
SIDE_KEY = {"long": "long_side", "short": "short_side"}


class JobBusy(RuntimeError):
    """Another optimization is still queued or running; one job at a time (spec §7)."""


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


def estimate_seconds(cells: int, bars: int, ms_per_bar: float = MS_PER_BAR) -> float:
    return cells * bars * ms_per_bar / 1000.0


def heatmap(
    cells: list[dict], fast_values: list[float], slow_values: list[float], metric: str
) -> list[list[float | None]]:
    """Rows fast ascending, columns slow ascending; None where skipped, pending or undefined."""
    lookup: dict[tuple[float, float], float | None] = {}
    for cell in cells:
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


@dataclass
class _Job:
    job_id: str
    request: OptimizeRequest
    plan: GridPlan
    rows: list[dict]
    data: dict
    created_at: str
    status: str = "queued"
    cells: list[dict] = field(default_factory=list)
    started: float | None = None
    elapsed_ms: int = 0
    cache_hits: int = 0
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)


class OptimizerRunner:
    """Runs one optimization at a time on a dedicated thread and answers progress snapshots."""

    def __init__(self, repository: RunRepository, max_workers: int = 1, after_cell=None):
        self._repository = repository
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aegis-optimizer"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._after_cell = after_cell  # test hook: called with the completed-cell count

    def start(self, request: OptimizeRequest, frame: pd.DataFrame, pinned: Any) -> str:
        side_spec: StrategySide = getattr(request.strategy, SIDE_KEY[request.side])
        plan = expand_grid(side_spec)
        data = pinned.model_dump(mode="json") if hasattr(pinned, "model_dump") else dict(pinned)
        job = _Job(
            job_id=str(uuid.uuid4()),
            request=request,
            plan=plan,
            rows=engine_rows(frame, request.data.symbol),
            data=data,
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            running = [j for j in self._jobs.values() if j.status in UNFINISHED]
            if running:
                raise JobBusy(running[0].job_id)
            self._jobs[job.job_id] = job
        self._executor.submit(self._run, job)
        return job.job_id

    def _run(self, job: _Job) -> None:
        request = job.request
        side_key, other_key = (
            SIDE_KEY[request.side],
            SIDE_KEY["short" if request.side == "long" else "long"],
        )
        base_side: StrategySide = getattr(request.strategy, side_key)
        other_side: StrategySide = getattr(request.strategy, other_key).model_copy(
            update={"enabled": False}
        )
        cache = IndicatorCache()
        with self._lock:
            job.status = "running"
            job.started = time.perf_counter()
        try:
            for params in job.plan.cells:
                if job.cancel.is_set():
                    break
                strategy = request.strategy.model_copy(
                    update={side_key: apply_parameters(base_side, params), other_key: other_side}
                )
                result = run_backtest(
                    BacktestRequest(strategy=strategy, bars=job.rows, settings=request.settings),
                    cache=cache,
                )
                cell = {
                    "params": params,
                    "fast": params.get(job.plan.fast_path),
                    "slow": params.get(job.plan.slow_path),
                    "metrics": result[request.side]["metrics"],
                }
                with self._lock:
                    job.cells.append(cell)
                    job.cache_hits = cache.hits
                    job.elapsed_ms = int((time.perf_counter() - job.started) * 1000)
                if self._after_cell is not None:
                    self._after_cell(len(job.cells))
            final = "cancelled" if job.cancel.is_set() else "done"
        except Exception as exc:  # noqa: BLE001 - a failing cell must fail the job visibly, not kill the worker thread
            final = "failed"
            with self._lock:
                job.error = f"{type(exc).__name__}: {exc}"
        # Persist first, then publish the terminal status: a client that sees `done` can reload it.
        with self._lock:
            job.elapsed_ms = int((time.perf_counter() - job.started) * 1000)
            envelope = {**self._snapshot(job), "status": final, "elapsed_ms": job.elapsed_ms}
        self._repository.save_optimization(envelope)
        with self._lock:
            job.status = final

    def _snapshot(self, job: _Job) -> dict:
        """Caller holds the lock. Lists are copied so the caller can release it immediately."""
        plan, request = job.plan, job.request
        cells = list(job.cells)
        done, total = len(cells), len(plan.cells)
        if job.status == "running" and job.started is not None:
            elapsed_ms = int((time.perf_counter() - job.started) * 1000)
        else:
            elapsed_ms = job.elapsed_ms
        remaining = total - done
        if done > 0 and elapsed_ms > 0:
            estimated = remaining * (elapsed_ms / done) / 1000.0
        else:
            estimated = estimate_seconds(remaining, len(job.rows))
        side = request.side
        return {
            "job_id": job.job_id,
            "status": job.status,
            "side": side,
            "objective": request.objective,
            "created_at": job.created_at,
            "progress": {"done": done, "total": total},
            "total_cells": total,
            "skipped_cells": len(plan.skipped),
            "skipped": list(plan.skipped),
            "elapsed_ms": elapsed_ms,
            "estimated_seconds": round(estimated, 3),
            "cells": cells,
            "matrices": {
                metric: {side: heatmap(cells, plan.fast_values, plan.slow_values, metric)}
                for metric in OBJECTIVES
            },
            "fast_values": list(plan.fast_values),
            "slow_values": list(plan.slow_values),
            "fast_path": plan.fast_path,
            "slow_path": plan.slow_path,
            "bars": len(job.rows),
            "cache_hits": job.cache_hits,
            "data": job.data,
            "strategy": request.strategy.model_dump(mode="json"),
            "settings": request.settings.model_dump(mode="json"),
            "error": job.error,
        }

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return self._snapshot(job)
        return self._repository.get_optimization(job_id)  # KeyError for unknown ids

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in UNFINISHED or job.cancel.is_set():
                return False
            job.cancel.set()
            return True

    def mark_lost_on_startup(self) -> list[str]:
        """Persisted jobs still queued/running belong to a dead worker: mark them lost."""
        lost = []
        for summary in self._repository.list_optimizations():
            if summary.get("status") in UNFINISHED:
                envelope = self._repository.get_optimization(summary["job_id"])
                envelope["status"] = "lost"
                self._repository.save_optimization(envelope)
                lost.append(summary["job_id"])
        return lost

    def list_jobs(self) -> list[dict]:
        return self._repository.list_optimizations()


__all__ = [
    "MAX_CELLS",
    "OBJECTIVES",
    "GridPlan",
    "JobBusy",
    "OptimizeRequest",
    "OptimizerRunner",
    "engine_rows",
    "estimate_seconds",
    "expand_grid",
    "heatmap",
]
