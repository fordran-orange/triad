"""Triad daily lifecycle and evidence-reviewed human debriefs.

Trusted host methods only. Model content cannot publish itself, mark a cycle
complete, or grant scheduling authority. Canonical snapshots append history.
"""

import hashlib
import json
from datetime import timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator
from trading_core.cycle_records import CycleRecord
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import Record, WorkItem, now, uid

from products.triad.cycle_history import CycleHistory

GAIN = Literal["NONE", "LOW", "MEDIUM", "HIGH", "TRANSFORMATIVE"]
TERMINAL = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
NEXT = {
    "CREATED": {"INSPECTING"},
    "INSPECTING": {"SELECTING"},
    "SELECTING": {"BUILDING"},
    "BUILDING": {"AWAITING_QA"},
    "AWAITING_QA": {"CORRECTING", "MERGING"},
    "CORRECTING": {"AWAITING_QA"},
    "MERGING": {"VERIFYING"},
    "VERIFYING": {"DEBRIEFING"},
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
    what_changed_about_tomorrow: dict[str, str]
    failures: tuple[str, ...]
    evidence: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def complete(self):
        required = {
            "new_capability",
            "more_important",
            "less_important",
            "changed_assumption",
            "new_dependency",
            "risk_to_monitor",
            "next_cycle",
        }
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

    def create(self, *, scheduled=False, cycle_id=None):
        control = self.product.ledger.guard()
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
                "failures",
                "agents_run",
                "tests",
                "provider_runs",
                "billing_sources",
            }:
                raise PermissionError("Transition cannot replace cycle identity or authority")
            if state == "COMPLETED":
                if updates:
                    raise PermissionError("Completion cannot alter the verified snapshot")
                self.require_complete(cycle_id, prior, conn)
            stamp = now()
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            payload.update(updates, status=state, recorded_at=stamp)
            if state == "INSPECTING":
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

    def require_complete(self, cycle_id, prior=None, conn=None):
        prior = prior or self.current(cycle_id, conn)
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
        if (
            not prior.get("merge_commit")
            or not verification
            or verification[-1].get("status") != "PASS"
            or not publications
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
        config = DailySchedule.model_validate(config)
        control = self.product.ledger.guard()
        prerequisite = None
        if config.enabled:
            cycles = [
                r
                for r in self.history.list()
                if r["cycle_type"] == "DAILY_PRODUCT"
                and r["execution_mode"] == "REAL"
                and r["status"] == "COMPLETED"
                and r["scheduled"] is False
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
            },
            owner="triad",
        )
