"""Append-only model reconciliation respects real immutable grants and QA revocation."""
# ruff: noqa: F811

from copy import deepcopy
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities, fingerprint
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.model_binding import ModelBindingRequest, binding_marker
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.intelligence.routing import Requirements, Routing
from trading_core.providers.control import ProviderControl
from trading_core.store import Store
from trading_core.work import ComputeBudget, WorkItem, now, uid

pytestmark = pytest.mark.integration


def setup(engine):
    records = Records(engine.host.store)
    agents = Agents(records)
    agents.seed_static(
        SimpleNamespace(snapshot=lambda _: {"workitem": {"actual_model": "grok-4.6"}})
    )
    with records.store.connect() as conn:
        raw = conn.execute(
            "SELECT definition FROM core.agent_instances WHERE id='GROK'"
        ).fetchone()["definition"]
    proofs = {}
    for kind in ("test", "workitem"):
        work = WorkItem(
            owner="core", title="Explicit fixture proof", description="No model invocation"
        )
        records.store.create(work)
        run_id = uid()
        records.ledger.put(
            "TransportRun", {"run_id": run_id, "status": "SUCCESS"}, work_id=work.work_item_id
        )
        usage_id = records.ledger.put(
            "Usage",
            {
                "run_id": run_id,
                "status": "SUCCESS",
                "usage_known": True,
                "mode": "REAL",
                "actual_model": "grok-4.7",
                "transport": "grok_build_cli",
                "billing_source": "SUBSCRIPTION",
                "agent": "GROK",
            },
            work_id=work.work_item_id,
        )
        proof = {
            "kind": kind,
            "run_id": run_id,
            "usage_id": usage_id,
            "work_item_id": work.work_item_id,
            "success": True,
            "mode": "REAL",
            "actual_model": "grok-4.7",
            "agent": "GROK",
            "provider": "xai",
            "transport": "grok_build_cli",
            "billing_source": "SUBSCRIPTION",
            "completed_at": now().isoformat(),
        }
        identifier = records.ledger.put("TransportVerification", proof, work_id=work.work_item_id)
        proofs[kind] = {**proof, "proof_id": identifier}
    status = {
        **proofs,
        "auth_state": "AUTHENTICATED",
        "billing_source": "SUBSCRIPTION",
        "error": None,
    }
    records.ledger.put("TransportStatus", status, identifier="transport-status-grok_build_cli")
    caps = [
        Capability(
            capability_id="grok_build_cli:grok-4.7:" + name,
            provider="xai",
            model="grok-4.7",
            transport="grok_build_cli",
            capability=name,
            native_or_tool_mediated="tool_mediated",
            status="AVAILABLE",
            verification_status="VERIFIED",
            discovery_source="runtime",
            evidence=(
                "transport-proof:" + proofs["workitem"]["proof_id"],
                "run:" + proofs["workitem"]["run_id"],
            ),
            permissions_required=("read",),
            verified_by="offline test fixture",
            verified_at=now(),
        )
        for name in ("structured_output", "isolated_text_read", "document_analysis")
    ]
    adoption = build(
        records, tuple("capability:" + fingerprint(c.model_dump(mode="json")) for c in caps)
    )
    quality = Quality(records)
    quality.review(qa(adoption))
    registry = Capabilities(records)
    versions = [
        registry.approve(
            registry.propose(c, actor="host"),
            adoption.implementation_run_id,
            adoption.change_commit,
        )
        for c in caps
    ]
    request = ModelBindingRequest(
        agent_id="GROK",
        base_definition_digest=fingerprint(raw),
        previous_model=raw["model"],
        model="grok-4.7",
        provider="xai",
        transport="grok_build_cli",
        test_proof=proofs["test"]["proof_id"],
        work_proof=proofs["workitem"]["proof_id"],
        capability_versions=tuple(versions),
    )
    return agents, records, raw, request, status, adoption


def approve(records, request):
    marker = binding_marker(request)
    implementation = build(records, (marker,))
    Quality(records).review(qa(implementation, evidence=(marker,)))
    return implementation


def publish(agents, request, implementation):
    return agents.bind_model(
        request, implementation.implementation_run_id, implementation.change_commit
    )


