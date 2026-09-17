"""Transactional control, reservations and cycle history in authoritative PostgreSQL."""

import math
from contextlib import contextmanager
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from triad.day3.contracts import Limits
from triad.day3.security import redact
from triad.settings import ROOT
from triad.store import Store
from triad.work import now, uid


class Stopped(PermissionError):
    pass


class Ledger:
    def __init__(self, store=None):
        self.store = store or Store()

    def initialize(self):
        with self.store.connect() as conn:
            conn.execute((ROOT / "infrastructure/postgres/003_autonomy.sql").read_text())
            initial = {
                "paused": False,
                "killed": False,
                "epoch": 0,
                "disabled_agents": [],
                "stopped_work": [],
                "require_human_review": False,
                "limits": Limits().model_dump(mode="json"),
            }
            conn.execute(
                "INSERT INTO triad.autonomy_control VALUES (1,%s) ON CONFLICT DO NOTHING",
                (Jsonb(initial),),
            )

    def control(self, conn=None, lock=False):
        if conn is None:
            with self.store.connect() as c:
                return self.control(c, lock)
        row = conn.execute(
            "SELECT payload FROM triad.autonomy_control WHERE id=1"
            + (" FOR UPDATE" if lock else "")
        ).fetchone()
        if not row:
            raise Stopped("Initialize Day 3 before dispatch")
        return row["payload"]

    def put(self, kind, payload, identifier=None, work_id=None, conn=None):
        if conn is None:
            with self.store.connect() as c:
                return self.put(kind, payload, identifier, work_id, c)
        identifier = identifier or uid()
        payload = redact(payload)
        conn.execute(
            "INSERT INTO triad.day3_records(id,kind,work_item_id,payload) VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET payload=EXCLUDED.payload",
            (identifier, kind, work_id, Jsonb(payload)),
        )
        self.store.enqueue(
            conn,
            "Day3Record",
            identifier,
            {"record_kind": kind, "work_item_id": work_id, **payload},
        )
        return identifier

    def get(self, identifier):
        with self.store.connect() as c:
            row = c.execute(
                "SELECT id,kind,work_item_id,payload FROM triad.day3_records WHERE id=%s",
                (identifier,),
            ).fetchone()
        if not row:
            raise KeyError(identifier)
        return {
            "id": row["id"],
            "kind": row["kind"],
            "work_item_id": row["work_item_id"],
            **row["payload"],
        }

    def records(self, kind=None, limit=300):
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT * FROM triad.day3_records WHERE (%s::text IS NULL OR kind=%s) ORDER BY created_at DESC LIMIT %s",
                (kind, kind, limit),
            ).fetchall()
        return [
            {"id": r["id"], "kind": r["kind"], "work_item_id": r["work_item_id"], **r["payload"]}
            for r in rows
        ]

    def event(self, name, work_id=None, **data):
        return self.put(
            "Event", {"event": name, "timestamp": now().isoformat(), **data}, work_id=work_id
        )

    @staticmethod
    def check(control, agent=None, work_id=None, epoch=None):
        if (
            control["paused"]
            or control["killed"]
            or (agent and agent in control["disabled_agents"])
            or (work_id and work_id in control["stopped_work"])
            or (epoch is not None and epoch != control["epoch"])
        ):
            raise Stopped("Run cancelled or autonomy paused")

    def guard(self, agent=None, work_id=None, epoch=None):
        control = self.control()
        self.check(control, agent, work_id, epoch)
        return control

    @contextmanager
    def gate(self, agent=None, work_id=None, epoch=None):
        # Serialize dispatch/merge start with the kill-switch transaction.
        with self.store.connect() as c:
            control = self.control(c, True)
            self.check(control, agent, work_id, epoch)
            yield control

    def operate(self, action, agent=None, work_id=None, limits=None):
        with self.store.connect() as c:
            control = self.control(c, True)
            if action in {"pause", "kill"}:
                control["paused"] = True
                control["epoch"] += 1
                if action == "kill":
                    control["killed"] = True
            elif action == "resume":
                control["paused"] = False
                control["killed"] = False
            elif action == "stop":
                if not work_id:
                    raise ValueError("Work ID required")
                control["stopped_work"] = list(set(control["stopped_work"] + [work_id]))
            elif action in {"disable", "enable"}:
                if agent not in {"CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"}:
                    raise ValueError("Unknown agent")
                disabled = set(control["disabled_agents"])
                if action == "disable":
                    disabled.add(agent)
                else:
                    disabled.discard(agent)
                control["disabled_agents"] = sorted(disabled)
            elif action == "human_review":
                control["require_human_review"] = True
            elif action == "lower_limits":
                requested = Limits.model_validate(
                    {**control["limits"], **(limits or {})}
                ).model_dump(mode="json")
                for key, value in requested.items():
                    if key == "allowed_directories":
                        if not set(value) <= set(control["limits"][key]):
                            raise PermissionError("Cannot widen paths")
                    elif value > control["limits"][key]:
                        raise PermissionError("UI may only lower limits")
                control["limits"] = requested
            else:
                raise ValueError("Unsupported human control")
            c.execute("UPDATE triad.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),))
            self.put(
                "ControlAction",
                {
                    "action": action,
                    "agent": agent,
                    "work_item_id": work_id,
                    "timestamp": now().isoformat(),
                    "control": control,
                },
                conn=c,
            )
        return control

    def reserve(self, agent, work_id, *, improvement=False, cost=0, tokens=0, seconds=0, day=None):
        if not math.isfinite(cost) or cost < 0 or tokens < 0 or seconds < 0:
            raise PermissionError("Invalid budget reservation")
        day = day or datetime.now(UTC).date().isoformat()
        with self.store.connect() as c:
            control = self.control(c, True)
            self.check(control, agent, work_id)
            limits = Limits.model_validate(control["limits"])
            c.execute(
                "INSERT INTO triad.autonomy_daily(day) VALUES (%s) ON CONFLICT DO NOTHING", (day,)
            )
            used = c.execute(
                "SELECT * FROM triad.autonomy_daily WHERE day=%s FOR UPDATE", (day,)
            ).fetchone()
            if (
                used["changes"] + int(improvement) > limits.max_changes_day
                or float(used["reserved_cost"]) + cost > limits.max_cloud_cost_day + 1e-9
                or used["reserved_tokens"] + tokens > limits.max_tokens_day
                or used["reserved_seconds"] + seconds > limits.max_compute_seconds_day
                or limits.max_repositories < 1
            ):
                raise PermissionError("AUTONOMY_BUDGET_EXHAUSTED")
            if improvement:
                exists = c.execute(
                    "SELECT 1 FROM triad.improvement_slots WHERE day=%s AND agent=%s", (day, agent)
                ).fetchone()
                if exists:
                    raise PermissionError("Daily agent improvement slot already consumed")
                c.execute(
                    "INSERT INTO triad.improvement_slots VALUES (%s,%s,%s)", (day, agent, work_id)
                )
            c.execute(
                "UPDATE triad.autonomy_daily SET changes=changes+%s,reserved_cost=reserved_cost+%s,reserved_tokens=reserved_tokens+%s,reserved_seconds=reserved_seconds+%s WHERE day=%s",
                (int(improvement), cost, tokens, seconds, day),
            )
            self.put(
                "BudgetReservation",
                {
                    "agent": agent,
                    "day": day,
                    "improvement": improvement,
                    "cost": cost,
                    "tokens": tokens,
                    "seconds": seconds,
                },
                work_id=work_id,
                conn=c,
            )
        return control["epoch"]

    def totals(self):
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT * FROM triad.autonomy_daily ORDER BY day DESC LIMIT 30"
            ).fetchall()
        return redact(rows)
