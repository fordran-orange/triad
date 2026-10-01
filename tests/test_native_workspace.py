"""Workspace adapters preserve host-observed changes and deny extra authority."""

import json
from types import SimpleNamespace

import pytest
from trading_core.contracts import AgentRunResult
from trading_core.product_workspace import ProductWorkspace
from trading_core.providers.native_agents import GrokSession, NativeRun, claude_arguments
from trading_core.runtime import ProviderError


def workspace():
    return ProductWorkspace({}, image="sha256:" + "a" * 64, guard=lambda: None)


def test_claude_catalog_includes_only_broker_tools():
    names = [t["name"] for t in workspace().definitions()]
    args = claude_arguments("http://127.0.0.1/fixture", tool_names=names)
    start = args.index("--allowedTools") + 1
    assert args[start : start + len(names)] == ["mcp__triad__" + n for n in names]
    assert args[args.index("--tools") + 1] == ""


def test_result_is_reconstructed_from_actual_edits():
    run = NativeRun([], lambda: None)
    run.product_workspace = True
    run.broker = workspace()
    run.broker.call("write_file", {"path": "products/triad/example.txt", "content": "observed"})
    raw = AgentRunResult(run_id="fixture", status="NO_CHANGE_JUSTIFIED", summary="fixture")
    result, *_ = run.finish(raw.model_dump(), 10, 5)
    assert json.loads(result.analysis_artifacts[0])["files"][0]["content"] == "observed"
    assert run.evidence["boundary"] == "DOCKER_PRODUCT_WORKSPACE"


def test_unobserved_model_payload_is_rejected():
    run = NativeRun([], lambda: None)
    run.product_workspace = True
    run.broker = workspace()
    raw = AgentRunResult(
        run_id="fixture",
        status="NO_CHANGE_JUSTIFIED",
        summary="fixture",
        analysis_artifacts=("unobserved",),
    )
    with pytest.raises(ProviderError, match="ProductToolResultViolation"):
        run.finish(raw.model_dump(), 10, 5)


def test_final_workspace_result_requires_actual_edits():
    run = NativeRun([], lambda: None)
    run.product_workspace = True
    run.broker = workspace()
    raw = AgentRunResult(run_id="fixture", status="CODE_CHANGE", summary="claimed edits")
    with pytest.raises(ProviderError, match="NativeWorkspaceChangesMissing"):
        run.finish(raw.model_dump(), 10, 5)


def test_output_schema_matches_host_evidence_rules_without_mutating_request():
    run = NativeRun([], lambda: None)
    schema = AgentRunResult.model_json_schema()
    original = json.dumps(schema, sort_keys=True)
    request = SimpleNamespace(required_output_schema=schema)
    ordinary = run.result_schema(request)
    assert ordinary["properties"]["tests_run"]["maxItems"] == 0
    assert "maxItems" not in ordinary["properties"]["analysis_artifacts"]
    run.product_workspace = True
    constrained = run.result_schema(request)
    for name in (
        "commands_executed",
        "permission_requests",
        "claims",
        "actions_taken",
        "tests_run",
        "files_changed",
        "analysis_artifacts",
    ):
        assert constrained["properties"][name]["maxItems"] == 0
    assert json.dumps(schema, sort_keys=True) == original


def test_bad_result_remains_rejected_with_field_names_only():
    run = NativeRun([], lambda: None)
    run.product_workspace = True
    run.broker = workspace()
    raw = AgentRunResult(
        run_id="fixture",
        status="NO_CHANGE_JUSTIFIED",
        summary="fixture",
        tests_run=("untrusted text",),
    )
    with pytest.raises(ProviderError, match="NativeResultViolation"):
        run.finish(raw.model_dump(), 10, 5)
    assert run.evidence["rejected_result_fields"] == ["tests_run"]
    assert "untrusted text" not in json.dumps(run.evidence)


