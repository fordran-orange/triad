"""Installation churn never silently changes an in-flight executable or grants."""

from types import SimpleNamespace

import pytest
from trading_core.providers import discovery
from trading_core.providers.contracts import ProviderPolicy
from trading_core.providers.process import ManagedProcess
from trading_core.providers.transports import CLITransport
from trading_core.runtime import ProviderError

pytestmark = pytest.mark.triad


def test_broken_preferred_install_falls_back_and_operation_is_pinned(tmp_path, monkeypatch):
    bad, good, newer = [tmp_path / n for n in ("bad.exe", "good.exe", "new.exe")]
    for p in (bad, good, newer):
        p.write_text(p.name)
    choices = [[str(bad)], [str(good)]]
    monkeypatch.setattr(discovery, "candidates", lambda _: choices)
    monkeypatch.setattr(
        ManagedProcess,
        "run",
        lambda self, argv, **kw: SimpleNamespace(
            exit_code=1 if argv[0] == str(bad) else 0, status="EXITED", stdout="codex-cli 0.156.0"
        ),
    )
    transport = CLITransport(
        "codex_cli",
        SimpleNamespace(
            policy=lambda _: ProviderPolicy(agent="CODEX", preferred_transport="codex_cli")
        ),
    )
    assert transport.command() == [str(good)]
    assert transport.detect()["compatibility_status"] == "CANDIDATE"
    choices[:] = [[str(newer)]]
    assert transport.command() == [str(good)]
    transport.assert_identity()
    good.write_text("replaced installation")
    with pytest.raises(ProviderError, match="ExecutableChanged"):
        transport.assert_identity()


@pytest.mark.parametrize(
    "agent,version",
    [("CODEX", "codex-cli 99.0.0"), ("GROK", "grok garbage"), ("CLAUDE", "3.0.0 (Claude Code)")],
)
def test_unknown_protocol_family_is_not_a_compatible_candidate(agent, version):
    assert not discovery.compatible(agent, version)


def test_assignment_never_silently_switches_to_a_new_verified_model(monkeypatch):
    from trading_core.intelligence.capabilities import Capabilities
    from trading_core.intelligence.routing import Routing

    decision = {
        "kind": "CapabilityRoutingDecision",
        "decision": "ALLOW",
        "requirements": {"role": "REVIEW", "context_chars": 0, "reason": "fixture"},
        "selected": {
            "agent_id": "CODEX",
            "executor": "CODEX",
            "transport": "codex_cli",
            "model": "old-model",
        },
    }
    routing = Routing.__new__(Routing)
    routing.records = SimpleNamespace(get=lambda _: decision)
    routing.store = SimpleNamespace(get=lambda _: object())
    routing.agents = SimpleNamespace(get=lambda _: object())
    routing._candidate = lambda *a: {"eligible": True, "model": "new-model"}
    monkeypatch.setattr(Capabilities, "__init__", lambda self, records=None: None)
    monkeypatch.setattr(Capabilities, "current", lambda _: [])
    with pytest.raises(PermissionError, match="fresh assignment"):
        routing.validate_execution(
            SimpleNamespace(work_item_id="fixture", role="REVIEW", agent_id="CODEX"),
            SimpleNamespace(transport_id="codex_cli"),
        )


def test_daily_preflight_checks_late_builder_before_inspection(monkeypatch):
    from products.triad.daily_development import DailyDevelopment
    from trading_core.intelligence.capabilities import Capabilities

    daily = DailyDevelopment.__new__(DailyDevelopment)
    checks = []

    def candidate(agent, work, requirements, versions):
        checks.append(requirements.role)
        return {
            "eligible": requirements.role != "IMPLEMENT",
            "exclusions": ["Writer compatibility check required"]
            if requirements.role == "IMPLEMENT"
            else [],
        }

    daily.routing = SimpleNamespace(
        records=None,
        control=SimpleNamespace(monitor_connections=lambda: None),
        agents=SimpleNamespace(get=lambda name: {}),
        _candidate=candidate,
    )
    daily.record = lambda *a, **kw: None
    monkeypatch.setattr(Capabilities, "__init__", lambda self, records=None: None)
    monkeypatch.setattr(Capabilities, "current", lambda self: [])
    with pytest.raises(PermissionError, match="CLAUDE.*implementation.*compatibility"):
        daily.readiness("fixture")
    assert checks.count("IMPLEMENT") == 1
    assert len(checks) == 10
