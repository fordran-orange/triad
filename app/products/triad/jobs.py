from products.triad.resources import product_resource

"""Persistent cycle submissions; uncertain executions never receive automatic replay."""

from datetime import date

from psycopg.types.json import Jsonb
from trading_core.brain import Brain
from trading_core.ledger import Stopped
from trading_core.security import redact
from trading_core.store import ConcurrentUpdate
from trading_core.work import uid

from products.triad.cycles import Cycles, failure_code


class Jobs:
    def __init__(self, cycles=None):
        self.cycles = cycles or Cycles()
        self.store = self.cycles.host.store
        self.ledger = self.cycles.ledger

    def initialize(self):
        with self.store.connect() as conn:
            conn.execute(product_resource("004_jobs.sql").read_text())

    def list(self):
        with self.store.connect() as conn:
            return redact(
                conn.execute(
                    "SELECT * FROM triad.cycle_jobs ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            )

    def submit(self, mode="REAL", scheduled=False):
        if mode not in {"REAL", "SIMULATED"}:
            raise ValueError("Explicit cycle mode required")
        if mode == "REAL":
            try:
                self.cycles.require_execution_gate()
            except PermissionError:
                if self.store.scope == "triad":
                    from products.triad.cycle_history import CycleHistory

                    CycleHistory(self.store).blocked(mode=mode, scheduled=scheduled)
                raise
        date.fromisoformat(self.cycles.day)
        with self.store.connect() as conn:
            control = self.ledger.control(conn, lock=True)
            self.ledger.check(control)
            row = conn.execute(
                "INSERT INTO triad.cycle_jobs(id,day,mode,status,control_epoch,scheduled) "
                "VALUES (%s,%s,%s,'QUEUED',%s,%s) ON CONFLICT(day,mode) DO NOTHING RETURNING *",
                (uid(), self.cycles.day, mode, control["epoch"], scheduled),
            ).fetchone()
            if row:
                self.ledger.put(
                    "JobEvent",
                    {
                        "event": "job_queued",
                        "job_id": row["id"],
                        "day": self.cycles.day,
                        "mode": mode,
                    },
                    conn=conn,
                )
            else:
                row = conn.execute(
                    "SELECT * FROM triad.cycle_jobs WHERE day=%s AND mode=%s",
                    (self.cycles.day, mode),
                ).fetchone()
        return {"accepted": True, "job": redact(row)}

    def finish(self, job_id, status, result=None, reason=None):
        with self.store.connect() as conn:
            row = conn.execute(
                "UPDATE triad.cycle_jobs SET status=%s,result=%s,failure_code=%s,finished_at=now() "
                "WHERE id=%s AND status IN ('QUEUED','RUNNING') RETURNING id",
                (status, Jsonb(redact(result)) if result is not None else None, reason, job_id),
            ).fetchone()
            if row:
                self.ledger.put(
                    "JobEvent",
                    {
                        "event": "job_finished",
                        "job_id": job_id,
                        "status": status,
                        "failure_code": reason,
                    },
                    conn=conn,
                )

    def cancel(self, job_id):
        # Running work uses the existing kill/stop controls, never a cosmetic status edit.
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM triad.cycle_jobs WHERE id=%s FOR UPDATE", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(job_id)
            if row["status"] != "QUEUED":
                raise PermissionError(
                    "Only queued jobs can be cancelled here; use running-work controls"
                )
            conn.execute(
                "UPDATE triad.cycle_jobs SET status='CANCELLED',failure_code='OPERATOR_CANCELLED',finished_at=now() WHERE id=%s",
                (job_id,),
            )
            self.ledger.put("JobEvent", {"event": "job_cancelled", "job_id": job_id}, conn=conn)
        return {"status": "CANCELLED", "id": job_id}

    def once(self):
        try:
            with self.store.lease("day4-worker"):
                return self._owned_once()
        except ConcurrentUpdate:
            return {"status": "WORKER_BUSY"}

    def _owned_once(self):
        # A worker owns the database session lock throughout execution. A replacement
        # pauses authority before reconciling abandoned RUNNING rows. Never replay them.
        with self.store.connect() as conn:
            abandoned = conn.execute(
                "SELECT id FROM triad.cycle_jobs WHERE status='RUNNING'"
            ).fetchall()
        if abandoned:
            self.ledger.operate("pause")
            for row in abandoned:
                self.finish(row["id"], "UNCERTAIN", reason="WORKER_INTERRUPTED_RECONCILE_REQUIRED")
            self.cycles.recover()
            Brain(self.store).flush()
            return {"status": "UNCERTAIN", "jobs": [r["id"] for r in abandoned]}
        with self.store.connect() as conn:
            control = self.ledger.control(conn, lock=True)
            if control["paused"] or control["killed"]:
                return {"status": "PAUSED"}
            row = conn.execute(
                "SELECT * FROM triad.cycle_jobs WHERE status='QUEUED' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if not row:
                return {"status": "IDLE"}
            stale = row["control_epoch"] != control["epoch"] or str(row["day"]) != self.cycles.day
            if not stale:
                worker_id = uid()
                conn.execute(
                    "UPDATE triad.cycle_jobs SET status='RUNNING',started_at=now(),worker_id=%s WHERE id=%s",
                    (worker_id, row["id"]),
                )
                self.ledger.put(
                    "JobEvent",
                    {"event": "job_started", "job_id": row["id"], "worker_id": worker_id},
                    conn=conn,
                )
        if stale:
            self.finish(row["id"], "CANCELLED", reason="STALE_DAY_OR_CANCELLED_AUTHORITY")
            return {"status": "CANCELLED", "id": row["id"]}
        try:
            self.ledger.guard(epoch=row["control_epoch"])
            result = self.cycles.run(
                mode=row["mode"], scheduled=row["scheduled"], expected_epoch=row["control_epoch"]
            )
            status = "COMPLETED" if result["status"] == "COMPLETED" else "BLOCKED"
            self.finish(row["id"], status, result)
        except Stopped:
            status = "CANCELLED"
            self.finish(row["id"], status, reason="CONTROL_STOPPED")
        except Exception as exc:  # noqa: BLE001 - no raw provider errors in queue records
            status = "BLOCKED"
            self.finish(row["id"], status, reason=failure_code(exc))
        Brain(self.store).flush()
        return {"id": row["id"], "status": status}
