# ruff: noqa: F401, F811
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from products.triad.daily import Daily
from products.triad.sequential import SequentialCycle
from products.triad.sequential_application import PLAN_PATH
from products.triad.sequential_corrections import claim_correction_build, prepare_correction
from test_day3_integration import engine
from test_proposal_revision_continuation import candidate
from trading_core.intelligence.records import Records
from trading_core.product_changes import (
    ProductFileChange,
    ProductGit,
    RequiredCheck,
    acceptance_problems,
)
from trading_core.product_workspace_grant import PROFILE
from trading_core.resource_policy import scope_digest
from trading_core.store import Store
from trading_core.work import State, WorkItem

pytestmark = pytest.mark.integration


def seed_work(store, w):
    initial = store.create(w.model_copy(update={"status": State.CREATED}))
    store.step(initial, w.model_copy(update={"revision": 1}), "Independent fixture terminal state")
    return store.get(w.work_item_id)


@pytest.fixture
def proof(engine, request):
    v = getattr(request.node, "callspec", None)
    variant = v.params.get("variant") if v else None
    h = Records(Store(engine.host.store.settings))
    d = Daily(h.store)
    cycle = d.create()
    m = cycle.cycle_id
    for state in ("INSPECTING", "SELECTING", "BUILDING", "AWAITING_QA"):
        d.transition(m, state, ["fixture"])
    day = "2001-01-01"
    h.append(
        "SequentialDailyProgram",
        {
            "cycle_id": m,
            "policy_id": "fixture",
            "order": ["CODEX", "CLAUDE", "GROK"],
            "parent_work_item_id": cycle.parent_work_item_id,
            "control_epoch": cycle.control_epoch,
            "local_date": day,
            "timezone": "America/Chicago",
        },
        owner="triad",
    )
    root = Path(engine.git.root)
    plan = json.loads(Path("app/products/triad/application_plan.json").read_text())
    p = root / PLAN_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps(plan)
    p.write_text(original)
    engine.git.git("add", ".")
    engine.git.git("commit", "-m", "fixture")
    base = engine.git.clean_baseline()
    plan["architecture_reasoning"] += " Independent correction fixture."
    content = json.dumps(plan)
    w = WorkItem(
        owner="triad",
        mission_id=m,
        parent_work_item_id=cycle.parent_work_item_id,
        assigned_agent="CODEX",
        title="Candidate",
        description="Fixture",
        status=State.CHANGES_REQUESTED,
        authority_tier=2,
        work_type="development",
        execution_permissions=("read", "write_code"),
        allowed_tools=("read_file", "write_artifact"),
        allowed_paths=(PLAN_PATH,),
        reviewer="CLAUDE",
    )
    w = seed_work(h.store, w)
    rw = WorkItem(
        owner="triad",
        mission_id=m,
        parent_work_item_id=cycle.parent_work_item_id,
        assigned_agent="CLAUDE",
        title="Review",
        description="Fixture",
        status=State.COMPLETED,
        authority_tier=0,
        work_type="review",
        execution_permissions=("read",),
        allowed_tools=("read_file",),
        allowed_paths=(),
        review_required=False,
    )
    rw = seed_work(h.store, rw)
    prop = candidate().model_copy(
        update={
            "outcome": "CHANGE",
            "files": (PLAN_PATH,),
            "acceptance": (
                RequiredCheck(
                    check_id="behavior", method="PYTHON_UNIT_TEST", description="Required assertion"
                ),
            ),
        }
    )
    ap = h.append(
        "ProductTurnApproval",
        {
            "cycle_id": m,
            "builder": "CODEX",
            "reviewer": "CLAUDE",
            "policy_id": "fixture",
            "base_commit": base,
            "proposal": prop.model_dump(mode="json"),
            "proposal_sha256": hashlib.sha256(prop.model_dump_json().encode()).hexdigest(),
        },
        owner="triad",
    )
    h.append(
        "ProductWorkspaceGrant",
        {
            "profile": PROFILE,
            "work_item_id": w.work_item_id,
            "agent": "CODEX",
            "scope_digest": scope_digest(w),
            "epoch": cycle.control_epoch,
            "policy_id": "fixture",
            "base_commit": base,
            "approval_id": ap,
            "writable_files": [PLAN_PATH],
        },
        owner="triad",
        identifier="workspace-" + w.work_item_id,
    )
    g = ProductGit((PLAN_PATH,), root=root, worktrees=engine.git.worktrees)
    meta = g.isolate(w.work_item_id, "CODEX")
    patch = {
        "files": [
            {
                "path": PLAN_PATH,
                "content": content,
                "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
            }
        ]
    }
    g.apply(meta, [ProductFileChange(**patch["files"][0])])
    g.commit(meta, "CODEX")
    checks = g.verify(meta)
    for kind, payload in [
        (
            "AgentRunRequest",
            {
                "run_id": "build-run",
                "work_item_id": w.work_item_id,
                "mission_id": m,
                "agent_id": "CODEX",
                "role": "IMPLEMENT",
                "control_epoch": cycle.control_epoch,
            },
        ),
        (
            "AgentRunResult",
            {
                "run_id": "build-run",
                "status": "CODE_CHANGE",
                "analysis_artifacts": [json.dumps(patch)],
            },
        ),
    ]:
        h.ledger.put(kind, payload, work_id=w.work_item_id)
    h.ledger.event(
        "native_executor_evidence",
        w.work_item_id,
        run_id="build-run",
        boundary="DOCKER_PRODUCT_WORKSPACE",
        denied_operations=0,
    )
    h.ledger.reserve(
        "CODEX", w.work_item_id, improvement=True, day=day, billing_source="SUBSCRIPTION"
    )
    h.ledger.reserve(
        "CODEX", w.work_item_id, tokens=50, seconds=2, day=day, billing_source="SUBSCRIPTION"
    )
    ids = [
        h.append(
            "EngineeringTestRun",
            {"commit": meta["change_commit"], "work_item_id": w.work_item_id, "status": "PASS"},
            owner="triad",
        )
        for _ in range(2)
    ]
    checks["test_record_id"] = ids[0]
    build = {
        "implementation_id": "implementation-fixture",
        "mission_id": m,
        "builder": "CODEX",
        "work_item_id": w.work_item_id,
        "git": meta,
        "checks": checks,
        "approval": ap,
    }
    build["id"] = h.append("ProductBuild", build, owner="triad")
    assessment = {
        "checks": [
            {
                "check_id": x.check_id,
                "status": "NOT_VERIFIED",
                "evidence_ids": [],
                "reason": "Missing exact test assertion",
            }
            for x in prop.acceptance
        ]
    }
    required = [x.model_dump(mode="json") for x in prop.acceptance]
    problems = list(acceptance_problems(required, assessment, meta["change_commit"], {}))
    qa_id = "qa-fixture"
    run = "qa-run"
    findings = ["Add two missing assertions"]
    rid = h.append(
        "ProductAcceptanceReview",
        {
            "cycle_id": m,
            "implementation_id": build["implementation_id"],
            "qa_id": qa_id,
            "reviewer": "CLAUDE",
            "commit": meta["change_commit"],
            "approval_id": ap,
            "required": required,
            "run_id": run,
            "assessment": assessment,
            "test_record_ids": ids,
            "problems": problems,
        },
        owner="triad",
    )
    qa = {
        "qa_run_id": qa_id,
        "qa_provider": "anthropic",
        "qa_model": "fixture",
        "agent_capabilities_used": ["structured_output"],
        "tests_repeated": ["unit fixture"],
        "implementation_run_id": build["implementation_id"],
        "decision": "CHANGES_REQUIRED",
        "qa_agent": "CLAUDE",
        "execution_mode": "REAL_PROVIDER",
        "reviewed_commit": meta["change_commit"],
        "evidence": ["acceptance-review:" + rid, "run:" + run],
        "qa_work_item_id": rw.work_item_id,
        "required_changes": problems,
        "findings": findings + problems,
    }
    h.append("QARun", qa, owner="triad", identifier=qa_id)
    req = {
        "run_id": run,
        "work_item_id": rw.work_item_id,
        "mission_id": m,
        "agent_id": "CLAUDE",
        "role": "REVIEW",
        "control_epoch": cycle.control_epoch,
        "execution_permissions": ["read"],
        "allowed_tools": ["read_file"],
        "allowed_paths": [],
        "context_packet": {
            "proposal": prop.model_dump(mode="json"),
            "exact_commit": meta["change_commit"],
        },
    }
    raw = {
        "run_id": run,
        "status": "RESEARCH_FINDING",
        "mode": "REAL",
        "summary": "Need correction",
        "review_decision": "REQUEST_CHANGES",
        "analysis_artifacts": [assessment],
        "findings": findings,
    }
    usage = {
        "run_id": run,
        "status": "SUCCESS",
        "mode": "REAL",
        "duration": 1.0,
        "agent": "CLAUDE",
        "usage_known": True,
        "input_tokens": 100,
        "output_tokens": 50,
        "provider": "anthropic",
        "transport": "claude_code_cli",
    }
    if variant == "payload_work":
        req["work_item_id"] = "wrong-work"
    if variant == "unknown_usage":
        usage["usage_known"] = False
    if variant == "wrong_provider":
        usage["provider"] = "openai"
    if variant == "write_tools":
        req["allowed_tools"] = ["write_file"]
    if variant == "REJECT":
        raw["review_decision"] = "REJECT"
    if variant == "BLOCKED":
        raw["status"] = "BLOCKED"
    if variant == "result_work":
        raw["work_item_id"] = "wrong-work"
    if variant == "usage_work":
        usage["work_item_id"] = "wrong-work"
    if variant == "bool_tokens":
        usage["input_tokens"] = True
    if variant == "wrong_commit":
        req["context_packet"]["exact_commit"] = "0" * 40
    if variant == "wrong_proposal":
        req["context_packet"]["proposal"] = {}
    if variant == "paths":
        req["allowed_paths"] = [".env"]
    for kind, payload in [("AgentRunRequest", req), ("AgentRunResult", raw), ("Usage", usage)]:
        h.ledger.put(kind, payload, work_id=rw.work_item_id)

    h.append(
        "CapabilityRoutingDecision",
        {
            "selected": {
                "agent_id": "CLAUDE",
                "provider": "anthropic",
                "transport": "claude_code_cli",
            }
        },
        owner="triad",
        identifier="route-" + rw.work_item_id,
    )
    if variant != "missing_transport":
        h.ledger.put(
            "TransportRun",
            {
                "run_id": run,
                "agent": "CLAUDE",
                "provider": "anthropic",
                "transport": "claude_code_cli",
                "status": "RUNNING" if variant == "active_transport" else "SUCCESS",
                "completed_at": None if variant == "active_transport" else "2001-01-01T00:00:00Z",
            },
            work_id=rw.work_item_id,
        )
    if variant != "missing_native":
        h.ledger.event(
            "native_executor_evidence",
            rw.work_item_id,
            run_id=run,
            boundary="DOCKER_OFFLINE_TOOLS",
            denials=0,
            usage_scope="PARTIAL_COMPLETED_TURNS" if variant == "partial_native" else "COMPLETE",
            calls=[{"tool": "read_file"}],
            input_tokens=100,
            output_tokens=50,
        )
    # Service shape matches real DailyDevelopment: product-scoped host, Core daily.host.
    f = object.__new__(SequentialCycle)
    f.root = root
    f.policy = {"id": "fixture"}
    f.improvement_day = day
    f.s = NS(
        daily=d,
        canonical=d.product,
        host=NS(store=d.product.store),
        ledger=d.product.ledger,
        git=engine.git,
    )
    f.guard = lambda _: d.product.ledger.guard(
        work_id=cycle.parent_work_item_id, epoch=cycle.control_epoch
    )
    return NS(
        flow=f,
        mission=m,
        work=w,
        reviewer=rw,
        proposal=prop,
        git=g,
        build=build,
        qa=qa_id,
        host=h,
        daily=d,
        day=day,
        qa_payload=qa,
    )


