"""Independent adversarial QA for Day 6 B; disposable databases only."""

# ruff: noqa: F811
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_agents import child, request, setup_agents
from test_intelligence_capabilities import build, qa
from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.intelligence.agents import AgentBudget, Agents
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.store import ConcurrentUpdate
from trading_core.work import ComputeBudget, WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.core]


def test_disabled_provider_cannot_create_specialist(engine):
    manager, _, parent = setup_agents(engine)
    engine.ledger.operate("disable", agent="CODEX")
    with pytest.raises((Stopped, PermissionError)):
        manager.request(request(parent))


def test_forged_empty_promotion_proposal_cannot_skip_value_evidence(engine):
    manager, _, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    proposal = manager.records.append(
        "AgentPromotionRequest",
        {
            "agent_id": agent,
            "evidence": [],
            "reason": "Forged count bypass",
            "status": "REQUIRE_HUMAN_APPROVAL",
        },
        owner="triad",
    )
    host = Records(engine.host.store)
    implementation = build(host, ("promotion:" + proposal,))
    Quality(host).review(qa(implementation))
    with pytest.raises(PermissionError):
        Agents(host).promote(proposal, implementation.implementation_run_id, "revision-a")


def test_promotion_cannot_ignore_global_kill(engine):
    manager, _, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    host = Records(engine.host.store)
    value_evidence = []
    for _ in range(2):
        value = build(host, ("fixture value",), owner="triad")
        # Trusted host evidence faithfully names its actual specialist builder.
        from trading_core.intelligence.contracts import ImplementationRun

        specialist_value = ImplementationRun.model_validate(
            value.model_dump()
            | {
                "implementation_run_id": value.implementation_run_id + "-specialist",
                "builder": agent,
            }
        )
        Quality(host).implementation(specialist_value)
        Quality(host).review(qa(specialist_value))
        value_evidence.append(specialist_value.implementation_run_id)
    proposal = manager.propose_promotion(agent, value_evidence, "Repeated useful work")
    implementation = build(host, ("promotion:" + proposal,))
    Quality(host).review(qa(implementation))
    engine.ledger.operate("kill")
    with pytest.raises((Stopped, PermissionError)):
        Agents(host).promote(proposal, implementation.implementation_run_id, "revision-a")


def test_run_reservation_is_atomic(engine):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, agent)
    barrier = threading.Barrier(2)

    def reserve():
        barrier.wait(timeout=10)
        try:
            return manager.reserve_run(work.work_item_id, 512)
        except (PermissionError, ConcurrentUpdate):
            return "DENIED"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert results.count(agent) == 1 and results.count("DENIED") == 1
    assert manager.get(agent)["active_runs"] == 1
    manager.release_run(agent)


def test_releasing_a_run_cannot_undo_concurrent_operator_disable(engine, monkeypatch):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(
        request(parent, budget=AgentBudget(total_output_tokens=1024, max_runs=2))
    )["agent_id"]
    work = child(manager, services, parent, agent)
    manager.reserve_run(work.work_item_id, 512)
    read_finished, proceed = threading.Event(), threading.Event()
    original_get = manager.get

    def paused_get(identifier, **kwargs):
        value = original_get(identifier, **kwargs)
        read_finished.set()
        assert proceed.wait(timeout=15)
        return value

    monkeypatch.setattr(manager, "get", paused_get)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(manager.release_run, agent)
        assert read_finished.wait(timeout=15)
        Agents(Records(engine.host.store)).operate(agent, "disable")
        proceed.set()
        pending.result(timeout=15)
    assert original_get(agent)["status"] == "DISABLED"


class BoundedFakeAdapter:
    provider = "fixture"
    model = "fixture"

    def __init__(self, delay=0):
        self.delay = delay

    def estimate_cost(self, *_):
        return 0

    def provider_metadata(self):
        return {"provider": "fixture", "model": "fixture"}

    def execute(self, request):
        time.sleep(self.delay)
        return (
            AgentRunResult(
                run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Fixture completed"
            ),
            1,
            1,
        )


def runtime_request(services, work, role="PROPOSE", **updates):
    policy = services.host.store.records("PolicyDecision", work.work_item_id)[0]
    return AgentRunRequest(
        agent_id="CODEX",
        work_item_id=work.work_item_id,
        mission_id=work.mission_id,
        context_packet={},
        role=role,
        objective="Bounded fixture",
        allowed_paths=work.allowed_paths,
        acceptance_criteria=work.acceptance_criteria,
        token_budget=512,
        reasoning_budget=512,
        policy_decision=policy,
        required_output_schema=AgentRunResult.model_json_schema(),
        control_epoch=services.ledger.get("authority-" + work.work_item_id)["epoch"],
        **updates,
    )


