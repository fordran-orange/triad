"""Independent Core C acceptance probes; no live provider inference."""

# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_day3_integration import engine  # noqa: F401
from test_intelligence_agents import child, request, setup_agents
from test_intelligence_capabilities import build, qa
from test_intelligence_routing import requirements, setup_routing, work
from trading_core.brain import Brain
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records

pytestmark = pytest.mark.integration


def test_two_database_configured_agents_and_all_lineage_stay_separate(engine, tmp_path):
    second_path = tmp_path / "second"
    second_path.mkdir()
    generator = globals()["engine"].__wrapped__(second_path)
    other = next(generator)
    try:
        scenarios = []
        for fixture in (engine, other):
            manager, services, parent = setup_agents(fixture)
            identifier = manager.request(request(parent))["agent_id"]
            assignment = child(manager, services, parent, identifier)
            host = Records(fixture.host.store)
            implementation = build(host)
            Quality(host).review(qa(implementation))
            graph = Brain(fixture.host.store)
            assert graph.flush()["error"] is None
            scenarios.append((manager, parent, identifier, assignment, implementation, graph))
        Agents(Records(engine.host.store)).operate("CODEX", "disable")
        assert scenarios[0][-1].flush()["error"] is None
        with scenarios[0][-1].driver() as driver, driver.session() as session:
            for i, fixture in enumerate((engine, other)):
                manager, parent, identifier, assignment, implementation, _ = scenarios[i]
                prefix = fixture.host.store.settings.postgres_db + ":agent:"
                assert session.run(
                    "MATCH (a:ConfiguredAgent {id:$id}) RETURN a.status AS status",
                    id=prefix + "CODEX",
                ).single()["status"] == ("DISABLED" if i == 0 else "ACTIVE")
                assert (
                    session.run(
                        "MATCH (a:ConfiguredAgent {id:$id})-[:REQUESTED]->(r:AgentCreationRequest)-[:CREATED_AGENT]->(b:ConfiguredAgent {id:$child})-[:DELEGATED_TO]->(w:WorkItem {id:$work}) RETURN count(*) AS n",
                        id=prefix + "CODEX",
                        child=prefix + identifier,
                        work=assignment.work_item_id,
                    ).single()["n"]
                    == 1
                )
                assert (
                    session.run(
                        "MATCH (a:ConfiguredAgent)-[:PERFORMED]->(r:ImplementationRun {id:$id}) RETURN a.id AS id",
                        id=implementation.implementation_run_id,
                    ).single()["id"]
                    == prefix + implementation.builder
                )
                assert (
                    session.run(
                        "MATCH (:ImplementationRun {id:$id})-[:VERIFIED_BY]->(q:QARun)<-[:PERFORMED]-(a:ConfiguredAgent) RETURN a.id AS id",
                        id=implementation.implementation_run_id,
                    )
                    .single()["id"]
                    .startswith(prefix)
                )
            ids = [s[1].work_item_id for s in scenarios]
            assert (
                session.run(
                    "MATCH (a:ConfiguredAgent)-[:REQUESTED]->(r:AgentCreationRequest)<-[:REQUESTED]-(w:WorkItem) WHERE w.id IN $ids AND NOT a.id STARTS WITH $prefix AND w.id=$first RETURN count(*) AS n",
                    ids=ids,
                    prefix=engine.host.store.settings.postgres_db + ":agent:",
                    first=ids[0],
                ).single()["n"]
                == 0
            )
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


def test_routed_dispatch_rechecks_latest_capability_revocation(engine):
    router, host = setup_routing(engine)
    assignment = router.create(work(), requirements())
    existing = next(
        v
        for v in Capabilities(host).current()
        if v["capability"]["transport"] == "codex_cli"
        and v["capability"]["capability"] == "document_analysis"
    )
    cap = Capability.model_validate(
        existing["capability"] | {"verification_status": "DEGRADED", "status": "RESTRICTED"}
    )
    proposal = Capabilities(host).propose(cap, actor="operator")
    implementation = build(host, ("capability:" + host.get(proposal)["digest"],))
    Quality(host).review(qa(implementation))
    Capabilities(host).approve(
        proposal, implementation.implementation_run_id, implementation.change_commit
    )
    with pytest.raises(PermissionError, match="no longer eligible"):
        router.validate_execution(
            SimpleNamespace(work_item_id=assignment.work_item_id, role="REVIEW", agent_id="CODEX"),
            SimpleNamespace(transport_id="codex_cli"),
        )


