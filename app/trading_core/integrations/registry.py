"""Append-only registry and candidate decisions; public metadata has no secrets."""

import hashlib
import json

from trading_core.integrations.adapters import RobinhoodBrokerAdapter, SchwabBrokerAdapter
from trading_core.integrations.contracts import (
    IntegrationCandidate,
    IntegrationConnection,
    IntegrationRecord,
)
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import now


class ExternalIntegrationRegistry:
    def __init__(self, store=None):
        self.store = store or Store()
        self.records = Records(self.store)
        self.host = Records(Store(self.store.settings))

    def seed(self):
        self.require_host()
        with self.store.lease("external-integration-registry"):
            for adapter in (SchwabBrokerAdapter(), RobinhoodBrokerAdapter()):
                if not any(
                    r["integration_id"] == adapter.definition.integration_id for r in self.catalog()
                ):
                    self.host.append("IntegrationDefinition", adapter.metadata(), owner="core")

    def require_host(self):
        if self.store.scope is not None:
            raise PermissionError("Registry changes require trusted Core operator ingestion")

    def catalog(self):
        # Only global sanitized definitions are shared; product candidates remain private.
        latest = {}
        for row in self.host.list("IntegrationDefinition"):
            if row["owner"] == "core":
                try:
                    clean = IntegrationRecord.model_validate(
                        {k: v for k, v in row.items() if k in IntegrationRecord.model_fields}
                    ).model_dump(mode="json")
                except ValueError:
                    continue  # Quarantined metadata cannot leak through the shared catalog.
                latest[row["integration_id"]] = {**clean, "id": row["id"], "owner": "core"}
        for row in self.host.list("IntegrationConnection"):
            if row["owner"] == "core" and row["integration_id"] in latest:
                item = latest[row["integration_id"]]
                item.update(
                    last_health_check=row["checked_at"],
                    connected=row["connected"],
                    status=row["status"],
                )
                for field in ("last_success", "last_failure"):
                    if row.get(field):
                        item[field] = row[field]
        return list(latest.values())

    def adapter(self, identifier):
        if identifier == "local-canonical":
            from trading_core.integrations.data import LocalCanonicalStore

            return LocalCanonicalStore(self.store)
        factories = {"schwab": SchwabBrokerAdapter, "robinhood": RobinhoodBrokerAdapter}
        if identifier not in factories:
            raise KeyError(identifier)
        return factories[identifier]()

    def check(self, identifier):
        self.require_host()
        result = self.adapter(identifier).health_check()
        connection = IntegrationConnection(
            integration_id=identifier,
            **result,
            last_success=now() if result["connected"] else None,
            last_failure=now() if result["status"] == "FAILED" else None,
        )
        self.host.append("IntegrationConnection", connection.model_dump(mode="json"), owner="core")
        return connection.model_dump(mode="json")

    def propose(self, candidate, *, work_id=None):
        candidate = IntegrationCandidate.model_validate(candidate)
        if candidate.status != "DISCOVERED" or candidate.security_review != "PENDING":
            raise PermissionError("A proposal cannot grant its own approval")
        owner = "core"
        if self.store.scope is not None or work_id:
            if not work_id:
                raise PermissionError("Agent proposal requires its active WorkItem")
            work = self.store.get(work_id)
            if (
                work.status not in {"IN_PROGRESS", "AWAITING_REVIEW"}
                or candidate.proposed_by != work.assigned_agent
            ):
                raise PermissionError("Proposal identity must match active assignment")
            self.records.ledger.guard(work.assigned_agent, work_id)
            owner = work.owner
        payload = candidate.model_dump(mode="json") | {
            "work_item_id": work_id,
            "created_at": now().isoformat(),
            "updated_at": now().isoformat(),
        }
        return self.host.append(
            "IntegrationCandidate", payload, owner=owner, identifier=candidate.candidate_id
        )

    def candidates(self):
        rows = self.records.list("IntegrationCandidate")
        for decision in self.records.list("IntegrationCandidateDecision"):
            for row in rows:
                if row["candidate_id"] == decision["candidate_id"]:
                    row.update(
                        status=decision["status"],
                        security_review=decision["security_review"],
                        updated_at=decision["decided_at"],
                    )
        return rows

    def decide(self, identifier, status, review):
        with self.store.lease("integration-candidate-" + identifier):
            return self._decide(identifier, status, review)

    def _decide(self, identifier, status, review):
        self.require_host()
        rows = {r["candidate_id"]: r for r in self.candidates()}
        candidate = rows[identifier]
        allowed = {
            "DISCOVERED": {"RESEARCHING", "REJECTED"},
            "RESEARCHING": {"APPROVED_FOR_IMPLEMENTATION", "REJECTED"},
            "APPROVED_FOR_IMPLEMENTATION": {"IMPLEMENTED", "REJECTED"},
            "IMPLEMENTED": {"DEPRECATED"},
        }
        if status not in allowed.get(candidate["status"], set()) or not review.strip():
            raise ValueError("A valid lifecycle transition and security review are required")
        if status == "IMPLEMENTED":
            raise PermissionError(
                "Implementation requires a separate reviewed adapter build; approval alone cannot install code"
            )
        return self.host.append(
            "IntegrationCandidateDecision",
            {
                "candidate_id": identifier,
                "status": status,
                "security_review": review,
                "decided_at": now().isoformat(),
            },
            owner=candidate["owner"],
        )

    def mark_implemented(self, identifier, integration_id, implementation_id, commit):
        from trading_core.intelligence.quality import Quality

        self.require_host()
        with self.store.lease("integration-candidate-" + identifier):
            candidate = next(r for r in self.candidates() if r["candidate_id"] == identifier)
            if candidate["status"] != "APPROVED_FOR_IMPLEMENTATION":
                raise PermissionError("Candidate needs a reviewed implementation approval")
            definition = next(r for r in self.catalog() if r["integration_id"] == integration_id)
            build = self.host.get(implementation_id)
            required = set(candidate["capabilities"])
            implemented = {k for k, v in definition["capabilities"].items() if v == "IMPLEMENTED"}
            fingerprint = definition_fingerprint(definition)
            if (
                build["kind"] != "ImplementationRun"
                or build["owner"] != "core"
                or definition["provider"] != candidate["provider"]
                or definition["category"] != candidate["category"]
                or not required
                or not required <= implemented
                or definition.get("candidate_id") != identifier
                or definition.get("implementation_run_id") != implementation_id
                or definition.get("implementation_commit") != commit
                or "integration-candidate:" + identifier not in build["evidence"]
                or "integration-definition-sha256:" + fingerprint not in build["evidence"]
                or not any(
                    path.startswith("app/trading_core/integrations/") for path in build["files"]
                )
            ):
                raise PermissionError(
                    "Implementation and independent QA must cover this exact Core candidate, definition and required capabilities"
                )
            Quality(self.host).require_pass(implementation_id, commit)
            return self.host.append(
                "IntegrationCandidateDecision",
                {
                    "candidate_id": identifier,
                    "status": "IMPLEMENTED",
                    "integration_id": integration_id,
                    "implementation_id": implementation_id,
                    "commit": commit,
                    "security_review": candidate["security_review"],
                    "decided_at": now().isoformat(),
                },
                owner=candidate["owner"],
            )

    def request_use(self, identifier, capability, *, work_id):
        work = self.store.get(work_id)
        self.records.ledger.guard(work.assigned_agent, work_id)
        if work.status not in {"IN_PROGRESS", "AWAITING_REVIEW"}:
            raise PermissionError("Integration request requires an active assignment")
        self.adapter(identifier)  # No dynamic import, installation or credential lookup.
        return self.host.append(
            "IntegrationUseRequest",
            {
                "integration_id": identifier,
                "capability": capability,
                "work_item_id": work_id,
                "requested_at": now().isoformat(),
                "decision": "DENY"
                if capability in {"ORDER_PLACE", "ORDER_CANCEL", "ORDER_REPLACE"}
                else "REQUIRE_HUMAN_APPROVAL",
                "reason": "Separate scoped data authorization required; live execution remains denied",
            },
            owner=work.owner,
        )


def definition_fingerprint(definition):
    excluded = {
        "id",
        "owner",
        "kind",
        "created_at",
        "updated_at",
        "last_health_check",
        "last_success",
        "last_failure",
        "candidate_id",
        "implementation_run_id",
        "implementation_commit",
    }
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in definition.items() if k not in excluded}, sort_keys=True
        ).encode()
    ).hexdigest()
