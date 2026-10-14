"""Independent canonical-cycle probes using disposable evidence and no provider inference."""
# ruff: noqa: F811

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from products.triad.cycle_history import CycleHistory
from products.triad.development import Development
from products.triad.development_api import development, router
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.ledger import Ledger
from trading_core.runtime import ProviderError
from trading_core.store import Store
from trading_core.work import State, WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.triad]


def scoped(engine):
    store = Store(engine.host.store.settings, scope="triad")
    return store, CycleHistory(store), Records(engine.host.store)


def test_historical_failed_inspection_is_terminal_not_in_progress(engine):
    store, history, host = scoped(engine)
    work = store.create(
        WorkItem(
            owner="triad",
            mission_id="failed-inspection",
            title="Inspection",
            description="Disposable historical inspection",
            assigned_agent="CLAUDE",
        )
    )
    work, _ = engine.start_work(work)
    engine.host.advance(
        work, State.FAILED, "Recorded provider failure", failure_reason="DeadlineExceeded"
    )
    host.append(
        "ProductCycle",
        {"mission_id": "failed-inspection", "status": "INSPECTING", "schedule_enabled": False},
        owner="triad",
    )
    row = history.capture("failed-inspection")
    assert row["failures"][0]["code"] == "DeadlineExceeded"
    assert row["status"] in {"FAILED", "BLOCKED"}


def test_recapture_cannot_erase_existing_gate_failure(engine):
    _, history, _ = scoped(engine)
    cycle = history.blocked(
        cycle_id="blocked-gate",
        scheduled=True,
        gate={"status": "BLOCKED", "failed_provider": "CLAUDE", "reason": "Verification expired"},
    )
    original = history.records.list("CycleRecord")[0]
    history.capture(cycle)
    latest = history.list()[0]
    assert latest["status"] == "BLOCKED"
    assert latest["failure_code"] == original["failure_code"]
    assert latest["blocked_at"] == original["blocked_at"]
    assert {k: latest[k] for k in ("provider_gate_result", "scheduled", "created_at")} == {
        k: original[k] for k in ("provider_gate_result", "scheduled", "created_at")
    }
    assert history.records.get(original["id"])["status"] == "BLOCKED"


def test_product_run_preinspection_failure_keeps_known_cycle_identity(engine, monkeypatch):
    store, history, _ = scoped(engine)
    product = Development(store, engine.git)

    def blocked(*args, **kwargs):
        raise ProviderError("UNAVAILABLE", "FixtureGateUnavailable")

    monkeypatch.setattr(product, "_run", blocked)
    with pytest.raises(ProviderError):
        product.run("early-failure")
    row = history.list()[0]
    assert row["status"] == "BLOCKED" and row["failure_code"] == "FixtureGateUnavailable"
    assert (row["cycle_type"], row["execution_mode"]) == ("PRODUCT_BUILD", "REAL")


def test_usage_preserves_canonical_work_link_and_billing(engine):
    store, history, host = scoped(engine)
    work = store.create(
        WorkItem(
            owner="triad",
            mission_id="usage-cycle",
            title="Build",
            description="Bounded usage fixture",
        )
    )
    host.append(
        "ProductCycle", {"mission_id": "usage-cycle", "status": "INSPECTING"}, owner="triad"
    )
    Ledger(store).put(
        "Usage",
        {
            "agent": "CLAUDE",
            "run_id": "native-run",
            "billing_source": "SUBSCRIPTION",
            "usage_known": True,
            "input_tokens": 50,
            "output_tokens": 20,
            "estimated_cost": 0,
        },
        work_id=work.work_item_id,
    )
    host.append(
        "Usage",
        {
            "mission_id": "usage-cycle",
            "agent": "CODEX",
            "billing_source": "API",
            "usage_known": True,
            "estimated_cost": 0.25,
        },
        owner="triad",
    )
    host.append(
        "Usage",
        {
            "mission_id": "usage-cycle",
            "agent": "PRIVATE",
            "billing_source": "API",
            "usage_known": True,
            "estimated_cost": 99,
        },
        owner="aegis",
    )
    row = history.capture("usage-cycle")
    assert row["api_cost"] == 0.25
    assert row["agents_run"] == ["CLAUDE", "CODEX"]
    assert row["subscription_usage"][0].get("work_item_id") == work.work_item_id


