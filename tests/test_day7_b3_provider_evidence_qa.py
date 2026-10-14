"""Offline cross-provider blocked-response measurement parity."""

import pytest
from test_day3 import request
from test_resource_http import adapter
from trading_core.runtime import ProviderError

pytestmark = pytest.mark.core


@pytest.mark.parametrize("agent", ["CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"])
def test_all_http_response_shapes_retain_blocked_measurements(monkeypatch, agent):
    provider = adapter(agent)
    req = request().model_copy(
        update={"agent_id": agent, "role": "SUPPORT" if agent == "LOCAL_QWEN" else "PROPOSE"}
    )
    common = {"model": "actual-fixture"}
    usage = {
        "input_tokens": 42,
        "output_tokens": 20,
        "output_tokens_details": {"reasoning_tokens": 11},
    }
    responses = {
        "CODEX": {
            **common,
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": usage,
        },
        "CLAUDE": {**common, "stop_reason": "max_tokens", "usage": usage},
        "GROK": {
            **common,
            "choices": [{"finish_reason": "length"}],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 20,
                "completion_tokens_details": {"reasoning_tokens": 11},
            },
        },
        "LOCAL_QWEN": {
            **common,
            "done_reason": "length",
            "prompt_eval_count": 42,
            "eval_count": 20,
        },
    }
    generation_calls = []

    def response(path, *args):
        if path == "/api/show":
            return {"model_info": {"qwen3.context_length": 65536}}
        generation_calls.append(path)
        return responses[agent]

    monkeypatch.setattr(provider, "transport", response)
    with pytest.raises(ProviderError) as failed:
        provider.execute(req)
    assert failed.value.status == "BLOCKED_RESOURCE_LIMIT"
    assert provider.actual_model == "actual-fixture"
    assert provider.evidence == {"input_tokens": 42, "output_tokens": 20}
    assert provider.reasoning_tokens == (0 if agent == "LOCAL_QWEN" else 11)
    assert len(generation_calls) == 1
