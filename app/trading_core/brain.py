"""Idempotent graph and Markdown projections; retryable transactional outbox."""

from contextvars import ContextVar
from itertools import pairwise

from trading_core.work import now

_projection_owner = ContextVar("projection_owner", default="triad")


def graph_id(label, identifier):
    if label in {"Mission", "File", "Evidence", "Commit", "Strategy", "DataSource"}:
        return _projection_owner.get() + ":" + identifier
    return identifier


from pathlib import Path

from neo4j import GraphDatabase

from trading_core.settings import ROOT
from trading_core.store import Store

LABELS = {
    "RawDataset",
    "DatasetVersion",
    "DataSource",
    "BacktestRun",
    "Strategy",
    "Hypothesis",
    "ResearchReview",
    "Day3Record",
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
    "NORMALIZED_INTO",
    "DERIVED_INTO",
    "USED_BY",
    "USES_STRATEGY",
    "DISAGREES_WITH",
    "CONTRADICTS",
    "REVERTS",
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
        f"MERGE (n:{label} {{id:$id}}) SET n += $props",
        id=graph_id(label, identifier),
        props={**properties, "owner": "core" if label == "Agent" else _projection_owner.get()},
    ).consume()


def edge(tx, left_label: str, left_id: str, relationship: str, right_label: str, right_id: str):
    if left_label not in LABELS or right_label not in LABELS or relationship not in RELATIONSHIPS:
        raise ValueError("Unknown graph contract")
    tx.run(
        f"MERGE (a:{left_label} {{id:$left}}) MERGE (b:{right_label} {{id:$right}}) "
        f"MERGE (a)-[:{relationship}]->(b) "
        "SET a.owner=coalesce(a.owner,$left_owner), b.owner=coalesce(b.owner,$right_owner)",
        left=graph_id(left_label, left_id),
        right=graph_id(right_label, right_id),
        left_owner="core" if left_label == "Agent" else _projection_owner.get(),
        right_owner="core" if right_label == "Agent" else _projection_owner.get(),
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
        _projection_owner.set(data.get("owner", "triad"))
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
        elif kind == "Day3Record":
            node(
                tx,
                kind,
                entity_id,
                record_kind=data["record_kind"],
                status=data.get("status", ""),
                mode=data.get("mode", ""),
            )
            if work_id:
                edge(tx, "WorkItem", work_id, "SUPPORTED_BY", kind, entity_id)
            if data.get("cycle_id") and entity_id != data["cycle_id"]:
                edge(tx, kind, entity_id, "PART_OF", "Day3Record", data["cycle_id"])
            record_kind = data["record_kind"]
            if record_kind == "RawDataset":
                node(tx, "RawDataset", data["raw_id"], mode=data["mode"], checksum=data["checksum"])
                edge(
                    tx, "DataSource", data["provider"], "SUPPORTED_BY", "RawDataset", data["raw_id"]
                )
            elif record_kind == "DatasetManifest":
                node(
                    tx,
                    "Dataset",
                    entity_id,
                    resolution=data["resolution"],
                    mode=data["mode"],
                    quality=data["quality_status"],
                )
                version_id = entity_id + ":" + data["dataset_version"]
                node(tx, "DatasetVersion", version_id, checksum=data["checksum"])
                edge(tx, "DatasetVersion", version_id, "PART_OF", "Dataset", entity_id)
                for raw in data["raw_sources"]:
                    edge(tx, "RawDataset", raw["raw_id"], "NORMALIZED_INTO", "Dataset", entity_id)
                if data["provenance"].get("parent_dataset"):
                    edge(
                        tx,
                        "Dataset",
                        data["provenance"]["parent_dataset"],
                        "DERIVED_INTO",
                        "Dataset",
                        entity_id,
                    )
            elif record_kind == "Experiment":
                node(tx, "Experiment", entity_id, name=data["name"], status=data["status"])
                edge(tx, "Dataset", data["dataset_id"], "USED_BY", "Experiment", entity_id)
                edge(
                    tx,
                    "Experiment",
                    entity_id,
                    "USES_STRATEGY",
                    "Strategy",
                    data["strategy_version"],
                )
                edge(tx, "Experiment", entity_id, "SUPPORTED_BY", "Commit", data["code_commit"])
                edge(tx, "Experiment", entity_id, "DERIVED_FROM", "Hypothesis", data["hypothesis"])
            elif record_kind == "BacktestRun":
                node(
                    tx,
                    "BacktestRun",
                    entity_id,
                    status=data["status"],
                    content_hash=data.get("content_hash") or "",
                )
                edge(tx, "BacktestRun", entity_id, "PART_OF", "Experiment", data["experiment_id"])
                edge(tx, "BacktestRun", entity_id, "SUPPORTED_BY", "Commit", data["code_commit"])
                edge(tx, "WorkItem", work_id, "SUPPORTED_BY", "BacktestRun", entity_id)
            elif record_kind == "ResearchReview":
                node(tx, "ResearchReview", entity_id, decision=data["decision"], mode=data["mode"])
                edge(tx, "BacktestRun", data["run_id"], "HAS_REVIEW", "ResearchReview", entity_id)
            elif record_kind == "Hypothesis":
                node(
                    tx, "Hypothesis", entity_id, statement=data["statement"], status=data["status"]
                )
            elif record_kind == "ResearchFinding":
                node(tx, "Claim", entity_id, text=data["statement"], status=data["status"])
                for run_id in data["supported_by"]:
                    edge(tx, "Claim", entity_id, "SUPPORTED_BY", "BacktestRun", run_id)
                for run_id in data["contradicted_by"]:
                    edge(tx, "Claim", entity_id, "CONTRADICTED_BY", "BacktestRun", run_id)
            metadata = data.get("git") or {}
            for name in (
                "base_commit",
                "change_commit",
                "review_commit",
                "merge_commit",
                "reverts_commit",
            ):
                if metadata.get(name):
                    edge(
                        tx,
                        kind,
                        entity_id,
                        "REVERTS" if name == "reverts_commit" else "SUPPORTED_BY",
                        "Commit",
                        metadata[name],
                    )
            if work_id and metadata.get("change_commit"):
                edge(tx, "WorkItem", work_id, "CREATED_COMMIT", "Commit", metadata["change_commit"])
            if data["record_kind"] == "Disagreement":
                reviews = data.get("review_ids", [])
                for left, right in pairwise(reviews):
                    edge(tx, "Day3Record", left, "DISAGREES_WITH", "Day3Record", right)
                claims = data.get("claims_in_conflict", [])
                for index, claim in enumerate(claims):
                    claim_id = f"{entity_id}-claim-{index}"
                    node(tx, "Claim", claim_id, text=claim[:1000], kind="EXTERNAL_CLAIM")
                    edge(tx, kind, entity_id, "SUPPORTED_BY", "Claim", claim_id)
                    if index:
                        edge(tx, "Claim", f"{entity_id}-claim-0", "CONTRADICTS", "Claim", claim_id)
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
            "---\nrecord_id: "
            + identifier
            + "\nowner: "
            + data.get("owner", "triad")
            + "\ngenerated: true\ngenerated_at: "
            + now().isoformat()
            + "\nsource: postgres:JournalEntry:"
            + identifier
            + "\n---",
            f"# {data['objective']}",
            f"Canonical journal: `{identifier}`",
            f"[Inspect canonical work](http://127.0.0.1:8000/core?work={data['work_item_id']})",
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
        if target.is_relative_to(ROOT):
            with self.store.connect() as conn:
                conn.execute(
                    "INSERT INTO core.artifact_owners VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (target.relative_to(ROOT).as_posix(), data.get("owner", "triad"), identifier),
                )

    def flush(self, limit: int = 500) -> dict:
        delivered = 0
        # Global advisory lock preserves ordering across concurrent projection workers.
        with self.store.lease("day2-projections"), self.driver() as driver:
            for _ in range(limit):
                with self.store.connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM core.projection_outbox WHERE delivered_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE"
                    ).fetchone()
                    if not row:
                        break
                    try:
                        # Payload content cannot assign graph or exported-note ownership.
                        table = (
                            "work_items"
                            if row["kind"] == "WorkItem"
                            else "day3_records"
                            if row["kind"] == "Day3Record"
                            else "orchestration_records"
                        )
                        owned = conn.execute(
                            f"SELECT owner FROM core.{table} WHERE id=%s", (row["entity_id"],)
                        ).fetchone()
                        owner = owned["owner"] if owned else "triad"
                        with driver.session() as session:
                            session.execute_write(
                                self.project,
                                row["kind"],
                                row["entity_id"],
                                {**row["payload"], "owner": owner},
                            )
                            session.run(
                                "MATCH (n {id:$id}) SET n.owner=$owner",
                                id=row["entity_id"],
                                owner=owner,
                            ).consume()
                        if (
                            row["kind"] == "Day3Record"
                            and row["payload"].get("record_kind") == "CycleSummary"
                        ):
                            import json

                            cycle_id = row["payload"]["cycle_id"]
                            if any(c not in "0123456789abcdef-" for c in cycle_id):
                                raise ValueError("Unsafe cycle ID")
                            self.vault.mkdir(parents=True, exist_ok=True)
                            target = self.vault / f"cycle-{cycle_id}.md"
                            temporary = target.with_suffix(".tmp")
                            temporary.write_text(
                                f"---\nrecord_id: {cycle_id}\nowner: {owner}\ngenerated: true\ngenerated_at: {now().isoformat()}\nsource: postgres:CycleSummary:{cycle_id}\n---\n# Cycle summary\n\nCanonical data: PostgreSQL.\n\n```json\n"
                                + json.dumps(row["payload"], indent=2)
                                + "\n```\n",
                                encoding="utf-8",
                            )
                            temporary.replace(target)
                        if row["kind"] == "JournalEntry":
                            self.export_markdown({**row["payload"], "owner": owner})
                    except Exception as exc:  # noqa: BLE001 - durable error type, never credentials
                        conn.execute(
                            "UPDATE core.projection_outbox SET attempts=attempts+1,last_error=%s WHERE id=%s",
                            (type(exc).__name__, row["id"]),
                        )
                        return {"delivered": delivered, "error": type(exc).__name__}
                    conn.execute(
                        "UPDATE core.projection_outbox SET delivered_at=now(),attempts=attempts+1,last_error=NULL WHERE id=%s",
                        (row["id"],),
                    )
                    delivered += 1
        return {"delivered": delivered, "error": None}

    def lineage(self, work_id: str) -> list[dict]:
        self.store.get(work_id)
        with self.driver() as driver, driver.session() as session:
            records = session.run(
                "MATCH (w:WorkItem {id:$id})-[r]-(n) WHERE $scope IS NULL OR n.owner=$scope OR n.owner='shared' OR 'Agent' IN labels(n) RETURN type(r) AS relationship, labels(n)[0] AS label, n.id AS id LIMIT 100",
                id=work_id,
                scope=self.store.scope,
            )
            return [r.data() for r in records]