def test_runtime_cannot_add_tools_to_read_only_specialist(engine):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, agent)
    envelope = runtime_request(services, work, allowed_tools=("propose_file_change",))
    with pytest.raises(PermissionError):
        services.runtime.execute(envelope, mode="SIMULATED", adapter=BoundedFakeAdapter())


def test_runtime_honors_child_timeout_not_global_timeout(engine):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent, budget=AgentBudget(timeout_seconds=1)))["agent_id"]
    grant = manager.get(agent)
    work = services.host.create(
        WorkItem(
            owner="triad",
            title="bounded timer",
            description="timeout fixture",
            assigned_agent="CODEX",
            parent_work_item_id=parent.work_item_id,
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("docs/improvements",),
            forbidden_paths=tuple(grant["forbidden_paths"]),
            execution_permissions=("read",),
            reasoning_budget=512,
            compute_budget=ComputeBudget(max_output_tokens=512, timeout_seconds=1),
        )
    )
    manager.bind_work(agent, work)
    work = services.start_work(work)[0]
    envelope = runtime_request(
        services, work, role="SUPPORT", allowed_tools=(), execution_permissions=("read",)
    )
    started = time.monotonic()
    with pytest.raises(ResourceBlocked) as blocked:
        services.runtime.execute(envelope, mode="SIMULATED", adapter=BoundedFakeAdapter(delay=1.4))
    assert blocked.value.status == "BLOCKED_RESOURCE_LIMIT"
    assert blocked.value.decision["resource_type"] == ResourceType.TIME
    assert blocked.value.decision["granted_amount"] == 0
    assert time.monotonic() - started < 10
    allocations = [
        row for row in Records(services.ledger.store).list("ResourceAllocation")
        if row["run_id"] == envelope.run_id
    ]
    assert allocations[0]["allocations"][ResourceType.TIME] == 1
    assert not any(
        row.get("status") == "SUCCESS" and row["run_id"] == envelope.run_id
        for row in services.ledger.records("Usage")
    )


def test_runtime_honors_zero_cost_specialist_grant(engine):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, agent)
    assert manager.get(agent)["budget"]["max_cost_usd"] == 0
    # Disposable database only: the child ceiling must be enforced independently
    # of this host's current zero-dollar default. No real adapter is invoked.
    with engine.host.store.connect() as conn:
        conn.execute(
            "UPDATE core.autonomy_control SET payload=jsonb_set(payload,'{limits,max_cloud_cost_day}','1'::jsonb) WHERE id=1"
        )
    envelope = runtime_request(
        services, work, role="SUPPORT", allowed_tools=(), execution_permissions=("read",)
    )

    class PaidAdapter(BoundedFakeAdapter):
        def estimate_cost(self, *_):
            return 0.01

    with pytest.raises(PermissionError):
        services.runtime.execute(envelope, mode="SIMULATED", adapter=PaidAdapter())


def reviewed_promotion(engine, manager, agent, evidence_owner="triad"):
    from trading_core.intelligence.contracts import ImplementationRun

    host = Records(engine.host.store)
    evidence = []
    for _ in range(2):
        prototype = build(host, ("fixture usefulness",), owner=evidence_owner)
        value = ImplementationRun.model_validate(
            prototype.model_dump()
            | {
                "implementation_run_id": prototype.implementation_run_id + "-value",
                "builder": agent,
            }
        )
        Quality(host).implementation(value)
        Quality(host).review(qa(value))
        evidence.append(value.implementation_run_id)
    proposal = manager.propose_promotion(agent, evidence, "Useful specialist")
    governance = build(host, ("promotion:" + proposal,))
    Quality(host).review(qa(governance))
    return Agents(host), proposal, governance


def test_promotion_positive_path_preserves_grant_and_owner(engine):
    manager, _, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    host, proposal, governance = reviewed_promotion(engine, manager, agent)
    promoted = host.promote(proposal, governance.implementation_run_id, governance.change_commit)
    assert promoted.persistent_or_temporary == "persistent"
    assert promoted.expires_at is None
    assert promoted.agent_id != agent
    assert host.get(promoted.agent_id)["owner"] == "triad"
    assert promoted.budget.model_dump() == manager.get(agent)["budget"]
    assert promoted.allowed_tools == tuple(manager.get(agent)["allowed_tools"])
    with pytest.raises(PermissionError):
        host.promote(proposal, governance.implementation_run_id, governance.change_commit)


