# ruff: noqa: F811
"""Real PostgreSQL contention and cross-process wake channel, no provider work."""

import threading
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from products.triad.daily_development import DailyDevelopment
from products.triad.sequential import SequentialCycle
from test_day3_integration import engine  # noqa: F401
from trading_core.store import ConcurrentUpdate, Store
from trading_core.work import now

from products.triad import daily_startup, daily_wakeup

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.mark.parametrize("scheduled", [False, True])
def test_real_development_service_startup_and_dispatch_ack(engine, monkeypatch, scheduled):
    """Use real Orchestrator/Records wiring; no provider or product work is launched."""
    service = DailyDevelopment(
        store=Store(engine.host.store.settings, scope="triad"), git=engine.git
    )
    assert not hasattr(service.host, "append")
    cycle_id = str(uuid4())
    config = {
        "id": "fixture-schedule",
        "enabled": True,
        "control_epoch": 0,
        "timezone": "America/Chicago",
    }
    monkeypatch.setattr(service.daily, "schedule", lambda: config)
    # Avoid inventing scheduling authority or calling a provider in this regression.
    cycle = NS(
        cycle_id=cycle_id, parent_work_item_id="fixture-parent", control_epoch=0, created_at=now()
    )
    monkeypatch.setattr(service.daily, "create", lambda **_: cycle)
    monkeypatch.setattr(service, "transition", lambda *a, **k: None)
    flow = object.__new__(SequentialCycle)
    flow.s = service
    flow.policy = {"id": "fixture-policy"}
    monkeypatch.setattr(flow, "close_failed_work", lambda *a: None)

    def stop_before_provider(_):
        raise RuntimeError("fixture reached readiness")

    monkeypatch.setattr(flow, "readiness", stop_before_provider)
    with pytest.raises(RuntimeError, match="fixture reached readiness"):
        flow.run(
            scheduled=scheduled,
            cycle_id=cycle_id,
            verify=lambda _: {},
            expected_epoch=0,
            schedule_id=config["id"],
        )
    startup = service.canonical.list("DailyStartupState", matching={"cycle_id": cycle_id})
    assert len(startup) == 1 and startup[0]["state"] == "OWNED"
    acknowledged = service.canonical.list(
        "DailyDispatchAcknowledged", matching={"cycle_id": cycle_id}
    )
    assert len(acknowledged) == int(scheduled)
    if scheduled:
        assert acknowledged[0]["parent_work_item_id"] == "fixture-parent"
    assert (
        len(service.canonical.list("SequentialDailyProgram", matching={"cycle_id": cycle_id})) == 1
    )
    with service.host.store.lease("triad-daily-product-execution"):
        pass  # Downstream errors must still release actual PostgreSQL ownership.


def test_runner_waits_and_monitor_does_not_own_execution(engine):
    store = engine.host.store
    entered = threading.Event()
    waiting = threading.Event()
    outcome = []

    def append(kind, payload, **_):
        if payload.get("state") == "WAITING":
            waiting.set()
            outcome.append(payload)

    service = NS(
        host=NS(store=store), canonical=NS(append=append), ledger=NS(guard=lambda **_: None)
    )

    def runner():
        with daily_startup.execution_lease(service, "fixture", timeout=8):
            entered.set()

    with store.lease("triad-daily-product-execution"):
        worker = threading.Thread(target=runner)
        worker.start()
        assert waiting.wait(4), "runner did not record actual contention"
        assert not entered.is_set()
        with store.lease("triad-daily-process-monitor"):
            assert "Triad pid:" in outcome[0]["holders"][0]["application_name"]
    assert entered.wait(4), "runner did not start after owner released"
    worker.join(4)
    assert not worker.is_alive()


def test_lock_diagnostics_do_not_expose_queries(engine):
    with (
        engine.host.store.lease("fixture-lock"),
        pytest.raises(ConcurrentUpdate) as error,
        engine.host.store.lease("fixture-lock"),
    ):
        pytest.fail("duplicate execution")
    assert error.value.lease_holders
    assert set(error.value.lease_holders[0]) == {
        "database_pid",
        "application_name",
        "backend_start",
    }


def test_submitted_work_notification_reaches_another_connection(engine):
    with engine.host.store.connect() as conn:
        conn.autocommit = True
        conn.execute("LISTEN triad_worker_wake")
        daily_wakeup.notify(engine.host.store)
        notifications = list(conn.notifies(timeout=3, stop_after=1))
    assert len(notifications) == 1 and notifications[0].payload == ""
