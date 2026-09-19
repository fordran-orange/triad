# ruff: noqa: F811
"""Disposable database tests; never create production completion/schedule proof."""

import pytest
from products.triad.daily import Daily, DailySchedule, Debrief, digest
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.quality import Quality
from trading_core.store import Store

pytestmark = pytest.mark.integration


def daily(engine):
    return Daily(Store(engine.host.store.settings))


def to_debrief(service):
    cycle = service.create()
    for state in (
        "INSPECTING",
        "SELECTING",
        "BUILDING",
        "AWAITING_QA",
        "CORRECTING",
        "AWAITING_QA",
        "MERGING",
        "VERIFYING",
        "DEBRIEFING",
    ):
        service.transition(
            cycle.cycle_id, state, ["disposable-test-evidence"], merge_commit="test-merge"
        )
    return cycle


def draft(cycle):
    return Debrief(
        cycle_id=cycle.cycle_id,
        date="2026-09-19",
        overall_status="VERIFIED_AWAITING_DEBRIEF_QA",
        started_at=cycle.created_at,
        finished_at=cycle.created_at,
        primary_improvement="Fixture",
        product_area="Research",
        builder="CLAUDE",
        qa_reviewer="CODEX",
        corrections=(),
        merge_status="MERGED",
        major_risks=("Test only",),
        contributions=(
            {
                "model": "test-model",
                "agent": "CLAUDE",
                "role": "builder",
                "changed": "fixture",
                "reason": "test",
                "why_you_care": "test",
                "effects": [
                    {
                        "order": 1,
                        "classification": "OBSERVED",
                        "description": "test",
                        "evidence": ["test"],
                    }
                ],
                "strategic_gain": "NONE",
                "debt_introduced": [],
                "debt_retired": [],
                "qa_result": "PASS",
                "evidence": ["test"],
            },
        ),
        proposed_gain="HIGH",
        gain_reason="Builder cannot decide",
        gain_evidence=("test",),
        capability_gained="Test",
        constraint_removed="None",
        debt=(),
        debt_introduced_statement="None",
        debt_retired_statement="None",
        net_effect={"Product": "Test"},
        what_changed_about_tomorrow={
            k: "Test"
            for k in (
                "new_capability",
                "more_important",
                "less_important",
                "changed_assumption",
                "new_dependency",
                "risk_to_monitor",
                "next_cycle",
            )
        },
        failures=(),
        evidence=("test",),
    )


def test_states_require_evidence_and_cannot_complete_on_merge(engine):
    service = daily(engine)
    cycle = service.create()
    assert cycle.status == "CREATED" and cycle.scheduled is False
    assert cycle.parent_work_item_id and cycle.control_epoch is not None
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["skip"])
    with pytest.raises(ValueError):
        service.transition(cycle.cycle_id, "INSPECTING", [])
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "INSPECTING", ["x"], control_epoch=99)
    service.transition(cycle.cycle_id, "BLOCKED", ["provider unavailable"])
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "INSPECTING", ["resume"])
    assert service.current(cycle.cycle_id)["finished_at"]
    with pytest.raises(ValueError):
        service.create(cycle_id=cycle.cycle_id)
    with pytest.raises(PermissionError):
        service.configure(DailySchedule(enabled=True))


def test_debrief_independent_hash_and_gain_before_completion(engine):
    service = daily(engine)
    cycle = to_debrief(service)
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["not enough"])
    doc = draft(cycle)
    draft_id = service.draft(doc)
    commit = "debrief:" + digest(doc.model_dump(mode="json"))
    quality = Quality(service.host)
    build = ImplementationRun(
        owner="triad",
        builder="CLAUDE",
        provider="test",
        model="fixture",
        transport="test",
        base_commit="test",
        change_commit=commit,
        files=(),
        tests=("fixture",),
        evidence=("fixture",),
    )
    quality.implementation(build)
    assessment = {
        "classification": "LOW",
        "reason": "Independent test downgrade",
        "action": "DOWNGRADE",
    }
    qa = QARun(
        implementation_run_id=build.implementation_run_id,
        qa_agent="CODEX",
        qa_provider="test",
        qa_model="fixture",
        reviewed_commit=commit,
        agent_capabilities_used=("test",),
        tests_repeated=("test",),
        evidence=("strategic-assessment:" + digest(assessment),),
        decision="PASS",
        execution_mode="HOST_INDEPENDENT_QA",
    )
    quality.review(qa)
    with pytest.raises(PermissionError):
        service.publish(
            draft_id,
            build.implementation_run_id,
            classification="HIGH",
            reason="Builder override",
            reviewer_action="CONFIRM",
        )
    service.publish(
        draft_id,
        build.implementation_run_id,
        classification="LOW",
        reason=assessment["reason"],
        reviewer_action="DOWNGRADE",
    )
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["missing verification"])
    service.host.append(
        "DailyVerification",
        {
            "cycle_id": cycle.cycle_id,
            "merge_commit": "test-merge",
            "status": "PASS",
            "evidence": ["test"],
        },
        owner="triad",
    )
    service.transition(cycle.cycle_id, "COMPLETED", ["verification and reviewed debrief"])
    assert service.debriefs()[0]["classification"] == "LOW"
    service.configure(DailySchedule(enabled=True))
    assert service.schedule()["enabled"] is True
    assert service.schedule()["effective_after"]
    failed = qa.model_copy(
        update={
            "qa_run_id": "new-failure",
            "decision": "CHANGES_REQUIRED",
            "required_changes": ("stale",),
        }
    )
    quality.review(failed)
    with pytest.raises(PermissionError):
        service.configure(DailySchedule(enabled=True))


def test_product_cannot_forge_publication_or_schedule(engine):
    from trading_core.intelligence.records import Records

    records = Records(Store(engine.host.store.settings, scope="triad"))
    for kind in (
        "DailySchedule",
        "DailyDebriefPublication",
        "DailyVerification",
        "DailyCycleTransition",
    ):
        with pytest.raises(PermissionError):
            records.append(kind, {"status": "PASS"}, owner="triad")
    with pytest.raises(PermissionError):
        Daily(records.store)
