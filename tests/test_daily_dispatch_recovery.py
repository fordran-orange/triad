"""The observer does not compete with live startup; only unstarted work retries."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest

from products.triad import daily_process


def fixture(monkeypatch, *, state="RUNNING", work_exists=False, date="2026-10-03"):
    rows = {
        "DailyDispatch": [
            {"id": "dispatch", "cycle_id": "same-id", "schedule_id": "schedule", "control_epoch": 4}
        ],
        "DailyDispatchProcess": [
            {
                "id": "process",
                "attempt_id": "dispatch",
                "cycle_id": "same-id",
                "pid": 123,
                "creation_id": "birth",
            }
        ],
        "DailyStartupState": [{"state": "DEFERRED", "attempt_id": "dispatch"}],
        "DailyScheduleClaim": [{"date": date}],
    }
    leases = []
    events = []
    launches = []

    @contextmanager
    def lease(name):
        leases.append(name)
        yield

    @contextmanager
    def connect():
        yield NS(execute=lambda *_: NS(fetchone=lambda: {"work": 1} if work_exists else None))

    def current(_):
        raise KeyError("not started")

    s = NS(
        product=NS(list=lambda kind, **_: rows.get(kind, []), ledger=NS(guard=lambda **_: None)),
        host=NS(
            store=NS(lease=lease, connect=connect),
            append=lambda kind, row, **_: events.append((kind, row)),
        ),
        current=current,
        require_complete=lambda _: None,
        history=NS(blocked=lambda **kw: events.append(("blocked", kw))),
        schedule=lambda: {
            "id": "schedule",
            "enabled": True,
            "control_epoch": 4,
            "timezone": "America/Chicago",
            "manual_prerequisite": "accepted",
        },
    )
    monkeypatch.setattr(
        daily_process,
        "process_info",
        lambda _: {"state": state, "creation_id": "birth", "exit_code": 75},
    )
    monkeypatch.setattr(daily_process, "now", lambda: datetime(2026, 10, 3, 16, tzinfo=UTC))
    monkeypatch.setattr(daily_process, "launch", lambda **kw: launches.append(kw))
    return s, leases, events, launches, rows


def test_live_runner_monitor_never_takes_execution_lease(monkeypatch):
    s, leases, events, launches, _ = fixture(monkeypatch)
    daily_process.reconcile(s)
    assert leases == ["triad-daily-process-monitor"]
    assert events == launches == []


def test_deferred_precreation_retries_same_scheduled_identity(monkeypatch):
    s, leases, events, launches, _ = fixture(monkeypatch, state="EXITED")
    daily_process.reconcile(s)
    assert leases == ["triad-daily-process-monitor", "triad-daily-product-execution"]
    assert launches == [
        {"cycle_id": "same-id", "scheduled": True, "expected_epoch": 4, "schedule_id": "schedule"}
    ]
    assert events[0][0] == "DailyStartupRetry"
    assert not any(kind == "blocked" for kind, _ in events)


@pytest.mark.parametrize(
    "defect",
    [
        "work_exists",
        "old_date",
        "unknown",
        "changed_schedule",
        "wrong_exit",
        "no_deferred",
        "wrong_attempt",
    ],
)
def test_unknown_or_started_execution_never_automatically_replays(monkeypatch, defect):
    s, _, _, launches, rows = fixture(
        monkeypatch,
        state="EXITED",
        work_exists=defect == "work_exists",
        date="2026-10-02" if defect == "old_date" else "2026-10-03",
    )
    if defect == "unknown":
        monkeypatch.setattr(daily_process, "process_info", lambda _: {"state": "UNKNOWN"})
    if defect == "changed_schedule":
        s.schedule = lambda: {
            "enabled": False,
            "id": "schedule",
            "control_epoch": 4,
            "timezone": "America/Chicago",
        }
    if defect == "wrong_exit":
        monkeypatch.setattr(
            daily_process, "process_info", lambda _: {"state": "EXITED", "exit_code": 1}
        )
    if defect == "no_deferred":
        rows["DailyStartupState"] = []
    if defect == "wrong_attempt":
        rows["DailyStartupState"][-1]["attempt_id"] = "previous-attempt"
    daily_process.reconcile(s)
    assert launches == []
