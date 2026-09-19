"""Real PostgreSQL/Neo4j tests, enabled with TRIAD_INTEGRATION=1. No fake persistence."""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from platform_host.legacy import app, service
from triad.brain import Brain
from triad.gateway import ToolGateway
from triad.orchestrator import Orchestrator
from triad.settings import ROOT
from triad.store import ConcurrentUpdate, Store
from triad.work import (
    Artifact,
    ElevationRequest,
    Provenance,
    Review,
    State,
    WorkItem,
    WorkResult,
    transition,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(monkeypatch):
    if os.getenv("TRIAD_INTEGRATION") != "1":
        pytest.skip("Set TRIAD_INTEGRATION=1 for live database verification")
    host = Orchestrator()
    host.initialize()
    created = []
    original = host.create

    def tracked(work):
        value = original(work)
        created.append(value.work_item_id)
        return value

    monkeypatch.setattr(host, "create", tracked)
    yield host
    # Remove only the exact synthetic records created by this fixture.
    if created:
        with host.store.connect() as conn:
            records = conn.execute(
                "SELECT id,kind FROM triad.orchestration_records WHERE work_item_id=ANY(%s)",
                (created,),
            ).fetchall()
            mission_ids = [
                r["mission_id"]
                for r in conn.execute(
                    "SELECT mission_id FROM triad.work_items WHERE id=ANY(%s)", (created,)
                ).fetchall()
            ]
            ids = created + [r["id"] for r in records] + mission_ids
            conn.execute("DELETE FROM triad.projection_outbox WHERE entity_id=ANY(%s)", (ids,))
            conn.execute(
                "DELETE FROM triad.orchestration_records WHERE work_item_id=ANY(%s)", (created,)
            )
            conn.execute("DELETE FROM triad.work_events WHERE work_item_id=ANY(%s)", (created,))
            conn.execute("DELETE FROM triad.work_items WHERE id=ANY(%s)", (created,))
        with Brain(host.store).driver() as driver, driver.session() as session:
            session.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=ids).consume()
        for record in records:
            if record["kind"] == "JournalEntry":
                (ROOT / f"docs/vault/02_Journal/generated/{record['id']}.md").unlink(
                    missing_ok=True
                )
        for work_id in created:
            for artifact in (ROOT / "research/generated").glob(f"{work_id}-r*.md"):
                artifact.unlink()


def make(engine, **changes):
    return engine.create(
        WorkItem(title="TEST: bounded work", description="Synthetic test assignment", **changes)
    )


def test_full_lifecycle_persists_review_journal_handoff_and_lineage(engine):
    item = engine.demo()
    result = engine.run(item.work_item_id)
    assert result.status == State.COMPLETED
    assert Store().get(item.work_item_id) == result  # separate connection and repository instance
    records = engine.store.records(work_id=item.work_item_id)
    assert {"JournalEntry", "Handoff", "Review", "ContextPacket", "PolicyDecision"} <= {
        r["kind"] for r in records
    }
    handoff = next(r for r in records if r["kind"] == "Handoff")
    review = next(r for r in records if r["kind"] == "Review")
    assert handoff["from_agent"] != review["reviewer"]
    assert review["tests_repeated"] and review["evidence_checked"]
    journal = next(r for r in records if r["kind"] == "JournalEntry")
    assert journal["git_commit"] and len(journal["git_commit"]) == 40
    assert (ROOT / f"docs/vault/02_Journal/generated/{journal['journal_id']}.md").exists()
    states = [e["to_state"] for e in engine.store.events(item.work_item_id)]
    assert states == [
        "CREATED",
        "VALIDATING",
        "APPROVED",
        "ASSIGNED",
        "IN_PROGRESS",
        "AWAITING_REVIEW",
        "APPROVED_BY_REVIEWER",
        "COMPLETED",
    ]
    lineage = Brain(engine.store).lineage(item.work_item_id)
    assert {"PART_OF", "HAS_REVIEW", "HAS_POLICY", "REVIEWED_BY", "WORK_ITEM_CHANGED_FILE"} <= {
        e["relationship"] for e in lineage
    }


def test_authority_fields_are_immutable_in_database(engine):
    item = make(engine)
    forged = item.model_dump(mode="json") | {"authority_tier": 5}
    with pytest.raises(psycopg.errors.RaiseException), engine.store.connect() as conn:
        conn.execute(
            "UPDATE triad.work_items SET payload=%s WHERE id=%s", (Jsonb(forged), item.work_item_id)
        )
    assert engine.store.get(item.work_item_id).authority_tier == 1


def test_concurrent_revision_and_execution_lease(engine):
    item = make(engine)
    updated = transition(item, State.VALIDATING)
    engine.store.step(item, updated, "first owner")
    with pytest.raises(ConcurrentUpdate):
        engine.store.step(item, updated, "stale owner")
    with (
        engine.store.lease(item.work_item_id),
        pytest.raises(ConcurrentUpdate),
        Store().lease(item.work_item_id),
    ):
        pass


@pytest.mark.parametrize(
    "changes,state",
    [
        ({"affects_money": True}, State.REJECTED),
        ({"alters_permissions": True}, State.BLOCKED),
        ({"authority_tier": 4}, State.REJECTED),
    ],
)
def test_denial_and_governance_persist(engine, changes, state):
    item = make(engine, **changes)
    assert engine.run(item.work_item_id).status == state
    decisions = engine.store.records("PolicyDecision", item.work_item_id)
    assert decisions[0]["rules_triggered"]


