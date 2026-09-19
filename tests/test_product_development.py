"""Product evidence is separate, scoped and cannot merge without independent QA."""

# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from products.triad.development import Development
from products.triad.development_api import development
from products.triad.development_contracts import ProductProposal
from products.triad.server import app
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.contracts import ImplementationRun
from trading_core.store import Store
from trading_core.work import WorkItem

pytestmark = pytest.mark.integration


def service(engine):
    return Development(Store(engine.host.store.settings, scope="triad"), engine.git)


def proposal(**updates):
    return ProductProposal(
        **{
            "candidate_id": "candidate",
            "title": "Bounded operator guide",
            "problem": "Missing explanation",
            "product_area": "workflow",
            "evidence": ["source"],
            "proposed_change": "Clarify observed workflow",
            "user_value": "Clarity",
            "technical_value": "Reproducibility",
            "expected_benefit": "Less ambiguity",
            "possible_downside": "Documentation maintenance",
            "affected_components": ["docs/improvements"],
            "risk_class": "LOW",
            "reversibility": "Git revert",
            "test_plan": ["Validate exact sources"],
            "QA_plan": ["Separate reviewer"],
            "rollback_plan": "Reviewed Git revert",
            "estimated_effort": "small",
            "permissions_required": ["write_docs"],
            "required_capabilities": ["structured_output", "isolated_text_proposal"],
            "recommended_agent": "CLAUDE",
            "specialist": "existing agent sufficient",
            **updates,
        }
    )


def test_approval_retains_authority_ceiling(engine):
    dev = service(engine)
    assert dev.approve("mission", proposal()).max_files == 3
    for updates in (
        {"risk_class": "HIGH"},
        {"permissions_required": ["shell"]},
        {"affected_components": ["app/products/p2p"]},
        {"required_capabilities": []},
        {"specialist": "new specialist agent recommended"},
    ):
        with pytest.raises(PermissionError):
            dev.approve("mission", proposal(**updates))
    engine.ledger.operate("kill")
    with pytest.raises(PermissionError):
        dev.approve("mission", proposal())


def test_scoped_dashboard_and_artifact_fail_closed(engine):
    dev = service(engine)
    dev.record("ProductCycle", "triad-mission", status="INSPECTING")
    dev.canonical.append("ProductCycle", {"mission_id": "private"}, owner="p2p")
    assert [r["mission_id"] for r in dev.dashboard()["records"]["ProductCycle"]] == [
        "triad-mission"
    ]
    with pytest.raises(KeyError):
        dev.artifact(".env")
    with dev.host.store.connect() as c:
        c.execute(
            "INSERT INTO core.artifact_owners VALUES ('docs/improvements/foreign.md','p2p','fixture')"
        )
    with pytest.raises(PermissionError):
        dev.check_ownership([SimpleNamespace(path="docs/improvements/FOREIGN.md")])
    with pytest.raises(PermissionError):
        Development(engine.host.store, engine.git)


def test_interrupted_build_never_replays(engine, monkeypatch):
    dev = service(engine)
    dev.record("ProductBuildCheckpoint", "interrupted", phase="ISOLATED")
    monkeypatch.setattr(
        dev, "inspect", lambda mission: pytest.fail("Must not replay uncertain execution")
    )
    with pytest.raises(PermissionError, match="reconciliation"):
        dev.run("interrupted", operator_authorized=True)


def test_missing_qa_blocks_merge_before_git(engine, monkeypatch):
    dev = service(engine)
    work = dev.host.create(
        WorkItem(
            owner="triad",
            assigned_agent="CLAUDE",
            title="QA gate probe",
            description="Bounded independent test",
        )
    )
    build = ImplementationRun(
        owner="triad",
        work_item_id=work.work_item_id,
        builder="CLAUDE",
        provider="anthropic",
        model="fixture",
        transport="fixture",
        base_commit="base",
        change_commit="change",
        files=("docs/improvements/a.md",),
        tests=("test",),
        evidence=("source",),
    )
    dev.quality.implementation(build)
    monkeypatch.setattr(dev.git, "merge", lambda *args: pytest.fail("Missing QA reached Git merge"))
    with pytest.raises(PermissionError, match="independent QA"):
        dev.merge(
            "mission",
            proposal(),
            {
                "work_item_id": work.work_item_id,
                "implementation_id": build.implementation_run_id,
                "git": {"change_commit": "change"},
            },
            None,
        )


def test_readable_lifecycle_assets_and_empty_api(engine):
    dev = service(engine)
    app.dependency_overrides[development] = lambda: dev
    try:
        client = TestClient(app)
        assert client.get("/triad/development").status_code == 200
        assert "textContent" in client.get("/triad/assets/development.js").text
        result = client.get("/triad/api/development")
        assert result.status_code == 200 and result.json()["records"]["ProductBuild"] == []
        assert (
            client.get("/triad/api/development/artifact", params={"path": "../.env"}).status_code
            == 404
        )
    finally:
        app.dependency_overrides.clear()


def test_legacy_real_stage_cannot_bypass_separate_qa(engine):
    with pytest.raises(PermissionError, match="separate build and QA"):
        engine.stage("CODEX", "legacy", "REAL", {})
