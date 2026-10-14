# ruff: noqa: F401, F811
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential_correction_renewal import PREFIX
from products.triad.sequential_qa_recovery import resume_citation_failure
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, prepare, proof, seed_work, snapshot
from trading_core.work import State, WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.triad]


def closed_read(p, agent, run, context, raw, paths=(), parent=None):
    work = seed_work(
        p.host.store,
        WorkItem(
            owner="triad",
            mission_id=p.mission,
            parent_work_item_id=parent or p.daily.current(p.mission)["parent_work_item_id"],
            assigned_agent=agent,
            title="Read-only correction reasoning",
            description="Disposable proof",
            status=State.COMPLETED,
            work_type="review",
            authority_tier=0,
            execution_permissions=("read",),
            allowed_tools=("read_file",),
            allowed_paths=paths,
            review_required=False,
        ),
    )
    provider, transport = (
        ("anthropic", "claude_code_cli") if agent == "CLAUDE" else ("openai", "codex_cli")
    )
    request = {
        "run_id": run,
        "work_item_id": work.work_item_id,
        "mission_id": p.mission,
        "agent_id": agent,
        "role": "REVIEW",
        "control_epoch": p.daily.current(p.mission)["control_epoch"],
        "execution_permissions": ["read"],
        "allowed_tools": ["read_file"],
        "allowed_paths": list(paths),
        "context_packet": context,
    }
    result = {"run_id": run, "status": "RESEARCH_FINDING", "mode": "REAL", **raw}
    usage = {
        "run_id": run,
        "status": "SUCCESS",
        "mode": "REAL",
        "duration": 1.0,
        "agent": agent,
        "usage_known": True,
        "input_tokens": 100,
        "output_tokens": 50,
        "provider": provider,
        "transport": transport,
    }
    for kind, payload in [
        ("AgentRunRequest", request),
        ("AgentRunResult", result),
        ("Usage", usage),
        (
            "TransportRun",
            {
                "run_id": run,
                "agent": agent,
                "provider": provider,
                "transport": transport,
                "status": "SUCCESS",
                "completed_at": "2001-01-01T00:00:00Z",
            },
        ),
    ]:
        p.host.ledger.put(kind, payload, work_id=work.work_item_id)
    p.host.append(
        "CapabilityRoutingDecision",
        {"selected": {"agent_id": agent, "provider": provider, "transport": transport}},
        owner="triad",
        identifier="route-" + work.work_item_id,
    )
    evidence = {"input_tokens": 100, "output_tokens": 50}
    if agent == "CODEX":
        evidence.update(
            boundary="DOCKER_REMOTE_EXECUTOR_READ_ONLY",
            denied_operations=0,
            commands=["read_file"],
            executed_argv=[["python", "read_file"]],
        )
    else:
        evidence.update(
            boundary="DOCKER_OFFLINE_TOOLS",
            denials=0,
            usage_scope="COMPLETE",
            calls=[{"tool": "read_file"}],
        )
    p.host.ledger.event("native_executor_evidence", work.work_item_id, run_id=run, **evidence)
    return work


@pytest.fixture
def stopped(proof, request):
    p = proof
    p.retained = prepare(p)
    p.daily.transition(p.mission, "CORRECTING", [p.qa])
    summary = "REQUEST_CHANGES. Address the actual missing engine and browser assertions. " * 12
    tamper = getattr(request.node, "callspec", None)
    tamper = tamper.params.get("tamper") if tamper else None
    other_parent = (
        seed_work(
            p.host.store,
            WorkItem(
                owner="triad",
                mission_id=p.mission,
                title="Other parent",
                description="Disposable independent authority",
                authority_tier=0,
                execution_permissions=("read",),
                allowed_tools=("read_file",),
                status=State.COMPLETED,
            ),
        )
        if tamper == "parent"
        else None
    )
    p.review_work = closed_read(
        p,
        "CLAUDE",
        "renewal-review",
        {
            "proposal": p.proposal.model_dump(mode="json"),
            "base_commit": p.build["git"]["base_commit"],
            "task_assignment": {"phase": "PROPOSAL_REVIEWER"},
            "retained_unmerged_candidate": p.retained,
        },
        {
            "summary": summary,
            "review_decision": "REQUEST_CHANGES",
            "findings": ["Specific assertions missing"],
            "analysis_artifacts": [],
        },
        parent=other_parent.work_item_id if other_parent else None,
    )
    p.review_id = p.host.append(
        "ProductProposalReview",
        {
            "mission_id": p.mission,
            "proposer": "CODEX",
            "reviewer": "CLAUDE",
            "attempt": 2,
            "proposal": p.proposal.model_dump(mode="json"),
            "run_id": "renewal-review",
            "decision": "REJECT" if tamper == "verdict" else "REQUEST_CHANGES",
            "summary": "different" if tamper == "summary" else summary,
            "findings": ["Specific assertions missing"],
        },
        owner="triad",
    )
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": (PREFIX + summary)[:500]},),
    )
    return p


