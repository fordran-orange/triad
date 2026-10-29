"""Mission 14: the read-only Core route for product readings, its per-product key and its refusals
(spec §4.1). No database: Core's engine and the reasoner are faked."""

import importlib
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from trading_core.api import app, service

# Core's app mounts the route module, so it is loaded after the app (as the chat's router is).
module = importlib.import_module("trading_core.product_reasoning_api")

pytestmark = pytest.mark.core

KEY = "k" * 48
OTHER = "t" * 48
OPERATOR = "o" * 48  # the operator routes compare against this, never the product key
PATH = "/api/core/products/aegis/reasoning"
BODY = {
    "provider": "CLAUDE",
    "instructions": "Rewrite the sentence into the reader's language.",
    "input": "buy when 9 ema crosses up 30 sma",
    "output_schema": {"type": "object", "required": ["rewrite"]},
}


class FakeReasoner:
    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome

    def providers(self, product):
        self.calls.append((product, "providers"))
        return [{"provider": "CLAUDE", "available": True}, {"provider": "GROK", "available": False}]

    def reason(self, product, request):
        self.calls.append((product, request))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return {
            "output": {"rewrite": "buy when 9 ema crosses above 30 sma"},
            "provenance": {"provider": "claude"},
        }


@pytest.fixture
def client():
    settings = NS(
        aegis_product_key=SecretStr(KEY),
        triad_product_key=SecretStr(OTHER),
        triad_operator_token=SecretStr(OPERATOR),
    )
    engine = NS(store=NS(settings=settings, scope=None))
    reasoner = FakeReasoner()
    app.dependency_overrides[service] = lambda: engine
    app.dependency_overrides[module.reasoner] = lambda: reasoner
    try:
        yield TestClient(app), settings, reasoner
    finally:
        app.dependency_overrides.clear()


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def test_a_missing_or_wrong_key_is_401(client):
    c, _, reasoner = client
    assert c.post(PATH, json=BODY).status_code == 401
    assert c.post(PATH, json=BODY, headers=bearer("x" * 48)).status_code == 401
    assert reasoner.calls == []


def test_another_products_key_is_403(client, monkeypatch):
    c, _, reasoner = client
    monkeypatch.setitem(module.PRODUCT_KEYS, "triad", "triad_product_key")
    assert c.post(PATH, json=BODY, headers=bearer(OTHER)).status_code == 403
    triad = "/api/core/products/triad/reasoning"
    assert c.post(triad, json=BODY, headers=bearer(KEY)).status_code == 403
    assert reasoner.calls == []


def test_an_unknown_product_is_404(client):
    c, _, _ = client
    assert (
        c.post("/api/core/products/nope/reasoning", json=BODY, headers=bearer(KEY)).status_code
        == 404
    )


def test_no_key_issued_is_503(client):
    c, settings, reasoner = client
    settings.aegis_product_key = SecretStr("short")
    answer = c.post(PATH, json=BODY, headers=bearer("short"))
    assert answer.status_code == 503 and answer.json()["detail"]["reason"] == "not_issued"
    assert reasoner.calls == []


def test_the_product_key_opens_no_operator_route(client):  # Review Focus 1
    c, _, _ = client
    for path in ("/api/core/conversations", "/api/core/intake"):
        assert c.get(path, headers=bearer(KEY)).status_code == 401, path


@pytest.mark.parametrize(
    "change",
    [
        {"instructions": "x" * 20_001},
        {"input": ""},
        {"input": "x" * 2_001},
        {"output_schema": {"description": "x" * 8_001}},
        {"provider": "OPENAI"},
    ],
)
def test_requests_out_of_bounds_are_422(client, change):
    c, _, reasoner = client
    assert c.post(PATH, json={**BODY, **change}, headers=bearer(KEY)).status_code == 422
    assert reasoner.calls == []


def test_a_good_request_returns_the_reasoners_answer(client):
    c, _, reasoner = client
    answer = c.post(PATH, json=BODY, headers=bearer(KEY))
    assert answer.status_code == 200, answer.text
    assert answer.json()["output"] == {"rewrite": "buy when 9 ema crosses above 30 sma"}
    ((product, request),) = reasoner.calls
    assert product == "aegis" and request.provider == "CLAUDE" and request.input == BODY["input"]


@pytest.mark.parametrize(
    ("reason", "status"),
    [("provider_failed", 502), ("malformed_answer", 502), ("busy", 409), ("timed_out", 504)],
)
def test_reasoning_failures_keep_their_status(client, reason, status):
    c, _, reasoner = client
    reasoner.outcome = module.ReasoningFailed(reason, status, "what happened")
    answer = c.post(PATH, json=BODY, headers=bearer(KEY))
    assert answer.status_code == status
    assert answer.json()["detail"] == {"reason": reason, "message": "what happened"}


def test_the_providers_need_the_product_key(client):
    c, _, reasoner = client
    assert c.get(PATH + "/providers").status_code == 401
    assert c.get(PATH + "/providers", headers=bearer("x" * 48)).status_code == 401
    assert reasoner.calls == []


def test_the_providers_are_what_core_would_route_now(client):
    c, _, reasoner = client
    answer = c.get(PATH + "/providers", headers=bearer(KEY))
    assert answer.status_code == 200, answer.text
    assert answer.json() == {
        "providers": [
            {"provider": "CLAUDE", "available": True},
            {"provider": "GROK", "available": False},
        ]
    }
    assert reasoner.calls == [("aegis", "providers")]


# -- the milestone review (2026-10-28) ------------------------------------------------------------
@pytest.mark.parametrize("value", [b"Bearer \xe9" + b"k" * 47, b"Bearer " + b"k" * 47 + b"\xff"])
def test_a_non_ascii_key_header_is_401(client, value):
    """A header byte outside ASCII is a wrong key, not an unhandled error: the compare runs on
    bytes. The same holds for the operator routes."""
    c, _, reasoner = client
    answer = c.post(PATH, json=BODY, headers={b"authorization": value})
    assert answer.status_code == 401 and reasoner.calls == []
    assert c.get("/api/core/conversations", headers={b"authorization": value}).status_code == 401


def test_the_product_key_is_redacted_like_other_secrets(monkeypatch):
    """Core redacts every .env credential it knows from prompts, results and logs; the product
    key joins the operator token and the API keys in that set."""
    import json

    from trading_core.security import redact

    monkeypatch.setenv("AEGIS_PRODUCT_KEY", "p" * 48)
    shown = json.dumps(redact({"value": "p" * 48, "header": "Bearer " + "p" * 48}))
    assert "p" * 48 not in shown