def test_semantically_same_new_id_revocation_cannot_leave_verified_route(engine):
    router, host = setup_routing(engine)
    existing = next(
        v
        for v in Capabilities(host).current()
        if v["capability"]["transport"] == "codex_cli"
        and v["capability"]["capability"] == "document_analysis"
    )
    cap = Capability.model_validate(
        existing["capability"]
        | {
            "capability_id": "operator-new-id-revocation",
            "verification_status": "DEGRADED",
            "status": "RESTRICTED",
        }
    )
    proposal = Capabilities(host).propose(cap, actor="operator")
    implementation = build(host, ("capability:" + host.get(proposal)["digest"],))
    Quality(host).review(qa(implementation))
    Capabilities(host).approve(
        proposal, implementation.implementation_run_id, implementation.change_commit
    )
    with pytest.raises(PermissionError):
        router.create(work(), requirements())


def test_codex_read_only_transport_cannot_route_support_role(engine):
    router, _ = setup_routing(engine)
    with pytest.raises(PermissionError):
        router.create(work(work_type="documentation_audit"), requirements(role="SUPPORT"))


@pytest.mark.parametrize("field,value", [("role", "IMPLEMENT"), ("agent_id", "CLAUDE")])
def test_routed_dispatch_rejects_role_and_executor_substitution(engine, field, value):
    router, _ = setup_routing(engine)
    assignment = router.create(work(), requirements())
    values = {"work_item_id": assignment.work_item_id, "role": "REVIEW", "agent_id": "CODEX"}
    values[field] = value
    with pytest.raises(PermissionError, match="governed capability route"):
        router.validate_execution(
            SimpleNamespace(**values), SimpleNamespace(transport_id="codex_cli")
        )


def test_core_intelligence_auth_assets_and_no_self_adoption(engine):
    from trading_core.api import app, service

    _, host = setup_routing(engine)
    app.dependency_overrides[service] = lambda: engine.host
    try:
        client = TestClient(app)
        for path in (
            "/core/intelligence",
            "/assets/intelligence.js",
            "/assets/record-view.js",
            "/assets/record-view.css",
        ):
            assert client.get(path).status_code == 200
        data = client.get("/api/core/intelligence").json()
        assert len(data["agents"]) == 4 and data["limits"]["max_depth"] == 1
        target = "/api/core/intelligence/agents/CODEX/control"
        assert client.post(target, json={"action": "disable"}).status_code == 401
        auth = {
            "Authorization": "Bearer "
            + engine.host.store.settings.triad_operator_token.get_secret_value(),
            "Origin": "http://127.0.0.1:8000",
        }
        assert client.post("/api/core/intelligence/auth/validate", json={}).status_code == 401
        assert (
            client.post("/api/core/intelligence/auth/validate", json={}, headers=auth).status_code
            == 200
        )
        assert (
            client.post(
                "/api/core/intelligence/auth/validate",
                json={},
                headers=auth | {"Origin": "http://127.0.0.1:8006"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                target,
                json={"action": "disable"},
                headers=auth | {"Origin": "https://evil.invalid"},
            ).status_code
            == 403
        )
        proposal = host.list("CapabilityProposal")[0]
        response = client.post(
            "/api/core/intelligence/capabilities/" + proposal["id"] + "/adopt",
            json={"implementation_id": "nonexistent", "commit": "unreviewed"},
            headers=auth,
        )
        assert response.status_code in (400, 403, 404, 409)
    finally:
        app.dependency_overrides.pop(service, None)
