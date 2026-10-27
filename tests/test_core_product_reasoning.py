"""Mission 14: a product reading runs Core's governed provider path with the product as owner
(spec §4.1). The integration tests use a disposable database (the day-3 engine) and fake the
provider run as the chat's tests do."""

import json
import time
from types import SimpleNamespace as NS

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core import product_reasoning as module
from trading_core.contracts import AgentRunResult
from trading_core.intelligence.records import Records
from trading_core.product_reasoning import ReasoningFailed, ReasoningRequest, check_shape
from trading_core.runtime import Runtime

pytestmark = pytest.mark.core

SCHEMA = {
    "type": "object",
    "required": ["rewrite", "substitutions", "unsupported"],
    "properties": {
        "rewrite": {"type": "string"},
        "substitutions": {"type": "array"},
        "unsupported": {"type": "string"},
    },
}
REQUEST = ReasoningRequest(
    provider="CLAUDE",
    instructions="Rewrite the sentence into the reader's language.",
    input="buy when 9 ema crosses up 30 sma",
    output_schema=SCHEMA,
)
ANSWER = {
    "rewrite": "buy when 9 ema crosses above 30 sma",
    "substitutions": [{"from": "crosses up", "to": "crosses above"}],
    "unsupported": "",
}


def reasoning(engine, monkeypatch, outcome, calls, routed=None):  # noqa: F811
    """ProductReasoning over the disposable database; `outcome` is the run's summary, an
    AgentRunResult, an exception, or a callable taking the request."""
    records = Records(engine.host.store)
    records.initialize()

    def create(work, requirements):
        (routed if routed is not None else []).append(requirements)
        return engine.host.create(work.model_copy(update={"assigned_agent": "CLAUDE"}))

    monkeypatch.setattr(module, "Routing", lambda _: NS(create=create))

    def execute(self, request):
        calls.append(request)
        self.ledger.put(
            "AgentRunRequest",
            request.model_dump(mode="json"),
            identifier=request.run_id,
            work_id=request.work_item_id,
        )
        self.ledger.put(
            "Usage",
            {
                "run_id": request.run_id,
                "provider": "test-provider",
                "actual_model": "test-model",
                "transport": "test-cli",
                "billing_source": "SUBSCRIPTION",
                "input_tokens": 11,
                "output_tokens": 7,
            },
            work_id=request.work_item_id,
        )
        value = outcome(request) if callable(outcome) else outcome
        if isinstance(value, Exception):
            raise value
        if isinstance(value, AgentRunResult):
            return value
        return AgentRunResult(run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary=value)

    monkeypatch.setattr(Runtime, "execute", execute)
    return module.ProductReasoning(records)


@pytest.mark.integration
def test_a_reading_returns_the_json_and_its_provenance(engine, monkeypatch):  # noqa: F811
    calls, routed = [], []
    service = reasoning(engine, monkeypatch, json.dumps(ANSWER), calls, routed)
    answer = service.reason("aegis", REQUEST)
    assert answer["output"] == ANSWER
    provenance = answer["provenance"]
    assert provenance["provider"] == "test-provider" and provenance["model"] == "test-model"
    assert provenance["transport"] == "test-cli" and provenance["billing_source"] == "SUBSCRIPTION"
    assert (provenance["input_tokens"], provenance["output_tokens"]) == (11, 7)
    assert provenance["run_id"] == calls[0].run_id
    work = engine.host.store.get(provenance["work_item_id"])
    assert work.status == "COMPLETED" and work.owner == "aegis"
    (requirements,) = routed
    assert requirements.preferred_agent == "CLAUDE"
    assert requirements.billing_sources == ("SUBSCRIPTION",)


@pytest.mark.integration
def test_the_request_asks_for_no_tools(engine, monkeypatch):  # noqa: F811
    calls = []
    reasoning(engine, monkeypatch, json.dumps(ANSWER), calls).reason("aegis", REQUEST)
    (request,) = calls
    assert request.agent_id == "CLAUDE" and request.role == "REVIEW"
    assert request.allowed_tools == () and request.allowed_paths == ()
    assert request.execution_permissions == ("read",)
    assert request.context_packet["input"] == REQUEST.input
    assert request.context_packet["output_schema"] == SCHEMA


@pytest.mark.integration
@pytest.mark.parametrize(
    "outcome",
    [
        RuntimeError("provider down"),
        "BLOCKED",
        {"actions_taken": ("wrote a file",)},
        {"commands_executed": ("dir",)},
        {"tests_run": ("pytest",)},
    ],
)
def test_a_failed_or_acting_run_is_provider_failed(engine, monkeypatch, outcome):  # noqa: F811
    """Review Focus 2: nothing comes back from a run that failed, was blocked or acted."""
    calls, routed = [], []

    def result(request):
        if outcome == "BLOCKED":
            return AgentRunResult(
                run_id=request.run_id, status="BLOCKED", summary=json.dumps(ANSWER)
            )
        if isinstance(outcome, dict):
            return AgentRunResult(
                run_id=request.run_id,
                status="NO_CHANGE_JUSTIFIED",
                summary=json.dumps(ANSWER),
                **outcome,
            )
        return outcome

    service = reasoning(engine, monkeypatch, result, calls, routed)
    with pytest.raises(ReasoningFailed) as caught:
        service.reason("aegis", REQUEST)
    assert (caught.value.reason, caught.value.status) == ("provider_failed", 502)
    assert len(routed) == 1 and len(calls) == 1  # no other provider asked
    assert engine.host.store.get(calls[0].work_item_id).status == "FAILED"


