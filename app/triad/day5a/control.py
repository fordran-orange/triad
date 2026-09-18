"""Host-only provider control, durable fallback grants, and evidence-based status."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from triad.day3.adapters import ProviderError
from triad.day3.ledger import Ledger
from triad.day5a.contracts import AGENTS, PREFERRED, SPECS, ProviderPolicy
from triad.day5a.secrets import WindowsSecretStore
from triad.day5a.transports import CLITransport, HTTPTransport
from triad.work import now


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
        self._snapshot_cache = None
        with self.ledger.store.lease("provider-policy-" + policy.agent):
            data = {"policy": policy.model_dump(), "updated_at": now().isoformat()}
            with self.ledger.store.connect() as conn:
                control = self.ledger.control(conn, lock=True)
                control["epoch"] += 1
                conn.execute(
                    "UPDATE triad.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
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
        if not isinstance(amount, (float, int)) or not 0 <= amount <= 25:
            raise ValueError("API daily budget must be between 0 and 25 USD")
        with self.ledger.store.connect() as conn:
            control = self.ledger.control(conn, lock=True)
            control["epoch"] += 1
            control["limits"]["max_cloud_cost_day"] = amount
            conn.execute(
                "UPDATE triad.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),)
            )
            self.ledger.put(
                "ProviderBudgetAuthorization",
                {"daily_usd": amount, "operator_authorized": True, "timestamp": now().isoformat()},
                conn=conn,
            )
        return {"daily_usd": amount}

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
        adapter = self.transport(transport_id)
        data = adapter.detect()
        if adapter.transport_type == "CLI":
            data.update(adapter.authentication_status())
            data.update(
                health="AUTH_REQUIRED" if data["auth_state"] != "AUTHENTICATED" else "OFFLINE",
                error="OuterBoundaryUnavailable",
                capabilities=adapter.capabilities(),
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
                try:
                    data.update(adapter.list_models())
                    data["local_version"] = (
                        adapter.adapter().transport("/api/version").get("version")
                    )
                except ProviderError:
                    pass
        previous = self.snapshot(transport_id)
        data.update(
            test=previous.get("test"),
            workitem=previous.get("workitem"),
            updated_at=now().isoformat(),
        )
        self.ledger.put("TransportStatus", data, identifier="transport-status-" + transport_id)
        return data

    def set_key(self, transport_id, secret):
        if SPECS.get(transport_id, {}).get("type") != "API":
            raise ValueError("API transport required")
        self.secrets.set_secret(transport_id, secret)
        self.invalidate(transport_id)
        self.ledger.event("api_credential_added", transport=transport_id)
        return {"configured": True}

    def delete_key(self, transport_id):
        if SPECS.get(transport_id, {}).get("type") != "API":
            raise ValueError("API transport required")
        self.secrets.delete_secret(transport_id)
        self.invalidate(transport_id)
        self.ledger.event("api_credential_removed", transport=transport_id)
        return {"configured": False}

    def enable(self, agent, enabled):
        value = self.ledger.operate("enable" if enabled else "disable", agent=agent)
        self.ledger.event("provider_enabled" if enabled else "provider_disabled", agent=agent)
        return value

    def allow_once(self, agent, work_id):
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

        for key in ("test", "workitem"):
            evidence = snapshot.get(key) or {}
            if not evidence.get("success") or evidence.get("mode") != "REAL":
                return False
            try:
                age = now() - datetime.fromisoformat(evidence["completed_at"])
                if not timedelta(0) <= age < timedelta(hours=1):
                    return False
            except (ValueError, TypeError, KeyError):
                return False
        return snapshot.get("auth_state") == "AUTHENTICATED" and not snapshot.get("error")

    def dashboard(self):
        identifiers = (
            ["provider-policy-" + a for a in AGENTS]
            + ["transport-status-" + t for t in SPECS]
            + ["day5a-relay"]
        )
        with self.ledger.store.connect() as conn:
            rows = conn.execute(
                "SELECT id,kind,work_item_id,payload FROM triad.day3_records WHERE id=ANY(%s)",
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
                    else preferred.get("health", "OFFLINE"),
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
                        "research": "Day 5 discovery gated",
                        "code_modification": "reviewed text proposals only",
                        "shell": "BLOCKED: outer isolation unavailable",
                        "git": "host reviewed changes only",
                        "web": False,
                        "external_tools": False,
                        "review_eligibility": agent != "LOCAL_QWEN",
                        "autonomous_improvement": "gate required",
                        "trading_research": "discovery gated",
                        "live_execution": False,
                    },
                }
            )
        relay = self.read("day5a-relay")
        passed = (
            all(
                a["state"] == "ONLINE"
                and a["policy"]["preferred_transport"] == PREFERRED[a["agent"]]
                and a["billing_source"]
                == ("LOCAL" if a["agent"] == "LOCAL_QWEN" else "SUBSCRIPTION")
                for a in agents
            )
            and relay.get("success") is True
        )
        return {
            "agents": agents,
            "gate": "PASS" if passed else "BLOCKED",
            "relay": relay or {"status": "NOT_RUN"},
            "discovery_enabled": passed,
            "control": control,
            "active_runs": [
                r for r in self.ledger.records("TransportRun", 100) if r.get("status") == "RUNNING"
            ],
            "secret_storage": "Windows Credential Manager",
            "timestamp": now().isoformat(),
        }

    def require_gate(self):
        if self.dashboard()["gate"] != "PASS":
            raise PermissionError(
                "DAY5A_GATE_BLOCKED: real frontier WorkItems and full relay required"
            )


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
        if preferred.transport_type == "CLI":
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
                    "SELECT id,payload FROM triad.day3_records WHERE kind='FallbackGrant' "
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
                            "FROM triad.day3_records WHERE kind='TransportDecision' "
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
