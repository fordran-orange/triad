"""Explicit transport identities, policy, and billing."""

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

AGENTS = ("CODEX", "CLAUDE", "GROK", "LOCAL_QWEN")
SPECS = {
    "codex_cli": {
        "agent": "CODEX",
        "provider": "openai",
        "type": "CLI",
        "cli": "codex",
        "docs": "https://developers.openai.com/codex/cli",
    },
    "claude_code_cli": {
        "agent": "CLAUDE",
        "provider": "anthropic",
        "type": "CLI",
        "cli": "claude",
        "docs": "https://code.claude.com/docs/en/setup",
    },
    "grok_build_cli": {
        "agent": "GROK",
        "provider": "xai",
        "type": "CLI",
        "cli": "grok",
        "docs": "https://docs.x.ai/build/overview",
    },
    "openai_api": {"agent": "CODEX", "provider": "openai", "type": "API"},
    "anthropic_api": {"agent": "CLAUDE", "provider": "anthropic", "type": "API"},
    "xai_api": {"agent": "GROK", "provider": "xai", "type": "API"},
    "ollama": {"agent": "LOCAL_QWEN", "provider": "ollama", "type": "LOCAL"},
}
PREFERRED = {a: next(t for t, s in SPECS.items() if s["agent"] == a) for a in AGENTS}


class AgentTransport(Protocol):
    transport_id: str
    agent_id: str
    provider: str
    transport_type: str

    def detect(self): ...
    def install_status(self): ...
    def authenticate(self): ...
    def logout(self): ...
    def health_check(self): ...
    def list_models(self): ...
    def execute(self, request): ...
    def cancel(self): ...
    def usage(self): ...
    def billing_source(self): ...
    def capabilities(self): ...


class ProviderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    agent: Literal["CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"]
    preferred_transport: str
    fallback: Literal["NEVER", "ASK_EACH_TIME", "ALLOW_WITHIN_BUDGET"] = "NEVER"
    models: dict[str, str] = Field(default_factory=dict)
    api_daily_budget: float = Field(default=0, ge=0, le=25)
    input_price_per_million: float = Field(default=0, ge=0, le=1000)
    output_price_per_million: float = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def agent_transports(self):
        valid = {t for t, s in SPECS.items() if s["agent"] == self.agent}
        if self.preferred_transport not in valid or not set(self.models) <= valid:
            raise ValueError("Transport belongs to a different agent")
        if any(
            not m
            or m.startswith("-")
            or len(m) > 120
            or not all(c.isalnum() or c in "-_.:/" for c in m)
            for m in self.models.values()
        ):
            raise ValueError("Invalid model identifier")
        if self.agent == "LOCAL_QWEN" and self.fallback != "NEVER":
            raise ValueError("Local capability cannot route to cloud")
        return self
