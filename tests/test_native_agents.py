"""Fixture protocol tests and real offline tools; no provider inference or login."""

import json
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from triad.day3.adapters import ProviderError
from triad.day3.contracts import AgentRunResult
from triad.day5a import native_agents as native
from triad.day5a.bounded_tools import BoundedTools, ToolServer
from triad.day5a.codex_executor import LineProcess
from triad.day5a.isolation import OfflineSandbox

pytestmark = pytest.mark.triad


class Wire:
    def __init__(self, replies=()):
        self.replies = iter(replies)
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def receive(self, **kwargs):
        kwargs.get("guard", lambda: None)()
        return next(self.replies)

    def close(self):
        pass


def test_workspace_cleanup_retries_windows_child_release(monkeypatch):
    attempts = []

    def cleanup():
        attempts.append(True)
        if len(attempts) == 1:
            raise PermissionError("Fixture child still closing")

    monkeypatch.setattr(
        native.tempfile,
        "TemporaryDirectory",
        lambda **k: SimpleNamespace(name="fixture-workspace", cleanup=cleanup),
    )
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    with native.native_workspace("fixture-") as cwd:
        assert cwd == "fixture-workspace"
    assert len(attempts) == 2


def test_protocol_burst_is_backpressured_without_frame_loss():
    process = LineProcess(
        [
            sys.executable,
            "-c",
            "import json; [print(json.dumps({'id':i}),flush=True) for i in range(400)]",
        ]
    )
    try:
        time.sleep(0.2)
        assert process.messages.qsize() <= 128
        assert [process.receive(timeout=5)["id"] for _ in range(400)] == list(range(400))
    finally:
        process.close()


def session(broker=None):
    s = native.GrokSession.__new__(native.GrokSession)
    s.cwd = "C:/Temp/triad-fixture"
    s.guard = lambda: None
    s.broker = broker or BoundedTools({"README.md": "Fixture\n"})
    s.serial, s.session_id = 0, "fixture-session"
    s.expected_tools, s.tools, s.text = {"read_file"}, None, ""
    s.process = Wire()
    return s


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "../README.md",
        "/etc/passwd",
        "C:/Triad/.env",
        "a\\b",
        "C:/Temp/triad-fixture-other/README.md",
    ],
)
def test_acp_path_escape_rejected(path):
    with pytest.raises((ValueError, PermissionError)):
        session().relative(path)


def test_acp_maps_only_dedicated_workspace():
    assert session().relative("C:\\Temp\\triad-fixture\\README.md") == "README.md"


@pytest.mark.parametrize(
    "method",
    [
        "terminal/create",
        "terminal/output",
        "session/request_permission",
        "x.ai/mcp/sdk_call",
        "fs/delete_file",
    ],
)
def test_acp_denies_extra_capabilities(method):
    s = session()
    s.observe({"id": 9, "method": method, "params": {"sessionId": s.session_id}})
    assert "error" in s.process.sent[-1]
    assert not s.broker.calls


def test_acp_wrong_session_and_catalog_drift_fail_closed():
    s = session()
    s.observe(
        {
            "id": 9,
            "method": "fs/read_text_file",
            "params": {"sessionId": "other", "path": "README.md"},
        }
    )
    assert "error" in s.process.sent[-1]
    with pytest.raises(ProviderError, match="NativeToolCatalogMismatch"):
        s.observe(
            {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "available_commands_update",
                        "_meta": {"tools": ["read_file", "run_terminal_command"]},
                    }
                },
            }
        )


def test_acp_subscription_metadata_required():
    s = session()
    replies = iter(
        [
            {
                "_meta": {"agentVersion": native.VERSIONS["GROK"]},
                "protocolVersion": 1,
                "authMethods": [{"id": "cached_token"}],
            },
            {
                "_meta": {
                    "auth_mode": "ApiKey",
                    "backend_billed": True,
                    "subscription_tier": "fixture",
                }
            },
        ]
    )
    s.call = lambda *_: next(replies)
    with pytest.raises(ProviderError, match="SubscriptionAuthenticationRequired"):
        s.authenticate()


def test_claude_has_no_builtin_tools_and_only_dedicated_mcp():
    args = native.claude_arguments("http://127.0.0.1/fixture")
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in args and "--disable-slash-commands" in args
    settings = json.loads(args[args.index("--settings") + 1])
    assert settings["disableAllHooks"] and settings["forceLoginMethod"] == "claudeai"
    assert "--dangerously-skip-permissions" not in args


