from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest
from trading_core import provider_queue as module
from trading_core.store import ConcurrentUpdate


def test_waits_for_provider_and_never_replays_execution(monkeypatch):
    attempts = []
    releases = []
    guards = []

    @contextmanager
    def lease(key):
        attempts.append(key)
        if len(attempts) == 1:
            raise ConcurrentUpdate("Busy")
        try:
            yield
        finally:
            releases.append(key)

    ledger = NS(store=NS(lease=lease), guard=lambda *a: guards.append(a))
    request = NS(agent_id="CODEX", work_item_id="w", control_epoch=4)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with (
        pytest.raises(ConcurrentUpdate, match="Actual execution failed"),
        module.provider_slot(ledger, request),
    ):
        raise ConcurrentUpdate("Actual execution failed")
    assert attempts == ["provider-execution-CODEX"] * 2
    assert releases == ["provider-execution-CODEX"]
    assert guards == [("CODEX", "w", 4)] * 3


def test_stop_control_interrupts_a_waiting_request(monkeypatch):
    guards = []

    @contextmanager
    def busy(key):
        raise ConcurrentUpdate("Busy")
        yield

    def guard(*args):
        guards.append(args)
        if len(guards) > 1:
            raise PermissionError("Stopped")

    ledger = NS(store=NS(lease=busy), guard=guard)
    request = NS(agent_id="CLAUDE", work_item_id="w", control_epoch=4)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError, match="Stopped"), module.provider_slot(ledger, request):
        pytest.fail("Must not dispatch stopped work")
