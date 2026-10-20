"""Optimizer core (spec §2b.9, §7): per-side grids, progressive results, cancel, cache reuse.

DB-free; synthetic bars from test_aegis_backtest; JSON repository on tmp_path.
"""

import json
import threading
import time

import pandas as pd
import pytest
from products.aegis.backtest import DataReference
from products.aegis.optimize import (
    MAX_CELLS,
    MS_PER_BAR,
    SERIAL_MAX_CELLS,
    GridPlan,
    JobBusy,
    OptimizeRequest,
    OptimizerJob,
    OptimizerRunner,
    axis_matrix,
    best_cells,
    estimate_seconds,
    expand_grid,
    heatmap,
    plan_seconds,
)
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import OptimizationParameter, default_strategy
from test_aegis_backtest import bars

pytestmark = pytest.mark.aegis

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


def test_a_grid_over_400_cells_is_planned_for_the_pool():  # the limits change (2026-10-20)
    strategy = small_strategy(fast=(1, 25, 1), slow=(30, 200, 10))  # 25 * 18 = 450 > 400
    assert (MAX_CELLS, SERIAL_MAX_CELLS) == (100_000, 400)
    assert len(expand_grid(strategy.long_side).cells) == 450


def test_grid_bound_names_the_count_and_points_to_experiments():
    strategy = small_strategy(fast=(1, 400, 1), slow=(401, 700, 1))  # 400 * 300 = 120,000
    with pytest.raises(ValueError, match="120000 cells over cap 100000") as info:
        expand_grid(strategy.long_side)
    assert "experiment" in str(info.value)


def test_plan_prices_a_pooled_grid_across_workers():
    assert plan_seconds(100, 1000, 0.02, None, 10) == pytest.approx(2.0)  # serial: the host rate
    assert plan_seconds(1000, 1000, 0.02, 0.03, 10) == pytest.approx(3.0)  # pooled: the pool rate
    assert plan_seconds(1000, 1000, 0.02, None, 10) == pytest.approx(2.0)  # no pool rate yet


def _grid_strategy():
    return small_strategy(fast=(3, 8, 1), slow=(9, 14, 1))  # 6 x 6 = 36 cells


def _run_to_end(tmp_path, kind):
    runner = OptimizerRunner(JsonRunRepository(tmp_path))
    job_id = runner.start(kind)
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "failed"), 120)
    return runner.status(job_id)


def test_pooled_cells_equal_serial_cells(tmp_path, monkeypatch):  # Review Focus 1
    import products.aegis.optimize as module
    from products.aegis.pool import Pool

    frame = pd.DataFrame(bars())
    serial = _run_to_end(
        tmp_path / "serial", OptimizerJob(request(_grid_strategy()), frame, PINNED)
    )
    monkeypatch.setattr(module, "SERIAL_MAX_CELLS", 10)
    kind = OptimizerJob(
        request(_grid_strategy()), frame, PINNED, pool_factory=lambda: Pool(max_workers=2)
    )
    assert kind.pooled and kind.total_units < 36
    pooled = _run_to_end(tmp_path / "pooled", kind)
    assert serial["status"] == pooled["status"] == "done", (serial["error"], pooled["error"])
    assert pooled["cells_done"] == serial["cells_done"] == 36
    by_params = {json.dumps(c["params"], sort_keys=True): c for c in serial["cells"]}
    for cell in pooled["cells"]:
        twin = by_params[json.dumps(cell["params"], sort_keys=True)]
        assert (cell["fast"], cell["slow"]) == (twin["fast"], twin["slow"])
        assert cell["metrics"] == pytest.approx(twin["metrics"], nan_ok=True)
    assert pooled["bars"] == serial["bars"] == len(frame)


def test_pooled_job_progresses_and_cancels_by_chunk(tmp_path, monkeypatch):  # Review Focus 2
    import products.aegis.optimize as module
    from products.aegis.pool import Pool

    monkeypatch.setattr(module, "SERIAL_MAX_CELLS", 10)
    monkeypatch.setattr(module, "CHUNK_PER_WORKER", 4)  # 2 workers x 4 = 8 cells per unit
    gate = threading.Event()

    def after_chunk(done):
        if done == 1:
            gate.wait(30)

    repository = JsonRunRepository(tmp_path)
    runner = OptimizerRunner(repository, after_cell=after_chunk)
    kind = OptimizerJob(
        request(_grid_strategy()),
        pd.DataFrame(bars()),
        PINNED,
        pool_factory=lambda: Pool(max_workers=2),
    )
    job_id = runner.start(kind)
    assert wait_for(lambda: runner.status(job_id)["progress"]["done"] == 1, 120)
    mid = runner.status(job_id)
    assert mid["progress"] == {"done": 1, "total": 5} and mid["cells_done"] == 8
    assert mid["total_cells"] == 36 and mid["ms_per_bar"] is None  # the pool never prices the host
    assert runner.cancel(job_id) is True
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "cancelled", 60)
    saved = repository.get_optimization(job_id)
    assert saved["status"] == "cancelled" and len(saved["cells"]) == 8


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