@pytest.mark.parametrize(
    "servers",
    [
        [],
        [{"name": "other", "status": "connected", "tools": []}],
        [{"name": "triad", "status": "failed", "tools": [{"name": "read_file"}]}],
        [
            {
                "name": "triad",
                "status": "connected",
                "tools": [{"name": "read_file"}, {"name": "shell"}],
            }
        ],
    ],
)
def test_claude_mcp_catalog_gate_precedes_inference(servers):
    app = Wire(
        [
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": "initialize"},
            },
            {
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": "mcp",
                    "response": {"mcpServers": servers},
                },
            },
        ]
    )
    with pytest.raises(ProviderError, match="NativeToolCatalogMismatch"):
        native.claude_initialize(app, lambda: None, {"read_file"})
    assert all(m["type"] == "control_request" for m in app.sent)


@pytest.mark.parametrize(
    "name,args",
    [
        ("read_file", {"path": "../secret"}),
        ("read_file", {"path": "other.md"}),
        ("read_file", {"path": "README.md", "cwd": "C:/"}),
        ("shell", {"path": "README.md"}),
        ("propose_file_change", {"path": "README.md", "content": "bad"}),
    ],
)
def test_broker_denies_before_container_launch(monkeypatch, name, args):
    broker = BoundedTools({"README.md": "safe"})
    monkeypatch.setattr(broker.sandbox, "run", lambda *a, **k: pytest.fail("Must not launch"))
    with pytest.raises((ValueError, PermissionError)):
        broker.call(name, args)
    assert broker.denials == 1


def test_mcp_endpoint_rejects_wrong_origin_path_and_unknown_method():
    with ToolServer(BoundedTools({})) as server:
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        with httpx.Client(trust_env=False) as client:
            assert client.post(server.url + "x", json=message).status_code == 403
            assert (
                client.post(
                    server.url, json=message, headers={"Origin": "https://evil.example"}
                ).status_code
                == 403
            )
            result = client.post(server.url, json=message).json()["result"]
            assert [t["name"] for t in result["tools"]] == ["read_file"]
            assert "error" in client.post(server.url, json={**message, "method": "shell"}).json()


def test_offline_read_proposal_and_call_budget():
    if not OfflineSandbox.available():
        pytest.skip("Pinned Docker image unavailable")
    broker = BoundedTools(
        {"README.md": "# Fixture\n"}, writable=("docs/improvements",), max_calls=2
    )
    assert broker.call("read_file", {"path": "README.md"}) == "# Fixture\n"
    broker.call(
        "propose_file_change", {"path": "docs/improvements/a.md", "content": "Reviewed later\n"}
    )
    assert broker.changes()[0].path == "docs/improvements/a.md"
    assert broker.changes()[0].content == "Reviewed later\n"
    with pytest.raises(PermissionError, match="budget"):
        broker.call("read_file", {"path": "README.md"})


def test_revoked_authority_prevents_tool(monkeypatch):
    def guard():
        raise PermissionError("Revoked")

    broker = BoundedTools({"README.md": "safe"}, guard=guard)
    monkeypatch.setattr(broker.sandbox, "run", lambda *a, **k: pytest.fail("Must not launch"))
    with pytest.raises(PermissionError, match="Revoked"):
        broker.call("read_file", {"path": "README.md"})


def test_result_needs_actual_tool_evidence_and_measured_usage():
    run = native.NativeRun([], lambda: None)
    run.broker = BoundedTools({"README.md": "safe"})
    result = AgentRunResult(
        run_id="fixture", status="NO_CHANGE_JUSTIFIED", summary="fixture"
    ).model_dump()
    with pytest.raises(ProviderError, match="NativeReadEvidenceMissing"):
        run.finish(result, 20, 10)
    assert run.evidence["input_tokens"] == 20
    with pytest.raises(ProviderError, match="NativeUsageMissing"):
        run.finish(result, True, 10)
    run.cancel()
    with pytest.raises(ProviderError, match="DeadlineExceeded"):
        run.check()


def test_grok_preflight_rejects_unrelated_integrations(monkeypatch):
    report = {"hooks": [{"disabled": False}], "plugins": [], "mcpServers": [], "lspServers": []}
    monkeypatch.setattr(
        native.ManagedProcess,
        "run",
        lambda *a, **k: SimpleNamespace(status="EXITED", exit_code=0, stdout=json.dumps(report)),
    )
    with pytest.raises(ProviderError, match="NativeCustomizationsPresent"):
        native.grok_preflight(["fixture"], ".")


