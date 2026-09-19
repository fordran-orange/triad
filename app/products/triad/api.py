"""Day 3 operator API. No endpoint accepts arbitrary model runtime envelopes or shell commands."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from trading_core.api import require_operator
from trading_core.brain import Brain
from trading_core.support import manifest, support

from products.triad.contracts import Candidate
from products.triad.cycles import Cycles
from products.triad.jobs import Jobs

router = APIRouter(prefix="/api/day3")


def cycles_service():
    return Cycles()


DEP = Depends(cycles_service)
AUTH = [Depends(require_operator)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CycleInput(Input):
    mode: Literal["REAL", "SIMULATED"] = "REAL"


class ControlInput(Input):
    action: Literal[
        "pause", "resume", "kill", "stop", "disable", "enable", "human_review", "lower_limits"
    ]
    agent: str | None = None
    work_id: str | None = None
    limits: dict | None = None


class ProposalInput(Input):
    action: Literal["approve", "deny"]


class ReviewInput(Input):
    human_merge: bool = False


class SupportInput(Input):
    parent_work_item_id: str
    requester: str
    capability: str
    text: str = Field(min_length=1, max_length=3000)


class ReasoningInput(Input):
    work_item_id: str
    agent: str
    requested: int
    justification: str = Field(min_length=1, max_length=1000)


@router.get("/dashboard")
def dashboard(engine: Cycles = DEP):
    records = engine.ledger.records(limit=1000)
    return {
        "control": engine.ledger.control(),
        "product_control": engine.ledger.product_control(),
        "rotation": engine.rotation,
        "records": [
            r
            for r in records
            if r["kind"] not in {"AgentRunRequest", "AgentRunResult", "BudgetReservation"}
        ],
        "budgets": engine.ledger.totals(),
        "providers": [r for r in records if r["kind"] == "ProviderHealth"],
        "capabilities": manifest(),
        "projections": engine.host.store.projection_status(),
    }


@router.post("/health", dependencies=AUTH)
def health(engine: Cycles = DEP):
    return engine.runtime.health()


@router.post("/cycles", dependencies=AUTH, status_code=202)
def cycle(body: CycleInput, engine: Cycles = DEP):
    engine.ledger.guard()
    return Jobs(engine).submit(mode=body.mode)


@router.post("/control", dependencies=AUTH)
def control(body: ControlInput, engine: Cycles = DEP):
    return engine.ledger.operate(
        body.action, agent=body.agent, work_id=body.work_id, limits=body.limits
    )


@router.post("/candidates", dependencies=AUTH, status_code=201)
def candidate(body: Candidate, engine: Cycles = DEP):
    engine.ledger.put("Candidate", body.model_dump(mode="json"), identifier=body.candidate_id)
    return body


@router.post("/proposals/{identifier}", dependencies=AUTH)
def proposal(identifier: str, body: ProposalInput, engine: Cycles = DEP):
    return engine.proposal_action(identifier, body.action)


@router.post("/changes/{identifier}/review", dependencies=AUTH)
def review(identifier: str, body: ReviewInput, engine: Cycles = DEP):
    with engine.host.store.lease("day3-cycle"):
        result = engine.review_change(identifier, human_merge=body.human_merge)
    Brain(engine.host.store).flush()
    return result


@router.post("/changes/{identifier}/rollback", dependencies=AUTH)
def rollback(identifier: str, engine: Cycles = DEP):
    with engine.host.store.lease("day3-cycle"):
        result = engine.prepare_rollback(identifier)
    Brain(engine.host.store).flush()
    return result


@router.post("/support", dependencies=AUTH)
def helper(body: SupportInput, engine: Cycles = DEP):
    return support(engine, body.parent_work_item_id, body.requester, body.capability, body.text)


@router.post("/reasoning-requests", dependencies=AUTH)
def reasoning(body: ReasoningInput, engine: Cycles = DEP):
    return engine.request_reasoning(
        body.work_item_id, body.agent, body.requested, body.justification
    )


@router.get("/records/{identifier}")
def record(identifier: str, engine: Cycles = DEP):
    return engine.ledger.get(identifier)


@router.get("/jobs")
def jobs(engine: Cycles = DEP):
    return {"jobs": Jobs(engine).list()}


@router.post("/jobs/{identifier}/cancel", dependencies=AUTH)
def cancel_job(identifier: str, engine: Cycles = DEP):
    return Jobs(engine).cancel(identifier)


@router.get("/readiness")
def provider_readiness(engine: Cycles = DEP):
    from products.triad.readiness import readiness

    return readiness(engine)
