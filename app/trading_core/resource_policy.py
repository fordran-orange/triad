"""Host-owned resource allocations, progress evidence and extension decisions.

Allocation is separate from authority. Callers observe progress only after an
authorized operation succeeds; model claims never count as progress evidence.
"""

import hashlib
import json
from enum import StrEnum

from pydantic import AwareDatetime, Field

from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.store import Store
from trading_core.work import Record, now, uid


class ResourceType(StrEnum):
    REASONING = "MORE_REASONING_BUDGET"
    INPUT = "MORE_INPUT_CONTEXT"
    OUTPUT = "MORE_OUTPUT_BUDGET"
    TIME = "MORE_TIME"
    TOOLS = "MORE_TOOL_CALLS"


DEFAULT_ALLOCATIONS = {
    ResourceType.REASONING: 8192,
    ResourceType.INPUT: 24000,
    ResourceType.OUTPUT: 6144,
    ResourceType.TIME: 480,
    ResourceType.TOOLS: 60,
}


class ResourceExtensionRequest(Record):
    request_id: str = Field(default_factory=uid)
    run_id: str
    work_item_id: str
    agent_id: str
    resource_type: ResourceType
    current_allocation: int = Field(ge=0)
    requested_additional: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)
    progress_evidence: tuple[str, ...]
    remaining_acceptance_criteria: tuple[str, ...]
    requested_at: AwareDatetime = Field(default_factory=now)


class ResourceBlocked(RuntimeError):
    status = "BLOCKED_RESOURCE_LIMIT"
    error_class = "ResourceExtensionBlocked"

    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision["reason"])


def scope_digest(work):
    fields = (
        "work_item_id",
        "owner",
        "mission_id",
        "assigned_agent",
        "reviewer",
        "authority_tier",
        "allowed_tools",
        "allowed_paths",
        "forbidden_paths",
        "execution_permissions",
        "acceptance_criteria",
        "description",
        "work_type",
        "expected_outputs",
        "parent_work_item_id",
        "risk_class",
        "affects_money",
        "affects_trading",
        "alters_permissions",
    )
    return hashlib.sha256(
        json.dumps(work.model_dump(mode="json", include=set(fields)), sort_keys=True).encode()
    ).hexdigest()


