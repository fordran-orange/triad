"""Product decisions are Triad-owned data, never Core authority."""

from typing import Literal

from pydantic import Field
from trading_core.work import Record, uid


class ProductArea(Record):
    capability: str
    state: Literal["EXISTS", "PARTIAL", "MISSING", "PROPOSED", "REJECTED"]
    user_value: str
    dependencies: tuple[str, ...]
    limitations: tuple[str, ...]
    technical_debt: tuple[str, ...]
    evidence: tuple[str, ...]
    candidate_improvements: tuple[str, ...]


class ProductCandidate(Record):
    candidate_id: str = Field(default_factory=uid)
    title: str
    problem: str
    product_area: str
    evidence: tuple[str, ...]
    expected_user_value: str
    technical_value: str
    risk: str
    effort: str
    dependencies: tuple[str, ...]
    reversibility: str
    origin: str
    status: Literal["PROPOSED", "DEFERRED", "SELECTED"] = "PROPOSED"


class ProductInspection(Record):
    areas: tuple[ProductArea, ...] = Field(min_length=1, max_length=4)
    candidates: tuple[ProductCandidate, ...] = Field(min_length=1, max_length=3)


class ProductProposal(Record):
    proposal_id: str = Field(default_factory=uid)
    candidate_id: str
    title: str
    problem: str
    product_area: str
    evidence: tuple[str, ...] = Field(min_length=1)
    proposed_change: str
    user_value: str
    technical_value: str
    expected_benefit: str
    possible_downside: str
    affected_components: tuple[str, ...] = Field(min_length=1)
    risk_class: Literal["LOW", "MEDIUM", "HIGH", "GOVERNANCE"]
    reversibility: str
    test_plan: tuple[str, ...] = Field(min_length=1)
    QA_plan: tuple[str, ...] = Field(min_length=1)
    rollback_plan: str = Field(min_length=1)
    estimated_effort: str
    permissions_required: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    recommended_agent: str
    specialist: Literal["existing agent sufficient", "new specialist agent recommended"]
