from trading_core.resources import resource

"""Host-owned registry and deterministic policy evaluation."""

import json
from pathlib import Path, PureWindowsPath

from trading_core.work import Agent, PolicyDecision, WorkItem

LOCAL_TASKS = frozenset(
    {
        "summarize_journal",
        "classify_logs",
        "extract_metadata",
        "tag_documents",
        "prepare_context",
        "compress_history",
        "duplicate_notes",
        "search_keywords",
        "organize_material",
    }
)
TIER_TOOLS = {
    0: {"read_file"},
    1: {"read_file", "write_artifact", "verify_docs"},
    2: {"read_file", "write_artifact", "verify_docs"},
    3: {"read_file", "write_artifact", "verify_docs"},
}
PROTECTED = (
    "app/triad",
    "app/trading_core",
    "app/platform_host",
    "config",
    "backups",
    ".env",
    ".git",
    ".venv",
    "control-plane",
    "agents",
    "infrastructure",
    "tools",
    "app/triad/control.py",
    "app/triad/policy.py",
    "app/triad/gateway.py",
    "app/triad/store.py",
    "app/triad/orchestrator.py",
    "app/triad/api.py",
)


def relative_path(value: str) -> str:
    value = value.replace("\\", "/")
    parts = value.split("/")
    if (
        not value
        or value.startswith("/")
        or PureWindowsPath(value).drive
        or ":" in value
        or any(p in {"", ".", ".."} or p.endswith((" ", ".")) for p in parts)
        or any(c in value for c in "*?\x00")
        or PureWindowsPath(value).is_reserved()
    ):
        raise PermissionError("Only explicit relative paths without traversal are allowed")
    return value


def beneath(path: str, prefix: str) -> bool:
    return path.casefold() == prefix.casefold() or path.casefold().startswith(
        prefix.casefold() + "/"
    )


class Registry:
    def __init__(self, path: Path | None = None):
        path = path or resource("config/core/agents.json")
        data = json.loads(path.read_text())
        entries = [Agent.model_validate(a) for a in data["agents"]]
        self.agents = {a.agent_id: a for a in entries}
        self.rotation = tuple(data.get("review_order", data.get("rotation", [])))
        if len(entries) != len(self.agents) or len(set(self.rotation)) != len(self.rotation):
            raise ValueError("Duplicate registry entries")
        if len(self.rotation) < 2 or any(
            a not in self.agents
            or not self.agents[a].review_eligible
            or self.agents[a].role != "member"
            for a in self.rotation
        ):
            raise ValueError("Rotation requires distinct review-eligible members")

    def successor(self, agent: str) -> str:
        if agent not in self.rotation:
            return self.rotation[0]
        return self.rotation[(self.rotation.index(agent) + 1) % len(self.rotation)]

    def route(self, work: WorkItem) -> tuple[str, str]:
        if work.assigned_agent:
            return work.assigned_agent, "Explicit operator assignment, subject to policy validation"
        if work.work_type in LOCAL_TASKS and work.risk_class == "LOW" and work.authority_tier == 0:
            helpers = [
                a.agent_id
                for a in self.agents.values()
                if a.role == "helper" and a.enabled and work.work_type in a.capabilities
            ]
            if helpers:
                return helpers[0], "Allowlisted low-risk observe-only helper task; local processing"
        return self.rotation[0], "Member capability/authority required; not routed by price"


class ControlPlane:
    def __init__(self, registry: Registry | None = None):
        self.registry = registry or Registry()

    def evaluate(self, work: WorkItem) -> PolicyDecision:
        agent_id, routing_reason = self.registry.route(work)
        rules = []
        verdict = "REQUIRE_REVIEW" if work.review_required else "ALLOW"
        agent = self.registry.agents.get(agent_id)
        if (
            work.affects_money
            or work.affects_trading
            or work.risk_class == "LIVE"
            or work.authority_tier == 4
        ):
            rules.append("day2_no_money_or_live_trading")
        if not agent or not agent.enabled or not agent.execution_eligible:
            rules.append("agent_unavailable")
        if agent:
            if work.work_type not in agent.capabilities:
                rules.append("capability_not_granted")
            if work.authority_tier > agent.authority_tier:
                rules.append("authority_ceiling")
            if work.reasoning_budget > agent.maximum_reasoning_budget:
                rules.append("reasoning_ceiling")
            if not set(work.allowed_tools) <= set(agent.allowed_tools) & TIER_TOOLS.get(
                work.authority_tier, set()
            ):
                rules.append("tool_not_granted")
            if agent.role == "helper" and (
                work.work_type not in LOCAL_TASKS
                or work.risk_class != "LOW"
                or work.authority_tier != 0
                or work.alters_permissions
            ):
                rules.append("helper_is_not_a_governor_or_decision_member")
        if set(work.execution_permissions) - {"read", "write_research", "write_code", "simulate"}:
            rules.append("execution_permission_not_supported")
        if (
            "write_research" in work.execution_permissions
            and work.authority_tier < 1
            or "write_code" in work.execution_permissions
            and work.authority_tier < 2
            or "simulate" in work.execution_permissions
            and work.authority_tier < 3
        ):
            rules.append("tier_permission_mismatch")
        if (
            "write_artifact" in work.allowed_tools or work.risk_class != "LOW"
        ) and not work.review_required:
            rules.append("mandatory_review")
        if work.review_required:
            reviewer = self.registry.agents.get(work.reviewer or self.registry.successor(agent_id))
            if (
                not reviewer
                or not reviewer.enabled
                or not reviewer.review_eligible
                or reviewer.agent_id == agent_id
            ):
                rules.append("independent_reviewer_required")
        try:
            for scope in (*work.allowed_paths, *work.forbidden_paths):
                relative_path(scope)
            for scope in work.allowed_paths:
                if any(beneath(scope, p) for p in PROTECTED):
                    rules.append("protected_path_scope")
        except PermissionError:
            rules.append("invalid_path_scope")
        if rules:
            verdict = "DENY"
        if work.alters_permissions or work.authority_tier == 5 or work.risk_class == "GOVERNANCE":
            verdict = "REQUIRE_HUMAN_APPROVAL"
            rules.append("governance_human_only_no_day2_approval_endpoint")
        if (
            work.affects_money
            or work.affects_trading
            or work.authority_tier == 4
            or work.risk_class == "LIVE"
        ):
            verdict = "DENY"
        if not rules:
            rules = [
                "bounded_tools",
                "path_scopes",
                "budget_ceiling",
                "review_gate" if work.review_required else "observe_only",
            ]
        return PolicyDecision(
            work_item_id=work.work_item_id,
            decision=verdict,
            reason="; ".join(rules),
            rules_triggered=tuple(rules),
            routed_agent=agent_id,
            routing_reason=work.routing_reason or routing_reason,
        )

    def approve_elevation(self, *, actor: str):
        raise PermissionError(
            "No elevation approval implementation on Day 2; requests stay pending"
        )
