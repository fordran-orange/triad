# ruff: noqa: F401, F811
import hashlib
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential_correction_plan import CorrectionPlan, renew_with_plan
from products.triad.sequential_corrections import claim_correction_build
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, prepare, proof, snapshot
from test_correction_renewal_integration import closed_read

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.fixture
def planned(proof, request):
    p = proof
    p.retained = prepare(p)
    p.daily.transition(p.mission, "CORRECTING", [p.qa])
    target = Path(p.flow.root) / "app/products/triad/sequential_fixture.py"
    target.write_text("# Protected infrastructure moved the baseline\n")
    (Path(p.flow.root) / "app/products/triad/server.py").write_text(
        "# Read-only integration fixture\n"
    )
    p.flow.s.git.git("add", ".")
    p.flow.s.git.git("commit", "-m", "protected fixture")
    base = p.flow.s.git.clean_baseline()
    plan = CorrectionPlan.model_validate(
        {
            "summary": "Close exact remaining QA",
            "steps": [
                {
                    "check_id": "behavior",
                    "files": list(p.proposal.files),
                    "approach": "Add missing assertions and execute the repeated checks",
                }
            ],
        }
    )
    tamper = getattr(request.node, "callspec", None)
    tamper = tamper.params.get("tamper") if tamper else None
    author = closed_read(
        p,
        "CODEX",
        "plan-author",
        {
            "proposal": p.proposal.model_dump(mode="json"),
            "base_commit": base,
            "retained_unmerged_candidate": p.retained,
            "task_assignment": {"phase": "CORRECTION_AUTHOR"},
        },
        {"summary": "Correction plan", "analysis_artifacts": [plan.model_dump(mode="json")]},
        paths=p.proposal.files,
    )
    identifier = p.host.append(
        "ProductCorrectionPlan",
        {
            "mission_id": p.mission,
            "agent": "CODEX",
            "base_commit": base,
            "original_approval": p.build["approval"],
            "candidate_commit": "different" if tamper == "candidate" else p.retained["commit"],
            "qa_id": "different" if tamper == "qa" else p.qa,
            "author_work_item_id": author.work_item_id,
            "author_run_id": "plan-author",
            "plan": {"summary": "Altered", "steps": []}
            if tamper == "plan"
            else plan.model_dump(mode="json"),
            "plan_sha256": hashlib.sha256(plan.model_dump_json().encode()).hexdigest(),
        },
        owner="triad",
    )
    row = p.host.get(identifier)
    p.retained["author_correction_plan"] = row
    reviewer = closed_read(
        p,
        "CLAUDE",
        "plan-review",
        {
            "proposal": p.proposal.model_dump(mode="json"),
            "base_commit": base,
            "retained_unmerged_candidate": p.retained,
            "correction_plan": row,
            "task_assignment": {"phase": "PROPOSAL_REVIEWER"},
        },
        {
            "summary": "Approved remaining changes",
            "analysis_artifacts": [],
            "review_decision": "APPROVE",
        },
    )
    old = p.host.get(p.build["approval"])
    p.renewed = p.host.append(
        "ProductTurnApproval",
        {
            **old,
            "base_commit": base,
            "author_work_item_id": author.work_item_id,
            "author_run_id": "plan-author",
            "review_work_item_id": reviewer.work_item_id,
            "run_id": "plan-review",
            "correction_plan_id": identifier,
            "correction_plan_sha256": "wrong"
            if getattr(request.node, "callspec", None)
            and request.node.callspec.params.get("tamper") == "approval_sha"
            else row["plan_sha256"],
            "correction_qa_id": p.qa,
            "correction_candidate_commit": p.retained["commit"],
        },
        owner="triad",
    )
    p.plan_id = identifier
    return p


