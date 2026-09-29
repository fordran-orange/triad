"""Host-only provider control, durable fallback grants, and evidence-based status."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from trading_core.ledger import Ledger
from trading_core.providers.contracts import AGENTS, PREFERRED, SPECS, ProviderPolicy
from trading_core.providers.secrets import WindowsSecretStore
from trading_core.providers.transports import CLITransport, HTTPTransport
from trading_core.runtime import ProviderError
from trading_core.work import now


class ProviderControl:
    def __init__(self, ledger=None, secrets=None):
        self.ledger = ledger or Ledger()
        self.secrets = secrets or WindowsSecretStore()
        self._snapshot_cache = None

    def read(self, identifier, default=None):
        if self._snapshot_cache is not None:
            return self._snapshot_cache.get(identifier, default or {})
        try:
            return self.ledger.get(identifier)
        except KeyError:
            return default or {}

    def policy(self, agent):
        if agent not in AGENTS:
            raise ValueError("Unknown agent")
        record = self.read("provider-policy-" + agent)
        return (
            ProviderPolicy.model_validate(record["policy"])
            if record
            else ProviderPolicy(agent=agent, preferred_transport=PREFERRED[agent])
        )

    def save_policy(self, policy):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        self._snapshot_cache = None
        with self.ledger.store.lease("provider-policy-" + policy.agent):
            data = {"policy": policy.model_dump(), "updated_at": now().isoformat()}
            with self.ledger.store.connect() as conn:
                control = self.ledger.control(conn, lock=True)
                control["epoch"] += 1
                conn.execute(
                    "UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
                )
                self.ledger.put(
                    "ProviderPolicy", data, identifier="provider-policy-" + policy.agent, conn=conn
                )
            self.ledger.event("provider_policy_changed", agent=policy.agent, **data)
            for t, s in SPECS.items():
                if s["agent"] == policy.agent:
                    self.invalidate(t)
        return data

    def authorize_api_budget(self, amount):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        if not isinstance(amount, (float, int)) or not 0 <= amount <= 25:
            raise ValueError("API daily budget must be between 0 and 25 USD")
        with self.ledger.store.connect() as conn:
            control = self.ledger.control(conn, lock=True)
            control["epoch"] += 1
            control["limits"]["max_cloud_cost_day"] = amount
            conn.execute(
                "UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
            )
            self.ledger.put(
                "ProviderBudgetAuthorization",
                {"daily_usd": amount, "operator_authorized": True, "timestamp": now().isoformat()},
                conn=conn,
            )
        return {"daily_usd": amount}

    def configure_local_usage_alert(self, tokens, seconds):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        if type(tokens) is not int or type(seconds) is not int or tokens < 1 or seconds < 1:
            raise ValueError("Warning thresholds must be positive whole numbers")
        settings = {"tokens": tokens, "seconds": seconds}
        with self.ledger.store.connect() as conn:
            control = self.ledger.control(conn, lock=True)
            control["local_usage_alert"] = settings
            conn.execute(
                "UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
            )
            self.ledger.put(
                "ControlAction",
                {
                    "action": "configure_local_usage_alert",
                    "thresholds": settings,
                    "timestamp": now().isoformat(),
                },
                conn=conn,
            )
        return settings

    def local_usage_alert(self, control):
        thresholds = control.get("local_usage_alert", {"tokens": 100000, "seconds": 3600})
        day = now().date().isoformat()
        # Aggregate the entire day, not the dashboard's bounded recent-history list.
        with self.ledger.store.connect() as conn:
            totals = conn.execute(
                "SELECT count(*) AS requests, "
                "COALESCE(sum(COALESCE((payload->>'input_tokens')::bigint,0) + "
                "COALESCE((payload->>'output_tokens')::bigint,0)),0) AS tokens, "
                "COALESCE(sum((payload->>'duration')::double precision),0) AS seconds "
                "FROM core.day3_records WHERE kind='Usage' AND payload->>'agent'='LOCAL_QWEN' "
                "AND payload->>'mode'='REAL' AND left(payload->>'timestamp',10)=%s",
                (day,),
            ).fetchone()
        exceeded = [key for key in ("tokens", "seconds") if totals[key] >= thresholds[key]]
        return {
            "agent": "LOCAL_QWEN",
            "day": day,
            "timezone": "UTC",
            "thresholds": thresholds,
            "usage": totals,
            "exceeded": exceeded,
            "active": bool(exceeded),
            "blocking": False,
            "message": "Qwen usage is high today. Work continues; inspect recent tasks for unexpected repetition."
            if exceeded
            else "Qwen usage is below the warning thresholds. Work is not limited.",
        }

    def transport(self, transport_id):
        if transport_id not in SPECS:
            raise ValueError("Unknown transport")
        cls = CLITransport if SPECS[transport_id]["type"] == "CLI" else HTTPTransport
        return cls(transport_id, self)

    def snapshot(self, transport_id):
        return self.read("transport-status-" + transport_id)

    def invalidate(self, transport_id):
        self._snapshot_cache = None
        self.ledger.put(
            "TransportStatus",
            {
                "transport": transport_id,
                "health": "OFFLINE",
                "test": None,
                "workitem": None,
                "updated_at": now().isoformat(),
            },
            identifier="transport-status-" + transport_id,
        )

    def refresh(self, transport_id):
        self._snapshot_cache = None
        with self.ledger.store.lease("provider-test-" + transport_id):
            return self._refresh(transport_id)

    def _refresh(self, transport_id):
        adapter = self.transport(transport_id)
        data = adapter.detect()
        local_identity_unavailable = False
        if adapter.transport_type == "CLI":
            missing = data.get("install_status") in {"NOT_FOUND", "NOT_INSTALLED"}
            mismatch = data.get("compatibility_status") == "VERSION_MISMATCH"
            unavailable = data.get("install_status") != "INSTALLED"
            data.update(
                {"auth_state": "NOT_FOUND" if missing else "UNKNOWN", "billing_source": "UNKNOWN"}
                if unavailable or mismatch
                else adapter.authentication_status()
            )
            capabilities = (
                adapter.capabilities()
                if not unavailable and not mismatch
                else {
                    "native": [],
                    "granted": [],
                    "outer_boundary": "NOT_READY",
                    "execution_blocker": "NOT_FOUND"
                    if missing
                    else "VERSION_MISMATCH"
                    if mismatch
                    else "UNAVAILABLE",
                }
            )
            data.update(
                health="NOT_FOUND"
                if missing
                else "VERSION_MISMATCH"
                if mismatch
                else "AUTH_REQUIRED"
                if data["auth_state"] in {"NOT_AUTHENTICATED", "AUTH_FAILED"}
                else "OFFLINE",
                error=capabilities["execution_blocker"],
                capabilities=capabilities,
            )
            self.ledger.event(
                "cli_detected" if data["install_status"] == "INSTALLED" else "cli_missing",
                agent=adapter.agent,
                **data,
            )
        else:
            probe = adapter.health_check()
            data.update(
                reachability=probe.status,
                error=probe.error_class,
                latency=probe.latency,
                health="OFFLINE",
            )
            if probe.status == "AVAILABLE":
                data["auth_state"] = "AUTHENTICATED"
            if adapter.transport_type == "LOCAL":
                local = adapter.adapter()
                # The configured endpoint remains known even while its server is down.
                data["endpoint"] = local.base
                try:
                    data.update(adapter.list_models())
                    response = local.transport("/api/version")
                    if not isinstance(response, dict):
                        raise ProviderError("UNAVAILABLE", "LocalVersionUnavailable")
                    version = response.get("version")
                    if not isinstance(version, str) or not version.strip():
                        raise ProviderError("UNAVAILABLE", "LocalVersionUnavailable")
                    data["local_version"] = version
                except ProviderError as exc:
                    local_identity_unavailable = True
                    data.update(
                        reachability="UNAVAILABLE", error=data.get("error") or exc.error_class
                    )
        previous = self.snapshot(transport_id)
        if local_identity_unavailable and previous.get("endpoint") == data.get("endpoint"):
            # Absence of a version probe is not evidence that the installed version changed.
            # Retain identity/proofs, but the current probe error still blocks readiness.
            data["local_version"] = previous.get("local_version")
        changed = any(
            previous.get(key) != data.get(key)
            for key in ("cli_version", "executable", "endpoint", "local_version")
        )
        data.update(
            test=None if changed else previous.get("test"),
            workitem=None if changed else previous.get("workitem"),
            updated_at=now().isoformat(),
        )
        self.ledger.put("TransportStatus", data, identifier="transport-status-" + transport_id)
        return data

    def set_key(self, transport_id, secret):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        if SPECS.get(transport_id, {}).get("type") != "API":
            raise ValueError("API transport required")
        self.secrets.set_secret(transport_id, secret)
        self.invalidate(transport_id)
        self.ledger.event("api_credential_added", transport=transport_id)
        return {"configured": True}

    def delete_key(self, transport_id):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        if SPECS.get(transport_id, {}).get("type") != "API":
            raise ValueError("API transport required")
        self.secrets.delete_secret(transport_id)
        self.invalidate(transport_id)
        self.ledger.event("api_credential_removed", transport=transport_id)
        return {"configured": False}

    def enable(self, agent, enabled):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        value = self.ledger.operate("enable" if enabled else "disable", agent=agent)
        self.ledger.event("provider_enabled" if enabled else "provider_disabled", agent=agent)
        return value

    def allow_once(self, agent, work_id):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        if agent not in AGENTS[:3]:
            raise ValueError("Frontier agent required")
        work = self.ledger.store.get(work_id)
        if agent not in {work.assigned_agent, work.reviewer} or work.status not in {
            "IN_PROGRESS",
            "AWAITING_REVIEW",
            "ASSIGNED",
        }:
            raise PermissionError("Approval requires an active assigned WorkItem")
        self.ledger.guard(agent, work_id)
        record = {
            "agent": agent,
            "work_item_id": work_id,
            "used": False,
            "expires_at": (now() + timedelta(minutes=15)).isoformat(),
            "created_at": now().isoformat(),
        }
        identifier = self.ledger.put("FallbackGrant", record, work_id=work_id)
        self.ledger.event("transport_fallback_allowed", work_id, grant_id=identifier, agent=agent)
        return {"grant_id": identifier, **record}

    def authenticate(self, transport_id, logout=False):
        if getattr(getattr(self.ledger, "store", None), "scope", None) is not None:
            raise PermissionError("Provider governance requires the Core operator surface")
        adapter = self.transport(transport_id)
        if adapter.transport_type != "CLI":
            raise ValueError("CLI login required; use credential controls for APIs")
        with self.ledger.store.lease("provider-auth-" + transport_id):
            self.invalidate(transport_id)
            self.ledger.put(
                "TransportStatus",
                {
                    "transport": transport_id,
                    "auth_state": "AUTHENTICATING",
                    "health": "OFFLINE",
                    "updated_at": now().isoformat(),
                },
                identifier="transport-status-" + transport_id,
            )
            self.ledger.event("provider_auth_started", transport=transport_id)
            result = adapter.logout() if logout else adapter.authenticate()
            self.ledger.event(
                "provider_logged_out"
                if logout and result["success"]
                else "provider_auth_succeeded"
                if result["success"]
                else "provider_auth_failed",
                transport=transport_id,
                **result,
            )
            return self.refresh(transport_id)

    @staticmethod
    def proven(snapshot):
        from datetime import datetime

        if (
            snapshot.get("install_status")
            in {"NOT_FOUND", "NOT_INSTALLED", "DETECTION_FAILED", "UNAVAILABLE"}
            or snapshot.get("compatibility_status") == "VERSION_MISMATCH"
        ):
            return False
        for key in ("test", "workitem"):
            evidence = snapshot.get(key) or {}
            if not evidence.get("success") or evidence.get("mode") != "REAL":
                return False
            try:
                age = now() - datetime.fromisoformat(evidence["completed_at"])
                if age < timedelta(0):
                    return False
            except (ValueError, TypeError, KeyError):
                return False
        return snapshot.get("auth_state") == "AUTHENTICATED" and not snapshot.get("error")

    def monitor_connections(self):
        """Refresh selected non-API connections without inference, login or replay."""
        import logging

        from trading_core.store import ConcurrentUpdate

        for agent in AGENTS:
            tid = self.policy(agent).preferred_transport
            if SPECS[tid]["type"] == "API":
                continue
            try:
                with self.ledger.store.lease("provider-auth-" + tid):
                    self.refresh(tid)
            except ConcurrentUpdate:
                continue  # An operator login or real verification owns the connection.
            except Exception:  # noqa: BLE001 - keep monitoring other providers during outages
                logging.getLogger("triad.providers").warning(
                    "Connection monitor could not refresh %s", tid
                )

    @classmethod
    def readiness_state(cls, snapshot):
        """Distinguish missing or stale evidence from a reported connection failure."""
        if snapshot.get("configuration") == "NOT_CONFIGURED":
            return "NOT_CONFIGURED"
        if snapshot.get("install_status") in {"NOT_FOUND", "NOT_INSTALLED"}:
            return "NOT_FOUND"
        if snapshot.get("compatibility_status") == "VERSION_MISMATCH":
            return "VERSION_MISMATCH"
        if snapshot.get("auth_state") in {"NOT_AUTHENTICATED", "AUTH_FAILED"}:
            return "AUTH_REQUIRED"
        if snapshot.get("error"):
            return (
                snapshot.get("health")
                if snapshot.get("health") not in {None, "ONLINE", "OFFLINE"}
                else "CONNECTION_ERROR"
            )
        if cls.proven(snapshot):
            return "ONLINE"
        if any(
            snapshot.get(k, {}).get("success") is False
            for k in ("test", "workitem")
            if snapshot.get(k)
        ):
            return "VERIFICATION_FAILED"
        if snapshot.get("auth_state") == "AUTHENTICATED":
            if all(
                (snapshot.get(k) or {}).get("success")
                and (snapshot.get(k) or {}).get("mode") == "REAL"
                for k in ("test", "workitem")
            ):
                return "VERIFICATION_REQUIRED"
            return "VERIFICATION_REQUIRED"
        return "NOT_CHECKED"

    def dashboard(self):
        identifiers = ["provider-policy-" + a for a in AGENTS] + [
            "transport-status-" + t for t in SPECS
        ]
        with self.ledger.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,kind,work_item_id,payload FROM core.day3_records WHERE id=ANY(%s)",
                (identifiers,),
            ).fetchall()
        self._snapshot_cache = {
            r["id"]: {
                "id": r["id"],
                "kind": r["kind"],
                "work_item_id": r["work_item_id"],
                **r["payload"],
            }
            for r in rows
        }
        control = self.ledger.control()
        usage = self.ledger.records("Usage", 2000)
        today = now().date().isoformat()
        agents = []
        for agent in AGENTS:
            policy = self.policy(agent)
            rows = [r for r in usage if r.get("agent") == agent and r.get("mode") == "REAL"]
            transports = []
            for tid, spec in SPECS.items():
                if spec["agent"] != agent:
                    continue
                state = self.snapshot(tid)
                configured = self.secrets.has_secret(tid) if spec["type"] == "API" else None
                transports.append(
                    {
                        **state,
                        "transport": tid,
                        **spec,
                        "configured": configured,
                        "selected_model": policy.models.get(
                            tid, "qwen3:4b" if tid == "ollama" else "Auto"
                        ),
                        "online": self.proven(state),
                        "readiness": self.readiness_state(state),
                        "capabilities": self.transport(tid).capabilities(),
                    }
                )
            preferred = next(t for t in transports if t["transport"] == policy.preferred_transport)
            enabled = agent not in control["disabled_agents"]
            latest = rows[0] if rows else {}
            daily = [r for r in rows if r.get("timestamp", "").startswith(today)]
            agents.append(
                {
                    "agent": agent,
                    "provider": preferred["provider"],
                    "enabled": enabled,
                    "policy": policy.model_dump(),
                    "state": "DISABLED"
                    if not enabled
                    else "ONLINE"
                    if preferred["online"]
                    else preferred["readiness"],
                    "transports": transports,
                    "active_transport": latest.get("transport"),
                    "billing_source": latest.get(
                        "billing_source", preferred.get("billing_source", "UNKNOWN")
                    ),
                    "last_success": next(
                        (r["timestamp"] for r in rows if r["status"] == "SUCCESS"), None
                    ),
                    "last_error": latest.get("error_class"),
                    "latency": latest.get("duration"),
                    "actual_model": latest.get("actual_model"),
                    "today": {
                        "requests": len(daily),
                        "input_tokens": sum(r.get("input_tokens", 0) for r in daily),
                        "output_tokens": sum(r.get("output_tokens", 0) for r in daily),
                        "estimated_api_cost": sum(
                            r.get("estimated_cost", 0)
                            for r in daily
                            if r.get("billing_source") == "API"
                        ),
                    },
                    "permissions": {
                        "authority_tier": 0 if agent == "LOCAL_QWEN" else 2,
                        "research": "Governed WorkItem required",
                        "code_modification": "reviewed text proposals only",
                        "shell": "Not granted; isolated file tools only",
                        "git": "host reviewed changes only",
                        "web": False,
                        "external_tools": False,
                        "review_eligibility": agent != "LOCAL_QWEN",
                        "autonomous_improvement": "product policy and Core authority required",
                        "trading_research": "bounded research only",
                        "live_execution": False,
                    },
                }
            )
        passed = all(
            a["state"] == "ONLINE"
            and a["policy"]["preferred_transport"] == PREFERRED[a["agent"]]
            and a["billing_source"] == ("LOCAL" if a["agent"] == "LOCAL_QWEN" else "SUBSCRIPTION")
            for a in agents
        )
        return {
            "agents": agents,
            "gate": "PASS" if passed else "BLOCKED",
            "execution_ready": passed,
            "control": control,
            "local_usage_alert": self.local_usage_alert(control),
            "active_runs": [
                r for r in self.ledger.records("TransportRun", 100) if r.get("status") == "RUNNING"
            ],
            "secret_storage": "Windows Credential Manager",
            "timestamp": now().isoformat(),
        }

    def require_gate(self):
        if self.dashboard()["gate"] != "PASS":
            raise PermissionError("PROVIDER_GATE_BLOCKED: verified provider WorkItems required")


class TransportRouter:
    def __init__(self, control):
        self.control = control

    def select(self, request, input_ceiling, transport_id=None):
        host = self.control
        ledger = host.ledger
        policy = host.policy(request.agent_id)
        preferred = host.transport(transport_id or policy.preferred_transport)
        if preferred.agent != request.agent_id:
            raise PermissionError("Transport identity mismatch")
        adapter = preferred
        fallback = False
        failure = None
        auth = {}
        if preferred.transport_type == "CLI" and preferred.readonly_ready():
            auth = preferred.authentication_status()
            preferred._verified_billing_source = auth.get("billing_source", "UNKNOWN")
        if preferred.transport_type == "CLI" and not (
            (request.role == "REVIEW" or preferred.agent in {"CLAUDE", "GROK"})
            and preferred.readonly_ready()
            and auth.get("auth_state") == "AUTHENTICATED"
        ):
            # Installation/authentication does not override the missing outer boundary.
            failure = "OuterBoundaryUnavailable"
            if transport_id:
                ledger.event(
                    "transport_test_failed",
                    request.work_item_id,
                    transport=transport_id,
                    reason=failure,
                )
                raise ProviderError("UNAVAILABLE", failure)
            fallback = True
            api = next(
                t for t, s in SPECS.items() if s["agent"] == request.agent_id and s["type"] == "API"
            )
            adapter = host.transport(api)
        with ledger.store.connect() as conn:
            control = ledger.control(conn, lock=True)
            ledger.check(control, request.agent_id, request.work_item_id, request.control_epoch)
            if adapter.transport_type == "API":
                grant = conn.execute(
                    "SELECT id,payload FROM core.day3_records WHERE kind='FallbackGrant' "
                    "AND work_item_id=%s AND payload->>'agent'=%s AND payload->>'used'='false' "
                    "AND (payload->>'expires_at')::timestamptz > now() ORDER BY created_at LIMIT 1 FOR UPDATE",
                    (request.work_item_id, request.agent_id),
                ).fetchone()
                if fallback and policy.fallback != "ALLOW_WITHIN_BUDGET" and not grant:
                    # Audit denial outside rolled-back transaction below.
                    failure = (
                        "FallbackApprovalRequired"
                        if policy.fallback == "ASK_EACH_TIME"
                        else "APIFallbackDisabled"
                    )
                elif not host.secrets.has_secret(adapter.transport_id):
                    failure = "APINotConfigured"
                else:
                    health = adapter.health_check()
                    if health.status != "AVAILABLE":
                        failure = health.error_class or "APIUnavailable"
                    else:
                        estimate = adapter.estimate_cost(input_ceiling, request.token_budget)
                        spent = conn.execute(
                            "SELECT COALESCE(sum((payload->>'reserved_cost')::numeric),0) AS cost "
                            "FROM core.day3_records WHERE kind='TransportDecision' "
                            "AND payload->>'agent'=%s AND payload->>'day'=%s",
                            (request.agent_id, now().date().isoformat()),
                        ).fetchone()["cost"]
                        if estimate > min(
                            request.cost_budget, control["limits"]["max_cost_run"]
                        ) or float(spent) + estimate > min(
                            policy.api_daily_budget, control["limits"]["max_cloud_cost_day"]
                        ):
                            failure = "APIBudgetExhausted"
                        else:
                            failure = None
                            if fallback and grant:
                                ledger.put(
                                    "FallbackGrant",
                                    {**grant["payload"], "used": True, "run_id": request.run_id},
                                    identifier=grant["id"],
                                    work_id=request.work_item_id,
                                    conn=conn,
                                )
            else:
                estimate = 0
            if not failure:
                decision = {
                    "agent": request.agent_id,
                    "run_id": request.run_id,
                    "selected_transport": adapter.transport_id,
                    "billing_source": adapter.billing_source(),
                    "fallback_policy": policy.fallback,
                    "fallback": fallback,
                    "selection_reason": "operator-authorized API fallback"
                    if fallback
                    else "operator preferred transport",
                    "reserved_cost": estimate,
                    "day": now().date().isoformat(),
                    "timestamp": now().isoformat(),
                }
                ledger.put("TransportDecision", decision, work_id=request.work_item_id, conn=conn)
        if failure:
            ledger.event(
                "transport_fallback_denied",
                request.work_item_id,
                agent=request.agent_id,
                reason=failure,
                preferred_transport=preferred.transport_id,
                fallback_policy=policy.fallback,
                run_id=request.run_id,
            )
            raise ProviderError("UNAVAILABLE", failure)
        ledger.event("transport_selected", request.work_item_id, **decision)
        return adapter
