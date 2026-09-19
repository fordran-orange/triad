"""Day 5A unit checks use explicit fixtures, never production connectivity claims."""

import ctypes
import json
import os
import sys
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from platform_host.legacy import app, require_operator
from pydantic import ValidationError
from triad.day3.adapters import ProviderError
from triad.day3.security import ensure_no_secret, redact
from triad.day5a.api import service
from triad.day5a.contracts import PREFERRED, ProviderPolicy
from triad.day5a.control import ProviderControl
from triad.day5a.process import ManagedProcess, clean_environment
from triad.day5a.secrets import WindowsSecretStore
from triad.day5a.transports import CLITransport, HTTPTransport, classify_failure
from triad.work import now


def test_cli_first_no_paid_fallback_and_model_ownership():
    for agent, transport in PREFERRED.items():
        policy = ProviderPolicy(agent=agent, preferred_transport=transport)
        assert policy.fallback == "NEVER" and policy.api_daily_budget == 0
    with pytest.raises(ValidationError):
        ProviderPolicy(agent="CODEX", preferred_transport="anthropic_api")
    with pytest.raises(ValidationError):
        ProviderPolicy(agent="LOCAL_QWEN", preferred_transport="ollama", fallback="ASK_EACH_TIME")
    with pytest.raises(ValidationError):
        ProviderPolicy(
            agent="CODEX", preferred_transport="codex_cli", api_daily_budget=float("nan")
        )
    with pytest.raises(ValidationError):
        ProviderPolicy(
            agent="CODEX", preferred_transport="codex_cli", models={"codex_cli": "--yolo"}
        )


def test_login_is_not_online_but_verified_setup_does_not_expire():
    state = {"auth_state": "AUTHENTICATED"}
    assert not ProviderControl.proven(state)
    proof = {"success": True, "mode": "REAL", "completed_at": now().isoformat()}
    state.update(test=proof, workitem=proof)
    assert ProviderControl.proven(state)
    assert not ProviderControl.proven({**state, "error": "AuthExpired"})
    assert not ProviderControl.proven({**state, "test": {**proof, "mode": "SIMULATED"}})
    assert ProviderControl.proven(
        {**state, "workitem": {**proof, "completed_at": (now() - timedelta(hours=2)).isoformat()}}
    )


def test_durable_verification_still_blocks_failures_and_missing_evidence():
    proof = {
        "success": True,
        "mode": "REAL",
        "completed_at": (now() - timedelta(hours=2)).isoformat(),
    }
    state = {"auth_state": "AUTHENTICATED", "health": "OFFLINE", "test": proof, "workitem": proof}
    assert ProviderControl.readiness_state(state) == "ONLINE"
    assert ProviderControl.proven(state)
    assert not ProviderControl.proven({**state, "test": {**proof, "completed_at": "invalid"}})
    assert not ProviderControl.proven(
        {**state, "test": {**proof, "completed_at": (now() + timedelta(days=1)).isoformat()}}
    )
    assert (
        ProviderControl.readiness_state({**state, "error": "ConnectionRefused"})
        == "CONNECTION_ERROR"
    )
    assert (
        ProviderControl.readiness_state({**state, "auth_state": "NOT_AUTHENTICATED"})
        == "AUTH_REQUIRED"
    )
    assert ProviderControl.readiness_state({**state, "workitem": None}) == "VERIFICATION_REQUIRED"
    assert (
        ProviderControl.readiness_state({**state, "test": {"success": False}})
        == "VERIFICATION_FAILED"
    )
    assert ProviderControl.readiness_state({}) == "NOT_CHECKED"
    fresh = {**proof, "completed_at": now().isoformat()}
    assert ProviderControl.readiness_state({**state, "test": fresh, "workitem": fresh}) == "ONLINE"


@pytest.mark.parametrize("version,retained", [("1.0", True), ("2.0", False)])
def test_connection_refresh_preserves_proofs_until_setup_changes(version, retained):
    proof = {"success": True, "mode": "REAL", "completed_at": now().isoformat()}
    adapter = SimpleNamespace(
        transport_type="CLI",
        agent="CODEX",
        detect=lambda: {"install_status": "INSTALLED", "cli_version": version},
        authentication_status=lambda: {"auth_state": "AUTHENTICATED"},
        capabilities=lambda: {"execution_blocker": None},
    )
    host = SimpleNamespace(
        transport=lambda tid: adapter,
        snapshot=lambda tid: {"cli_version": "1.0", "test": proof, "workitem": proof},
        ledger=SimpleNamespace(event=lambda *a, **k: None, put=lambda *a, **k: None),
    )
    result = ProviderControl._refresh(host, "codex_cli")
    assert (result["test"] == proof) is retained
    assert (result["workitem"] == proof) is retained


