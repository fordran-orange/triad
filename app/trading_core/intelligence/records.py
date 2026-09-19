"""Append-only canonical intelligence evidence; explicit host/product ownership."""

from psycopg.types.json import Jsonb

from trading_core.ledger import Ledger
from trading_core.ownership import require_owner
from trading_core.resources import resource
from trading_core.security import ensure_no_secret
from trading_core.store import Store
from trading_core.work import uid


class Records:
    def __init__(self, store=None):
        self.store = store or Store()
        self.ledger = Ledger(self.store)

    def initialize(self):
        with self.store.connect() as conn:
            conn.execute(resource("infrastructure/postgres/010_intelligence.sql").read_text())

    def append(self, kind, payload, *, owner="core", identifier=None, conn=None):
        from trading_core.ownership import require_write

        if self.store.scope is not None and kind in {
            "ImplementationRun",
            "QARun",
            "QualityDebt",
            "CapabilityVersion",
        }:
            raise PermissionError("Canonical build and QA evidence requires trusted Core ingestion")
        require_write(self.store.scope, owner)
        ensure_no_secret(payload)
        if conn is None:
            with self.store.connect() as connection:
                return self.append(
                    kind, payload, owner=owner, identifier=identifier, conn=connection
                )
        identifier = identifier or uid()
        conn.execute(
            "INSERT INTO core.intelligence_records(id,kind,owner,payload) VALUES (%s,%s,%s,%s)",
            (identifier, kind, owner, Jsonb(payload)),
        )
        # Existing outbox keeps graph projection durable and atomic with evidence.
        self.ledger.put(kind, payload, identifier=identifier, conn=conn)
        # Ledger is host code here; canonical ownership is always the explicit owner.
        conn.execute("UPDATE core.day3_records SET owner=%s WHERE id=%s", (owner, identifier))
        return identifier

    def get(self, identifier, *, conn=None):
        if conn is None:
            with self.store.connect() as connection:
                return self.get(identifier, conn=connection)
        row = conn.execute(
            "SELECT * FROM core.intelligence_records WHERE id=%s", (identifier,)
        ).fetchone()
        if not row:
            raise KeyError(identifier)
        if not (row["kind"] == "CapabilityVersion" and row["owner"] == "core"):
            require_owner(self.store.scope, row["owner"])
        return {**row["payload"], "id": row["id"], "kind": row["kind"], "owner": row["owner"]}

    def list(self, kind, *, shared=False, conn=None):
        if conn is None:
            with self.store.connect() as connection:
                return self.list(kind, shared=shared, conn=connection)
        # Only approved capability versions are shared platform facts.
        shared = shared and kind == "CapabilityVersion"
        rows = conn.execute(
            "SELECT * FROM core.intelligence_records WHERE kind=%s AND (%s::text IS NULL OR owner=%s OR (%s AND owner='core')) ORDER BY created_at,id",
            (kind, self.store.scope, self.store.scope, shared),
        ).fetchall()
        return [
            {**r["payload"], "id": r["id"], "kind": r["kind"], "owner": r["owner"]} for r in rows
        ]
