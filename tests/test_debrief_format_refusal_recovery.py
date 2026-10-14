"""Disposable evidence checks for operator recovery of the known schema conflict."""
# ruff: noqa: F811

import pytest
from products.triad.daily import TOMORROW_KEYS
from test_daily_lifecycle import daily, to_debrief
from test_day3_integration import engine  # noqa: F401
from trading_core.work import State, WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.triad]


def fixture(engine, monkeypatch, defect=None):
    s = daily(engine)
    cycle = to_debrief(s)
    artifact = {"what_changed_about_tomorrow": {}}
    summary = "The supplied schema cannot represent the seven required answers"
    s.host.append("SequentialDailyProgram", {"cycle_id": cycle.cycle_id, "policy_id": "fixture"}, owner="triad")
    monkeypatch.setattr("trading_core.product_changes.active_policy", lambda _: {"id": "fixture"})
    works = []
    for run in ["original", "repair"]:
        work = s.host.store.create(WorkItem(
            owner="triad", mission_id=cycle.cycle_id, work_type="review", title="Disposable debrief",
            description="Fixture only", assigned_agent="CLAUDE", authority_tier=0,
            parent_work_item_id=cycle.parent_work_item_id, execution_permissions=("read",),
            allowed_tools=("read_file",),
            allowed_paths=("app/product.py",) if run == "repair" and defect == "work_paths" else (),
        ))
        updates = {"status": State.FAILED, "revision": 1}
        stopped = work.model_copy(update=updates)
        s.host.store.step(work, stopped, "Disposable completed failed reporting run")
        works.append(stopped)
        context = {
            "cycle": {"cycle_id": cycle.cycle_id, "verified_revision": None},
            "required_tomorrow_keys": list(TOMORROW_KEYS),
            "schema": {"title": "Debrief", "properties": {"what_changed_about_tomorrow": {
                "type": "object", "additionalProperties": {"type": "string"},
            }}},
        } if run == "original" else {
            "previous_run_id": "original", "original_artifact": artifact,
            "schema": {"title": "Debrief"},
            "validation_errors": "What changed about tomorrow requires all seven answers",
        }
        request = {
            "run_id": run, "work_item_id": work.work_item_id, "mission_id": cycle.cycle_id,
            "agent_id": "CLAUDE", "role": "REVIEW", "execution_permissions": ["read"],
            "control_epoch": cycle.control_epoch, "context_packet": context,
            "objective": "Write a candid Daily Debrief using supplied actual evidence." if run == "original"
                else "Repair only the response format of the supplied complete artifact.",
        }
        result = {"run_id": run, "status": "BLOCKED" if run == "repair" else "DOCUMENTATION_CHANGE",
                  "summary": summary, "analysis_artifacts": [artifact]}
        usage = {"run_id": run, "agent": "CLAUDE", "status": "SUCCESS"}
        if run == "repair":
            if defect == "foreign_mission": request["mission_id"] = "foreign"
            if defect == "writer": request["execution_permissions"] = ["write_code"]
            if defect == "wrong_epoch": request["control_epoch"] = -1
            if defect == "wrong_agent": request["agent_id"] = "CODEX"
            if defect == "unrelated_request": request["objective"] = "Inspect a product"
            if defect == "unrelated_schema": context["schema"]["title"] = "ProductProposal"
            if defect == "unbound_artifact": context["original_artifact"] = {"different": "artifact"}
            if defect == "not_stopped": usage["status"] = "RUNNING"
            if defect == "not_refused": result["status"] = "DOCUMENTATION_CHANGE"
            if defect == "usage_wrong_agent": usage["agent"] = "GROK"
            if defect == "request_paths": request["allowed_paths"] = ["app/product.py"]
        if run == "original" and defect == "not_schema_conflict":
            context["schema"]["properties"]["what_changed_about_tomorrow"]["properties"] = {"new_capability": {"type": "string"}}
        for kind, payload in [("AgentRunRequest", request), ("AgentRunResult", result), ("Usage", usage)]:
            column_work = works[0].work_item_id if run == "repair" and (
                (defect == "result_other_work" and kind == "AgentRunResult")
                or (defect == "usage_other_work" and kind == "Usage")
                or (defect == "request_other_work" and kind == "AgentRunRequest")
            ) else work.work_item_id
            s.host.ledger.put(kind, payload, work_id=column_work)
    if defect != "missing_retry":
        s.host.append("ProductResponseRetry", {"mission_id": cycle.cycle_id, "previous_run_id": "original",
            "agent": "CLAUDE", "recovery_mode": "FORMAT_REPAIR", "failure_category": "SCHEMA"}, owner="triad")
    s.transition(cycle.cycle_id, "BLOCKED", ["PermissionError"], failures=({"code": "PermissionError",
        "message": "Different refusal" if defect == "wrong_failure" else "Provider blocked this assignment: " + summary},))
    return s, cycle, works


def test_explicit_recovery_preserves_work_and_still_requires_completed_turns(engine, monkeypatch):
    s, cycle, works = fixture(engine, monkeypatch)
    with pytest.raises(PermissionError, match="Only a blocked reporting"):
        s.resume_debrief(cycle.cycle_id)
    with pytest.raises(PermissionError, match="All three"):
        s.resume_debrief(cycle.cycle_id, blocked_format_repair_run_id="repair")
    checks = []
    monkeypatch.setattr(s, "require_turns_complete", lambda *args: checks.append(args[0]))
    result = s.resume_debrief(cycle.cycle_id, blocked_format_repair_run_id="repair")
    assert result.status == "DEBRIEFING" and checks == [cycle.cycle_id]
    assert all(s.host.store.get(w.work_item_id) == w for w in works)
    assert result.failures[-1]["code"] == "PermissionError"
    with pytest.raises(PermissionError):
        s.transition(cycle.cycle_id, "COMPLETED", ["No independent debrief QA"])


@pytest.mark.parametrize("defect", ["foreign_mission", "writer", "wrong_epoch", "wrong_agent",
    "unrelated_request", "unrelated_schema", "unbound_artifact", "not_stopped", "not_refused",
    "not_schema_conflict", "missing_retry", "wrong_failure", "usage_wrong_agent", "request_paths",
    "work_paths", "result_other_work", "usage_other_work", "request_other_work"])
def test_unrelated_or_incomplete_proof_cannot_reopen_reporting(engine, monkeypatch, defect):
    s, cycle, _ = fixture(engine, monkeypatch, defect)
    with pytest.raises(PermissionError, match="evidence does not match"):
        s.resume_debrief(cycle.cycle_id, blocked_format_repair_run_id="repair")
    assert s.current(cycle.cycle_id)["status"] == "BLOCKED"
