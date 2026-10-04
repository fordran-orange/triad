"""Disposable canonical evidence for continuation after the old revision cap."""

# ruff: noqa: F811
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from products.triad.daily import Daily
from products.triad.sequential_recovery import resume_patch_failure
from test_day3_integration import engine  # noqa: F401
from test_proposal_revision_continuation import candidate
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import State, WorkItem, now

pytestmark = pytest.mark.integration


@pytest.fixture
def checkpoint(engine, monkeypatch, request):
    variant = getattr(request.node, "callspec", None)
    tamper = variant.params.get("tamper") if variant else None
    host = Records(Store(engine.host.store.settings))
    daily = Daily(host.store)
    cycle = daily.create()
    m = cycle.cycle_id
    base = engine.git.clean_baseline()
    day = now().astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    host.append(
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
    host.append("ProductTurnStarted", {"mission_id": m, "agent": "CODEX"}, owner="triad")
    daily.transition(m, "INSPECTING", ["fixture"])
    daily.transition(m, "SELECTING", ["fixture"])
    proposal = candidate().model_dump(mode="json")
    summary = "Correct remaining contract"
    findings = ["Quality preflight before the engine"]
    host.append(
        "ProductProposal",
        {"mission_id": m, "proposer": "CODEX", "attempt": 3, "proposal": proposal},
        owner="triad",
    )
    works = []
    for index, agent in enumerate(("CODEX", "CLAUDE")):
        work = engine.host.create(
            WorkItem(
                owner="triad",
                mission_id=m,
                parent_work_item_id=cycle.parent_work_item_id,
                assigned_agent=agent,
                work_type="review",
                authority_tier=0,
                review_required=False,
                execution_permissions=("read",),
                allowed_tools=("read_file",),
                title="Disposable successful read",
                description="No provider execution",
            )
        )
        for status in (
            State.VALIDATING,
            State.APPROVED,
            State.ASSIGNED,
            State.IN_PROGRESS,
            State.COMPLETED,
        ):
            work = engine.host.advance(work, status, "fixture")
        works.append(work)
        run = f"fixture-read-{index}"
        host.ledger.reserve(agent, work.work_item_id, tokens=7, day=day)
        context = {
            "base_commit": base,
            "schema": {"title": "CurrentProposal"},
            "product_planning": {
                "cycle_id": m,
                "shared_core": {"source_revision": base},
                "application_plan": {"source_revision": base},
            },
        }
        if index:
            context["proposal"] = {"different": True} if tamper == "review_context" else proposal
        host.ledger.put(
            "AgentRunRequest",
            {
                "run_id": run,
                "work_item_id": work.work_item_id,
                "mission_id": m,
                "agent_id": agent,
                "role": "REVIEW",
                "control_epoch": cycle.control_epoch,
                "execution_permissions": ["read"],
                "allowed_tools": ["read_file"],
                "context_packet": context,
            },
            work_id=work.work_item_id,
        )
        result = {
            "run_id": run,
            "mode": "SIMULATED" if index and tamper == "mode" else "REAL",
            "status": "RESEARCH_FINDING",
            "proposal": None,
            "files_changed": [{"path": "claimed"}] if index and tamper == "claimed_edit" else [],
            "analysis_artifacts": [] if index else [candidate().model_dump_json()],
            "review_decision": "APPROVE"
            if index and tamper == "result_verdict"
            else "REQUEST_CHANGES",
            "summary": "Different" if index and tamper == "summary" else summary,
            "findings": ["Different"] if index and tamper == "findings" else findings,
        }
        host.ledger.put("AgentRunResult", result, work_id=work.work_item_id)
        host.ledger.put(
            "Usage",
            {
                "run_id": run,
                "mode": "REAL",
                "status": "SUCCESS",
                "agent": agent,
                "provider": "fixture-provider",
                "transport": "fixture-cli",
                "usage_known": True,
                "input_tokens": 20,
                "output_tokens": 10,
            },
            work_id=work.work_item_id,
        )
        transport = {
            "run_id": run,
            "work_item_id": work.work_item_id,
            "agent": agent,
            "provider": "fixture-provider",
            "transport": "fixture-cli",
            "status": "SUCCESS",
            "completed_at": now().isoformat(),
        }
        if index and tamper == "live":
            transport.update(status="RUNNING", completed_at=None)
        host.ledger.put("TransportRun", transport, work_id=work.work_item_id)
        if index and tamper == "duplicate":
            host.ledger.put("TransportRun", transport, work_id=work.work_item_id)
        native = (
            {
                "boundary": "DOCKER_REMOTE_EXECUTOR_READ_ONLY",
                "denied_operations": 0,
                "commands": ["cat evidence.txt"],
                "executed_argv": [["python", "-c", "read only", "evidence.txt"]],
            }
            if agent == "CODEX"
            else {
                "boundary": "DOCKER_OFFLINE_TOOLS",
                "denials": 1 if tamper == "denials" else 0,
                "calls": [{"tool": "read_file"}],
                "usage_scope": "COMPLETE",
            }
        )
        host.ledger.event(
            "native_executor_evidence",
            work.work_item_id,
            run_id=run,
            **native,
            input_tokens=20,
            output_tokens=10,
        )
        host.append(
            "CapabilityRoutingDecision",
            {
                "selected": {
                    "agent_id": agent,
                    "provider": "fixture-provider",
                    "transport": "fixture-cli",
                }
            },
            owner="triad",
            identifier="route-" + work.work_item_id,
        )
    review = {
        "mission_id": m,
        "proposer": "CODEX",
        "reviewer": "CLAUDE",
        "attempt": 3,
        "proposal": proposal,
        "decision": "APPROVE" if tamper == "verdict" else "REQUEST_CHANGES",
        "summary": summary,
        "findings": findings,
        "run_id": "fixture-read-1",
    }
    if tamper == "attempt":
        review["attempt"] = 2
    host.append("ProductProposalReview", review, owner="triad")
    daily.transition(
        m,
        "BLOCKED",
        ["PermissionError"],
        failures=(
            {
                "code": "PermissionError",
                "message": "Proposal revision attempts exhausted: " + summary,
            },
        ),
    )
    flow = NS(s=NS(daily=daily, git=engine.git), policy={"id": "fixture"})
    flow.guard = lambda _: host.ledger.guard(
        work_id=cycle.parent_work_item_id, epoch=cycle.control_epoch
    )
    monkeypatch.setattr(
        "products.triad.sequential_recovery.health", lambda r: {"loaded_revision": r}
    )
    return NS(flow=flow, daily=daily, host=host, cycle=cycle, day=day, works=works)


def test_exact_review_continuation_preserves_work_and_accounting(checkpoint):
    b = checkpoint
    before = b.host.ledger.totals()
    record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)
    assert record.status == "CREATED" and count == 0 and day == b.day
    assert b.host.ledger.totals() == before
    assert all(b.host.store.get(w.work_item_id).status == State.COMPLETED for w in b.works)
    action = b.host.ledger.records("ControlAction")[0]
    assert (
        action["action"] == "continue_reviewed_product_revision"
        and action["released_change_slots"] == 0
    )
    assert action["review_checkpoint_id"] and action["retained_proposal_id"] is None
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)


@pytest.mark.parametrize(
    "tamper",
    [
        "verdict",
        "attempt",
        "mode",
        "claimed_edit",
        "result_verdict",
        "summary",
        "findings",
        "review_context",
        "live",
        "duplicate",
        "denials",
    ],
)
def test_unproved_review_continuation_rejects_without_effect(checkpoint, tamper):
    b = checkpoint
    before = b.host.ledger.totals()
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)
    assert b.host.ledger.totals() == before
    assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"
