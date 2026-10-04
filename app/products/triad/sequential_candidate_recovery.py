"""Retain a proved unmerged candidate as advisory material for a fresh approval."""

import hashlib
import json
import re
import subprocess

from pydantic import ValidationError
from trading_core.product_changes import ProductGit
from trading_core.product_workspace_grant import PROFILE
from trading_core.resource_policy import scope_digest

from products.triad.sequential_application import (
    PLAN_PATH,
    WORKFLOW_ERROR,
    WORKFLOW_PATTERN,
    ApplicationContribution,
    ApplicationPlan,
    contributed_workflow,
)
from products.triad.sequential_recovery import require

NATIVE_IDENTITY_ERROR = "Retained native run identity differs"
CHANGED_RESULT_STATUSES = frozenset(
    {
        "CODE_CHANGE",
        "DOCUMENTATION_CHANGE",
        "TEST_ADDITION",
        "BUG_FIX",
        "ARCHITECTURAL_IMPROVEMENT",
        "PERFORMANCE_IMPROVEMENT",
    }
)


def retain_application_candidate(
    flow, mission, agent, prior, work, checkpoint, conn, *, qa_feedback=None
):
    from products.triad.sequential import Patch

    daily = flow.s.daily
    from products.triad.sequential import REVIEWERS

    require(
        work.authority_tier == 2
        and work.review_required
        and work.reviewer == REVIEWERS[agent]
        and set(work.execution_permissions) == {"read", "write_code"}
        and set(work.allowed_tools) == {"read_file", "write_artifact"},
        "Retained candidate requires the original workspace assignment",
    )
    grant = daily.product.get("workspace-" + work.work_item_id, conn=conn)
    require(
        grant["kind"] == "ProductWorkspaceGrant"
        and grant["owner"] == "triad"
        and grant["agent"] == agent
        and grant["work_item_id"] == work.work_item_id
        and grant["scope_digest"] == scope_digest(work)
        and grant["epoch"] == prior["control_epoch"]
        and grant["policy_id"] == flow.policy["id"]
        and grant["profile"] == PROFILE
        and grant["base_commit"] == checkpoint["git"]["base_commit"],
        "Retained candidate workspace authority differs",
    )
    approved = daily.host.get(grant["approval_id"], conn=conn)
    require(
        approved["kind"] == "ProductTurnApproval"
        and approved["owner"] == "triad"
        and approved["cycle_id"] == mission
        and approved["builder"] == agent
        and approved["reviewer"] == work.reviewer
        and approved["policy_id"] == flow.policy["id"]
        and approved["base_commit"] == grant["base_commit"]
        and approved["proposal"]["files"] == grant["writable_files"],
        "Retained candidate proposal authority differs",
    )
    records = {}
    for kind in ("AgentRunRequest", "AgentRunResult"):
        rows = conn.execute(
            "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind=%s "
            "AND work_item_id=%s",
            (kind, work.work_item_id),
        ).fetchall()
        require(len(rows) == 1, "Unambiguous retained native records required")
        records[kind] = rows[0]["payload"]
    request, result = records["AgentRunRequest"], records["AgentRunResult"]
    require(
        all(
            request.get(k) == v
            for k, v in {
                "work_item_id": work.work_item_id,
                "mission_id": mission,
                "agent_id": agent,
                "role": "IMPLEMENT",
                "control_epoch": prior["control_epoch"],
            }.items()
        )
        and isinstance(request.get("run_id"), str)
        and bool(request["run_id"])
        and result.get("run_id") == request["run_id"]
        and result.get("status") in CHANGED_RESULT_STATUSES
        and len(result.get("analysis_artifacts", [])) == 1,
        NATIVE_IDENTITY_ERROR,
    )
    patch = Patch.model_validate_json(result["analysis_artifacts"][0])
    events = conn.execute(
        "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind='Event' "
        "AND work_item_id=%s",
        (work.work_item_id,),
    ).fetchall()
    evidence = [
        r["payload"] for r in events if r["payload"].get("event") == "native_executor_evidence"
    ]
    require(
        len(evidence) == 1
        and evidence[0].get("run_id") == request["run_id"]
        and evidence[0].get("boundary") == "DOCKER_PRODUCT_WORKSPACE"
        and type(evidence[0].get("denied_operations", evidence[0].get("denials"))) is int
        and evidence[0].get("denied_operations", evidence[0].get("denials")) >= 0
        and not any(r["payload"].get("event") == "provider_failed" for r in events),
        "Retained candidate requires a completed native workspace export",
    )
    git = ProductGit(grant["writable_files"], root=flow.root)
    metadata = dict(checkpoint["git"])
    require(checkpoint["phase"] == "ISOLATED", "Retained candidate phase differs")
    require(
        not git.git("status", "--porcelain", cwd=metadata["worktree"]),
        "Retained candidate is dirty",
    )
    commit = git.git("rev-parse", "HEAD", cwd=metadata["worktree"])
    require(
        git.git("rev-list", "--parents", "-n", "1", commit, cwd=metadata["worktree"]).split()
        == [commit, metadata["base_commit"]],
        "Retained candidate must contain exactly its original single build commit",
    )
    metadata["change_commit"] = commit
    actual = git.verify(metadata)
    require(
        set(actual["files"]) == {f.path for f in patch.files}
        and len(patch.files) == len(actual["files"]),
        "Retained candidate file manifest differs from the native export",
    )
    for change in patch.files:
        # Git may materialize CRLF on Windows; compare the same universal-newline
        # snapshot the workspace originally received, without trimming content.
        content = change.content
        normalized = (
            content.replace("\r\n", "\n").replace("\r", "\n") if content is not None else None
        )
        require(
            actual["sources"][change.path] == normalized,
            "Retained candidate content differs from its native export",
        )
        exists = git.git(
            "ls-tree",
            "--name-only",
            metadata["base_commit"],
            "--",
            change.path,
            cwd=metadata["worktree"],
        )
        original = None
        if exists:
            # GitChanges.git strips stdout. Read original bytes for exact hashes.
            raw = subprocess.check_output(
                ["git", "show", metadata["base_commit"] + ":" + change.path],
                cwd=metadata["worktree"],
            )
            original = raw.decode().replace("\r\n", "\n").replace("\r", "\n")
        require(
            change.original_sha256
            == (hashlib.sha256(original.encode()).hexdigest() if original is not None else None),
            "Retained candidate original source hash differs",
        )
    require(
        PLAN_PATH in actual["sources"] and actual["sources"][PLAN_PATH] is not None,
        "Retained application plan required",
    )
    try:
        plan = ApplicationPlan.model_validate(json.loads(actual["sources"][PLAN_PATH]))
    except ValidationError as exc:
        require(
            prior["failure_code"] == "ValidationError",
            "Not the recorded application format failure",
        )
        require(
            str(exc)[:500] == prior["failures"][-1]["message"],
            "Retained application failure differs",
        )
        feedback = exc.errors(include_input=False, include_url=False, include_context=False)
    else:
        if qa_feedback is not None:
            # The caller has bound this feedback to canonical independent QA of
            # this exact native export. It grants no new scope or approval.
            return {
                "agent": agent,
                "commit": commit,
                "base_commit": metadata["base_commit"],
                "native_run_id": request["run_id"],
                "files": [f.model_dump(mode="json") for f in patch.files],
                "snapshot_sha256": hashlib.sha256(
                    json.dumps(actual["sources"], sort_keys=True).encode()
                ).hexdigest(),
                "independent_qa": qa_feedback,
                "authority": "Advisory unmerged candidate. Correct the actual QA findings through a current approved workspace; fresh tests and independent QA remain mandatory.",
            }
        require(
            prior["failure_code"] == "ValueError"
            and prior["failures"][-1]["message"] == WORKFLOW_ERROR,
            "Retained candidate is not the recorded application reference failure",
        )
        contribution = ApplicationContribution.model_validate(
            approved["proposal"]["value_plan"]["application_contribution"]
        )
        require(
            not re.fullmatch(WORKFLOW_PATTERN, contribution.workflow),
            "Only a historical prose workflow may use this recovery",
        )
        workflow = contributed_workflow(plan, contribution)
        feedback = [
            {
                "type": "workflow_reference",
                "loc": ["application_contribution", "workflow"],
                "msg": "Use the stable workflow identifier instead of a prose journey description",
                "expected_workflow_id": workflow.id,
            }
        ]
    return {
        "agent": agent,
        "commit": commit,
        "base_commit": metadata["base_commit"],
        "native_run_id": request["run_id"],
        "files": [f.model_dump(mode="json") for f in patch.files],
        "snapshot_sha256": hashlib.sha256(
            json.dumps(actual["sources"], sort_keys=True).encode()
        ).hexdigest(),
        "application_format_errors": feedback,
        "prior_denied_operations": evidence[0].get("denied_operations", evidence[0].get("denials")),
        "authority": "Advisory unmerged material only. Requires a fresh proposal, independent approval, current-baseline workspace, executed tests and independent QA.",
    }
