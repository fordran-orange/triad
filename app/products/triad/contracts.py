"""Triad backlog and autonomous cycle contracts."""
from typing import Literal

from pydantic import Field
from trading_core.work import Record, uid


class Candidate(Record):
    candidate_id: str = Field(default_factory=uid)
    source: str
    problem: str = Field(min_length=1, max_length=4000)
    evidence: tuple[str, ...]
    impact: str
    risk: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    estimated_effort: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["OPEN", "SELECTED", "DONE", "BLOCKED"] = "OPEN"


class CycleSummary(Record):
    cycle_id: str
    date: str
    agents_run: tuple[str, ...]
    proposals: tuple[str, ...]
    changes_accepted: tuple[str, ...]
    changes_rejected: tuple[str, ...]
    changes_rolled_back: tuple[str, ...] = ()
    reviews: tuple[str, ...]
    disagreements: tuple[str, ...]
    tests: tuple[str, ...]
    cost: float
    failures: tuple[str, ...]
    lessons: tuple[str, ...]
    open_questions: tuple[str, ...]
    next_cycle_candidates: tuple[str, ...]
