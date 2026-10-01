"""Owned intake records: content never grants execution authority."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from trading_core.intelligence.records import Records
from trading_core.work import Record, now, uid

IntakeType = Literal["COMMAND", "WORK_REQUEST", "INFORMATION", "OBSERVATION", "IDEA_INJECTION"]


class Submission(Record):
    content: str = Field(min_length=1, max_length=20000)
    destination: Literal["core", "triad"] = "core"
    declared_type: IntakeType | None = None
    links: tuple[str, ...] = Field(default=(), max_length=20)


class IntakeRecord(Submission):
    received_at: str
    channel: Literal["local_api", "core_chat", "internal_observation"]
    source_identity: str
    trust_level: Literal["OPERATOR_AUTHENTICATED", "KNOWN_UNVERIFIED", "UNTRUSTED"]
    raw_ref: str
    content_hash: str
    inferred_type: IntakeType
    effective_type: IntakeType
    obligation: Literal["NONE", "REQUESTED"]
    status: Literal["NEW", "RECEIVED"]
    provenance: dict

    @model_validator(mode="after")
    def authority_is_explicit(self):
        if self.inferred_type == "COMMAND":
            raise ValueError("Inference cannot create command authority")
        if self.effective_type != (self.declared_type or self.inferred_type):
            raise ValueError("An explicit declaration takes precedence")
        if self.effective_type == "COMMAND" and (
            self.declared_type != "COMMAND" or self.trust_level != "OPERATOR_AUTHENTICATED"
        ):
            raise PermissionError("Commands require explicit authenticated operator input")
        expected = "REQUESTED" if self.effective_type in {"COMMAND", "WORK_REQUEST"} else "NONE"
        if self.obligation != expected:
            raise ValueError("Advisory material cannot create an obligation")
        if not self.content.strip():
            raise ValueError("Content must not be blank")
        return self


class Intake:
    def __init__(self, records=None):
        self.records = records or Records()

    def submit(
        self,
        value,
        *,
        authenticated=False,
        channel="internal_observation",
        source="untrusted",
        inferred_type="INFORMATION",
    ):
        if self.records.store.scope is not None:
            raise PermissionError("Core host ingests intake with server-owned provenance")
        value = Submission.model_validate(value)
        # Observations can suggest a classification, never authority.
        if inferred_type == "COMMAND":
            inferred_type = "INFORMATION"
        effective = value.declared_type or inferred_type
        identifier = uid()
        record = IntakeRecord(
            **value.model_dump(),
            received_at=now().isoformat(),
            channel=channel,
            source_identity=source,
            trust_level="OPERATOR_AUTHENTICATED" if authenticated else "UNTRUSTED",
            raw_ref="intake:" + identifier,
            content_hash=hashlib.sha256(value.content.encode()).hexdigest(),
            inferred_type=inferred_type,
            effective_type=effective,
            obligation="REQUESTED" if effective in {"COMMAND", "WORK_REQUEST"} else "NONE",
            status="NEW" if effective == "IDEA_INJECTION" else "RECEIVED",
            provenance={
                "classification": "explicit" if value.declared_type else "inferred",
                "automatic_execution": False,
            },
        )
        return self.records.append(
            "IntakeRecord",
            record.model_dump(mode="json"),
            owner=value.destination,
            identifier=identifier,
        )

    def list(self, owner):
        if owner not in {"core", "triad"}:
            raise PermissionError("Unknown intake destination")
        from trading_core.ownership import require_owner

        require_owner(self.records.store.scope, owner)
        dispositions = {
            r["intake_id"]: r for r in self.records.list("IdeaDisposition") if r["owner"] == owner
        }
        return [
            {**r, "disposition": dispositions.get(r["id"])}
            for r in self.records.list("IntakeRecord")
            if r["owner"] == owner
        ]

    def disposition(self, identifier, status, rationale):
        if self.records.store.scope is not None:
            raise PermissionError("Only the authenticated Core operator records dispositions")
        if not rationale.strip() or len(rationale) > 4000:
            raise ValueError("A short rationale is required")
        with self.records.store.lease("intake-" + identifier):
            row = self.records.get(identifier)
            if row["kind"] != "IntakeRecord" or row["effective_type"] != "IDEA_INJECTION":
                raise PermissionError("Disposition applies only to ideas")
            history = [
                r for r in self.records.list("IdeaDisposition") if r["intake_id"] == identifier
            ]
            prior = history[-1]["status"] if history else "NEW"
            allowed = {
                "NEW": {"CONSIDERING"},
                "CONSIDERING": {"USED", "DEFERRED", "REJECTED"},
                "DEFERRED": {"CONSIDERING"},
            }
            if status not in allowed.get(prior, set()):
                raise ValueError("Invalid idea disposition transition")
            return self.records.append(
                "IdeaDisposition",
                {
                    "intake_id": identifier,
                    "status": status,
                    "actor": "Core operator",
                    "timestamp": now().isoformat(),
                    "rationale": rationale,
                },
                owner=row["owner"],
            )

    def advisory(self, owner):
        return [
            {
                "id": r["id"],
                "content": r["content"],
                "source": r["source_identity"],
                "trust": r["trust_level"],
                "label": "Advisory idea; no obligation. You may use, reinterpret, test, defer, ignore or reject it.",
            }
            for r in self.list(owner)
            if r["effective_type"] == "IDEA_INJECTION"
            and r["obligation"] == "NONE"
            and (r.get("disposition") or {}).get("status", "NEW") in {"NEW", "CONSIDERING"}
        ][-5:]

    def retrieve(self, query):
        # The chat's one retrieval source is Core-owned intake, never another product's records.
        terms = {word.casefold() for word in query.split() if len(word) > 2}
        rows = [
            r
            for r in self.list("core")
            if r["effective_type"] in {"INFORMATION", "OBSERVATION", "IDEA_INJECTION"}
        ]
        ranked = sorted(
            rows,
            key=lambda r: (sum(t in r["content"].casefold() for t in terms), r["received_at"]),
            reverse=True,
        )
        return [
            {
                "id": r["id"],
                "content": r["content"][:1200],
                "excerpt_truncated": len(r["content"]) > 1200,
                "content_hash": r["content_hash"],
                "type": r["effective_type"],
                "obligation": r["obligation"],
            }
            for r in ranked[:3]
        ]
