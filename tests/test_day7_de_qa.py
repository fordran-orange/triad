"""Independent D/E adversarial checks; disposable persistence, no provider network."""

# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.execution import ExecutionServices
from trading_core.integrations.adapters import (
    CapabilityUnavailable,
    RobinhoodBrokerAdapter,
    SchwabBrokerAdapter,
)
from trading_core.integrations.contracts import IntegrationCandidate, IntegrationRecord
from trading_core.integrations.registry import ExternalIntegrationRegistry
from trading_core.intelligence.quality import Quality
from trading_core.store import Store
from trading_core.work import WorkItem


def candidate(**values):
    return IntegrationCandidate(
        **(
            {
                "provider": "Synthetic provider",
                "category": "HISTORICAL_DATA",
                "proposed_by": "operator",
                "reason": "Bounded data research",
                "capabilities": ("HISTORICAL_BARS",),
                "documentation": ("https://example.invalid/docs",),
                "cost": "Unknown",
                "limitations": ("Not connected",),
            }
            | values
        )
    )


def definition(**values):
    return IntegrationRecord(
        **(
            {
                "integration_id": "fixture-vendor",
                "name": "Fixture",
                "provider": "Synthetic provider",
                "category": "HISTORICAL_DATA",
                "capabilities": {"HISTORICAL_BARS": "IMPLEMENTED"},
                "authentication_type": "not configured",
            }
            | values
        )
    )


def approve(registry):
    identifier = registry.propose(candidate())
    registry.decide(identifier, "RESEARCHING", "Scope reviewed")
    registry.decide(
        identifier, "APPROVED_FOR_IMPLEMENTATION", "Research-only implementation approved"
    )
    return identifier


@pytest.mark.integration
def test_unrelated_qa_cannot_mark_integration_implemented(engine):
    registry = ExternalIntegrationRegistry(engine.host.store)
    identifier = approve(registry)
    registry.host.append(
        "IntegrationDefinition", definition().model_dump(mode="json"), owner="core"
    )
    unrelated = build(registry.host, ("Unrelated UI typography change",), owner="triad")
    Quality(registry.host).review(qa(unrelated))
    with pytest.raises(PermissionError):
        registry.mark_implemented(
            identifier, "fixture-vendor", unrelated.implementation_run_id, unrelated.change_commit
        )


@pytest.mark.integration
def test_different_capability_cannot_complete_candidate(engine):
    registry = ExternalIntegrationRegistry(engine.host.store)
    identifier = approve(registry)
    registry.host.append(
        "IntegrationDefinition",
        definition(
            capabilities={"ACCOUNT_READ": "IMPLEMENTED", "HISTORICAL_BARS": "UNAVAILABLE"}
        ).model_dump(mode="json"),
        owner="core",
    )
    reviewed = build(registry.host, ("Unrelated account-read adapter",))
    Quality(registry.host).review(qa(reviewed))
    with pytest.raises(PermissionError):
        registry.mark_implemented(
            identifier, "fixture-vendor", reviewed.implementation_run_id, reviewed.change_commit
        )


@pytest.mark.integration
def test_shared_catalog_never_exposes_credential_shaped_metadata(engine):
    registry = ExternalIntegrationRegistry(engine.host.store)
    marker = "synthetic-qa-credential-never-real"
    try:
        value = definition(
            endpoint="https://fixture-user:" + marker + "@example.invalid/data?api_key=" + marker,
            transports=({"transport": "REST", "api_key": marker},),
        )
        registry.host.append("IntegrationDefinition", value.model_dump(mode="json"), owner="core")
    except (ValueError, PermissionError):
        return
    product = ExternalIntegrationRegistry(Store(engine.host.store.settings, scope="triad"))
    assert marker not in str(product.catalog()), (
        "credential-shaped metadata escaped into product-shared catalog"
    )


