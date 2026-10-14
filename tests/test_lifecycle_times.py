# ruff: noqa: F811
"""Lifecycle timestamps record real transitions without rewriting source evidence."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_day3_integration import active, engine  # noqa: F401
from trading_core.work import Handoff, State, WorkItem, transition

pytestmark = pytest.mark.core


def test_utc_required_and_legacy_missing_times_remain_unknown():
    stamp = datetime(2026, 9, 19, 12, tzinfo=timezone(timedelta(hours=-5)))
    work = WorkItem(title="Time", description="Evidence", created_at=stamp)
    assert work.created_at == datetime(2026, 9, 19, 17, tzinfo=UTC)
    assert work.created_at.tzinfo == UTC
    assert work.updated_at is None and work.closed_at is None
    with pytest.raises(ValueError, match="timezone"):
        WorkItem(title="Time", description="Evidence", created_at=stamp.replace(tzinfo=None))
    legacy = work.model_dump(exclude={"updated_at", "closed_at"})
    assert WorkItem.model_validate(legacy).updated_at is None


def test_transition_times_and_retries():
    work = WorkItem(
        title="Retry", description="Verify", status=State.IN_PROGRESS, review_required=False
    )
    failed = transition(work, State.FAILED)
    assert failed.completed_at == failed.updated_at
    assert failed.closed_at is None
    current = failed
    for state in (State.VALIDATING, State.APPROVED, State.ASSIGNED, State.IN_PROGRESS):
        current = transition(current, state)
    assert current.started_at == current.updated_at
    assert current.completed_at is None
    completed = transition(current, State.COMPLETED)
    assert completed.closed_at == completed.completed_at == completed.updated_at
    assert completed.started_at <= completed.closed_at


@pytest.mark.integration
def test_handoff_events_overlay_preserves_immutable_original(engine):
    work, _ = active(engine)
    store = engine.host.store
    assert store.get(work.work_item_id).updated_at is not None
    handoff = Handoff(
        from_agent=work.assigned_agent,
        to_agent=work.reviewer,
        work_item_id=work.work_item_id,
        completed_work="Ready for review",
        files_changed=(),
        tests_performed=(),
        evidence=(),
        recommended_checks=("Inspect",),
        git_commit="fixture",
        review_request="Independent review",
    )
    store.add_record(handoff)
    with store.connect() as conn:
        original = conn.execute(
            "SELECT * FROM core.orchestration_records WHERE id=%s", (handoff.handoff_id,)
        ).fetchone()
    assert original["payload"]["created_at"] and original["payload"]["sent_at"]
    assert original["payload"]["received_at"] is None
    with pytest.raises(PermissionError):
        store.receive_handoff(work.work_item_id, work.assigned_agent)
    store.receive_handoff(work.work_item_id, work.reviewer)
    store.receive_handoff(work.work_item_id, work.reviewer)
    store.handoff_lifecycle(work.work_item_id, "completed_at", work.reviewer)
    projected = store.records("Handoff", work.work_item_id)[0]
    times = [
        datetime.fromisoformat(projected[key])
        for key in ("created_at", "sent_at", "received_at", "acknowledged_at", "completed_at")
    ]
    assert times == sorted(times)
    assert len(store.records("HandoffLifecycle", work.work_item_id)) == 3
    with store.connect() as conn:
        assert (
            conn.execute(
                "SELECT * FROM core.orchestration_records WHERE id=%s", (handoff.handoff_id,)
            ).fetchone()
            == original
        )
