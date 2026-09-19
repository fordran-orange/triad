"""Independent HTTP failure forwarding and invalid-measurement checks."""
# ruff: noqa: F811

from types import SimpleNamespace

import pytest
from test_day3 import request
from test_day3_integration import active, engine  # noqa: F401
from test_resource_http import adapter
from trading_core.contracts import AgentRunResult
from trading_core.providers.transports import HTTPTransport
from trading_core.resource_policy import ResourceBlocked
from trading_core.runtime import ProviderError


def completed(req, **usage):
    result = AgentRunResult(run_id=req.run_id, status="NO_CHANGE_JUSTIFIED", summary="Checked")
    return {
        "status": "completed",
        "model": "fixture-actual",
        "output": [{"content": [{"type": "output_text", "text": result.model_dump_json()}]}],
        "usage": {"input_tokens": 42, "output_tokens": 20, **usage},
    }


@pytest.mark.parametrize("invalid", [-1, True, "111"])
def test_completed_http_reasoning_measurement_is_validated(monkeypatch, invalid):
    provider = adapter("CODEX")
    req = request()
    monkeypatch.setattr(
        provider,
        "transport",
        lambda *a: completed(req, output_tokens_details={"reasoning_tokens": invalid}),
    )
    provider.execute(req)
    assert provider.reasoning_tokens is None


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_boolean_http_token_counts_cannot_be_accepted_as_real_usage(monkeypatch, field):
    provider = adapter("CODEX")
    req = request()
    monkeypatch.setattr(provider, "transport", lambda *a: completed(req, **{field: True}))
    with pytest.raises(ProviderError) as failed:
        provider.execute(req)
    assert failed.value.error_class in {"MissingUsageEvidence", "InvalidUsageMetadata"}


@pytest.mark.integration
@pytest.mark.parametrize("input_value,known", [(42, True), (True, False), (None, False)])
def test_http_wrapper_preserves_failed_evidence_and_unknowns(
    engine, monkeypatch, input_value, known
):
    work, policy = active(engine)
    req = engine.request(work, policy, "IMPLEMENT", {})
    provider = adapter("CODEX")
    calls = []

    def response(*args):
        calls.append(args)
        return {
            "status": "incomplete",
            "model": "fixture-actual",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {
                "input_tokens": input_value,
                "output_tokens": req.token_budget,
                "output_tokens_details": {"reasoning_tokens": 111 if known else -1},
            },
        }

    monkeypatch.setattr(provider, "transport", response)
    monkeypatch.setattr(provider, "estimate_cost", lambda *a: 0)
    control = SimpleNamespace(policy=lambda _: SimpleNamespace(models={"openai_api": "fixture"}))
    wrapper = HTTPTransport("openai_api", control)
    monkeypatch.setattr(wrapper, "adapter", lambda: provider)
    with pytest.raises(ResourceBlocked):
        engine.runtime.execute(req, mode="SIMULATED", adapter=wrapper, day=engine.day)
    usage = engine.ledger.records("Usage")[0]
    assert usage["status"] == "BLOCKED_RESOURCE_LIMIT"
    assert usage["usage_known"] is known
    assert usage["input_tokens"] == (42 if known else 0)
    assert usage["output_tokens"] == (req.token_budget if known else 0)
    assert usage["reasoning_tokens"] == (111 if known else None)
    assert usage["actual_model"] == "fixture-actual"
    assert len(calls) == 1
    assert not engine.ledger.records("AgentRunResult")
    assert wrapper.active_adapter is None
