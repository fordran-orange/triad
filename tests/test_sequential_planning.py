"""Planning receives current authority, cross-cycle evidence and independent value review."""

import json
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential import CurrentProposal, Proposal, SequentialCycle
from products.triad.sequential_application import PLAN_PATH
from products.triad.sequential_planning import (
    CORE_REFERENCES,
    HISTORICAL,
    planning_context,
    token_guidance,
    token_targets,
)
from pydantic import ValidationError


def plan():
    return {
        "initiative": "Research comparison workspace",
        "user_outcome": "Compare retained experiments rather than manually reading artifacts",
        "why_highest_value": "Closes a missing workflow; current page polish does not",
        "alternatives": [
            {
                "change": "Navigation copy",
                "expected_value": "Clarity",
                "reason_not_selected": "Lower impact",
            },
            {
                "change": "Live order entry",
                "expected_value": "Execution",
                "reason_not_selected": "Not authorized",
            },
        ],
        "next_steps": ["Add comparisons using the established result contract"],
        "dependencies_or_blockers": ["Product-scoped retained-result access needs proof"],
        "mission_contribution": "Creates a research evaluation workflow beyond the shell",
        "major_gaps": ["No experiment comparison workflow", "No chart analysis workspace"],
        "application_contribution": {
            "workflow": "research-comparison",
            "entry_point": "/triad/product",
            "input_producer": "Core scoped research",
            "output_consumer": "Triad comparison view",
            "contracts_and_versions": ["ResearchResult-v1"],
            "integration_checks": ["comparison"],
            "status": "FOUNDATION",
        },
    }


def proposal(**updates):
    return {
        "title": "Compare research results",
        "problem": "No comparison workflow",
        "change": "Build a comparator",
        "files": ["app/products/triad/compare.py", PLAN_PATH],
        "evidence": ["Inspected sources"],
        "acceptance": [
            {"check_id": "comparison", "method": "SOURCE_REVIEW", "description": "Review contract"}
        ],
        **updates,
    }


def service(tmp_path):
    rows = {
        "ProductProposal": [
            {
                "id": "previous",
                "owner": "triad",
                "mission_id": "yesterday",
                "proposal": proposal(value_plan=plan()),
            },
            {"id": "private", "owner": "aegis", "proposal": "PRIVATE"},
        ],
        "ProductTurn": [
            {
                "id": "done",
                "owner": "triad",
                "mission_id": "yesterday",
                "status": "COMPLETED",
                "verified_revision": "abc",
            }
        ],
    }

    def git(*args):
        if args == ("rev-parse", "HEAD"):
            return "base"
        assert args[0] == "show"
        path = args[1].split(":", 1)[1]
        if path.endswith("resources/product.json"):
            return json.dumps(
                {
                    "mission": "Build the best trading application",
                    "product_scope": ["research", "risk"],
                }
            )
        if path == PLAN_PATH:
            from products.triad.sequential_application import current_plan

            return current_plan().model_dump_json()
        assert path in CORE_REFERENCES or path.endswith("server.py")
        return "# current published source"

    return NS(
        git=NS(root=tmp_path, git=git, clean_baseline=lambda: "base"),
        records=NS(list=lambda kind: rows.get(kind, [])),
    )


def test_old_proposals_keep_exact_serialization_and_new_proposals_require_value():
    old = proposal()
    assert "value_plan" not in Proposal(**old).model_dump()
    assert "value_plan" not in Proposal(**old).model_dump_json()
    with pytest.raises(ValidationError):
        CurrentProposal(**old)
    current = CurrentProposal(**proposal(value_plan=plan()))
    restored = Proposal.model_validate(current.model_dump())
    assert restored.value_plan.initiative == plan()["initiative"]
    with pytest.raises(ValidationError):
        CurrentProposal(**proposal(value_plan={**plan(), "alternatives": []}))


def test_history_is_product_private_and_does_not_reapply_old_grants(tmp_path):
    packet = planning_context(service(tmp_path), "today", "base")
    assert packet["mission"] == "Build the best trading application"
    assert packet["history"]["ProductProposal"][0]["mission_id"] == "yesterday"
    assert "PRIVATE" not in json.dumps(packet)
    assert packet["history"]["ProductTurn"][0]["verified_revision"] == "abc"
    assert "acceptance" not in packet["history"]["ProductProposal"][0]["proposal"]
    assert packet["history"]["ProductProposal"][0]["proposal"]["value_plan"] == plan()
    assert "superseded" in packet["current_authority"]["obsolete_limits"]
    assert packet["shared_core"]["source_revision"] == "base"
    from products.triad.sequential_application import ApplicationPlan

    assert packet["application_plan"]["schema"] == ApplicationPlan.model_json_schema()
    assert "unsupported keys are rejected" in packet["application_plan"]["format"]
    assert set(packet["shared_core"]["references_read_only"]) == set(CORE_REFERENCES)
    assert "installed read-only" in packet["shared_core"]["availability"]


