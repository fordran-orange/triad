"""Provider repair fixtures; no real login, inference, DB or installer execution."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from trading_core.contracts import ProviderHealth
from trading_core.providers import transports as module
from trading_core.providers.contracts import PREFERRED, ProviderPolicy
from trading_core.providers.control import ProviderControl
from trading_core.providers.transports import CLITransport
from trading_core.runtime import ProviderError


def adapter(agent="CODEX"):
    control = SimpleNamespace(
        policy=lambda a: ProviderPolicy(agent=a, preferred_transport=PREFERRED[a]),
        snapshot=lambda t: {},
    )
    return CLITransport(PREFERRED[agent], control)


@pytest.fixture
def locations(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path / "triad")
    for key, sub in (
        ("USERPROFILE", "home"),
        ("LOCALAPPDATA", "local"),
        ("APPDATA", "roaming"),
        ("PROGRAMFILES", "program"),
    ):
        monkeypatch.setenv(key, str(tmp_path / sub))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    return tmp_path


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture")
    return str(path)


def test_durable_codex_precedes_desktop_and_old_prefix(locations, monkeypatch):
    node = touch(locations / "program/nodejs/node.exe")
    script = touch(locations / "triad/data/provider-cli/node_modules/@openai/codex/bin/codex.js")
    touch(locations / "triad/data/temp/provider-cli/node_modules/@openai/codex/bin/codex.js")
    desktop = touch(locations / "local/OpenAI/Codex/bin/version/codex.exe")
    monkeypatch.setattr(
        module.shutil, "which", lambda name: desktop if name == "codex.exe" else None
    )
    assert adapter().command() == [node, script]


def test_stale_path_finds_desktop_but_mismatch_never_ready(locations, monkeypatch):
    desktop = touch(locations / "local/OpenAI/Codex/bin/version/codex.exe")
    a = adapter()
    assert a.command() == [desktop]
    monkeypatch.setattr(
        module.ManagedProcess,
        "run",
        lambda *a, **k: SimpleNamespace(
            exit_code=0, status="EXITED", stdout="codex-cli wrong-version"
        ),
    )
    assert a.detect()["compatibility_status"] == "VERSION_MISMATCH"
    monkeypatch.setattr(
        a, "authentication_status", lambda: pytest.fail("version drift must block login probe")
    )
    assert a.cli_ready() is False
    assert a.health_check().status == "VERSION_MISMATCH"
    with pytest.raises(ValueError, match="version mismatch"):
        a.authenticate()


def test_native_claude_does_not_require_node(locations):
    exe = touch(
        locations / "triad/data/provider-cli/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    )
    assert adapter("CLAUDE").command() == [exe]


def test_legacy_pinned_grok_fallback_and_explicit_node(locations):
    node = touch(locations / "program/nodejs/node.exe")
    script = touch(
        locations / "triad/data/temp/provider-cli/node_modules/@xai-official/grok/bin/grok"
    )
    assert adapter("GROK").command() == [node, script]


def test_missing_install_blocks_login_instead_of_auth_failure(locations):
    a = adapter()
    assert a.detect()["install_status"] == "NOT_FOUND"
    assert a.authentication_status()["auth_state"] == "NOT_FOUND"
    with pytest.raises(ValueError, match="Install the supported CLI"):
        a.authenticate()


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        ({"install_status": "NOT_FOUND"}, "NOT_FOUND"),
        ({"install_status": "NOT_INSTALLED"}, "NOT_FOUND"),
        (
            {"install_status": "INSTALLED", "compatibility_status": "VERSION_MISMATCH"},
            "VERSION_MISMATCH",
        ),
    ],
)
def test_setup_state_takes_precedence_over_stale_auth(snapshot, expected):
    state = {"auth_state": "NOT_AUTHENTICATED", "error": "OuterBoundaryUnavailable", **snapshot}
    assert ProviderControl.readiness_state(state) == expected
    assert not ProviderControl.proven({**state, "auth_state": "AUTHENTICATED", "error": None})


def test_missing_refresh_skips_auth_and_invalidates_previous_evidence():
    a = SimpleNamespace(
        agent="CODEX",
        transport_type="CLI",
        detect=lambda: {"install_status": "NOT_FOUND", "executable": None},
        authentication_status=lambda: pytest.fail("missing executable has no authentication test"),
        capabilities=lambda: pytest.fail("missing executable has no capability probe"),
    )
    recorded = []
    control = ProviderControl.__new__(ProviderControl)
    control.transport = lambda tid: a
    control.snapshot = lambda tid: {
        "executable": ["old.exe"],
        "test": {"success": True},
        "workitem": {"success": True},
    }
    control.ledger = SimpleNamespace(
        event=lambda *a, **k: None, put=lambda *a, **k: recorded.append(a)
    )
    state = control._refresh("codex_cli")
    assert state["health"] == state["auth_state"] == "NOT_FOUND"
    assert state["test"] is state["workitem"] is None


def test_context_workspace_does_not_enable_codex_implementation(monkeypatch):
    a = adapter()
    monkeypatch.setattr(a, "readonly_ready", lambda: True)
    request = SimpleNamespace(
        role="IMPLEMENT",
        context_packet={"_core_execution": {"workspace": "forged"}},
        execution_permissions=("write_code",),
    )
    with pytest.raises(ProviderError, match="OuterBoundaryUnavailable"):
        a.execute(request)
    caps = a.capabilities()
    assert caps["granted"] == ["read_supplied_files"]
    assert "shell_execution" not in caps["granted"]


def test_claude_implementation_uses_existing_isolated_grant_path(monkeypatch):
    a = adapter("CLAUDE")
    request = SimpleNamespace(
        role="IMPLEMENT", context_packet={"_core_execution": {"workspace": "ignored"}}
    )
    observed = []
    monkeypatch.setattr(a, "_execute_isolated", lambda req: observed.append(req))
    a.execute(request)
    assert observed == [request]


def test_legacy_auth_failed_health_still_valid():
    assert (
        ProviderHealth(
            agent="LOCAL_QWEN", provider="ollama", model="qwen3:4b", status="AUTH_FAILED"
        ).status
        == "AUTH_FAILED"
    )


@pytest.mark.parametrize(
    "detected",
    [
        {"install_status": "UNAVAILABLE", "compatibility_status": "VERIFIED"},
        {"install_status": "DETECTION_FAILED", "compatibility_status": "VERIFIED"},
        {"install_status": "INSTALLED", "compatibility_status": "NOT_VERIFIED"},
    ],
)
def test_failed_detection_cannot_reuse_cached_ready_or_auth(monkeypatch, detected):
    a = adapter()
    a._readonly_ready = True
    monkeypatch.setattr(a, "detect", lambda: detected)
    monkeypatch.setattr(
        a, "authentication_status", lambda: pytest.fail("unverified install must stop before auth")
    )
    assert a.health_check().status == "UNAVAILABLE"


def test_ui_has_setup_guidance_and_keeps_api_separate():
    text = (Path(module.__file__).parents[1] / "static/providers.html").read_text()
    assert "t.install_status!=='INSTALLED'||t.compatibility_status==='VERSION_MISMATCH'" in text
    assert "tools/install_provider_clis.ps1" in text
    assert "API credential:" in text and "No API key is needed" in text
