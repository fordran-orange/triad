"""Live Day 3 tests use disposable PostgreSQL databases and isolated temporary Git repos."""

import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from platform_host.legacy import app, service
from psycopg import sql
from triad.brain import Brain
from triad.day3.adapters import SimulatedProvider
from triad.day3.api import cycles_service
from triad.day3.changes import GitChanges
from triad.day3.contracts import AgentRunResult
from triad.day3.cycles import Cycles
from triad.day3.ledger import Stopped
from triad.day3.support import support
from triad.settings import ROOT, Settings
from triad.store import Store
from triad.work import State

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.fixture
def engine(tmp_path):
    if os.getenv("TRIAD_INTEGRATION") != "1":
        pytest.skip("Enable live integration tests with TRIAD_INTEGRATION=1")
    database = "triad_test_" + uuid4().hex
    admin = Store()
    with admin.connect() as c:
        c.autocommit = True
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    store = Store(Settings(postgres_db=database))
    with store.connect() as c:
        c.execute("CREATE SCHEMA triad")
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)

    git("init", "-b", "main")
    git("config", "user.email", "test@localhost")
    git("config", "user.name", "Triad Test")
    (root / "README.md").write_text("# Isolated fixture\n")
    git("add", ".")
    git("commit", "-m", "baseline")
    value = Cycles(store, GitChanges(root, tmp_path / "worktrees"), day="2001-01-01")
    value.initialize()
    yield value
    # Cleanup uses only IDs from this disposable test database; shared registry nodes are retained.
    records = value.ledger.records(limit=5000)
    works = store.list_work(5000)
    canonical = store.records(limit=5000)
    ids = (
        [r["id"] for r in records if not r["id"].startswith(("candidate-", "health-"))]
        + [w.work_item_id for w in works]
        + [w.mission_id for w in works]
    )
    # Configured roles are private to each authoritative database even when the
    # same four executor names appear in disposable databases sharing Neo4j.
    ids.extend(
        database + ":agent:" + r[key]
        for r in records
        for key in ("agent_id", "parent_agent", "builder", "qa_agent")
        if r.get(key) and isinstance(r[key], str)
    )
    for row in canonical:
        for key in (
            "journal_id",
            "handoff_id",
            "review_id",
            "policy_decision_id",
            "packet_id",
            "event_id",
        ):
            if key in row:
                ids.append(row[key])
        if row["kind"] == "JournalEntry":
            (ROOT / f"docs/vault/02_Journal/generated/{row['journal_id']}.md").unlink(
                missing_ok=True
            )
    for record in records:
        if record["kind"] == "CycleSummary":
            (ROOT / f"docs/vault/02_Journal/generated/cycle-{record['cycle_id']}.md").unlink(
                missing_ok=True
            )
    with Brain(store).driver() as d, d.session() as session:
        session.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=ids).consume()
    assert database.startswith("triad_test_") and len(database) == 43
    with admin.connect() as c:
        c.autocommit = True
        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


def active(engine):
    work = engine.make_work("CODEX", str(uuid4()))
    return engine.start_work(work)


def test_full_rotation_exact_commits_summary_and_lineage(engine):
    cycle = engine.run("SIMULATED")
    assert cycle["status"] == "COMPLETED", cycle
    assert cycle["summary"]["agents_run"] == ("CODEX", "CLAUDE", "GROK") or cycle["summary"][
        "agents_run"
    ] == ["CODEX", "CLAUDE", "GROK"]
    assert len(cycle["summary"]["changes_accepted"]) == 3
    for identifier in cycle["summary"]["changes_accepted"]:
        change = engine.ledger.get(identifier)
        assert change["agent"] != change["reviewer"] and change["status"] == "MERGED"
        assert all(
            change["git"][k]
            for k in ("base_commit", "change_commit", "review_commit", "merge_commit")
        )
        work = engine.host.store.get(change["work_item_id"])
        assert work.status == State.COMPLETED
        assert {"JournalEntry", "Handoff", "Review"} <= {
            r["kind"] for r in engine.host.store.records(work_id=work.work_item_id)
        }
        assert any(
            r["relationship"] == "CREATED_COMMIT"
            for r in Brain(engine.host.store).lineage(work.work_item_id)
        )
    assert engine.run("SIMULATED")["cycle_id"] == cycle["cycle_id"]
    assert engine.git.git("status", "--porcelain") == ""
    assert (ROOT / f"docs/vault/02_Journal/generated/cycle-{cycle['cycle_id']}.md").exists()


