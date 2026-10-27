"""Mission 14: the worker reads with the phrase reader first and asks Core only when it refuses
(spec §4.2). Core is faked; no test reaches the real gateway."""

import pytest
from products.aegis import api, server
from products.aegis.ai_reading import OUTPUT_SCHEMA, instructions, read_with_ai
from products.aegis.core_client import CoreReadingError
from products.aegis.strategy import default_strategy
from test_aegis_api import client  # noqa: F401

pytestmark = pytest.mark.aegis

UNREADABLE = "buy when 9 ema crosses up 30 sma"
REWRITE = "buy when 9 ema crosses above 30 sma"
PROVENANCE = {
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "transport": "claude_code_cli",
    "billing_source": "SUBSCRIPTION",
    "input_tokens": 900,
    "output_tokens": 60,
    "run_id": "run-1",
    "work_item_id": "work-1",
}


class FakeCore:
    def __init__(self, output=None, error=None):
        self.calls = []
        self.output = output or {
            "rewrite": REWRITE,
            "substitutions": [{"from": "crosses up", "to": "crosses above"}],
            "unsupported": "",
        }
        self.error = error
        self.available = {"CLAUDE", "CODEX"}

    def providers(self):
        if self.error:
            raise self.error
        return [
            {"provider": p, "available": p in self.available} for p in ("CLAUDE", "CODEX", "GROK")
        ]

    def reason(self, provider, instructions, input, output_schema):
        self.calls.append(
            {
                "provider": provider,
                "instructions": instructions,
                "input": input,
                "schema": output_schema,
            }
        )
        if self.error:
            raise self.error
        return {"output": self.output, "provenance": PROVENANCE}


@pytest.fixture
def core(client):  # noqa: F811
    fake = FakeCore()
    server.app.dependency_overrides[api.get_core_reasoning] = lambda: fake
    return client[0], fake


def body(text, **extra):
    return {"text": text, "strategy": default_strategy().model_dump(mode="json"), **extra}


def test_the_reader_reads_first_and_core_is_not_asked(core):
    c, fake = core
    answer = c.post("/aegis/api/strategies/read", json=body(REWRITE))
    assert answer.status_code == 200 and answer.json()["read_by"] == "phrases"
    assert fake.calls == []


def test_a_refusal_goes_to_the_chosen_provider(core):
    c, fake = core
    answer = c.post("/aegis/api/strategies/read", json=body(UNREADABLE, provider="CODEX"))
    assert answer.status_code == 200, answer.text
    reading = answer.json()
    assert reading["read_by"] == "ai" and reading["rewrite"] == REWRITE
    assert reading["substitutions"] == [{"from": "crosses up", "to": "crosses above"}]
    assert reading["provenance"]["model"] == "claude-sonnet-5"
    assert reading["sides"]["long_side"]["entry"]["operator"] == "crosses_above"
    (call,) = fake.calls
    assert call["provider"] == "CODEX" and call["input"] == UNREADABLE
    assert call["schema"] == OUTPUT_SCHEMA
    assert "Openers:" in call["instructions"] and "ema (EMA 9)" in call["instructions"]


def test_the_instructions_carry_the_examples():
    examples = [
        {
            "text": "go long if 20 ema goes over 50 sma",
            "rewrite": "buy when 20 ema crosses above 50 sma",
        }
    ]
    text = instructions(default_strategy(), examples)
    assert '"go long if 20 ema goes over 50 sma" -> "buy when 20 ema crosses above 50 sma"' in text
    assert "never use pronouns" in text.lower()


def test_an_unreadable_rewrite_is_refused_with_the_rewrite(core):
    c, fake = core
    fake.output = {"rewrite": "buy when vwap rises", "substitutions": [], "unsupported": ""}
    answer = c.post("/aegis/api/strategies/read", json=body(UNREADABLE))
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["unread"][0]["text"] == "up"  # the phrase reader's own refusal, as before
    assert (
        detail["ai"]["reason"] == "rewrite_unread"
        and detail["ai"]["rewrite"] == "buy when vwap rises"
    )
    assert detail["ai"]["provider"] == "CLAUDE" and "vwap" in detail["ai"]["message"]


def test_unsupported_is_passed_on(core):
    c, fake = core
    fake.output = {**fake.output, "unsupported": "stop out at 3% down"}
    reading = c.post("/aegis/api/strategies/read", json=body(UNREADABLE)).json()
    assert reading["unsupported"] == "stop out at 3% down" and reading["read_by"] == "ai"


@pytest.mark.parametrize(
    ("error", "reason", "words"),
    [
        (
            CoreReadingError(
                502, "provider_failed", "Requested agent is not eligible; no silent substitution"
            ),
            "provider_failed",
            "Claude could not read this: Requested agent is not eligible",
        ),
        (
            CoreReadingError(503, "not_issued", "no product key issued"),
            "not_set_up",
            "AI reading is not set up",
        ),
        (
            CoreReadingError(409, "busy", "a reading is still running"),
            "busy",
            "a reading is still finishing",
        ),  # Review Focus 4
        (
            CoreReadingError(504, "timed_out", "no answer within 120 s"),
            "timed_out",
            "Claude took too long",
        ),
        (
            CoreReadingError(502, "malformed_answer", "the answer is not JSON"),
            "malformed_answer",
            "Claude's answer could not be used",
        ),
    ],
)
def test_core_errors_pass_through_with_their_reason(core, error, reason, words):
    c, fake = core
    fake.error = error
    answer = c.post("/aegis/api/strategies/read", json=body(UNREADABLE))
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["ai"]["reason"] == reason and words in detail["ai"]["message"], detail
    assert detail["message"] == "didn't understand 'up'" and detail["unread"][0]["text"] == "up"


