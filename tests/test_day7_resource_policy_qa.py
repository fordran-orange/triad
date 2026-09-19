"""Independent resource-policy authority and durable-denial probes; disposable DB."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from test_resource_policy import session
from trading_core.intelligence.records import Records
from trading_core.ledger import Ledger
from trading_core.resource_policy import (
    DEFAULT_ALLOCATIONS,
    ResourceBlocked,
    ResourceSession,
    ResourceType,
)
from trading_core.store import Store
from trading_core.work import uid

pytestmark = pytest.mark.integration


def test_product_scoped_service_cannot_mint_resource_truth(engine):
    run = session(engine)
    scoped = Ledger(Store(run.ledger.store.settings, scope=run.work.owner))
    request = run.request.model_copy(update={"run_id": uid()})
    with pytest.raises(PermissionError, match="Core|host|trusted"):
        forged = ResourceSession(
            scoped, request, DEFAULT_ALLOCATIONS, billing_source="SUBSCRIPTION", day=engine.day
        )
        forged.observe("authorized_read", "caller-claimed-operation-without-host-evidence")
        forged.ensure(ResourceType.TOOLS, 61)


def test_existing_budget_denial_is_durable_and_terminal(engine):
    run = session(engine)
    run.observe("test_result", "new-host-test-result")
    with run.ledger.store.connect() as conn:
        conn.execute(
            "UPDATE core.autonomy_control SET payload=jsonb_set(jsonb_set(payload,'{daily_execution_caps,SUBSCRIPTION}','true'::jsonb),'{limits,max_tokens_day}','0'::jsonb) WHERE id=1"
        )
    before = len(run.ledger.records("BudgetReservation"))
    with pytest.raises(ResourceBlocked) as failure:
        run.ensure(ResourceType.OUTPUT, 6145)
    assert failure.value.decision["decision"] == "DENY"
    assert failure.value.decision["granted_amount"] == 0
    assert len(run.ledger.records("BudgetReservation")) == before
    records = Records(Store(run.ledger.store.settings))
    decisions = [
        r for r in records.list("ResourceExtensionDecision") if r["run_id"] == run.request.run_id
    ]
    assert len(decisions) == 1 and decisions[0]["decision"] == "DENY"
    run.observe("test_result", "another-valid-test")
    with pytest.raises(ResourceBlocked):
        run.ensure(ResourceType.TIME, 1)
    assert (
        len(
            [
                r
                for r in records.list("ResourceExtensionDecision")
                if r["run_id"] == run.request.run_id
            ]
        )
        == 1
    )


def test_oversized_request_persists_human_review_without_allocation(engine):
    run = session(engine)
    run.observe("valid_proposal", "new-validated-proposal")
    with pytest.raises(ResourceBlocked) as failure:
        run.ensure(ResourceType.TIME, 961)
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"
    assert run.allocation(ResourceType.TIME) == 480
    assert len(run.host.list("ResourceExtensionRequest")) == 1
    assert len(run.host.list("ResourceExtensionDecision")) == 1


def test_all_resource_truth_kinds_reject_scoped_record_paths(engine):
    run = session(engine)
    store = Store(run.ledger.store.settings, scope=run.work.owner)
    for kind in (
        "ResourceAllocation",
        "ResourceProgress",
        "ResourceExtensionRequest",
        "ResourceExtensionDecision",
        "ResourceRunState",
    ):
        with pytest.raises(PermissionError):
            Records(store).append(kind, {"run_id": run.request.run_id}, owner=run.work.owner)
        with pytest.raises(PermissionError):
            Ledger(store).put(kind, {"run_id": run.request.run_id})
