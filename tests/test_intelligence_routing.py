"""Routing uses observed capability and grants, never provider marketing claims."""

# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import build, qa
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.intelligence.routing import Requirements, Routing
from trading_core.providers.contracts import PREFERRED, SPECS
from trading_core.store import Store
from trading_core.work import WorkItem, now

pytestmark = pytest.mark.integration


class Control:
    def __init__(self, ledger):
        self.ledger = ledger
        self.changed = False

    def snapshot(self, transport):
        return {
            "billing_source": "LOCAL" if transport == "ollama" else "SUBSCRIPTION",
            "workitem": {"actual_model": "fixture-model", "success": True},
        }

    def policy(self, executor):
        return SimpleNamespace(
            preferred_transport=PREFERRED[executor],
            models={PREFERRED[executor]: "changed" if self.changed else "Auto"},
        )

    @staticmethod
    def proven(snapshot):
        return snapshot["workitem"]["success"]


def setup_routing(engine):
    host = Records(engine.host.store)
    control = Control(engine.ledger)
    Agents(host).seed_static(control)
    registry = Capabilities(host)
    for transport in PREFERRED.values():
        for name in ("structured_output", "document_analysis", "private_local_processing"):
            if name == "private_local_processing" and transport != "ollama":
                continue
            cap = Capability(
                capability_id=transport + ":" + name,
                provider=SPECS[transport]["provider"],
                model="fixture-model",
                transport=transport,
                capability=name,
                native_or_tool_mediated="local" if transport == "ollama" else "tool_mediated",
                status="AVAILABLE",
                verification_status="VERIFIED",
                discovery_source="runtime",
                evidence=("fixture runtime",),
                verified_by="fixture verifier",
                verified_at=now(),
                permissions_required=("read",),
            )
            proposal = registry.propose(cap, actor="operator")
            implementation = build(host, ("capability:" + host.get(proposal)["digest"],))
            Quality(host).review(qa(implementation))
            registry.approve(
                proposal, implementation.implementation_run_id, implementation.change_commit
            )
    return Routing(Records(Store(engine.host.store.settings, scope="triad")), control), host


def work(**updates):
    return WorkItem(
        **(
            {
                "owner": "triad",
                "title": "Independent inspection",
                "description": "Inspect bounded product evidence",
                "work_type": "review",
                "authority_tier": 0,
                "allowed_tools": ("read_file",),
                "allowed_paths": ("docs/improvements",),
                "execution_permissions": ("read",),
                "review_required": False,
            }
            | updates
        )
    )


def requirements(**updates):
    return Requirements(
        **(
            {
                "role": "REVIEW",
                "capabilities": ("structured_output", "document_analysis"),
                "context_chars": 1000,
                "preferred_agent": "CODEX",
                "reason": "Independent technical inspection",
            }
            | updates
        )
    )


def test_route_persists_evidence_and_excludes_local_qa(engine):
    router, _ = setup_routing(engine)
    assigned = router.create(work(), requirements())
    decision = router.records.get("route-" + assigned.work_item_id)
    assert (
        assigned.assigned_agent == "CODEX"
        and decision["selected"]["billing_source"] == "SUBSCRIPTION"
    )
    assert len(decision["selected"]["capability_versions"]) == 2
    qwen = next(c for c in decision["candidates"] if c["agent_id"] == "LOCAL_QWEN")
    assert not qwen["eligible"] and "Agent cannot independently review" in qwen["exclusions"]
    with pytest.raises(PermissionError):
        Records(Store(engine.host.store.settings, scope="aegis")).get(decision["id"])


@pytest.mark.parametrize(
    "failure",
    ["capability", "privacy", "disabled", "model_change", "tools", "independence"],
)
def test_unsuitable_provider_cannot_be_routed(engine, failure):
    router, _ = setup_routing(engine)
    task, need = work(), requirements()
    if failure == "capability":
        need = requirements(capabilities=("native_x_access",))
    if failure == "privacy":
        need = requirements(privacy="local_only")
    if failure == "disabled":
        engine.ledger.operate("disable", agent="CODEX")
    if failure == "model_change":
        router.control.changed = True
    if failure == "tools":
        task = work(allowed_tools=("shell",))
    if failure == "independence":
        need = requirements(excluded_executors=("CODEX",))
    with pytest.raises(PermissionError):
        router.create(task, need)


def test_local_privacy_support_is_routed_to_qwen(engine):
    router, _ = setup_routing(engine)
    assigned = router.create(
        work(work_type="summarize_journal"),
        requirements(
            role="SUPPORT",
            privacy="local_only",
            capabilities=("private_local_processing", "structured_output"),
            preferred_agent="LOCAL_QWEN",
        ),
    )
    assert assigned.assigned_agent == "LOCAL_QWEN"


def test_forged_proposal_digest_cannot_borrow_reviewed_update(engine):
    _, host = setup_routing(engine)
    prior = host.list("CapabilityProposal")[0]
    forged = Records(Store(engine.host.store.settings, scope="triad")).append(
        "CapabilityProposal",
        {
            **{k: v for k, v in prior.items() if k not in {"id", "kind", "owner"}},
            "capability": prior["capability"] | {"capability": "native_x_access"},
        },
        owner="triad",
    )
    implementation = build(host, ("capability:" + prior["digest"],))
    Quality(host).review(qa(implementation))
    with pytest.raises(PermissionError, match="digest"):
        Capabilities(host).approve(
            forged, implementation.implementation_run_id, implementation.change_commit
        )


def test_provider_policy_is_rechecked_at_dispatch(engine):
    router, _ = setup_routing(engine)
    assigned = router.create(work(), requirements())
    request = SimpleNamespace(work_item_id=assigned.work_item_id, role="REVIEW", agent_id="CODEX")
    adapter = SimpleNamespace(transport_id="codex_cli")
    assert router.validate_execution(request, adapter)["model"] == "fixture-model"
    router.control.changed = True
    with pytest.raises(PermissionError, match="no longer eligible"):
        router.validate_execution(request, adapter)


def test_context_above_initial_allocation_can_reach_governed_dispatch(engine):
    router, _ = setup_routing(engine)
    assigned = router.create(work(), requirements(context_chars=30000))
    assert assigned.assigned_agent == "CODEX"
    with pytest.raises(ValueError):
        requirements(context_chars=1000001)
