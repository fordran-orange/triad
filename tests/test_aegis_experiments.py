"""Experiments (Mission 6 spec §6): the resumable chunked job kind, Parquet cells, pause and
resume, cancel, materialize, and the document on the repository."""

import time

import pytest
from products.aegis import experiments as exp
from products.aegis.jobs import JobRunner
from products.aegis.runs import JsonRunRepository
from products.aegis.strategies import StrategyLibrary
from products.aegis.surface import Budget, Parameter, Surface
from test_aegis_surface import pinned
from test_aegis_walkforward import wave_bars

ROWS = wave_bars(n=260, period=37.0, amplitude=10.0)
PINNED_DATA = {
    "source": "raw_archive",
    "symbol": "QQQ",
    "vintage": "test",
    "research_eligible": False,
}


def wait_for(predicate, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def surface12():
    return Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=7),
        ]
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(exp, "CHUNK_CELLS", 5)
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    repository = JsonRunRepository(tmp_path / "aegis")
    library = StrategyLibrary(repository)
    document = library.create("Breakout", pinned())
    return repository, library, document


def request(document, **overrides):
    body = {
        "name": "twelve cells",
        "strategy_id": document.id,
        "data": {"symbol": "QQQ", "timeframe": "1h", "start": "2023-01-01", "end": "2024-12-31"},
        "settings": {"initial_capital": 100_000, "allocation_fraction": 1},
        "objective": "net_pnl",
        "surface": surface12().model_dump(),
        "budget": Budget(runs=1000).model_dump(),
    }
    body.update(overrides)
    return exp.ExperimentRequest.model_validate(body)


def start(repository, library, document, runner=None, **overrides):
    runner = runner or JobRunner(repository)
    doc = exp.create(
        exp.ExperimentStore(repository),
        library,
        request(document, **overrides),
        bars=len(ROWS),
        max_workers=2,
    )
    job = exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository)
    job_id = runner.start(job)
    return runner, job, job_id, doc.id


def document_of(repository, experiment_id):
    return exp.ExperimentDocument.model_validate(repository.get_experiment(experiment_id))


def test_experiment_runs_in_chunks_and_persists_rows(world):
    repository, library, document = world
    runner, job, job_id, experiment_id = start(repository, library, document)
    assert job.total_units == 3 and job.bars_per_unit == 0 and job.name == "experiment"
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("done", "failed"))
    doc = document_of(repository, experiment_id)
    assert doc.status == "done", doc.error
    assert doc.progress == {
        "cells_done": 12,
        "cells_planned": 12,
        "chunks_done": 3,
        "chunks_total": 3,
    }
    assert doc.plan["mode"] == "exhaustive" and doc.job_id == job_id and doc.engine == "kernel"
    table = exp.ExperimentStore(repository).cells(experiment_id)
    assert sorted(table.column("cell").to_pylist()) == list(range(12))
    assert set(table.column("pass").to_pylist()) == {"grid"}
    assert (
        "combined.net_pnl" in table.column_names
        and "long_side.indicators.rsi.length" in table.column_names
    )
    assert doc.ms_per_cell_bar is not None and doc.ms_per_cell_bar > 0
    assert runner.status(job_id)["status"] == "done"
    summary = next(s for s in repository.list_experiments() if s["id"] == experiment_id)
    assert (
        summary["status"] == "done"
        and summary["mode"] == "exhaustive"
        and summary["parameters"] == 2
    )


def test_snapshot_overrides_cost_and_estimate_and_leaves_the_runner_rate_alone(world):
    repository, library, document = world
    runner = JobRunner(repository)
    before = runner.ms_per_bar
    runner, _job, job_id, experiment_id = start(repository, library, document, runner=runner)
    assert wait_for(lambda: document_of(repository, experiment_id).status == "done")
    status = runner.status(job_id)
    assert status["ms_per_bar"] is None and status["ms_per_cell_bar"] > 0
    assert status["estimated_seconds"] == 0.0 and status["units"] == {"done": 3, "total": 3}
    assert runner.ms_per_bar == before


