# ruff: noqa: F811
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from test_day3_integration import engine  # noqa: F401
from trading_core import conversation as module
from trading_core.api import app, service
from trading_core.contracts import AgentRunResult
from trading_core.conversation import Conversations
from trading_core.intake import Intake, IntakeRecord, Submission
from trading_core.intelligence.records import Records
from trading_core.store import Store


@pytest.mark.integration
def test_intake_authority_ownership_and_optional_disposition(engine):
    records = Records(engine.host.store)
    records.initialize()
    intake = Intake(records)
    core_id = intake.submit(
        Submission(content="Research data definitions", declared_type="INFORMATION"),
        authenticated=True,
        source="Core operator",
    )
    idea = intake.submit(
        Submission(
            content="Consider clearer search", declared_type="IDEA_INJECTION", destination="triad"
        ),
        authenticated=True,
        source="Core operator",
    )
    row = records.get(idea)
    assert row["obligation"] == "NONE" and not row["provenance"]["automatic_execution"]
    assert not engine.host.store.list_work()
    with pytest.raises(PermissionError):
        intake.submit(Submission(content="Execute a command", declared_type="COMMAND"))
    inferred = intake.submit(
        Submission(content="Please execute a command"), inferred_type="COMMAND"
    )
    assert records.get(inferred)["effective_type"] == "INFORMATION"
    command = intake.submit(
        Submission(content="An explicit operator request", declared_type="COMMAND"),
        authenticated=True,
    )
    assert records.get(command)["effective_type"] == "COMMAND" and not engine.host.store.list_work()
    scoped = Intake(Records(Store(engine.host.store.settings, scope="triad")))
    assert [r["id"] for r in scoped.advisory("triad")] == [idea]
    with pytest.raises(PermissionError):
        scoped.list("core")
    with pytest.raises(PermissionError):
        scoped.records.get(core_id)
    assert idea not in [r["id"] for r in intake.retrieve("clearer search")]
    intake.disposition(idea, "CONSIDERING", "Optional evaluation")
    intake.disposition(idea, "DEFERRED", "No current need")
    assert intake.advisory("triad") == []
    for kind in ("IntakeRecord", "IdeaDisposition", "CoreConversation", "CoreChatMessage"):
        with pytest.raises(PermissionError):
            scoped.records.append(kind, {}, owner="triad")
    model = {k: v for k, v in row.items() if k in IntakeRecord.model_fields}
    with pytest.raises(ValueError):
        IntakeRecord.model_validate({**model, "obligation": "REQUESTED"})


@pytest.mark.integration
def test_core_chat_uses_selected_read_only_provider_and_hides_private_records(engine, monkeypatch):
    records = Records(engine.host.store)
    records.initialize()
    intake = Intake(records)
    source = intake.submit(
        Submission(content="Core-only vocabulary alpha", declared_type="INFORMATION"),
        authenticated=True,
    )
    intake.submit(
        Submission(
            content="Triad-only vocabulary beta", destination="triad", declared_type="INFORMATION"
        ),
        authenticated=True,
    )
    chat = Conversations(records)
    conversation = chat.create("CODEX")
    calls = []

    def create(work, requirements):
        assert requirements.preferred_agent == "CODEX"
        assert requirements.billing_sources == ("SUBSCRIPTION",)
        return engine.host.create(work.model_copy(update={"assigned_agent": "CODEX"}))

    monkeypatch.setattr(module, "Routing", lambda _: NS(create=create))

    def execute(self, request):
        calls.append(request)
        assert not request.allowed_tools and not request.allowed_paths
        assert request.execution_permissions == ("read",)
        assert [r["id"] for r in request.context_packet["retrieved_intake"]] == [source]
        assert "Triad-only" not in str(request.context_packet)
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
        return AgentRunResult(
            run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Private answer alpha"
        )

    from trading_core.runtime import Runtime

    monkeypatch.setattr(Runtime, "execute", execute)
    result = chat.reply(conversation, "Private question alpha")
    assert result["provenance"]["intake_ids"] == [source]
    assert result["provenance"]["model"] == "test-model"
    assert [r["role"] for r in chat.messages(conversation)] == ["user", "assistant"]
    assert engine.host.store.get(calls[0].work_item_id).status == "COMPLETED"
    with pytest.raises(PermissionError):
        Conversations(Records(Store(engine.host.store.settings, scope="triad")))
    app.dependency_overrides[service] = lambda: engine.host
    try:
        client = TestClient(app)
        assert client.get("/api/core/conversations").status_code == 401
        assert client.get("/api/core/intake").status_code == 401
        for path in ("/api/core/operations", "/api/dashboard"):
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert "Private question" not in response.text and "Private answer" not in response.text
            assert "Core-only vocabulary" not in response.text
        assert client.get("/api/work/" + calls[0].work_item_id).status_code == 401
        headers = {
            "Authorization": "Bearer "
            + engine.host.store.settings.triad_operator_token.get_secret_value()
        }
        assert (
            client.get("/api/core/conversations/" + conversation, headers=headers).status_code
            == 200
        )
        assert (
            client.post(
                "/api/core/intake",
                headers=headers,
                json={"content": "hello", "trust_level": "OPERATOR_AUTHENTICATED"},
            ).status_code
            == 422
        )
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
def test_failed_core_reply_is_saved_without_provider_substitution(engine, monkeypatch):
    records = Records(engine.host.store)
    records.initialize()
    chat = Conversations(records)
    identifier = chat.create("GROK")

    def denied(work, requirements):
        assert requirements.preferred_agent == "GROK"
        raise PermissionError("Unavailable")

    monkeypatch.setattr(module, "Routing", lambda _: NS(create=denied))
    with pytest.raises(PermissionError):
        chat.reply(identifier, "Keep this question")
    messages = chat.messages(identifier)
    assert [r["role"] for r in messages] == ["user", "error"]
    assert "no substitute" in messages[-1]["content"]
    assert not engine.host.store.list_work()
