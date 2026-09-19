"""Global operator controls remain available independently of products."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from trading_core.api import ENGINE_DEPENDENCY, require_operator
from trading_core.ledger import Ledger

router = APIRouter()


class ControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "pause", "resume", "kill", "stop", "disable", "enable", "human_review", "lower_limits"
    ]
    agent: str | None = None
    work_id: str | None = None
    limits: dict | None = None


@router.get("/api/core/operations")
def operations(engine=ENGINE_DEPENDENCY):
    ledger = Ledger(engine.store)
    return {
        "control": ledger.control(),
        "records": ledger.records(limit=1000),
        "budgets": ledger.totals(),
        "exchange": "CLOSED",
    }


@router.post("/api/core/control", dependencies=[Depends(require_operator)])
def control(body: ControlInput, engine=ENGINE_DEPENDENCY):
    return Ledger(engine.store).operate(body.action, body.agent, body.work_id, body.limits)
