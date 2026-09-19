"""Independent timestamp authority and historical-evidence QA (99dd242)."""
# ruff: noqa: F811

from datetime import UTC, datetime, timedelta, timezone

import pytest
from test_day3_integration import active, engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import Handoff, HandoffLifecycle, Review, WorkItem


def handoff(store, work):
    value = Handoff(
        from_agent=work.assigned_agent,
        to_agent=work.reviewer,
        work_item_id=work.work_item_id,
        completed_work="Ready",
        files_changed=(),
        tests_performed=(),
        evidence=(),
        recommended_checks=("Independent review",),
        git_commit="fixture",
        review_request="Review",
    )
    store.add_record(value)
    return value


@pytest.mark.integration
def test_direct_lifecycle_record_cannot_forge_foreign_receiver(engine):
    work, _ = active(engine)
    store = engine.host.store
    h = handoff(store, work)
    product = Store(store.settings, scope=work.owner)
    try:
        product.add_record(
            HandoffLifecycle(
                handoff_id=h.handoff_id,
                work_item_id=work.work_item_id,
                phase="completed_at",
                actor=work.assigned_agent,
            )
        )
    except (PermissionError, ValueError):
        return
    assert store.records("Handoff", work.work_item_id)[0]["completed_at"] is None


@pytest.mark.integration
def test_lifecycle_target_cannot_cross_product_boundary(engine):
    store = engine.host.store
    victim = store.create(
        WorkItem(
            owner="aegis",
            title="Victim",
            description="Private",
            assigned_agent="VICTIM",
            reviewer="VICTIM_REVIEWER",
        )
    )
    own = store.create(WorkItem(owner="triad", title="Own", description="Private"))
    h = handoff(store, victim)
    product = Store(store.settings, scope="triad")
    try:
        product.add_record(
            HandoffLifecycle(
                handoff_id=h.handoff_id,
                work_item_id=own.work_item_id,
                phase="completed_at",
                actor="ATTACKER",
            )
        )
    except (PermissionError, ValueError):
        return
    assert (
        Store(store.settings, scope="aegis").records("Handoff", victim.work_item_id)[0][
            "completed_at"
        ]
        is None
    )


@pytest.mark.integration
def test_normal_review_completes_handoff_atomically_and_keeps_initial_time(engine):
    work, _ = active(engine)
    store = engine.host.store
    handoff(store, work)
    store.receive_handoff(work.work_item_id, work.reviewer)
    before = store.records("Handoff", work.work_item_id)[0]
    store.add_record(
        Review(
            reviewer=work.reviewer,
            work_item_id=work.work_item_id,
            decision="APPROVE",
            findings=(),
            severity="NONE",
            evidence_checked=("fixture",),
            tests_repeated=("fixture",),
        )
    )
    after = store.records("Handoff", work.work_item_id)[0]
    assert after["received_at"] == before["received_at"]
    assert after["acknowledged_at"] == before["acknowledged_at"]
    assert datetime.fromisoformat(after["completed_at"]) >= datetime.fromisoformat(
        after["acknowledged_at"]
    )
    store.handoff_lifecycle(work.work_item_id, "completed_at", work.reviewer)
    assert store.records("Handoff", work.work_item_id)[0]["completed_at"] == after["completed_at"]


@pytest.mark.integration
def test_quality_preserves_explicit_historical_times_and_absent_start(engine):
    records = Records(engine.host.store)
    original = build(records)
    prior = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=5)))
    changed = original.model_dump() | {
        "implementation_run_id": "historical-time-fixture",
        "started_at": prior,
        "completed_at": prior + timedelta(minutes=3),
    }
    historical = ImplementationRun.model_validate(changed)
    identifier = Quality(records).implementation(historical)
    stored = records.get(identifier)
    assert datetime.fromisoformat(stored["started_at"]) == prior
    assert datetime.fromisoformat(stored["completed_at"]) == prior + timedelta(minutes=3)
    assert records.get(original.implementation_run_id)["started_at"] is None
    review = QARun.model_validate(
        qa(historical).model_dump()
        | {"started_at": prior, "completed_at": prior + timedelta(minutes=4)}
    )
    stored_qa = records.get(Quality(records).review(review))
    assert datetime.fromisoformat(stored_qa["completed_at"]) == prior + timedelta(minutes=4)
    assert historical.started_at.tzinfo == UTC
    with pytest.raises(ValueError, match="timezone"):
        QARun.model_validate(review.model_dump() | {"completed_at": prior.replace(tzinfo=None)})
