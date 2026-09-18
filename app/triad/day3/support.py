"""Controlled helper capabilities; no recursive agent creation or direct model access."""

import json

from triad.brain import Brain
from triad.day3.contracts import AgentRunRequest, Limits
from triad.day3.security import ensure_no_secret
from triad.settings import ROOT
from triad.work import ComputeBudget, Provenance, State, WorkItem

CAPABILITIES = tuple(json.loads((ROOT / "agents/day3.json").read_text())["local_capabilities"])


def manifest():
    return [
        {
            "capability": name,
            "risk": "LOW",
            "preferred_agent": "LOCAL_QWEN",
            "authority_tier": 0,
            "max_delegation_depth": 1,
            "required_output": {"summary": "string", "assumptions": "array of strings"},
        }
        for name in CAPABILITIES
    ]


def support(cycles, parent_id, requester, capability, text, *, objective=None):
    ledger = cycles.ledger
    parent = cycles.host.store.get(parent_id)
    ensure_no_secret(text)
    if (
        capability not in CAPABILITIES
        or requester != parent.assigned_agent
        or requester == "LOCAL_QWEN"
    ):
        raise PermissionError("Invalid support request identity/capability")
    if parent.parent_work_item_id and parent.assigned_agent == "LOCAL_QWEN":
        raise PermissionError("Recursive helper delegation denied")
    if len(text) > 3000:
        raise PermissionError("Support source exceeds bounded input")
    with ledger.store.lease("support-" + parent_id):
        limits = Limits.model_validate(ledger.guard(requester, parent_id)["limits"])
        if limits.max_delegation_depth < 1:
            raise PermissionError("Delegation disabled")
        prior = [
            r
            for r in ledger.records("SupportRequest", 1000)
            if r.get("parent_work_item_id") == parent_id
        ]
        if len(prior) >= limits.max_support_requests:
            raise PermissionError("Support delegation count exhausted")
        work = cycles.host.create(
            WorkItem(
                title=f"{capability}: bounded local support",
                description=objective
                or f"{capability}: Process only the supplied observation. Return a concise summary and explicit assumptions. Do not add facts.",
                parent_work_item_id=parent_id,
                mission_id=parent.mission_id,
                work_type="summarize_journal",
                authority_tier=0,
                allowed_tools=("read_file",),
                allowed_paths=("docs",),
                execution_permissions=("read",),
                reasoning_budget=512,
                compute_budget=ComputeBudget(max_output_tokens=1024, timeout_seconds=120),
                input_context=(
                    Provenance(
                        kind="OBSERVATION",
                        text=text,
                        source=f"work:{parent_id}:operator-supplied",
                        agent=requester,
                    ),
                ),
                expected_outputs=("Structured supporting summary and assumptions",),
                acceptance_criteria=("Preserve supplied facts and distinguish assumptions",),
            )
        )
        ledger.put(
            "SupportRequest",
            {
                "parent_work_item_id": parent_id,
                "requester": requester,
                "capability": capability,
                "delegation_depth": 1,
            },
            work_id=work.work_item_id,
        )
        work, policy = cycles.start_work(work)
        request = AgentRunRequest(
            agent_id="LOCAL_QWEN",
            control_epoch=ledger.get("authority-" + work.work_item_id)["epoch"],
            work_item_id=work.work_item_id,
            mission_id=work.mission_id,
            parent_work_item_id=parent_id,
            delegation_depth=1,
            role="SUPPORT",
            objective=work.description,
            context_packet={
                "source": f"work:{parent_id}",
                "classification": "OBSERVATION",
                "text": text,
            },
            allowed_tools=(),
            allowed_paths=work.allowed_paths,
            acceptance_criteria=work.acceptance_criteria,
            reasoning_budget=512,
            token_budget=1024,
            cost_budget=0,
            execution_permissions=("read",),
            policy_decision=policy.model_dump(mode="json"),
            required_output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "assumptions"],
                "additionalProperties": False,
            },
        )
        try:
            result = cycles.runtime.execute(request, mode="REAL", day=cycles.day)
            checks = {
                "checks": ["Validated structured helper response; not independently verified"],
                "hashes": {},
                "files": [],
            }
            cycles.handoff(work, result, None, checks, "REAL")
            ledger.put(
                "SupportResult",
                {
                    "capability": capability,
                    "parent_work_item_id": parent_id,
                    "result": result.model_dump(mode="json"),
                    "mode": "REAL",
                    "status": "AWAITING_REVIEW",
                },
                work_id=work.work_item_id,
            )
            Brain(ledger.store).flush()
            return {
                "work_item_id": work.work_item_id,
                "result": result.model_dump(mode="json"),
                "status": "AWAITING_REVIEW",
                "mode": "REAL",
            }
        except Exception as exc:
            journal = cycles.host.journal(
                work,
                kind="failure",
                result="Controlled local helper failed",
                failures=(type(exc).__name__,),
                mode="REAL",
            )
            cycles.host.advance(
                work,
                State.FAILED,
                "Local support failure",
                records=(journal,),
                failure_reason=type(exc).__name__,
            )
            Brain(ledger.store).flush()
            raise
