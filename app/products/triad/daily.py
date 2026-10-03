"""Triad daily lifecycle and evidence-reviewed human debriefs.

Trusted host methods only. Model content cannot publish itself, mark a cycle
complete, or grant scheduling authority. Canonical snapshots append history.
"""

import hashlib
import json
from datetime import timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, WithJsonSchema, model_validator
from trading_core.cycle_records import CycleRecord
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import Record, WorkItem, now, uid

from products.triad.cycle_history import CycleHistory

GAIN = Literal["NONE", "LOW", "MEDIUM", "HIGH", "TRANSFORMATIVE"]
TOMORROW_KEYS = (
    "new_capability",
    "more_important",
    "less_important",
    "changed_assumption",
    "new_dependency",
    "risk_to_monitor",
    "next_cycle",
)
TERMINAL = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
NEXT = {
    "CREATED": {"INSPECTING"},
    "INSPECTING": {"SELECTING"},
    "SELECTING": {"BUILDING", "VERIFYING"},
    "BUILDING": {"AWAITING_QA"},
    "AWAITING_QA": {"CORRECTING", "MERGING"},
    "CORRECTING": {"AWAITING_QA"},
    "MERGING": {"VERIFYING"},
    "VERIFYING": {"INSPECTING", "DEBRIEFING"},
    "DEBRIEFING": {"COMPLETED"},
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Effect(Record):
    order: Literal[1, 2, 3]
    classification: Literal["OBSERVED", "EXPECTED", "HYPOTHESIZED"]
    description: str = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)


class Contribution(Record):
    model: str
    agent: str
    role: str
    changed: str
    reason: str
    why_you_care: str
    effects: tuple[Effect, ...] = Field(min_length=1)
    strategic_gain: str
    debt_introduced: tuple[str, ...]
    debt_retired: tuple[str, ...]
    qa_result: str
    evidence: tuple[str, ...] = Field(min_length=1)


class Debt(Record):
    category: Literal[
        "Technical",
        "Architectural",
        "Product",
        "Research",
        "Data",
        "Security",
        "Operational",
        "UX",
        "Governance",
    ]
    change: Literal["INTRODUCED", "RETIRED"]
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    description: str
    cause: str
    consequence: str
    owner: str
    follow_up: str
    evidence: tuple[str, ...] = Field(min_length=1)


class Debrief(Record):
    debrief_id: str = Field(default_factory=uid)
    cycle_id: str
    date: str
    overall_status: str
    created_at: AwareDatetime = Field(default_factory=now)
    started_at: AwareDatetime
    finished_at: AwareDatetime
    primary_improvement: str
    product_area: str
    builder: str
    qa_reviewer: str
    corrections: tuple[str, ...]
    merge_status: str
    major_risks: tuple[str, ...]
    contributions: tuple[Contribution, ...] = Field(min_length=1)
    proposed_gain: GAIN
    gain_reason: str
    gain_evidence: tuple[str, ...] = Field(min_length=1)
    capability_gained: str
    constraint_removed: str
    debt: tuple[Debt, ...]
    debt_introduced_statement: str = Field(min_length=1)
    debt_retired_statement: str = Field(min_length=1)
    net_effect: dict[str, str]
    # Advertise the existing required answers before vendor strict-schema
    # conversion closes objects. Keep the stored dictionary shape compatible.
    what_changed_about_tomorrow: Annotated[
        dict[str, str],
        WithJsonSchema(
            {
                "type": "object",
                "properties": {key: {"type": "string", "minLength": 1} for key in TOMORROW_KEYS},
                "required": list(TOMORROW_KEYS),
                "additionalProperties": {"type": "string"},
            }
        ),
    ]
    failures: tuple[str, ...]
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete(self):
        required = set(TOMORROW_KEYS)
        if not required <= self.what_changed_about_tomorrow.keys() or any(
            not self.what_changed_about_tomorrow[k].strip() for k in required
        ):
            raise ValueError("What changed about tomorrow requires all seven answers")
        if self.finished_at < self.started_at:
            raise ValueError("Debrief duration cannot be negative")
        if any(not any(e.order == 1 for e in c.effects) for c in self.contributions):
            raise ValueError("Each actual model contribution requires a first-order effect")
        return self