def test_pause_then_resume_completes_without_duplicates(world):
    repository, library, document = world
    gate = {"paused": False}

    def after_unit(done):
        if done == 1 and not gate["paused"]:
            gate["paused"] = True
            runner.cancel(job_id)

    runner = JobRunner(repository, after_unit=after_unit)
    doc = exp.create(
        exp.ExperimentStore(repository), library, request(document), bars=len(ROWS), max_workers=2
    )
    job = exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository)
    job.pause_requested = True  # what POST /pause sets before cancelling
    job_id = runner.start(job)
    assert wait_for(lambda: document_of(repository, doc.id).status == "paused")
    paused = document_of(repository, doc.id)
    assert (
        paused.progress["cells_done"] in (5, 10) and runner.status(job_id)["status"] == "cancelled"
    )

    again = JobRunner(repository)
    resumed = exp.ExperimentJob(paused, ROWS, PINNED_DATA, repository)
    assert resumed.total_units == 3 - paused.progress["chunks_done"]
    new_job_id = again.start(resumed)
    assert new_job_id != job_id
    assert wait_for(lambda: document_of(repository, doc.id).status == "done")
    table = exp.ExperimentStore(repository).cells(doc.id)
    assert sorted(table.column("cell").to_pylist()) == list(range(12))
    assert document_of(repository, doc.id).progress["cells_done"] == 12


def test_restart_marks_an_unfinished_experiment_paused_not_lost(world):
    repository, library, document = world
    doc = exp.create(
        exp.ExperimentStore(repository), library, request(document), bars=len(ROWS), max_workers=2
    )
    repository.save_experiment(
        {**doc.model_dump(mode="json"), "status": "running", "job_id": "dead"}
    )
    repository.save_optimization(
        {"job_id": "opt-1", "status": "running", "created_at": "2026-10-12T00:00:00+00:00"}
    )
    JobRunner(repository).mark_lost_on_startup()
    assert repository.get_experiment(doc.id)["status"] == "paused"
    assert repository.get_optimization("opt-1")["status"] == "lost"


def test_leftover_tmp_and_missing_chunk_are_rerun_on_resume(world):
    repository, library, document = world
    _runner, _job, _job_id, experiment_id = start(repository, library, document)
    assert wait_for(lambda: document_of(repository, experiment_id).status == "done")
    store = exp.ExperimentStore(repository)
    folder = store.cells_dir(experiment_id)
    files = sorted(folder.glob("*.parquet"))
    assert len(files) == 3
    files[-1].unlink()  # a chunk that never landed
    (folder / "000009.parquet.tmp").write_bytes(b"torn")  # a write the worker died inside
    doc = document_of(repository, experiment_id).model_copy(update={"status": "paused"})
    repository.save_experiment(doc.model_dump(mode="json"))
    resumed = exp.ExperimentJob(doc, ROWS, PINNED_DATA, repository)
    assert resumed.total_units == 1 and sorted(resumed.pending_cells()) == [10, 11]
    JobRunner(repository).start(resumed)
    assert wait_for(lambda: document_of(repository, experiment_id).status == "done")
    table = store.cells(experiment_id)
    assert sorted(table.column("cell").to_pylist()) == list(range(12))


def test_cancel_keeps_finished_chunks(world):
    repository, library, document = world

    def after_unit(done):
        if done == 1:
            runner.cancel(job_id)

    runner = JobRunner(repository, after_unit=after_unit)
    runner, _job, job_id, experiment_id = start(repository, library, document, runner=runner)
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("cancelled", "done"))
    doc = document_of(repository, experiment_id)
    assert doc.status == "cancelled" and 0 < doc.progress["cells_done"] < 12
    assert len(exp.ExperimentStore(repository).cells(experiment_id)) == doc.progress["cells_done"]


def test_materialize_matches_the_row_and_is_deterministic(world):
    repository, library, document = world
    _runner, _job, _job_id, experiment_id = start(repository, library, document)
    assert wait_for(lambda: document_of(repository, experiment_id).status == "done")
    doc = document_of(repository, experiment_id)
    first = exp.materialize(doc, exp.ExperimentStore(repository), repository, ROWS, PINNED_DATA, 7)
    second = exp.materialize(doc, exp.ExperimentStore(repository), repository, ROWS, PINNED_DATA, 7)
    assert first["result_hash"] == second["result_hash"] and first["run_id"] != second["run_id"]
    assert first["experiment_id"] == experiment_id and first["cell"] == 7
    assert first["strategy_id"] == document.id and first["engine"] == "kernel"
    row = exp.ExperimentStore(repository).row(experiment_id, 7)
    assert first["result"]["combined"]["metrics"]["net_pnl"] == row["combined.net_pnl"]
    assert repository.get_run(first["run_id"])["cell"] == 7
    with pytest.raises(KeyError):
        exp.materialize(doc, exp.ExperimentStore(repository), repository, ROWS, PINNED_DATA, 99)


