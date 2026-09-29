"""Canonical model-independent runtime and autonomy contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from trading_core.work import Provenance, Record, now, uid

Mode = Literal["REAL", "SIMULATED", "UNAVAILABLE"]


class Limits(Record):
    max_changes_day: int = Field(default=3, ge=0, le=3)
    max_cloud_cost_day: float = Field(default=0, ge=0, le=25)
    max_tokens_day: int = Field(default=160000, ge=0, le=500000)
    max_compute_seconds_day: int = Field(default=1800, ge=0, le=3600)
    max_repositories: int = Field(default=1, ge=0, le=1)
    max_migrations: int = Field(default=0, ge=0, le=0)
    max_high_risk: int = Field(default=0, ge=0, le=0)
    max_files: int = Field(default=3, ge=1, le=5)
    max_lines: int = Field(default=180, ge=1, le=300)
    timeout_seconds: int = Field(default=480, ge=1, le=86400)
    max_input_chars: int = Field(default=24000, ge=1000, le=1000000)
    max_output_tokens: int = Field(default=6144, ge=256, le=1000000)
    max_cost_run: float = Field(default=0.25, ge=0, le=1)
    max_delegation_depth: int = Field(default=1, ge=0, le=1)
    max_support_requests: int = Field(default=1, ge=0, le=2)
    allowed_directories: tuple[str, ...] = ("docs/improvements", "research/improvements")


class ImprovementProposal(Record):
    proposal_id: str = Field(default_factory=uid)
    agent: str
    title: str = Field(min_length=1, max_length=160)
    problem: str
    evidence: tuple[str, ...]
    proposed_change: str
    expected_benefit: str
    possible_downside: str
    affected_components: tuple[str, ...]
    risk_class: Literal["LOW", "MEDIUM", "HIGH", "GOVERNANCE"]
    reversibility: str
    test_plan: tuple[str, ...]
    rollback_plan: str
    estimated_cost: float = Field(ge=0)
    permissions_required: tuple[str, ...]


class FileChange(Record):
    path: str
    content: str = Field(max_length=32000)
    original_sha256: str | None = None


class AgentRunRequest(Record):
    run_id: str = Field(default_factory=uid)
    control_epoch: int = Field(default=0, ge=0)
    agent_id: str
    work_item_id: str
    mission_id: str
    context_packet: dict
    role: Literal["PROPOSE", "IMPLEMENT", "REVIEW", "SUPPORT"]
    objective: str
    allowed_tools: tuple[str, ...] = ("propose_file_change",)
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...] = (
        ".env",
        ".git",
        "agents",
        "control-plane",
        "app/triad",
        "app/trading_core",
        "app/platform_host",
        "config",
        "backups",
        "infrastructure",
        "tools",
    )
    acceptance_criteria: tuple[str, ...]
    reasoning_budget: int = Field(default=8192, ge=0, le=1000000)
    token_budget: int = Field(default=6144, ge=1, le=1000000)
    cost_budget: float = Field(default=0.25, ge=0, le=1)
    execution_permissions: tuple[str, ...] = ("write_docs",)
    policy_decision: dict
    required_output_schema: dict
    parent_work_item_id: str | None = None
    delegation_depth: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def bounded(self):
        if self.agent_id == "LOCAL_QWEN" and (
            self.role != "SUPPORT" or self.execution_permissions != ("read",)
        ):
            raise ValueError("Qwen is an observe-only support worker")
        if self.delegation_depth and not self.parent_work_item_id:
            raise ValueError("Delegation requires a parent assignment")
        return self


class AgentRunResult(Record):
    run_id: str
    status: Literal[
        "CODE_CHANGE",
        "DOCUMENTATION_CHANGE",
        "TEST_ADDITION",
        "BUG_FIX",
        "ARCHITECTURAL_IMPROVEMENT",
        "RESEARCH_FINDING",
        "PERFORMANCE_IMPROVEMENT",
        "NO_CHANGE_JUSTIFIED",
        "BLOCKED",
    ]
    summary: str = Field(min_length=1, max_length=8000)
    analysis_artifacts: tuple[str, ...] = ()
    proposed_actions: tuple[str, ...] = ()
    actions_taken: tuple[str, ...] = ()
    files_changed: tuple[FileChange, ...] = ()
    commands_executed: tuple[str, ...] = ()
    tests_run: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    claims: tuple[Provenance, ...] = ()
    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    recommended_next_step: str = "Independent review"
    handoff_request: str = "Verify against original objective and source evidence"
    permission_requests: tuple[str, ...] = ()
    proposal: ImprovementProposal | None = None
    review_decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"] | None = None
    findings: tuple[str, ...] = ()


class ProviderHealth(Record):
    agent: str
    provider: str
    model: str
    status: Literal[
        "AVAILABLE",
        "DEGRADED",
        "AUTH_FAILED",
        "NOT_FOUND",
        "VERSION_MISMATCH",
        "NOT_AUTHENTICATED",
        "QUOTA_EXHAUSTED",
        "RATE_LIMITED",
        "UNAVAILABLE",
        "DISABLED",
    ]
    mode: Mode = "UNAVAILABLE"
    checked_at: datetime = Field(default_factory=now)
    last_success: str | None = None
    last_failure: str | None = None
    latency: float | None = None
    error_class: str | None = None
    recent_request_count: int = 0
    estimated_cost: float = 0


class Disagreement(Record):
    disagreement_id: str = Field(default_factory=uid)
    work_item_id: str
    agents: tuple[str, ...]
    claims_in_conflict: tuple[str, ...]
    evidence_used: tuple[str, ...]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["OPEN", "RESOLVED"] = "OPEN"
    resolution_method: str = "Human review; no automatic majority vote"
    human_review_required: bool = True
    review_ids: tuple[str, ...] = ()
