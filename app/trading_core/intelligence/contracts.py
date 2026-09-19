"""Extensible capability taxonomy and immutable governed-update contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from trading_core.work import Record, now, uid

HOST_RECORD_KINDS = frozenset(
    {
        "ImplementationRun",
        "QARun",
        "QualityDebt",
        "CapabilityVersion",
        "AgentDefinition",
        "AgentCreationRequest",
        "AgentCreationDecision",
        "AgentDelegation",
        "AgentRunReservation",
        "AgentLifecycle",
        "AgentPromotion",
        "CapabilityRoutingDecision",
        "QualityDebtResolution",
        "ResourceAllocation",
        "ResourceProgress",
        "ResourceExtensionRequest",
        "ResourceExtensionDecision",
        "ResourceRunState",
    }
)


class Capability(Record):
    capability_id: str = Field(default_factory=uid)
    provider: str
    model: str
    transport: str
    capability: str = Field(pattern=r"^[a-z][a-z0-9_./-]{1,79}$")
    capability_type: str = "intelligence"
    native_or_tool_mediated: Literal["native", "tool_mediated", "local"]
    status: Literal["AVAILABLE", "RESTRICTED", "UNAVAILABLE", "DEPRECATED"]
    verification_status: Literal[
        "DISCOVERED", "CLAIMED", "VERIFIED", "DEGRADED", "UNAVAILABLE", "DEPRECATED"
    ]
    evidence: tuple[str, ...] = ()
    verified_at: datetime | None = None
    verified_by: str | None = None
    limitations: tuple[str, ...] = ()
    permissions_required: tuple[str, ...] = ()
    cost_characteristics: dict = Field(default_factory=dict)
    latency_characteristics: dict = Field(default_factory=dict)
    notes: str = ""
    discovery_source: Literal[
        "documentation", "introspection", "runtime", "agent_observation", "operator"
    ]

    @model_validator(mode="after")
    def proof_required(self):
        if self.verification_status == "VERIFIED" and not (
            self.evidence and self.verified_at and self.verified_by
        ):
            raise ValueError("Verified capability requires dated evidence and verifier")
        if self.verified_at and (self.verified_at.tzinfo is None or self.verified_at > now()):
            raise ValueError("Verification time must be aware and not in the future")
        return self


class ImplementationRun(Record):
    implementation_run_id: str = Field(default_factory=uid)
    work_item_id: str | None = None
    owner: Literal["core", "triad", "aegis", "p2p"]
    builder: str
    provider: str
    model: str
    transport: str
    base_commit: str
    change_commit: str
    files: tuple[str, ...]
    tests: tuple[str, ...]
    evidence: tuple[str, ...]
    status: Literal["IMPLEMENTED", "FAILED"] = "IMPLEMENTED"
    created_at: datetime = Field(default_factory=now)


class QARun(Record):
    qa_run_id: str = Field(default_factory=uid)
    implementation_run_id: str
    qa_work_item_id: str | None = None
    qa_agent: str
    qa_provider: str
    qa_model: str
    reviewed_commit: str
    agent_capabilities_used: tuple[str, ...]
    findings: tuple[str, ...] = ()
    severity: str = "NONE"
    tests_repeated: tuple[str, ...]
    new_tests: tuple[str, ...] = ()
    browser_checks: tuple[str, ...] = ()
    regressions: tuple[str, ...] = ()
    architecture_findings: tuple[str, ...] = ()
    security_findings: tuple[str, ...] = ()
    required_changes: tuple[str, ...] = ()
    optional_improvements: tuple[str, ...] = ()
    evidence: tuple[str, ...]
    decision: Literal["PASS", "PASS_WITH_OBSERVATIONS", "CHANGES_REQUIRED", "REJECT", "BLOCKED"]
    execution_mode: Literal["HOST_INDEPENDENT_QA", "REAL_PROVIDER", "TEST_FIXTURE"]
    created_at: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def passing_evidence(self):
        if self.decision in {"PASS", "PASS_WITH_OBSERVATIONS"} and (
            not self.tests_repeated
            or not self.evidence
            or self.required_changes
            or self.regressions
            or self.security_findings
        ):
            raise ValueError("Passing QA requires repeated tests, evidence and no required fixes")
        return self
