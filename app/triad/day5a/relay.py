"""Operator-invoked, read-only documentation relay with independently persisted reviews.

The acceptance mission identifies an improvement; it does not authorize or claim
an implementation/merge. Git evidence records the source HEAD and exact file hashes.
"""

import hashlib
import json

from triad.brain import Brain
from triad.day3.adapters import ProviderError
from triad.day3.contracts import AgentRunRequest, AgentRunResult, Disagreement
from triad.execution import ExecutionServices
from triad.day3.support import support
from triad.day5a.contracts import PREFERRED
from triad.gateway import ToolGateway
from triad.work import ComputeBudget, Handoff, Provenance, Review, State, WorkItem, now, uid

SOURCES = ("README.md", "docs/UI.md")
MISSION = "Review the current Triad operator documentation and identify one bounded usability improvement."


def run_relay(control):
    ledger = control.ledger
    cycles = ExecutionServices(store=ledger.store)
    proof = {
        "relay_id": uid(),
        "mode": "REAL",
        "success": False,
        "status": "RUNNING",
        "started_at": now().isoformat(),
        "mission": MISSION,
        "steps": [],
        "reviews": [],
    }
    main = None
    created = []

    def persist():
        ledger.put(
            "ProviderRelay",
            proof,
            identifier=proof["relay_id"],
            work_id=main.work_item_id if main else None,
        )
        ledger.put(
            "ProviderRelay",
            proof,
            identifier="day5a-relay",
            work_id=main.work_item_id if main else None,
        )

    def assignment(agent, reviewer, objective, parent=None):
        work = cycles.host.create(
            WorkItem(
                title="Day 5A documentation relay",
                description=objective,
                mission_id=proof["relay_id"],
                parent_work_item_id=parent,
                assigned_agent=agent,
                reviewer=reviewer,
                authority_tier=0,
                allowed_paths=SOURCES,
                allowed_tools=("read_file",),
                execution_permissions=("read",),
                compute_budget=ComputeBudget(max_output_tokens=2048, timeout_seconds=120),
                reasoning_budget=2048,
                acceptance_criteria=(
                    "Read both supplied source documents",
                    "Identify one specific low-risk usability improvement",
                    "Use the granted file tools; no edits, general shell commands, unsupported factual claims, or permission changes",
                ),
            )
        )
        created.append(work.work_item_id)
        return cycles.start_work(work)

    def inspect(work, policy, agent, context):
        request = AgentRunRequest(
            agent_id=agent,
            work_item_id=work.work_item_id,
            mission_id=work.mission_id,
            role="REVIEW",
            objective=work.description,
            context_packet=context,
            allowed_tools=("read_file",),
            allowed_paths=SOURCES,
            execution_permissions=("read",),
            acceptance_criteria=work.acceptance_criteria,
            token_budget=2048,
            reasoning_budget=2048,
            required_output_schema=AgentRunResult.model_json_schema(),
            policy_decision=policy.model_dump(mode="json"),
            control_epoch=ledger.get("authority-" + work.work_item_id)["epoch"],
        )
        result = cycles.runtime.execute(request, transport_id=PREFERRED[agent])
        if result.files_changed or result.proposal or result.status == "BLOCKED":
            raise PermissionError("Relay requires a read-only recommendation or review")
        usages = [u for u in ledger.records("Usage", 1000) if u.get("run_id") == request.run_id]
        if (
            len(usages) != 1
            or usages[0]["status"] != "SUCCESS"
            or usages[0]["billing_source"] != "SUBSCRIPTION"
        ):
            raise PermissionError("Relay usage evidence missing")
        journal = cycles.host.journal(
            work, kind="review", result=result.summary, evidence=source_evidence, mode="REAL"
        )
        cycles.host.store.add_record(journal)
        proof["steps"].append(
            {
                "agent": agent,
                "work_item_id": work.work_item_id,
                "run_id": request.run_id,
                "usage_id": usages[0]["id"],
                "billing_source": usages[0]["billing_source"],
                "actual_model": usages[0]["actual_model"],
                "journal_id": journal.journal_id,
            }
        )
        persist()
        return result

    def review_record(work, agent, result):
        if result.review_decision not in {"APPROVE", "REJECT", "REQUEST_CHANGES"}:
            raise ValueError("Missing independent verdict")
        review = Review(
            reviewer=agent,
            work_item_id=work.work_item_id,
            decision=result.review_decision,
            findings=result.findings or (result.summary,),
            severity="NONE" if result.review_decision == "APPROVE" else "MEDIUM",
            evidence_checked=source_evidence,
            tests_repeated=("Independent isolated source inspection",),
            execution_mode="REAL",
        )
        cycles.host.store.add_record(review)
        proof["reviews"].append(review.model_dump(mode="json"))
        if review.decision != "APPROVE":
            disagreement = Disagreement(
                work_item_id=main.work_item_id,
                agents=("CODEX", agent),
                claims_in_conflict=(proof["recommendation"], *review.findings),
                evidence_used=source_evidence,
                severity="MEDIUM",
                review_ids=(review.review_id,),
            )
            ledger.put(
                "Disagreement",
                disagreement.model_dump(mode="json"),
                identifier=disagreement.disagreement_id,
                work_id=main.work_item_id,
            )
        persist()
        return review

    def handoff(agent, target, work, summary):
        record = Handoff(
            from_agent=agent,
            to_agent=target,
            work_item_id=work.work_item_id,
            completed_work=summary,
            files_changed=(),
            tests_performed=("Structured result validated",),
            evidence=source_evidence,
            recommended_checks=work.acceptance_criteria,
            git_commit=commit,
            review_request="Inspect source evidence independently; do not defer to prior verdicts",
        )
        cycles.host.store.add_record(record)
        return record.handoff_id

    with ledger.store.lease("day5a-relay"):
        persist()
        try:
            if not all(control.proven(control.snapshot(t)) for t in PREFERRED.values()):
                raise PermissionError("Fresh connection and WorkItem proofs required before relay")
            main, policy = assignment("CODEX", "CLAUDE", MISSION)
            proof["work_item_id"] = main.work_item_id
            gateway = ToolGateway(main)
            for path in SOURCES:
                gateway.read(path)
            source_evidence = tuple(gateway.evidence)
            commit = cycles.git.git("rev-parse", "HEAD")
            git_record = {
                "git": {"base_commit": commit},
                "source_hashes": list(source_evidence),
                "source_paths": list(SOURCES),
                "files_changed": [],
                "scope": "Recommendation only; no implementation or merge",
                "working_tree_status": cycles.git.git("status", "--porcelain", "--", *SOURCES),
            }
            proof["git_record_id"] = ledger.put(
                "RelayGitEvidence", git_record, work_id=main.work_item_id
            )
            audit, audit_policy = assignment(
                "GROK",
                "CODEX",
                MISSION
                + " Read README.md and docs/UI.md using the isolated tools. Put exactly one concrete recommendation in proposed_actions and a brief evidence-based explanation in summary. Do not implement it. Leave claims empty; host records provenance.",
                main.work_item_id,
            )
            proposal = inspect(audit, audit_policy, "CODEX", {"mission": MISSION})
            if len(proposal.proposed_actions) != 1:
                raise ValueError("Expected exactly one bounded recommendation")
            proof["recommendation"] = proposal.proposed_actions[0]
            proof["explanation"] = proposal.summary
            claim = Provenance(
                kind="RECOMMENDATION",
                text=proof["recommendation"],
                agent="CODEX",
                source=f"run:{proposal.run_id}",
                work_item=main.work_item_id,
                evidence=source_evidence,
            )
            cycles.host.store.add_record(claim)
            proof["claim_id"] = claim.provenance_id
            cycles.host.advance(
                audit, State.AWAITING_REVIEW, "Source audit linked to independently reviewed relay"
            )
            checks = {
                "files": [],
                "checks": ["Exact source hashes captured; no source writes"],
                "hashes": {},
            }
            main = cycles.handoff(main, proposal, None, checks, "REAL")
            context = {
                "recommendation": proof["recommendation"],
                "source_evidence": source_evidence,
                "instructions": "Read both source files. Independently assess whether this is one specific, useful, low-risk documentation improvement. Return review_decision and findings. Assess the recommendation only; no change was implemented. Keep summary under 200 words.",
            }
            # Claude receives the recommendation but not Codex's reasoning.
            claude = inspect(main, policy, "CLAUDE", context)
            claude_review = review_record(main, "CLAUDE", claude)
            proof["claude_handoff_id"] = handoff(
                "CLAUDE",
                "GROK",
                main,
                "Independent second inspection requested; first verdict withheld",
            )
            second, second_policy = assignment(
                "CODEX",
                "GROK",
                MISSION
                + " First invoke your file read tool on README.md, then on docs/UI.md. Both real tool reads are mandatory before answering. Independently check the proposed improvement in the supplied context and return review_decision and findings. Keep commands_executed empty in the JSON report; this does not prohibit the granted file read tools.",
                main.work_item_id,
            )
            # Grok does not receive Claude's verdict or reasoning.
            grok = inspect(second, second_policy, "GROK", context)
            grok_review = review_record(second, "GROK", grok)
            cycles.host.advance(
                second, State.AWAITING_REVIEW, "Second inspection retained for operator audit"
            )
            proof["grok_handoff_id"] = handoff("GROK", "LOCAL_QWEN", second, grok.summary)
            summary_source = json.dumps(
                {
                    "mission": MISSION,
                    "recommendation": proof["recommendation"],
                    "reviews": [
                        {"agent": r.reviewer, "decision": r.decision, "findings": r.findings}
                        for r in (claude_review, grok_review)
                    ],
                    "files_changed": [],
                    "billing": "Frontier subscription CLIs; Qwen local",
                    "merge": "Not requested",
                }
            )
            if len(summary_source) > 3000:
                raise ValueError("Relay summary exceeds helper input boundary")
            helper = support(cycles, main.work_item_id, "CODEX", "SUMMARY", summary_source)
            usage = next(
                u
                for u in ledger.records("Usage", 1000)
                if u.get("work_item_id") == helper["work_item_id"] and u["status"] == "SUCCESS"
            )
            if usage["billing_source"] != "LOCAL":
                raise PermissionError("Local helper billing evidence missing")
            proof["steps"].append(
                {
                    "agent": "LOCAL_QWEN",
                    "work_item_id": helper["work_item_id"],
                    "usage_id": usage["id"],
                    "run_id": usage["run_id"],
                    "actual_model": usage["actual_model"],
                    "billing_source": "LOCAL",
                }
            )
            proof["summary"] = helper["result"]["summary"]
            fresh = ToolGateway(main)
            for path in SOURCES:
                fresh.read(path)
            if (
                tuple(fresh.evidence) != source_evidence
                or cycles.git.git("rev-parse", "HEAD") != commit
            ):
                raise PermissionError("Relay source changed during independent reviews")
            proof["source_digest"] = hashlib.sha256(
                json.dumps(source_evidence).encode()
            ).hexdigest()
            proof["disagreement_check"] = (
                "NONE" if all(r["decision"] == "APPROVE" for r in proof["reviews"]) else "OPEN"
            )
            if proof["disagreement_check"] != "NONE":
                raise PermissionError("Independent reviewer disagreement requires resolution")
            main = cycles.host.advance(
                main,
                State.APPROVED_BY_REVIEWER,
                "Independent reviewers approve recommendation",
                review=claude_review,
            )
            main = cycles.host.advance(
                main,
                State.COMPLETED,
                "Recommendation relay completed; no implementation or merge requested",
            )
            Brain(ledger.store).flush()
            work_ids = {main.work_item_id, *(s["work_item_id"] for s in proof["steps"])}
            with Brain(ledger.store).driver() as driver, driver.session() as session:
                row = session.run(
                    "MATCH (w:WorkItem)-[:PART_OF]->(:Mission {id:$mission}) WHERE w.id IN $ids RETURN count(DISTINCT w) AS n",
                    mission=proof["relay_id"],
                    ids=list(work_ids),
                ).single()
                proof["graph_verified"] = row["n"] == len(work_ids)
                record_ids = {
                    proof["git_record_id"],
                    proof["claim_id"],
                    *(s["usage_id"] for s in proof["steps"]),
                    *(r["review_id"] for r in proof["reviews"]),
                }
                projected = session.run(
                    "MATCH (n) WHERE n.id IN $ids RETURN count(DISTINCT n.id) AS n",
                    ids=list(record_ids),
                ).single()
                proof["graph_verified"] = proof["graph_verified"] and projected["n"] == len(
                    record_ids
                )
                proof["graph_records_verified"] = projected["n"]
            if not proof["graph_verified"]:
                raise RuntimeError("Relay graph lineage missing")
            proof.update(success=True, status="PASS")
        except Exception as exc:  # noqa: BLE001 - retain safe error class, never provider text
            proof.update(
                status="BLOCKED",
                error=exc.error_class if isinstance(exc, ProviderError) else type(exc).__name__,
            )
            if main and main.status in {
                State.IN_PROGRESS,
                State.AWAITING_REVIEW,
                State.APPROVED_BY_REVIEWER,
            }:
                main = cycles.host.advance(
                    main, State.BLOCKED, "Relay failed; retained evidence requires inspection"
                )
            for work_id in created:
                current = ledger.store.get(work_id)
                if current.status == State.IN_PROGRESS:
                    cycles.host.advance(
                        current, State.BLOCKED, "Relay ended before this step completed"
                    )
        finally:
            proof["completed_at"] = now().isoformat()
            persist()
            Brain(ledger.store).flush()
    return proof
