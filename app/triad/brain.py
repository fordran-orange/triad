"""Idempotent graph and Markdown projections; retryable transactional outbox."""

from pathlib import Path

from neo4j import GraphDatabase

from triad.settings import ROOT
from triad.store import Store

LABELS = {
    "Agent",
    "WorkItem",
    "Mission",
    "JournalEntry",
    "Decision",
    "File",
    "Commit",
    "Dataset",
    "Experiment",
    "Claim",
    "Evidence",
    "PolicyDecision",
    "Review",
    "Handoff",
    "ContextPacket",
    "ElevationRequest",
}
RELATIONSHIPS = {
    "AGENT_PERFORMED_WORK_ITEM",
    "WORK_ITEM_CHANGED_FILE",
    "WORK_ITEM_PRODUCED_DECISION",
    "REVIEWED_BY",
    "SUPPORTED_BY",
    "CONTRADICTED_BY",
    "DERIVED_FROM",
    "SUPERSEDES",
    "USED_DATASET",
    "CREATED_COMMIT",
    "HANDOFF_TO",
    "PART_OF",
    "PRODUCED_JOURNAL",
    "HAS_POLICY",
    "HAS_REVIEW",
    "HAS_CONTEXT",
}


def node(tx, label: str, identifier: str, **properties):
    if label not in LABELS:
        raise ValueError("Unknown graph label")
    tx.run(
        f"MERGE (n:{label} {{id:$id}}) SET n += $props", id=identifier, props=properties
    ).consume()


def edge(tx, left_label: str, left_id: str, relationship: str, right_label: str, right_id: str):
    if left_label not in LABELS or right_label not in LABELS or relationship not in RELATIONSHIPS:
        raise ValueError("Unknown graph contract")
    tx.run(
        f"MERGE (a:{left_label} {{id:$left}}) MERGE (b:{right_label} {{id:$right}}) "
        f"MERGE (a)-[:{relationship}]->(b)",
        left=left_id,
        right=right_id,
    ).consume()


