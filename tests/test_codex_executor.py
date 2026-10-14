"""Executor mediation tests do not spend subscription or API usage."""

import pytest
from triad.day5a.codex_executor import CodexExecutor

pytestmark = pytest.mark.triad


def request(argv, **extra):
    return {
        "id": 1,
        "method": "process/start",
        "params": {
            "argv": argv,
            "cwd": "file:///host",
            "env": {"UNTRUSTED": "value"},
            **extra,
        },
    }


def test_native_read_is_rebuilt_without_shell_or_environment():
    executor = CodexExecutor({"README.md": "approved"}, guard=lambda: None)
    output = executor.mediate(request(["/usr/bin/bash", "-lc", "cat README.md"]))
    assert output["params"]["argv"] == ["cat", "--", "README.md"]
    assert output["params"]["cwd"] == "file:///workspace"
    assert output["params"]["env"] == {}
    assert output["params"]["envPolicy"]["inherit"] == "none"
    assert output["params"]["pipeStdin"] is False


@pytest.mark.parametrize(
    "command",
    [
        "cat README.md; id",
        "cat /etc/passwd",
        "cat ../README.md",
        "cat README.md > new",
        "cat $(id)",
        "curl https://example.com",
        "python -c 'print(1)'",
        "cat README.md | sh",
        "cat README.md && id",
    ],
)
def test_ungranted_commands_never_reach_executor(command):
    executor = CodexExecutor({"README.md": "approved"}, guard=lambda: None)
    with pytest.raises(PermissionError):
        executor.mediate(request(["/usr/bin/bash", "-lc", command]))


@pytest.mark.parametrize(
    "method",
    [
        "fs/writeFile",
        "fs/remove",
        "process/writeStdin",
        "network/connect",
        "environment/add",
        "unknown",
    ],
)
def test_unknown_or_mutating_protocol_operations_are_denied(method):
    executor = CodexExecutor({}, guard=lambda: None)
    with pytest.raises(PermissionError):
        executor.mediate({"id": 1, "method": method, "params": {}})


def test_only_supplied_file_content_can_be_read():
    executor = CodexExecutor({"README.md": "approved"}, guard=lambda: None)
    allowed = {"id": 1, "method": "fs/readFile", "params": {"path": "file:///workspace/README.md"}}
    assert executor.mediate(allowed) == allowed
    for path in ("file:///etc/passwd", "file:///workspace/../tmp/secret", "C:/Triad/.env"):
        with pytest.raises(PermissionError):
            executor.mediate({**allowed, "params": {"path": path}})


def test_secret_in_protocol_rejected(monkeypatch):
    monkeypatch.setenv("TRIAD_TEST_TOKEN", "secret-boundary-check-123")
    executor = CodexExecutor({}, guard=lambda: None)
    with pytest.raises(PermissionError):
        executor.mediate(request(["cat", "README.md"], env={"KEY": "secret-boundary-check-123"}))
