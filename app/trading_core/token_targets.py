"""Subscription product-cycle token targets; authority is derived from host records."""

from trading_core.intelligence.records import Records
from trading_core.product_changes import active_policy
from trading_core.store import Store


def advisory(ledger, request, billing_source):
    if billing_source != "SUBSCRIPTION" or request.agent_id not in {"CODEX", "CLAUDE", "GROK"}:
        return False
    work = ledger.store.get(request.work_item_id)
    if (
        work.owner != "triad"
        or work.assigned_agent != request.agent_id
        or work.mission_id != request.mission_id
        or request.role != "REVIEW"
    ):
        return False
    records = Records(Store(ledger.store.settings))
    programs = [
        r
        for r in records.list("SequentialDailyProgram")
        if r["owner"] == "triad" and r.get("cycle_id") == work.mission_id
    ]
    if not programs:
        return False
    program = programs[-1]
    policy = active_policy(records)
    if (
        program["policy_id"] != policy["id"]
        or policy.get("token_policy") != "TARGET"
        or request.control_epoch != program["control_epoch"]
        or work.parent_work_item_id != program["parent_work_item_id"]
    ):
        return False
    cycles = [
        r
        for r in records.list("CycleRecord")
        if r.get("cycle_id") == work.mission_id and r.get("product") == "triad"
    ]
    return bool(
        cycles
        and cycles[-1].get("execution_mode") == "REAL"
        and cycles[-1].get("status") not in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
    )