class Brain:
    def __init__(self, store: Store, vault: Path = ROOT / "docs/vault/02_Journal/generated"):
        self.store = store
        self.vault = vault

    def driver(self):
        s = self.store.settings
        return GraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password.get_secret_value()),
            connection_timeout=5,
            max_transaction_retry_time=5,
        )

    def initialize(self):
        with self.driver() as driver, driver.session() as session:
            for label in sorted(LABELS):
                session.run(
                    f"CREATE CONSTRAINT day2_{label.lower()} IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                ).consume()

    @staticmethod
    def project(tx, kind: str, entity_id: str, data: dict):
        work_id = data.get("work_item_id")
        if kind == "WorkItem":
            node(
                tx,
                "WorkItem",
                entity_id,
                title=data["title"],
                status=data["status"],
                revision=data["revision"],
            )
            edge(tx, "WorkItem", entity_id, "PART_OF", "Mission", data["mission_id"])
            if data.get("parent_work_item_id"):
                edge(
                    tx,
                    "WorkItem",
                    entity_id,
                    "DERIVED_FROM",
                    "WorkItem",
                    data["parent_work_item_id"],
                )
            if data.get("assigned_agent"):
                edge(
                    tx,
                    "Agent",
                    data["assigned_agent"],
                    "AGENT_PERFORMED_WORK_ITEM",
                    "WorkItem",
                    entity_id,
                )
        elif kind == "Agent":
            node(
                tx,
                "Agent",
                entity_id,
                display_name=data["display_name"],
                role=data["role"],
                model=data["model"],
            )
        elif kind == "Provenance":
            node(
                tx,
                "Claim",
                entity_id,
                kind=data["kind"],
                source=data["source"],
                text=data["text"][:1000],
            )
            if data.get("work_item"):
                edge(
                    tx,
                    "WorkItem",
                    data["work_item"],
                    "WORK_ITEM_PRODUCED_DECISION" if data["kind"] == "DECISION" else "SUPPORTED_BY",
                    "Claim",
                    entity_id,
                )
            for reference in data["evidence"]:
                edge(tx, "Claim", entity_id, "SUPPORTED_BY", "Evidence", reference)
        elif kind in LABELS:
            props = {
                k: data[k]
                for k in ("decision", "agent", "reviewer", "event_kind", "execution_mode", "status")
                if k in data
            }
            node(tx, kind, entity_id, **props)
            if work_id:
                relationship = {
                    "PolicyDecision": "HAS_POLICY",
                    "Review": "HAS_REVIEW",
                    "JournalEntry": "PRODUCED_JOURNAL",
                    "ContextPacket": "HAS_CONTEXT",
                }.get(kind, "SUPPORTED_BY")
                edge(tx, "WorkItem", work_id, relationship, kind, entity_id)
            if kind == "Review":
                edge(tx, "WorkItem", work_id, "REVIEWED_BY", "Agent", data["reviewer"])
            if kind == "Handoff":
                edge(tx, "Handoff", entity_id, "HANDOFF_TO", "Agent", data["to_agent"])
            if kind == "JournalEntry":
                for path in data["files_changed"]:
                    edge(tx, "WorkItem", work_id, "WORK_ITEM_CHANGED_FILE", "File", path)
                if data["git_commit"]:
                    # References implementation commit, not a false claim that the agent made it.
                    edge(
                        tx, "JournalEntry", entity_id, "SUPPORTED_BY", "Commit", data["git_commit"]
                    )
            for ref in data.get("evidence", data.get("evidence_checked", [])):
                edge(tx, kind, entity_id, "SUPPORTED_BY", "Evidence", ref)

    def export_markdown(self, data: dict):
        identifier = data["journal_id"]
        if not identifier or any(c not in "0123456789abcdef-" for c in identifier):
            raise ValueError("Unsafe journal export ID")
        self.vault.mkdir(parents=True, exist_ok=True)
        sections = [
            f"# {data['objective']}",
            f"Canonical journal: `{identifier}`",
            f"Agent: {data['agent']} · Mode: {data['execution_mode']} · {data['timestamp']}",
            "This Markdown is a projection. PostgreSQL is authoritative.",
        ]
        for key, value in data.items():
            sections.append(
                f"## {key.replace('_', ' ').title()}\n\n"
                + ("\n".join(f"- {v}" for v in value) if isinstance(value, list) else str(value))
            )
        target = self.vault / f"{identifier}.md"
        temporary = target.with_suffix(".tmp")
        temporary.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        temporary.replace(target)

    def flush(self, limit: int = 500) -> dict:
        delivered = 0
        # Global advisory lock preserves ordering across concurrent projection workers.
        with self.store.lease("day2-projections"), self.driver() as driver:
            for _ in range(limit):
                with self.store.connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM triad.projection_outbox WHERE delivered_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE"
                    ).fetchone()
                    if not row:
                        break
                    try:
                        with driver.session() as session:
                            session.execute_write(
                                self.project, row["kind"], row["entity_id"], row["payload"]
                            )
                        if row["kind"] == "JournalEntry":
                            self.export_markdown(row["payload"])
                    except Exception as exc:  # noqa: BLE001 - durable error type, never credentials
                        conn.execute(
                            "UPDATE triad.projection_outbox SET attempts=attempts+1,last_error=%s WHERE id=%s",
                            (type(exc).__name__, row["id"]),
                        )
                        return {"delivered": delivered, "error": type(exc).__name__}
                    conn.execute(
                        "UPDATE triad.projection_outbox SET delivered_at=now(),attempts=attempts+1,last_error=NULL WHERE id=%s",
                        (row["id"],),
                    )
                    delivered += 1
        return {"delivered": delivered, "error": None}

    def lineage(self, work_id: str) -> list[dict]:
        with self.driver() as driver, driver.session() as session:
            records = session.run(
                "MATCH (w:WorkItem {id:$id})-[r]-(n) RETURN type(r) AS relationship, labels(n)[0] AS label, n.id AS id LIMIT 100",
                id=work_id,
            )
            return [r.data() for r in records]
