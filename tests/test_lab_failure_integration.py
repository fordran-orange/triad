import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_day3_integration import engine  # noqa: F401
from test_lab import END, START
from triad.lab.service import Laboratory
from triad.research_review import MethodReview, record_method_review
from triad.store import ConcurrentUpdate

pytestmark = pytest.mark.integration


def prepare(cycles, tmp_path, training=False):
    lab = Laboratory(cycles, tmp_path)
    dataset = lab.ingest("LABTEST", START, END)
    config = (
        {
            "partitions": [{"name": "training", "start": START, "end": END}],
            "selected_partition": "training",
        }
        if training
        else None
    )
    return lab, lab.create_experiment(dataset.dataset_id, config)


def test_late_failure_reconciles_files_database_and_work(engine, tmp_path, monkeypatch):  # noqa: F811
    from triad.lab import service

    lab, experiment = prepare(engine, tmp_path)
    original = service.write_run_status

    def fail_after_completed_manifest(path, run):
        original(path, run)
        if run.status == "COMPLETED":
            raise PermissionError("Injected late cancellation/publication failure")

    monkeypatch.setattr(service, "write_run_status", fail_after_completed_manifest)
    with pytest.raises(PermissionError):
        lab.run(experiment.experiment_id)
    run = lab.ledger.records("BacktestRun")[0]
    path = tmp_path / f"research/experiments/{experiment.experiment_id}/runs/{run['run_id']}"
    assert run["status"] == "FAILED"
    assert lab.host.store.get(run["work_item_id"]).status == "FAILED"
    assert json.loads((path / "manifest.json").read_text())["status"] == "FAILED"
    assert json.loads((path / "logs/events.json").read_text())["status"] == "FAILED"
    assert (path / "trades.parquet").exists()


def test_review_transaction_rollback_and_concurrent_verdicts(engine, tmp_path, monkeypatch):  # noqa: F811
    lab, experiment = prepare(engine, tmp_path)
    run = lab.run(experiment.experiment_id)
    body = MethodReview(
        decision="ACCEPT_RESULT",
        findings=("Fixture inspected",),
        evidence_checked=(run.content_hash,),
        tests_repeated=(),
    )
    original_put = lab.put

    def fail_after_insert(kind, *args, **kwargs):
        result = original_put(kind, *args, **kwargs)
        if kind == "ResearchReview":
            raise RuntimeError("Injected transaction failure")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(lab, "put", fail_after_insert)
        with pytest.raises(RuntimeError, match="transaction failure"):
            record_method_review(lab, run.run_id, body)
    assert not lab.ledger.records("ResearchReview")
    assert lab.host.store.get(run.work_item_id).status == "AWAITING_REVIEW"
    barrier = Barrier(2)
    original_get = lab.host.store.get

    def concurrent_get(identifier, *, conn=None):
        if conn is not None:
            return original_get(identifier, conn=conn)
        work = original_get(identifier)
        barrier.wait(timeout=20)
        return work

    def submit():
        try:
            return record_method_review(lab, run.run_id, body)["decision"]
        except ConcurrentUpdate:
            return "STALE"

    with monkeypatch.context() as patch:
        patch.setattr(lab.host.store, "get", concurrent_get)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(results) == ["ACCEPT_RESULT", "STALE"]
    assert len(lab.ledger.records("ResearchReview")) == 1
    assert lab.host.store.get(run.work_item_id).status == "COMPLETED"


def test_failed_sweep_attempt_keeps_run_and_parameters(engine, tmp_path, monkeypatch):  # noqa: F811
    from triad.lab import service

    lab, experiment = prepare(engine, tmp_path, training=True)

    def timeout(*args, **kwargs):
        raise TimeoutError("Injected run deadline")

    monkeypatch.setattr(service, "run_engine", timeout)
    with pytest.raises(TimeoutError):
        lab.sweep(experiment.experiment_id, {"period": [15, 20], "hold": [3]})
    sweep = lab.ledger.records("ParameterSweep")[0]
    assert sweep["tests_attempted"] == 1 and len(sweep["runs"]) == 1
    attempt = sweep["attempts"][0]
    assert attempt["parameters"] == {"period": 15, "hold": 3}
    assert attempt["status"] == "FAILED" and attempt["run_id"] == sweep["runs"][0]
    assert lab.ledger.get(attempt["run_id"])["status"] == "FAILED"


def test_rejected_sweep_variant_is_recorded_without_phantom_run(engine, tmp_path):  # noqa: F811
    lab, experiment = prepare(engine, tmp_path, training=True)
    with pytest.raises(ValueError):
        lab.sweep(experiment.experiment_id, {"period": [1], "hold": [3]})
    sweep = lab.ledger.records("ParameterSweep")[0]
    assert sweep["runs"] == []
    assert sweep["attempts"][0]["status"] == "NOT_STARTED"
    assert sweep["attempts"][0]["parameters"] == {"period": 1, "hold": 3}
