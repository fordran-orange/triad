"""Relevant bounded context with provenance; never load unrestricted history or secrets."""

from triad.work import ContextPacket, Provenance, WorkItem


def packet_for(
    work: WorkItem,
    journals: list[dict] | None = None,
    handoffs: list[dict] | None = None,
    graph: list[dict] | None = None,
) -> ContextPacket:
    budget = work.compute_budget.max_input_chars
    relevant = [j for j in (journals or []) if j["mission_id"] == work.mission_id][:3]
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
    )[:1]
    packet = ContextPacket(
        work_item_id=work.work_item_id,
        work_item=f"{work.title}\n{work.description}",
        charter=(
            Provenance(
                kind="DECISION",
                text="Independent research; human governance; no live trading.",
                source="docs/vault/01_Charter/README.md",
                agent="operator",
            ),
        ),
        applicable_policies=(
            Provenance(
                kind="DECISION",
                text="day2-v1: bounded tools, immutable authority, independent review.",
                source="app/triad/control.py",
                agent="operator",
            ),
        ),
        recent_journal_entries=history,
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
        ),
        required_acceptance_criteria=work.acceptance_criteria,
    )
    if len(packet.model_dump_json()) > budget:
        raise ValueError("Relevant context exceeds assignment budget; operator must narrow inputs")
    return packet