@pytest.mark.parametrize("agent,receives_candidate", [("CODEX", True), ("CLAUDE", False)])
def test_workspace_receives_exact_plan_schema_and_only_its_own_retained_candidate(monkeypatch, agent, receives_candidate):
    from products.triad.sequential_application import ApplicationPlan
    from trading_core.product_workspace_grant import PROFILE

    from products.triad import sequential

    flow = SequentialCycle.__new__(SequentialCycle)
    flow.policy = {"workspace_profile": PROFILE}
    flow.guard = lambda _: None
    flow.inventory = lambda: [PLAN_PATH]
    material = {"agent": "CODEX", "files": [{"path": PLAN_PATH, "content": "retained"}]}
    flow.retained_application_candidate = material
    captured = {}
    def call(*args, **kwargs):
        captured.update(context=args[4])
        return "fixture"
    flow.s = NS(call=call, git=NS(git=lambda *a: "base"), daily=NS(current=lambda *a: {"parent_work_item_id": "parent"}))
    monkeypatch.setattr(sequential, "core_context", lambda *a: {})
    assert flow.implementation_call("mission", agent, "unused", {"proposal": {"files": [PLAN_PATH]}}, None, approval="approval") == "fixture"
    assert captured["context"]["application_plan_schema"] == ApplicationPlan.model_json_schema()
    assert captured["context"]["retained_unmerged_candidate"] == (material if receives_candidate else None)


def test_proposer_and_reviewer_see_same_value_context_and_all_current_sources(
    tmp_path, monkeypatch
):
    from trading_core.intake import Intake

    monkeypatch.setattr(Intake, "advisory", lambda *args: [])
    s = service(tmp_path)
    existing = [
        "app/products/triad/product_app.py",
        "tests/products/triad/test_large.py",
        *HISTORICAL,
    ]
    for path in existing:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# large current test\n" * 1000 if "test_large" in path else "historical or current",
            encoding="utf-8",
        )
    calls, records = [], []
    s.record = lambda *args, **kw: records.append((args, kw))
    s.rows = lambda *args: []
    s.transition = lambda *args, **kw: None
    s.canonical = NS(append=lambda *args, **kw: "approved")
    flow = object.__new__(SequentialCycle)
    flow.s, flow.root, flow.policy = s, tmp_path, {"id": "policy"}
    flow.inventory = lambda: existing

    def call(mission, agent, objective, context, schema=None, paths=()):
        calls.append((objective, context, paths))
        if schema:
            return (
                NS(work_item_id="author"),
                None,
                CurrentProposal(**proposal(value_plan=plan())),
                {"run_id": "author-run"},
            )
        return (
            NS(work_item_id="reviewer"),
            NS(review_decision="APPROVE", summary="Highest value supported", findings=[]),
            None,
            {"run_id": "review-run"},
        )

    flow.call = call
    chosen, approval, _ = flow.proposal_attempt("today", "CLAUDE", [], 1)
    assert approval == "approved" and type(chosen) is Proposal
    author, reviewer = calls[0][1], calls[1][1]
    assert author["product_planning"] == reviewer["product_planning"]
    assert not HISTORICAL.intersection(author["additional_product_sources_read_only"])
    assert not HISTORICAL.intersection(reviewer["sources"])
    assert len(reviewer["sources"]["tests/products/triad/test_large.py"]) > 12000
    assert any(args[0] == "ProductPlanningContext" for args, _ in records)
    assert "highest-value" in calls[0][0] and "value" in calls[1][0]


def test_codex_targets_lower_without_changing_other_agents_or_imposing_cutoffs():
    assert token_targets("CODEX") == (4096, 3072)
    for agent in ("CLAUDE", "GROK"):
        assert token_targets(agent) == (8192, 6144)
    assert "not cutoffs" in token_guidance("CODEX")


def test_planning_machinery_remains_protected():
    from trading_core.product_changes import product_path

    with pytest.raises(PermissionError):
        product_path("app/products/triad/sequential_planning.py")


@pytest.mark.parametrize("agent", ["CODEX", "CLAUDE", "GROK"])
def test_assignment_targets_match_prompt_without_changing_authority(agent):
    from products.triad.development import Development

    value = object.__new__(Development)
    work, requirements = value.call("cycle", agent, "REVIEW", "Plan", {}, _preview=True)
    reasoning, output = token_targets(agent)
    assert work.reasoning_budget == reasoning
    assert work.compute_budget.max_output_tokens == output
    assert work.execution_permissions == ("read",)
    assert requirements.preferred_agent == agent
