"""Dynamic authority, lifetime, quotas and durable delegation tests."""
# ruff: noqa: F811

import time

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.brain import Brain
from trading_core.execution import ExecutionServices
from trading_core.intelligence.agents import AgentBudget, AgentCreationRequest, Agents
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.store import Store
from trading_core.work import ComputeBudget, State, WorkItem

pytestmark = pytest.mark.integration


def setup_agents(engine):
    class ExistingProofs:
        def snapshot(self, transport):
            return {"workitem": {"actual_model": "observed-test-model"}}

    Agents(Records(engine.host.store)).seed_static(ExistingProofs())
    services = ExecutionServices(Store(engine.host.store.settings, scope="triad"))
    parent = services.host.create(
        WorkItem(
            owner="triad",
            title="parent",
            description="bounded task",
            assigned_agent="CODEX",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("docs/improvements",),
            execution_permissions=("read",),
            compute_budget=ComputeBudget(max_output_tokens=2048, timeout_seconds=120),
            reasoning_budget=1024,
        )
    )
    parent, _ = services.start_work(parent)
    manager = Agents(Records(services.host.store))
    return manager, services, parent


def request(parent, **changes):
    data = {
        "requested_by": "CODEX",
        "parent_agent": "CODEX",
        "parent_work_item": parent.work_item_id,
        "proposed_name": "Temporary document QA",
        "purpose": "Inspect bounded documentation",
        "required_capabilities": ("document_analysis",),
        "required_paths": ("docs/improvements",),
        "reason": "One bounded specialist inspection",
    }
    return AgentCreationRequest(**(data | changes))


def child(manager, services, parent, identifier):
    grant = manager.get(identifier)
    work = services.host.create(
        WorkItem(
            owner="triad",
            title="child",
            description="bounded child",
            assigned_agent="CODEX",
            parent_work_item_id=parent.work_item_id,
            mission_id=parent.mission_id,
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("docs/improvements",),
            forbidden_paths=tuple(grant["forbidden_paths"]),
            execution_permissions=("read",),
            reasoning_budget=512,
            compute_budget=ComputeBudget(max_output_tokens=512, timeout_seconds=90),
        )
    )
    manager.bind_work(identifier, work)
    return services.start_work(work)[0]


def test_low_risk_creation_lineage_budget_and_termination(engine):
    manager, services, parent = setup_agents(engine)
    result = manager.request(request(parent))
    assert result["decision"] == "ALLOW"
    identifier = result["agent_id"]
    work = child(manager, services, parent, identifier)
    assert manager.get(identifier)["delegation_depth"] == 1
    assert manager.reserve_run(work.work_item_id, 512) == identifier
    with pytest.raises(PermissionError):
        manager.reserve_run(work.work_item_id, 1)
    manager.release_run(identifier)
    assert manager.get(identifier)["status"] == "TERMINATED"
    with pytest.raises(Stopped):
        services.ledger.guard("CODEX", work.work_item_id)
    graph = Brain(engine.host.store)
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        assert (
            session.run(
                "MATCH (r:AgentCreationRequest)-[:CREATED_AGENT]->(a:ConfiguredAgent {id:$id})-[:DELEGATED_TO]->(w:WorkItem {id:$work}) RETURN count(*) AS n",
                id=engine.host.store.settings.postgres_db + ":agent:" + identifier,
                work=work.work_item_id,
            ).single()["n"]
            == 1
        )
    with pytest.raises(PermissionError):
        Agents(Records(Store(engine.host.store.settings, scope="aegis"))).get(identifier)


@pytest.mark.parametrize(
    "change,rule",
    [
        ({"requested_authority": 2}, "authority_ceiling"),
        ({"required_tools": ("shell",)}, "tool_ceiling"),
        ({"required_paths": ("app/trading_core",)}, "path_ceiling"),
        ({"required_paths": ("../.env",)}, "invalid_path"),
        ({"preferred_provider": "unapproved"}, "provider_binding_requires_separate_governance"),
        (
            {"budget": AgentBudget(max_output_tokens=2048, total_output_tokens=4096)},
            "parent_delegation_pool",
        ),
    ],
)
def test_creation_cannot_mint_authority(engine, change, rule):
    manager, _, parent = setup_agents(engine)
    decision = manager.request(request(parent, **change))
    assert decision["decision"] == "DENY" and rule in decision["rules_triggered"]
    assert not any(a["agent_type"] == "specialist" for a in manager.list())


def test_depth_expiration_and_operator_disable_are_runtime_blocks(engine):
    manager, services, parent = setup_agents(engine)
    identifier = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, identifier)
    nested = manager.request(request(work, requested_by=identifier, parent_agent=identifier))
    assert nested["decision"] == "DENY" and "delegation_depth" in nested["rules_triggered"]
    Agents(Records(engine.host.store)).operate(identifier, "disable")
    with pytest.raises(Stopped):
        services.ledger.guard("CODEX", work.work_item_id)
    second = manager.request(request(parent, lifetime_seconds=1))["agent_id"]
    time.sleep(1.1)
    assert manager.get(second)["status"] == "EXPIRED"
    with pytest.raises(PermissionError):
        child(manager, services, parent, second)


def test_parent_terminal_closes_child_and_persistent_creation_needs_governance(engine):
    manager, services, parent = setup_agents(engine)
    pending = manager.request(request(parent, persistent_or_temporary="persistent"))
    assert pending["decision"] == "REQUIRE_HUMAN_APPROVAL"
    identifier = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, identifier)
    services.host.advance(parent, State.BLOCKED, "parent stopped")
    assert manager.get(identifier)["status"] == "TERMINATED"
    with pytest.raises(Stopped):
        services.ledger.guard("CODEX", work.work_item_id)
    assert any(
        r["kind"] == "AgentCreationRequest" for r in manager.records.list("AgentCreationRequest")
    )
