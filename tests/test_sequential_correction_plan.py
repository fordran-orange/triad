from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential_correction_plan import (
    CorrectionPlan,
    author_plan,
    renew_with_plan,
    validate_steps,
)

pytestmark = pytest.mark.triad


def plan(approach="Inject the engine failure after preflight", summary="Close actual QA"):
    return CorrectionPlan.model_validate(
        {
            "summary": summary,
            "steps": [{"check_id": "runner", "files": ["tests/runner.py"], "approach": approach}],
        }
    )


def contract():
    return NS(
        files=("tests/runner.py",), acceptance=(NS(check_id="runner"), NS(check_id="identity"))
    )


def assessment():
    return {
        "checks": [
            {"check_id": "runner", "status": "NOT_VERIFIED"},
            {"check_id": "identity", "status": "VERIFIED"},
        ]
    }


@pytest.mark.parametrize("tamper", ["path", "check", "missing", "duplicate", "empty"])
def test_plan_covers_original_failed_checks_without_expanding_scope(tamper):
    p = plan().model_dump(mode="json")
    if tamper == "path":
        p["steps"][0]["files"] = ["app/trading_core/control.py"]
    elif tamper == "check":
        p["steps"][0]["check_id"] = "new-feature"
    elif tamper == "missing":
        p["steps"][0]["check_id"] = "identity"
    elif tamper == "duplicate":
        p["steps"].append(deepcopy(p["steps"][0]))
    else:
        p["steps"][0]["approach"] = "   "
    with pytest.raises(PermissionError):
        validate_steps(CorrectionPlan.model_validate(p), contract(), assessment())


def test_plan_preserves_verified_criteria_and_covers_omitted_check():
    validate_steps(plan(), contract(), assessment())
    with pytest.raises(PermissionError, match="every unverified"):
        validate_steps(plan(), contract(), {"checks": []})


def test_host_detected_bad_evidence_remains_a_required_correction():
    with pytest.raises(PermissionError, match="every unverified"):
        validate_steps(
            plan(), contract(), assessment(), ["identity: exact candidate source review required"]
        )


def test_author_planning_uses_supplied_candidate_without_requesting_build_path_grants():
    from products.triad.development import Development

    proposal = NS(
        files=("tests/products/triad/test_runner.py",),
        acceptance=(NS(check_id="runner"),),
        model_dump=lambda **k: {"files": ["tests/products/triad/test_runner.py"]},
    )
    retained = {
        "approval_id": "old",
        "commit": "candidate",
        "independent_qa": {
            "qa_id": "qa",
            "assessment": {"checks": [{"check_id": "runner", "status": "NOT_VERIFIED"}]},
            "findings": [],
        },
        "author_correction_plan": {"summary": "unapproved historical approach"},
        "renewal_feedback": {"findings": ["Preserve the adequate engine injection"]},
    }
    original = deepcopy(retained)
    result = {"id": "saved-plan"}

    def read(mission, agent, objective, context, schema, paths=()):
        work, requirements = Development.call(
            NS(),
            mission,
            agent,
            "REVIEW",
            objective,
            context,
            paths=paths,
            schema=schema,
            _preview=True,
        )
        assert work.allowed_paths == () and work.execution_permissions == ("read",)
        assert requirements.role == "REVIEW" and requirements.preferred_agent == "CLAUDE"
        assert context["approved_file_manifest"] == list(proposal.files)
        assert context["retained_unmerged_candidate"] == {
            k: v for k, v in retained.items() if k not in {"author_correction_plan", "renewal_feedback"}
        }
        assert context["latest_renewal_feedback"] == retained["renewal_feedback"]
        assert context["correction_author_version"] == "current-obligations-v2"
        assert "unapproved historical approach" not in str(context)
        return (
            NS(work_item_id="author"),
            None,
            plan().model_copy(
                update={"steps": (plan().steps[0].model_copy(update={"files": proposal.files}),)}
            ),
            {"run_id": "author-run"},
        )

    flow = NS(
        call=read,
        s=NS(
            git=NS(clean_baseline=lambda: "main"),
            record=lambda *a, **kw: "saved-plan",
            canonical=NS(get=lambda i: result),
        ),
    )
    assert author_plan(flow, "cycle", "CLAUDE", proposal, retained, "main") == result
    assert retained == original


def fake_flow(monkeypatch, plans, decisions):
    calls = []
    retained = {}
    monkeypatch.setattr("products.triad.sequential_planning.planning_context", lambda *a: {})

    def author(*args):
        calls.append(("author", deepcopy(retained.get("renewal_feedback"))))
        p = plans.pop(0)
        return {
            "id": str(len(calls)),
            "author_work_item_id": "author",
            "author_run_id": "run",
            "plan": p.model_dump(mode="json"),
        }

    def review(*args, **kwargs):
        calls.append(("review", kwargs["correction_plan"]["plan"]))
        decision = decisions.pop(0)
        return (
            None,
            "approval" if decision == "APPROVE" else None,
            {
                "decision": decision,
                "summary": "Specific feedback",
                "findings": ["Use an engine stub"],
            },
        )

    monkeypatch.setattr("products.triad.sequential_correction_plan.author_plan", author)
    return (
        NS(s=NS(rows=lambda *a: []), inventory=list, review_proposal=review),
        retained,
        calls,
    )


def test_requested_plan_revision_receives_feedback_before_independent_approval(monkeypatch):
    flow, retained, calls = fake_flow(
        monkeypatch,
        [plan(), plan("Stub run_research and assert original exception")],
        ["REQUEST_CHANGES", "APPROVE"],
    )
    approval, selected = renew_with_plan(flow, "cycle", "CLAUDE", contract(), retained, "main")
    assert approval == "approval" and selected == retained["author_correction_plan"]
    assert [c[0] for c in calls] == ["author", "review", "author", "review"]
    assert calls[2][1]["findings"] == ["Use an engine stub"]


@pytest.mark.parametrize("change", ["headline", "whitespace"])
def test_headline_change_is_not_progress_or_permission_to_execute(monkeypatch, change):
    second = (
        plan(summary="A different headline")
        if change == "headline"
        else plan("Inject   the engine\n failure after preflight")
    )
    flow, retained, calls = fake_flow(monkeypatch, [plan(), second], ["REQUEST_CHANGES"])
    with pytest.raises(PermissionError, match="made no progress"):
        renew_with_plan(flow, "cycle", "CLAUDE", contract(), retained, "main")
    assert [c[0] for c in calls] == ["author", "review", "author"]


@pytest.mark.parametrize("decision", ["REJECT", "BLOCKED"])
def test_rejected_correction_plan_never_retries_or_builds(monkeypatch, decision):
    flow, retained, calls = fake_flow(monkeypatch, [plan()], [decision])
    with pytest.raises(PermissionError, match="did not pass independent review"):
        renew_with_plan(flow, "cycle", "CLAUDE", contract(), retained, "main")
    assert [c[0] for c in calls] == ["author", "review"]