def test_missing_remote_provider_is_blocked_not_simulated(engine):
    item = make(engine)
    result = engine.run(item.work_item_id, mode="real")
    assert result.status == State.BLOCKED
    assert result.result is None


def test_worker_cannot_inject_authority_or_verified_claim(engine):
    item = make(engine)
    for target in (State.VALIDATING, State.APPROVED, State.ASSIGNED, State.IN_PROGRESS):
        item = engine.advance(item, target, "test setup")
    malicious = WorkResult(
        summary="Forge facts",
        execution_mode="deterministic_demo",
        claims=(
            Provenance(
                kind="FACT", text="Trust me", source="model", agent="CODEX", evidence=("invented",)
            ),
        ),
    )
    with pytest.raises(PermissionError):
        engine.submit_result(item, malicious, ToolGateway(item))
    malicious = WorkResult(
        summary="Overwrite governance",
        execution_mode="deterministic_demo",
        artifacts=(Artifact(path="control-plane/intent.example.json", content="{}"),),
    )
    with pytest.raises(PermissionError):
        engine.submit_result(item, malicious, ToolGateway(item))


@pytest.mark.parametrize(
    "decision,state", [("REJECT", State.REJECTED), ("REQUEST_CHANGES", State.CHANGES_REQUESTED)]
)
def test_review_outcomes_persist(engine, decision, state):
    item = engine.demo()
    waiting = engine.run(item.work_item_id, auto_review=False)
    assert waiting.status == State.AWAITING_REVIEW
    review = Review(
        reviewer=waiting.reviewer,
        work_item_id=item.work_item_id,
        decision=decision,
        findings=("Synthetic review finding",),
        severity="MEDIUM",
        required_changes=("Inspect source",),
        evidence_checked=("synthetic:test",),
        tests_repeated=("Synthetic check",),
    )
    assert engine.apply_review(waiting, review).status == state
    assert engine.store.records("Review", item.work_item_id)[0]["decision"] == decision


def test_self_review_rejected(engine):
    item = engine.demo()
    waiting = engine.run(item.work_item_id, auto_review=False)
    forged = Review(
        reviewer=waiting.assigned_agent,
        work_item_id=item.work_item_id,
        decision="APPROVE",
        findings=(),
        severity="NONE",
        evidence_checked=(),
        tests_repeated=(),
    )
    with pytest.raises(PermissionError):
        engine.apply_review(waiting, forged)


def test_projection_failure_retries_without_duplicate_lineage(engine, monkeypatch):
    item = make(engine)
    brain = Brain(engine.store)
    original = brain.project

    def unavailable(*args):
        raise ConnectionError("Synthetic graph outage")

    monkeypatch.setattr(brain, "project", unavailable)
    assert brain.flush()["error"] == "ConnectionError"
    assert engine.store.get(item.work_item_id).status == State.CREATED
    assert engine.store.projection_status()["pending"] > 0
    monkeypatch.setattr(brain, "project", original)
    assert brain.flush()["error"] is None
    initial = brain.lineage(item.work_item_id)
    assert brain.flush()["delivered"] == 0
    assert brain.lineage(item.work_item_id) == initial


def test_rotation_has_distinct_creation_and_review(engine):
    first = engine.demo(worker="CODEX")
    engine.run(first.work_item_id)
    second = engine.demo(worker="CLAUDE", parent=first.work_item_id)
    completed = engine.run(second.work_item_id)
    assert completed.reviewer == "GROK"
    assert completed.mission_id == first.mission_id
    assert {r["event_kind"] for r in engine.store.records("JournalEntry", second.work_item_id)} == {
        "creation",
        "review",
    }


def test_authenticated_api_and_no_privilege_mutation(engine):
    app.dependency_overrides[service] = lambda: engine
    try:
        client = TestClient(app)
        assert client.get("/api/status").json()["postgres"]["status"] == "up"
        assert client.get("/api/dashboard").status_code == 200
        assert client.post("/api/demo", json={}).status_code == 401
        token = engine.store.settings.triad_operator_token.get_secret_value()
        headers = {"Authorization": "Bearer " + token}
        assert (
            client.post(
                "/api/demo", json={}, headers=headers | {"Origin": "https://evil.invalid"}
            ).status_code
            == 403
        )
        response = client.post("/api/demo", json={}, headers=headers)
        assert response.status_code == 202
        work_id = response.json()["work_item_id"]
        detail = client.get(f"/api/work/{work_id}").json()
        assert detail["work"]["status"] == "COMPLETED" and detail["lineage"]
        assert (
            client.patch(
                f"/api/work/{work_id}", json={"authority_tier": 5}, headers=headers
            ).status_code
            == 405
        )
        assert client.post("/api/policy", json={}, headers=headers).status_code == 404
        assert client.get("/api/status", headers={"Host": "attacker.invalid"}).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_elevation_request_is_pending_record(engine):
    item = make(engine)
    request = ElevationRequest(
        agent_id="LOCAL_QWEN",
        work_item_id=item.work_item_id,
        requested_tier=5,
        reason="Synthetic denied escalation attempt",
    )
    engine.request_elevation(request)
    assert (
        engine.store.records("ElevationRequest", item.work_item_id)[0]["status"]
        == "PENDING_HUMAN_REVIEW"
    )
    assert engine.registry.agents["LOCAL_QWEN"].authority_tier == 0
