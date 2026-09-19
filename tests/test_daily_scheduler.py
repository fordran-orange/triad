# ruff: noqa: F811
"""Durable scheduler claims with disposable independently reviewed fixtures."""

from datetime import UTC, datetime

import pytest
from products.triad.daily import DailySchedule
from products.triad.daily_scheduler import next_cycle, tick
from test_daily_lifecycle import daily
from test_day3_integration import engine  # noqa: F401
from test_day8_daily_qa import reviewed


def test_next_cycle_timezone_days_and_activation():
    config = {**DailySchedule(enabled=True).model_dump(), "effective_after": "2026-09-20"}
    assert next_cycle(config, datetime(2026, 9, 19, 15, tzinfo=UTC)) == "2026-09-20T09:00:00-05:00"
    assert next_cycle({**config, "enabled": False}) is None
    assert next_cycle({**config, "days": (0,)}, datetime(2026, 9, 19, 15, tzinfo=UTC)).startswith(
        "2026-09-21"
    )
    with pytest.raises(ValueError):
        next_cycle(config, datetime(2026, 9, 19))  # noqa: DTZ001 - deliberate invalid input


@pytest.mark.integration
def test_scheduler_only_after_manual_acceptance_and_once_even_when_failed(engine):
    service = daily(engine)
    assert tick(service=service)["status"] == "DISABLED"
    with pytest.raises(PermissionError):
        service.configure(DailySchedule(enabled=True))
    cycle, _, _, _ = reviewed(service)
    service.transition(cycle.cycle_id, "COMPLETED", ["independent fixture verification"])
    service.configure(DailySchedule(enabled=True))
    effective = service.schedule()["effective_after"]
    before = datetime.fromisoformat(effective + "T10:00:00+00:00")
    due = datetime.fromisoformat(effective + "T15:00:00+00:00")
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("No eligible QA provider")

    assert tick(service=service, instant=before, run=fail)["status"] == "NOT_DUE"
    result = tick(service=service, instant=due, run=fail)
    assert result["status"] == "BLOCKED" and len(calls) == 1
    assert service.current(result["cycle_id"])["scheduled"] is True
    assert tick(service=service, instant=due, run=fail)["status"] == "ALREADY_CLAIMED"
    assert len(calls) == 1
    service.host.ledger.operate("kill")
    assert tick(service=service, instant=due, run=fail)["status"] == "ALREADY_CLAIMED"
    assert len(calls) == 1