def test_request_refusals(world):
    repository, library, document = world
    with pytest.raises(ValueError, match="settings.evaluate_from"):
        request(document, settings={"evaluate_from": "2024-01-01T00:00:00+00:00"})
    with pytest.raises(ValueError, match="tolerance"):
        request(document, tolerance=0)
    with pytest.raises(ValueError, match="objective"):
        request(document, objective="sharpe")
    with pytest.raises(KeyError):
        exp.create(
            exp.ExperimentStore(repository),
            library,
            request(document, strategy_id="nope"),
            bars=260,
            max_workers=2,
        )


def test_sampled_experiment_runs_first_pass_then_refinement(world, monkeypatch):
    """Spec §5.4 / plan P3: a 400-cell grid under a 30-run budget samples 20 cells, then spends
    10 on the neighbours of what the first pass found (the analysis is stubbed until Task 5)."""
    import sys
    import types

    repository, library, document = world
    monkeypatch.setattr(exp, "CHUNK_CELLS", 10)

    def analyse(table, grid, objective, tolerance, mode, seed, data_label):
        run = sorted(table.column("cell").to_pylist())
        return {
            "objective": objective,
            "tolerance": tolerance,
            "plateaus": [{"id": 1, "cells": run[:5], "centre": {"cell": run[0]}}],
            "recommendation": None,
            "statement": "stub",
            "cells_named": [],
        }

    stub = types.ModuleType("products.aegis.analysis")
    stub.analyse = analyse
    stub.render_markdown = lambda report: "# stub"
    monkeypatch.setitem(sys.modules, "products.aegis.analysis", stub)
    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=29, step=1),
            Parameter(path="long_side.indicators.rsi.length", start=5, stop=24, step=1),
        ]
    )
    _runner, job, _job_id, experiment_id = start(
        repository,
        library,
        document,
        surface=surface.model_dump(),
        budget=Budget(runs=30).model_dump(),
    )
    assert job.document.plan["mode"] == "sampled" and job.total_units == 3
    assert job.units[2] is None and len(job.pending_cells()) == 20
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("done", "failed"))
    doc = document_of(repository, experiment_id)
    assert doc.status == "done", doc.error
    table = exp.ExperimentStore(repository).cells(experiment_id)
    passes = table.column("pass").to_pylist()
    assert passes.count("sample") == 20 and passes.count("refine") == 10
    assert len(set(table.column("cell").to_pylist())) == 30
    assert len(doc.first_pass_cells) == 20 and len(doc.refinement_cells) == 10
    assert doc.progress["cells_done"] == 30 and doc.plan["sampled_fraction"] == 30 / 400


# --- Mission 6 Task 6: reports on the document, decision, refine ------------------------------


def finished(world, monkeypatch=None, **overrides):
    repository, library, document = world
    _runner, _job, _job_id, experiment_id = start(repository, library, document, **overrides)
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("done", "failed"))
    doc = document_of(repository, experiment_id)
    assert doc.status == "done", doc.error
    return repository, doc


def test_report_is_written_at_completion_and_can_be_recomputed(world, monkeypatch):
    monkeypatch.setattr(exp, "CURVES_LIMIT", 5)  # a "large" experiment: curves only for named cells
    repository, doc = finished(world)
    store = exp.ExperimentStore(repository)
    assert doc.latest_report == 1 and len(doc.reports) == 1
    assert doc.reports[0]["objective"] == "net_pnl" and doc.reports[0]["tolerance"] == 0.15
    report = store.read_report(doc.id, 1)
    for key in (
        "recommendation",
        "plateaus",
        "peaks",
        "main_effects",
        "sensitivity",
        "clusters",
        "statement",
        "report_id",
        "generated_at",
    ):
        assert key in report, key
    assert report["report_id"] == 1 and report["valid_cells"] == 12
    markdown = store.read_markdown(doc.id, 1)
    assert markdown.startswith("# Recommendation")
    assert [s["id"] for s in repository.list_experiments()] == [doc.id]  # reports are not listed
    assert store.report_path(doc.id, 1).parent.name == f"{doc.id}.reports"
    named = set(report["cells_named"])
    curves = store.curves(doc.id, range(12))
    assert set(curves) == named and all(len(c) == 128 for c in curves.values())

    doc, again = exp.recompute_report(store, doc, objective="max_drawdown", tolerance=0.10)
    assert (
        again["report_id"] == 2
        and again["objective"] == "max_drawdown"
        and again["tolerance"] == 0.10
    )
    assert doc.latest_report == 2 and [r["report_id"] for r in doc.reports] == [1, 2]
    assert store.read_report(doc.id, 1)["objective"] == "net_pnl"
    assert document_of(repository, doc.id).latest_report == 2