def test_get_is_read_only_and_recovery_preserves_source_records(engine):
    store, history, host = scoped(engine)
    cycle = history.blocked(cycle_id="source-failure")
    host.append(
        "Cycle", {"cycle_id": "recovery", "status": "COMPLETED", "mode": "SIMULATED"}, owner="triad"
    )
    history.capture("recovery")
    original = history.records.list("CycleRecord")
    history.link(cycle, "recovery", "recovered_by_cycle_id")
    history.link(cycle, "recovery", "recovered_by_cycle_id")
    assert history.records.list("CycleRecord") == original
    assert len(history.records.list("CycleRelationship")) == 1
    before = host.list("CycleRecord"), host.list("CycleRelationship"), store.list_work(100)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[development] = lambda: SimpleNamespace(
        host=SimpleNamespace(store=store)
    )
    with TestClient(app) as client:
        response = client.get("/triad/api/cycles")
        assert response.status_code == 200
        assert client.get("/triad/cycles").status_code == 200
        assert client.get("/triad/assets/cycles.js").status_code == 200
    assert (
        host.list("CycleRecord"),
        host.list("CycleRelationship"),
        store.list_work(100),
    ) == before
    row = next(r for r in response.json()["cycles"] if r["cycle_id"] == cycle)
    assert row["status"] == "BLOCKED" and row["recovered_by_cycle_id"] == "recovery"


def test_legacy_proposals_are_retained_and_selection_requires_change_link(engine):
    store, history, _ = scoped(engine)
    work = store.create(
        WorkItem(
            owner="triad",
            mission_id="legacy-proposal",
            title="Proposal",
            description="Historical source fixture",
        )
    )
    ledger = Ledger(store)
    ledger.put("Cycle", {"cycle_id": "legacy-proposal", "status": "COMPLETED", "mode": "SIMULATED"})
    ledger.put(
        "Proposal",
        {"proposal_id": "proposal-a", "title": "Historical idea", "decision": "ALLOW"},
        identifier="proposal-a",
        work_id=work.work_item_id,
    )
    unselected = history.capture("legacy-proposal")
    assert unselected["proposals"][0]["proposal_id"] == "proposal-a"
    assert unselected["selected_proposal"] is None
    ledger.put(
        "Change",
        {"proposal_id": "proposal-a", "cycle_id": "legacy-proposal", "status": "MERGED"},
        work_id=work.work_item_id,
    )
    selected = history.capture("legacy-proposal")
    assert selected["selected_proposal"]["proposal_id"] == "proposal-a"
    assert selected["selected_proposal"]["work_item_id"] == work.work_item_id
    records = len(history.records.list("CycleRecord"))
    history.capture("legacy-proposal")
    assert len(history.records.list("CycleRecord")) == records


@pytest.mark.parametrize("terminal", [State.CANCELLED, State.REJECTED])
def test_terminal_product_work_does_not_become_active_history(engine, terminal):
    store, history, host = scoped(engine)
    work = store.create(
        WorkItem(
            owner="triad",
            mission_id="terminal-work",
            title="Build",
            description="Terminal lifecycle fixture",
            assigned_agent="CLAUDE",
        )
    )
    work, _ = engine.start_work(work)
    if terminal == State.CANCELLED:
        work = engine.host.advance(work, State.BLOCKED, "Fixture halted before cancellation")
    if terminal == State.REJECTED:
        work = engine.host.advance(work, State.AWAITING_REVIEW, "Fixture awaiting separate review")
    engine.host.advance(work, terminal, "Recorded terminal outcome")
    host.append(
        "ProductCycle", {"mission_id": "terminal-work", "status": "INSPECTING"}, owner="triad"
    )
    if terminal == State.REJECTED:
        host.append(
            "ProductQA",
            {
                "mission_id": "terminal-work",
                "decision": "FAIL",
                "findings": ["Recorded independent rejection"],
            },
            owner="triad",
        )
    row = history.capture("terminal-work")
    assert row["status"] in {"CANCELLED", "REJECTED", "FAILED", "BLOCKED"}
    terminal_work = store.get(work.work_item_id)
    assert terminal_work.completed_at is not None
    assert row["finished_at"] == terminal_work.model_dump(mode="json")["completed_at"]
