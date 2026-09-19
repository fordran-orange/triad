"""Independent Day 8 lifecycle adversarial checks; disposable databases only."""
# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError

import pytest
from products.triad.daily import DailySchedule, digest
from test_daily_lifecycle import daily, draft, to_debrief
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.ledger import Ledger, Stopped
from trading_core.store import Store
from trading_core.work import uid

pytestmark = pytest.mark.integration


def reviewed(service):
    cycle = to_debrief(service)
    doc = draft(cycle)
    draft_id = service.draft(doc)
    commit = "debrief:" + digest(doc.model_dump(mode="json"))
    quality = Quality(service.host)
    build = ImplementationRun(
        owner="triad",
        builder="CLAUDE",
        provider="fixture",
        model="fixture",
        transport="fixture",
        base_commit="fixture",
        change_commit=commit,
        files=(),
        tests=("fixture",),
        evidence=("fixture",),
    )
    quality.implementation(build)
    assessment = {"classification": "LOW", "reason": "Independent downgrade", "action": "DOWNGRADE"}
    qa = QARun(
        implementation_run_id=build.implementation_run_id,
        qa_agent="CODEX",
        qa_provider="fixture",
        qa_model="fixture",
        reviewed_commit=commit,
        agent_capabilities_used=("evidence review",),
        tests_repeated=("fixture",),
        evidence=("strategic-assessment:" + digest(assessment),),
        decision="PASS",
        execution_mode="HOST_INDEPENDENT_QA",
    )
    quality.review(qa)
    service.publish(
        draft_id,
        build.implementation_run_id,
        classification="LOW",
        reason=assessment["reason"],
        reviewer_action="DOWNGRADE",
    )
    service.host.append(
        "DailyVerification",
        {
            "cycle_id": cycle.cycle_id,
            "merge_commit": "test-merge",
            "status": "PASS",
            "evidence": ["independent fixture verification"],
        },
        owner="triad",
    )
    return cycle, build, qa, draft_id


@pytest.mark.parametrize(
    "changes",
    [
        {"merge_commit": "unverified-replacement"},
        {"implementation_runs": ({"id": "unreviewed-build"},)},
        {"qa_runs": ({"id": "unrelated-qa"},)},
    ],
)
def test_completion_cannot_replace_the_reviewed_snapshot(engine, changes):
    service = daily(engine)
    cycle, _, _, _ = reviewed(service)
    before = service.current(cycle.cycle_id)
    with pytest.raises((PermissionError, ValueError)):
        service.transition(cycle.cycle_id, "COMPLETED", ["attempt replacement"], **changes)
    assert service.current(cycle.cycle_id) == before


def test_latest_failed_verification_and_qa_block_completion(engine):
    service = daily(engine)
    cycle, _, qa, _ = reviewed(service)
    service.host.append(
        "DailyVerification",
        {
            "cycle_id": cycle.cycle_id,
            "merge_commit": "test-merge",
            "status": "FAILED",
            "evidence": ["regression failed"],
        },
        owner="triad",
    )
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["stale successful verification"])
    service.host.append(
        "DailyVerification",
        {
            "cycle_id": cycle.cycle_id,
            "merge_commit": "test-merge",
            "status": "PASS",
            "evidence": ["fresh rerun"],
        },
        owner="triad",
    )
    Quality(service.host).review(
        qa.model_copy(
            update={
                "qa_run_id": uid(),
                "decision": "CHANGES_REQUIRED",
                "required_changes": ("fix",),
            }
        )
    )
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["superseded debrief QA"])
    with pytest.raises(PermissionError):
        service.configure(DailySchedule(enabled=True))


def test_scoped_products_cannot_forge_all_daily_host_records(engine):
    kinds = (
        "DailyCycleTransition",
        "DailyVerification",
        "DailyDebriefDraft",
        "DailyDebriefPublication",
        "DailySchedule",
        "DailyScheduleClaim",
    )
    for owner in ("triad", "aegis", "core"):
        store = Store(engine.host.store.settings, scope=owner)
        for kind in kinds:
            with pytest.raises(PermissionError):
                Records(store).append(kind, {"status": "PASS"}, owner=owner)
            with pytest.raises(PermissionError):
                Ledger(store).put(kind, {"status": "PASS"})


