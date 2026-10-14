# ruff: noqa: F811
"""Real control-plane persistence, concurrency and authority checks."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from test_day3_integration import active, engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.resource_policy import (
    DEFAULT_ALLOCATIONS,
    ResourceBlocked,
    ResourceSession,
    ResourceType,
)
from trading_core.store import Store

pytestmark = [pytest.mark.integration, pytest.mark.core]


def session(engine, billing="SUBSCRIPTION"):
    work, policy = active(engine)
    request = engine.request(work, policy, "IMPLEMENT", {})
    return ResourceSession(
        engine.ledger, request, DEFAULT_ALLOCATIONS, billing_source=billing, day=engine.day
    )


@pytest.mark.parametrize("resource", list(ResourceType))
def test_progress_extends_each_resource_with_durable_states(engine, resource):
    run = session(engine)
    original = run.work.model_dump()
    run.observe("authorized_read", "docs/one.md:actualsha256")
    assert (
        run.ensure(resource, DEFAULT_ALLOCATIONS[resource] + 1) == DEFAULT_ALLOCATIONS[resource] * 2
    )
    assert run.allocation(resource) == DEFAULT_ALLOCATIONS[resource] * 2
    rows = run.host.list("ResourceRunState")
    assert {r["status"] for r in rows} == {
        "RESOURCE_THRESHOLD_REACHED",
        "EXTENSION_REQUESTED",
        "RUNNING_EXTENDED",
    }
    assert run.ledger.store.get(run.work.work_item_id).model_dump() == original
    assert run.host.list("ResourceExtensionDecision")[-1]["decision"] == "ALLOW"


def test_repeated_evidence_cannot_extend_and_block_is_terminal(engine):
    run = session(engine)
    assert run.observe("authorized_read", "one")
    assert run.observe("authorized_read", "one") is None
    run.ensure(ResourceType.TOOLS, 61)
    with pytest.raises(ResourceBlocked) as failure:
        run.ensure(ResourceType.TOOLS, 121)
    assert failure.value.decision["decision"] == "DENY"
    run.observe("authorized_read", "two")
    with pytest.raises(ResourceBlocked):
        run.ensure(ResourceType.TOOLS, 121)
    assert len(run.host.list("ResourceExtensionDecision")) == 2
    assert (
        max(run.host.list("ResourceRunState"), key=lambda r: r["observed_at"])["status"]
        == "BLOCKED_RESOURCE_LIMIT"
    )


@pytest.mark.parametrize("billing", ["API", "UNKNOWN"])
def test_cost_unapproved_extensions_require_human(engine, billing):
    run = session(engine, billing)
    run.observe("authorized_read", "new")
    with pytest.raises(ResourceBlocked) as failure:
        run.ensure(ResourceType.TIME, 481)
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"
    assert failure.value.decision["granted_amount"] == 0


def test_extensions_are_finite_even_with_fresh_progress(engine):
    run = session(engine)
    for number in range(8):
        run.observe("valid_proposal", f"validated-diff-{number}")
        run.ensure(ResourceType.TOOLS, 61 + number * 60)
    run.observe("valid_proposal", "validated-diff-9")
    with pytest.raises(ResourceBlocked) as failure:
        run.ensure(ResourceType.TOOLS, 541)
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"


def test_concurrent_thresholds_cannot_double_grant(engine):
    run = session(engine)
    run.observe("authorized_read", "one")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run.ensure(ResourceType.TOOLS, 61), range(2)))
    assert results == [120, 120]
    assert len(run.host.list("ResourceExtensionDecision")) == 1


def test_kill_and_product_forgery_and_restart_are_rejected(engine):
    run = session(engine)
    forged = Records(Store(run.ledger.store.settings, scope="triad"))
    for kind in (
        "ResourceProgress",
        "ResourceAllocation",
        "ResourceExtensionDecision",
        "ResourceRunState",
    ):
        with pytest.raises(PermissionError):
            forged.append(kind, {"run_id": run.request.run_id}, owner="triad")
    with pytest.raises(PermissionError, match="cannot reset"):
        ResourceSession(engine.ledger, run.request, DEFAULT_ALLOCATIONS, billing_source="LOCAL")
    run.observe("authorized_read", "one")
    engine.ledger.operate("kill")
    with pytest.raises(Stopped):
        run.ensure(ResourceType.TIME, 481)
    assert not run.host.list("ResourceExtensionDecision")