@pytest.mark.integration
def test_product_candidate_owner_identity_lifecycle_and_reserved_writers(engine):
    from psycopg.errors import RaiseException

    services = ExecutionServices(Store(engine.host.store.settings, scope="triad"))
    work = services.host.create(
        WorkItem(
            owner="triad",
            title="Data candidate research",
            description="Bounded metadata investigation",
            assigned_agent="CODEX",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("docs",),
            execution_permissions=("read",),
        )
    )
    work, _ = services.start_work(work)
    triad = ExternalIntegrationRegistry(services.host.store)
    aegis = ExternalIntegrationRegistry(Store(engine.host.store.settings, scope="aegis"))
    host = ExternalIntegrationRegistry(engine.host.store)
    identifier = triad.propose(candidate(proposed_by="CODEX"), work_id=work.work_item_id)
    assert len(triad.candidates()) == 1 and aegis.candidates() == []
    with pytest.raises(PermissionError):
        aegis.propose(candidate(proposed_by="CODEX"), work_id=work.work_item_id)
    with pytest.raises(PermissionError):
        triad.propose(candidate(proposed_by="GROK"), work_id=work.work_item_id)
    with pytest.raises(PermissionError):
        triad.propose(
            candidate(proposed_by="CODEX", status="IMPLEMENTED"), work_id=work.work_item_id
        )
    with pytest.raises(PermissionError):
        triad.decide(identifier, "RESEARCHING", "Self approval")
    host.decide(identifier, "RESEARCHING", "Operator review")
    assert triad.candidates()[0]["status"] == "RESEARCHING" and aegis.candidates() == []
    for kind in (
        "IntegrationDefinition",
        "IntegrationConnection",
        "IntegrationCandidate",
        "IntegrationCandidateDecision",
        "IntegrationUseRequest",
        "DataAcquisition",
    ):
        with pytest.raises(PermissionError):
            triad.records.append(kind, {}, owner="triad")
        with pytest.raises(PermissionError):
            triad.records.ledger.put(kind, {})
    host.seed()
    use = triad.request_use("schwab", "ORDER_PLACE", work_id=work.work_item_id)
    assert triad.records.get(use)["decision"] == "DENY"
    with pytest.raises(PermissionError):
        aegis.records.get(use)
    with pytest.raises(RaiseException), engine.host.store.connect() as connection:
        connection.execute(
            "UPDATE core.intelligence_records SET payload='{}'::jsonb WHERE id=%s", (identifier,)
        )


@pytest.mark.integration
def test_concurrent_decisions_do_not_duplicate_transition(engine):
    registry = ExternalIntegrationRegistry(engine.host.store)
    identifier = registry.propose(candidate())
    barrier = Barrier(2)

    def decide():
        barrier.wait(timeout=5)
        try:
            registry.decide(identifier, "RESEARCHING", "Independent metadata review")
            return True
        except (ValueError, RuntimeError):
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: decide(), range(2)))
    assert sum(results) == 1
    assert len(registry.records.list("IntegrationCandidateDecision")) == 1


@pytest.mark.parametrize("factory", [SchwabBrokerAdapter, RobinhoodBrokerAdapter])
def test_all_shell_operations_fail_closed_even_if_metadata_overclaims(factory, monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "create_connection", lambda *a, **k: pytest.fail("Shell attempted network access")
    )
    shell = factory()
    shell.definition = shell.definition.model_copy(
        update={
            "enabled": True,
            "configured": True,
            "capabilities": {k: "IMPLEMENTED" for k in shell.capabilities()},
        }
    )
    assert shell.health_check()["connected"] is False
    for function, args in [
        (shell.get_accounts, ()),
        (shell.get_balances, ("fixture",)),
        (shell.get_positions, ("fixture",)),
        (shell.get_orders, ("fixture",)),
        (shell.get_order, ("fixture", "order")),
        (shell.get_quotes, (("SPY",),)),
        (shell.stream_events, ()),
        (shell.authenticate, ()),
        (shell.disconnect, ()),
    ]:
        with pytest.raises(CapabilityUnavailable):
            function(*args)
    for method in (shell.place_order, shell.cancel_order, shell.replace_order):
        with pytest.raises(PermissionError):
            method({"symbol": "SPY"})
