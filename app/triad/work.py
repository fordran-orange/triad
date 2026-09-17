"""Canonical Day 2 contracts. Provider output is data, never authority."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class State(StrEnum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    APPROVED = "APPROVED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED_BY_REVIEWER = "APPROVED_BY_REVIEWER"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Provenance(Record):
    provenance_id: str = Field(default_factory=uid)
    kind: Literal[
        "FACT",
        "OBSERVATION",
        "HYPOTHESIS",
        "DECISION",
        "EXTERNAL_CLAIM",
        "TEST_RESULT",
        "ASSUMPTION",
        "RECOMMENDATION",
    ]
    text: str = Field(min_length=1, max_length=8000)
    source: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=now)
    agent: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: tuple[str, ...] = ()
    work_item: str | None = None

    @model_validator(mode="after")
    def supported_fact(self):
        if self.kind in {"FACT", "TEST_RESULT"} and not self.evidence:
            raise ValueError("Verified facts and test results require evidence references")
        return self


class ComputeBudget(Record):
    max_input_chars: int = Field(default=12000, ge=100, le=32000)
    max_output_tokens: int = Field(default=512, ge=1, le=2048)
    timeout_seconds: int = Field(default=90, ge=1, le=120)
    max_tool_calls: int = Field(default=30, ge=1, le=100)


class Artifact(Record):
    path: str
    content: str = Field(max_length=64000)


class WorkResult(Record):
    summary: str = Field(min_length=1, max_length=16000)
    artifacts: tuple[Artifact, ...] = ()
    claims: tuple[Provenance, ...] = ()
    actions: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)
    execution_mode: Literal["deterministic_demo", "ollama"]


class WorkItem(Record):
    work_item_id: str = Field(default_factory=uid)
    parent_work_item_id: str | None = None
    mission_id: str = Field(default_factory=uid)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=8000)
    created_at: datetime = Field(default_factory=now)
    created_by: str = "operator"
    assigned_agent: str | None = None
    status: State = State.CREATED
    priority: int = Field(default=3, ge=1, le=5)
    work_type: str = "documentation_audit"
    authority_tier: int = Field(default=1, ge=0, le=5)
    allowed_tools: tuple[str, ...] = ("read_file", "write_artifact")
    allowed_paths: tuple[str, ...] = ("docs", "research/generated")
    forbidden_paths: tuple[str, ...] = (".env", ".git", ".venv", "control-plane")
    reasoning_budget: int = Field(default=512, ge=0, le=4096)
    compute_budget: ComputeBudget = Field(default_factory=ComputeBudget)
    execution_permissions: tuple[str, ...] = ("read", "write_research")
    risk_class: Literal["LOW", "MEDIUM", "HIGH", "GOVERNANCE", "LIVE"] = "LOW"
    affects_money: bool = False
    affects_trading: bool = False
    alters_permissions: bool = False
    input_context: tuple[Provenance, ...] = ()
    expected_outputs: tuple[str, ...] = ("Documentation consistency report",)
    acceptance_criteria: tuple[str, ...] = (
        "Inspect required documentation independently",
        "Preserve evidence and source hashes",
    )
    review_required: bool = True
    reviewer: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: WorkResult | None = None
    failure_reason: str | None = None
    revision: int = Field(default=0, ge=0)

    @field_validator("work_item_id", "mission_id", "parent_work_item_id")
    @classmethod
    def safe_identifier(cls, value):
        if value is not None and (
            not value
            or len(value) > 100
            or any(
                c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for c in value
            )
        ):
            raise ValueError("Identifiers must be safe alphanumeric IDs")
        return value

    @model_validator(mode="after")
    def independent_reviewer(self):
        if self.reviewer and self.reviewer == self.assigned_agent:
            raise ValueError("Worker cannot review its own work")
        if not self.expected_outputs or not self.acceptance_criteria:
            raise ValueError("Work requires outputs and acceptance criteria")
        return self


class Agent(Record):
    agent_id: str
    display_name: str
    provider: str
    model: str
    role: Literal["member", "helper"]
    capabilities: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    default_reasoning_budget: int = 512
    maximum_reasoning_budget: int = 2048
    cost_class: str
    local_or_remote: Literal["local", "remote"]
    enabled: bool
    review_eligible: bool
    execution_eligible: bool
    authority_tier: int = Field(ge=0, le=3)
    integration: Literal["unconfigured", "ollama"]


class PolicyDecision(Record):
    policy_decision_id: str = Field(default_factory=uid)
    work_item_id: str
    decision: Literal["ALLOW", "DENY", "REQUIRE_REVIEW", "REQUIRE_HUMAN_APPROVAL"]
    reason: str
    policy_version: str = "day2-v1"
    evaluated_at: datetime = Field(default_factory=now)
    rules_triggered: tuple[str, ...]
    routed_agent: str | None
    routing_reason: str


class ContextPacket(Record):
    packet_id: str = Field(default_factory=uid)
    work_item_id: str
    generated_at: datetime = Field(default_factory=now)
    work_item: str
    charter: tuple[Provenance, ...] = ()
    applicable_policies: tuple[Provenance, ...] = ()
    recent_journal_entries: tuple[Provenance, ...] = ()
    relevant_decisions: tuple[Provenance, ...] = ()
    relevant_files: tuple[Provenance, ...] = ()
    prior_handoff: tuple[Provenance, ...] = ()
    relevant_graph_relationships: tuple[Provenance, ...] = ()
    required_acceptance_criteria: tuple[str, ...]


class JournalEntry(Record):
    journal_id: str = Field(default_factory=uid)
    timestamp: datetime = Field(default_factory=now)
    agent: str
    work_item_id: str
    mission_id: str
    objective: str
    context_received: tuple[str, ...]
    actions_taken: tuple[str, ...]
    files_changed: tuple[str, ...]
    tests_run: tuple[str, ...]
    results: str
    failures: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    recommended_next_step: str
    handoff_to: str | None
    git_commit: str
    event_kind: Literal["creation", "review", "failure"]
    execution_mode: str


class Handoff(Record):
    handoff_id: str = Field(default_factory=uid)
    from_agent: str
    to_agent: str
    work_item_id: str
    completed_work: str
    files_changed: tuple[str, ...]
    tests_performed: tuple[str, ...]
    evidence: tuple[str, ...]
    known_issues: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    recommended_checks: tuple[str, ...]
    git_commit: str
    review_request: str

    @model_validator(mode="after")
    def distinct_agents(self):
        if self.from_agent == self.to_agent:
            raise ValueError("Self-handoff is not independent review")
        return self


class Review(Record):
    review_id: str = Field(default_factory=uid)
    reviewer: str
    work_item_id: str
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    findings: tuple[str, ...]
    severity: Literal["NONE", "LOW", "MEDIUM", "HIGH"]
    required_changes: tuple[str, ...] = ()
    optional_improvements: tuple[str, ...] = ()
    evidence_checked: tuple[str, ...]
    tests_repeated: tuple[str, ...]
    timestamp: datetime = Field(default_factory=now)
    execution_mode: str = "deterministic_demo"


class ElevationRequest(Record):
    request_id: str = Field(default_factory=uid)
    agent_id: str
    work_item_id: str | None = None
    requested_tier: int = Field(ge=0, le=5)
    reason: str = Field(min_length=1, max_length=4000)
    timestamp: datetime = Field(default_factory=now)
    status: Literal["PENDING_HUMAN_REVIEW"] = "PENDING_HUMAN_REVIEW"


TRANSITIONS = {
    State.CREATED: {State.VALIDATING, State.CANCELLED},
    State.VALIDATING: {State.APPROVED, State.REJECTED, State.BLOCKED, State.FAILED},
    State.APPROVED: {State.ASSIGNED, State.BLOCKED, State.CANCELLED},
    State.ASSIGNED: {State.IN_PROGRESS, State.BLOCKED, State.CANCELLED},
    State.IN_PROGRESS: {State.AWAITING_REVIEW, State.COMPLETED, State.FAILED, State.BLOCKED},
    State.AWAITING_REVIEW: {
        State.APPROVED_BY_REVIEWER,
        State.CHANGES_REQUESTED,
        State.REJECTED,
        State.BLOCKED,
        State.FAILED,
    },
    State.CHANGES_REQUESTED: {State.VALIDATING, State.CANCELLED},
    State.APPROVED_BY_REVIEWER: {State.COMPLETED},
    State.BLOCKED: {State.VALIDATING, State.CANCELLED},
    State.FAILED: {State.VALIDATING, State.CANCELLED},
    State.REJECTED: set(),
    State.COMPLETED: set(),
    State.CANCELLED: set(),
}


def transition(
    work: WorkItem,
    target: State,
    *,
    actor: str = "orchestrator",
    approved_review: Review | None = None,
) -> WorkItem:
    if actor != "orchestrator":
        raise PermissionError("Agents submit results; only the host orchestrator changes state")
    if target not in TRANSITIONS[work.status]:
        raise ValueError(f"Invalid transition {work.status} -> {target}")
    if (
        target == State.COMPLETED
        and work.review_required
        and work.status != State.APPROVED_BY_REVIEWER
    ):
        raise PermissionError("Mandatory independent review cannot be bypassed")
    if target == State.APPROVED_BY_REVIEWER and (
        approved_review is None
        or approved_review.decision != "APPROVE"
        or approved_review.reviewer != work.reviewer
        or approved_review.work_item_id != work.work_item_id
        or approved_review.reviewer == work.assigned_agent
    ):
        raise PermissionError("Matching independent approval required")
    changes = {"status": target, "revision": work.revision + 1}
    if target == State.IN_PROGRESS:
        changes["started_at"] = now()
    if target in {State.COMPLETED, State.REJECTED, State.CANCELLED, State.FAILED}:
        changes["completed_at"] = now()
    return WorkItem.model_validate(work.model_dump() | changes)
