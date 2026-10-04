# ruff: noqa: F401, F811
"""Closed read-only review can be renewed after protected baseline maintenance."""

from pathlib import Path

import pytest
from products.triad.sequential_correction_renewal import REVIEW_BASELINE_MOVED
from products.triad.sequential_qa_recovery import resume_citation_failure
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, prepare, proof, seed_work, snapshot
from test_correction_renewal_integration import closed_read, healthy
from trading_core.work import State, WorkItem

pytestmark = pytest.mark.integration


@pytest.fixture
def moved_review(proof, request):
    p = proof
    p.retained = prepare(p)
    p.daily.transition(p.mission, "CORRECTING", [p.qa])
    variant = getattr(request.node, "callspec", None)
    variant = variant.params.get("review_case", "REQUEST_CHANGES") if variant else "REQUEST_CHANGES"
    verdict = variant if variant in {"APPROVE", "REQUEST_CHANGES", "REJECT"} else "REQUEST_CHANGES"
    p.read = closed_read(
        p,
        "CLAUDE",
        "completed-moved-review",
        {
            "proposal": p.proposal.model_dump(mode="json"),
            "base_commit": p.build["git"]["base_commit"],
            "task_assignment": {"phase": "PROPOSAL_REVIEWER"},
            "retained_unmerged_candidate": p.retained,
        },
        {
            "summary": "Exact correction plan reviewed",
            "review_decision": verdict,
            "findings": ["Recorded reviewer findings"],
            "analysis_artifacts": [],
        },
    )
    p.review_id = p.host.append(
        "ProductProposalReview",
        {
            "mission_id": p.mission,
            "proposer": "CODEX",
            "reviewer": "CLAUDE",
            "attempt": 3,
            "proposal": p.proposal.model_dump(mode="json"),
            "run_id": "completed-moved-review",
            "decision": verdict,
            "summary": "Exact correction plan reviewed",
            "findings": ["Recorded reviewer findings"],
        },
        owner="triad",
    )
    if variant != "unchanged":
        (Path(p.flow.root) / "app/products/triad/sequential_review_fixture.py").write_text(
            "# Core-reviewed orchestration maintenance\n"
        )
        p.flow.s.git.git("add", ".")
        p.flow.s.git.git("commit", "-m", "protected review maintenance")
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": REVIEW_BASELINE_MOVED},),
    )
    return p


@pytest.mark.parametrize("review_case", ["APPROVE", "REQUEST_CHANGES"])
def test_closed_review_can_renew_without_using_stale_approval_or_refunding_slot(
    moved_review, monkeypatch, review_case
):
    p = moved_review
    healthy(monkeypatch)
    before = snapshot(p)
    cycle, count, day, _ = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and count == 0 and day == p.day
    assert snapshot(p) == before
    assert p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
    assert p.flow._prepared_correction["renewal_feedback"]["decision"] == review_case
    assert not p.host.list("ProductTurnApproval", matching={"run_id": "completed-moved-review"})
    with p.host.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)


@pytest.mark.parametrize(
    "review_case", ["REJECT", "unchanged", "unknown_usage", "later_read", "duplicate_result"]
)
def test_moved_review_recovery_requires_known_closed_last_read_and_real_source_movement(
    moved_review, monkeypatch, review_case
):
    p = moved_review
    healthy(monkeypatch)
    before = snapshot(p)
    if review_case == "unknown_usage":
        with p.host.store.connect() as c:
            c.execute(
                "UPDATE core.day3_records SET payload=payload || %s WHERE kind='Usage' AND payload->>'run_id'='completed-moved-review'",
                (Jsonb({"usage_known": False}),),
            )
    elif review_case == "later_read":
        seed_work(
            p.host.store,
            WorkItem(
                owner="triad",
                mission_id=p.mission,
                title="Later unknown read",
                description="Cannot replay it",
                work_type="review",
                status=State.BLOCKED,
                execution_permissions=("read",),
                allowed_tools=("read_file",),
            ),
        )
    elif review_case == "duplicate_result":
        p.host.ledger.put(
            "AgentRunResult", {"run_id": "completed-moved-review"}, work_id=p.read.work_item_id
        )
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert snapshot(p) == before
    assert p.daily.current(p.mission)["status"] == "BLOCKED"