def test_cancelled_experiment_reports_what_it_has(world):
    repository, library, document = world

    def after_unit(done):
        if done == 1:
            runner.cancel(job_id)

    runner = JobRunner(repository, after_unit=after_unit)
    runner, _job, job_id, experiment_id = start(repository, library, document, runner=runner)
    assert wait_for(lambda: document_of(repository, experiment_id).status in ("cancelled", "done"))
    doc = document_of(repository, experiment_id)
    assert doc.status == "cancelled" and doc.latest_report == 1
    report = exp.ExperimentStore(repository).read_report(doc.id, 1)
    assert report["valid_cells"] == doc.progress["cells_done"] < 12
    assert "cancelled" in report["statement"]


def test_decision_round_trip(world):
    repository, doc = finished(world)
    store = exp.ExperimentStore(repository)
    decided = exp.decide(store, doc, "accepted", "use the centre next week")
    assert (
        decided.decision["verdict"] == "accepted"
        and decided.decision["notes"] == "use the centre next week"
    )
    assert (
        decided.decision["decided_at"]
        and document_of(repository, doc.id).decision == decided.decision
    )
    with pytest.raises(ValueError, match="verdict"):
        exp.decide(store, doc, "maybe", "")
    summary = next(s for s in repository.list_experiments() if s["id"] == doc.id)
    assert summary["decision"]["verdict"] == "accepted"


def test_refined_surface_narrows_to_the_plateau_plus_one_step():
    from products.aegis.surface import build_grid

    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=40, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=7),
        ]
    )
    grid = build_grid(pinned(), surface)
    plateau = [
        grid.index_of(
            {"long_side.indicators.donchian.length": d, "long_side.indicators.rsi.length": 14}
        )
        for d in (20, 25)
    ]
    narrowed = exp.refined_surface(surface, grid, plateau)
    assert [(p.start, p.stop, p.step) for p in narrowed.parameters] == [(15, 30, 5), (7, 21, 7)]
    edge = [
        grid.index_of(
            {"long_side.indicators.donchian.length": 10, "long_side.indicators.rsi.length": 28}
        )
    ]
    clipped = exp.refined_surface(surface, grid, edge)
    assert [(p.start, p.stop) for p in clipped.parameters] == [(10, 15), (21, 28)]


def test_refine_creates_a_queued_child_from_the_recommended_plateau(world):
    repository, doc = finished(world)
    store = exp.ExperimentStore(repository)
    report = store.read_report(doc.id, 1)
    from products.aegis.surface import build_grid

    grid = build_grid(doc.spec, doc.surface)
    plateau = [
        grid.index_of(
            {"long_side.indicators.donchian.length": 15, "long_side.indicators.rsi.length": r}
        )
        for r in (7, 14, 21)
    ]
    report["recommendation"] = {
        "plateau": 1,
        "centre": {"cell": plateau[1]},
        "supported_peak": None,
        "fragile_peaks": [],
        "statement": "x",
    }
    report["plateaus"] = [{"id": 1, "cells": plateau, "centre": {"cell": plateau[1]}}]
    store.write_report(doc.id, 1, report, "# Recommendation — x\n")
    child = exp.refine(store, doc, bars=len(ROWS), max_workers=2)
    assert child.parent == doc.id and child.status == "queued" and child.id != doc.id
    assert child.name == f"{doc.name} · refined"
    assert [(p.start, p.stop, p.step) for p in child.surface.parameters] == [
        (10, 20, 5),
        (7, 28, 7),
    ]
    assert (child.objective, child.budget, child.tolerance) == (
        doc.objective,
        doc.budget,
        doc.tolerance,
    )
    assert child.spec == doc.spec and child.strategy_hash == doc.strategy_hash
    assert document_of(repository, child.id).parent == doc.id
    report["recommendation"] = None
    store.write_report(doc.id, 1, report, "# Recommendation — none\n")
    with pytest.raises(ValueError, match="no recommendation"):
        exp.refine(store, doc, bars=len(ROWS), max_workers=2)