def test_actual_plan_review_revision_then_claim_preserves_original_contract(planned, monkeypatch):
    p = planned
    before = snapshot(p)
    p.flow.s.canonical = p.host  # Actual approval writes require trusted Core ingestion.
    p.flow.retained_application_candidate = p.retained
    monkeypatch.setattr("products.triad.sequential_planning.planning_context", lambda *a: {})
    p.flow.s.record = lambda kind, mission, **payload: p.host.append(
        kind, {"mission_id": mission, **payload}, owner="triad"
    )
    p.flow.s.rows = lambda kind, mission: p.host.list(kind, matching={"mission_id": mission})
    author_count = reviewer_count = 0

    def call(mission, agent, objective, context, schema=None, paths=()):
        nonlocal author_count, reviewer_count
        if schema is CorrectionPlan:
            author_count += 1
            if author_count == 2:
                assert context["latest_renewal_feedback"]["findings"] == [
                    "Add the exact missing assertion"
                ]
            plan = CorrectionPlan.model_validate(
                {
                    "summary": "Close remaining QA",
                    "steps": [
                        {
                            "check_id": "behavior",
                            "files": list(p.proposal.files),
                            "approach": "Assert engine exception"
                            if author_count == 1
                            else "Inject post-preflight engine error and assert identical exception",
                        }
                    ],
                }
            )
            run = "auto-author-" + str(author_count)
            raw = {"summary": "Author plan", "analysis_artifacts": [plan.model_dump(mode="json")]}
            payload = plan
        else:
            reviewer_count += 1
            assert context["correction_review_version"] == "current-obligations-v2"
            assert context["current_correction_plan"] == context["correction_plan"]["plan"]
            assert "inventory" not in context and "product_planning" not in context
            assert "retained_unmerged_candidate" in context
            run = "auto-review-" + str(reviewer_count)
            raw = {
                "summary": "Plan assessed",
                "review_decision": "REQUEST_CHANGES" if reviewer_count == 1 else "APPROVE",
                "findings": ["Add the exact missing assertion"] if reviewer_count == 1 else [],
                "analysis_artifacts": [],
            }
            payload = None
        work = closed_read(p, agent, run, context, raw, paths=paths)
        return work, NS(**raw), payload, {"run_id": run}

    p.flow.call = call
    p.renewed, row = renew_with_plan(
        p.flow, p.mission, "CODEX", p.proposal, p.retained, p.flow.s.git.clean_baseline()
    )
    assert author_count == reviewer_count == 2
    assert row == p.retained["author_correction_plan"]
    approved = p.host.get(p.renewed)
    assert approved["proposal"] == p.proposal.model_dump(mode="json")
    claim(p)
    assert snapshot(p) == before


def claim(p):
    return claim_correction_build(p.flow, p.mission, "CODEX", p.proposal, p.renewed, p.retained)


def test_current_baseline_plan_binds_actual_author_independent_approval_and_one_slot(planned):
    p = planned
    before = snapshot(p)
    claim(p)
    assert snapshot(p) == before
    with p.host.store.connect() as c:
        row = c.execute(
            "SELECT payload FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()
    assert row["payload"]["correction_plan_id"] == p.plan_id
    assert row["payload"]["approval"] == p.renewed
    with pytest.raises(PermissionError, match="already attempted"):
        claim(p)


@pytest.mark.parametrize(
    "tamper",
    [
        "plan",
        "candidate",
        "qa",
        "author_response",
        "author_unknown",
        "author_phase",
        "author_context",
        "author_candidate",
        "review_plan",
        "review_verdict",
        "review_native",
        "approval_sha",
    ],
)
def test_plan_binding_cannot_substitute_proposed_text_for_closed_native_authority(planned, tamper):
    p = planned
    before = snapshot(p)
    with p.host.store.connect() as c:
        if tamper in {"plan", "candidate", "qa"}:
            pass  # Canonical records are immutable; seed invalid variants initially.
        elif tamper in {"author_context", "author_candidate"}:
            path, value = (
                ("{context_packet,task_assignment,phase}", "PROPOSAL_AUTHOR")
                if tamper == "author_context"
                else ("{context_packet,retained_unmerged_candidate,commit}", "wrong")
            )
            c.execute(
                "UPDATE core.day3_records SET payload=jsonb_set(payload,%s,%s) WHERE kind='AgentRunRequest' AND payload->>'run_id'='plan-author'",
                (path, Jsonb(value)),
            )
        elif tamper == "approval_sha":
            pass  # Immutable approval variant was constructed before publication.
        else:
            kind, run, update = {
                "author_response": (
                    "AgentRunResult",
                    "plan-author",
                    {"analysis_artifacts": [{"different": "plan"}]},
                ),
                "author_unknown": ("Usage", "plan-author", {"usage_known": False}),
                "author_phase": ("AgentRunRequest", "plan-author", {"role": "IMPLEMENT"}),
                "review_plan": (
                    "AgentRunRequest",
                    "plan-review",
                    {"context_packet": {"correction_plan": {}}},
                ),
                "review_verdict": (
                    "AgentRunResult",
                    "plan-review",
                    {"review_decision": "REQUEST_CHANGES"},
                ),
                "review_native": (
                    "TransportRun",
                    "plan-review",
                    {"status": "RUNNING", "completed_at": None},
                ),
            }[tamper]
            c.execute(
                "UPDATE core.day3_records SET payload=payload || %s WHERE kind=%s AND payload->>'run_id'=%s",
                (Jsonb(update), kind, run),
            )
    with pytest.raises((PermissionError, ValueError)):
        claim(p)
    assert snapshot(p) == before
    with p.host.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()