def test_automatic_monitor_skips_paid_api_and_continues_after_outage():
    from contextlib import nullcontext

    checked = []

    def refresh(tid):
        checked.append(tid)
        if tid == "claude_code_cli":
            raise RuntimeError("fixture unavailable")

    host = SimpleNamespace(
        policy=lambda agent: SimpleNamespace(
            preferred_transport="openai_api" if agent == "CODEX" else PREFERRED[agent]
        ),
        ledger=SimpleNamespace(store=SimpleNamespace(lease=lambda key: nullcontext())),
        refresh=refresh,
    )
    ProviderControl.monitor_connections(host)
    assert checked == ["claude_code_cli", "grok_build_cli", "ollama"]


@pytest.mark.parametrize(
    "message,expected",
    [
        ("usage limit reached", "USAGE_LIMIT_REACHED"),
        ("HTTP 429", "RATE_LIMITED"),
        ("session expired", "AUTH_EXPIRED"),
        ("401 unauthorized", "AUTH_FAILED"),
        ("not logged in", "AUTH_REQUIRED"),
        ("failure", "ERROR"),
    ],
)
def test_failure_classification(message, expected):
    assert classify_failure(message) == expected


def test_process_does_not_inherit_provider_or_operator_credentials(monkeypatch):
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "TRIAD_OPERATOR_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CODEX_HOME",
        "PYTHONPATH",
        "NODE_OPTIONS",
    ):
        monkeypatch.setenv(key, "sensitive-fixture-value")
        assert key not in clean_environment()


def test_managed_process_exit_redaction_and_output_bound(tmp_path):
    result = ManagedProcess().run(
        [sys.executable, "-c", "print('sk-abcdefghijklmnop');raise SystemExit(7)"], cwd=tmp_path
    )
    assert result.exit_code == 7 and "sk-" not in result.stdout
    assert result.process_id > 0 and result.duration > 0
    result = ManagedProcess().run([sys.executable, "-c", "print('x'*200000)"], cwd=tmp_path)
    assert len(result.stdout) <= 131072 and result.status == "OUTPUT_LIMIT"


def test_process_timeout_cancellation_and_kill_guard(tmp_path):
    argv = [sys.executable, "-c", "import time;time.sleep(20)"]
    runner = ManagedProcess()
    result = runner.run(argv, cwd=tmp_path, timeout=0.15)
    assert result.status == "TIMEOUT" and runner.process.poll() is not None
    runner = ManagedProcess()
    timer = threading.Timer(0.15, runner.cancel)
    timer.start()
    result = runner.run(argv, cwd=tmp_path)
    assert result.status == "CANCELLED" and runner.process.poll() is not None
    timer.join()
    runner = ManagedProcess()

    def guard():
        if runner.process:
            raise PermissionError("global kill")

    with pytest.raises(PermissionError, match="global kill"):
        runner.run(argv, cwd=tmp_path, guard=guard)
    assert runner.process.poll() is not None and runner not in ManagedProcess.active


def test_process_callback_failure_still_cleans_up(tmp_path):
    runner = ManagedProcess()

    def fail(pid):
        raise RuntimeError("journal unavailable")

    with pytest.raises(RuntimeError, match="journal unavailable"):
        runner.run(
            [sys.executable, "-c", "import time;time.sleep(20)"], cwd=tmp_path, on_start=fail
        )
    assert runner.process.poll() is not None


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree containment")
def test_timeout_terminates_child_process_tree(tmp_path):
    script = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)']); "
        "print(p.pid,flush=True);time.sleep(20)"
    )
    result = ManagedProcess().run([sys.executable, "-c", script], cwd=tmp_path, timeout=1)
    assert result.status == "TIMEOUT"
    pid = int(result.stdout.strip())
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 2000) == 0
        finally:
            kernel.CloseHandle(handle)


def fake_control(agent="CODEX"):
    return SimpleNamespace(
        policy=lambda a: ProviderPolicy(agent=a, preferred_transport=PREFERRED[a]),
        snapshot=lambda t: {},
    )


def test_missing_cli_and_untrusted_isolation_never_execute(monkeypatch):
    adapter = CLITransport("codex_cli", fake_control())
    monkeypatch.setattr(adapter, "command", lambda: None)
    assert adapter.detect()["install_status"] == "NOT_INSTALLED"
    assert adapter.authentication_status()["auth_state"] == "NOT_AUTHENTICATED"
    with pytest.raises(ProviderError, match="OuterBoundaryUnavailable"):
        adapter.execute(None)