def test_workspace_denials_retain_code_location_not_arguments():
    broker = workspace()
    with pytest.raises(PermissionError):
        broker.call("invented secret tool", {"sensitive": "private text"})
    assert broker.denials == 1
    assert broker.denial_details[0]["tool"] == "UNKNOWN"
    assert broker.denial_details[0]["location"].startswith("product_workspace.py:")
    assert "private text" not in json.dumps(broker.denial_details)


def session():
    value = GrokSession.__new__(GrokSession)
    value.guard = lambda: None
    value.workspace_url = "http://127.0.0.1/fixture"
    value.broker = workspace()
    value.session_id = "fixture"
    value.catalog_starting = True
    value.expected_tools = {"search_tool", "use_tool"} | {
        "triad__" + t["name"] for t in value.broker.definitions()
    }
    value.sent = []
    value.process = SimpleNamespace(send=value.sent.append)
    return value


def catalog(value, tools):
    value.observe(
        {
            "method": "session/update",
            "params": {"sessionId": value.session_id, "update": {"_meta": {"tools": list(tools)}}},
        }
    )


def test_grok_lazy_catalog_cannot_expand_or_downgrade():
    value = session()
    catalog(value, {"search_tool", "use_tool"})
    catalog(value, value.expected_tools)
    assert not value.catalog_starting
    with pytest.raises(ProviderError, match="NativeToolCatalogMismatch"):
        catalog(value, value.expected_tools | {"run_terminal_command"})
    with pytest.raises(ProviderError, match="NativeToolCatalogMismatch"):
        catalog(value, {"search_tool", "use_tool"})


@pytest.mark.parametrize(
    "method",
    ["fs/read_text_file", "fs/write_text_file", "terminal/create", "session/request_permission"],
)
def test_grok_workspace_never_permits_host_callbacks(method):
    value = session()
    value.observe(
        {
            "id": 1,
            "method": method,
            "params": {
                "sessionId": "fixture",
                "path": "products/triad/example.txt",
                "content": "bad",
            },
        }
    )
    assert "error" in value.sent[-1]
    assert not value.broker.calls


def permission_request(value):
    return {
        "id": 5,
        "method": "session/request_permission",
        "params": {
            "sessionId": value.session_id,
            "toolCall": {
                "toolCallId": "call-1",
                "rawInput": {
                    "variant": "UseTool",
                    "tool_name": "triad__run_command",
                    "tool_input": {"argv": ["python", "--version"]},
                },
            },
            "options": [
                {"kind": "allow_always", "optionId": "forever"},
                {"kind": "allow_once", "optionId": "once"},
            ],
        },
    }


@pytest.mark.parametrize("as_text", [False, True])
def test_grok_approves_only_one_broker_invocation(as_text):
    value = session()
    value.tools = value.expected_tools
    request = permission_request(value)
    if as_text:
        raw = request["params"]["toolCall"]["rawInput"]
        raw["tool_input"] = json.dumps(raw["tool_input"])
    value.observe(request)
    assert value.sent[-1]["result"] == {"outcome": {"outcome": "selected", "optionId": "once"}}
    assert not value.broker.calls


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        '"string"',
        "{bad",
        '{"argv":[],"argv":[]}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
    ],
)
def test_grok_malformed_tool_arguments_are_recoverable_tool_errors(raw):
    from trading_core.providers.bounded_tools import ToolServer

    value = session()
    value.tools = value.expected_tools
    request = permission_request(value)
    request["params"]["toolCall"]["rawInput"]["tool_input"] = raw
    value.observe(request)
    assert value.sent[-1]["result"]["outcome"]["optionId"] == "once"
    assert not value.broker.calls
    server = ToolServer.__new__(ToolServer)
    server.broker = value.broker
    reply = server.dispatch(
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "run_command",
                "arguments": raw,
            },
        }
    )
    assert reply["result"]["isError"]
    assert not value.broker.calls and not value.broker.changes()
    # A valid subsequent call can succeed in the same broker session.
    reply = server.dispatch(
        {
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "write_file",
                "arguments": {"path": "products/triad/example.txt", "content": "corrected"},
            },
        }
    )
    assert not reply["result"].get("isError")
    assert value.broker.changes()[0].content == "corrected"


