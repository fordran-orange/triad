"""Transport resource behavior uses fake responses; no paid calls."""

import json

import pytest
from test_day3 import request
from trading_core.resources import resource
from trading_core.runtime import HttpProvider, ProviderError

pytestmark = pytest.mark.core


def adapter(agent):
    config = json.loads(resource("config/core/runtime.json").read_text(encoding="utf-8"))[
        "providers"
    ][agent]
    values = {config["model_env"]: "fixture"}
    if config.get("key_env"):
        values[config["key_env"]] = "fixture"
    return HttpProvider(agent, config, values)


def test_output_cap_is_independent_and_exhaustion_is_explicit(monkeypatch):
    provider = adapter("CODEX")
    sent = []

    def response(path, body, timeout):
        sent.append(body)
        return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}

    monkeypatch.setattr(provider, "transport", response)
    req = request().model_copy(update={"reasoning_budget": 8, "token_budget": 100})
    with pytest.raises(ProviderError) as failed:
        provider.execute(req)
    assert failed.value.status == "BLOCKED_RESOURCE_LIMIT"
    assert sent[0]["max_output_tokens"] == 100
    assert len(sent) == 1  # Never silently retry a billable invocation.


def test_ollama_checks_actual_context_capacity_before_generation(monkeypatch):
    provider = adapter("LOCAL_QWEN")
    calls = []

    def response(path, body, timeout=10):
        calls.append(path)
        return {"model_info": {"qwen3.context_length": 128}}

    monkeypatch.setattr(provider, "transport", response)
    req = request().model_copy(update={"agent_id": "LOCAL_QWEN", "role": "SUPPORT"})
    with pytest.raises(ProviderError, match="ModelContextCapacityUnavailable"):
        provider.execute(req)
    assert calls == ["/api/show"]
