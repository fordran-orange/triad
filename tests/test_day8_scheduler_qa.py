"""Independent scheduler authority/race cases; disposable database only."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Barrier

import pytest
from products.triad.daily import DailySchedule
from products.triad.daily_development import DailyDevelopment
from products.triad.daily_scheduler import next_cycle, tick
from test_daily_lifecycle import daily
from test_day3_integration import engine  # noqa: F401
from test_day8_daily_qa import reviewed
from trading_core.ledger import Stopped
from trading_core.store import ConcurrentUpdate


def enabled(engine):
    service = daily(engine)
    cycle, _, _, _ = reviewed(service)
    service.transition(cycle.cycle_id, "COMPLETED", ["fixture acceptance"])
    service.configure(DailySchedule(enabled=True))
    due = datetime.fromisoformat(service.schedule()["effective_after"] + "T15:00:00+00:00")
    return service, due


@pytest.mark.integration
@pytest.mark.parametrize("change", ["kill_resume", "disable"])
def test_claim_cannot_dispatch_after_authority_changes(engine, monkeypatch, change):
    service, due = enabled(engine)
    original = service.host.store.lease

    changed = False

    @contextmanager
    def controlled(name):
        nonlocal changed
        with original(name):
            yield
        if name == "triad-daily-schedule-slot" and not changed:
            changed = True
            if change == "kill_resume":
                service.host.ledger.operate("kill")
                service.host.ledger.operate("resume")
            else:
                service.configure(DailySchedule(enabled=False))

    monkeypatch.setattr(service.host.store, "lease", controlled)
    workflow = DailyDevelopment.__new__(DailyDevelopment)
    workflow.host = service.host
    workflow.daily = service
    executed = []

    def inspect(mission):
        executed.append(mission)
        raise RuntimeError("Stop before any inference")

    workflow.inspect = inspect

    def runner(**kwargs):
        return workflow.run_daily(verify=lambda _: None, **kwargs)

    try:
        tick(service=service, instant=due, run=runner)
    except (PermissionError, Stopped):
        pass
    assert executed == [], "Claimed old authorization must not start an inspection after revocation"


@pytest.mark.integration
def test_concurrent_ticks_claim_once_and_do_not_repeat_failed_slot(engine):
    service, due = enabled(engine)
    barrier = Barrier(2)
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("fixture failed runner")

    def attempt():
        barrier.wait(timeout=5)
        try:
            return tick(service=service, instant=due, run=fail)
        except ConcurrentUpdate:
            return {"status": "LEASE_BUSY"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert len(calls) == 1
    assert len(service.product.list("DailyScheduleClaim")) == 1
    assert tick(service=service, instant=due, run=fail)["status"] == "ALREADY_CLAIMED"
    assert len(calls) == 1
    assert any(o["status"] == "BLOCKED" for o in outcomes)


@pytest.mark.integration
@pytest.mark.parametrize("action", ["pause", "kill", "stale_epoch", "product_pause"])
def test_existing_control_restriction_prevents_any_claim(engine, action):
    service, due = enabled(engine)
    if action == "product_pause":
        service.product.ledger.operate("pause")
    else:
        service.host.ledger.operate("pause" if action == "stale_epoch" else action)
        if action == "stale_epoch":
            service.host.ledger.operate("resume")
    calls = []
    with pytest.raises(Stopped):
        tick(service=service, instant=due, run=lambda **kw: calls.append(kw))
    assert not calls
    assert service.product.list("DailyScheduleClaim") == []


@pytest.mark.integration
def test_missing_trusted_runner_never_reserves_slot(engine):
    service, due = enabled(engine)
    with pytest.raises(PermissionError):
        tick(service=service, instant=due)
    assert service.product.list("DailyScheduleClaim") == []


def test_next_cycle_uses_real_local_time_across_dst_gap():
    config = {
        **DailySchedule(enabled=True, time="02:30").model_dump(),
        "effective_after": "2026-03-08",
    }
    instant = datetime(2026, 3, 8, 7, tzinfo=UTC)
    candidate = datetime.fromisoformat(next_cycle(config, instant))
    from zoneinfo import ZoneInfo

    local = candidate.astimezone(UTC).astimezone(ZoneInfo("America/Chicago"))
    assert (candidate.hour, candidate.minute) == (local.hour, local.minute), (
        "Do not show nonexistent local wall time"
    )


@pytest.mark.integration
def test_original_authorized_scheduled_create_and_replaced_config(engine):
    service, _ = enabled(engine)
    config = service.schedule()
    cycle = service.create(
        scheduled=True, expected_epoch=config["control_epoch"], schedule_id=config["id"]
    )
    assert cycle.scheduled is True and cycle.control_epoch == config["control_epoch"]
    service.configure(DailySchedule(enabled=True, time="10:00"))
    with pytest.raises(PermissionError):
        service.create(
            scheduled=True, expected_epoch=config["control_epoch"], schedule_id=config["id"]
        )
    with pytest.raises(PermissionError):
        service.create(scheduled=True)


@pytest.mark.integration
def test_fall_fold_claims_only_first_occurrence(engine):
    service, _ = enabled(engine)
    service.configure(DailySchedule(enabled=True, time="01:30"))
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("fixture stop")

    first = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    second = datetime(2026, 11, 1, 7, 30, tzinfo=UTC)
    assert tick(service=service, instant=first, run=fail)["status"] == "BLOCKED"
    assert tick(service=service, instant=second, run=fail)["status"] == "ALREADY_CLAIMED"
    assert len(calls) == 1
    assert next_cycle(service.schedule(), first).startswith("2026-11-02T01:30")


def test_spring_gap_dispatch_skips_same_day_as_preview():
    from types import SimpleNamespace

    config = {
        **DailySchedule(enabled=True, time="02:30").model_dump(),
        "effective_after": "2026-03-08",
        "control_epoch": 1,
        "manual_prerequisite": "reviewed",
    }
    service = SimpleNamespace(
        schedule=lambda: config,
        product=SimpleNamespace(ledger=SimpleNamespace(guard=lambda **_: None)),
        require_complete=lambda _: None,
    )
    result = tick(
        service=service,
        instant=datetime(2026, 3, 8, 9, tzinfo=UTC),
        run=lambda **_: pytest.fail("Must not dispatch nonexistent wall time"),
    )
    assert result["status"] == "NOT_DUE"
    assert result["next_cycle"].startswith("2026-03-09T02:30")