def test_product_pause_blocks_new_daily_creation_and_progress(engine):
    service = daily(engine)
    cycle = service.create()
    Ledger(Store(engine.host.store.settings, scope="triad")).operate("pause")
    with pytest.raises((PermissionError, Stopped)):
        service.create()
    with pytest.raises((PermissionError, Stopped)):
        service.transition(cycle.cycle_id, "INSPECTING", ["paused product"])


def test_parent_stop_blocks_daily_progress(engine):
    service = daily(engine)
    cycle = service.create()
    Ledger(Store(engine.host.store.settings, scope="triad")).operate(
        "stop", work_id=cycle.parent_work_item_id
    )
    with pytest.raises((PermissionError, Stopped)):
        service.transition(cycle.cycle_id, "INSPECTING", ["stopped parent"])


def test_product_pause_blocks_existing_daily_progress(engine):
    service = daily(engine)
    cycle = service.create()
    Ledger(Store(engine.host.store.settings, scope="triad")).operate("pause")
    with pytest.raises((PermissionError, Stopped)):
        service.transition(cycle.cycle_id, "INSPECTING", ["paused product"])


def test_product_pause_blocks_schedule_enable_after_valid_manual_cycle(engine):
    service = daily(engine)
    cycle, _, _, _ = reviewed(service)
    service.transition(cycle.cycle_id, "COMPLETED", ["verified manual prerequisite"])
    Ledger(Store(engine.host.store.settings, scope="triad")).operate("pause")
    with pytest.raises((PermissionError, Stopped)):
        service.configure(DailySchedule(enabled=True))


def test_duplicate_concurrent_create_has_single_evidence_parent(engine, monkeypatch):
    service = daily(engine)
    other = daily(engine)
    cycle_id = uid()
    barrier = Barrier(2)
    original = Store.create

    def synchronized_create(store, work, *args, **kwargs):
        if work.mission_id == cycle_id and work.work_type == "cycle_record":
            # A correct implementation holds the per-cycle lock before creation,
            # so its peer cannot arrive here. The timeout permits that serialized
            # path while still aligning both calls in the original unsafe path.
            try:
                barrier.wait(timeout=1)
            except BrokenBarrierError:
                pass
        return original(store, work, *args, **kwargs)

    monkeypatch.setattr(Store, "create", synchronized_create)

    def create(instance):
        try:
            return instance.create(cycle_id=cycle_id)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, [service, other]))
    assert sum(r is not None for r in results) == 1
    with service.host.store.connect() as conn:
        parents = conn.execute(
            "SELECT id FROM core.work_items WHERE mission_id=%s "
            "AND payload->>'work_type'='cycle_record'",
            (cycle_id,),
        ).fetchall()
    assert len(parents) == 1


def test_valid_completion_is_manual_timestamped_and_schedule_deferred(engine):
    service = daily(engine)
    cycle, _, _, _ = reviewed(service)
    completed = service.transition(cycle.cycle_id, "COMPLETED", ["verified debrief"])
    assert cycle.started_at is None and cycle.finished_at is None
    assert completed.created_at <= completed.started_at <= completed.finished_at
    assert completed.execution_mode == "REAL" and completed.scheduled is False
    transitions = [
        r for r in service.product.list("DailyCycleTransition") if r["cycle_id"] == cycle.cycle_id
    ]
    assert transitions[0]["to"] == "CREATED" and transitions[-1]["to"] == "COMPLETED"
    assert all(r["timestamp"] and r["evidence"] for r in transitions)
    assert service.schedule()["enabled"] is False
    service.configure(DailySchedule(enabled=True))
    schedule = service.schedule()
    assert schedule["manual_prerequisite"] == cycle.cycle_id
    assert schedule["effective_after"] > schedule["updated_at"][:10]
    assert not service.product.list("DailyScheduleClaim")


def test_draft_cannot_reuse_another_exact_debrief_review(engine):
    service = daily(engine)
    _, build, _, _ = reviewed(service)
    other = to_debrief(service)
    other_id = service.draft(draft(other))
    with pytest.raises(PermissionError):
        service.publish(
            other_id,
            build.implementation_run_id,
            classification="LOW",
            reason="Independent downgrade",
            reviewer_action="DOWNGRADE",
        )
