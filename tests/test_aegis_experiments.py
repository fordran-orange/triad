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
