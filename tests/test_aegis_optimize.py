"""Optimizer core (spec §2b.9, §7): per-side grids, progressive results, cancel, cache reuse.

DB-free; synthetic bars from test_aegis_backtest; JSON repository on tmp_path.
"""

import threading
import time

import pandas as pd
import pytest
from products.aegis.backtest import DataReference
from products.aegis.optimize import (
    MAX_CELLS,
    GridPlan,
    JobBusy,
    OptimizeRequest,
    OptimizerRunner,
    estimate_seconds,
    expand_grid,
    heatmap,
)
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import OptimizationParameter, default_strategy
from test_aegis_backtest import bars

PINNED = {"source": "raw_archive", "symbol": "QQQ", "vintage": "test", "research_eligible": False}
DATA = DataReference(symbol="QQQ", timeframe="30m", start="2026-01-05", end="2026-01-06")


def small_strategy(fast=(5, 7, 1), slow=(8, 10, 1)):
    """Default strategy with a tiny long grid: 3x3 cells, no skips unless ranges overlap."""
    strategy = default_strategy()
    side = strategy.long_side.model_copy(
        update={
            "optimization": [
                OptimizationParameter(
                    path="indicators.ema.length", start=fast[0], stop=fast[1], step=fast[2]
                ),
                OptimizationParameter(
                    path="indicators.sma.length", start=slow[0], stop=slow[1], step=slow[2]
                ),
            ]
        }
    )
    return strategy.model_copy(update={"long_side": side})


def request(strategy=None, objective="net_pnl"):
    return OptimizeRequest(
        strategy=strategy or small_strategy(), side="long", data=DATA, objective=objective
    )


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_grid_expands_from_side_ranges_and_skips_fast_ge_slow():
    plan = expand_grid(default_strategy().long_side)
    assert isinstance(plan, GridPlan)
    assert plan.fast_values == [float(v) for v in range(5, 21)]
    assert plan.slow_values == [float(v) for v in range(20, 101, 5)]
    total = len(plan.cells) + len(plan.skipped)
    assert total == 16 * 17 == 272
    assert len(plan.skipped) == sum(1 for f in plan.fast_values for s in plan.slow_values if f >= s)
    assert all(c["indicators.ema.length"] < c["indicators.sma.length"] for c in plan.cells)
    assert all(s["indicators.ema.length"] >= s["indicators.sma.length"] for s in plan.skipped)


def test_grid_over_400_cells_is_rejected():
    strategy = small_strategy(fast=(1, 25, 1), slow=(30, 200, 10))  # 25 * 18 = 450 > 400
    assert MAX_CELLS == 400
    with pytest.raises(ValueError, match="grid too large"):
        expand_grid(strategy.long_side)


def test_estimate_uses_cells_bars_and_ms_per_bar():
    assert estimate_seconds(cells=10, bars=1000, ms_per_bar=0.5) == pytest.approx(5.0)
    assert estimate_seconds(cells=0, bars=1000) == 0.0
    assert estimate_seconds(cells=272, bars=3493) > estimate_seconds(cells=10, bars=3493)


def test_job_runs_to_completion_with_progress_and_partial_cells(tmp_path):
    gate = threading.Event()
    seen = []

    def after_cell(done):
        seen.append(done)
        if done == 1:
            gate.wait(10)  # hold the runner after the first cell so the partial state is observable

    runner = OptimizerRunner(JsonRunRepository(tmp_path), after_cell=after_cell)
    job_id = runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["progress"]["done"] == 1)
    mid = runner.status(job_id)
    assert mid["status"] == "running"
    assert 0 < mid["progress"]["done"] < mid["progress"]["total"] == 9
    assert len(mid["cells"]) == mid["progress"]["done"]
    assert set(mid["cells"][0]) >= {"params", "fast", "slow", "metrics"}
    assert set(mid["matrices"]) == {"net_pnl", "mar", "max_drawdown", "trade_count"}
    matrix = mid["matrices"]["net_pnl"]["long"]
    assert len(matrix) == 3 and len(matrix[0]) == 3
    assert sum(v is not None for row in matrix for v in row) == 1
    assert mid["estimated_seconds"] >= 0
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    done = runner.status(job_id)
    assert done["progress"] == {"done": 9, "total": 9} and len(done["cells"]) == 9
    assert done["elapsed_ms"] >= 0 and seen == list(range(1, 10))
    assert all(v is not None for row in done["matrices"]["trade_count"]["long"] for v in row)


