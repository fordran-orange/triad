"""Real transactional storage; provider responses here are explicit test fixtures."""
# ruff: noqa: F811 - pytest fixture injection shadows the imported fixture name

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_day3_integration import engine  # noqa: F401 - shared disposable database fixture
from triad.day3.adapters import ProviderError
from triad.day3.contracts import ProviderHealth
from triad.day5a.contracts import ProviderPolicy
from triad.day5a.control import ProviderControl, TransportRouter
from triad.day5a.transports import HTTPTransport

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.mark.parametrize(
    "tokens,seconds,exceeded",
    [(100, 600, ["tokens"]), (1000, 60, ["seconds"]), (100, 60, ["tokens", "seconds"])],
)
def test_qwen_alert_uses_actual_daily_usage_without_blocking(engine, tokens, seconds, exceeded):
    from datetime import timedelta

    from triad.work import now

    c = ProviderControl(engine.ledger)
    c.configure_local_usage_alert(tokens, seconds)
    base = {
        "agent": "LOCAL_QWEN",
        "mode": "REAL",
        "timestamp": now().isoformat(),
        "input_tokens": 30,
        "output_tokens": 20,
        "duration": 30,
        "status": "FAILED",
    }
    for delta in (
        {"mode": "SIMULATED"},
        {"agent": "CODEX"},
        {"timestamp": (now() - timedelta(days=1)).isoformat()},
    ):
        engine.ledger.put("Usage", {**base, **delta})
    assert c.local_usage_alert(engine.ledger.control())["usage"]["tokens"] == 0
    engine.ledger.put("Usage", base)
    assert not c.local_usage_alert(engine.ledger.control())["active"]
    engine.ledger.put("Usage", base)
    alert = c.local_usage_alert(engine.ledger.control())
    assert alert["active"] and alert["exceeded"] == exceeded
    assert alert["blocking"] is False
    assert alert["usage"]["tokens"] == 100
    # An active warning does not become a policy cap or alter operator controls.
    engine.ledger.reserve(
        "LOCAL_QWEN",
        "alert-fixture",
        tokens=900000,
        seconds=9000,
        billing_source="LOCAL",
        day=engine.day,
    )
    engine.ledger.guard("LOCAL_QWEN")
    assert c.local_usage_alert(engine.ledger.control())["usage"]["tokens"] == 100


def test_qwen_alert_threshold_endpoint_is_operator_only(engine):
    from fastapi.testclient import TestClient
    from platform_host.legacy import app
    from triad.day5a.api import service

    app.dependency_overrides[service] = lambda: ProviderControl(engine.ledger)
    try:
        client = TestClient(app)
        body = {"tokens": 100000, "seconds": 3600}
        assert client.put("/api/providers/local-usage-alert", json=body).status_code == 401
        headers = {
            "Authorization": "Bearer "
            + engine.host.store.settings.triad_operator_token.get_secret_value()
        }
        assert (
            client.put("/api/providers/local-usage-alert", json=body, headers=headers).status_code
            == 200
        )
        assert (
            client.put(
                "/api/providers/local-usage-alert",
                json={"tokens": 0, "seconds": 1},
                headers=headers,
            ).status_code
            == 422
        )
        assert engine.ledger.control()["local_usage_alert"] == body
    finally:
        app.dependency_overrides.clear()


