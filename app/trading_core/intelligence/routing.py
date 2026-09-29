"""Evidence-based assignment with immutable rationale and dispatch revalidation."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from trading_core.control import ControlPlane, beneath
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.records import Records
from trading_core.ledger import Ledger
from trading_core.orchestrator import Orchestrator
from trading_core.ownership import require_owner
from trading_core.providers.control import ProviderControl
from trading_core.store import Store
from trading_core.work import Record, WorkItem, now


class Requirements(Record):
    capabilities: tuple[str, ...] = ("structured_output",)
    role: Literal["REVIEW", "PROPOSE", "IMPLEMENT", "SUPPORT"]
    privacy: Literal["local_only", "approved_remote"] = "approved_remote"
    context_chars: int = Field(ge=0, le=1000000)
    billing_sources: tuple[Literal["LOCAL", "SUBSCRIPTION", "API"], ...] = ("LOCAL", "SUBSCRIPTION")
    max_cost_usd: float = Field(default=0, ge=0, le=1)
    preferred_agent: str | None = None
    excluded_executors: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=2000)


class Routing:
    def __init__(self, records=None, control=None):
        self.records = records or Records()
        self.store = self.records.store
        self.host = Records(Store(self.store.settings))
        self.agents = Agents(self.records)
        self.control = control or ProviderControl(Ledger(self.host.store))

    def _candidate(self, agent, work, requirements, versions):
        reasons = []
        executor = agent["executor_identity"]
        transport = agent["preferred_transport"]
        policy = self.control.policy(executor)
        snapshot = self.control.snapshot(transport)
        billing = snapshot.get("billing_source", "UNKNOWN")
        capabilities = {
            v["capability"]["capability"]: v
            for v in versions
            if v["capability"]["provider"] == agent["provider"]
            and v["capability"]["model"] == agent["model"]
            and v["capability"]["transport"] == transport
            and v["capability"]["status"] == "AVAILABLE"
            and v["capability"]["verification_status"] == "VERIFIED"
        }
        if not set(requirements.capabilities) <= capabilities.keys():
            reasons.append("Required provider capability lacks current verified evidence")
        if not set(requirements.capabilities) <= set(agent["capabilities"]):
            reasons.append("Configured role does not grant required capabilities")
        if agent["status"] != "ACTIVE":
            reasons.append("Configured agent is inactive")
        elif not agent["execution_eligible"]:
            reasons.append(
                "Provider compatibility evidence is being renewed"
                if agent.get("model_binding_status")
                else "Configured agent is not eligible"
            )
        if executor in requirements.excluded_executors:
            reasons.append("Independent execution identity required")
        if requirements.role == "REVIEW" and not agent["review_eligible"]:
            reasons.append("Agent cannot independently review")
        if executor == "LOCAL_QWEN" and requirements.role != "SUPPORT":
            reasons.append("Local helper is observe-only")
        roles = {
            "codex_cli": {"REVIEW"},
            "claude_code_cli": {"REVIEW", "PROPOSE", "IMPLEMENT"},
            "grok_build_cli": {"REVIEW", "PROPOSE", "IMPLEMENT"},
            "ollama": {"SUPPORT"},
        }
        if transport in roles and requirements.role not in roles[transport]:
            reasons.append("Installed transport does not support this task role")
        if (
            requirements.role in {"PROPOSE", "IMPLEMENT"}
            and "isolated_text_proposal" not in requirements.capabilities
        ):
            reasons.append("Write requests must explicitly require verified proposal capability")
        if requirements.privacy == "local_only" and (
            billing != "LOCAL" or "private_local_processing" not in capabilities
        ):
            reasons.append("Private local processing required")
        if billing not in requirements.billing_sources:
            reasons.append("Billing source is outside this assignment")
        if not self.control.proven(snapshot):
            reasons.append("Transport has no current successful runtime proof")
        if policy.preferred_transport != transport or policy.models.get(transport, "Auto") not in {
            "Auto",
            agent["model"],
        }:
            reasons.append("Provider policy changed since configured definition")
        if (snapshot.get("workitem") or {}).get("actual_model") != agent["model"]:
            reasons.append("Observed model differs from configured definition")
        if (
            work.authority_tier > agent["authority_tier"]
            or not set(work.allowed_tools) <= set(agent["allowed_tools"])
            or not set(work.execution_permissions) <= set(agent["execution_permissions"])
        ):
            reasons.append("Assignment exceeds configured role authority")
        if (
            agent["persistent_or_temporary"] == "temporary"
            and work.parent_work_item_id != agent["parent_work_item"]
        ):
            reasons.append("Temporary specialist belongs to another parent assignment")
        for name in requirements.capabilities:
            if name in capabilities:
                permissions = set(capabilities[name]["capability"]["permissions_required"])
                granted = set(work.execution_permissions)
                if "write_research" in granted or "write_code" in granted:
                    granted.add("write_docs")
                if not permissions <= granted:
                    reasons.append(
                        "Capability requires execution permissions outside this assignment"
                    )
        if any(
            not any(beneath(path, allowed) for allowed in agent["allowed_paths"])
            or any(beneath(path, denied) for denied in agent["forbidden_paths"])
            for path in work.allowed_paths
        ):
            reasons.append("Assignment exceeds configured path grant")
        if (
            work.reasoning_budget > agent["reasoning_budget"]
            or work.compute_budget.max_output_tokens > agent["budget"]["max_output_tokens"]
            or work.compute_budget.timeout_seconds > agent["budget"]["timeout_seconds"]
        ):
            reasons.append("Assignment exceeds configured run budget")
        control = self.host.ledger.control()
        if requirements.context_chars > 1000000:
            reasons.append("Context exceeds the physical serialization ceiling")
        cost = 0.0
        if billing == "API":
            cost = (
                requirements.context_chars * policy.input_price_per_million
                + work.compute_budget.max_output_tokens * policy.output_price_per_million
            ) / 1_000_000
            if (
                policy.api_daily_budget <= 0
                or policy.input_price_per_million <= 0
                or policy.output_price_per_million <= 0
            ):
                reasons.append("API pricing or spending authority unavailable")
        if cost > min(
            requirements.max_cost_usd,
            agent["budget"]["max_cost_usd"],
            control["limits"]["max_cost_run"],
        ):
            reasons.append("Cost exceeds assignment or configured role grant")
        try:
            self.host.ledger.guard(executor, work.work_item_id)
        except PermissionError as exc:
            reasons.append(str(exc))
        candidate = WorkItem.model_validate(
            work.model_dump() | {"assigned_agent": executor, "reviewer": None}
        )
        if ControlPlane().evaluate(candidate).decision not in {"ALLOW", "REQUIRE_REVIEW"}:
            reasons.append("Control Plane rejected the candidate assignment")
        workload = agent["active_runs"]
        for run in self.control.ledger.records("TransportRun", 100):
            if run.get("agent") == executor and run.get("status") == "RUNNING":
                started = datetime.fromisoformat(run["started_at"])
                if (now() - started).total_seconds() < run.get("timeout", 120):
                    workload += 1
        latency = min(
            (
                float(v["capability"]["latency_characteristics"].get("observed_seconds") or 1000000)
                for v in capabilities.values()
            ),
            default=1000000,
        )
        return {
            "agent_id": agent["agent_id"],
            "executor": executor,
            "provider": agent["provider"],
            "model": agent["model"],
            "transport": transport,
            "eligible": not reasons,
            "exclusions": reasons,
            "billing_source": billing,
            "estimated_cost": cost,
            "observed_latency_seconds": None if latency == 1000000 else latency,
            "current_workload": workload,
            "capability_versions": [
                capabilities[c]["id"] for c in requirements.capabilities if c in capabilities
            ],
            "score": (
                int(agent["agent_id"] != requirements.preferred_agent),
                workload,
                cost,
                latency,
                agent["agent_id"],
            ),
        }

    def create(self, work: WorkItem, requirements: Requirements):
        require_owner(self.store.scope, work.owner)
        if work.status != "CREATED" or work.assigned_agent is not None:
            raise ValueError("Routing requires a pristine unassigned WorkItem")
        if requirements.role == "REVIEW" and work.work_type != "review":
            raise ValueError("Separate review assignments must use the review work type")
        self.host.ledger.guard()
        versions = Capabilities(self.records).current()
        candidates = [self._candidate(a, work, requirements, versions) for a in self.agents.list()]
        eligible = sorted((c for c in candidates if c["eligible"]), key=lambda c: c["score"])
        if not eligible:
            self.host.append(
                "CapabilityRoutingDecision",
                {
                    "work_item_id": work.work_item_id,
                    "requirements": requirements.model_dump(mode="json"),
                    "decision": "DENY",
                    "candidates": candidates,
                    "reason": "No authorized verified provider/role fits this task",
                },
                owner=work.owner,
            )
            raise PermissionError("No authorized verified provider/role fits this task")
        selected = eligible[0]
        if requirements.preferred_agent and selected["agent_id"] != requirements.preferred_agent:
            raise PermissionError("Requested agent is not eligible; no silent substitution")
        reason = (
            requirements.reason
            + "; verified capability, bounded authority, transport availability and billing fit; workload/cost/latency used for eligible alternatives"
        )
        assigned = WorkItem.model_validate(
            work.model_dump() | {"assigned_agent": selected["executor"], "routing_reason": reason}
        )
        assigned = Orchestrator(self.store).create(assigned)
        if selected["agent_id"] != selected["executor"]:
            self.agents.bind_work(selected["agent_id"], assigned)
        self.host.append(
            "CapabilityRoutingDecision",
            {
                "work_item_id": assigned.work_item_id,
                "requirements": requirements.model_dump(mode="json"),
                "decision": "ALLOW",
                "selected": selected,
                "candidates": candidates,
                "reason": reason,
                "created_at": now().isoformat(),
            },
            owner=work.owner,
            identifier="route-" + assigned.work_item_id,
        )
        return assigned

    def validate_execution(self, request, adapter):
        try:
            decision = self.records.get("route-" + request.work_item_id)
        except KeyError:
            return None  # Retained legacy assignments still use the existing transport/governance gates.
        work = self.store.get(request.work_item_id)
        requirements = Requirements.model_validate(decision["requirements"])
        selected = decision["selected"]
        if (
            decision["kind"] != "CapabilityRoutingDecision"
            or decision["decision"] != "ALLOW"
            or request.role != requirements.role
            or request.agent_id != selected["executor"]
            or adapter.transport_id != selected["transport"]
        ):
            raise PermissionError("Execution does not match the governed capability route")
        candidate = self._candidate(
            self.agents.get(selected["agent_id"]),
            work,
            requirements,
            Capabilities(self.records).current(),
        )
        if candidate["model"] != selected["model"]:
            raise PermissionError(
                "Verified model changed after assignment; a fresh assignment is required"
            )
        if not candidate["eligible"]:
            raise PermissionError(
                "Capability route is no longer eligible: " + "; ".join(candidate["exclusions"])
            )
        return selected
