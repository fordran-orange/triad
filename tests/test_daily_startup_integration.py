# ruff: noqa: F811
"""Real PostgreSQL contention and cross-process wake channel, no provider work."""

import threading
from types import SimpleNamespace as NS

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.store import ConcurrentUpdate

from products.triad import daily_startup, daily_wakeup

pytestmark = pytest.mark.integration


def test_runner_waits_and_monitor_does_not_own_execution(engine):
    store = engine.host.store
    entered = threading.Event()
    waiting = threading.Event()
    outcome = []

    def append(kind, payload, **_):
        if payload.get("state") == "WAITING":
            waiting.set()
            outcome.append(payload)

    service = NS(host=NS(store=store, append=append), ledger=NS(guard=lambda **_: None))

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
