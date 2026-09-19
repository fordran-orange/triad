import subprocess

import pytest
from test_day3_integration import engine  # noqa: F401
from test_lab import END, START
from triad.brain import Brain
from triad.lab.service import Laboratory

pytestmark = pytest.mark.integration


def test_research_pipeline_reproducibility_review_and_lineage(engine, tmp_path):  # noqa: F811
    lab = Laboratory(engine, tmp_path)
    dataset = lab.ingest("LABTEST", START, END)
    experiment = lab.create_experiment(dataset.dataset_id)
    first, second = lab.run(experiment.experiment_id), lab.run(experiment.experiment_id)
    assert first.content_hash == second.content_hash
    review = lab.review(first.run_id)
    assert review["decision"] == "ACCEPT_RESULT"
    assert engine.host.store.get(first.work_item_id).status == "COMPLETED"
    assert engine.host.store.get(second.work_item_id).status == "AWAITING_REVIEW"
    from triad.research_review import MethodReview, record_method_review

    method = record_method_review(
        lab,
        second.run_id,
        MethodReview(
            decision="LOOKAHEAD_RISK",
            findings=("Test rejection of a method pending further audit",),
            evidence_checked=(second.content_hash,),
            tests_repeated=(),
        ),
    )
    assert method["mode"] == "HUMAN_OPERATOR_METHOD_REVIEW"
    assert engine.host.store.get(second.work_item_id).status == "CHANGES_REQUESTED"
    with pytest.raises(ValueError, match="not awaiting"):
        record_method_review(
            lab,
            second.run_id,
            MethodReview(
                decision="ACCEPT_RESULT",
                findings=("Cannot overwrite prior review",),
                evidence_checked=(second.content_hash,),
                tests_repeated=(),
            ),
        )
    with Brain(engine.host.store).driver() as driver, driver.session() as session:
        assert (
            session.run(
                "MATCH (d:Dataset {id:$id})-[:USED_BY]->(e:Experiment)-[:SUPPORTED_BY]->(:Commit) RETURN count(e) AS n",
                id=dataset.dataset_id,
            ).single()["n"]
            == 1
        )
    assert lab.catalog("LABTEST")[0]["dataset_id"] == dataset.dataset_id
    with pytest.raises(PermissionError, match="test partition"):
        lab.sweep(experiment.experiment_id, {"period": [20], "hold": [5]})
    import sys

    from triad.settings import ROOT

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/portable_research.py"),
            str(tmp_path),
            str(tmp_path / f"data/manifests/{dataset.dataset_id}.json"),
            str(
                tmp_path
                / f"research/experiments/{experiment.experiment_id}/runs/{first.run_id}/manifest.json"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert '"services_required": false' in result.stdout
    engine.ledger.operate("kill")
    with pytest.raises(PermissionError):
        lab.run(experiment.experiment_id)


def test_sweep_records_every_variant_and_no_test_optimization(engine, tmp_path):  # noqa: F811
    lab = Laboratory(engine, tmp_path)
    dataset = lab.ingest("LABTEST", START, END)
    exp = lab.create_experiment(
        dataset.dataset_id,
        {
            "partitions": [{"name": "training", "start": START, "end": END}],
            "selected_partition": "training",
        },
    )
    result = lab.sweep(exp.experiment_id, {"period": [15, 20], "hold": [3]})
    assert result["status"] == "COMPLETED" and result["tests_attempted"] == 2
    assert len(result["runs"]) == 2 and result["out_of_sample_result"] is None
    with pytest.raises(ValueError, match="ceiling"):
        lab.sweep(exp.experiment_id, {"period": list(range(20)), "hold": [1]})


def test_research_api_requires_auth(engine, tmp_path):  # noqa: F811
    from fastapi.testclient import TestClient
    from platform_host.legacy import app, service
    from triad.lab.api import laboratory

    lab = Laboratory(engine, tmp_path)
    app.dependency_overrides[laboratory] = lambda: lab
    app.dependency_overrides[service] = lambda: engine.host
    try:
        client = TestClient(app)
        assert client.get("/api/research/dashboard").status_code == 200
        assert client.post("/api/research/fixture", json={}).status_code == 401
        assert client.post("/api/research/runs/x/method-review", json={}).status_code == 401
        assert client.post("/api/research/experiments", json={"dataset_id": "x"}).status_code == 401
    finally:
        app.dependency_overrides.clear()
