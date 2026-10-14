"""Revocable effective grants and probe prechecks, with no production inference."""
# ruff: noqa: F811

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_day3_integration import engine  # noqa: F401
from test_day8_role_qa import MARKER, adopt_capability, definition, setup
from test_engineering import PATH, SCRIPT
from test_intelligence_capabilities import qa
from trading_core.engineering import adopt_ui_role, effective_ui_role, issue_grant
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.work import WorkItem

pytestmark = pytest.mark.core


@pytest.mark.integration
def test_overlay_preserves_raw_definition_and_revalidates_qa_and_capability(engine):
    records, run = setup(engine)
    base = definition(records)
    original = records.list("AgentDefinition")
    quality = Quality(records)
    with pytest.raises(PermissionError):
        adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    quality.review(qa(run, evidence=(MARKER,)))
    adopt_capability(records, verification_status="CLAIMED")
    with pytest.raises(PermissionError):
        adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    adopt_capability(records)
    adoption = adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    effective = Agents(records).get("CLAUDE")
    assert effective["engineering_role_adoption"] == adoption
    assert set(effective["execution_permissions"]) == set(base["execution_permissions"]) | {
        "write_code"
    }
    assert set(effective["capabilities"]) == set(base["capabilities"]) | {
        "isolated_product_ui_edit"
    }
    for key in ("authority_tier", "allowed_tools", "allowed_paths", "forbidden_paths", "budget"):
        assert effective[key] == base[key]
    assert definition(records) == base and records.list("AgentDefinition") == original
    quality.review(qa(run, evidence=(MARKER,), decision="CHANGES_REQUIRED", findings=("Revoked",)))
    assert "write_code" not in Agents(records).get("CLAUDE")["execution_permissions"]
    quality.review(qa(run, evidence=(MARKER,)))
    assert "write_code" not in Agents(records).get("CLAUDE")["execution_permissions"]
    adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    assert "write_code" in Agents(records).get("CLAUDE")["execution_permissions"]
    adopt_capability(records, status="RESTRICTED")
    assert "write_code" not in Agents(records).get("CLAUDE")["execution_permissions"]
    adopt_capability(records)
    assert "write_code" not in Agents(records).get("CLAUDE")["execution_permissions"]
    adopt_ui_role(records, run.implementation_run_id, run.change_commit)
    assert "write_code" in Agents(records).get("CLAUDE")["execution_permissions"]
    with records.store.connect() as conn:
        altered = effective_ui_role(records, base | {"purpose": "different base"}, conn=conn)
    assert "write_code" not in altered["execution_permissions"]
    assert definition(records) == base


@pytest.mark.integration
def test_grant_requires_started_authority_and_cannot_refresh_revoked_epoch(engine):
    records = Records(engine.host.store)

    def work():
        return engine.host.create(
            WorkItem(
                owner="triad",
                title="Authority fixture",
                description="Bounded",
                work_type="development",
                authority_tier=2,
                assigned_agent="CLAUDE",
                reviewer="CODEX",
                review_required=True,
                allowed_paths=(PATH,),
                allowed_tools=("read_file", "write_artifact"),
                execution_permissions=("read", "write_code"),
            )
        )

    initial = work()
    args = {"base_commit": "fixture", "files": (PATH,), "test_id": "qa", "test_script": SCRIPT}
    with pytest.raises(KeyError):
        issue_grant(records, initial, **args)
    active, _ = engine.start_work(initial)
    assert issue_grant(records, active, **args).epoch == 0
    stale, _ = engine.start_work(work())
    engine.ledger.operate("kill")
    engine.ledger.operate("resume")
    with pytest.raises(Stopped):
        issue_grant(records, stale, **args)
    assert len(records.list("EngineeringGrant")) == 1


@pytest.mark.parametrize(
    "change",
    [None, {"model": "wrong"}, {"status": "RESTRICTED"}, {"verification_status": "CLAIMED"}],
)
def test_probe_rejects_missing_current_substrate_before_creating_work(monkeypatch, change):
    path = Path(__file__).resolve().parents[1] / "tools/day8_engineering_probe.py"
    spec = importlib.util.spec_from_file_location("probe_qa", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "Records",
        lambda: SimpleNamespace(store=SimpleNamespace(settings=None), ledger=None),
    )
    monkeypatch.setattr(module, "Store", lambda *a, **k: None)
    monkeypatch.setattr(module, "ExecutionServices", lambda *a: None)

    class Control:
        def __init__(self, *_):
            pass

        def require_gate(self):
            pass

        def snapshot(self, *_):
            return {"workitem": {"actual_model": "fixture"}}

    monkeypatch.setattr(module, "ProviderControl", Control)
    capability = {
        "provider": "anthropic",
        "model": "fixture",
        "transport": "claude_code_cli",
        "capability": "isolated_text_proposal",
        "status": "AVAILABLE",
        "verification_status": "VERIFIED",
    }

    class Caps:
        def __init__(self, *_):
            pass

        def current(self):
            return [] if change is None else [{"id": "fixture", "capability": capability | change}]

        def propose(self, *_args, **_kwargs):
            pytest.fail("No proposal before valid substrate")

    monkeypatch.setattr(module, "Capabilities", Caps)
    with pytest.raises(PermissionError, match="Current verified Claude"):
        module.main()
