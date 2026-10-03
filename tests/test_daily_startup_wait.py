"""Contention, wake deadlines and retry identity without running providers."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from trading_core.store import ConcurrentUpdate

from products.triad import daily_startup, daily_wakeup


def service(failures=0):
    events, guards, leases = [], [], []

    @contextmanager
    def lease(name):
        leases.append(name)
        if len(leases) <= failures:
            error = ConcurrentUpdate("busy")
            error.lease_holders = [
                {"database_pid": 123, "application_name": "Triad pid:456 lease:runner"}
            ]
            raise error
        try:
            yield
        finally:
            events.append(("released", {}))

    s = NS(
        host=NS(store=NS(lease=lease), append=lambda kind, row, **_: events.append((kind, row))),
        ledger=NS(guard=lambda **kw: guards.append(kw)),
        daily=NS(schedule=lambda: {"id": "schedule", "enabled": True, "control_epoch": 4}),
    )
    return s, events, guards, leases


def clock(monkeypatch):
    value = [0]
    monkeypatch.setattr(daily_startup.time, "monotonic", lambda: value[0])
    monkeypatch.setattr(
        daily_startup.time, "sleep", lambda seconds: value.__setitem__(0, value[0] + seconds)
    )


def test_busy_startup_waits_before_any_product_execution(monkeypatch):
    clock(monkeypatch)
    s, events, guards, leases = service(2)
    with daily_startup.execution_lease(
        s, "same-id", scheduled=True, expected_epoch=4, schedule_id="schedule"
    ):
        assert events[-1][1]["state"] == "OWNED"
        events.append(("product-work", {}))
    assert events[0][1]["state"] == "WAITING"
    assert events[0][1]["holders"][0]["database_pid"] == 123
    assert len(guards) == 4 and len(leases) == 3
    assert [e[0] for e in events][-2:] == ["product-work", "released"]


def test_waiting_checks_kill_and_never_enters_work(monkeypatch):
    clock(monkeypatch)
    s, events, _, _ = service(99)
    count = [0]

    def guard(**_):
        count[0] += 1
        if count[0] > 1:
            raise PermissionError("operator stopped")

    s.ledger.guard = guard
    with (
        pytest.raises(PermissionError, match="operator stopped"),
        daily_startup.execution_lease(s, "id"),
    ):
        pytest.fail("work started")
    assert not any(r.get("state") == "OWNED" for _, r in events)


def test_timeout_is_deferred_not_product_failure(monkeypatch):
    clock(monkeypatch)
    s, events, _, _ = service(99)
    with (
        pytest.raises(daily_startup.StartupDeferred),
        daily_startup.execution_lease(s, "id", timeout=2),
    ):
        pytest.fail("work started")
    assert events[-1][1]["state"] == "DEFERRED"


def test_changed_schedule_denies_waiting_startup(monkeypatch):
    clock(monkeypatch)
    s, _, _, _ = service(99)
    with (
        pytest.raises(PermissionError, match="authority changed"),
        daily_startup.execution_lease(
            s, "id", scheduled=True, expected_epoch=4, schedule_id="other"
        ),
    ):
        pytest.fail("work started")


def test_failed_ack_releases_execution_lock():
    s, events, _, _ = service()
    s.host.append = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database write failed"))
    with pytest.raises(RuntimeError), daily_startup.execution_lease(s, "id"):
        pytest.fail("work started")
    assert events[-1][0] == "released"


def test_failed_notification_preserves_accepted_submission():
    @contextmanager
    def connect():
        raise RuntimeError("notification channel unavailable")
        yield

    daily_wakeup.WAKE.clear()
    daily_wakeup.QUEUE_WAKE.clear()
    daily_wakeup.notify(NS(connect=connect))
    assert daily_wakeup.WAKE.is_set() and daily_wakeup.QUEUE_WAKE.is_set()
    daily_wakeup.WAKE.clear()
    daily_wakeup.QUEUE_WAKE.clear()


@pytest.mark.parametrize(
    "active,instant,expected",
    [
        (False, datetime(2026, 10, 3, 12, tzinfo=UTC), 300),
        (False, datetime(2026, 10, 3, 13, 59, tzinfo=UTC), 60),
        (True, datetime(2026, 10, 3, 12, tzinfo=UTC), 30),
    ],
)
def test_idle_schedule_deadline_and_active_delays(active, instant, expected):
    @contextmanager
    def connect():
        yield NS(execute=lambda *_: NS(fetchone=lambda: {"pending": 1} if active else None))

    s = NS(
        schedule=lambda: {
            "enabled": True,
            "time": "09:00",
            "timezone": "America/Chicago",
            "days": list(range(7)),
            "effective_after": "2026-10-01",
        },
        host=NS(store=NS(connect=connect)),
    )
    assert daily_wakeup.delay(s, instant) == expected


def test_submission_wakes_idle_worker():
    daily_wakeup.WAKE.clear()
    daily_wakeup.wake()
    assert daily_wakeup.WAKE.wait(0)
    daily_wakeup.WAKE.clear()
