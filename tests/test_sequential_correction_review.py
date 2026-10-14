"""Correction review keeps authority while excluding unrelated feature selection."""

from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from products.triad.development import Development
from products.triad.sequential import Proposal, SequentialCycle
from products.triad.sequential_correction_review import correction_context

pytestmark = pytest.mark.triad


def setup_flow(tmp_path, decision="APPROVE", changed=False):
    approved = "tests/products/triad/test_runner.py"
    unrelated = "app/products/triad/other_feature.py"
    for name, content in ((approved, "current approved source"), (unrelated, "unrelated sentinel")):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    proposal = Proposal(
        title="Approved connection",
        problem="Missing connection",
        change="Connect it",
        files=(approved,),
        acceptance=(
            {
                "check_id": "runner",
                "method": "PYTHON_UNIT_TEST",
                "description": "Propagate actual failure",
            },
        ),
        evidence=("Exact source",),
    )
    candidate = {
        "agent": "CLAUDE",
        "commit": "unmerged",
        "approval_id": "original-approval",
        "implementation_id": "implementation",
        "snapshot_sha256": "snapshot",
        "reservation_id": "slot",
        "reservation_work_item_id": "original-work",
        "independent_qa": {"qa_id": "failed-qa", "findings": ["Engine failure was not injected"]},
        "files": [{"path": approved, "content": "retained candidate source"}],
        "author_correction_plan": {"summary": "obsolete-plan sentinel"},
        "renewal_feedback": {"summary": "older-feedback sentinel"},
    }
    plan = {
        "id": "current-plan",
        "plan_sha256": "plan-hash",
        "qa_id": "failed-qa",
        "candidate_commit": "unmerged",
        "plan": {
            "summary": "Current correction",
            "steps": [
                {
                    "check_id": "runner",
                    "files": [approved],
                    "approach": "Inject failure into engine after successful preflight",
                }
            ],
        },
    }
    feedback = [
        {"decision": "REQUEST_CHANGES", "summary": "historical sentinel"},
        {
            "decision": "REQUEST_CHANGES",
            "summary": "latest feedback",
            "findings": ["Inject engine failure"],
        },
    ]
    captured, recorded, approvals = [], [], []
    flow = object.__new__(SequentialCycle)
    flow.root, flow.policy = tmp_path, {"id": "policy"}
    flow.retained_application_candidate = candidate

    def call(mission, agent, objective, context, *args, **kwargs):
        work, requirements = Development.call(
            NS(), mission, agent, "REVIEW", objective, context, _preview=True
        )
        assert work.allowed_paths == () and work.execution_permissions == ("read",)
        assert requirements.preferred_agent == "GROK" and requirements.role == "REVIEW"
        captured.append((objective, context))
        return (
            NS(work_item_id="review-work"),
            NS(review_decision=decision, summary="Review result", findings=("Finding",)),
            None,
            {"run_id": "review-run"},
        )

    def append(kind, payload, **kwargs):
        approvals.append((kind, payload))
        return "approval"

    flow.call = call
    flow.s = NS(
        record=lambda *a, **kw: recorded.append((a, kw)),
        canonical=NS(append=append),
        git=NS(
            clean_baseline=lambda: "moved" if changed else "main",
            git=lambda *args: "current integration source",
        ),
    )
    return flow, proposal, candidate, plan, feedback, unrelated, captured, recorded, approvals


@pytest.mark.parametrize("decision", ["APPROVE", "REQUEST_CHANGES", "REJECT", "BLOCKED"])
def test_real_review_dispatch_keeps_exact_scope_and_verdict_binding(tmp_path, decision):
    flow, proposal, candidate, plan, feedback, unrelated, calls, records, approvals = setup_flow(
        tmp_path, decision
    )
    original = deepcopy(candidate)
    _, approval, assessment = flow.review_proposal(
        "cycle",
        "CLAUDE",
        proposal,
        feedback,
        4,
        "main",
        [unrelated],
        {"unrelated_feature_selection": "excluded"},
        "author-work",
        "author-run",
        correction_plan=plan,
    )
    objective, context = calls[0]
    assert context["current_correction_plan"] == plan["plan"]
    assert context["correction_plan"] == plan
    assert context["latest_requested_changes"] == feedback[-1]
    assert context["proposal"] == proposal.model_dump(mode="json")
    assert context["base_commit"] == "main"
    retained = context["retained_unmerged_candidate"]
    assert (
        retained["files"] == candidate["files"]
        and retained["independent_qa"] == candidate["independent_qa"]
    )
    assert retained["reservation_id"] == "slot" and retained["approval_id"] == "original-approval"
    assert candidate == original  # Packet curation cannot alter canonical authority/evidence.
    assert "author_correction_plan" not in retained and "renewal_feedback" not in retained
    assert set(context["current_baseline_approved_files"]) == set(proposal.files)
    assert "unrelated sentinel" not in str(context) and "obsolete-plan sentinel" not in str(context)
    assert "historical sentinel" not in str(context)
    assert "inventory" not in context and "product_planning" not in context
    assert "quote the exact" in objective and "functionally equivalent" in objective
    assert assessment["decision"] == decision and records[0][1]["decision"] == decision
    assert (approval is not None) == (decision == "APPROVE")
    if approvals:
        bound = approvals[0][1]
        assert bound["proposal"] == context["proposal"]
        assert bound["review_work_item_id"] == "review-work" and bound["run_id"] == "review-run"
        assert (
            bound["author_work_item_id"] == "author-work" and bound["author_run_id"] == "author-run"
        )
        assert (
            bound["correction_plan_id"] == "current-plan"
            and bound["correction_plan_sha256"] == "plan-hash"
        )
        assert (
            bound["correction_candidate_commit"] == "unmerged"
            and bound["correction_qa_id"] == "failed-qa"
        )


def test_baseline_moving_cannot_publish_approval(tmp_path):
    flow, proposal, _, plan, feedback, unrelated, _, _, approvals = setup_flow(
        tmp_path, changed=True
    )
    with pytest.raises(PermissionError, match="Source changed"):
        flow.review_proposal(
            "cycle",
            "CLAUDE",
            proposal,
            feedback,
            4,
            "main",
            [unrelated],
            {},
            "author",
            "run",
            correction_plan=plan,
        )
    assert not approvals


def test_feature_review_still_receives_autonomous_planning_and_inventory(tmp_path):
    flow, proposal, _, _, feedback, unrelated, calls, _, _ = setup_flow(tmp_path)
    flow.review_proposal(
        "cycle",
        "CLAUDE",
        proposal,
        feedback,
        4,
        "main",
        [unrelated],
        {"autonomous": True},
        "author",
        "run",
    )
    objective, context = calls[0]
    assert context["product_planning"] == {"autonomous": True}
    assert (
        unrelated in context["inventory"] and context["sources"][unrelated] == "unrelated sentinel"
    )
    assert len(context["review_feedback"]) == 2
    assert "highest-value" in objective


def test_missing_candidate_cannot_dispatch_a_correction():
    with pytest.raises(PermissionError, match="retained unmerged candidate"):
        correction_context("CLAUDE", "GROK", None, None, {}, "main", [], {})