@pytest.mark.parametrize(
    "mutation", ["other_tool", "wrong_session", "pending_catalog", "permanent_only", "extra_input"]
)
def test_grok_rejects_broader_permission(mutation):
    value = session()
    value.tools = value.expected_tools
    message = permission_request(value)
    if mutation == "other_tool":
        message["params"]["toolCall"]["rawInput"]["tool_name"] = "other__run_command"
    elif mutation == "wrong_session":
        message["params"]["sessionId"] = "other"
    elif mutation == "pending_catalog":
        value.tools = ["search_tool", "use_tool"]
    elif mutation == "permanent_only":
        message["params"]["options"] = message["params"]["options"][:1]
    else:
        message["params"]["toolCall"]["rawInput"]["host"] = True
    value.observe(message)
    assert "error" in value.sent[-1]


@pytest.mark.parametrize("empty_attempts", [0, 1, 2])
def test_grok_executes_without_schema_before_formatting(monkeypatch, empty_attempts):
    from contextlib import nullcontext

    from trading_core.providers import native_agents as native

    broker = workspace()
    prompts = []
    closed = []

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.session_id = "fixture"
            self.process = SimpleNamespace(failure_reason=None)
            self.tools = self.expected_tools = {"search_tool", "use_tool"}
            self.text = ""

        def authenticate(self):
            pass

        def start(self, model):
            return "fixture-model"

        def call(self, method, params):
            assert method == "session/prompt"
            prompts.append(params)
            schema = params.get("_meta", {}).get("outputSchema")
            if schema is None and len(prompts) > empty_attempts:
                broker.call(
                    "write_file", {"path": "products/triad/example.txt", "content": "actual"}
                )
            if schema:
                assert broker.changes()
                assert schema["properties"]["files_changed"]["maxItems"] == 0
                assert "host verified that both/all" not in params["prompt"][0]["text"]
            return {
                "stopReason": "end_turn",
                "_meta": {
                    "modelId": "fixture-model",
                    "usage": {"modelUsage": {"fixture": {"inputTokens": 10, "outputTokens": 3}}},
                    "structuredOutput": AgentRunResult(
                        run_id="fixture", status="CODE_CHANGE", summary="fixture"
                    ).model_dump(),
                },
            }

        def close(self):
            closed.append(True)

    monkeypatch.setattr(native, "GrokSession", FakeSession)
    monkeypatch.setattr(native, "grok_preflight", lambda *args: None)
    monkeypatch.setattr(
        native, "ToolServer", lambda _: nullcontext(SimpleNamespace(url="http://fixture"))
    )
    request = SimpleNamespace(
        required_output_schema=AgentRunResult.model_json_schema(),
        model_dump_json=lambda **kwargs: "{}",
    )
    run = native.GrokRun([], lambda: None)
    if empty_attempts == 2:
        with pytest.raises(ProviderError, match="NativeWorkspaceChangesMissing"):
            run.execute(request, {"fixture": "content"}, workspace=broker)
        assert len(prompts) == 2
        assert run.evidence["input_tokens"] == 20
        assert all("_meta" not in p for p in prompts)
    else:
        result, inputs, outputs = run.execute(request, {"fixture": "content"}, workspace=broker)
        assert len(prompts) == empty_attempts + 2
        assert inputs == len(prompts) * 10 and outputs == len(prompts) * 3
        assert json.loads(result.analysis_artifacts[0])["files"][0]["content"] == "actual"
        assert all("_meta" not in p for p in prompts[:-1])
        assert "_meta" in prompts[-1]
    assert closed == [True]