def test_daily_slots_and_cost_token_compute_reservations(engine):
    ledger = engine.ledger
    ledger.reserve("CODEX", "fixture-1", improvement=True, day=engine.day)
    with pytest.raises(PermissionError, match="slot"):
        ledger.reserve("CODEX", "fixture-2", improvement=True, day=engine.day)
    with pytest.raises(PermissionError, match="AUTONOMY_BUDGET_EXHAUSTED"):
        ledger.reserve("CLAUDE", "fixture-3", cost=0.001, day=engine.day)
    with pytest.raises(PermissionError, match="AUTONOMY_BUDGET_EXHAUSTED"):
        ledger.reserve("CLAUDE", "fixture-3", tokens=999999, day=engine.day)
    with pytest.raises(PermissionError, match="AUTONOMY_BUDGET_EXHAUSTED"):
        ledger.reserve("CLAUDE", "fixture-3", seconds=999999, day=engine.day)
    ledger.operate("lower_limits", limits={"max_changes_day": 1})
    with pytest.raises(PermissionError, match="AUTONOMY_BUDGET_EXHAUSTED"):
        ledger.reserve("CLAUDE", "fixture-3", improvement=True, day=engine.day)
    with pytest.raises(PermissionError, match="only lower"):
        ledger.operate("lower_limits", limits={"max_changes_day": 2})


def test_kill_switch_cancels_inflight_and_blocks_new_requests_merges_and_legacy(engine):
    work, policy = active(engine)
    req = engine.request(work, policy, "PROPOSE", {})
    started = threading.Event()
    release = threading.Event()

    class Slow(SimulatedProvider):
        def execute(self, request):
            started.set()
            release.wait(5)
            return (
                AgentRunResult(
                    run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Late output"
                ),
                0,
                0,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            engine.runtime.execute, req, mode="SIMULATED", day=engine.day, adapter=Slow("CODEX")
        )
        assert started.wait(3)
        engine.ledger.operate("kill")
        with pytest.raises(Stopped):
            future.result(timeout=3)
        release.set()
    assert engine.ledger.control()["killed"]
    assert not engine.ledger.records("AgentRunResult")
    with pytest.raises(Stopped):
        engine.runtime.execute(req, mode="SIMULATED", day=engine.day)
    with pytest.raises(Stopped):
        engine.host.run(work.work_item_id)
    with pytest.raises(Stopped), engine.ledger.gate("CODEX", work.work_item_id):
        pytest.fail("Merge gate opened while killed")
    engine.ledger.operate("resume")
    engine.ledger.guard()
    with pytest.raises(Stopped):
        engine.runtime.execute(req, mode="SIMULATED", day=engine.day)


def test_runtime_rejects_raised_budget_and_wrong_identity(engine):
    work, policy = active(engine)
    req = engine.request(work, policy, "PROPOSE", {})
    with pytest.raises(PermissionError):
        engine.runtime.execute(
            req.model_copy(update={"token_budget": work.compute_budget.max_output_tokens + 1}),
            mode="SIMULATED",
            day=engine.day,
        )
    with pytest.raises(PermissionError):
        engine.runtime.execute(
            req.model_copy(update={"agent_id": "GROK"}), mode="SIMULATED", day=engine.day
        )
    assert (
        engine.request_reasoning(
            work.work_item_id, "CODEX", work.reasoning_budget + 1, "Need more analysis"
        )["decision"]
        == "REQUIRE_HUMAN_APPROVAL"
    )
    assert engine.host.store.get(work.work_item_id).reasoning_budget == work.reasoning_budget


def test_provider_output_cannot_print_secrets_or_claim_shell_execution(engine, monkeypatch):
    secret = "test-runtime-secret-value-1234567"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    work, policy = active(engine)
    req = engine.request(work, policy, "PROPOSE", {})

    class Unsafe(SimulatedProvider):
        def execute(self, request):
            return (
                AgentRunResult(
                    run_id=request.run_id,
                    status="NO_CHANGE_JUSTIFIED",
                    summary=secret,
                    commands_executed=("shell",),
                ),
                0,
                0,
            )

    with pytest.raises(PermissionError):
        engine.runtime.execute(req, mode="SIMULATED", day=engine.day, adapter=Unsafe("CODEX"))
    assert secret not in json.dumps(engine.ledger.records(), default=str)
    assert engine.ledger.records("Usage")[0]["status"] == "FAILED"


