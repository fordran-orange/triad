"""Core-owned authority for interactive, independently reviewed product builds."""

from trading_core.intelligence.records import Records
from trading_core.product_changes import PRODUCT_ROOTS, active_policy, product_path
from trading_core.resource_policy import scope_digest
from trading_core.store import Store

PROFILE = "product-workspace-v1"
TOOLS = ("list_files", "read_file", "write_file", "delete_file", "rename_file", "run_command")
MEMBERS = {"CODEX", "CLAUDE", "GROK"}


def activate(records, implementation_id, commit):
    from trading_core.intelligence.quality import Quality

    if records.store.scope is not None:
        raise PermissionError("Workspace rollout requires Core host")
    records.ledger.guard()
    qa = Quality(records).require_pass(implementation_id, commit)
    build = records.get(implementation_id)
    evidence = set(build["evidence"]) & set(qa["evidence"])
    if build["owner"] != "core" or not all(
        any(e.startswith(PROFILE + ":" + agent + ":") for e in evidence) for agent in MEMBERS
    ):
        raise PermissionError("Independent QA must cover all three real workspace proofs")
    previous = active_policy(records)
    payload = {k: v for k, v in previous.items() if k not in {"id", "kind", "owner"}}
    payload.update(
        implementation=implementation_id,
        commit=commit,
        qa_id=qa["id"],
        workspace_profile=PROFILE,
        previous_policy_id=previous["id"],
        workspace_evidence=sorted(evidence),
    )
    return records.append("ProductCyclePolicy", payload)


def is_workspace(request):
    return set(getattr(request, "allowed_tools", ())) == set(TOOLS)


def assignment(records, work, agent):
    policy = active_policy(records)
    if (
        policy.get("workspace_profile") != PROFILE
        or agent not in MEMBERS
        or work.owner != "triad"
        or work.work_type != "development"
        or work.authority_tier != 2
        or set(work.execution_permissions) != {"read", "write_code"}
        or set(work.allowed_tools) != {"read_file", "write_artifact"}
        or not work.review_required
        or work.reviewer not in MEMBERS - {agent}
        or not work.allowed_paths
    ):
        raise PermissionError("Reviewed product workspace assignment required")
    for path in work.allowed_paths:
        product_path(path)
    return policy


def role_authority(records, work, agent):
    """Only this explicit assignment receives the reviewed product profile."""
    assignment(records, work, agent["executor_identity"])
    if agent["agent_type"] != "static" or agent["authority_tier"] != 2:
        raise PermissionError("Workspace profile is limited to existing development members")
    return {
        **agent,
        "execution_permissions": sorted(set(agent["execution_permissions"]) | {"write_code"}),
        "allowed_paths": sorted(set(agent["allowed_paths"]) | set(PRODUCT_ROOTS)),
    }


def issue(records, work, approval_id):
    if records.store.scope is not None:
        raise PermissionError("Only Core issues workspace grants")
    if work.status != "IN_PROGRESS":
        raise PermissionError("Workspace requires active implementation work")
    policy = assignment(records, work, work.assigned_agent)
    approval = records.get(approval_id)
    if (
        approval["kind"] != "ProductTurnApproval"
        or approval["owner"] != work.owner
        or approval["cycle_id"] != work.mission_id
        or approval["builder"] != work.assigned_agent
        or approval["reviewer"] != work.reviewer
        or approval["policy_id"] != policy["id"]
        or not set(approval["proposal"]["files"]) <= set(work.allowed_paths)
    ):
        raise PermissionError("Workspace must match the independently approved proposal")
    epoch = records.ledger.get("authority-" + work.work_item_id)["epoch"]
    records.ledger.guard(work.assigned_agent, work.work_item_id, epoch)
    return records.append(
        "ProductWorkspaceGrant",
        {
            "work_item_id": work.work_item_id,
            "agent": work.assigned_agent,
            "scope_digest": scope_digest(work),
            "epoch": epoch,
            "policy_id": policy["id"],
            "approval_id": approval_id,
            "base_commit": approval["base_commit"],
            "writable_files": approval["proposal"]["files"],
            "image": policy["test_image"],
            "profile": PROFILE,
        },
        owner=work.owner,
        identifier="workspace-" + work.work_item_id,
    )


def grant_for(ledger, request):
    records = Records(Store(ledger.store.settings))
    work = ledger.store.get(request.work_item_id)
    policy = assignment(records, work, request.agent_id)
    grant = records.get("workspace-" + request.work_item_id)
    ledger.guard(request.agent_id, request.work_item_id, request.control_epoch)
    if (
        grant["kind"] != "ProductWorkspaceGrant"
        or grant["owner"] != work.owner
        or grant["scope_digest"] != scope_digest(work)
        or grant["epoch"] != request.control_epoch
        or grant["agent"] != request.agent_id
        or work.assigned_agent != request.agent_id
        or work.status != "IN_PROGRESS"
        or request.mission_id != work.mission_id
        or request.role != "IMPLEMENT"
        or request.execution_permissions != ("write_code",)
        or set(request.allowed_paths) != set(work.allowed_paths)
        or not is_workspace(request)
        or grant["policy_id"] != policy["id"]
        or grant["profile"] != PROFILE
        or grant["image"] != policy["test_image"]
    ):
        raise PermissionError("Workspace request differs from its immutable host grant")
    return grant
