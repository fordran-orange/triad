"""Relevant bounded context with provenance; never load unrestricted history or secrets."""

from trading_core.product_identity import canonical_product
from trading_core.work import ContextPacket, Provenance, WorkItem


def packet_for(
    work: WorkItem,
    journals: list[dict] | None = None,
    handoffs: list[dict] | None = None,
    graph: list[dict] | None = None,
    decisions: list[dict] | None = None,
) -> ContextPacket:
    budget = work.compute_budget.max_input_chars
    relevant = [
        j
        for j in (journals or [])
        if j["mission_id"] == work.mission_id
        and canonical_product(j.get("owner", work.owner)) == canonical_product(work.owner)
    ][:3]
    history = tuple(
        Provenance(
            kind="OBSERVATION",
            text=j["results"][:1200],
            source=f"postgres:JournalEntry:{j['journal_id']}",
            timestamp=j["timestamp"],
            agent=j["agent"],
            work_item=work.work_item_id,
        )
        for j in relevant
    )
    prior = tuple(
        Provenance(
            kind="OBSERVATION",
            text=h["completed_work"][:1000],
            source=f"postgres:Handoff:{h['handoff_id']}",
            agent=h["from_agent"],
            work_item=work.work_item_id,
        )
        for h in (handoffs or [])
        if h["work_item_id"] == work.parent_work_item_id
        and canonical_product(h.get("owner", work.owner)) == canonical_product(work.owner)
    )[:1]
    packet = ContextPacket(
        work_item_id=work.work_item_id,
        work_item=f"{work.title}\n{work.description}",
        charter=(
            Provenance(
                kind="DECISION",
                text="Bounded work; human governance; no live trading.",
                source="config/core/agents.json",
                agent="operator",
            ),
        ),
        applicable_policies=(
            Provenance(
                kind="DECISION",
                text="day2-v1: bounded tools, immutable authority, independent review.",
                source="app/trading_core/control.py",
                agent="operator",
            ),
        ),
        recent_journal_entries=history,
        relevant_decisions=tuple(
            Provenance(
                kind="DECISION",
                text=f"{d['decision']}: {d['reason']}; {d['routing_reason']}",
                source=f"postgres:PolicyDecision:{d['policy_decision_id']}",
                timestamp=d["evaluated_at"],
                agent="control_plane",
                work_item=work.work_item_id,
            )
            for d in (decisions or [])[:2]
            if canonical_product(d.get("owner", work.owner)) == canonical_product(work.owner)
        ),
        prior_handoff=prior,
        relevant_files=work.input_context,
        relevant_graph_relationships=tuple(
            Provenance(
                kind="OBSERVATION",
                text=str(r),
                source=f"neo4j:{work.work_item_id}",
                agent="context_builder",
            )
            for r in (graph or [])[:5]
            if (
                r.get("owner", work.owner) in {"shared", "core"}
                or canonical_product(r.get("owner", work.owner)) == canonical_product(work.owner)
            )
        ),
        required_acceptance_criteria=work.acceptance_criteria,
    )
    if len(packet.model_dump_json()) > budget:
        raise ValueError("Relevant context exceeds assignment budget; operator must narrow inputs")
    return packet