class DailySchedule(Record):
    enabled: bool = False
    time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "America/Chicago"
    days: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6)

    @model_validator(mode="after")
    def valid(self):
        ZoneInfo(self.timezone)
        if (
            not self.days
            or len(set(self.days)) != len(self.days)
            or any(type(d) is not int or not 0 <= d <= 6 for d in self.days)
        ):
            raise ValueError("Choose distinct weekdays 0 through 6")
        return self


class Daily:
    def __init__(self, store=None):
        store = store or Store()
        if store.scope is not None:
            raise PermissionError("Daily lifecycle changes require the trusted host")
        self.host = Records(store)
        self.product = Records(Store(store.settings, scope="triad"))
        self.history = CycleHistory(store)

    def create(self, *, scheduled=False, cycle_id=None, expected_epoch=None, schedule_id=None):
        control = self.product.ledger.guard(epoch=expected_epoch)
        if scheduled:
            config = self.schedule()
            if not schedule_id or config.get("id") != schedule_id or not config["enabled"]:
                raise PermissionError("Scheduled authority was disabled or replaced")
            if expected_epoch != config["control_epoch"]:
                raise PermissionError("Scheduled authority epoch differs")
            policies = self.host.list("ProductCyclePolicy")
            if policies and config.get("product_policy_id") != policies[-1]["id"]:
                raise PermissionError(
                    "Scheduled authority requires acceptance of the current product policy"
                )
        cycle_id = cycle_id or uid()
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (cycle_id,))
            if any(r["cycle_id"] == cycle_id for r in self.product.list("CycleRecord", conn=conn)):
                raise ValueError("Cycle already exists; reconcile rather than replay")
            parent = self.product.store.create(
                WorkItem(
                    owner="triad",
                    mission_id=cycle_id,
                    work_type="cycle_record",
                    title="Daily cycle evidence: " + cycle_id[:100],
                    description="Canonical daily lifecycle anchor; no execution authority.",
                    authority_tier=0,
                    allowed_tools=(),
                    allowed_paths=(),
                    execution_permissions=(),
                    review_required=False,
                ),
                conn=conn,
            ).work_item_id
            record = CycleRecord(
                cycle_id=cycle_id,
                product="triad",
                cycle_type="DAILY_PRODUCT",
                execution_mode="REAL",
                status="CREATED",
                created_at=now(),
                control_epoch=control["epoch"],
                scheduled=scheduled,
                parent_work_item_id=parent,
            )
            self.host.append(
                "CycleRecord", record.model_dump(mode="json"), owner="triad", conn=conn
            )
            self.host.append(
                "DailyCycleTransition",
                {
                    "cycle_id": cycle_id,
                    "from": None,
                    "to": "CREATED",
                    "timestamp": record.created_at.isoformat(),
                    "evidence": ["parent:" + parent],
                },
                owner="triad",
                conn=conn,
            )
        return record

    def current(self, cycle_id, conn=None):
        rows = [r for r in self.product.list("CycleRecord", conn=conn) if r["cycle_id"] == cycle_id]
        if not rows:
            raise KeyError(cycle_id)
        return rows[-1]

    def refresh(self, cycle_id):
        """Append actual evidence while preserving every lifecycle authority field."""
        snapshot = self.history.capture(cycle_id, snapshot_only=True)
        fields = {
            "agents_run",
            "work_items",
            "provider_runs",
            "candidate_improvements",
            "proposals",
            "implementation_runs",
            "qa_runs",
            "correction_runs",
            "reviews",
            "disagreements",
            "changes_accepted",
            "changes_rejected",
            "changes_rolled_back",
            "tests",
            "failures",
            "quality_debt",
            "billing_sources",
            "api_cost",
            "subscription_usage",
            "local_usage",
            "product_state_before",
            "product_state_after",
            "evidence_ids",
            "provenance_notes",
        }
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (cycle_id,))
            prior = self.current(cycle_id, conn)
            if prior["status"] in TERMINAL:
                raise PermissionError("Terminal daily evidence cannot be replaced")
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            payload.update({k: snapshot[k] for k in fields}, recorded_at=now())
            record = CycleRecord.model_validate(payload)
            self.host.append(
                "CycleRecord", record.model_dump(mode="json"), owner="triad", conn=conn
            )
        return record

    def transition(self, cycle_id, state, evidence, **updates):
        if not evidence:
            raise ValueError("A transition requires actual evidence")
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (cycle_id,))
            prior = self.current(cycle_id, conn)
            if prior["status"] in TERMINAL or state not in NEXT.get(prior["status"], set()) | {
                "BLOCKED",
                "FAILED",
                "CANCELLED",
            }:
                raise PermissionError("Invalid or terminal cycle transition")
            if state not in {"BLOCKED", "FAILED", "CANCELLED"}:
                self.product.ledger.guard(
                    work_id=prior["parent_work_item_id"], epoch=prior["control_epoch"]
                )
            if set(updates) - {
                "selected_proposal",
                "implementation_runs",
                "qa_runs",
                "correction_runs",
                "merge_commit",
                "verified_revision",
                "failures",
                "agents_run",
                "tests",
                "provider_runs",
                "billing_sources",
            }:
                raise PermissionError("Transition cannot replace cycle identity or authority")
            if prior["status"] == "SELECTING" and state == "VERIFYING":
                from products.triad.no_change import require_no_change

                turns = [
                    r
                    for r in self.product.list("ProductTurn", conn=conn)
                    if r.get("mission_id") == cycle_id
                ]
                if not turns or turns[-1].get("outcome") != "NO_CHANGE":
                    raise PermissionError("Skipping a build requires an approved no-change turn")
                require_no_change(self.host, turns[-1], prior, conn)
                if updates.get("verified_revision") != turns[-1]["verified_revision"]:
                    raise PermissionError("No-change verification revision mismatch")
            if state == "COMPLETED":
                if updates:
                    raise PermissionError("Completion cannot alter the verified snapshot")
                self.require_complete(cycle_id, prior, conn)
            stamp = now()
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            payload.update(updates, status=state, recorded_at=stamp)
            if state == "INSPECTING" and not prior.get("started_at"):
                payload["started_at"] = stamp
            if state in TERMINAL:
                payload["finished_at"] = stamp
            if state == "BLOCKED":
                payload["blocked_at"] = stamp
                payload["failure_code"] = str(evidence[0])
            record = CycleRecord.model_validate(payload)
            self.host.append(
                "CycleRecord", record.model_dump(mode="json"), owner="triad", conn=conn
            )
            self.host.append(
                "DailyCycleTransition",
                {
                    "cycle_id": cycle_id,
                    "from": prior["status"],
                    "to": state,
                    "timestamp": stamp.isoformat(),
                    "evidence": list(evidence),
                },
                owner="triad",
                conn=conn,
            )
        return record

    def require_turns_complete(self, cycle_id, prior=None, conn=None):
        return self.require_turn_prefix(cycle_id, prior, conn, complete=True)

    def require_turn_prefix(self, cycle_id, prior=None, conn=None, *, complete=False):
        """Validate every retained turn; partial evidence can never complete a cycle."""
        prior = prior or self.current(cycle_id, conn)
        programs = [
            r
            for r in self.product.list("SequentialDailyProgram", conn=conn)
            if r["cycle_id"] == cycle_id
        ]
        if not programs:
            raise PermissionError("Sequential program required")
        if programs:
            turns = [
                r
                for r in self.product.list("ProductTurn", conn=conn)
                if r.get("mission_id") == cycle_id
            ]
            order = ["CODEX", "CLAUDE", "GROK"]
            expected = order if complete else order[: len(turns)]
            if (
                len(turns) > 3
                or [r.get("agent") for r in turns] != expected
                or any(r.get("status") != "COMPLETED" for r in turns)
            ):
                raise PermissionError(
                    "All three provider turns must finish before daily completion"
                )
            for turn in turns:
                if turn.get("outcome") == "NO_CHANGE":
                    from products.triad.no_change import require_no_change

                    require_no_change(self.host, turn, prior, conn)
                    continue
                implementation = self.host.get(turn["implementation_id"], conn=conn)
                work = self.host.store.get(implementation["work_item_id"], conn=conn)
                required_reviewer = {"CODEX": "CLAUDE", "CLAUDE": "GROK", "GROK": "CODEX"}
                if (
                    implementation["owner"] != "triad"
                    or implementation["builder"] != turn["agent"]
                    or work.owner != "triad"
                    or work.mission_id != cycle_id
                    or work.parent_work_item_id != prior["parent_work_item_id"]
                    or work.assigned_agent != turn["agent"]
                    or turn["reviewer"] != required_reviewer[turn["agent"]]
                ):
                    raise PermissionError("Daily turn does not belong to this cycle and provider")
                merges = [
                    r
                    for r in self.product.list("ProductMerge", conn=conn)
                    if r.get("mission_id") == cycle_id
                    and r.get("implementation_id") == turn["implementation_id"]
                    and r.get("qa_id") == turn["qa_id"]
                    and r.get("git", {}).get("change_commit") == implementation["change_commit"]
                    and r.get("git", {}).get("merge_commit") == turn["merge_commit"]
                ]
                rollbacks = [
                    r
                    for r in self.product.list("ProductRollback", conn=conn)
                    if r.get("implementation_id") == turn["implementation_id"]
                ]
                if not merges or rollbacks:
                    raise PermissionError("Daily turn lacks its exact retained merge")
                reviewed = Quality(self.host).require_pass(
                    turn["implementation_id"],
                    implementation["change_commit"],
                    conn=conn,
                )
                if reviewed["id"] != turn["qa_id"] or reviewed["qa_agent"] != turn["reviewer"]:
                    raise PermissionError("Daily turn QA is stale or mismatched")
                if programs[-1].get("acceptance_contract") == "required-checks-v1":
                    from trading_core.product_changes import acceptance_problems

                    refs = [
                        e.removeprefix("acceptance-review:")
                        for e in reviewed["evidence"]
                        if e.startswith("acceptance-review:")
                    ]
                    if len(refs) != 1:
                        raise PermissionError("Daily turn requires mandatory-check evidence")
                    accepted = self.host.get(refs[0], conn=conn)
                    approved = self.host.get(accepted["approval_id"], conn=conn)
                    if (
                        accepted["kind"] != "ProductAcceptanceReview"
                        or accepted["owner"] != "triad"
                        or accepted["cycle_id"] != cycle_id
                        or accepted["qa_id"] != reviewed["id"]
                        or accepted["implementation_id"] != turn["implementation_id"]
                        or accepted["commit"] != implementation["change_commit"]
                        or accepted["reviewer"] != turn["reviewer"]
                        or approved["kind"] != "ProductTurnApproval"
                        or approved["owner"] != "triad"
                        or approved["cycle_id"] != cycle_id
                        or accepted["required"] != approved["proposal"]["acceptance"]
                    ):
                        raise PermissionError("Daily acceptance evidence mismatch")
                    proofs = {
                        key: self.host.get(key, conn=conn) for key in accepted["test_record_ids"]
                    }
                    if (
                        len(proofs) != 2
                        or any(
                            p["kind"] != "EngineeringTestRun"
                            or p["owner"] != "triad"
                            or p.get("commit") != accepted["commit"]
                            or p.get("status") != "PASS"
                            for p in proofs.values()
                        )
                        or acceptance_problems(
                            accepted["required"], accepted["assessment"], accepted["commit"], proofs
                        )
                    ):
                        raise PermissionError("Daily turn has missing mandatory verification")
                checks = [
                    r
                    for r in self.product.list("DailyVerification", conn=conn)
                    if r["cycle_id"] == cycle_id
                    and r.get("agent") == turn["agent"]
                    and r.get("merge_commit") == turn["merge_commit"]
                ]
                if not checks or checks[-1].get("status") != "PASS":
                    raise PermissionError(
                        "Each daily turn requires successful deployment verification"
                    )
        return turns

    def require_complete(self, cycle_id, prior=None, conn=None):
        prior = prior or self.current(cycle_id, conn)
        if any(
            r["cycle_id"] == cycle_id
            for r in self.product.list("SequentialDailyProgram", conn=conn)
        ):
            self.require_turns_complete(cycle_id, prior, conn)
        verification = [
            r
            for r in self.product.list("DailyVerification", conn=conn)
            if r["cycle_id"] == cycle_id and r.get("merge_commit") == prior.get("merge_commit")
        ]
        publications = [
            r
            for r in self.product.list("DailyDebriefPublication", conn=conn)
            if r["cycle_id"] == cycle_id
        ]
        turns = [
            r
            for r in self.product.list("ProductTurn", conn=conn)
            if r.get("mission_id") == cycle_id
        ]
        last_unchanged = bool(
            turns
            and turns[-1].get("outcome") == "NO_CHANGE"
            and prior.get("verified_revision") == turns[-1]["verified_revision"]
        )
        if last_unchanged:
            from products.triad.no_change import require_no_change

            require_no_change(self.host, turns[-1], prior, conn)
        if not publications or (
            not last_unchanged
            and (
                not prior.get("merge_commit")
                or not verification
                or verification[-1].get("status") != "PASS"
            )
        ):
            raise PermissionError(
                "Completion requires post-merge verification and reviewed debrief"
            )
        published = publications[-1]
        review = Quality(self.host).require_pass(
            published["implementation_id"], published["reviewed_commit"], conn=conn
        )
        if review["id"] != published["qa_id"]:
            raise PermissionError("Debrief publication QA is superseded")
        return published

    def _blocked_debrief_format_repair(self, cycle_id, prior, run_id, conn):
        """Bind explicit operator recovery to a completed reporting-only refusal."""
        def record(kind, identifier, work_id=None):
            row = conn.execute(
                "SELECT payload,work_item_id FROM core.day3_records WHERE kind=%s AND owner='triad' "
                "AND payload->>'run_id'=%s ORDER BY created_at DESC LIMIT 1",
                (kind, identifier),
            ).fetchone()
            if not row or (work_id and row["work_item_id"] != work_id):
                return {}
            if kind == "AgentRunRequest" and row["work_item_id"] != row["payload"].get("work_item_id"):
                return {}
            return row["payload"]

        request = record("AgentRunRequest", run_id)
        result = record("AgentRunResult", run_id, request.get("work_item_id"))
        usage = record("Usage", run_id, request.get("work_item_id"))
        previous = request.get("context_packet", {}).get("previous_run_id")
        original = record("AgentRunRequest", previous)
        original_result = record("AgentRunResult", previous, original.get("work_item_id"))
        original_usage = record("Usage", previous, original.get("work_item_id"))
        original_context = original.get("context_packet", {})
        artifact = request.get("context_packet", {}).get("original_artifact")
        tomorrow_schema = original_context.get("schema", {}).get("properties", {}).get(
            "what_changed_about_tomorrow", {}
        )
        retries = self.product.list(
            "ProductResponseRetry",
            matching={"mission_id": cycle_id, "previous_run_id": previous},
            conn=conn,
        )
        failure = (prior.get("failures") or [{}])[-1]
        eligible = (
            prior.get("failure_code") == "PermissionError"
            and result.get("status") == "BLOCKED"
            and usage.get("status") == "SUCCESS"
            and usage.get("agent") == "CLAUDE"
            and original_usage.get("status") == "SUCCESS"
            and original_usage.get("agent") == "CLAUDE"
            and original_result.get("analysis_artifacts") == [artifact]
            and original_context.get("cycle", {}).get("cycle_id") == cycle_id
            and original_context.get("cycle", {}).get("verified_revision") == prior.get("verified_revision")
            and set(original_context.get("required_tomorrow_keys", [])) == set(TOMORROW_KEYS)
            and tomorrow_schema.get("type") == "object"
            and tomorrow_schema.get("additionalProperties") == {"type": "string"}
            and not tomorrow_schema.get("properties")
            and "What changed about tomorrow requires all seven answers"
                in request.get("context_packet", {}).get("validation_errors", "")
            and failure.get("message") == ("Provider blocked this assignment: " + result.get("summary", ""))[:500]
            and request.get("objective", "").startswith("Repair only the response format of the supplied complete artifact.")
            and original.get("objective", "").startswith("Write a candid Daily Debrief using supplied actual evidence.")
            and all(
                r.get("mission_id") == cycle_id
                and r.get("agent_id") == "CLAUDE"
                and r.get("role") == "REVIEW"
                and r.get("execution_permissions") == ["read"]
                and r.get("control_epoch") == prior.get("control_epoch")
                and set(r.get("allowed_tools", [])) <= {"read_file"}
                and not r.get("allowed_paths")
                for r in (request, original)
            )
            and request.get("context_packet", {}).get("schema", {}).get("title") == "Debrief"
            and any(
                r.get("agent") == "CLAUDE" and r.get("recovery_mode") == "FORMAT_REPAIR"
                and r.get("failure_category") == "SCHEMA" for r in retries
            )
        )
        if eligible:
            for r in (request, original):
                work = self.host.store.get(r["work_item_id"], conn=conn)
                eligible = eligible and (
                    str(work.status) == "FAILED" and work.mission_id == cycle_id
                    and work.assigned_agent == "CLAUDE" and work.work_type == "review"
                    and work.authority_tier == 0
                    and work.owner == "triad"
                    and work.parent_work_item_id == prior.get("parent_work_item_id")
                    and tuple(work.execution_permissions) == ("read",)
                    and set(work.allowed_tools) <= {"read_file"}
                    and not work.allowed_paths
                )
        if not eligible:
            raise PermissionError("Blocked debrief format-repair evidence does not match")
        return True

    def resume_debrief(self, cycle_id, *, blocked_format_repair_run_id=None):
        """Operator recovery of reporting only; never replays a build or merge."""
        from trading_core.product_changes import active_policy

        if self.host.store.scope is not None:
            raise PermissionError("Core host recovery required")
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (cycle_id,))
            prior = self.current(cycle_id, conn)
            history = [
                r for r in self.product.list("CycleRecord", conn=conn) if r["cycle_id"] == cycle_id
            ]
            active = [r for r in history if r["status"] not in TERMINAL]
            blocked_format_repair = (
                self._blocked_debrief_format_repair(cycle_id, prior, blocked_format_repair_run_id, conn)
                if blocked_format_repair_run_id else False
            )
            rejected_runtime_result = (
                prior.get("failure_code") == "ProviderError"
                and prior.get("failures", [{}])[-1].get("message") == "InvalidRuntimeResult"
            )
            review_exhausted = prior.get("failure_code") == "PermissionError" and any(
                r.get("message")
                in {
                    "Recovered debrief did not pass independent review",
                    "Daily debrief did not pass independent review",
                }
                for r in prior.get("failures", ())
            )
            if review_exhausted:
                commits = {
                    "debrief:" + r["digest"]
                    for r in self.product.list("DailyDebriefDraft", conn=conn)
                    if r["cycle_id"] == cycle_id
                }
                reviews = [
                    r
                    for r in self.product.list("QARun", conn=conn)
                    if r.get("reviewed_commit") in commits
                ]
                review_exhausted = bool(reviews and reviews[-1]["decision"] == "CHANGES_REQUIRED")
            if (
                prior["status"] != "BLOCKED"
                or (
                    prior.get("failure_code")
                    not in {"ProductResponseFormatError", "UniqueViolation"}
                    and not review_exhausted
                    and not rejected_runtime_result
                    and not blocked_format_repair
                )
                or not active
                or active[-1]["status"] != "DEBRIEFING"
            ):
                raise PermissionError(
                    "Only a blocked reporting error or independently requested correction may resume"
                )
            self.product.ledger.guard(
                work_id=prior["parent_work_item_id"], epoch=prior["control_epoch"]
            )
            programs = [
                r
                for r in self.product.list("SequentialDailyProgram", conn=conn)
                if r["cycle_id"] == cycle_id
            ]
            if not programs or programs[-1]["policy_id"] != active_policy(self.host)["id"]:
                raise PermissionError("Cycle policy changed; debrief recovery denied")
            self.require_turns_complete(cycle_id, prior, conn)
            self.host.ledger.put(
                "ControlAction",
                {
                    "action": "resume_verified_cycle_debrief",
                    "cycle_id": cycle_id,
                    "prior_status": prior["status"],
                    "prior_failure": prior.get("failures"),
                    "merge_commit": prior["merge_commit"],
                    "blocked_format_repair_run_id": blocked_format_repair_run_id,
                },
                conn=conn,
            )
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            payload.update(
                status="DEBRIEFING",
                finished_at=None,
                blocked_at=None,
                failure_code=None,
                recorded_at=now(),
            )
            record = CycleRecord.model_validate(payload)
            self.host.append(
                "CycleRecord", record.model_dump(mode="json"), owner="triad", conn=conn
            )
            return record

    def draft(self, debrief):
        debrief = Debrief.model_validate(debrief)
        cycle = self.current(debrief.cycle_id)
        self.product.ledger.guard(
            work_id=cycle["parent_work_item_id"], epoch=cycle["control_epoch"]
        )
        if cycle["status"] != "DEBRIEFING":
            raise PermissionError("Debrief follows post-merge verification")
        payload = debrief.model_dump(mode="json")
        self.host.append(
            "DailyDebriefDraft",
            {"debrief": payload, "digest": digest(payload), "cycle_id": debrief.cycle_id},
            owner="triad",
            identifier=debrief.debrief_id,
        )
        return debrief.debrief_id

    def publish(self, draft_id, implementation_id, *, classification, reason, reviewer_action):
        if (
            classification not in {"NONE", "LOW", "MEDIUM", "HIGH", "TRANSFORMATIVE"}
            or reviewer_action not in {"CONFIRM", "DOWNGRADE", "UPGRADE_WITH_EVIDENCE", "DISAGREE"}
            or not reason
        ):
            raise ValueError("Independent strategic assessment required")
        self.product.ledger.guard()
        draft = self.product.get(draft_id)
        if draft["kind"] != "DailyDebriefDraft" or digest(draft["debrief"]) != draft["digest"]:
            raise PermissionError("Debrief hash does not match")
        cycle = self.current(draft["cycle_id"])
        self.product.ledger.guard(
            work_id=cycle["parent_work_item_id"], epoch=cycle["control_epoch"]
        )
        if cycle["status"] != "DEBRIEFING":
            raise PermissionError("Only an active debriefing cycle may publish")
        commit = "debrief:" + draft["digest"]
        qa = Quality(self.host).require_pass(implementation_id, commit)
        assessment = digest(
            {"classification": classification, "reason": reason, "action": reviewer_action}
        )
        if "strategic-assessment:" + assessment not in qa["evidence"]:
            raise PermissionError("Final gain must match the independent QA evidence")
        if qa["owner"] != "triad":
            raise PermissionError("Wrong product QA")
        return self.host.append(
            "DailyDebriefPublication",
            {
                "cycle_id": draft["cycle_id"],
                "draft_id": draft_id,
                "digest": draft["digest"],
                "implementation_id": implementation_id,
                "qa_id": qa["id"],
                "reviewed_commit": commit,
                "classification": classification,
                "reason": reason,
                "reviewer_action": reviewer_action,
                "published_at": now().isoformat(),
                "qa_status": qa["decision"],
            },
            owner="triad",
        )

    def debriefs(self):
        rows = []
        for pub in self.product.list("DailyDebriefPublication"):
            draft = self.product.get(pub["draft_id"])
            qa = Quality(self.host).require_pass(pub["implementation_id"], pub["reviewed_commit"])
            if qa["id"] == pub["qa_id"] and draft["digest"] == digest(draft["debrief"]):
                rows.append(
                    {
                        **draft["debrief"],
                        **pub,
                        "cycle_status": self.current(pub["cycle_id"])["status"],
                    }
                )
        return list(reversed(rows))

    def schedule(self):
        rows = self.product.list("DailySchedule")
        return rows[-1] if rows else {**DailySchedule().model_dump(), "effective_after": None}

    def configure(self, config):
        with self.host.store.lease("triad-daily-schedule-slot"):
            return self._configure(config)

    def _configure(self, config):
        config = DailySchedule.model_validate(config)
        control = self.product.ledger.guard()
        prerequisite = None
        policy_id = None
        if config.enabled:
            if self.host.list("ProductCyclePolicy"):
                from trading_core.product_changes import active_policy

                policy_id = active_policy(self.host)["id"]
            accepted_programs = {
                r["cycle_id"]
                for r in self.product.list("SequentialDailyProgram")
                if r["policy_id"] == policy_id
            }
            cycles = [
                r
                for r in self.history.list()
                if r["cycle_type"] == "DAILY_PRODUCT"
                and r["execution_mode"] == "REAL"
                and r["status"] == "COMPLETED"
                and r["scheduled"] is False
                and (policy_id is None or r["cycle_id"] in accepted_programs)
            ]
            if not cycles:
                raise PermissionError("A completed manual REAL daily cycle is required")
            prerequisite = cycles[0]["cycle_id"]
            self.require_complete(prerequisite)
        stamp = now()
        next_day = stamp.astimezone(ZoneInfo(config.timezone)).date() + timedelta(days=1)
        return self.host.append(
            "DailySchedule",
            {
                **config.model_dump(mode="json"),
                "updated_at": stamp.isoformat(),
                "control_epoch": control["epoch"],
                "effective_after": next_day.isoformat(),
                "manual_prerequisite": prerequisite,
                "product_policy_id": policy_id,
            },
            owner="triad",
        )