# --- fix pass after the whole-branch review (one-axis grids, persistence, learned cost) --------


def one_axis_strategy():
    strategy = small_strategy(fast=(5, 7, 1), slow=(8, 10, 1))
    side = strategy.long_side
    ranges = [side.optimization[0], side.optimization[1].model_copy(update={"enabled": False})]
    return strategy.model_copy(
        update={"long_side": side.model_copy(update={"optimization": ranges})}
    )


def test_heatmap_ignores_cells_without_both_axes():
    cells = [{"fast": 5.0, "slow": None, "metrics": {"net_pnl": 1.0}}]
    assert heatmap(cells, [5.0], [], "net_pnl") == [[]]
    assert heatmap(cells, [5.0], [8.0], "net_pnl") == [[None]]


def test_single_enabled_range_runs_and_reports_a_one_axis_grid(tmp_path):
    runner = OptimizerRunner(JsonRunRepository(tmp_path))
    job_id = runner.start(request(one_axis_strategy()), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "failed"))
    status = runner.status(job_id)  # must never raise, whatever the grid shape
    assert status["status"] == "done" and status["error"] is None
    assert status["progress"] == {"done": 3, "total": 3} and status["slow_values"] == []
    assert status["matrices"]["net_pnl"]["long"] == [[], [], []]
    assert all(cell["slow"] is None and cell["fast"] is not None for cell in status["cells"])


def test_failing_persistence_marks_the_job_failed_and_frees_the_runner(tmp_path):
    class Broken(JsonRunRepository):
        saves = 0

        def save_optimization(self, envelope):
            Broken.saves += 1
            if Broken.saves > 1:  # the start persists fine; everything after fails
                raise OSError("disk full")
            return super().save_optimization(envelope)

    runner = OptimizerRunner(Broken(tmp_path))
    job_id = runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["status"] == "failed")
    assert "OSError" in runner.status(job_id)["error"]
    # The runner is free again: the next start is refused by the broken disk, not by JobBusy,
    # and a start that cannot persist its queued envelope registers nothing.
    with pytest.raises(OSError, match="disk full"):
        runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert [j for j in runner._jobs.values() if j.status in ("queued", "running")] == []


def test_job_is_persisted_on_start_and_per_cell_so_a_restart_can_mark_it_lost(tmp_path):
    gate = threading.Event()

    def after_cell(done):
        if done == 1:
            gate.wait(10)

    repository = JsonRunRepository(tmp_path)
    runner = OptimizerRunner(repository, after_cell=after_cell)
    job_id = runner.start(request(), pd.DataFrame(bars()), PINNED)
    persisted = repository.get_optimization(job_id)
    assert persisted["status"] in ("queued", "running") and persisted["progress"]["total"] == 9
    assert [j["job_id"] for j in runner.list_jobs()] == [job_id]
    assert wait_for(lambda: repository.get_optimization(job_id)["progress"]["done"] == 1)
    assert repository.get_optimization(job_id)["status"] == "running"
    assert OptimizerRunner(JsonRunRepository(tmp_path)).mark_lost_on_startup() == [job_id]
    assert repository.get_optimization(job_id)["status"] == "lost"
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    assert repository.get_optimization(job_id)["status"] == "done"