def test_non_api_caps_optional_and_api_accounting_separate(engine):
    ledger = engine.ledger
    ledger.suspend_daily_execution_limits_today()
    control = ledger.configure_non_api_daily_caps()
    assert "daily_execution_limit_suspension" not in control
    for source in ("SUBSCRIPTION", "LOCAL"):
        ledger.reserve(
            "CODEX", "fixture", tokens=900000, seconds=9000, billing_source=source, day=engine.day
        )
    # Non-API usage does not consume this API bucket; spending remains zero.
    ledger.reserve("CODEX", "fixture", tokens=100, seconds=1, billing_source="API", day=engine.day)
    with pytest.raises(PermissionError, match="BUDGET"):
        ledger.reserve("CODEX", "fixture", cost=0.01, billing_source="API", day=engine.day)
    with pytest.raises(PermissionError, match="BUDGET"):
        ledger.reserve("CODEX", "fixture", tokens=160000, billing_source="API", day=engine.day)
    # Policy is durable and re-enabling caps includes previously recorded usage.
    ledger.configure_non_api_daily_caps(subscription=True, local=False)
    with pytest.raises(PermissionError, match="BUDGET"):
        ledger.reserve("CODEX", "fixture", tokens=1, billing_source="SUBSCRIPTION", day=engine.day)
    ledger.reserve("LOCAL_QWEN", "fixture", tokens=1, billing_source="LOCAL", day=engine.day)
    # A change-slot reservation must not consume or be blocked by token usage.
    ledger.reserve("CODEX", "fixture", improvement=True, day=engine.day)
    ledger.operate("kill")
    with pytest.raises(PermissionError, match="cancelled"):
        ledger.reserve("LOCAL_QWEN", "fixture", tokens=1, billing_source="LOCAL", day=engine.day)


def test_runtime_admission_is_one_run_per_agent(engine, monkeypatch):
    from types import SimpleNamespace

    from triad.store import ConcurrentUpdate

    calls = []
    monkeypatch.setattr(engine.runtime, "_execute", lambda *a, **k: calls.append("executed"))
    request = SimpleNamespace(agent_id="CODEX", work_item_id="admission-fixture", token_budget=512)
    with engine.host.store.lease("provider-execution-CODEX"):
        with pytest.raises(ConcurrentUpdate):
            engine.runtime.execute(request)
        engine.runtime.execute(
            SimpleNamespace(
                agent_id="LOCAL_QWEN", work_item_id="admission-fixture", token_budget=512
            )
        )
    assert calls == ["executed"]
    engine.runtime.execute(request)
    assert len(calls) == 2


