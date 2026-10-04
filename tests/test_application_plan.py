"""Persistent architecture integrity and honest integration evidence."""

from pathlib import Path

import pytest
from products.triad.sequential import CurrentProposal
from products.triad.sequential_application import (
    PLAN_PATH,
    ApplicationPlan,
    current_plan,
    validate_connection_proof,
    validate_plan,
)
from products.triad.sequential_mission import render_application
from pydantic import ValidationError
from test_sequential_planning import plan, proposal
from trading_core.product_changes import acceptance_problems, product_path
from trading_core.product_sdk import SDK_FILES
from trading_core.providers.isolation import OfflineSandbox


def fixture_plan():
    """Fixed validator inputs; the autonomous product's evolving plan is not a fixture."""
    return ApplicationPlan.model_validate({
        "schema_version": "triad.application.v1",
        "goal": "Fixture connected application",
        "architecture_reasoning": "One tested edge does not complete the whole chain",
        "components": [
            {"id": "workspace", "name": "Workspace", "responsibility": "User input",
             "owner": "triad", "status": "EXISTS", "paths": ["app/products/triad/static/fixture.html"]},
            {"id": "adapter", "name": "Adapter", "responsibility": "SDK input",
             "owner": "triad", "status": "EXISTS", "paths": ["app/products/triad/fixture_adapter.py"]},
            {"id": "core", "name": "Core", "responsibility": "Shared computation",
             "owner": "core", "status": "EXISTS", "paths": ["app/trading_core/product_sdk.py"]},
        ],
        "connections": [
            {"producer": "adapter", "consumer": "core", "contract": "core.product-research",
             "version": "v1", "status": "TESTED", "tests": ["tests/products/triad/test_fixture.py"]},
            {"producer": "workspace", "consumer": "adapter", "contract": "fixture.input",
             "version": "v1", "status": "PLANNED", "tests": []},
        ],
        "workflows": [{"id": "fixture-research", "user_outcome": "Fixture research",
                       "entry_point": "/triad/product", "components": ["workspace", "adapter", "core"],
                       "status": "NOT_BUILT", "next_connection": "Connect workspace to adapter"}],
        "decisions": ["This is an immutable test fixture, not the product roadmap"],
        "next_initiatives": ["Connect the missing edge"],
    })


def test_plan_is_product_owned_but_its_validator_is_protected():
    assert product_path(PLAN_PATH) == PLAN_PATH
    with pytest.raises(PermissionError):
        product_path("app/products/triad/sequential_application.py")
    raw = proposal(value_plan=plan())
    raw["files"] = ["app/products/triad/example.py"]
    with pytest.raises(ValidationError, match="application plan"):
        CurrentProposal(**raw)


def test_current_inventory_validates_without_a_fixed_product_status():
    application = current_plan()
    snapshot = {PLAN_PATH: application.model_dump_json()}
    root = Path(__file__).resolve().parents[1]
    for component in application.components:
        if component.owner == "triad" and component.status == "EXISTS":
            for path in component.paths:
                snapshot[path] = (root / path).read_text(encoding="utf-8")
    for connection in application.connections:
        if connection.status == "TESTED":
            for path in connection.tests:
                snapshot[path] = (root / path).read_text(encoding="utf-8")
    core_paths = {
        path for component in application.components if component.owner == "core"
        for path in component.paths if (root / path).is_file()
    }
    assert validate_plan(snapshot, core_paths=core_paths) == application


def test_connections_cannot_invent_components_or_execution_evidence():
    raw = fixture_plan().model_dump(mode="json")
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


def test_planned_component_and_non_discovered_helper_cannot_claim_tested_connection():
    raw = fixture_plan().model_dump(mode="json")
    raw["components"][-1]["status"] = "PLANNED"
    with pytest.raises(ValidationError, match="endpoints must exist"):
        ApplicationPlan.model_validate(raw)
    raw = fixture_plan().model_dump(mode="json")
    raw["connections"][0]["tests"] = ["tests/products/triad/helper.py"]
    with pytest.raises(ValidationError, match="product tests"):
        ApplicationPlan.model_validate(raw)


def test_connection_proof_requires_actual_passing_cases_in_each_declared_file():
    application = fixture_plan()
    path = application.connections[0].tests[0]
    for files in ({}, {path: 0}, {"tests/products/triad/test_unrelated.py": 100}):
        with pytest.raises(ValueError, match="actual passing"):
            validate_connection_proof(application, {"status": "PASS", "passed_test_files": files})
    validate_connection_proof(application, {"status": "PASS", "passed_test_files": {path: 5}})


def test_image_identity_is_stable_across_windows_and_unix_checkout(tmp_path):
    from trading_core.product_changes import image_input_bytes, test_image_digest

    roots = [tmp_path / "unix", tmp_path / "windows"]
    inputs = (
        "infrastructure/product-tests.Dockerfile",
        "requirements.lock",
        "infrastructure/product-tests.lock",
        *SDK_FILES,
    )
    for root in roots:
        for path in inputs:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                b"first\nsecond\n" if root.name == "unix" else b"first\r\nsecond\r\n"
            )
    assert test_image_digest(roots[0]) == test_image_digest(roots[1])
    assert image_input_bytes(roots[0], inputs[0]) == image_input_bytes(roots[1], inputs[0])


def test_other_product_cannot_become_a_core_or_triad_component():
    raw = fixture_plan().model_dump(mode="json")
    raw["components"][0]["paths"] = ["app/products/aegis/private.py"]
    with pytest.raises(PermissionError):
        ApplicationPlan.model_validate(raw)


def test_application_panel_escapes_agent_owned_design_content():
    plan = fixture_plan().model_copy(update={"architecture_reasoning": "<script>bad()</script>"})
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
