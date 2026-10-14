"""Normal review correction is not approval and not a fixed attempt budget."""

from types import SimpleNamespace as NS

import pytest
from products.triad.sequential import Proposal, SequentialCycle
from products.triad.sequential_proposal_revisions import proposal_digest

pytestmark = pytest.mark.triad


def candidate(change="Correct current contract"):
    return Proposal(
        outcome="NO_CHANGE",
        title="Reviewed fixture",
        problem="Needs evidence",
        change=change,
        files=(),
        acceptance=(),
        evidence=("Fixture evidence",),
    )


def test_substantive_revisions_continue_until_independent_approval():
    flow = object.__new__(SequentialCycle)
    flow.s = NS(rows=lambda *a: [])
    numbers = []

    def attempt(mission, agent, feedback, number):
        numbers.append(number)
        if number > 1:
            assert feedback[-1]["findings"] == [f"Finding {number - 1}"]
        p = candidate(f"Corrected behavior {number}")
        return (
            p,
            "fresh-approval" if number == 5 else None,
            {
                "decision": "APPROVE" if number == 5 else "REQUEST_CHANGES",
                "summary": "Check contract",
                "findings": [f"Finding {number}"],
            },
        )

    flow.proposal_attempt = attempt
    assert flow.propose("cycle", "CLAUDE")[1] == "fresh-approval"
    assert numbers == [1, 2, 3, 4, 5]


def test_resume_numbers_and_feedback_are_retained():
    flow = object.__new__(SequentialCycle)
    review = {
        "proposer": "CLAUDE",
        "decision": "REQUEST_CHANGES",
        "findings": ["Fix quality"],
        "summary": "Fix quality",
        "proposal": candidate().model_dump(mode="json"),
    }

    def rows(kind, mission):
        return (
            [review] if kind == "ProductProposalReview" else [{"proposer": "CLAUDE", "attempt": 3}]
        )

    flow.s = NS(rows=rows)

    def attempt(mission, agent, feedback, number):
        assert number == 4 and feedback[-1]["findings"] == ["Fix quality"]
        return candidate("Quality preflight added"), "independent", {}

    flow.proposal_attempt = attempt
    assert flow.propose("cycle", "CLAUDE")[1] == "independent"


def test_title_evidence_and_whitespace_churn_are_not_progress():
    original = candidate().model_dump(mode="json")
    churn = {
        **original,
        "title": "Renamed",
        "evidence": ["Another claim"],
        "change": "  Correct current   contract ",
    }
    assert proposal_digest(original) == proposal_digest(churn)
    flow = object.__new__(SequentialCycle)
    flow.s = NS(rows=lambda *a: [])
    calls = []

    def attempt(m, a, feedback, n):
        calls.append(n)
        p = Proposal.model_validate(original if n == 1 else churn)
        return p, None, {"decision": "REQUEST_CHANGES", "summary": "Still wrong"}

    flow.proposal_attempt = attempt
    with pytest.raises(PermissionError, match="no progress"):
        flow.propose("cycle", "GROK")
    assert calls == [1, 2]


def test_case_sensitive_contract_correction_is_distinct():
    original = candidate("Call ResearchInput").model_dump(mode="json")
    corrected = {**original, "change": "Call researchInput"}
    assert proposal_digest(original) != proposal_digest(corrected)
    assert proposal_digest(
        {**original, "value_plan": {"why_highest_value": "New prose"}}
    ) == proposal_digest(original)
