"""Requested corrections stay native, exact and independent before merge."""

from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from products.triad.daily import Daily, DailySchedule
from products.triad.sequential_corrections import correct_until_pass

pytestmark = pytest.mark.triad


def test_correction_uses_fresh_build_and_qa_before_return(monkeypatch):
    events = []
    build = {
        "approval": "approved",
        "git": {"base_commit": "main"},
        "checks": {"hashes": {"p": "first"}},
    }
    new = {**build, "implementation_id": "fresh", "checks": {"hashes": {"p": "corrected"}}}
    retained = {
        "agent": "CLAUDE",
        "independent_qa": {"qa_id": "rejected", "findings": ["Assert stale response"]},
    }
    monkeypatch.setattr(
        "products.triad.sequential_corrections.prepare_correction", lambda *a: retained
    )
    flow = NS(
        s=NS(
            transition=lambda m, state, evidence: events.append(state),
            git=NS(clean_baseline=lambda: "main"),
        )
    )

    def build_again(m, agent, proposal, approval):
        assert agent == "CLAUDE" and approval == "approved"
        assert flow.retained_application_candidate == retained
        events.append("native correction")
        return "new checkout", new

    flow.build = build_again
    flow.qa = lambda *a: (
        events.append("fresh independent QA") or NS(decision="PASS", qa_run_id="new-qa")
    )
    result = correct_until_pass(
        flow,
        "cycle",
        "CLAUDE",
        "exact proposal",
        "old checkout",
        build,
        NS(decision="CHANGES_REQUIRED", qa_run_id="rejected"),
    )
    assert result[1] == new and result[2].qa_run_id == "new-qa"
    assert events == ["CORRECTING", "native correction", "AWAITING_QA", "fresh independent QA"]


@pytest.mark.parametrize("decision", ["REJECT", "BLOCKED"])
def test_rejection_is_never_correction_authority(decision):
    with pytest.raises(PermissionError, match="rejected or blocked"):
        correct_until_pass(None, "cycle", "CLAUDE", None, None, {}, NS(decision=decision))


def test_identical_native_candidate_stops_without_another_review(monkeypatch):
    build = {
        "approval": "approved",
        "implementation_id": "old",
        "git": {"base_commit": "main"},
        "checks": {"hashes": {"p": "same"}},
    }
    monkeypatch.setattr("products.triad.sequential_corrections.prepare_correction", lambda *a: {})
    flow = NS(
        s=NS(transition=lambda *a: None, git=NS(clean_baseline=lambda: "main")),
        build=lambda *a: (None, build),
    )
    with pytest.raises(PermissionError, match="made no progress"):
        correct_until_pass(
            flow,
            "cycle",
            "CLAUDE",
            None,
            None,
            build,
            NS(decision="CHANGES_REQUIRED", qa_run_id="qa"),
        )


@pytest.mark.parametrize("change", [None, "time", "days", "timezone", "disabled", "epoch"])
def test_midnight_rebinding_preserves_only_identical_authorized_cadence(monkeypatch, change):
    stamp = datetime(2026, 10, 4, 5, 1, tzinfo=UTC)  # 00:01 Chicago.
    monkeypatch.setattr("products.triad.daily.now", lambda: stamp)
    config = DailySchedule(enabled=True)
    old = {**config.model_dump(mode="json"), "effective_after": "2026-10-03", "control_epoch": 4}
    if change == "time":
        old["time"] = "10:00"
    if change == "days":
        old["days"] = [0]
    if change == "timezone":
        old["timezone"] = "UTC"
    if change == "disabled":
        old["enabled"] = False
    if change == "epoch":
        old["control_epoch"] = 3
    captured = []
    service = object.__new__(Daily)
    service.host = NS(
        ledger=NS(guard=lambda: {"epoch": 4}),
        list=lambda k: [],
        append=lambda k, row, **kwargs: captured.append(row) or row,
    )
    service.product = NS(list=lambda k: [], ledger=service.host.ledger)
    service.history = NS(
        list=lambda: [
            {
                "cycle_id": "accepted",
                "cycle_type": "DAILY_PRODUCT",
                "execution_mode": "REAL",
                "status": "COMPLETED",
                "scheduled": False,
            }
        ]
    )
    service.require_complete = lambda c: captured.append({"validated": c})
    service.schedule = lambda: old
    result = service._configure(config)
    assert captured[0] == {"validated": "accepted"}
    assert result["effective_after"] == ("2026-10-03" if change is None else "2026-10-05")