def test_cancel_stops_between_cells(tmp_path):
    gate = threading.Event()

    def after_cell(done):
        if done == 1:
            gate.wait(10)

    repository = JsonRunRepository(tmp_path)
    runner = OptimizerRunner(repository, after_cell=after_cell)
    job_id = runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["progress"]["done"] == 1)
    assert runner.cancel(job_id) is True
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "cancelled")
    status = runner.status(job_id)
    assert status["progress"]["done"] == 1 and len(status["cells"]) == 1
    assert runner.cancel(job_id) is False  # nothing left to cancel
    assert repository.get_optimization(job_id)["status"] == "cancelled"


def test_second_job_while_running_is_409_and_first_continues(tmp_path):
    gate = threading.Event()

    def after_cell(done):
        if done == 1:
            gate.wait(10)

    runner = OptimizerRunner(JsonRunRepository(tmp_path), after_cell=after_cell)
    first = runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(first)["progress"]["done"] == 1)
    with pytest.raises(JobBusy):
        runner.start(request(), pd.DataFrame(bars()), PINNED)
    gate.set()
    assert wait_for(lambda: runner.status(first)["status"] == "done")
    assert runner.status(first)["progress"] == {"done": 9, "total": 9}
    second = runner.start(request(), pd.DataFrame(bars()), PINNED)  # free again
    assert wait_for(lambda: runner.status(second)["status"] == "done")


def test_indicator_cache_is_reused_across_cells(tmp_path):
    runner = OptimizerRunner(JsonRunRepository(tmp_path))
    strategy = small_strategy(fast=(5, 6, 1), slow=(8, 9, 1))  # 2x2
    job_id = runner.start(request(strategy), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    status = runner.status(job_id)
    assert status["progress"]["total"] == 4
    assert status["cache_hits"] > 0


def test_heatmap_matrix_shape_and_none_for_skipped():
    cells = [
        {"fast": 5.0, "slow": 8.0, "metrics": {"net_pnl": 1.0}},
        {"fast": 6.0, "slow": 9.0, "metrics": {"net_pnl": -2.0}},
    ]
    matrix = heatmap(cells, [5.0, 6.0], [8.0, 9.0], "net_pnl")
    assert matrix == [[1.0, None], [None, -2.0]]
    assert heatmap([], [5.0], [8.0, 9.0], "mar") == [[None, None]]


def test_completed_job_is_persisted_via_repository(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = OptimizerRunner(repository)
    job_id = runner.start(request(objective="mar"), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    saved = repository.get_optimization(job_id)
    assert saved["job_id"] == job_id and saved["status"] == "done"
    assert saved["side"] == "long" and saved["objective"] == "mar"
    assert saved["data"]["source"] == "raw_archive" and saved["data"]["research_eligible"] is False
    assert len(saved["cells"]) == 9 and saved["progress"] == {"done": 9, "total": 9}
    assert [s["job_id"] for s in repository.list_optimizations()] == [job_id]


def test_mark_lost_on_startup_marks_unfinished_persisted_jobs(tmp_path):
    repository = JsonRunRepository(tmp_path)
    repository.save_optimization(
        {"job_id": "stale-1", "status": "running", "created_at": "2026-01-01T00:00:00+00:00"}
    )
    repository.save_optimization(
        {"job_id": "fine-1", "status": "done", "created_at": "2026-01-02T00:00:00+00:00"}
    )
    runner = OptimizerRunner(repository)
    assert runner.mark_lost_on_startup() == ["stale-1"]
    assert repository.get_optimization("stale-1")["status"] == "lost"
    assert repository.get_optimization("fine-1")["status"] == "done"
