"""Independent B3 allocation/HTTP boundary checks; providers are simulated."""
# ruff: noqa: F811

import threading
import time

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_day3 import request
from test_day3_integration import active, engine  # noqa: F401
from test_resource_http import adapter
from test_resource_policy import session
from trading_core.contracts import AgentRunResult
from trading_core.intelligence.records import Records
from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.resources import resource
from trading_core.runtime import ProviderError, SimulatedProvider

pytestmark = pytest.mark.core


@pytest.mark.integration
def test_versioned_migration_keeps_custom_controls_and_is_immutable(engine):
    store = engine.host.store
    with store.connect() as conn:
        control = engine.ledger.control(conn)
        control["limits"].update(timeout_seconds=31, max_output_tokens=777, max_cost_run=0.07)
        conn.execute("UPDATE core.autonomy_control SET payload=%s WHERE id=1", (Jsonb(control),))
        conn.execute("DELETE FROM core.schema_migrations WHERE version='013_resource_allocations'")
        sql = resource("infrastructure/postgres/013_resource_allocations.sql").read_text()
        conn.execute(sql)
        migrated = engine.ledger.control(conn)
        assert migrated["limits"] == control["limits"]
        assert migrated["epoch"] == control["epoch"] + 1
        conn.execute(sql)
        assert engine.ledger.control(conn) == migrated
    for mutation in (
        "UPDATE core.resource_policies SET payload='{}'",
        "DELETE FROM core.resource_policies",
    ):
        with (
            pytest.raises(psycopg.errors.RaiseException, match="append-only"),
            store.connect() as conn,
        ):
            conn.execute(mutation)
    assert (
        resource("infrastructure/postgres/013_resource_allocations.sql").read_bytes()
        == resource("app/trading_core/resources/sql/013_resource_allocations.sql").read_bytes()
    )


@pytest.mark.integration
@pytest.mark.parametrize("context_size,allowed", [(26000, True), (55000, False)])
def test_large_context_requires_decision_before_provider_call(engine, context_size, allowed):
    class Observed(SimulatedProvider):
        calls = 0

        def execute(self, req):
            self.calls += 1
            return (
                AgentRunResult(run_id=req.run_id, status="NO_CHANGE_JUSTIFIED", summary="Checked"),
                1,
                1,
            )

    work, policy = active(engine)
    req = engine.request(work, policy, "IMPLEMENT", {"evidence": "x" * context_size})
    provider = Observed("CODEX")
    if allowed:
        engine.runtime.execute(req, mode="SIMULATED", adapter=provider, day=engine.day)
    else:
        with pytest.raises(ResourceBlocked):
            engine.runtime.execute(req, mode="SIMULATED", adapter=provider, day=engine.day)
    decisions = [
        r
        for r in Records(engine.host.store).list("ResourceExtensionDecision")
        if r["run_id"] == req.run_id
    ]
    assert decisions[0]["resource_type"] == ResourceType.INPUT
    assert decisions[0]["decision"] == ("ALLOW" if allowed else "REQUIRE_HUMAN_APPROVAL")
    assert provider.calls == int(allowed)
    assert engine.host.store.get(work.work_item_id) == work


@pytest.mark.integration
def test_reported_reasoning_can_extend_without_expanding_output(engine):
    class Reasoning(SimulatedProvider):
        def execute(self, req):
            self.resources.observe("test_result", "independently completed fixture check")
            self.reasoning_tokens = req.reasoning_budget + 1
            return (
                AgentRunResult(run_id=req.run_id, status="NO_CHANGE_JUSTIFIED", summary="Checked"),
                1,
                1,
            )

    work, policy = active(engine)
    req = engine.request(work, policy, "IMPLEMENT", {})
    provider = Reasoning("CODEX")
    engine.runtime.execute(req, mode="SIMULATED", adapter=provider, day=engine.day)
    assert provider.resources.allocation(ResourceType.REASONING) == req.reasoning_budget * 2
    assert provider.resources.allocation(ResourceType.OUTPUT) == req.token_budget
    assert engine.ledger.records("Usage")[0]["reasoning_tokens"] == req.reasoning_budget + 1


