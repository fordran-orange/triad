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
        {"method": "session/update", "params": {"update": {"_meta": {"tools": list(tools)}}}}
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


def test_grok_approves_only_one_broker_invocation():
    value = session()
    value.tools = value.expected_tools
    value.observe(permission_request(value))
    assert value.sent[-1]["result"] == {"outcome": {"outcome": "selected", "optionId": "once"}}
    assert not value.broker.calls


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
