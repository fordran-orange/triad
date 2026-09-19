"""Triad-owned rollups assembled only from canonical, same-product evidence.

Snapshots and recovery links append history; GET handlers never rewrite evidence.
Historical missing timestamps/epochs remain unknown, not backdated guesses.
"""

import hashlib
import json

from trading_core.cycle_records import CycleRecord
from trading_core.intelligence.records import Records
from trading_core.orchestrator import Orchestrator
from trading_core.store import Store
from trading_core.work import State, WorkItem, now, uid


class CycleHistory:
    def __init__(self, store=None):
        store = store or Store(scope="triad")
        if store.scope not in {None, "triad"}:
            raise PermissionError("Triad cycle history is product private")
        self.store = Store(store.settings, scope="triad")
        self.records = Records(self.store)
        self.host = Records(Store(store.settings))

    def list(self):
        latest = {}
        for row in self.records.list("CycleRecord"):
            prior = latest.get(row["cycle_id"])
            if not prior or row["recorded_at"] > prior["recorded_at"]:
                latest[row["cycle_id"]] = row
        for link in self.records.list("CycleRelationship"):
            if link["cycle_id"] in latest:
                latest[link["cycle_id"]][link["relation"]] = link["target_cycle_id"]
        return sorted(latest.values(), key=lambda r: r.get("created_at") or "", reverse=True)

    def link(self, source, target, relation):
        if relation not in {"superseded_by_cycle_id", "recovered_by_cycle_id"} or source == target:
            raise ValueError("Invalid cycle relationship")
        rows = {r["cycle_id"]: r for r in self.list()}
        if source not in rows or target not in rows:
            raise KeyError("Both cycles must be canonical Triad records")
        if relation == "recovered_by_cycle_id" and rows[target]["status"] != "COMPLETED":
            raise ValueError("Recovery requires completed cycle evidence")
        if rows[source].get(relation):
            if rows[source][relation] == target:
                return
            raise ValueError("An existing relationship cannot be replaced")
        self.host.append(
            "CycleRelationship",
            {
                "cycle_id": source,
                "target_cycle_id": target,
                "relation": relation,
                "created_at": now().isoformat(),
            },
            owner="triad",
        )

    def parent(self, cycle_id, historical=False):
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM core.work_items WHERE owner='triad' AND mission_id=%s AND payload->>'work_type'='cycle_record'",
                (cycle_id,),
            ).fetchall()
        if rows:
            return rows[0]["payload"]["work_item_id"]
        work = WorkItem(
            owner="triad",
            mission_id=cycle_id,
            work_type="cycle_record",
            title="Cycle evidence: " + cycle_id[:100],
            authority_tier=0,
            description=(
                "Historical evidence anchor created now; does not backdate execution."
                if historical
                else "Cycle lifecycle evidence anchor; no execution authority."
            ),
            allowed_tools=(),
            allowed_paths=(),
            execution_permissions=(),
            review_required=False,
        )
        return self.store.create(work).work_item_id

    def blocked(
        self,
        *,
        cycle_id=None,
        mode="REAL",
        scheduled=False,
        code="TRIAD_PROVIDER_GATE_FAILED",
        gate=None,
    ):
        cycle_id = cycle_id or uid()
        timestamp = now()
        parent = self.parent(cycle_id)
        host = Orchestrator(store=self.store)
        work = self.store.get(parent)
        if work.status == State.CREATED:
            work = host.advance(work, State.VALIDATING, "Cycle gate evaluation")
            host.advance(
                work, State.BLOCKED, "Cycle blocked by execution gate", failure_reason=code
            )
        record = CycleRecord(
            cycle_id=cycle_id,
            product="triad",
            cycle_type="ROTATION",
            execution_mode=mode,
            status="BLOCKED",
            created_at=timestamp,
            blocked_at=timestamp,
            finished_at=timestamp,
            parent_work_item_id=parent,
            scheduled=scheduled,
            control_epoch=self.host.ledger.control()["epoch"],
            failure_code=code,
            provider_gate_result=gate or {"status": "BLOCKED", "reason": code},
            failures=({"code": code},),
            recovery_action="Restore provider verification or resolve the recorded governance gate, then explicitly submit a new cycle.",
        )
        self._save(record)
        return cycle_id

    def _save(self, record):
        payload = record.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(
                {k: v for k, v in payload.items() if k != "recorded_at"}, sort_keys=True
            ).encode()
        ).hexdigest()
        identifier = "cycle-record-" + digest
        with self.host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (record.cycle_id,))
            if conn.execute(
                "SELECT 1 FROM core.intelligence_records WHERE id=%s", (identifier,)
            ).fetchone():
                return identifier
            return self.host.append(
                "CycleRecord", payload, owner="triad", identifier=identifier, conn=conn
            )

    def capture(self, cycle_id, *, status=None, error=None, cycle_type=None, execution_mode=None):
        prior = next((r for r in self.list() if r["cycle_id"] == cycle_id), {})
        with self.store.connect() as conn:
            works = [
                r["payload"]
                for r in conn.execute(
                    "SELECT payload FROM core.work_items WHERE owner='triad' AND mission_id=%s",
                    (cycle_id,),
                ).fetchall()
            ]
            ids = [w["work_item_id"] for w in works]
            rows = conn.execute(
                "SELECT id,kind,payload,created_at,work_item_id FROM core.day3_records WHERE owner='triad' AND kind NOT IN ('CycleRecord','CycleRelationship') AND (payload->>'mission_id'=%s OR payload->>'cycle_id'=%s OR work_item_id=ANY(%s) OR payload->>'work_item_id'=ANY(%s)) ORDER BY created_at",
                (cycle_id, cycle_id, ids, ids),
            ).fetchall()
        if not rows and not works:
            raise KeyError(cycle_id)
        records = [
            {
                **r["payload"],
                "id": r["id"],
                "kind": r["kind"],
                "work_item_id": r["work_item_id"] or r["payload"].get("work_item_id"),
                "stored_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

        def kinds(*names):
            return [r for r in records if r["kind"] in names]

        legacy = kinds("Cycle")
        summaries = kinds("CycleSummary")
        summary = summaries[-1] if summaries else (legacy[-1].get("summary", {}) if legacy else {})
        merges = kinds("ProductMerge")
        builds = kinds("ProductBuild", "ProductBuildFailure", "ImplementationRun")
        qa = kinds("ProductQA", "QARun")
        # QA and debt may refer to build IDs rather than mission/work directly.
        build_ids = {r.get("implementation_id") or r.get("implementation_run_id") for r in builds}
        build_ids.discard(None)
        for row in self.records.list("QARun"):
            if row.get("implementation_run_id") in build_ids and row["id"] not in {
                r["id"] for r in qa
            }:
                qa.append(row)
        qa_ids = {r.get("qa_id") or r.get("qa_run_id") or r["id"] for r in qa}
        debts = [r for r in self.records.list("QualityDebt") if r.get("source_qa_run") in qa_ids]
        resolutions = self.records.list("QualityDebtResolution")
        for debt in debts:
            debt["resolutions"] = [r for r in resolutions if r.get("quality_debt_id") == debt["id"]]
        usages = kinds("Usage")
        final_status = status or (
            "COMPLETED"
            if merges
            else legacy[-1]["status"]
            if legacy
            else "BLOCKED"
            if kinds("ProductBuildFailure")
            or any(w["status"] in {"FAILED", "BLOCKED"} for w in works)
            else "CANCELLED"
            if any(w["status"] == "CANCELLED" for w in works)
            else "REJECTED"
            if any(w["status"] == "REJECTED" for w in works)
            else prior.get("status", "IN_PROGRESS")
        )
        failures = [{"code": f, "source": summary.get("id")} for f in summary.get("failures", ())]
        failures += [
            {
                "code": r.get("error_class") or r.get("failure_reason"),
                "work_item_id": r.get("work_item_id"),
                "source": r["id"],
            }
            for r in kinds("ProductBuildFailure")
        ]
        failures += [
            {"code": w.get("failure_reason") or w["status"], "work_item_id": w["work_item_id"]}
            for w in works
            if w["status"] in {"FAILED", "BLOCKED", "CANCELLED", "REJECTED"}
            and w["work_type"] != "cycle_record"
        ]
        for failure in prior.get("failures", ()):
            if failure not in failures:
                failures.append(failure)
        if error:
            failures.append({"code": error})
        events = kinds("Event")
        starts = [r["timestamp"] for r in events if r.get("event") == "cycle_started"]
        ends = [r["timestamp"] for r in events if r.get("event") == "cycle_completed"]
        started = (
            min(starts)
            if starts
            else min((w["started_at"] for w in works if w.get("started_at")), default=None)
        )
        finished = merges[-1].get("recorded_at") if merges else max(ends, default=None)
        finished = finished or prior.get("finished_at")
        if final_status == "BLOCKED" and not finished:
            finished = max(
                (
                    w["completed_at"]
                    for w in works
                    if w.get("completed_at") and w["work_type"] != "cycle_record"
                ),
                default=None,
            )
        if error:
            finished = now().isoformat()
        epochs = [
            r.get("epoch")
            for r in records
            if r["kind"] == "RunAuthority" and r.get("epoch") is not None
        ]
        proposal_rows = kinds("ProductProposal", "ImprovementProposal", "Proposal")
        product_proposals = kinds("ProductProposal")
        selected = product_proposals[-1].get("proposal") if product_proposals else None
        if not selected:
            selected_ids = {r.get("proposal_id") for r in kinds("Change")}
            selected = next(
                (r for r in reversed(proposal_rows) if r.get("proposal_id") in selected_ids), None
            )
        product_cycle = kinds("ProductCycle")
        created = min([r["stored_at"] for r in records] + [w["created_at"] for w in works])
        mode = (
            "REAL"
            if product_cycle or merges
            else legacy[-1].get("mode", "UNKNOWN")
            if legacy
            else "UNKNOWN"
        )
        mode = execution_mode or prior.get("execution_mode") or mode
        gate_failed = any(
            "CredentialsOrModelNotConfigured" in str(f) or "PROVIDER_GATE" in str(f)
            for f in failures
        )
        blocked_code = (
            "TRIAD_PROVIDER_GATE_FAILED"
            if gate_failed
            else (failures[-1]["code"] if failures else prior.get("failure_code"))
        )
        parent = next(
            (w["work_item_id"] for w in works if w["work_type"] == "cycle_record"), None
        ) or self.parent(cycle_id, historical=True)
        record = CycleRecord(
            cycle_id=cycle_id,
            product="triad",
            cycle_type=cycle_type
            or prior.get("cycle_type")
            or ("PRODUCT_BUILD" if product_cycle or merges else "ROTATION"),
            execution_mode=mode,
            status=final_status,
            created_at=prior.get("created_at") or created,
            started_at=prior.get("started_at") or started,
            finished_at=finished,
            parent_work_item_id=parent,
            control_epoch=epochs[0] if epochs else prior.get("control_epoch"),
            scheduled=prior.get("scheduled")
            if prior.get("scheduled") is not None
            else product_cycle[0].get("schedule_enabled")
            if product_cycle
            else legacy[-1].get("scheduled")
            if legacy
            else None,
            agents_run=tuple(dict.fromkeys(r["agent"] for r in usages)),
            work_items=tuple(
                {
                    k: w.get(k)
                    for k in (
                        "work_item_id",
                        "title",
                        "assigned_agent",
                        "status",
                        "created_at",
                        "started_at",
                        "completed_at",
                        "failure_reason",
                    )
                }
                for w in works
                if w["work_type"] != "cycle_record"
            ),
            provider_runs=tuple(usages),
            candidate_improvements=tuple(kinds("ProductCandidate")),
            proposals=tuple(proposal_rows),
            selected_proposal=selected,
            implementation_runs=tuple(builds),
            qa_runs=tuple(qa),
            correction_runs=tuple(r for r in kinds("ProductBuild") if r.get("correction")),
            reviews=tuple(kinds("AutonomousReview", "ProductQA")),
            disagreements=tuple(kinds("Disagreement")),
            changes_accepted=tuple(r["implementation_id"] for r in merges)
            or tuple(summary.get("changes_accepted", ())),
            changes_rejected=tuple(summary.get("changes_rejected", ())),
            changes_rolled_back=tuple(summary.get("changes_rolled_back", ())),
            tests=tuple(
                dict.fromkeys(
                    [t for r in kinds("ProductQA") for t in r.get("checks", {}).get("checks", ())]
                    + list(summary.get("tests", ()))
                )
            ),
            failures=tuple(failures),
            lessons=tuple(summary.get("lessons", ())),
            quality_debt=tuple(debts),
            billing_sources=tuple(sorted({r.get("billing_source", "UNKNOWN") for r in usages})),
            api_cost=sum(r["estimated_cost"] for r in usages if r.get("billing_source") == "API")
            if all(r.get("usage_known") for r in usages if r.get("billing_source") == "API")
            else None,
            subscription_usage=tuple(
                r for r in usages if r.get("billing_source") == "SUBSCRIPTION"
            ),
            local_usage=tuple(r for r in usages if r.get("billing_source") == "LOCAL"),
            merge_commit=merges[-1]["git"]["merge_commit"] if merges else None,
            product_state_before={"base_commit": merges[-1]["git"].get("base_commit")}
            if merges
            else {"status": "Historical state not recorded"},
            product_state_after={
                "merge_commit": merges[-1]["git"]["merge_commit"],
                "artifacts": merges[-1].get("hashes", {}),
            }
            if merges
            else {"status": final_status},
            next_cycle_candidates=tuple(summary.get("next_cycle_candidates", ())),
            failure_code=blocked_code if final_status == "BLOCKED" else None,
            blocked_at=(prior.get("blocked_at") or finished) if final_status == "BLOCKED" else None,
            provider_gate_result=prior.get("provider_gate_result")
            or {
                "status": "FAILED",
                "source": "historical failure evidence",
                "failures": failures,
            }
            if gate_failed
            else prior.get("provider_gate_result"),
            recovery_action="Resolve recorded failure and explicitly submit a new cycle; original failure remains preserved."
            if final_status == "BLOCKED"
            else None,
            evidence_ids=tuple(r["id"] for r in records),
            provenance_notes=(
                "Rollup captured from canonical evidence; missing historical fields remain unknown.",
                "Subscription usage is tokens, not an invented monetary charge.",
            ),
        )
        self._save(record)
        return record.model_dump(mode="json")

    def backfill(self):
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind IN ('Cycle','ProductCycle')"
            ).fetchall()
        ids = {r["payload"].get("cycle_id") or r["payload"].get("mission_id") for r in rows}
        return [self.capture(identifier) for identifier in sorted(ids) if identifier]