def test_claude_structured_result_and_cache_usage(monkeypatch):
    result = AgentRunResult(
        run_id="fixture", status="NO_CHANGE_JUSTIFIED", summary="Fixture only"
    ).model_dump(mode="json")
    wire = Wire(
        [
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": "initialize"},
            },
            {
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": "mcp",
                    "response": {
                        "mcpServers": [
                            {
                                "name": "triad",
                                "status": "connected",
                                "tools": [{"name": "read_file"}],
                            }
                        ]
                    },
                },
            },
            {
                "type": "system",
                "subtype": "init",
                "tools": ["mcp__triad__read_file", "StructuredOutput"],
                "model": "fixture-model",
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "structured_output": result,
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 30,
                    "output_tokens": 5,
                },
            },
        ]
    )
    monkeypatch.setattr(native, "LineProcess", lambda *a, **k: wire)
    request = SimpleNamespace(
        context_packet={},
        run_id="fixture",
        required_output_schema=AgentRunResult.model_json_schema(),
        model_dump_json=lambda **k: "{}",
    )
    run = native.ClaudeRun(["fixture"], lambda: None)
    parsed, inputs, outputs = run.execute(request, {})
    assert parsed.run_id == "fixture" and (inputs, outputs) == (60, 5)
    assert run.actual_model == "fixture-model"
    assert wire.sent[-1]["type"] == "user"


def test_grok_uses_whole_prompt_usage_not_last_call(monkeypatch):
    result = AgentRunResult(
        run_id="fixture", status="NO_CHANGE_JUSTIFIED", summary="Fixture only"
    ).model_dump(mode="json")

    class FixtureSession:
        def __init__(self, *args):
            self.session_id = "fixture-session"

        def authenticate(self):
            return {"auth_state": "AUTHENTICATED", "billing_source": "SUBSCRIPTION"}

        def start(self, model):
            return "fixture-model"

        def call(self, method, params):
            assert method == "session/prompt"
            return {
                "stopReason": "end_turn",
                "_meta": {
                    "structuredOutput": result,
                    "modelId": "fixture-model",
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "usage": {
                        "modelUsage": {"fixture-model": {"inputTokens": 120, "outputTokens": 12}}
                    },
                },
            }

        def close(self):
            pass

    monkeypatch.setattr(native, "GrokSession", FixtureSession)
    monkeypatch.setattr(native, "grok_preflight", lambda *a: None)
    request = SimpleNamespace(
        context_packet={},
        run_id="fixture",
        required_output_schema=AgentRunResult.model_json_schema(),
        model_dump_json=lambda **k: "{}",
    )
    parsed, inputs, outputs = native.GrokRun(["fixture"], lambda: None).execute(request, {})
    assert parsed.run_id == "fixture" and (inputs, outputs) == (120, 12)


@pytest.mark.parametrize("complete_reads", [True, False])
def test_grok_reads_before_schema_and_accounts_for_both_prompts(monkeypatch, complete_reads):
    result = AgentRunResult(
        run_id="fixture", status="NO_CHANGE_JUSTIFIED", summary="Fixture"
    ).model_dump(mode="json")
    prompts = []

    class FixtureSession:
        def __init__(self, command, cwd, guard, broker):
            self.broker = broker
            self.session_id = "fixture"
            self.process = SimpleNamespace(failure_reason="fixture")

        def authenticate(self):
            pass

        def start(self, model):
            return "fixture-model"

        def call(self, method, params):
            prompts.append(params)
            if len(prompts) == 1:
                assert "_meta" not in params
                self.broker.calls.append({"tool": "read_file", "path": "README.md"})
                if complete_reads:
                    self.broker.calls.append({"tool": "read_file", "path": "docs/UI.md"})
            else:
                assert "outputSchema" in params["_meta"]
            return {
                "stopReason": "end_turn",
                "_meta": {
                    "modelId": "fixture-model",
                    "structuredOutput": result,
                    "usage": {
                        "modelUsage": {"fixture-model": {"inputTokens": 120, "outputTokens": 12}}
                    },
                },
            }

        def close(self):
            pass

    monkeypatch.setattr(native, "GrokSession", FixtureSession)
    monkeypatch.setattr(native, "grok_preflight", lambda *a: None)
    request = SimpleNamespace(
        context_packet={},
        run_id="fixture",
        required_output_schema=AgentRunResult.model_json_schema(),
        model_dump_json=lambda **k: "{}",
    )
    run = native.GrokRun(["fixture"], lambda: None)
    files = {"README.md": "fixture", "docs/UI.md": "fixture"}
    if complete_reads:
        _, inputs, outputs = run.execute(request, files)
        assert (inputs, outputs) == (240, 24) and len(prompts) == 2
    else:
        with pytest.raises(ProviderError, match="NativeReadEvidenceMissing"):
            run.execute(request, files)
        assert len(prompts) == 1
        assert run.evidence["input_tokens"] == 120
