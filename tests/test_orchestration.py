import os

import pytest
from pydantic import ValidationError
from triad.context import packet_for
from triad.control import ControlPlane, Registry
from triad.gateway import ToolGateway
from triad.providers import AUDIT_FILES, DocumentationReviewer, DocumentationWorker
from triad.work import ComputeBudget, Handoff, Provenance, Review, State, WorkItem, transition


def work(**changes):
    return WorkItem(title="Test assignment", description="Bounded documentation work", **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"priority": 0},
        {"authority_tier": 6},
        {"reasoning_budget": -1},
        {"unknown_permission": True},
        {"work_item_id": "../escape"},
        {"assigned_agent": "CODEX", "reviewer": "CODEX"},
        {"acceptance_criteria": ()},
    ],
)
def test_work_validation(changes):
    with pytest.raises(ValidationError):
        work(**changes)


def test_authority_is_frozen():
    item = work()
    with pytest.raises(ValidationError):
        item.authority_tier = 5


@pytest.mark.parametrize(
    "source,target",
    [
        (State.CREATED, State.COMPLETED),
        (State.COMPLETED, State.IN_PROGRESS),
        (State.IN_PROGRESS, State.APPROVED_BY_REVIEWER),
    ],
)
def test_invalid_state_transitions(source, target):
    with pytest.raises(ValueError):
        transition(work(status=source), target)


def test_review_cannot_be_bypassed():
    with pytest.raises(PermissionError):
        transition(work(status=State.IN_PROGRESS), State.COMPLETED)
    with pytest.raises(PermissionError):
        transition(work(status=State.AWAITING_REVIEW), State.APPROVED_BY_REVIEWER)
    with pytest.raises(PermissionError):
        transition(work(), State.VALIDATING, actor="CODEX")


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"affects_money": True}, "DENY"),
        ({"affects_trading": True}, "DENY"),
        ({"authority_tier": 4}, "DENY"),
        ({"execution_permissions": ("live_trade",)}, "DENY"),
        ({"alters_permissions": True}, "REQUIRE_HUMAN_APPROVAL"),
        ({"authority_tier": 5}, "REQUIRE_HUMAN_APPROVAL"),
        ({"review_required": False}, "DENY"),
        ({"allowed_tools": ("shell",)}, "DENY"),
        ({"allowed_paths": ("../outside",)}, "DENY"),
        ({"allowed_paths": ("control-plane",)}, "DENY"),
        ({"assigned_agent": "LOCAL_QWEN"}, "DENY"),
        ({"reasoning_budget": 4096}, "DENY"),
    ],
)
def test_policy_denials(changes, expected):
    assert ControlPlane().evaluate(work(**changes)).decision == expected


def test_elevation_never_self_approved():
    with pytest.raises(PermissionError):
        ControlPlane().approve_elevation(actor="LOCAL_QWEN")


def test_local_route_is_capability_not_price():
    helper = work(
        work_type="summarize_journal",
        authority_tier=0,
        allowed_tools=("read_file",),
        execution_permissions=("read",),
    )
    decision = ControlPlane().evaluate(helper)
    assert decision.routed_agent == "LOCAL_QWEN"
    assert decision.decision == "REQUIRE_REVIEW"
    assert "local" in decision.routing_reason
    assert ControlPlane().evaluate(work()).routed_agent == "CODEX"


def test_rotation_and_helper_boundary():
    registry = Registry()
    assert [registry.successor(a) for a in ("CODEX", "CLAUDE", "GROK")] == [
        "CLAUDE",
        "GROK",
        "CODEX",
    ]
    assert not registry.agents["LOCAL_QWEN"].review_eligible


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "C:/Windows/file",
        "docs/../../.env",
        "docs/.env",
        "docs/file:stream",
        ".git/config",
        "control-plane/policy.json",
        "app/triad/api.py",
        "docs/file.",
        "docs//file",
        "CON",
    ],
)
def test_path_boundary(tmp_path, path):
    with pytest.raises(PermissionError):
        ToolGateway(work(), tmp_path).write(path, "not allowed")


def test_tier_zero_and_budget(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/note.md").write_text("example")
    observer = work(
        authority_tier=0,
        allowed_tools=("read_file",),
        execution_permissions=("read",),
        compute_budget=ComputeBudget(max_tool_calls=1),
    )
    gateway = ToolGateway(observer, tmp_path)
    assert gateway.read("docs/note.md") == "example"
    with pytest.raises(PermissionError):
        gateway.read("docs/note.md")
    with pytest.raises(PermissionError):
        ToolGateway(observer, tmp_path).write("research/generated/test.md", "deny")


def test_symlink_and_hardlink_denied(tmp_path):
    (tmp_path / "docs").mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    link = tmp_path / "docs/hard.md"
    os.link(target, link)
    with pytest.raises(PermissionError):
        ToolGateway(work(), tmp_path).read("docs/hard.md")


def test_context_provenance_relevance_and_size():
    item = work()
    other_journal = {"mission_id": "unrelated", "results": "DO NOT INCLUDE"}
    packet = packet_for(item, [other_journal])
    assert not packet.recent_journal_entries
    assert packet.charter[0].source and packet.charter[0].timestamp
    with pytest.raises(ValueError):
        packet_for(work(compute_budget=ComputeBudget(max_input_chars=100)))


def test_fact_requires_evidence():
    with pytest.raises(ValidationError):
        Provenance(kind="FACT", text="Unsupported", source="model", agent="LOCAL_QWEN")
    hypothesis = Provenance(kind="HYPOTHESIS", text="Unverified", source="model", agent="CODEX")
    assert hypothesis.kind == "HYPOTHESIS"


def test_independent_review_recomputes_and_detects_tampering(tmp_path):
    for name in AUDIT_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Heading\n\nActual evidence.\n")
    item = work(status=State.IN_PROGRESS, assigned_agent="CODEX", reviewer="CLAUDE")
    gateway = ToolGateway(item, tmp_path)
    result = DocumentationWorker().perform(item, packet_for(item), gateway)
    for artifact in result.artifacts:
        gateway.write(artifact.path, artifact.content)
    handoff = Handoff(
        from_agent="CODEX",
        to_agent="CLAUDE",
        work_item_id=item.work_item_id,
        completed_work="Worker claims success",
        files_changed=tuple(gateway.changed),
        tests_performed=result.tests,
        evidence=result.evidence,
        recommended_checks=item.acceptance_criteria,
        git_commit="fixture",
        review_request="Verify independently",
    )
    reviewer = DocumentationReviewer()
    assert reviewer.review(item, handoff, ToolGateway(item, tmp_path)).decision == "APPROVE"
    (tmp_path / AUDIT_FILES[0]).write_text("# Changed after the worker read it\n")
    verdict = reviewer.review(item, handoff, ToolGateway(item, tmp_path))
    assert verdict.decision == "REQUEST_CHANGES"
    assert verdict.evidence_checked


def test_matching_review_required():
    item = work(status=State.AWAITING_REVIEW, assigned_agent="CODEX", reviewer="CLAUDE")
    review = Review(
        reviewer="GROK",
        work_item_id=item.work_item_id,
        decision="APPROVE",
        findings=(),
        severity="NONE",
        evidence_checked=(),
        tests_repeated=(),
    )
    with pytest.raises(PermissionError):
        transition(item, State.APPROVED_BY_REVIEWER, approved_review=review)