def healthy(monkeypatch):
    monkeypatch.setattr(
        "products.triad.sequential_qa_recovery.health",
        lambda head: {"loaded_revision": head, "development_provider_gate": "PASS"},
    )


def test_resume_exact_closed_renewal_reuses_checkpoint_and_retains_rejected_work(
    stopped, monkeypatch
):
    p = stopped
    healthy(monkeypatch)
    before = snapshot(p)
    cycle, count, day, _ = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and count == 0 and day == p.day
    assert (
        snapshot(p) == before
        and p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
    )
    assert p.flow._prepared_correction["renewal_feedback"]["id"] == p.review_id
    with p.host.store.connect() as c:
        assert (
            len(
                c.execute(
                    "SELECT 1 FROM core.day3_records WHERE id=%s", ("candidate-correction-" + p.qa,)
                ).fetchall()
            )
            == 1
        )
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)


@pytest.mark.parametrize(
    "tamper",
    [
        "summary",
        "verdict",
        "unknown_usage",
        "candidate",
        "parent",
        "duplicate_result",
        "claim",
        "new_build",
        "checkpoint",
        "write_assignment",
        "build_checkpoint",
    ],
)
def test_renewal_cannot_hide_unknown_execution_or_changed_review(stopped, monkeypatch, tamper):
    p = stopped
    healthy(monkeypatch)
    before = snapshot(p)
    with p.host.store.connect() as c:
        if tamper in {"summary", "verdict"}:
            pass  # Invalid canonical variants were seeded before publication.
        elif tamper == "unknown_usage":
            c.execute(
                "UPDATE core.day3_records SET payload=payload || %s WHERE kind='Usage' AND payload->>'run_id'='renewal-review'",
                (Jsonb({"usage_known": False}),),
            )
        elif tamper == "candidate":
            c.execute(
                "UPDATE core.day3_records SET payload=jsonb_set(payload,'{context_packet,retained_unmerged_candidate,commit}',%s) WHERE kind='AgentRunRequest' AND payload->>'run_id'='renewal-review'",
                (Jsonb("wrong"),),
            )
        elif tamper == "parent":
            pass  # Work authority is immutable; fixture creates a different parent.
        elif tamper == "checkpoint":
            c.execute(
                "UPDATE core.day3_records SET payload=payload || %s WHERE id=%s",
                (Jsonb({"released_change_slots": 1}), "candidate-correction-" + p.qa),
            )
    if tamper == "duplicate_result":
        p.host.ledger.put(
            "AgentRunResult", {"run_id": "renewal-review"}, work_id=p.review_work.work_item_id
        )
    elif tamper == "claim":
        p.host.ledger.put(
            "ControlAction", {"action": "attempted"}, identifier="correction-build-" + p.qa
        )
    elif tamper == "new_build":
        p.host.ledger.put(
            "AgentRunRequest",
            {"mission_id": p.mission, "run_id": "unsettled", "role": "IMPLEMENT"},
            work_id=p.work.work_item_id,
        )
    elif tamper == "write_assignment":
        seed_work(
            p.host.store,
            WorkItem(
                owner="triad",
                mission_id=p.mission,
                title="Failed before provider request",
                description="Disposable proof",
                assigned_agent="CODEX",
                work_type="development",
                authority_tier=2,
                execution_permissions=("read", "write_code"),
                status=State.FAILED,
            ),
        )
    elif tamper == "build_checkpoint":
        p.host.append(
            "ProductBuildCheckpoint",
            {"mission_id": p.mission, "phase": "ISOLATED", "work_item_id": "unknown"},
            owner="triad",
        )
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before
    with p.host.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s",
            ("qa-resume-" + p.qa + "-" + p.review_id,),
        ).fetchone()
