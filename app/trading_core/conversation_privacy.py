"""Keep private chat content out of the existing unauthenticated operations views."""

PRIVATE_KINDS = {"CoreConversation", "CoreChatMessage", "IntakeRecord", "IdeaDisposition"}


def private_work_ids(store):
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT w.id FROM core.work_items w JOIN core.intelligence_records c ON c.id=w.mission_id "
            "WHERE c.kind='CoreConversation' AND c.owner='core' AND w.owner='core'"
        ).fetchall()
    return {r["id"] for r in rows}


def public_records(rows, private_ids):
    return [
        r
        for r in rows
        if r.get("kind") not in PRIVATE_KINDS
        and r.get("work_item_id", r.get("work_item")) not in private_ids
    ]
