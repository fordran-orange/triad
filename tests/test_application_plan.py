"""Persistent architecture integrity and honest integration evidence."""

from pathlib import Path

import pytest
from products.triad.sequential import CurrentProposal
from products.triad.sequential_application import (
    PLAN_PATH,
    ApplicationPlan,
    current_plan,
    validate_plan,
)
from products.triad.sequential_mission import render_application
from pydantic import ValidationError
from test_sequential_planning import plan, proposal
from trading_core.product_changes import acceptance_problems, product_path
from trading_core.product_sdk import SDK_FILES
from trading_core.providers.isolation import OfflineSandbox


def test_plan_is_product_owned_but_its_validator_is_protected():
    assert product_path(PLAN_PATH) == PLAN_PATH
    with pytest.raises(PermissionError):
        product_path("app/products/triad/sequential_application.py")
    raw = proposal(value_plan=plan())
    raw["files"] = ["app/products/triad/example.py"]
    with pytest.raises(ValidationError, match="application plan"):
        CurrentProposal(**raw)


def test_current_inventory_is_not_claimed_as_a_built_application():
    application = current_plan()
    assert application.workflows[0].status == "NOT_BUILT"
    snapshot = {PLAN_PATH: application.model_dump_json()}
    root = Path(__file__).resolve().parents[1]
    for component in application.components:
        if component.owner == "triad":
            for path in component.paths:
                snapshot[path] = (root / path).read_text(encoding="utf-8")
    for connection in application.connections:
        for path in connection.tests:
            snapshot[path] = (root / path).read_text(encoding="utf-8")
    assert validate_plan(snapshot) == application


def test_connections_cannot_invent_components_or_execution_evidence():
    raw = current_plan().model_dump(mode="json")
    invalid = {
        **raw,
        "connections": [
            {
                "producer": "missing",
                "consumer": "workspace",
                "contract": "bars",
                "version": "1",
                "status": "TESTED",
                "tests": [],
            }
        ],
    }
    with pytest.raises(ValidationError):
        ApplicationPlan.model_validate(invalid)
    raw["workflows"][0]["status"] = "CONNECTED"
    with pytest.raises(ValidationError, match="tested adjacent"):
        ApplicationPlan.model_validate(raw)


def test_other_product_cannot_become_a_core_or_triad_component():
    raw = current_plan().model_dump(mode="json")
    raw["components"][0]["paths"] = ["app/products/aegis/private.py"]
    with pytest.raises(PermissionError):
        ApplicationPlan.model_validate(raw)


def test_application_panel_escapes_agent_owned_design_content():
    plan = current_plan().model_copy(update={"architecture_reasoning": "<script>bad()</script>"})
    html = render_application(plan)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Not Built" in html and "not proof" in html


def test_sdk_exports_no_host_credentials_store_or_provider_runtime():
    assert not any(
        "store" in path or "settings" in path or "providers" in path for path in SDK_FILES
    )
    image = "sha256:" + "a" * 64
    args = OfflineSandbox.create_options("fixture", image, profile="product")
    for restriction in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--ipc=none",
    ):
        assert restriction in args
    assert not any(arg.startswith(("--volume", "--mount")) for arg in args)


def test_browser_acceptance_requires_repeated_exact_executed_checks():
    required = [
        {"check_id": "click", "method": "BROWSER_TEST", "description": "Actual interaction"}
    ]
    assessed = {
        "checks": [
            {
                "check_id": "click",
                "status": "VERIFIED",
                "evidence_ids": ["first", "second"],
                "reason": "Executed exact candidate",
            }
        ]
    }
    proof = {
        "status": "PASS",
        "commit": "exact",
        "browser_status": "PASSED",
        "executed_browser_tests": 1,
    }
    assert not acceptance_problems(required, assessed, "exact", {"first": proof, "second": proof})
    assert acceptance_problems(
        required,
        assessed,
        "exact",
        {"first": {**proof, "executed_browser_tests": 0}, "second": proof},
    )
    assert acceptance_problems(
        required, assessed, "exact", {"first": {**proof, "commit": "old"}, "second": proof}
    )


def test_reviewed_environment_upgrade_preserves_existing_workspace_authority(monkeypatch):
    from types import SimpleNamespace as NS

    from trading_core import product_changes as changes
    from trading_core.intelligence.quality import Quality

    image = "sha256:" + "a" * 64
    required = (
        "app/products/triad/sequential.py",
        "app/trading_core/product_sdk.py",
        "infrastructure/product-tests.Dockerfile",
        "app/trading_core/providers/isolation.py",
    )
    old = {
        "id": "old-policy",
        "owner": "core",
        "kind": "ProductCyclePolicy",
        "workspace_profile": "product-workspace-v1",
        "order": ["CODEX", "CLAUDE", "GROK"],
        "token_policy": "TARGET",
        "workspace_evidence": ["actual vendor proofs"],
    }
    appended = []
    records = NS(
        store=NS(scope=None),
        ledger=NS(guard=lambda: None),
        get=lambda _: {"owner": "core", "files": required},
        append=lambda kind, row: appended.append(row) or "new-policy",
    )
    monkeypatch.setattr(
        Quality,
        "require_pass",
        lambda *a, **k: {"id": "qa", "tests_repeated": ["actual image " + image]},
    )
    monkeypatch.setattr(changes, "reviewed_test_image", lambda: image)
    monkeypatch.setattr(changes, "active_policy", lambda _: old)
    assert changes.upgrade_test_environment(records, "implementation", "commit") == "new-policy"
    assert appended[0]["workspace_profile"] == old["workspace_profile"]
    assert appended[0]["workspace_evidence"] == old["workspace_evidence"]
    assert appended[0]["order"] == old["order"]
    assert appended[0]["token_policy"] == "TARGET"
    assert appended[0]["previous_policy_id"] == "old-policy"
    monkeypatch.setattr(Quality, "require_pass", lambda *a, **k: {"id": "qa", "tests_repeated": []})
    with pytest.raises(PermissionError):
        changes.upgrade_test_environment(records, "implementation", "commit")
