# ruff: noqa: F401, F811
"""Valid change labels retain exact exports; unknown execution is not replay authority."""

import pytest
from products.triad.sequential_candidate_recovery import NATIVE_IDENTITY_ERROR
from products.triad.sequential_qa_recovery import resume_citation_failure
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, prepare, proof, snapshot
from test_correction_renewal_integration import healthy
from trading_core.work import State

pytestmark = pytest.mark.integration


def label(p, status, **extra):
    with p.host.store.connect() as conn:
        conn.execute(
            "UPDATE core.day3_records SET payload=payload || %s "
            "WHERE owner='triad' AND kind='AgentRunResult' AND work_item_id=%s",
            (Jsonb({"status": status, **extra}), p.work.work_item_id),
        )


@pytest.mark.parametrize(
    "change_status",
    [
        "CODE_CHANGE",
        "BUG_FIX",
        "TEST_ADDITION",
        "DOCUMENTATION_CHANGE",
        "ARCHITECTURAL_IMPROVEMENT",
        "PERFORMANCE_IMPROVEMENT",
    ],
)
def test_valid_label_preserves_exact_unmerged_native_candidate_and_accounting(proof, change_status):
    p = proof
    label(p, change_status)
    before = snapshot(p)
    retained = prepare(p)
    assert retained["commit"] == p.build["git"]["change_commit"]
    assert retained["native_run_id"] == "build-run"
    assert retained["independent_qa"]["qa_id"] == p.qa
    assert retained["reservation_work_item_id"] == p.work.work_item_id
    assert snapshot(p) == before


@pytest.mark.parametrize("change_status", ["BUG_FIX", "TEST_ADDITION"])
def test_exact_closed_qa_label_block_can_resume_once_without_build_or_slot_refund(
    proof, monkeypatch, change_status
):
    p = proof
    label(p, change_status)
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": NATIVE_IDENTITY_ERROR},),
    )
    healthy(monkeypatch)
    before = snapshot(p)
    cycle, count, day, retained = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and count == 0 and day == p.day
    assert retained[-1].decision == "CHANGES_REQUIRED"
    assert p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
    assert p.flow._prepared_correction["commit"] == p.build["git"]["change_commit"]
    assert snapshot(p) == before
    with p.host.store.connect() as conn:
        assert not conn.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)


@pytest.mark.parametrize(
    "change_case",
    ["CODE_CHANGE", "RESEARCH_FINDING", "NO_CHANGE_JUSTIFIED", "BLOCKED", "unknown", "crossed_run"],
)
def test_label_failure_is_not_general_replay_permission(proof, monkeypatch, change_case):
    p = proof
    label(
        p,
        "BUG_FIX" if change_case == "crossed_run" else change_case,
        **({"run_id": "different-run"} if change_case == "crossed_run" else {}),
    )
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": NATIVE_IDENTITY_ERROR},),
    )
    healthy(monkeypatch)
    before = snapshot(p)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED"
    assert snapshot(p) == before
    with p.host.store.connect() as conn:
        assert not conn.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("candidate-correction-" + p.qa,)
        ).fetchone()