def test_the_provider_is_remembered(core):
    c, fake = core
    assert c.put("/aegis/api/preferences", json={"reader_provider": "CODEX"}).status_code == 200
    assert c.get("/aegis/api/preferences").json()["reader_provider"] == "CODEX"
    c.post("/aegis/api/strategies/read", json=body(UNREADABLE))
    assert fake.calls[0]["provider"] == "CODEX"
    assert c.put("/aegis/api/preferences", json={"reader_provider": "GROK"}).status_code == 200
    assert c.get("/aegis/api/preferences").json()["reader_provider"] == "GROK"
    assert c.put("/aegis/api/preferences", json={"reader_provider": "OPENAI"}).status_code == 422


def test_grok_reads_when_chosen(core):  # operator, 2026-10-27
    c, fake = core
    answer = c.post("/aegis/api/strategies/read", json=body(UNREADABLE, provider="GROK"))
    assert answer.status_code == 200, answer.text
    assert fake.calls[0]["provider"] == "GROK"


def test_the_providers_are_the_ones_core_can_route_now(core):
    c, _ = core
    answer = c.get("/aegis/api/phrases/providers")
    assert answer.status_code == 200
    assert answer.json() == {
        "providers": [
            {"id": "CLAUDE", "name": "Claude", "available": True},
            {"id": "CODEX", "name": "Codex", "available": True},
            {"id": "GROK", "name": "Grok", "available": False},
        ],
        "message": None,
    }


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (CoreReadingError(503, "not_issued", "no product key issued"), "AI reading is not set up"),
        (
            CoreReadingError(503, "core_unavailable", "Core is not answering"),
            "Core is not answering",
        ),
    ],
)
def test_without_core_no_provider_is_available(core, error, words):
    c, fake = core
    fake.error = error
    answer = c.get("/aegis/api/phrases/providers").json()
    assert [(p["id"], p["available"]) for p in answer["providers"]] == [
        ("CLAUDE", False),
        ("CODEX", False),
        ("GROK", False),
    ]
    assert words in answer["message"]


def test_the_client_asks_core_with_the_product_key(monkeypatch):
    import io
    import json

    from products.aegis import core_client

    with pytest.raises(CoreReadingError) as caught:
        core_client.CoreReasoning(key="short").providers()
    assert caught.value.reason == "not_issued"
    seen = []

    def urlopen(request, timeout):
        seen.append((request.full_url, request.get_method(), request.get_header("Authorization")))
        listed = [{"provider": "GROK", "available": True}]
        return io.BytesIO(json.dumps({"providers": listed}).encode())

    monkeypatch.setattr(core_client.urllib.request, "urlopen", urlopen)
    listed = core_client.CoreReasoning(base="http://core", key="k" * 48).providers()
    assert listed == [{"provider": "GROK", "available": True}]
    assert seen == [
        ("http://core/api/core/products/aegis/reasoning/providers", "GET", "Bearer " + "k" * 48)
    ]


def test_with_no_provider_offered_only_the_phrase_reader_reads(core):  # QA observation 2
    c, fake = core
    answer = c.post("/aegis/api/strategies/read", json=body(UNREADABLE, ai=False))
    assert answer.status_code == 422
    detail = answer.json()["detail"]
    assert detail["ai"]["reason"] == "none_available" and "No AI" in detail["ai"]["message"]
    assert detail["unread"][0]["text"] == "up"
    assert fake.calls == []  # Core is not asked, so it records no refused routing
    assert c.post("/aegis/api/strategies/read", json=body(REWRITE, ai=False)).status_code == 200


@pytest.mark.parametrize("failure", [ValueError("not JSON"), KeyError("providers")])
def test_a_malformed_core_answer_offers_none(core, failure):  # QA observation 5
    c, fake = core
    fake.providers = lambda: (_ for _ in ()).throw(failure)
    answer = c.get("/aegis/api/phrases/providers")
    assert answer.status_code == 200
    assert not any(p["available"] for p in answer.json()["providers"])
    assert "could not say which providers are available" in answer.json()["message"]


def test_a_failed_availability_check_says_so(core):  # QA observation 5
    c, fake = core
    fake.error = CoreReadingError(500, "failed", "boom")
    message = c.get("/aegis/api/phrases/providers").json()["message"]
    assert message == "Core could not say which providers are available: boom"


def test_learn_list_and_remove_routes(core):
    c, fake = core
    learned = c.post(
        "/aegis/api/phrases/learn",
        json={
            "text": UNREADABLE,
            "rewrite": REWRITE,
            "substitutions": [{"from": "crosses up", "to": "crosses above"}],
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "run_id": "run-1",
            "strategy": default_strategy().model_dump(mode="json"),
        },
    )
    assert learned.status_code == 200, learned.text
    ((entry,),) = [learned.json()["kept"]]
    assert entry["from"] == "crosses up"
    assert [e["id"] for e in c.get("/aegis/api/phrases/learned").json()] == [entry["id"]]
    again = c.post("/aegis/api/strategies/read", json=body(UNREADABLE)).json()
    assert again["read_by"] == "phrases" and fake.calls == []  # instant now, no provider
    assert c.delete(f"/aegis/api/phrases/learned/{entry['id']}").status_code == 200
    assert c.delete(f"/aegis/api/phrases/learned/{entry['id']}").status_code == 404
    c.post("/aegis/api/strategies/read", json=body(UNREADABLE))
    assert len(fake.calls) == 1  # forgotten: the provider is asked again


def test_read_with_ai_checks_the_rewrite_with_the_reader():
    fake = FakeCore()
    reading = read_with_ai(UNREADABLE, default_strategy(), "CLAUDE", fake, [])
    assert reading.read_by == "ai" and reading.provenance["run_id"] == "run-1"
