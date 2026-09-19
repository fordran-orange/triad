from trading_core.resources import resource

"""PostgreSQL is authoritative. Each transition, evidence bundle and outbox commit atomically."""

import json
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from trading_core.settings import Settings
from trading_core.work import Record, WorkItem

ID_FIELDS = {
    "Agent": "agent_id",
    "PolicyDecision": "policy_decision_id",
    "ContextPacket": "packet_id",
    "JournalEntry": "journal_id",
    "Handoff": "handoff_id",
    "Review": "review_id",
    "ElevationRequest": "request_id",
    "Provenance": "provenance_id",
}


class ConcurrentUpdate(RuntimeError):
    pass


class Store:
    def __init__(self, settings: Settings | None = None, *, scope=None):
        from trading_core.ownership import PRODUCTS

        if scope is not None and scope not in PRODUCTS:
            raise ValueError("Unknown product scope")
        self.scope = scope
        self.settings = settings or Settings()

    def connect(self):
        s = self.settings
        return psycopg.connect(
            host=s.postgres_host,
            port=s.postgres_port,
            dbname=s.postgres_db,
            user=s.postgres_user,
            password=s.postgres_password.get_secret_value(),
            connect_timeout=5,
            row_factory=dict_row,
        )

    def migrate(self):
        with self.connect() as conn:
            conn.execute(resource("infrastructure/postgres/002_orchestration.sql").read_text())
            for table in ("work_items", "orchestration_records"):
                conn.execute(
                    f"ALTER TABLE core.{table} ADD COLUMN IF NOT EXISTS owner text NOT NULL DEFAULT 'triad'"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS core.artifact_owners (path text PRIMARY KEY, owner text NOT NULL, record_id text NOT NULL)"
            )

    @contextmanager
    def lease(self, work_id: str):
        """Session-level advisory lock prevents simultaneous execution of the same assignment."""
        with self.connect() as conn:
            acquired = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS ok", (work_id,)
            ).fetchone()["ok"]
            if not acquired:
                raise ConcurrentUpdate("Work is already being executed")
            try:
                yield
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (work_id,))

    @staticmethod
    def enqueue(conn, kind: str, entity_id: str, payload: dict):
        conn.execute(
            "INSERT INTO core.projection_outbox(kind,entity_id,payload) VALUES (%s,%s,%s)",
            (kind, entity_id, Jsonb(payload)),
        )

    def add_record(self, record: Record, *, conn=None):
        if conn is None:
            with self.connect() as transaction:
                self.add_record(record, conn=transaction)
            return
        kind = type(record).__name__
        data = record.model_dump(mode="json")
        work_id = data.get("work_item_id") or data.get("work_item")
        owner = "core" if kind == "Agent" else self.scope or "core"
        if work_id:
            owned = conn.execute(
                "SELECT owner FROM core.work_items WHERE id=%s", (work_id,)
            ).fetchone()
            if not owned:
                raise KeyError(work_id)
            from trading_core.ownership import require_write

            require_write(self.scope, owned["owner"])
            owner = owned["owner"]
        record_id = data[ID_FIELDS[kind]]
        inserted = conn.execute(
            "INSERT INTO core.orchestration_records(id,kind,work_item_id,payload,owner) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            (record_id, kind, work_id, Jsonb(data), owner),
        ).fetchone()
        if inserted:
            self.enqueue(conn, kind, record_id, data)

    def create(self, work: WorkItem):
        from trading_core.ownership import require_owner

        require_owner(self.scope, work.owner)
        if work.parent_work_item_id:
            parent = self.get(work.parent_work_item_id)
            if parent.owner != work.owner:
                raise PermissionError("Cross-product parent assignment")
        if work.status != "CREATED" or work.revision != 0 or work.result is not None:
            raise ValueError("Only pristine CREATED assignments may be inserted")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO core.work_items(id,mission_id,status,revision,payload,owner) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    work.work_item_id,
                    work.mission_id,
                    work.status,
                    work.revision,
                    Jsonb(work.model_dump(mode="json")),
                    work.owner,
                ),
            )
            conn.execute(
                "INSERT INTO core.work_events(work_item_id,to_state,revision,detail) VALUES (%s,%s,0,%s)",
                (work.work_item_id, work.status, "Operator created immutable bounded assignment"),
            )
            self.enqueue(conn, "WorkItem", work.work_item_id, work.model_dump(mode="json"))

    def step(
        self,
        previous: WorkItem,
        updated: WorkItem,
        detail: str,
        records: tuple[Record, ...] = (),
        *,
        conn=None,
    ):
        if updated.owner != previous.owner:
            raise PermissionError("Work ownership is immutable")
        from trading_core.ownership import require_write

        require_write(self.scope, previous.owner)
        if (
            updated.revision != previous.revision + 1
            or updated.work_item_id != previous.work_item_id
        ):
            raise ValueError("Invalid revision")
        if conn is None:
            with self.connect() as transaction:
                return self.step(previous, updated, detail, records, conn=transaction)
        result = conn.execute(
            "UPDATE core.work_items SET status=%s,revision=%s,payload=%s,updated_at=now() "
            "WHERE id=%s AND revision=%s AND (%s::text IS NULL OR owner=%s) RETURNING id",
            (
                updated.status,
                updated.revision,
                Jsonb(updated.model_dump(mode="json")),
                previous.work_item_id,
                previous.revision,
                self.scope,
                self.scope,
            ),
        ).fetchone()
        if not result:
            raise ConcurrentUpdate("Stale work revision")
        conn.execute(
            "INSERT INTO core.work_events(work_item_id,from_state,to_state,revision,detail) VALUES (%s,%s,%s,%s,%s)",
            (updated.work_item_id, previous.status, updated.status, updated.revision, detail),
        )
        self.enqueue(conn, "WorkItem", updated.work_item_id, updated.model_dump(mode="json"))
        for record in records:
            self.add_record(record, conn=conn)

    def get(self, work_id: str) -> WorkItem:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload,owner FROM core.work_items WHERE id=%s", (work_id,)
            ).fetchone()
        if not row:
            raise KeyError(work_id)
        from trading_core.ownership import require_owner

        require_owner(self.scope, row["owner"])
        return WorkItem.model_validate({**row["payload"], "owner": row["owner"]})

    def list_work(self, limit: int = 100) -> list[WorkItem]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload,owner FROM core.work_items WHERE (%s::text IS NULL OR owner=%s) ORDER BY created_at DESC LIMIT %s",
                (self.scope, self.scope, limit),
            ).fetchall()
        return [WorkItem.model_validate({**r["payload"], "owner": r["owner"]}) for r in rows]

    def records(
        self, kind: str | None = None, work_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT kind,payload,owner FROM core.orchestration_records WHERE (%s::text IS NULL OR owner=%s OR owner='shared' OR kind='Agent') AND (%s::text IS NULL OR kind=%s) "
                "AND (%s::text IS NULL OR work_item_id=%s) ORDER BY created_at DESC LIMIT %s",
                (self.scope, self.scope, kind, kind, work_id, work_id, limit),
            ).fetchall()
        return [{"kind": r["kind"], **r["payload"]} for r in rows]

    def events(self, work_id: str) -> list[dict]:
        self.get(work_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM core.work_events WHERE work_item_id=%s ORDER BY sequence",
                (work_id,),
            ).fetchall()
        return json.loads(json.dumps(rows, default=str))

    def projection_status(self) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT count(*) FILTER (WHERE delivered_at IS NULL) AS pending, "
                "count(*) FILTER (WHERE last_error IS NOT NULL) AS errors FROM core.projection_outbox"
            ).fetchone()
        return row