@pytest.mark.parametrize(
    "block", ["foreign_evidence", "product_pause", "provider_disable", "ceiling"]
)
def test_promotion_rechecks_current_governance(engine, block):
    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    host, proposal, governance = reviewed_promotion(
        engine, manager, agent, evidence_owner="aegis" if block == "foreign_evidence" else "triad"
    )
    if block == "product_pause":
        services.ledger.operate("pause")
    elif block == "provider_disable":
        engine.ledger.operate("disable", agent="CODEX")
    elif block == "ceiling":
        host.policy = host.policy.model_copy(update={"max_total_active_specialists": 1})
    with pytest.raises((Stopped, PermissionError)):
        host.promote(proposal, governance.implementation_run_id, governance.change_commit)


def test_legacy_product_records_cannot_forge_configured_agent_truth(engine):
    from trading_core.brain import Brain
    from trading_core.ledger import Ledger
    from trading_core.store import Store

    manager, _, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    malicious = Ledger(Store(engine.host.store.settings, scope="aegis"))
    try:
        malicious.put(
            "AgentDefinition",
            {
                "agent_id": agent,
                "display_name": "forged other-product identity",
                "status": "ACTIVE",
                "provider": "forged",
                "model": "forged",
            },
        )
    except PermissionError:
        return
    graph = Brain(engine.host.store)
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        row = session.run(
            "MATCH (a:ConfiguredAgent {id:$id}) RETURN a.owner AS owner,a.provider AS provider",
            id=engine.host.store.settings.postgres_db + ":agent:" + agent,
        ).single()
        assert row["owner"] == "triad" and row["provider"] != "forged"


def test_all_reserved_intelligence_kinds_reject_both_product_writers(engine):
    from trading_core.intelligence.contracts import HOST_RECORD_KINDS
    from trading_core.ledger import Ledger
    from trading_core.store import Store

    private = Store(engine.host.store.settings, scope="triad")
    for kind in HOST_RECORD_KINDS:
        with pytest.raises(PermissionError):
            Records(private).append(kind, {"fixture": True}, owner="triad")
        with pytest.raises(PermissionError):
            Ledger(private).put(kind, {"fixture": True})


def test_canonical_intelligence_overrides_tampered_legacy_mirror(engine):
    from trading_core.brain import Brain

    manager, _, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    original = manager.get(agent)
    engine.ledger.put(
        "AgentDefinition",
        {
            "agent_id": agent,
            "display_name": "forged legacy mirror",
            "status": "ACTIVE",
            "provider": "forged",
            "model": "forged",
        },
        identifier=agent,
        work_id=parent.work_item_id,
    )
    graph = Brain(engine.host.store)
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        row = session.run(
            "MATCH (a:ConfiguredAgent {id:$id}) RETURN a.display_name AS name,a.provider AS provider",
            id=engine.host.store.settings.postgres_db + ":agent:" + agent,
        ).single()
        assert row["name"] == original["display_name"]
        assert row["provider"] == original["provider"]


def test_success_records_specialist_identity_and_correct_parent_lineage(engine):
    from trading_core.brain import Brain

    manager, services, parent = setup_agents(engine)
    agent = manager.request(request(parent))["agent_id"]
    work = child(manager, services, parent, agent)
    envelope = runtime_request(
        services, work, role="SUPPORT", allowed_tools=(), execution_permissions=("read",)
    )
    result = services.runtime.execute(envelope, mode="SIMULATED", adapter=BoundedFakeAdapter())
    assert result.summary == "Fixture completed"
    usage = services.ledger.records("Usage")[0]
    assert usage["configured_agent"] == agent and usage["agent"] == "CODEX"
    graph = Brain(engine.host.store)
    assert graph.flush()["error"] is None
    with graph.driver() as driver, driver.session() as session:
        assert (
            session.run(
                "MATCH (:WorkItem {id:$child})-[:DERIVED_FROM]->(:WorkItem {id:$parent}) RETURN count(*) AS n",
                child=work.work_item_id,
                parent=parent.work_item_id,
            ).single()["n"]
            == 1
        )
        assert (
            session.run(
                "MATCH (:WorkItem {id:$parent})-[:DERIVED_FROM]->(:WorkItem {id:$child}) RETURN count(*) AS n",
                child=work.work_item_id,
                parent=parent.work_item_id,
            ).single()["n"]
            == 0
        )


def test_unscoped_host_dispatch_enforces_product_pause(engine):
    _, services, parent = setup_agents(engine)
    services.ledger.operate("pause")
    with pytest.raises(Stopped):
        engine.ledger.guard("CODEX", parent.work_item_id)
