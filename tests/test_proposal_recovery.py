"""A rejected candidate may be replaced, never applied without fresh approval."""

from types import SimpleNamespace

import pytest
from products.triad.sequential import Proposal, SequentialCycle

pytestmark = pytest.mark.triad


def proposal(title):
    return Proposal(
        outcome="NO_CHANGE",
        title=title,
        problem="Inspected",
        change="No edit needed",
        files=(),
        acceptance=(),
        evidence=("Exact baseline inspected",),
    )


def cycle():
    flow = object.__new__(SequentialCycle)
    # propose() first consults the mission's prior reviews and proposals; none exist here.
    flow.s = SimpleNamespace(rows=lambda kind, mission: [])
    return flow


def test_rejected_candidate_gets_fresh_review_with_feedback():
    flow = cycle()
    seen = []

    def attempt(mission, agent, feedback, number):
        seen.append((mission, agent, list(feedback), number))
        if number == 1:
            return proposal("Duplicate"), None, {"decision": "REJECT", "summary": "Already exists"}
        return proposal("Inspected no change"), "fresh-approval", {"decision": "APPROVE"}

    flow.proposal_attempt = attempt
    candidate, approval = flow.propose("cycle", "CLAUDE")
    assert candidate.title == "Inspected no change" and approval == "fresh-approval"
    assert len(seen) == 2 and seen[1][2][0]["decision"] == "REJECT"
    assert seen[1][2][0]["proposal"]["title"] == "Duplicate"
    assert all(row[0:2] == ("cycle", "CLAUDE") for row in seen)


@pytest.mark.parametrize("decision", ["REJECT", "REQUEST_CHANGES", "BLOCKED"])
def test_unapproved_candidates_never_return_an_approval(decision):
    flow = cycle()
    seen = []

    def attempt(*args):
        seen.append(args[-1])
        return proposal("Unapproved"), None, {"decision": decision, "summary": "Not approved"}

    flow.proposal_attempt = attempt
    # An invalid decision stops at once; a valid rejection allows exactly one resubmission,
    # and an identical resubmission is refused as making no progress (rule added 2026-10-03).
    expected = "Invalid proposal review" if decision == "BLOCKED" else "made no progress"
    with pytest.raises(PermissionError, match=expected):
        flow.propose("cycle", "GROK")
    assert seen == ([1] if decision == "BLOCKED" else [1, 2])


def test_authority_failure_is_not_retried_as_candidate_feedback():
    flow = cycle()
    seen = []

    def attempt(*args):
        seen.append(args[-1])
        raise PermissionError("Autonomy paused")

    flow.proposal_attempt = attempt
    with pytest.raises(PermissionError, match="Autonomy paused"):
        flow.propose("cycle", "CODEX")
    assert seen == [1]