def test_review_rejection_persists_disagreement_and_never_merges(engine, monkeypatch):
    original = engine.runtime.provider

    class Rejecting(SimulatedProvider):
        def execute(self, request):
            if request.role == "REVIEW":
                return (
                    AgentRunResult(
                        run_id=request.run_id,
                        status="NO_CHANGE_JUSTIFIED",
                        summary="Evidence inadequate",
                        review_decision="REJECT",
                        findings=("Needs additional source evidence",),
                    ),
                    0,
                    0,
                )
            return super().execute(request)

    monkeypatch.setattr(
        engine.runtime,
        "provider",
        lambda agent, mode="REAL": (
            Rejecting(agent) if mode == "SIMULATED" else original(agent, mode)
        ),
    )
    before = engine.git.git("rev-parse", "HEAD")
    cycle = engine.run("SIMULATED")
    assert cycle["status"] == "BLOCKED"
    assert engine.git.git("rev-parse", "HEAD") == before
    assert engine.ledger.records("Disagreement")[0]["human_review_required"]
    assert engine.ledger.records("Change")[0]["status"] == "REJECT"


def test_no_change_justified_does_not_create_commits(engine, monkeypatch):
    class NoChange(SimulatedProvider):
        def execute(self, request):
            if request.role == "PROPOSE":
                return (
                    AgentRunResult(
                        run_id=request.run_id,
                        status="NO_CHANGE_JUSTIFIED",
                        summary="No evidence justifies another edit",
                    ),
                    0,
                    0,
                )
            return super().execute(request)

    monkeypatch.setattr(engine.runtime, "provider", lambda agent, mode="REAL": NoChange(agent))
    before = engine.git.git("rev-parse", "HEAD")
    cycle = engine.run("SIMULATED")
    assert cycle["status"] == "COMPLETED", cycle
    assert engine.git.git("rev-parse", "HEAD") == before
    assert all(r["status"] == "NO_CHANGE_JUSTIFIED" for r in engine.ledger.records("Change"))


def test_real_unavailable_cycle_never_substitutes_simulation(engine):
    with pytest.raises(PermissionError, match="PROVIDER_GATE_BLOCKED"):
        engine.run("REAL")
    assert not engine.ledger.records("Cycle")
    assert not engine.ledger.records("Usage")


def test_helper_scope_delegation_and_secrets(engine, monkeypatch):
    work, _policy = active(engine)
    with pytest.raises(PermissionError):
        support(engine, work.work_item_id, "LOCAL_QWEN", "SUMMARY", "fixture")
    with pytest.raises(PermissionError):
        support(engine, work.work_item_id, "CODEX", "SHELL", "fixture")
    monkeypatch.setenv("XAI_API_KEY", "fixture-do-not-transmit-123456")
    with pytest.raises(PermissionError):
        support(engine, work.work_item_id, "CODEX", "SUMMARY", "fixture-do-not-transmit-123456")
    engine.ledger.operate("lower_limits", limits={"max_delegation_depth": 0})
    with pytest.raises(PermissionError, match="Delegation disabled"):
        support(engine, work.work_item_id, "CODEX", "SUMMARY", "fixture")


def test_operator_controls_require_auth_and_never_raise_governance(engine):
    app.dependency_overrides[cycles_service] = lambda: engine
    app.dependency_overrides[service] = lambda: engine.host
    try:
        client = TestClient(app)
        assert client.post("/api/day3/control", json={"action": "kill"}).status_code == 401
        token = engine.host.store.settings.triad_operator_token.get_secret_value()
        headers = {"Authorization": "Bearer " + token}
        assert (
            client.post("/api/day3/control", json={"action": "kill"}, headers=headers).status_code
            == 200
        )
        assert client.get("/api/day3/dashboard").status_code == 200
        assert (
            client.post("/api/day3/cycles", json={"mode": "SIMULATED"}, headers=headers).status_code
            == 403
        )
        assert (
            client.post("/api/day3/control", json={"action": "resume"}, headers=headers).status_code
            == 200
        )
        assert (
            client.post(
                "/api/day3/control",
                json={"action": "lower_limits", "limits": {"max_migrations": 1}},
                headers=headers,
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/day3/control", json={"action": "enable_live"}, headers=headers
            ).status_code
            == 422
        )
    finally:
        app.dependency_overrides.clear()


def test_conflicting_reviews_persist_edges_and_block_consensus(engine):
    work, _policy = active(engine)
    first = {
        "review_id": str(uuid4()),
        "reviewer": "CLAUDE",
        "worker": "CODEX",
        "decision": "APPROVE",
        "change_commit": "test-commit",
        "evidence_checked": ["fixture:evidence"],
    }
    second = {**first, "review_id": str(uuid4()), "reviewer": "GROK", "decision": "REJECT"}
    engine.record_review(first, work.work_item_id)
    engine.record_review(second, work.work_item_id)
    disputes = engine.ledger.records("Disagreement")
    assert len(disputes) == 1 and disputes[0]["status"] == "OPEN"
    Brain(engine.host.store).flush()
    with Brain(engine.host.store).driver() as d, d.session() as session:
        row = session.run(
            "MATCH (a:Day3Record {id:$id})-[:DISAGREES_WITH]->(b) RETURN b.id AS id",
            id=first["review_id"],
        ).single()
        assert row["id"] == second["review_id"]


