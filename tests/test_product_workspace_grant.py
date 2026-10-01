"""Explicit workspace authority cannot be obtained from an ordinary review."""

from types import SimpleNamespace as NS

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core import product_workspace_grant as grants
from trading_core.work import WorkItem


def work(**updates):
    values = {
        "owner": "triad",
        "title": "Product build",
        "description": "Implement reviewed product behavior",
        "work_type": "development",
        "assigned_agent": "CODEX",
        "reviewer": "CLAUDE",
        "authority_tier": 2,
        "allowed_tools": ("read_file", "write_artifact"),
        "allowed_paths": (
            "app/products/triad/product_app.py",
            "tests/products/triad/test_feature.py",
        ),
        "execution_permissions": ("read", "write_code"),
        "review_required": True,
    }
    values.update(updates)
    return WorkItem(**values).model_copy(update={"status": "IN_PROGRESS"})


def fixture(monkeypatch):
    item = work()
    rows = {
        "approval": {
            "kind": "ProductTurnApproval",
            "owner": "triad",
            "cycle_id": item.mission_id,
            "builder": "CODEX",
            "reviewer": "CLAUDE",
            "policy_id": "policy",
            "base_commit": "base",
            "proposal": {"files": list(item.allowed_paths)},
        }
    }
    policy = {
        "id": "policy",
        "workspace_profile": grants.PROFILE,
        "test_image": "sha256:" + "a" * 64,
    }
    store = NS(scope=None, settings=None, get=lambda _: item)
    ledger = NS(store=store, get=lambda _: {"epoch": 3}, guard=lambda *a: None)

    def append(kind, payload, owner, identifier):
        rows[identifier] = {**payload, "kind": kind, "owner": owner, "id": identifier}
        return identifier

    records = NS(store=store, ledger=ledger, get=lambda i: rows[i], append=append)
    monkeypatch.setattr(grants, "active_policy", lambda _: policy)
    monkeypatch.setattr(grants, "Store", lambda _: store)
    monkeypatch.setattr(grants, "Records", lambda _: records)
    request = NS(
        work_item_id=item.work_item_id,
        mission_id=item.mission_id,
        agent_id="CODEX",
        control_epoch=3,
        role="IMPLEMENT",
        execution_permissions=("write_code",),
        allowed_tools=grants.TOOLS,
        allowed_paths=item.allowed_paths,
    )
    return records, item, request, rows, policy


def test_exact_host_grant_and_policy_revalidation(monkeypatch):
    records, item, request, _rows, policy = fixture(monkeypatch)
    key = grants.issue(records, item, "approval")
    assert grants.grant_for(records.ledger, request)["id"] == key
    policy["id"] = "replacement"
    with pytest.raises(PermissionError):
        grants.grant_for(records.ledger, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("agent_id", "GROK"),
        ("role", "REVIEW"),
        ("execution_permissions", ("read",)),
        ("control_epoch", 4),
        ("mission_id", "other"),
        ("allowed_tools", ("read_file",)),
        ("allowed_paths", ("products/triad/extra.txt",)),
    ],
)
def test_request_cannot_expand_or_repurpose_grant(monkeypatch, field, value):
    records, item, request, _, _ = fixture(monkeypatch)
    grants.issue(records, item, "approval")
    setattr(request, field, value)
    with pytest.raises(PermissionError):
        grants.grant_for(records.ledger, request)


@pytest.mark.parametrize(
    "updates",
    [
        {"owner": "aegis"},
        {"reviewer": "CODEX"},
        {"authority_tier": 1},
        {"review_required": False},
        {"allowed_paths": ("app/trading_core/api.py",)},
        {"allowed_paths": ("app/products/triad/sequential.py",)},
        {"execution_permissions": ("read",)},
    ],
)
def test_product_authority_boundary(monkeypatch, updates):
    records, _, _, _, _ = fixture(monkeypatch)
    with pytest.raises((PermissionError, ValueError)):
        grants.assignment(records, work(**updates), "CODEX")


def test_scoped_product_cannot_issue_grant(monkeypatch):
    records, item, _, _, _ = fixture(monkeypatch)
    records.store.scope = "triad"
    with pytest.raises(PermissionError):
        grants.issue(records, item, "approval")


def test_profile_must_be_explicitly_activated(monkeypatch):
    records, item, _, _, policy = fixture(monkeypatch)
    del policy["workspace_profile"]
    with pytest.raises(PermissionError):
        grants.assignment(records, item, "CODEX")


def test_approval_for_another_builder_rejected(monkeypatch):
    records, item, _, rows, _ = fixture(monkeypatch)
    rows["approval"]["builder"] = "CLAUDE"
    with pytest.raises(PermissionError):
        grants.issue(records, item, "approval")


@pytest.mark.integration
@pytest.mark.parametrize(
    "agent,reviewer", [("CODEX", "CLAUDE"), ("CLAUDE", "GROK"), ("GROK", "CODEX")]
)
def test_persisted_assignment_grant_and_dispatch(monkeypatch, engine, agent, reviewer):  # noqa: F811
    from test_intelligence_routing import requirements, setup_routing
    from trading_core.execution import ExecutionServices

    router, records = setup_routing(engine)
    policy = {
        "id": "profile-policy",
        "workspace_profile": grants.PROFILE,
        "test_image": "sha256:" + "a" * 64,
    }
    monkeypatch.setattr(grants, "active_policy", lambda _: policy)
    item = work(assigned_agent=agent, reviewer=reviewer).model_copy(
        update={"assigned_agent": None, "status": "CREATED"}
    )
    req = requirements(
        role="IMPLEMENT", preferred_agent=agent, execution_profile="product_workspace"
    )
    assigned = router.create(item, req)
    service = ExecutionServices(router.store, engine.git)
    assigned, _ = service.start_work(assigned)
    approval = records.append(
        "ProductTurnApproval",
        {
            "cycle_id": assigned.mission_id,
            "builder": agent,
            "reviewer": reviewer,
            "policy_id": policy["id"],
            "base_commit": "fixture-base",
            "proposal": {"files": list(assigned.allowed_paths)},
        },
        owner="triad",
    )
    grants.issue(records, assigned, approval)
    request = NS(
        work_item_id=assigned.work_item_id,
        mission_id=assigned.mission_id,
        agent_id=agent,
        control_epoch=service.ledger.get("authority-" + assigned.work_item_id)["epoch"],
        role="IMPLEMENT",
        allowed_tools=grants.TOOLS,
        allowed_paths=assigned.allowed_paths,
        execution_permissions=("write_code",),
    )
    assert grants.grant_for(service.ledger, request)["approval_id"] == approval
    selected = router.validate_execution(
        request, NS(transport_id=router.control.policy(agent).preferred_transport)
    )
    assert selected["executor"] == agent
