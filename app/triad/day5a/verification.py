"""Real provider tests; a blocked transport never produces a passing proof."""

import time

from triad.brain import Brain
from triad.day3.adapters import ProviderError
from triad.day3.contracts import AgentRunRequest, AgentRunResult
from triad.day3.cycles import Cycles
from triad.day3.support import support
from triad.day5a.contracts import SPECS
from triad.work import ComputeBudget, State, WorkItem, now, uid


def verify(control, transport_id, acceptance=False):
    adapter = control.transport(transport_id)
    ledger = control.ledger
    ledger.guard(adapter.agent)
    if adapter.transport_type == "API" and not control.secrets.has_secret(transport_id):
        return {
            "transport": transport_id,
            "status": "NOT_CONFIGURED",
            "success": False,
            "error": "APINotConfigured",
            "mode": "REAL",
            "billing_source": "API",
        }
    cycles = Cycles(store=ledger.store)
    started = time.monotonic()
    proof = {
        "transport": transport_id,
        "agent": adapter.agent,
        "provider": adapter.provider,
        "billing_source": adapter.billing_source(),
        "requested_model": adapter.model,
        "actual_model": None,
        "mode": "REAL",
        "started_at": now().isoformat(),
        "success": False,
        "kind": "workitem" if acceptance else "test",
    }
    proof_id = uid()
    parent = None
    with ledger.store.lease("provider-test-" + transport_id):
        ledger.event("transport_test_started", transport=transport_id, proof_id=proof_id)
        try:
            if SPECS[transport_id]["type"] == "CLI" and not adapter.readonly_ready():
                raise ProviderError("UNAVAILABLE", "OuterBoundaryUnavailable")
            if adapter.agent == "LOCAL_QWEN":
                parent = cycles.host.create(
                    WorkItem(
                        title="Day 5A local capability verification",
                        description="Request a bounded journal summary",
                        assigned_agent="CODEX",
                        allowed_tools=("read_file",),
                        allowed_paths=("docs",),
                        execution_permissions=("read",),
                        authority_tier=0,
                        review_required=False,
                    )
                )
                parent, _ = cycles.start_work(parent)
                proof["parent_work_item_id"] = parent.work_item_id
                source = (
                    (
                        "The Day 5A transport test is an operator-authorized local helper request. "
                        "Strategy discovery is paused until frontier CLI WorkItems and the relay pass."
                    )
                    if acceptance
                    else "TRIAD_TRANSPORT_OK"
                )
                objective = (
                    None
                    if acceptance
                    else (
                        'Return JSON with summary exactly "TRIAD_TRANSPORT_OK" and assumptions an empty array. '
                        "This is a connection test. Do not add other text."
                    )
                )
                result = support(
                    cycles, parent.work_item_id, "CODEX", "SUMMARY", source, objective=objective
                )
                proof["work_item_id"] = result["work_item_id"]
                summary = result["result"]["summary"]
                cycles.host.advance(
                    parent,
                    State.COMPLETED,
                    "Host capability request concluded; helper result remains reviewable",
                )
            else:
                worker = cycles.host.registry.successor(adapter.agent)
                work = cycles.host.create(
                    WorkItem(
                        title="Day 5A explicit provider verification",
                        description=(
                            "Read README.md using the supplied isolated file tools. Return its title "
                            "and one structural observation in summary. No changes."
                            if adapter.transport_type == "CLI" and acceptance
                            else "Return a structured result with summary exactly TRIAD_TRANSPORT_OK, no changes or commands."
                        ),
                        assigned_agent=worker,
                        reviewer=adapter.agent,
                        allowed_tools=("read_file",),
                        allowed_paths=("README.md",)
                        if adapter.transport_type == "CLI" and acceptance
                        else ("docs",),
                        execution_permissions=("read",),
                        authority_tier=0,
                        compute_budget=ComputeBudget(max_output_tokens=1024),
                        reasoning_budget=1024,
                    )
                )
                work, policy = cycles.start_work(work)
                proof["work_item_id"] = work.work_item_id
                request = AgentRunRequest(
                    agent_id=adapter.agent,
                    work_item_id=work.work_item_id,
                    mission_id=work.mission_id,
                    role="REVIEW",
                    objective=work.description,
                    acceptance_criteria=work.acceptance_criteria,
                    context_packet={"purpose": "transport test"},
                    allowed_tools=("read_file",) if adapter.transport_type == "CLI" else (),
                    allowed_paths=work.allowed_paths,
                    execution_permissions=("read",),
                    reasoning_budget=1024,
                    token_budget=1024,
                    policy_decision=policy.model_dump(mode="json"),
                    required_output_schema=AgentRunResult.model_json_schema(),
                    control_epoch=ledger.get("authority-" + work.work_item_id)["epoch"],
                )
                response = cycles.runtime.execute(request, transport_id=transport_id)
                summary = response.summary
                journal = cycles.host.journal(work, kind="review", result=summary, mode="REAL")
                cycles.host.advance(
                    work,
                    State.AWAITING_REVIEW,
                    "Connection result awaits operator review",
                    records=(journal,),
                )
            if not acceptance and summary.strip() != "TRIAD_TRANSPORT_OK":
                raise ProviderError("DEGRADED", "UnexpectedTestResponse")
            usages = [
                u
                for u in ledger.records("Usage", 1000)
                if u.get("work_item_id") == proof["work_item_id"] and u.get("status") == "SUCCESS"
            ]
            if not usages:
                raise ProviderError("DEGRADED", "UsageEvidenceMissing")
            proof.update(
                success=True,
                result=summary,
                usage_id=usages[0]["id"],
                actual_model=usages[0].get("actual_model"),
                billing_source=usages[0].get("billing_source"),
                run_id=usages[0]["run_id"],
            )
        except Exception as exc:  # noqa: BLE001 - fixed error codes only
            proof["error"] = (
                exc.error_class if isinstance(exc, ProviderError) else type(exc).__name__
            )
            if parent:
                for child in ledger.records("SupportRequest", 100):
                    if child.get("parent_work_item_id") == parent.work_item_id:
                        proof["work_item_id"] = child["work_item_id"]
                        break
                current_parent = ledger.store.get(parent.work_item_id)
                if current_parent.status == State.IN_PROGRESS:
                    cycles.host.advance(
                        current_parent, State.FAILED, "Provider verification concluded with failure"
                    )
            if proof.get("work_item_id"):
                work = ledger.store.get(proof["work_item_id"])
                if work.status == State.IN_PROGRESS:
                    journal = cycles.host.journal(
                        work,
                        kind="failure",
                        result="Provider verification failed",
                        failures=(proof["error"],),
                        mode="REAL",
                    )
                    cycles.host.advance(
                        work, State.FAILED, "Verification failed", records=(journal,)
                    )
        proof.update(completed_at=now().isoformat(), latency=time.monotonic() - started)
        ledger.put(
            "TransportVerification", proof, identifier=proof_id, work_id=proof.get("work_item_id")
        )
        snapshot = control.snapshot(transport_id)
        snapshot.update(
            {
                proof["kind"]: {**proof, "proof_id": proof_id},
                "error": proof.get("error"),
                "billing_source": proof["billing_source"],
                "health": "OFFLINE",
                "auth_state": "AUTHENTICATED"
                if proof["success"]
                else snapshot.get("auth_state", "NOT_AUTHENTICATED"),
            }
        )
        ledger.put("TransportStatus", snapshot, identifier="transport-status-" + transport_id)
        ledger.event(
            "transport_test_succeeded" if proof["success"] else "transport_test_failed",
            proof.get("work_item_id"),
            transport=transport_id,
            proof_id=proof_id,
            error=proof.get("error"),
        )
        Brain(ledger.store).flush()
        return {"proof_id": proof_id, **proof}