@pytest.mark.integration
def test_truncated_http_result_records_review_request_without_retry(engine, monkeypatch):
    run = session(engine, billing="API")
    run.observe("accepted_context", "bounded context")
    provider = adapter("CODEX")
    provider.resources = run
    calls = []

    def response(path, body, timeout):
        calls.append(path)
        return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}

    monkeypatch.setattr(provider, "transport", response)
    with pytest.raises(ResourceBlocked) as failure:
        provider.execute(run.request)
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"
    assert failure.value.decision["granted_amount"] == 0
    assert len(calls) == 1
    assert run.host.list("ResourceExtensionRequest")[-1]["resource_type"] == ResourceType.OUTPUT


def test_http_cancel_is_prompt_and_rejects_late_read(monkeypatch):
    provider = adapter("CODEX")
    entered, release = threading.Event(), threading.Event()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self, _):
            entered.set()
            assert release.wait(3)
            return b"{}"

        def close(self):
            release.wait(3)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: Response())
    errors = []

    def call():
        try:
            provider.transport("/responses", {}, 3)
        except ProviderError as exc:
            errors.append(exc)

    worker = threading.Thread(target=call)
    worker.start()
    assert entered.wait(2)
    try:
        start = time.monotonic()
        provider.cancel()
        assert time.monotonic() - start < 0.5
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert errors and errors[0].error_class == "RunCancelled"


def test_ollama_sizes_context_instead_of_truncating_at_4096(monkeypatch):
    provider = adapter("LOCAL_QWEN")
    req = request().model_copy(
        update={
            "agent_id": "LOCAL_QWEN",
            "role": "SUPPORT",
            "context_packet": {"evidence": "x" * 6000},
        }
    )
    calls = []
    result = AgentRunResult(run_id=req.run_id, status="RESEARCH_FINDING", summary="Checked")

    def response(path, body, timeout=10):
        calls.append((path, body))
        if path == "/api/show":
            return {"model_info": {"qwen3.context_length": 65536}}
        return {
            "done_reason": "stop",
            "response": '{"summary":"Checked","assumptions":[]}',
            "prompt_eval_count": 100,
            "eval_count": 20,
            "model": "fixture",
        }

    monkeypatch.setattr(provider, "transport", response)
    actual, _, _ = provider.execute(req)
    assert actual == result
    assert calls[-1][1]["options"]["num_ctx"] > 4096
    assert calls[-1][1]["options"]["num_predict"] == req.token_budget
    assert provider.reasoning_tokens == 0


@pytest.mark.integration
def test_http_output_exhaustion_retains_measured_usage_and_model(engine, monkeypatch):
    work, policy = active(engine)
    req = engine.request(work, policy, "IMPLEMENT", {})
    provider = adapter("CODEX")
    # Offline response fixture: no network or billable provider operation occurs.
    monkeypatch.setattr(provider, "estimate_cost", lambda inputs, outputs: 0)
    monkeypatch.setattr(
        provider,
        "transport",
        lambda *a, **kw: {
            "status": "incomplete",
            "model": "observed-fixture-model",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {
                "input_tokens": 42,
                "output_tokens": req.token_budget,
                "output_tokens_details": {"reasoning_tokens": 111},
            },
        },
    )
    with pytest.raises(ResourceBlocked):
        engine.runtime.execute(req, mode="SIMULATED", adapter=provider, day=engine.day)
    usage = engine.ledger.records("Usage")[0]
    assert usage["usage_known"] is True, {
        key: usage.get(key)
        for key in (
            "usage_known",
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "actual_model",
            "status",
        )
    }
    assert usage["input_tokens"] == 42 and usage["output_tokens"] == req.token_budget
    assert usage["reasoning_tokens"] == 111
    assert usage["actual_model"] == "observed-fixture-model"
