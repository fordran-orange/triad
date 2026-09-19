"""Readable Core intelligence views and operator-authenticated governance."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from trading_core.api import ENGINE_DEPENDENCY, require_operator
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities, fingerprint
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.records import Records
from trading_core.providers.control import ProviderControl
from trading_core.work import now

router = APIRouter()
AUTH = [Depends(require_operator)]


def records(engine=ENGINE_DEPENDENCY):
    return Records(engine.store)


DEP = Depends(records)


@router.post("/api/core/intelligence/auth/validate", dependencies=AUTH)
def validate_operator():
    return {"authenticated": True}


class Adoption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    implementation_id: str
    commit: str


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["disable", "terminate"]


@router.get("/core/intelligence", include_in_schema=False)
def intelligence_shell():
    return FileResponse(Path(__file__).parents[1] / "static/intelligence.html")


@router.get("/assets/intelligence.js", include_in_schema=False)
def intelligence_script():
    return FileResponse(
        Path(__file__).parents[1] / "static/intelligence.js", media_type="text/javascript"
    )


@router.get("/api/core/intelligence")
def dashboard(service=DEP):
    agents = Agents(service)
    decisions = {r["request_id"]: r for r in service.list("AgentCreationDecision")}
    works = service.store.list_work(1000)
    bindings = service.list("AgentDelegation")
    definitions = []
    for agent in agents.list():
        ids = {r["child_work_item"] for r in bindings if r["agent_id"] == agent["agent_id"]}
        current = [
            {"work_item_id": w.work_item_id, "title": w.title, "status": w.status}
            for w in works
            if w.status in {"ASSIGNED", "IN_PROGRESS", "AWAITING_REVIEW"}
            and (
                w.work_item_id in ids
                or agent["agent_type"] == "static"
                and w.assigned_agent == agent["agent_id"]
            )
        ]
        definitions.append({**agent, "current_work": current})
    approved = {v["proposal_id"] for v in service.list("CapabilityVersion")}
    return {
        "capabilities": Capabilities(service).current(),
        "agents": definitions,
        "capability_proposals": [
            {**r, "review_status": "APPROVED" if r["id"] in approved else "PENDING"}
            for r in service.list("CapabilityProposal")
        ],
        "requests": [
            {**r, "evaluation": decisions.get(r["id"], {"decision": "PENDING"})}
            for r in service.list("AgentCreationRequest")
        ],
        "promotions": service.list("AgentPromotionRequest"),
        "promotion_decisions": service.list("AgentPromotion"),
        "delegations": bindings,
        "lifecycle": service.list("AgentLifecycle"),
        "routing": service.list("CapabilityRoutingDecision"),
        "limits": agents.policy.model_dump(),
        "quality_debt": service.list("QualityDebt"),
        "updated_at": now().isoformat(),
    }


@router.post("/api/core/intelligence/capabilities/proposals", dependencies=AUTH)
def propose(value: Capability, service=DEP):
    return {"proposal_id": Capabilities(service).propose(value, actor="Core operator")}


@router.post("/api/core/intelligence/capabilities/discover", dependencies=AUTH)
def discover(service=DEP):
    registry, control = Capabilities(service), ProviderControl(service.ledger)
    existing = {r["digest"] for r in service.list("CapabilityProposal")}
    results = []
    for capability in (
        *registry.discover_runtime(control),
        *registry.discover_introspection(control),
    ):
        if fingerprint(capability.model_dump(mode="json")) not in existing:
            results.append(registry.propose(capability, actor="Core evidence discovery"))
    return {
        "proposals_created": len(results),
        "proposal_ids": results,
        "message": "Evidence discovered. Independent QA and exact revision approval are required before adoption.",
    }


@router.post("/api/core/intelligence/capabilities/{identifier}/adopt", dependencies=AUTH)
def adopt(identifier: str, value: Adoption, service=DEP):
    return {
        "version_id": Capabilities(service).approve(
            identifier, value.implementation_id, value.commit
        )
    }


@router.post("/api/core/intelligence/agents/{identifier}/control", dependencies=AUTH)
def operate(identifier: str, value: Operation, service=DEP):
    return Agents(service).operate(identifier, value.action)


@router.post("/api/core/intelligence/promotions/{identifier}/adopt", dependencies=AUTH)
def promote(identifier: str, value: Adoption, service=DEP):
    return (
        Agents(service)
        .promote(identifier, value.implementation_id, value.commit)
        .model_dump(mode="json")
    )
