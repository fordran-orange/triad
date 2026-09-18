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

pytestmark = pytest.mark.integration


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
    host, request = setup(engine, monkeypatch, "ALLOW_WITHIN_BUDGET", budget=0.03)
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
    with pytest.raises(PermissionError, match="DAY5A_GATE_BLOCKED"):
        host.require_gate()
    with pytest.raises(PermissionError, match="DAY5A_GATE_BLOCKED"):
        engine.run(mode="REAL")
