"""Configured identities and bounded specialization. Agents cannot create authority."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from trading_core.control import PROTECTED, Registry, beneath, relative_path
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.ownership import require_owner
from trading_core.product_identity import canonical_product, same_product
from trading_core.providers.contracts import PREFERRED
from trading_core.store import Store
from trading_core.work import Record, WorkItem, now, uid


class AgentBudget(Record):
    max_output_tokens: int = Field(default=512, ge=1, le=1000000)
    total_output_tokens: int = Field(default=512, ge=1, le=1000000)
    max_runs: int = Field(default=1, ge=1, le=4)
    timeout_seconds: int = Field(default=90, ge=1, le=86400)
    max_cost_usd: float = Field(default=0, ge=0, le=0)

    @model_validator(mode="after")
    def fits(self):
        if self.max_output_tokens > self.total_output_tokens:
            raise ValueError("Per-run output exceeds total agent grant")
        return self


class AgentDefinition(Record):
    agent_id: str = Field(default_factory=lambda: "specialist-" + uid())
    display_name: str
    agent_type: Literal["static", "specialist"]
    purpose: str
    provider: str
    model: str
    preferred_transport: str
    executor_identity: Literal["CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"]
    capabilities: tuple[str, ...]
    role: Literal["member", "helper", "reviewer", "specialist"]
    authority_tier: int = Field(ge=0, le=2)
    allowed_tools: tuple[str, ...]
    execution_permissions: tuple[str, ...] = ("read",)
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...] = PROTECTED
    budget: AgentBudget
    reasoning_budget: int = Field(ge=0, le=1000000)
    review_eligible: bool
    execution_eligible: bool = True
    persistent_or_temporary: Literal["persistent", "temporary"]
    creator: str
    created_at: datetime = Field(default_factory=now)
    status: Literal["ACTIVE", "DISABLED", "TERMINATED", "EXPIRED"] = "ACTIVE"
    parent_agent: str | None = None
    parent_work_item: str | None = None
    delegation_depth: int = Field(default=0, ge=0, le=1)
    expires_at: datetime | None = None
    creation_request: str | None = None


class AgentCreationRequest(Record):
    request_id: str = Field(default_factory=uid)
    requested_by: str
    parent_agent: str
    parent_work_item: str
    proposed_name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=2000)
    required_capabilities: tuple[str, ...]
    preferred_provider: str | None = None
    preferred_model: str | None = None
    required_tools: tuple[str, ...] = ("read_file",)
    required_paths: tuple[str, ...]
    requested_authority: int = Field(default=0, ge=0, le=5)
    budget: AgentBudget = Field(default_factory=AgentBudget)
    reasoning_budget: int = Field(default=512, ge=0, le=1000000)
    lifetime_seconds: int = Field(default=900, ge=1, le=3600)
    persistent_or_temporary: Literal["persistent", "temporary"] = "temporary"
    reason: str = Field(min_length=1, max_length=2000)
    requested_at: datetime | None = None


class DelegationPolicy(Record):
    max_depth: int = 1
    max_children_per_parent: int = 2
    max_total_active_specialists: int = 8
    max_concurrent_runs: int = 4
    max_creation_spend_usd: float = 0
    max_lifetime_seconds: int = 3600


TERMINAL_WORK = {"COMPLETED", "CANCELLED", "FAILED", "REJECTED", "BLOCKED"}


class Agents:
    def __init__(self, records=None):
        self.records = records or Records()
        self.store = self.records.store
        # This is Core host code. Untrusted products/agents only submit structured
        # requests; all privileged writes below follow the scope/policy checks.
        self.host = Records(Store(self.store.settings))
        self.policy = DelegationPolicy()

    def seed_static(self, control):
        if self.store.scope is not None:
            raise PermissionError("Static definitions are Core-owned")
        with self.store.lease("agent-creation"), self.store.connect() as conn:
            for base in Registry().agents.values():
                if conn.execute(
                    "SELECT 1 FROM core.agent_instances WHERE id=%s", (base.agent_id,)
                ).fetchone():
                    continue
                transport = PREFERRED[base.agent_id]
                observed = control.snapshot(transport).get("workitem") or {}
                capabilities = tuple(
                    dict.fromkeys(
                        (
                            *base.capabilities,
                            "structured_output",
                            "document_analysis",
                            "isolated_text_read",
                            "isolated_text_proposal",
                            *(
                                ("local_execution", "private_local_processing")
                                if base.agent_id == "LOCAL_QWEN"
                                else ()
                            ),
                        )
                    )
                )
                definition = AgentDefinition(
                    agent_id=base.agent_id,
                    display_name=base.display_name,
                    agent_type="static",
                    purpose="Configured Core frontier member"
                    if base.role == "member"
                    else "Local observe-only support",
                    provider=base.provider,
                    model=observed.get("actual_model") or base.model,
                    preferred_transport=transport,
                    executor_identity=base.agent_id,
                    capabilities=capabilities,
                    role=base.role,
                    authority_tier=base.authority_tier,
                    allowed_tools=base.allowed_tools,
                    execution_permissions=("read", "write_research")
                    if base.authority_tier >= 1
                    else ("read",),
                    allowed_paths=("docs", "research", "products/triad/docs", "app/products/triad"),
                    budget=AgentBudget(
                        max_output_tokens=6144,
                        total_output_tokens=24576,
                        max_runs=4,
                        timeout_seconds=480,
                    ),
                    reasoning_budget=base.maximum_reasoning_budget,
                    review_eligible=base.review_eligible,
                    execution_eligible=base.execution_eligible,
                    persistent_or_temporary="persistent",
                    creator="Core configuration",
                )
                self._insert(definition, "core", conn)

    def _insert(self, definition, owner, conn):
        from psycopg.types.json import Jsonb

        data = definition.model_dump(mode="json")
        self.host.append(
            "AgentDefinition",
            data,
            owner=owner,
            identifier=uid() if definition.agent_type == "static" else definition.agent_id,
            conn=conn,
        )
        conn.execute(
            "INSERT INTO core.agent_instances(id,owner,definition,status,expires_at,parent_work_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                definition.agent_id,
                owner,
                Jsonb(data),
                definition.status,
                definition.expires_at,
                definition.parent_work_item,
            ),
        )

    def get(self, identifier, *, conn=None):
        if conn is None:
            with self.store.connect() as connection:
                return self.get(identifier, conn=connection)
        row = conn.execute(
            "SELECT * FROM core.agent_instances WHERE id=%s", (identifier,)
        ).fetchone()
        if not row:
            raise KeyError(identifier)
        if not (row["owner"] == "core" and row["definition"]["agent_type"] == "static"):
            require_owner(self.store.scope, row["owner"])
        status = row["status"]
        if row["expires_at"] and row["expires_at"] <= now() and status == "ACTIVE":
            status = "EXPIRED"
        if row["parent_work_id"] and row["definition"]["persistent_or_temporary"] == "temporary":
            parent = conn.execute(
                "SELECT status FROM core.work_items WHERE id=%s", (row["parent_work_id"],)
            ).fetchone()
            if (not parent or parent["status"] in TERMINAL_WORK) and status == "ACTIVE":
                status = "TERMINATED"
        definition = dict(row["definition"])
        if definition["agent_type"] == "static" and identifier in {
            "CODEX",
            "CLAUDE",
            "GROK",
            "LOCAL_QWEN",
        }:
            table = conn.execute("SELECT to_regclass('core.resource_policies') AS name").fetchone()
            policy = (
                conn.execute(
                    "SELECT payload FROM core.resource_policies WHERE version='day7-v1'"
                ).fetchone()
                if table["name"]
                else None
            )
            if policy:
                initial = policy["payload"]
                recorded = definition["budget"]
                effective = dict(recorded)
                for key, old in (("max_output_tokens", 2048), ("timeout_seconds", 120)):
                    if recorded[key] == old:
                        effective[key] = initial[key]
                if (
                    recorded["total_output_tokens"] == 8192
                    and recorded["max_output_tokens"] == 2048
                ):
                    effective["total_output_tokens"] = (
                        initial["max_output_tokens"] * recorded["max_runs"]
                    )
                old_reasoning = 1024 if identifier == "LOCAL_QWEN" else 2048
                definition.update(
                    recorded_budget=definition["budget"],
                    recorded_reasoning_budget=definition["reasoning_budget"],
                    resource_policy_version="day7-v1",
                    budget=effective,
                    reasoning_budget=initial["reasoning_budget"]
                    if definition["reasoning_budget"] == old_reasoning
                    else definition["reasoning_budget"],
                )
        return {
            **definition,
            "owner": row["owner"],
            "status": status,
            "runs_reserved": row["runs_reserved"],
            "tokens_reserved": row["tokens_reserved"],
            "active_runs": row["active_runs"],
        }

    def list(self):
        with self.store.connect() as conn:
            ids = conn.execute(
                "SELECT id FROM core.agent_instances WHERE %s::text IS NULL OR owner=ANY(%s) OR (owner='core' AND definition->>'agent_type'='static') ORDER BY id",
                (self.store.scope, self.store.owner_aliases),
            ).fetchall()
            return [self.get(r["id"], conn=conn) for r in ids]

    def request(self, request: AgentCreationRequest):
        work = self.store.get(request.parent_work_item)
        owner = work.owner
        with self.store.lease("agent-creation"), self.store.connect() as conn:
            parent = self.get(request.parent_agent, conn=conn)
            self.records.ledger.guard(parent["executor_identity"], work.work_item_id)
            binding = conn.execute(
                "SELECT agent_id FROM core.agent_work_bindings WHERE work_id=%s",
                (work.work_item_id,),
            ).fetchone()
            assigned = binding["agent_id"] if binding else work.assigned_agent
            rules = []
            if assigned != request.parent_agent or request.requested_by != assigned:
                rules.append("authenticated_parent_identity_required")
            if (
                work.status != "IN_PROGRESS"
                or parent["status"] != "ACTIVE"
                or not parent["execution_eligible"]
            ):
                rules.append("parent_not_active")
            depth = parent["delegation_depth"] + 1
            if depth > self.policy.max_depth:
                rules.append("delegation_depth")
            if request.requested_authority > min(work.authority_tier, parent["authority_tier"], 2):
                rules.append("authority_ceiling")
            if not set(request.required_tools) <= set(work.allowed_tools) & set(
                parent["allowed_tools"]
            ):
                rules.append("tool_ceiling")
            if not set(request.required_capabilities) <= set(parent["capabilities"]):
                rules.append("agent_capability_ceiling")
            if (
                request.preferred_provider
                and request.preferred_provider != parent["provider"]
                or request.preferred_model
                and request.preferred_model != parent["model"]
            ):
                rules.append("provider_binding_requires_separate_governance")
            try:
                for path in request.required_paths:
                    name = relative_path(path)
                    if (
                        not any(beneath(name, p) for p in work.allowed_paths)
                        or not any(beneath(name, p) for p in parent["allowed_paths"])
                        or any(
                            beneath(name, p)
                            for p in (*PROTECTED, *work.forbidden_paths, *parent["forbidden_paths"])
                        )
                    ):
                        rules.append("path_ceiling")
                if not request.required_paths:
                    rules.append("explicit_paths_required")
            except PermissionError:
                rules.append("invalid_path")
            budget = request.budget
            if (
                budget.max_output_tokens
                > min(work.compute_budget.max_output_tokens, parent["budget"]["max_output_tokens"])
                or budget.timeout_seconds
                > min(work.compute_budget.timeout_seconds, parent["budget"]["timeout_seconds"])
                or request.reasoning_budget > min(work.reasoning_budget, parent["reasoning_budget"])
            ):
                rules.append("budget_ceiling")
            # A per-parent delegation pool is bounded separately from its own run.
            # Reservations are never refunded after creation, preventing churn.
            siblings = conn.execute(
                "SELECT definition FROM core.agent_instances WHERE parent_work_id=%s",
                (work.work_item_id,),
            ).fetchall()
            if len(siblings) >= self.policy.max_children_per_parent:
                rules.append("child_count")
            allocated = sum(r["definition"]["budget"]["total_output_tokens"] for r in siblings)
            if allocated + budget.total_output_tokens > min(
                work.compute_budget.max_output_tokens, parent["budget"]["total_output_tokens"]
            ):
                rules.append("parent_delegation_pool")
            active = conn.execute(
                "SELECT count(*) AS n FROM core.agent_instances WHERE status='ACTIVE' AND definition->>'agent_type'='specialist' AND (expires_at IS NULL OR expires_at>now())"
            ).fetchone()["n"]
            if active >= self.policy.max_total_active_specialists:
                rules.append("active_agent_ceiling")
            decision = (
                "DENY"
                if rules
                else "REQUIRE_HUMAN_APPROVAL"
                if request.persistent_or_temporary == "persistent"
                else "ALLOW"
            )
            if not rules:
                rules = ["bounded_parent_grant", "no_creation_spend", "temporary_lifetime"]
            result = {
                "request_id": request.request_id,
                "decision": decision,
                "reason": "; ".join(rules),
                "rules_triggered": rules,
                "granted_authority": request.requested_authority if decision == "ALLOW" else 0,
                "granted_budget": budget.model_dump() if decision == "ALLOW" else {},
                "granted_tools": request.required_tools if decision == "ALLOW" else (),
                "granted_paths": request.required_paths if decision == "ALLOW" else (),
                "lifetime": request.lifetime_seconds if decision == "ALLOW" else 0,
                "parent_work_item": work.work_item_id,
                "parent_agent": request.parent_agent,
                "evaluated_at": now().isoformat(),
            }
            self.host.append(
                "AgentCreationRequest",
                {
                    **request.model_dump(mode="json"),
                    "requested_at": (request.requested_at or now()).isoformat(),
                },
                owner=owner,
                identifier=request.request_id,
                conn=conn,
            )
            if decision == "ALLOW":
                definition = AgentDefinition(
                    display_name=request.proposed_name,
                    agent_type="specialist",
                    purpose=request.purpose,
                    provider=parent["provider"],
                    model=parent["model"],
                    preferred_transport=parent["preferred_transport"],
                    executor_identity=parent["executor_identity"],
                    capabilities=request.required_capabilities,
                    role="specialist",
                    authority_tier=request.requested_authority,
                    allowed_tools=request.required_tools,
                    execution_permissions=tuple(
                        p
                        for p in work.execution_permissions
                        if p in parent["execution_permissions"]
                    ),
                    allowed_paths=request.required_paths,
                    forbidden_paths=tuple(
                        dict.fromkeys(
                            (*PROTECTED, *work.forbidden_paths, *parent["forbidden_paths"])
                        )
                    ),
                    budget=budget,
                    reasoning_budget=request.reasoning_budget,
                    review_eligible=parent["review_eligible"],
                    persistent_or_temporary="temporary",
                    creator=request.requested_by,
                    parent_agent=request.parent_agent,
                    parent_work_item=work.work_item_id,
                    delegation_depth=depth,
                    expires_at=min(
                        now() + timedelta(seconds=request.lifetime_seconds),
                        datetime.fromisoformat(parent["expires_at"])
                        if parent["expires_at"]
                        else now() + timedelta(seconds=self.policy.max_lifetime_seconds),
                    ),
                    creation_request=request.request_id,
                )
                self._insert(definition, owner, conn)
                result["agent_id"] = definition.agent_id
            self.host.append("AgentCreationDecision", result, owner=owner, conn=conn)
        return result

    def bind_work(self, agent_id, work: WorkItem):
        """Host creates a child assignment; provider identity stays separate from role identity."""
        with self.store.lease("agent-creation"), self.store.connect() as conn:
            agent = self.get(agent_id, conn=conn)
            if (
                agent["agent_type"] != "specialist"
                or agent["status"] != "ACTIVE"
                or not same_product(work.owner, agent["owner"])
            ):
                raise PermissionError("Active owned specialist required")
            if (
                (
                    agent["persistent_or_temporary"] == "temporary"
                    and work.parent_work_item_id != agent["parent_work_item"]
                )
                or work.assigned_agent != agent["executor_identity"]
                or work.authority_tier > agent["authority_tier"]
            ):
                raise PermissionError("Child assignment exceeds its parent identity or authority")
            if not set(work.allowed_tools) <= set(agent["allowed_tools"]) or any(
                not any(beneath(relative_path(p), a) for a in agent["allowed_paths"])
                for p in work.allowed_paths
            ):
                raise PermissionError("Child assignment exceeds tool/path grant")
            if not set(agent["forbidden_paths"]) <= set(work.forbidden_paths):
                raise PermissionError("Child assignment must retain inherited forbidden paths")
            if not set(work.execution_permissions) <= set(agent["execution_permissions"]):
                raise PermissionError("Child assignment exceeds execution grant")
            if (
                work.reasoning_budget > agent["reasoning_budget"]
                or work.compute_budget.max_output_tokens > agent["budget"]["max_output_tokens"]
                or work.compute_budget.timeout_seconds > agent["budget"]["timeout_seconds"]
            ):
                raise PermissionError("Child assignment exceeds agent budget")
            # Work is created before binding only by trusted host; it cannot be run
            # until the caller receives its bound ID. Binding itself is immutable.
            if self.store.get(work.work_item_id).model_dump() != work.model_dump():
                raise PermissionError("Binding requires the exact canonical assignment")
            conn.execute(
                "INSERT INTO core.agent_work_bindings(work_id,agent_id) VALUES (%s,%s)",
                (work.work_item_id, agent_id),
            )
            self.host.append(
                "AgentDelegation",
                {
                    "agent_id": agent_id,
                    "parent_agent": agent["parent_agent"],
                    "parent_work_item": agent["parent_work_item"],
                    "child_work_item": work.work_item_id,
                    "mission_id": work.mission_id,
                    "creation_request": agent["creation_request"],
                },
                owner=work.owner,
                conn=conn,
            )
        return work

    def reserve_run(self, work_id, output_tokens):
        if type(output_tokens) is not int or output_tokens <= 0:
            raise ValueError("A positive bounded output reservation is required")
        with self.store.lease("agent-run-reservation"), self.store.connect() as conn:
            binding = conn.execute(
                "SELECT agent_id FROM core.agent_work_bindings WHERE work_id=%s", (work_id,)
            ).fetchone()
            if not binding:
                return None
            conn.execute(
                "SELECT id FROM core.agent_instances WHERE id=%s FOR UPDATE", (binding["agent_id"],)
            ).fetchone()
            agent = self.get(binding["agent_id"], conn=conn)
            budget = agent["budget"]
            total_active = conn.execute(
                "SELECT COALESCE(sum(active_runs),0) AS n FROM core.agent_instances"
            ).fetchone()["n"]
            if (
                agent["status"] != "ACTIVE"
                or not agent["execution_eligible"]
                or agent["runs_reserved"] >= budget["max_runs"]
                or output_tokens > budget["max_output_tokens"]
                or agent["tokens_reserved"] + output_tokens > budget["total_output_tokens"]
                or total_active >= self.policy.max_concurrent_runs
            ):
                raise PermissionError("Agent lifecycle, quota or concurrency ceiling")
            conn.execute(
                "UPDATE core.agent_instances SET runs_reserved=runs_reserved+1,tokens_reserved=tokens_reserved+%s,active_runs=active_runs+1 WHERE id=%s",
                (output_tokens, agent["agent_id"]),
            )
            self.host.append(
                "AgentRunReservation",
                {
                    "agent_id": agent["agent_id"],
                    "child_work_item": work_id,
                    "output_tokens": output_tokens,
                },
                owner=agent["owner"],
                conn=conn,
            )
        return agent["agent_id"]

    def release_run(self, identifier):
        if identifier is None:
            return
        with self.store.connect() as conn:
            agent = self.get(identifier, conn=conn)
            exhausted = (
                agent["runs_reserved"] >= agent["budget"]["max_runs"]
                or agent["tokens_reserved"] >= agent["budget"]["total_output_tokens"]
            )
            status = "TERMINATED" if exhausted else agent["status"]
            updated = conn.execute(
                "UPDATE core.agent_instances SET active_runs=GREATEST(active_runs-1,0),status=CASE WHEN status='ACTIVE' THEN %s ELSE status END WHERE id=%s RETURNING status",
                (status, identifier),
            ).fetchone()
            self.host.append(
                "AgentLifecycle",
                {
                    "agent_id": identifier,
                    "status": updated["status"],
                    "reason": "Bounded run ended; evidence retained",
                },
                owner=agent["owner"],
                conn=conn,
            )

    def operate(self, identifier, action):
        if self.store.scope is not None or action not in {"disable", "terminate"}:
            raise PermissionError("Lifecycle control requires Core operator authority")
        with self.store.connect() as conn:
            agent = self.get(identifier, conn=conn)
            status = "DISABLED" if action == "disable" else "TERMINATED"
            conn.execute(
                "UPDATE core.agent_instances SET status=%s WHERE id=%s", (status, identifier)
            )
            self.host.append(
                "AgentLifecycle",
                {"agent_id": identifier, "status": status, "reason": "Core operator " + action},
                owner=agent["owner"],
                conn=conn,
            )
        return self.get(identifier)

    def propose_promotion(self, identifier, evidence, reason):
        agent = self.get(identifier)
        if agent["agent_type"] != "specialist" or len(set(evidence)) < 2:
            raise PermissionError("Promotion requires repeated independent usefulness evidence")
        return self.records.append(
            "AgentPromotionRequest",
            {
                "agent_id": identifier,
                "evidence": evidence,
                "reason": reason,
                "status": "REQUIRE_HUMAN_APPROVAL",
            },
            owner=agent["owner"],
        )

    def promote(self, request_id, implementation_id, commit):
        if self.store.scope is not None:
            raise PermissionError("Persistent-agent promotion requires Core operator")
        with self.store.lease("agent-creation"), self.store.connect() as conn:
            request = self.records.get(request_id, conn=conn)
            if request["kind"] != "AgentPromotionRequest":
                raise ValueError("Expected promotion request")
            evidence_ids = request.get("evidence", [])
            if (
                not isinstance(evidence_ids, list)
                or any(not isinstance(e, str) for e in evidence_ids)
                or len(set(evidence_ids)) < 2
            ):
                raise PermissionError("Promotion requires at least two distinct usefulness records")
            old = self.get(request["agent_id"], conn=conn)
            if (
                old["agent_type"] != "specialist"
                or old["persistent_or_temporary"] != "temporary"
                or not same_product(request["owner"], old["owner"])
                or old["status"] == "DISABLED"
            ):
                raise PermissionError("Promotion must belong to an eligible temporary specialist")
            self.records.ledger.guard(old["executor_identity"])
            current_owner = canonical_product(old["owner"])
            product = conn.execute(
                "SELECT paused FROM core.product_controls WHERE product=%s", (current_owner,)
            ).fetchone()
            if product and product["paused"]:
                raise PermissionError("Product is paused")
            active = conn.execute(
                "SELECT count(*) AS n FROM core.agent_instances WHERE status='ACTIVE' AND definition->>'agent_type'='specialist' AND (expires_at IS NULL OR expires_at>now())"
            ).fetchone()["n"]
            if active >= self.policy.max_total_active_specialists:
                raise PermissionError("Active agent ceiling")
            qa = Quality(self.host).require_pass(implementation_id, commit, conn=conn)
            build = self.host.get(implementation_id, conn=conn)
            if build["owner"] != "core" or "promotion:" + request_id not in build["evidence"]:
                raise PermissionError("Promotion needs exact reviewed governance evidence")
            for evidence in evidence_ids:
                run = self.host.get(evidence, conn=conn)
                if (
                    run["kind"] != "ImplementationRun"
                    or run["builder"] != request["agent_id"]
                    or not same_product(run["owner"], old["owner"])
                ):
                    raise PermissionError("Evidence must demonstrate this specialist's work")
                Quality(self.host).require_pass(evidence, run["change_commit"], conn=conn)
            if any(
                r.get("promotion_request") == request_id
                for r in self.host.list("AgentPromotion", conn=conn)
            ):
                raise PermissionError("Promotion already handled")
            data = {k: v for k, v in old.items() if k in AgentDefinition.model_fields}
            definition = AgentDefinition.model_validate(
                {
                    **data,
                    "agent_id": "specialist-" + uid(),
                    "persistent_or_temporary": "persistent",
                    "expires_at": None,
                    "created_at": now(),
                    "status": "ACTIVE",
                }
            )
            self._insert(definition, current_owner, conn)
            self.host.append(
                "AgentPromotion",
                {
                    "agent_id": definition.agent_id,
                    "previous_agent": old["agent_id"],
                    "promotion_request": request_id,
                    "qa_run_id": qa["id"],
                },
                owner=current_owner,
                conn=conn,
            )
        return definition
