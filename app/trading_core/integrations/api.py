"""Operator UI and read-only discovery; changes use existing local operator auth."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from trading_core.api import ENGINE_DEPENDENCY, require_operator
from trading_core.integrations.contracts import CATEGORIES, DataRequest, IntegrationCandidate
from trading_core.integrations.data import DataAccess
from trading_core.integrations.readiness import ReadinessRequest

router = APIRouter()
AUTH = [Depends(require_operator)]


def access(engine=ENGINE_DEPENDENCY):
    return DataAccess(engine.store)


DEP = Depends(access)


@router.get("/api/core/research-readiness")
def readiness_catalog(service=DEP):
    from trading_core.integrations.readiness import Readiness

    return Readiness(service).catalog()


@router.post("/api/core/research-readiness/evaluate")
def readiness_evaluate(body: ReadinessRequest, service=DEP):
    from trading_core.integrations.readiness import Readiness

    return Readiness(service).evaluate(body)


@router.get("/core/integrations")
def shell():
    return FileResponse(Path(__file__).parents[1] / "static/integrations.html")


@router.get("/assets/integrations.js")
def script():
    return FileResponse(
        Path(__file__).parents[1] / "static/integrations.js", media_type="text/javascript"
    )


@router.get("/api/core/integrations")
def dashboard(service=DEP):
    return {
        "integrations": service.registry.catalog(),
        "candidates": service.registry.candidates(),
        "categories": CATEGORIES,
        "live_execution": "DENIED",
        "paid_fallback": "NEVER_AUTOMATIC",
    }


@router.post("/api/core/integrations/match")
def match(body: DataRequest, service=DEP):
    return service.match(body)


@router.post("/api/core/integrations/{identifier}/check", dependencies=AUTH)
def check(identifier: str, service=DEP):
    return service.registry.check(identifier)


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=160)
    category: str = Field(pattern=r"^[A-Z][A-Z_]{1,49}$")
    reason: str = Field(min_length=1, max_length=4000)
    capabilities: tuple[str, ...]
    documentation: tuple[HttpUrl, ...]
    cost: str = Field(max_length=1000)
    limitations: tuple[str, ...] = ()


@router.post("/api/core/integrations/candidates", dependencies=AUTH, status_code=201)
def propose(body: CandidateInput, service=DEP):
    identifier = service.registry.propose(
        IntegrationCandidate(**body.model_dump(), proposed_by="operator")
    )
    return {
        "candidate_id": identifier,
        "status": "DISCOVERED",
        "message": "Candidate recorded for review. No code installed or connection enabled.",
    }


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["RESEARCHING", "APPROVED_FOR_IMPLEMENTATION", "REJECTED", "DEPRECATED"]
    review: str = Field(min_length=1, max_length=4000)


@router.post("/api/core/integrations/candidates/{identifier}/decision", dependencies=AUTH)
def decide(identifier: str, body: DecisionInput, service=DEP):
    return {"decision_id": service.registry.decide(identifier, body.status, body.review)}