class ResourceSession:
    """One host run. No API accepts caller-supplied grants or progress records."""

    def __init__(self, ledger, request, allocations, *, billing_source, day=None):
        self.ledger, self.request, self.day = ledger, request, day
        self.host = Records(Store(ledger.store.settings))
        self.work = ledger.store.get(request.work_item_id)
        if request.agent_id not in {self.work.assigned_agent, self.work.reviewer}:
            raise PermissionError("Resource identity must match the assigned worker or reviewer")
        self.initial = {ResourceType(k): v for k, v in allocations.items()}
        if set(self.initial) != set(ResourceType) or any(
            type(v) is not int or v < 1 for v in self.initial.values()
        ):
            raise ValueError("Every resource requires a positive initial allocation")
        self.scope = scope_digest(self.work)
        self.billing_source = billing_source
        self._guard()
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (request.run_id,))
            if self._rows(conn, "ResourceAllocation"):
                raise PermissionError("A run cannot reset its resource allocation")
            self._append(
                conn,
                "ResourceAllocation",
                {
                    "allocations": self.initial,
                    "scope_digest": self.scope,
                    "control_epoch": request.control_epoch,
                    "billing_source": billing_source,
                    "status": "RUNNING",
                    "created_at": now().isoformat(),
                },
            )

    def _guard(self):
        self.ledger.guard(self.request.agent_id, self.work.work_item_id, self.request.control_epoch)
        work = self.ledger.store.get(self.work.work_item_id)
        if scope_digest(work) != self.scope or work.status not in {
            "IN_PROGRESS",
            "AWAITING_REVIEW",
        }:
            raise PermissionError("Work scope or execution state changed")

    def _rows(self, conn, kind):
        return conn.execute(
            "SELECT id,payload FROM core.intelligence_records WHERE kind=%s "
            "AND payload->>'run_id'=%s ORDER BY created_at,id",
            (kind, self.request.run_id),
        ).fetchall()

    def _append(self, conn, kind, payload):
        return self.host.append(
            kind,
            {
                **payload,
                "run_id": self.request.run_id,
                "work_item_id": self.work.work_item_id,
                "agent_id": self.request.agent_id,
            },
            owner=self.work.owner,
            conn=conn,
        )

    def observe(self, kind, fingerprint):
        """Trusted executor callback: digest a successful, scope-checked observation."""
        if kind not in {"authorized_read", "valid_proposal", "test_result", "accepted_context"}:
            raise ValueError("Unsupported host progress source")
        digest = hashlib.sha256((kind + ":" + fingerprint).encode()).hexdigest()
        self._guard()
        with self.host.store.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (self.request.run_id,)
            )
            if any(r["payload"]["digest"] == digest for r in self._rows(conn, "ResourceProgress")):
                return None
            return self._append(
                conn,
                "ResourceProgress",
                {
                    "source": kind,
                    "digest": digest,
                    "observed_at": now().isoformat(),
                },
            )

    def allocation(self, resource_type):
        resource_type = ResourceType(resource_type)
        with self.host.store.connect() as conn:
            grants = self._rows(conn, "ResourceExtensionDecision")
        return self.initial[resource_type] + sum(
            r["payload"]["granted_amount"]
            for r in grants
            if r["payload"]["resource_type"] == resource_type
        )

    def ensure(self, resource_type, required, *, reason="Initial allocation reached"):
        resource_type = ResourceType(resource_type)
        if type(required) is not int or required < 0:
            raise ValueError("Resource measurement must be a nonnegative integer")
        self._guard()
        with self.host.store.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (self.request.run_id,)
            )
            decisions = [r["payload"] for r in self._rows(conn, "ResourceExtensionDecision")]
            denied = next((d for d in decisions if d["decision"] != "ALLOW"), None)
            if denied:
                raise ResourceBlocked(denied)
            current = self.initial[resource_type] + sum(
                d["granted_amount"] for d in decisions if d["resource_type"] == resource_type
            )
            if required <= current:
                return current
            used = {e for d in decisions for e in d["progress_evidence"]}
            progress = tuple(
                r["id"] for r in self._rows(conn, "ResourceProgress") if r["id"] not in used
            )
            additional = max(required - current, self.initial[resource_type])
            request = ResourceExtensionRequest(
                run_id=self.request.run_id,
                work_item_id=self.work.work_item_id,
                agent_id=self.request.agent_id,
                resource_type=resource_type,
                current_allocation=current,
                requested_additional=additional,
                reason=reason,
                progress_evidence=progress,
                remaining_acceptance_criteria=self.work.acceptance_criteria,
            )
            self._append(
                conn,
                "ResourceRunState",
                {
                    "status": "RESOURCE_THRESHOLD_REACHED",
                    "resource_type": resource_type,
                    "observed_at": now().isoformat(),
                },
            )
            self._append(conn, "ResourceExtensionRequest", request.model_dump(mode="json"))
            self._append(
                conn,
                "ResourceRunState",
                {
                    "status": "EXTENSION_REQUESTED",
                    "request_id": request.request_id,
                    "observed_at": now().isoformat(),
                },
            )
            decision, explanation = "ALLOW", "New host-observed progress within the same assignment"
            if not progress:
                decision, explanation = (
                    "DENY",
                    "No new progress; repeated evidence cannot extend a run",
                )
            elif len(decisions) >= 8 or additional > self.initial[resource_type]:
                decision, explanation = (
                    "REQUIRE_HUMAN_APPROVAL",
                    "Extension exceeds automatic review envelope",
                )
            elif self.billing_source not in {"SUBSCRIPTION", "LOCAL"}:
                decision, explanation = (
                    "REQUIRE_HUMAN_APPROVAL",
                    "Additional cost requires an explicit cost reservation",
                )
            if decision == "ALLOW":
                try:
                    self.ledger.reserve(
                        self.request.agent_id,
                        self.work.work_item_id,
                        day=self.day,
                        tokens=additional
                        if resource_type
                        in {ResourceType.INPUT, ResourceType.OUTPUT, ResourceType.REASONING}
                        else 0,
                        seconds=additional if resource_type == ResourceType.TIME else 0,
                        billing_source=self.billing_source,
                    )
                    self._guard()
                except Stopped:
                    raise
                except PermissionError:
                    decision, explanation = (
                        "DENY",
                        "Existing governance or cost policy rejected the extension",
                    )
            result = {
                "request_id": request.request_id,
                "decision": decision,
                "resource_type": resource_type,
                "granted_amount": additional if decision == "ALLOW" else 0,
                "reason": explanation,
                "policy_rules": [
                    "same_work_and_authority",
                    "fresh_host_progress",
                    "bounded_extensions",
                    "existing_cost_policy",
                ],
                "progress_evidence": progress,
                "decided_at": now().isoformat(),
            }
            self._append(conn, "ResourceExtensionDecision", result)
            self._append(
                conn,
                "ResourceRunState",
                {
                    "status": "RUNNING_EXTENDED"
                    if decision == "ALLOW"
                    else "BLOCKED_RESOURCE_LIMIT",
                    "request_id": request.request_id,
                    "observed_at": now().isoformat(),
                },
            )
        if decision != "ALLOW":
            raise ResourceBlocked(result)
        return current + additional
