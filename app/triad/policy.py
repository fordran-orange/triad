"""Pure policy contracts, not an OS security boundary or an execution engine."""

import hashlib
import json
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

WORKER_TASKS = frozenset(
    {
        "summarization",
        "log_analysis",
        "classification",
        "tagging",
        "retrieval_preparation",
        "context_compression",
        "housekeeping",
    }
)


class RiskLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_order_notional: float = Field(default=0, ge=0, le=0)
    max_gross_exposure: float = Field(default=0, ge=0, le=0)
    max_daily_loss: float = Field(default=0, ge=0, le=0)


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str = Field(min_length=1)
    role: Literal["triad_member", "local_worker"]
    model: str = Field(min_length=1)
    reasoning_depth: Literal["low", "medium", "high"] = "low"
    tools: frozenset[Literal["read_docs", "read_logs", "read_canonical", "write_scratch"]] = (
        frozenset()
    )
    data_scope: frozenset[Literal["docs", "logs", "canonical", "scratch"]] = frozenset()
    execution_permissions: frozenset[Literal["read", "write_scratch"]] = frozenset({"read"})
    risk_limits: RiskLimits = Field(default_factory=RiskLimits)
    compute_tokens: int = Field(default=4096, ge=0, le=32768)
    compute_seconds: int = Field(default=60, ge=0, le=300)
    live_trading_authority: Literal[False] = False
    tasks: frozenset[str] = frozenset()

    @model_validator(mode="after")
    def scope_and_worker_limits(self):
        scopes = {
            "read_docs": "docs",
            "read_logs": "logs",
            "read_canonical": "canonical",
            "write_scratch": "scratch",
        }
        for tool in self.tools:
            if scopes[tool] not in self.data_scope:
                raise ValueError(f"{tool} requires matching data scope")
        if "write_scratch" in self.tools and "write_scratch" not in self.execution_permissions:
            raise ValueError("scratch writes require explicit permission")
        if self.role == "local_worker":
            if not self.tasks <= WORKER_TASKS:
                raise ValueError("local worker may only perform helper tasks")
            if self.compute_tokens > 8192 or self.compute_seconds > 120:
                raise ValueError("local worker exceeds Day 1 compute ceiling")
            if "canonical" in self.data_scope:
                raise ValueError("local worker has no direct canonical market-data scope on Day 1")
        return self


class RuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: Intent
    intent_sha256: str
    approved_by: str
    version: Literal[1] = 1


class TrustedPrincipal(BaseModel):
    """Must come from a future authenticated host adapter, never agent-supplied JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    subject: str = Field(min_length=1)
    kind: Literal["human", "agent"]


def compile_policy(intent: Intent, *, principal: TrustedPrincipal) -> RuntimePolicy:
    if principal.kind != "human":
        raise PermissionError("Agents may request authority; only a human may approve intent")
    # Revalidate at boundary, including instances built with model_construct/model_copy.
    validated = Intent.model_validate(intent.model_dump())
    body = validated.model_dump(mode="json")
    for key, value in body.items():
        if isinstance(value, list):
            body[key] = sorted(value)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return RuntimePolicy(intent=validated, intent_sha256=digest, approved_by=principal.subject)


class AuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str
    reason: str = Field(min_length=1)
    requested_intent: Intent
    status: Literal["pending_human_review"] = "pending_human_review"


class PolicyStore(Protocol):
    def current(self, agent_id: str) -> RuntimePolicy: ...


class AuthorityRequestQueue(Protocol):
    def submit(self, request: AuthorityRequest) -> str: ...


class ToolAuthorizer(Protocol):
    def authorize(self, policy: RuntimePolicy, tool: str, resource: str) -> bool: ...
