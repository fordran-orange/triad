# ruff: noqa: F811
import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.integrations.adapters import (
    CapabilityUnavailable,
    RobinhoodBrokerAdapter,
    SchwabBrokerAdapter,
)
from trading_core.integrations.contracts import IntegrationCandidate
from trading_core.integrations.registry import ExternalIntegrationRegistry
from trading_core.intelligence.records import Records
from trading_core.store import Store

pytestmark = pytest.mark.core


@pytest.mark.parametrize("adapter", [SchwabBrokerAdapter, RobinhoodBrokerAdapter])
def test_broker_shell_never_claims_account_access_or_live_orders(adapter):
    shell = adapter()
    assert not shell.metadata()["configured"] and not shell.health_check()["connected"]
    assert "IMPLEMENTED" not in shell.capabilities().values()
    with pytest.raises(CapabilityUnavailable):
        shell.get_accounts()
    with pytest.raises(CapabilityUnavailable):
        shell.authenticate()
    for method in (shell.place_order, shell.cancel_order, shell.replace_order):
        with pytest.raises(PermissionError):
            method({"symbol": "SPY"})


@pytest.mark.integration
def test_registry_is_generic_idempotent_and_proposals_do_not_install(engine):
    registry = ExternalIntegrationRegistry(engine.host.store)
    registry.seed()
    registry.seed()
    assert len(registry.catalog()) == 2
    assert registry.check("robinhood")["status"] == "NOT_CONFIGURED"
    candidate = IntegrationCandidate(
        provider="Historical source",
        category="HISTORICAL_DATA",
        proposed_by="operator",
        reason="Nonbroker data research",
        capabilities=("HISTORICAL_BARS",),
        documentation=("https://example.org/docs",),
        cost="Unknown",
        limitations=("Not reviewed",),
    )
    identifier = registry.propose(candidate)
    registry.decide(identifier, "RESEARCHING", "Official interface still needs review")
    registry.decide(identifier, "APPROVED_FOR_IMPLEMENTATION", "Reviewed scope: research-only data")
    with pytest.raises(PermissionError):
        registry.decide(identifier, "IMPLEMENTED", "Claimed installation")
    assert len(registry.catalog()) == 2
    assert registry.candidates()[0]["status"] == "APPROVED_FOR_IMPLEMENTATION"
    assert len(registry.records.list("IntegrationCandidate")) == 1
    product = ExternalIntegrationRegistry(Store(engine.host.store.settings, scope="triad"))
    assert len(product.catalog()) == 2 and product.candidates() == []
    with pytest.raises(PermissionError):
        product.seed()
    with pytest.raises(PermissionError):
        product.propose(candidate.model_copy(update={"candidate_id": "forged"}))
    with pytest.raises(PermissionError):
        Records(product.store).append("IntegrationDefinition", {}, owner="triad")