def test_human_review_gate_and_runtime_rollback(engine):
    engine.ledger.operate("human_review")
    engine.run("SIMULATED")
    change = engine.ledger.records("Change")[0]
    assert change["status"] == "AWAITING_HUMAN_MERGE"
    assert not change["git"].get("merge_commit")
    merged = engine.review_change(change["id"], human_merge=True)
    assert merged["status"] == "MERGED"
    engine.day = "2001-01-02"
    rollback = engine.prepare_rollback(change["id"])
    assert rollback["git"]["reverts_commit"] == merged["git"]["change_commit"]
    engine.review_change(rollback["id"])
    reverted = engine.review_change(rollback["id"], human_merge=True)
    assert reverted["status"] == "MERGED"
    assert engine.ledger.get(change["id"])["status"] == "ROLLED_BACK"
    assert not (engine.git.root / "docs/improvements" / f"{change['work_item_id']}.md").exists()


def test_interrupted_cycle_recovery_retains_budget_and_blocks_work(engine):
    cycle_id = str(uuid4())
    work = engine.make_work("CODEX", cycle_id)
    engine.ledger.put("Cycle", {"cycle_id": cycle_id, "status": "RUNNING"}, identifier=cycle_id)
    before = engine.ledger.totals()
    assert engine.recover()["recovered"] == [cycle_id]
    assert engine.host.store.get(work.work_item_id).status == State.BLOCKED
    assert engine.ledger.totals() == before


def test_helper_delegation_count_is_persistently_bounded(engine, monkeypatch):
    work, _policy = active(engine)

    def output(request, **kwargs):
        return AgentRunResult(
            run_id=request.run_id,
            status="RESEARCH_FINDING",
            summary="Bounded synthetic helper result",
        )

    monkeypatch.setattr(engine.runtime, "execute", output)
    result = support(engine, work.work_item_id, "CODEX", "SUMMARY", "Synthetic observation")
    assert engine.host.store.get(result["work_item_id"]).result.execution_mode == "ollama"
    with pytest.raises(PermissionError, match="count exhausted"):
        support(engine, work.work_item_id, "CODEX", "SUMMARY", "Another observation")


def test_unsafe_proposal_and_runtime_permissions_are_denied(engine):
    work, policy = active(engine)
    request = engine.request(work, policy, "PROPOSE", {})
    with pytest.raises(PermissionError, match="role grant"):
        engine.runtime.execute(
            request.model_copy(update={"execution_permissions": ("live_trading",)}),
            mode="SIMULATED",
            day=engine.day,
        )
    from triad.day3.contracts import ImprovementProposal

    proposal = ImprovementProposal(
        agent="CODEX",
        title="Unsafe",
        problem="fixture",
        evidence=("fixture",),
        proposed_change="Change permissions",
        expected_benefit="none",
        possible_downside="escalation",
        affected_components=("agents",),
        risk_class="LOW",
        reversibility="revert",
        test_plan=("fixture",),
        rollback_plan="revert",
        estimated_cost=0,
        permissions_required=("governance",),
    )
    assert engine.evaluate_proposal(proposal, work) == "DENY"
    with pytest.raises(PermissionError):
        engine.proposal_action(proposal.proposal_id, "approve")
    assert (
        engine.evaluate_proposal(proposal.model_copy(update={"risk_class": "HIGH"}), work)
        == "REQUIRE_HUMAN_APPROVAL"
    )


def test_cycle_reports_budget_stop_without_reset(engine):
    # Simulation is explicitly local; exercise a deliberately enabled local cap.
    assert engine.ledger.control()["daily_execution_caps"]["LOCAL"] is False
    engine.ledger.configure_non_api_daily_caps(local=True)
    engine.ledger.operate("lower_limits", limits={"max_tokens_day": 0})
    cycle = engine.run("SIMULATED")
    assert cycle["status"] == "BLOCKED"
    assert cycle["summary"]["failures"] == ["AUTONOMY_BUDGET_EXHAUSTED"]
    assert engine.ledger.totals()[0]["changes"] == 1
    assert not engine.ledger.records("Usage")
    assert engine.run("SIMULATED")["cycle_id"] == cycle["cycle_id"]