def test_daily_caps_endpoint_requires_operator_and_cannot_disable_api_caps(engine):
    from fastapi.testclient import TestClient
    from platform_host.legacy import app
    from triad.day5a.api import service

    app.dependency_overrides[service] = lambda: ProviderControl(engine.ledger)
    try:
        client = TestClient(app)
        body = {"subscription": False, "local": False}
        assert client.put("/api/providers/daily-execution-caps", json=body).status_code == 401
        headers = {
            "Authorization": "Bearer "
            + engine.host.store.settings.triad_operator_token.get_secret_value()
        }
        response = client.put("/api/providers/daily-execution-caps", json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()["daily_execution_caps"] == {"SUBSCRIPTION": False, "LOCAL": False}
        assert (
            client.put(
                "/api/providers/daily-execution-caps", json={**body, "api": False}, headers=headers
            ).status_code
            == 422
        )
        assert engine.ledger.control()["limits"]["max_cloud_cost_day"] == 0
    finally:
        app.dependency_overrides.clear()


def test_daily_suspension_keeps_accounting_paid_budget_and_kill_switch(engine):
    from datetime import timedelta

    from triad.work import now

    ledger = engine.ledger
    grant = ledger.suspend_daily_execution_limits_today()
    assert grant["operator_authorized"]
    ledger.reserve("CODEX", "suspension-test", tokens=900000, seconds=9000, day=engine.day)
    row = next(t for t in ledger.totals() if str(t["day"]) == engine.day)
    assert row["reserved_tokens"] == 900000 and row["reserved_seconds"] == 9000
    with pytest.raises(PermissionError, match="BUDGET"):
        ledger.reserve("CODEX", "suspension-test", cost=1, day=engine.day)
    ledger.operate("kill")
    with pytest.raises(PermissionError, match="cancelled"):
        ledger.reserve("CODEX", "suspension-test", day=engine.day)
    ledger.operate("resume")
    with ledger.store.connect() as conn:
        control = ledger.control(conn, True)
        control["daily_execution_limit_suspension"]["expires_at"] = (
            now() - timedelta(seconds=1)
        ).isoformat()
        conn.execute("UPDATE triad.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),))
    with pytest.raises(PermissionError, match="BUDGET"):
        ledger.reserve("CODEX", "suspension-test", tokens=1, day=engine.day)


@pytest.mark.parametrize("invalid_result", [False, True])
def test_native_usage_reservation_and_failed_result_metering(engine, invalid_result):
    from triad.day3.adapters import SimulatedProvider
    from triad.day3.contracts import AgentRunResult

    class NativeFixture(SimulatedProvider):
        transport_type = "CLI"

        def execute(self, request):
            return (
                AgentRunResult(
                    run_id="wrong-id" if invalid_result else request.run_id,
                    status="NO_CHANGE_JUSTIFIED",
                    summary="SIMULATED native usage fixture",
                ),
                38000,
                200,
            )

    work, policy = engine.start_work(engine.make_work("CODEX", str(uuid4())))
    request = engine.request(work, policy, "REVIEW", {}, agent=work.reviewer)
    fixture = NativeFixture(work.reviewer)
    if invalid_result:
        with pytest.raises(ProviderError, match="InvalidRuntimeResult"):
            engine.runtime.execute(request, mode="SIMULATED", day=engine.day, adapter=fixture)
    else:
        engine.runtime.execute(request, mode="SIMULATED", day=engine.day, adapter=fixture)
    usage = next(u for u in engine.ledger.records("Usage") if u["run_id"] == request.run_id)
    assert usage["input_tokens"] == 38000
    assert usage["usage_known"] is True
    assert usage["mode"] == "SIMULATED"
    reservation = next(r for r in engine.ledger.records("BudgetReservation") if r["tokens"])
    assert reservation["tokens"] >= 48000


@pytest.mark.parametrize(
    "agent,transport", [("CLAUDE", "claude_code_cli"), ("GROK", "grok_build_cli")]
)
def test_isolated_cli_routing_never_uses_paid_api(engine, monkeypatch, agent, transport):
    from triad.day5a.transports import CLITransport

    monkeypatch.setattr(CLITransport, "readonly_ready", lambda self: True)
    monkeypatch.setattr(
        CLITransport,
        "authentication_status",
        lambda self: {"auth_state": "AUTHENTICATED", "billing_source": "SUBSCRIPTION"},
    )
    work, policy = engine.start_work(engine.make_work(agent, str(uuid4())))
    request = engine.request(work, policy, "IMPLEMENT", {}, agent=agent)
    selected = TransportRouter(ProviderControl(engine.ledger)).select(request, 2000)
    assert selected.transport_id == transport
    assert selected.transport_type == "CLI"


def test_native_adapter_rejection_keeps_measured_usage(engine):
    from types import SimpleNamespace

    from triad.day3.adapters import SimulatedProvider

    class NativeFixture(SimulatedProvider):
        transport_type = "CLI"

        def execute(self, request):
            self.native_run = SimpleNamespace(evidence={"input_tokens": 1234, "output_tokens": 80})
            raise ProviderError("DEGRADED", "NativeReadEvidenceMissing")

    work, policy = engine.start_work(engine.make_work("CODEX", str(uuid4())))
    request = engine.request(work, policy, "REVIEW", {}, agent=work.reviewer)
    with pytest.raises(ProviderError, match="NativeReadEvidenceMissing"):
        engine.runtime.execute(
            request, mode="SIMULATED", day=engine.day, adapter=NativeFixture(work.reviewer)
        )
    usage = next(u for u in engine.ledger.records("Usage") if u["run_id"] == request.run_id)
    assert usage["usage_known"] is True
    assert (usage["input_tokens"], usage["output_tokens"]) == (1234, 80)


class MemorySecrets:
    def __init__(self):
        self.values = {}

    def set_secret(self, name, value):
        self.values[name] = value

    def has_secret(self, name):
        return name in self.values

    def get_secret(self, name):
        return self.values.get(name)

    def delete_secret(self, name):
        self.values.pop(name, None)


def setup(engine, monkeypatch, fallback="NEVER", budget=1):
    host = ProviderControl(engine.ledger, MemorySecrets())
    host.save_policy(
        ProviderPolicy(
            agent="CODEX",
            preferred_transport="codex_cli",
            fallback=fallback,
            models={"openai_api": "test-fixture"},
            api_daily_budget=budget,
            input_price_per_million=10,
            output_price_per_million=10,
        )
    )
    monkeypatch.setattr(
        HTTPTransport,
        "health_check",
        lambda self: ProviderHealth(
            agent=self.agent, provider=self.provider, model=self.model, status="AVAILABLE"
        ),
    )
    with engine.host.store.connect() as conn:
        value = engine.ledger.control(conn, lock=True)
        value["limits"]["max_cloud_cost_day"] = budget
        conn.execute("UPDATE triad.autonomy_control SET payload=%s WHERE id=1", (Jsonb(value),))
    work, policy = engine.start_work(engine.make_work("CODEX", str(uuid4())))
    request = engine.request(work, policy, "PROPOSE", {"source": "explicit test fixture"})
    return host, request


def test_no_silent_api_fallback_and_one_time_grant(engine, monkeypatch):
    host, request = setup(engine, monkeypatch)
    host.secrets.set_secret("openai_api", "fixture-never-networked")
    router = TransportRouter(host)
    with pytest.raises(ProviderError, match="APIFallbackDisabled"):
        router.select(request, 100)
    grant = host.allow_once("CODEX", request.work_item_id)
    assert router.select(request, 100).transport_id == "openai_api"
    assert engine.ledger.get(grant["grant_id"])["used"]
    with pytest.raises(ProviderError, match="APIFallbackDisabled"):
        router.select(request, 100)
    assert engine.ledger.records("TransportDecision")[0]["billing_source"] == "API"
    assert any(
        r.get("event") == "transport_fallback_denied" for r in engine.ledger.records("Event")
    )


def test_ask_each_time_missing_key_and_budget(engine, monkeypatch):
    host, request = setup(engine, monkeypatch, "ASK_EACH_TIME", budget=0)
    router = TransportRouter(host)
    with pytest.raises(ProviderError, match="FallbackApprovalRequired"):
        router.select(request, 100)
    host.allow_once("CODEX", request.work_item_id)
    with pytest.raises(ProviderError, match="APINotConfigured"):
        router.select(request, 100)
    host.secrets.set_secret("openai_api", "fixture-never-networked")
    with pytest.raises(ProviderError, match="APIBudgetExhausted"):
        router.select(request, 100)
    assert not engine.ledger.records("TransportDecision")


def test_budget_fallback_is_atomic_and_kill_enable_override_routes(engine, monkeypatch):
    host, request = setup(engine, monkeypatch, "ALLOW_WITHIN_BUDGET", budget=0.09)
    # The fixture's $10/M rates and Day 7 output reservation admit exactly one run.
    estimate = (100 + request.token_budget) * 10 / 1_000_000
    assert estimate <= 0.09 < 2 * estimate
    host.secrets.set_secret("openai_api", "fixture-never-networked")
    router = TransportRouter(host)

    def route():
        try:
            return router.select(
                request.model_copy(update={"run_id": str(uuid4())}), 100
            ).transport_id
        except ProviderError as exc:
            return exc.error_class

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: route(), range(2)))
    assert sorted(results) == ["APIBudgetExhausted", "openai_api"]
    host.enable("CODEX", False)
    with pytest.raises(PermissionError):
        router.select(request, 100)
    host.enable("CODEX", True)
    engine.ledger.operate("kill")
    with pytest.raises(PermissionError):
        router.select(request, 100)


def test_production_gate_cannot_pass_on_installation_or_fake_proofs(engine):
    host = ProviderControl(engine.ledger, MemorySecrets())
    assert host.dashboard()["gate"] == "BLOCKED"
    with pytest.raises(PermissionError, match="PROVIDER_GATE_BLOCKED"):
        host.require_gate()
    with pytest.raises(PermissionError, match="PROVIDER_GATE_BLOCKED"):
        engine.run(mode="REAL")
