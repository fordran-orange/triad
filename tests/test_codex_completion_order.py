"""Actual runner with a deterministic app-server notification ordering fixture."""

from types import SimpleNamespace as NS

import pytest
from trading_core.contracts import AgentRunResult
from trading_core.providers import codex_executor as codex
from trading_core.runtime import ProviderError

pytestmark = pytest.mark.core


class Executor:
    def __init__(self, files, **kw):
        self.environment_id, self.url = "env", "ws://fixture"
        self.methods, self.responses, self.requests = [], [], []
        self.denials, self.files = 0, files

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class App:
    def __init__(self, early, status="completed", foreign=False, omit=False):
        self.early, self.status, self.foreign, self.omit = early, status, foreign, omit
        self.queue, self.closed = [], False

    def send(self, msg):
        method = msg.get("method")
        if "id" not in msg or not method:
            return
        replies = {
            "initialize": {},
            "environment/add": {},
            "environment/info": {"cwd": "file:///workspace"},
            "model/list": {"data": [{"id": "model", "isDefault": True}]},
            "thread/start": {"model": "model", "thread": {"id": "thread"}},
            "turn/start": {"turn": {"id": "turn"}},
        }
        reply = {"id": msg["id"], "result": replies[method]}
        if method != "turn/start":
            self.queue.append(reply)
            return
        result = AgentRunResult(run_id="run", status="NO_CHANGE_JUSTIFIED", summary="Done")
        events = [
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread",
                    "tokenUsage": {"total": {"inputTokens": 10, "outputTokens": 5}},
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "threadId": "thread",
                    "turnId": "turn",
                    "item": {
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": result.model_dump_json(),
                    },
                },
            },
        ]
        if self.foreign:
            events.extend(
                [
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "foreign",
                            "turn": {"id": "turn", "status": "failed"},
                        },
                    },
                    {
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread",
                            "turn": {"id": "stale", "status": "failed"},
                        },
                    },
                    {
                        "method": "item/completed",
                        "params": {
                            "threadId": "thread",
                            "turnId": "stale",
                            "item": {
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": "foreign malformed result",
                            },
                        },
                    },
                ]
            )
        if not self.omit:
            events.append(
                {
                    "method": "turn/completed",
                    "params": {"threadId": "thread", "turn": {"id": "turn", "status": self.status}},
                }
            )
        self.queue.extend(events + [reply] if self.early else [reply] + events)

    def receive(self, guard, **kw):
        guard()
        if not self.queue:
            raise TimeoutError("No matching terminal event")
        return self.queue.pop(0)

    def close(self):
        self.closed = True


def execute(monkeypatch, app):
    monkeypatch.setattr(codex, "CodexExecutor", Executor)
    monkeypatch.setattr(codex, "LineProcess", lambda *a, **kw: app)
    monkeypatch.setattr("trading_core.evidence_delivery.prepare", lambda r, f: (r, f, set(f), {}))
    runner = codex.CodexReadOnlyRun([], lambda: None)
    request = NS(
        required_output_schema=AgentRunResult.model_json_schema(), model_dump_json=lambda **kw: "{}"
    )
    return runner.execute(request, {})


@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("status", ["completed", "failed"])
def test_terminal_event_survives_rpc_reply_order(monkeypatch, early, status):
    app = App(early, status)
    if status == "completed":
        result, inputs, outputs = execute(monkeypatch, app)
        assert result.run_id == "run" and (inputs, outputs) == (10, 5)
    else:
        with pytest.raises(ProviderError, match="CodexTurnFailed"):
            execute(monkeypatch, app)
    assert app.closed and not app.queue


def test_vendor_failure_detail_is_preserved_and_redacted(monkeypatch):
    from trading_core import security

    secret = "fixture-private-value-12345"
    monkeypatch.setattr(security, "secrets", lambda: [secret])

    class FailedApp(App):
        def send(self, msg):
            super().send(msg)
            for event in self.queue:
                if event.get("method") == "turn/completed":
                    event["params"]["turn"]["error"] = {
                        "message": "Vendor request failed: " + secret,
                        "openaiErrorInfo": "Other",
                    }

    app = FailedApp(True, "failed " + secret)
    runner = codex.CodexReadOnlyRun([], lambda: None)
    monkeypatch.setattr(codex, "CodexReadOnlyRun", lambda *a, **kw: runner)
    with pytest.raises(ProviderError, match="CodexTurnFailed"):
        execute(monkeypatch, app)
    assert runner.evidence["failed_turn"] == {
        "status": "failed [REDACTED]",
        "message": "Vendor request failed: [REDACTED]",
        "openai_error_info": "Other",
    }
    assert app.closed


@pytest.mark.parametrize("early", [False, True])
def test_foreign_and_stale_events_cannot_replace_matching_completion_or_result(monkeypatch, early):
    app = App(early, foreign=True)
    assert execute(monkeypatch, app)[0].run_id == "run"
    assert app.closed


@pytest.mark.parametrize("early", [False, True])
def test_unrelated_completion_cannot_finish_this_turn(monkeypatch, early):
    app = App(early, foreign=True, omit=True)
    with pytest.raises(TimeoutError):
        execute(monkeypatch, app)
    assert app.closed


@pytest.mark.parametrize("early", [False, True])
@pytest.mark.parametrize("conflict", [False, True])
def test_final_message_replay_must_be_identical(monkeypatch, early, conflict):
    import copy
    import json

    class ReplayApp(App):
        def send(self, msg):
            super().send(msg)
            if msg.get("method") == "turn/start":
                index = next(
                    i for i, r in enumerate(self.queue) if r.get("method") == "item/completed"
                )
                repeated = copy.deepcopy(self.queue[index])
                if conflict:
                    result = json.loads(repeated["params"]["item"]["text"])
                    result["summary"] = "Conflicting final verdict"
                    repeated["params"]["item"]["text"] = json.dumps(result)
                self.queue.insert(index + 1, repeated)

    app = ReplayApp(early)
    if conflict:
        with pytest.raises(ProviderError, match="CodexConflictingCompletion"):
            execute(monkeypatch, app)
    else:
        assert execute(monkeypatch, app)[0].summary == "Done"
    assert app.closed
