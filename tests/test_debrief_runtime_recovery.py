"""Reporting recovery never grants a bypass around completed-turn evidence."""
# ruff: noqa: F811

import pytest
from test_daily_lifecycle import daily, to_debrief
from test_day3_integration import engine  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.core]


def blocked(engine, monkeypatch, message="InvalidRuntimeResult"):
    service = daily(engine)
    cycle = to_debrief(service)
    service.host.append(
        "SequentialDailyProgram",
        {
            "cycle_id": cycle.cycle_id,
            "policy_id": "fixture",
        },
        owner="triad",
    )
    monkeypatch.setattr("trading_core.product_changes.active_policy", lambda _: {"id": "fixture"})
    service.transition(
        cycle.cycle_id,
        "BLOCKED",
        ["ProviderError"],
        failures=(
            {
                "code": "ProviderError",
                "message": message,
            },
        ),
    )
    return service, cycle


def test_reporting_error_still_requires_all_three_verified_turns(engine, monkeypatch):
    service, cycle = blocked(engine, monkeypatch)
    with pytest.raises(PermissionError, match="All three"):
        service.resume_debrief(cycle.cycle_id)
    assert service.current(cycle.cycle_id)["status"] == "BLOCKED"


def test_reporting_resume_calls_completion_gate_preserves_work_and_ignores_foreign_history(
    engine, monkeypatch
):
    service, cycle = blocked(engine, monkeypatch)
    checks = []
    monkeypatch.setattr(service, "require_turns_complete", lambda *args: checks.append(args[0]))
    service.host.append(
        "CycleRecord", {"cycle_id": cycle.cycle_id, "status": "BUILDING"}, owner="aegis"
    )
    works = service.host.store.list_work(1000)
    result = service.resume_debrief(cycle.cycle_id)
    assert result.status == "DEBRIEFING" and checks == [cycle.cycle_id]
    assert result.failures[-1]["message"] == "InvalidRuntimeResult"
    assert service.host.store.list_work(1000) == works
    with pytest.raises(PermissionError):
        service.resume_debrief(cycle.cycle_id)
    with pytest.raises(PermissionError):
        service.transition(cycle.cycle_id, "COMPLETED", ["not reviewed"])


@pytest.mark.parametrize(
    "message", ["AuthenticationRequired", "OtherFailure", "InvalidRuntimeResult extra"]
)
def test_unrelated_provider_errors_cannot_reopen_reporting(engine, monkeypatch, message):
    service, cycle = blocked(engine, monkeypatch, message)
    with pytest.raises(PermissionError, match="Only a blocked reporting"):
        service.resume_debrief(cycle.cycle_id)