def test_runner_learns_ms_per_bar_from_completed_jobs_and_persists_it(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = OptimizerRunner(repository)
    assert runner.ms_per_bar == MS_PER_BAR
    job_id = runner.start(request(), pd.DataFrame(bars()), PINNED)
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    assert 0 < runner.ms_per_bar != MS_PER_BAR
    assert repository.get_optimization(job_id)["ms_per_bar"] == pytest.approx(runner.ms_per_bar)
    fresh = OptimizerRunner(JsonRunRepository(tmp_path))
    assert fresh.ms_per_bar == pytest.approx(runner.ms_per_bar)


def _ranged_side(indicators, ranges, entry=None):
    from products.aegis.strategy import RuleSpec

    side = default_strategy().long_side
    update = {
        "indicators": [*side.indicators, *indicators],
        "optimization": [
            OptimizationParameter(path=path, start=start, stop=stop, step=step)
            for path, start, stop, step in ranges
        ],
    }
    if entry is not None:
        update["entry"] = RuleSpec(**entry)
    return type(side).model_validate(side.model_copy(update=update).model_dump(mode="json"))


def test_grid_axes_for_a_non_crossover_rule_are_the_first_two_paths():
    from products.aegis.strategy import IndicatorSpec

    side = _ranged_side(
        [
            IndicatorSpec(id="donchian", kind="DONCHIAN", length=20),
            IndicatorSpec(id="rsi", kind="RSI", length=14),
        ],
        [("indicators.donchian.length", 10, 40, 10), ("indicators.rsi.length", 7, 21, 7)],
        entry={"left": "rsi", "operator": "crosses_above", "right": "sma"},
    )
    plan = expand_grid(side)
    assert len(plan.cells) == 12 and plan.skipped == []
    assert plan.fast_path == "indicators.donchian.length"
    assert plan.slow_path == "indicators.rsi.length"
    assert plan.fast_values == [10.0, 20.0, 30.0, 40.0] and plan.slow_values == [7.0, 14.0, 21.0]
    assert plan.skip_reason is None


def test_grid_skips_invalid_macd_cells():
    from products.aegis.strategy import IndicatorSpec

    side = _ranged_side(
        [IndicatorSpec(id="macd", kind="MACD", length=12)],
        [("indicators.macd.length", 10, 30, 10), ("indicators.macd.params.slow", 20, 30, 10)],
    )
    plan = expand_grid(side)
    assert len(plan.cells) == 3 and len(plan.skipped) == 3
    assert all(c["indicators.macd.length"] < c["indicators.macd.params.slow"] for c in plan.cells)
    assert plan.skip_reason == "invalid parameter combinations"


def test_reference_grid_is_unchanged():
    plan = expand_grid(default_strategy().long_side)
    assert (len(plan.cells), len(plan.skipped)) == (271, 1)
    assert plan.fast_path == "indicators.ema.length" and plan.slow_path == "indicators.sma.length"
    assert plan.skip_reason == "fast ≥ slow"


def test_grid_axes_for_a_group_rule_are_the_first_two_paths():
    from products.aegis.strategy import IndicatorSpec, RuleGroup, RuleSpec

    side = _ranged_side(
        [
            IndicatorSpec(id="donchian", kind="DONCHIAN", length=20),
            IndicatorSpec(id="rsi", kind="RSI", length=14),
        ],
        [("indicators.donchian.length", 10, 40, 10), ("indicators.rsi.length", 7, 21, 7)],
    )
    side = type(side).model_validate(
        {
            **side.model_dump(mode="json"),
            "entry": RuleGroup(
                all_of=[
                    RuleSpec(left="price.close", operator="crosses_above", right="donchian.upper"),
                    RuleSpec(left="rsi", operator="less_than", right="70"),
                ]
            ).model_dump(mode="json"),
        }
    )
    plan = expand_grid(side)
    assert len(plan.cells) == 12 and plan.skip_reason is None
    assert (plan.fast_path, plan.slow_path) == (
        "indicators.donchian.length",
        "indicators.rsi.length",
    )


def test_optimize_request_refuses_the_settings_the_job_sets_itself():
    from products.aegis.backtest import BacktestSettings, OpenPosition
    from pydantic import ValidationError

    carried = OpenPosition(
        side="LONG",
        entry_time="2026-01-05T10:00:00+00:00",
        signal_time="2026-01-05T09:30:00+00:00",
        entry_price=100.0,
        quantity=1,
        entry_fee=0.0,
        capital_at_entry=100_000.0,
        entry_tags=[],
    )
    with pytest.raises(
        ValidationError, match="settings.initial_position is set by the job itself; leave it unset"
    ):
        OptimizeRequest(
            strategy=small_strategy(),
            side="long",
            data=DATA,
            settings=BacktestSettings(initial_position=carried),
        )
    with pytest.raises(
        ValidationError, match="settings.close_at_end is set by the job itself; leave it unset"
    ):
        OptimizeRequest(
            strategy=small_strategy(),
            side="long",
            data=DATA,
            settings=BacktestSettings(close_at_end=False),
        )
    assert OptimizeRequest(strategy=small_strategy(), side="long", data=DATA).settings.close_at_end


def test_grid_values_are_rounded_to_the_steps_decimals():
    from products.aegis.optimize import _values

    assert _values(0.1, 0.5, 0.1) == [0.1, 0.2, 0.3, 0.4, 0.5]
    assert _values(5, 7, 1) == [5.0, 6.0, 7.0]
    assert _values(1.0, 2.0, 0.25) == [1.0, 1.25, 1.5, 1.75, 2.0]


# --- the limits change: what a job sends, and a matrix of any two parameters ----------------------


def _cell(ema, sma, rsi, net, dd):
    return {
        "params": {
            "indicators.ema.length": ema,
            "indicators.sma.length": sma,
            "indicators.rsi.length": rsi,
        },
        "fast": ema,
        "slow": sma,
        "metrics": {"net_pnl": net, "mar": None, "max_drawdown": dd, "trade_count": 3},
    }


THREE = [  # ema x sma x rsi: two rsi values per (ema, sma) square
    _cell(5, 20, 7, 10.0, 0.20),
    _cell(5, 20, 14, 30.0, 0.30),
    _cell(5, 30, 7, None, None),
    _cell(5, 30, 14, -5.0, 0.10),
    _cell(9, 20, 7, 50.0, 0.05),
    _cell(9, 20, 14, 50.0, 0.40),  # ties the cell before it on net P&L: the first is kept
]


def test_heatmap_keeps_the_best_cell_of_a_square():  # Review Focus 3
    net = heatmap(THREE, [5.0, 9.0], [20.0, 30.0], "net_pnl")
    assert net == [[30.0, -5.0], [50.0, None]]
    assert heatmap(THREE, [5.0, 9.0], [20.0, 30.0], "max_drawdown") == [[0.20, 0.10], [0.05, None]]


def test_best_cells_by_objective_with_undefined_last_and_ties_stable():  # Review Focus 5
    assert [c["metrics"]["net_pnl"] for c in best_cells(THREE, "net_pnl", 4)] == [
        50.0,
        50.0,
        30.0,
        10.0,
    ]
    assert best_cells(THREE, "net_pnl", 2)[0] is THREE[4]
    assert [c["metrics"]["max_drawdown"] for c in best_cells(THREE, "max_drawdown", 6)][-1] is None
    assert best_cells(THREE, "max_drawdown", 1)[0] is THREE[4]


def test_axis_matrix_shows_any_two_parameters_with_the_best_of_the_rest():
    values = {
        "indicators.ema.length": [5.0, 9.0],
        "indicators.sma.length": [20.0, 30.0],
        "indicators.rsi.length": [7.0, 14.0],
    }
    m = axis_matrix(THREE, "indicators.ema.length", "indicators.rsi.length", values)
    assert (m["rows"], m["cols"]) == ([5.0, 9.0], [7.0, 14.0])
    net = m["metrics"]["net_pnl"]
    assert net["values"] == [
        [10.0, 30.0],
        [50.0, 50.0],
    ]  # best over sma; the undefined cell ignored
    assert m["counts"] == [[2, 2], [1, 1]]
    best = m["cells"][net["cells"][0][1]]
    assert best["params"]["indicators.sma.length"] == 20 and best["metrics"]["net_pnl"] == 30.0
    assert m["metrics"]["max_drawdown"]["values"][0] == [0.20, 0.10]
    with pytest.raises(ValueError, match="two different parameters"):
        axis_matrix(THREE, "indicators.ema.length", "indicators.ema.length", values)
    with pytest.raises(ValueError, match="not a parameter"):
        axis_matrix(THREE, "indicators.ema.length", "indicators.macd.length", values)


def test_axis_matrix_of_a_two_parameter_job_equals_its_heatmap():  # Review Focus 4
    two = [c for c in THREE if c["params"]["indicators.rsi.length"] == 7]
    values = {"indicators.ema.length": [5.0, 9.0], "indicators.sma.length": [20.0, 30.0]}
    m = axis_matrix(two, "indicators.ema.length", "indicators.sma.length", values)
    for metric in ("net_pnl", "max_drawdown"):
        assert m["metrics"][metric]["values"] == heatmap(two, [5.0, 9.0], [20.0, 30.0], metric)