def test_auth_metadata_does_not_retain_cli_output(monkeypatch):
    adapter = CLITransport("codex_cli", fake_control())
    monkeypatch.setattr(adapter, "command", lambda: ["fixture.exe"])
    monkeypatch.setattr(
        ManagedProcess,
        "run",
        lambda *a, **k: SimpleNamespace(
            exit_code=0, status="EXITED", stdout="", stderr="Logged in using ChatGPT"
        ),
    )
    assert adapter.authentication_status() == {
        "auth_state": "AUTHENTICATED",
        "billing_source": "SUBSCRIPTION",
    }
    monkeypatch.setattr(
        ManagedProcess,
        "run",
        lambda *a, **k: SimpleNamespace(
            exit_code=0, status="EXITED", stdout="Logged in using an API key", stderr=""
        ),
    )
    assert adapter.authentication_status()["billing_source"] == "UNKNOWN"


def test_grok_unverified_login_is_not_reported_as_signed_out(monkeypatch):
    from triad.day5a import native_agents

    def unavailable(command):
        raise RuntimeError("fixture unavailable")

    monkeypatch.setattr(native_agents, "grok_authentication", unavailable)
    adapter = CLITransport("grok_build_cli", fake_control("GROK"))
    monkeypatch.setattr(adapter, "command", lambda: ["fixture.exe"])
    monkeypatch.setattr(adapter, "readonly_ready", lambda: False)
    auth = adapter.authentication_status()
    assert auth["auth_state"] == "UNKNOWN"
    assert auth["billing_source"] == "UNKNOWN"
    assert "does not need to be repeated" in auth["auth_detail"]
    assert adapter.health_check().error_class == "AuthenticationStatusUnknown"
    monkeypatch.setattr(adapter, "detect", lambda: {"install_status": "INSTALLED"})
    recorded = []
    control = SimpleNamespace(
        transport=lambda tid: adapter,
        snapshot=lambda tid: {},
        ledger=SimpleNamespace(event=lambda *a, **k: None, put=lambda *a, **k: recorded.append(a)),
    )
    result = ProviderControl._refresh(control, "grok_build_cli")
    assert result["health"] == "OFFLINE"
    assert result["auth_state"] == "UNKNOWN"
    assert recorded


def test_http_transport_never_reads_legacy_env_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-env-key-must-not-be-used")
    host = fake_control()
    host.secrets = SimpleNamespace(get_secret=lambda t: None, has_secret=lambda t: False)
    adapter = HTTPTransport("openai_api", host)
    assert not adapter.adapter().key
    assert adapter.detect()["configuration"] == "NOT_CONFIGURED"


@pytest.mark.skipif(os.name != "nt", reason="Windows Credential Manager integration")
def test_windows_secret_roundtrip_redaction_and_delete():
    class TestStore(WindowsSecretStore):
        @staticmethod
        def target(name):
            return "Triad/Tests/" + name

    store = TestStore()
    name = uuid4().hex
    secret = "unit-test-credential-" + uuid4().hex
    try:
        assert not store.has_secret(name)
        store.set_secret(name, secret)
        assert store.has_secret(name) and store.get_secret(name) == secret
        assert secret not in json.dumps(redact({"nested": [secret]}))
        with pytest.raises(PermissionError):
            ensure_no_secret({"context": secret})
    finally:
        store.delete_secret(name)
    assert not store.has_secret(name)


def test_api_validation_never_reflects_raw_secret_and_no_secret_getter():
    fixture_secret = "credential-sensitive-unit-fixture"
    app.dependency_overrides[require_operator] = lambda: None
    app.dependency_overrides[service] = lambda: fake_control()
    try:
        client = TestClient(app)
        response = client.put(
            "/api/providers/transports/openai_api/credential", json={"value": [fixture_secret]}
        )
        assert response.status_code == 422 and fixture_secret not in response.text
        assert client.get("/api/providers/transports/openai_api/credential").status_code == 405
        fixture = SimpleNamespace(set_key=lambda name, value: {"configured": True})
        app.dependency_overrides[service] = lambda: fixture
        stored = client.put(
            "/api/providers/transports/openai_api/credential", json={"value": fixture_secret}
        )
        assert stored.status_code == 200 and fixture_secret not in stored.text
        assert stored.json() == {"configured": True}
        assert client.get("/settings/ai-providers").status_code == 200
    finally:
        app.dependency_overrides.clear()