@pytest.mark.integration
@pytest.mark.parametrize(
    "summary",
    [
        "not json at all",
        json.dumps({"substitutions": [], "unsupported": ""}),
        json.dumps({"rewrite": "x", "substitutions": "none", "unsupported": ""}),
    ],
)
def test_a_malformed_answer_is_refused(engine, monkeypatch, summary):  # noqa: F811
    calls = []
    service = reasoning(engine, monkeypatch, summary, calls)
    with pytest.raises(ReasoningFailed) as caught:
        service.reason("aegis", REQUEST)
    assert (caught.value.reason, caught.value.status) == ("malformed_answer", 502)
    assert engine.host.store.get(calls[0].work_item_id).status == "FAILED"


@pytest.mark.integration
def test_one_reading_at_a_time(engine, monkeypatch):  # noqa: F811
    calls = []
    service = reasoning(engine, monkeypatch, json.dumps(ANSWER), calls)
    with (
        engine.host.store.lease("core-product-reasoning-aegis"),
        pytest.raises(ReasoningFailed) as caught,
    ):
        service.reason("aegis", REQUEST)
    assert (caught.value.reason, caught.value.status) == ("busy", 409)
    assert calls == []


@pytest.mark.integration
def test_a_reading_past_the_limit_is_timed_out(engine, monkeypatch):  # noqa: F811
    calls = []

    def slow(request):
        time.sleep(1.0)
        return json.dumps(ANSWER)

    service = reasoning(engine, monkeypatch, slow, calls)
    monkeypatch.setattr(module, "LIMIT_SECONDS", 0.2)
    with pytest.raises(ReasoningFailed) as caught:
        service.reason("aegis", REQUEST)
    assert (caught.value.reason, caught.value.status) == ("timed_out", 504)
    deadline = time.monotonic() + 10  # Core finishes and records the run when it ends
    while not calls or engine.host.store.get(calls[0].work_item_id).status != "COMPLETED":
        assert time.monotonic() < deadline, "the timed-out run was never recorded"
        time.sleep(0.2)


def test_check_shape():
    assert check_shape(ANSWER, SCHEMA)
    assert not check_shape({"substitutions": [], "unsupported": ""}, SCHEMA)
    assert not check_shape({**ANSWER, "rewrite": 3}, SCHEMA)
    assert not check_shape({**ANSWER, "substitutions": {}}, SCHEMA)
    assert not check_shape(["not", "an", "object"], SCHEMA)
    assert check_shape(
        {"n": 1.5, "flag": True},
        {"type": "object", "properties": {"n": {"type": "number"}, "flag": {"type": "boolean"}}},
    )


@pytest.mark.integration
def test_providers_say_what_routing_would_assign_a_reading_now(engine, monkeypatch):  # noqa: F811
    from test_intelligence_routing import setup_routing

    router, _ = setup_routing(engine)
    proven = router.control.snapshot
    router.control.snapshot = lambda transport: {
        **proven(transport),
        "workitem": {"actual_model": "fixture-model", "success": transport != "grok_build_cli"},
    }
    seen, evaluate = [], router.evaluate

    def spy(work, requirements):
        seen.append((work, requirements))
        return evaluate(work, requirements)

    router.evaluate = spy
    monkeypatch.setattr(module, "Routing", lambda _: router)

    def rows():
        with engine.host.store.connect() as c:
            return [
                c.execute(f"SELECT count(*) AS n FROM core.{table}").fetchone()["n"]
                for table in ("day3_records", "intelligence_records")
            ]

    before = rows()
    found = module.ProductReasoning(Records(engine.host.store)).providers("aegis")
    assert rows() == before  # no routing decision, work item or event of any id
    assert found == [
        {"provider": "CLAUDE", "available": True},
        {"provider": "CODEX", "available": True},
        {"provider": "GROK", "available": False},
    ]
    ((work, need),) = seen  # a reading's own work item and requirements, nothing recorded
    assert work.owner == "aegis" and work.work_type == "review"
    assert work.allowed_tools == () and work.execution_permissions == ("read",)
    assert need.role == "REVIEW" and need.capabilities == ("structured_output",)
    assert need.billing_sources == ("SUBSCRIPTION",)
    with pytest.raises(KeyError):
        engine.host.store.get(work.work_item_id)