def test_binding_preserves_real_immutable_definition_and_routes_read_only(engine):
    agents, records, raw, request, _status, _ = setup(engine)
    before = agents.get("GROK")
    with (
        pytest.raises(psycopg.errors.RaiseException, match="Immutable agent grant"),
        records.store.connect() as conn,
    ):
        conn.execute(
            "UPDATE core.agent_instances SET definition=%s WHERE id='GROK'",
            (Jsonb({**raw, "model": "grok-4.7"}),),
        )
    implementation = approve(records, request)
    identifier = publish(agents, request, implementation)
    effective = agents.get("GROK")
    assert {k for k in before if before[k] != effective[k]} == {"model"}
    assert effective["model"] == "grok-4.7" and records.get(identifier)["owner"] == "core"
    with records.store.connect() as conn:
        assert (
            conn.execute("SELECT definition FROM core.agent_instances WHERE id='GROK'").fetchone()[
                "definition"
            ]
            == raw
        )
    router = Routing(records, ProviderControl(records.ledger))
    work = WorkItem(
        owner="triad",
        title="Read fixture",
        description="No dispatch",
        work_type="review",
        authority_tier=0,
        allowed_tools=("read_file",),
        allowed_paths=("docs/improvements",),
        execution_permissions=("read",),
        reasoning_budget=512,
        compute_budget=ComputeBudget(max_output_tokens=512, timeout_seconds=90),
        review_required=False,
    )
    requirements = Requirements(
        role="REVIEW",
        capabilities=("structured_output", "isolated_text_read"),
        context_chars=100,
        preferred_agent="GROK",
        reason="Fixture inspection",
    )
    versions = Capabilities(records).current()
    assert not router._candidate(before, work, requirements, versions)["eligible"]
    assert router._candidate(effective, work, requirements, versions)["eligible"]
    Quality(records).review(
        qa(
            implementation,
            decision="CHANGES_REQUIRED",
            findings=("Binding revoked",),
            severity="LOW",
        )
    )
    assert agents.get("GROK")["execution_eligible"] is False


def test_binding_requires_core_scope_exact_independent_qa_and_live_proofs(engine):
    agents, records, _raw, request, status, _ = setup(engine)
    scoped = Records(Store(records.store.settings, scope="triad"))
    with pytest.raises(PermissionError, match="Core host"):
        Agents(scoped).bind_model(request, "unknown", "unknown")
    with pytest.raises(PermissionError, match="trusted Core ingestion"):
        scoped.append("AgentModelBinding", {"request": request.model_dump(mode="json")})
    wrong = build(records)
    Quality(records).review(qa(wrong))
    with pytest.raises(PermissionError, match="exact model binding"):
        publish(agents, request, wrong)
    implementation = approve(records, request)
    for update in (
        {"model": "grok-4.8"},
        {"base_definition_digest": "a" * 64},
        {"provider": "openai"},
    ):
        with pytest.raises(PermissionError):
            publish(agents, request.model_copy(update=update), implementation)
    status["error"] = "TransportUnavailable"
    records.ledger.put("TransportStatus", status, identifier="transport-status-grok_build_cli")
    with pytest.raises(PermissionError, match="runtime proof"):
        publish(agents, request, implementation)
    assert not records.list("AgentModelBinding")


def test_binding_revalidates_proof_policy_capability_and_does_not_revive_older_binding(engine):
    agents, records, _, request, status, adoption = setup(engine)
    implementation = approve(records, request)
    publish(agents, request, implementation)
    original = deepcopy(status)
    for altered in (
        {**original, "error": "TransportUnavailable"},
        {**original, "workitem": {**original["workitem"], "proof_id": "different"}},
        {**original, "workitem": {**original["workitem"], "actual_model": "grok-4.8"}},
    ):
        records.ledger.put("TransportStatus", altered, identifier="transport-status-grok_build_cli")
        assert not agents.get("GROK")["execution_eligible"]
    records.ledger.put("TransportStatus", original, identifier="transport-status-grok_build_cli")
    assert agents.get("GROK")["model"] == "grok-4.7"
    records.ledger.put(
        "ProviderPolicy",
        {
            "policy": {
                "agent": "GROK",
                "preferred_transport": "grok_build_cli",
                "models": {"grok_build_cli": "grok-4.8"},
            }
        },
        identifier="provider-policy-GROK",
    )
    assert not agents.get("GROK")["execution_eligible"]
    records.ledger.put(
        "ProviderPolicy",
        {"policy": {"agent": "GROK", "preferred_transport": "grok_build_cli"}},
        identifier="provider-policy-GROK",
    )
    assert agents.get("GROK")["model"] == "grok-4.7"
    Quality(records).review(
        qa(
            adoption,
            decision="CHANGES_REQUIRED",
            findings=("Proof adoption revoked",),
            severity="LOW",
        )
    )
    assert not agents.get("GROK")["execution_eligible"]


def test_binding_rejects_active_run_and_becomes_ineligible_on_capability_supersession(engine):
    agents, records, _, request, _, _ = setup(engine)
    implementation = approve(records, request)
    run = records.ledger.put("TransportRun", {"agent": "GROK", "status": "RUNNING"})
    with pytest.raises(PermissionError, match="active provider run"):
        publish(agents, request, implementation)
    records.ledger.put("TransportRun", {"agent": "GROK", "status": "SUCCESS"}, identifier=run)
    publish(agents, request, implementation)
    assert agents.get("GROK")["execution_eligible"]
    existing = records.get(request.capability_versions[0])["capability"]
    degraded = Capability.model_validate(
        {**existing, "status": "RESTRICTED", "verification_status": "DEGRADED"}
    )
    proposal = Capabilities(records).propose(degraded, actor="host")
    implementation = build(
        records, ("capability:" + fingerprint(degraded.model_dump(mode="json")),)
    )
    Quality(records).review(qa(implementation))
    Capabilities(records).approve(
        proposal, implementation.implementation_run_id, implementation.change_commit
    )
    assert not agents.get("GROK")["execution_eligible"]