def snapshot(p):
    with p.host.store.connect() as c:
        return c.execute("SELECT * FROM core.autonomy_daily WHERE day=%s", (p.day,)).fetchone()


def prepare(p):
    return prepare_correction(p.flow, p.mission, "CODEX", p.proposal, p.git, p.build, p.qa)


def test_prepare_claim_single_dispatch_preserves_accounting(proof):
    p = proof
    before = snapshot(p)
    ret = prepare(p)
    assert ret["independent_qa"]["qa_id"] == p.qa and snapshot(p) == before
    p.daily.transition(p.mission, "CORRECTING", ["fixture"])
    claim_correction_build(p.flow, p.mission, "CODEX", p.proposal, p.build["approval"], ret)
    with pytest.raises(PermissionError, match="already attempted"):
        claim_correction_build(p.flow, p.mission, "CODEX", p.proposal, p.build["approval"], ret)
    with pytest.raises(PermissionError, match="already dispatched"):
        prepare(p)
    assert (
        snapshot(p) == before
        and p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
    )


@pytest.mark.parametrize(
    "variant",
    [
        "payload_work",
        "unknown_usage",
        "wrong_provider",
        "write_tools",
        "REJECT",
        "BLOCKED",
        "result_work",
        "usage_work",
        "bool_tokens",
        "wrong_commit",
        "wrong_proposal",
        "paths",
        "missing_transport",
        "active_transport",
        "missing_native",
        "partial_native",
    ],
)
def test_bad_review_proof_cannot_authorize_correction(proof, variant):
    with pytest.raises(PermissionError):
        prepare(proof)


@pytest.mark.parametrize("variant", ["stale", "dirty", "active", "epoch", "policy", "rollback"])
def test_guard_and_rollback(proof, variant, monkeypatch):
    p = proof
    before = snapshot(p)
    if variant == "stale":
        p.host.append("QARun", {**p.qa_payload, "decision": "REJECT"}, owner="triad")
    if variant == "dirty":
        (Path(p.build["git"]["worktree"]) / PLAN_PATH).write_text("changed")
    if variant == "active":
        seed_work(
            p.host.store,
            WorkItem(
                owner="triad",
                mission_id=p.mission,
                title="Active",
                description="Fixture",
                status=State.IN_PROGRESS,
            ),
        )
    if variant == "epoch":
        p.host.ledger.operate("pause")
    if variant == "policy":
        p.flow.policy["id"] = "other"
    if variant == "rollback":
        old = p.daily.host.ledger.put

        def fail(*a, **k):
            old(*a, **k)
            raise RuntimeError("Injected failure after insert")

        monkeypatch.setattr(p.daily.host.ledger, "put", fail)
    with pytest.raises((PermissionError, RuntimeError)):
        prepare(p)
    assert snapshot(p) == before
    with p.host.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("candidate-correction-" + p.qa,)
        ).fetchone()
