from trading_core.resources import resource

"""Transactional control, reservations and cycle history in authoritative PostgreSQL."""

import math
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from trading_core.contracts import Limits
from trading_core.security import redact
from trading_core.store import Store
from trading_core.work import now, uid


class Stopped(PermissionError):
    pass


class Ledger:
    def __init__(self, store=None):
        self.store = store or Store()

    def initialize(self):
        with self.store.connect() as conn:
            conn.execute(resource("infrastructure/postgres/003_autonomy.sql").read_text())
            conn.execute(resource("infrastructure/postgres/006_record_ownership.sql").read_text())
            conn.execute(resource("infrastructure/postgres/008_artifact_ownership.sql").read_text())
            conn.execute(
                resource("infrastructure/postgres/009_product_audit_ownership.sql").read_text()
            )
            initial = {
                "paused": False,
                "killed": False,
                "epoch": 0,
                "disabled_agents": [],
                "stopped_work": [],
                "require_human_review": False,
                "limits": Limits().model_dump(mode="json"),
                "daily_execution_caps": {"SUBSCRIPTION": False, "LOCAL": False},
            }
            conn.execute(
                "INSERT INTO core.autonomy_control VALUES (1,%s) ON CONFLICT DO NOTHING",
                (Jsonb(initial),),
            )

    def control(self, conn=None, lock=False):
        if conn is None:
            with self.store.connect() as c:
                return self.control(c, lock)
        row = conn.execute(
            "SELECT payload FROM core.autonomy_control WHERE id=1" + (" FOR UPDATE" if lock else "")
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
        from trading_core.ownership import require_write

        owner = self.store.scope or "core"
        if work_id:
            assigned = conn.execute(
                "SELECT owner FROM core.work_items WHERE id=%s", (work_id,)
            ).fetchone()
            if assigned:
                owner = assigned["owner"]
            elif self.store.scope is not None:
                raise KeyError(work_id)
        require_write(self.store.scope, owner)
        existing = conn.execute(
            "SELECT owner,kind FROM core.day3_records WHERE id=%s", (identifier,)
        ).fetchone()
        if existing:
            require_write(self.store.scope, existing["owner"])
            owner = existing["owner"]
        stored = conn.execute(
            "INSERT INTO core.day3_records(id,kind,work_item_id,payload,owner) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET payload=EXCLUDED.payload WHERE core.day3_records.owner=EXCLUDED.owner RETURNING id",
            (identifier, kind, work_id, Jsonb(payload), owner),
        ).fetchone()
        if not stored:
            raise PermissionError("Record ownership changed during write")
        for artifact in payload.get("result_artifacts", {}).values():
            if isinstance(artifact, dict) and artifact.get("path"):
                path = artifact["path"]
                prior = conn.execute(
                    "SELECT owner,record_id FROM core.artifact_owners WHERE path=%s", (path,)
                ).fetchone()
                if prior and (prior["owner"] != owner or prior["record_id"] != identifier):
                    raise PermissionError("Artifact already belongs to another record")
                conn.execute(
                    "INSERT INTO core.artifact_owners VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (path, owner, identifier),
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
                "SELECT id,kind,work_item_id,payload,owner FROM core.day3_records WHERE id=%s",
                (identifier,),
            ).fetchone()
        if not row:
            raise KeyError(identifier)
        from trading_core.ownership import require_owner

        require_owner(self.store.scope, row["owner"], row["kind"])
        return {
            "id": row["id"],
            "kind": row["kind"],
            "work_item_id": row["work_item_id"],
            **row["payload"],
        }

    def records(self, kind=None, limit=300):
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT * FROM core.day3_records WHERE (%s::text IS NULL OR owner=%s OR owner='shared' OR (owner='core' AND kind IN ('ProviderPolicy','TransportStatus','ProviderHealth'))) AND (%s::text IS NULL OR kind=%s) ORDER BY created_at DESC LIMIT %s",
                (self.store.scope, self.store.scope, kind, kind, limit),
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
        if work_id and self.store.scope:
            self.store.get(work_id)
        if self.store.scope:
            with self.store.connect() as conn:
                row = conn.execute(
                    "SELECT paused FROM core.product_controls WHERE product=%s", (self.store.scope,)
                ).fetchone()
                if row and row["paused"]:
                    raise Stopped("Product is paused")
                if (
                    work_id
                    and conn.execute(
                        "SELECT 1 FROM core.product_stops WHERE product=%s AND work_id=%s",
                        (self.store.scope, work_id),
                    ).fetchone()
                ):
                    raise Stopped("Product assignment stopped")
        control = self.control()
        self.check(control, agent, work_id, epoch)
        return control

    @staticmethod
    def daily_execution_limits_suspended(control, at=None):
        """Fail closed; expiry is enforced on every reservation, including after restart."""
        grant = control.get("daily_execution_limit_suspension", {})
        try:
            start = datetime.fromisoformat(grant["starts_at"])
            end = datetime.fromisoformat(grant["expires_at"])
            return (
                grant.get("operator_authorized") is True
                and grant.get("scope") == ["max_tokens_day", "max_compute_seconds_day"]
                and start.tzinfo is not None
                and end.tzinfo is not None
                and timedelta(0) < end - start <= timedelta(hours=25)
                and start <= (at or now()) < end
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    def suspend_daily_execution_limits_today(self, timezone="America/Chicago"):
        """Host-only operator action; never exposed to models or the lower-limits UI."""
        if self.store.scope is not None:
            raise PermissionError("Global governance requires the Core operator surface")
        started = now()
        local = started.astimezone(ZoneInfo(timezone))
        expires = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        grant = {
            "operator_authorized": True,
            "starts_at": started.isoformat(),
            "expires_at": expires.astimezone(UTC).isoformat(),
            "timezone": timezone,
            "scope": ["max_tokens_day", "max_compute_seconds_day"],
            "reason": "Operator requested daily execution limits suspended today for acceptance testing",
        }
        with self.store.connect() as conn:
            control = self.control(conn, True)
            control["daily_execution_limit_suspension"] = grant
            conn.execute(
                "UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
            )
            self.put(
                "ControlAction", {"action": "suspend_daily_execution_limits", **grant}, conn=conn
            )
        return grant

    def configure_non_api_daily_caps(self, *, subscription=False, local=False):
        """Explicit host/operator policy; not callable through model tools."""
        if self.store.scope is not None:
            raise PermissionError("Global governance requires the Core operator surface")
        if type(subscription) is not bool or type(local) is not bool:
            raise ValueError("Daily cap settings must be booleans")
        with self.store.connect() as conn:
            control = self.control(conn, True)
            control["daily_execution_caps"] = {"SUBSCRIPTION": subscription, "LOCAL": local}
            control.pop("daily_execution_limit_suspension", None)
            control["epoch"] += 1
            conn.execute(
                "UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
            )
            self.put(
                "ControlAction",
                {
                    "action": "configure_non_api_daily_caps",
                    "operator_authorized": True,
                    "timestamp": now().isoformat(),
                    "daily_execution_caps": control["daily_execution_caps"],
                    "api_daily_caps": True,
                    "replaces_temporary_suspension": True,
                },
                conn=conn,
            )
        return control

    @contextmanager
    def gate(self, agent=None, work_id=None, epoch=None):
        self.guard(agent, work_id, epoch)
        # Serialize dispatch/merge start with the kill-switch transaction.
        with self.store.connect() as c:
            control = self.control(c, True)
            self.check(control, agent, work_id, epoch)
            yield control

    def product_control(self):
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT paused FROM core.product_controls WHERE product=%s", (self.store.scope,)
            ).fetchone()
        return {"product": self.store.scope, "paused": bool(row and row["paused"])}

    def operate(self, action, agent=None, work_id=None, limits=None):
        if self.store.scope is not None:
            if action == "stop" and work_id:
                self.store.get(work_id)
                with self.store.connect() as conn:
                    conn.execute(
                        "INSERT INTO core.product_stops(product,work_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (self.store.scope, work_id),
                    )
                return {"product": self.store.scope, "stopped_work": work_id}
            if action not in {"pause", "resume"}:
                raise PermissionError("Global governance requires the Core operator surface")
            with self.store.connect() as conn:
                conn.execute(
                    "INSERT INTO core.product_controls(product,paused) VALUES (%s,%s) ON CONFLICT(product) DO UPDATE SET paused=EXCLUDED.paused",
                    (self.store.scope, action == "pause"),
                )
            return {"product": self.store.scope, "paused": action == "pause"}
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
            c.execute("UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),))
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

    def reserve_product(self, conn, agent, work_id, day, improvement):
        """Optional product policy hook; may only add restrictions."""

    def reserve(
        self,
        agent,
        work_id,
        *,
        improvement=False,
        cost=0,
        tokens=0,
        seconds=0,
        day=None,
        billing_source="UNKNOWN",
    ):
        if not math.isfinite(cost) or cost < 0 or tokens < 0 or seconds < 0:
            raise PermissionError("Invalid budget reservation")
        if billing_source not in {"SUBSCRIPTION", "LOCAL", "API", "UNKNOWN"}:
            billing_source = "UNKNOWN"
        self.guard(agent, work_id)
        day = day or datetime.now(UTC).date().isoformat()
        with self.store.connect() as c:
            control = self.control(c, True)
            self.check(control, agent, work_id)
            limits = Limits.model_validate(control["limits"])
            suspended = self.daily_execution_limits_suspended(control)
            # Only the host-selected adapter supplies billing; never model output.
            # Unknown billing fails closed, as do malformed/missing policy values.
            optional = billing_source in {"SUBSCRIPTION", "LOCAL"}
            capped = not (
                optional and control.get("daily_execution_caps", {}).get(billing_source) is False
            )
            c.execute(
                "INSERT INTO core.autonomy_daily(day) VALUES (%s) ON CONFLICT DO NOTHING", (day,)
            )
            used = c.execute(
                "SELECT * FROM core.autonomy_daily WHERE day=%s FOR UPDATE", (day,)
            ).fetchone()
            execution_used = {"tokens": 0, "seconds": 0}
            if capped and not suspended and (tokens or seconds):
                # Keep subscription/local reservations out of paid API ceilings.
                # Legacy unclassified reservations remain conservatively charged.
                execution_used = c.execute(
                    "SELECT COALESCE(sum((payload->>'tokens')::bigint),0) AS tokens, "
                    "COALESCE(sum((payload->>'seconds')::bigint),0) AS seconds "
                    "FROM core.day3_records WHERE kind='BudgetReservation' "
                    "AND payload->>'day'=%s AND "
                    "COALESCE(payload->>'billing_source','UNKNOWN') IN (%s,'UNKNOWN')",
                    (day, billing_source),
                ).fetchone()
            if (
                used["changes"] + int(improvement) > limits.max_changes_day
                or float(used["reserved_cost"]) + cost > limits.max_cloud_cost_day + 1e-9
                or (
                    capped
                    and not suspended
                    and tokens > 0
                    and execution_used["tokens"] + tokens > limits.max_tokens_day
                )
                or (
                    capped
                    and not suspended
                    and seconds > 0
                    and execution_used["seconds"] + seconds > limits.max_compute_seconds_day
                )
                or limits.max_repositories < 1
            ):
                raise PermissionError("AUTONOMY_BUDGET_EXHAUSTED")
            self.reserve_product(c, agent, work_id, day, improvement)
            c.execute(
                "UPDATE core.autonomy_daily SET changes=changes+%s,reserved_cost=reserved_cost+%s,reserved_tokens=reserved_tokens+%s,reserved_seconds=reserved_seconds+%s WHERE day=%s",
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
                    "daily_execution_limits_suspended": suspended,
                    "billing_source": billing_source,
                    "daily_execution_caps_enforced": capped and not suspended,
                },
                work_id=work_id,
                conn=c,
            )
        return control["epoch"]

    def totals(self):
        with self.store.connect() as c:
            rows = c.execute(
                "SELECT * FROM core.autonomy_daily ORDER BY day DESC LIMIT 30"
            ).fetchall()
        return redact(rows)
