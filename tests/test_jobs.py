"""Durable queue integration checks against disposable databases and Git fixtures."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_day3_integration import engine  # noqa: F401 - reuse isolated infrastructure fixture
from triad.api import app, service
from triad.day3.api import cycles_service
from triad.day3.scheduler import tick
from triad.jobs import Jobs
from triad.readiness import readiness

pytestmark = pytest.mark.integration


@pytest.fixture
def jobs(engine):  # noqa: F811 - pytest injects the imported fixture
    value = Jobs(engine)
    value.initialize()
    return value


def test_concurrent_submission_is_durable_and_idempotent(jobs):
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: jobs.submit("SIMULATED"), range(4)))
    assert len({r["job"]["id"] for r in rows}) == 1
    assert len(Jobs(jobs.cycles).list()) == 1
    assert jobs.list()[0]["status"] == "QUEUED"
    assert not jobs.ledger.records("Usage")


def test_worker_records_real_blockers_without_simulation(jobs):
    job = jobs.submit("REAL")["job"]
    assert jobs.once()["status"] == "BLOCKED"
    row = Jobs(jobs.cycles).list()[0]
    assert row["id"] == job["id"] and row["result"]["mode"] == "REAL"
    assert row["result"]["agents_run"] == []
    assert jobs.once()["status"] == "IDLE"


def test_worker_runs_full_reviewed_cycle_once(jobs):
    jobs.submit("SIMULATED")
    assert jobs.once()["status"] == "COMPLETED"
    assert len(jobs.list()[0]["result"]["summary"]["changes_accepted"]) == 3
    calls = len(jobs.ledger.records("Usage"))
    assert Jobs(jobs.cycles).once()["status"] == "IDLE"
    jobs.submit("SIMULATED")
    assert jobs.once()["status"] == "IDLE"
    assert len(jobs.ledger.records("Usage")) == calls


def test_single_worker_lock_does_not_claim(jobs):
    jobs.submit("SIMULATED")
    with jobs.store.lease("day4-worker"):
        assert Jobs(jobs.cycles).once()["status"] == "WORKER_BUSY"
    assert jobs.list()[0]["status"] == "QUEUED"


def test_restart_marks_uncertain_and_pauses_without_replay(jobs):
    row = jobs.submit("SIMULATED")["job"]
    with jobs.store.connect() as conn:
        conn.execute(
            "UPDATE triad.cycle_jobs SET status='RUNNING',worker_id='crashed-worker' WHERE id=%s",
            (row["id"],),
        )
    old_epoch = jobs.ledger.control()["epoch"]
    assert Jobs(jobs.cycles).once()["status"] == "UNCERTAIN"
    assert jobs.ledger.control()["paused"]
    assert jobs.ledger.control()["epoch"] > old_epoch
    assert jobs.list()[0]["status"] == "UNCERTAIN"
    jobs.ledger.operate("resume")
    assert jobs.once()["status"] == "IDLE"
    assert jobs.ledger.records("Usage") == []


def test_kill_then_resume_cannot_resurrect_queued_authority(jobs):
    jobs.submit("SIMULATED")
    jobs.ledger.operate("kill")
    assert jobs.once()["status"] == "PAUSED"
    jobs.ledger.operate("resume")
    assert jobs.once()["status"] == "CANCELLED"
    assert not jobs.ledger.records("Usage")


def test_old_day_is_not_executed_as_catchup(jobs):
    jobs.submit("SIMULATED")
    jobs.cycles.day = "2001-01-02"
    assert jobs.once()["status"] == "CANCELLED"
    assert jobs.list()[0]["failure_code"] == "STALE_DAY_OR_CANCELLED_AUTHORITY"


def test_job_error_text_is_not_persisted(jobs, monkeypatch):
    jobs.submit("SIMULATED")

    def fail(**kwargs):
        raise RuntimeError("private-provider-response")

    monkeypatch.setattr(jobs.cycles, "run", fail)
    assert jobs.once()["status"] == "BLOCKED"
    assert jobs.list()[0]["failure_code"] == "RuntimeError"
    assert "private-provider-response" not in str(jobs.list())


def test_api_persists_without_executing_and_requires_auth(jobs):
    app.dependency_overrides[cycles_service] = lambda: jobs.cycles
    app.dependency_overrides[service] = lambda: jobs.cycles.host
    try:
        client = TestClient(app)
        assert client.post("/api/day3/cycles", json={"mode": "SIMULATED"}).status_code == 401
        headers = {
            "Authorization": "Bearer " + jobs.store.settings.triad_operator_token.get_secret_value()
        }
        response = client.post("/api/day3/cycles", json={"mode": "SIMULATED"}, headers=headers)
        assert response.status_code == 202
        job = response.json()["job"]
        assert job["status"] == "QUEUED" and not jobs.ledger.records("Usage")
        assert client.get("/api/day3/jobs").status_code == 200
        assert client.post(f"/api/day3/jobs/{job['id']}/cancel").status_code == 401
        assert client.post(f"/api/day3/jobs/{job['id']}/cancel", headers=headers).status_code == 200
        assert jobs.once()["status"] == "IDLE"
    finally:
        app.dependency_overrides.clear()


def test_readiness_does_not_equate_review_agreement_with_quality(jobs):
    report = readiness(jobs.cycles, probe=True)
    assert report["cloud_validation"] == "BLOCKED"
    for provider in report["providers"][:3]:
        assert "CLOUD_BUDGET_NOT_AUTHORIZED" in provider["blockers"]
        assert provider["quality"] == "NOT_EVALUATED"
        assert provider["observed_real_successes"] == 0
    assert all(m["reviews"] == 0 for m in report["review_evidence"])


def test_scheduler_enqueues_instead_of_running(jobs):
    from datetime import UTC, datetime

    result = tick(
        jobs.cycles,
        datetime(2001, 1, 1, 12, tzinfo=UTC),
        {"enabled": True, "timezone": "UTC", "time": "11:00", "mode": "SIMULATED"},
        submit=jobs.submit,
    )
    assert result["job"]["status"] == "QUEUED"
    assert not jobs.ledger.records("Usage")
