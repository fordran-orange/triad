"""Real isolated commits and disposable database proof; no provider calls."""

# ruff: noqa: F811
import hashlib
import json
from pathlib import Path

import pytest
from products.triad.sequential_application import PLAN_PATH, ApplicationPlan
from products.triad.sequential_recovery import resume_patch_failure
from pydantic import ValidationError
from test_day3_integration import engine  # noqa: F401
from test_sequential_patch_recovery import blocked, totals  # noqa: F401
from trading_core.cycle_records import CycleRecord
from trading_core.product_changes import ProductFileChange, ProductGit
from trading_core.product_workspace_grant import PROFILE
from trading_core.resource_policy import scope_digest
from trading_core.work import State, WorkItem

pytestmark = pytest.mark.integration


@pytest.fixture
def candidate(blocked, engine):
    b = blocked
    plan = {
        "schema_version": "triad.application.v1",
        "goal": "Fixture application",
        "architecture_reasoning": "Fixture only",
        "components": [
            {
                "id": "workspace",
                "name": "Workspace",
                "responsibility": "Fixture",
                "owner": "triad",
                "status": "PLANNED",
                "paths": [PLAN_PATH],
            }
        ],
        "connections": [],
        "workflows": [
            {
                "id": "workspace",
                "user_outcome": "Fixture",
                "entry_point": "/triad/product",
                "components": ["workspace"],
                "status": "NOT_BUILT",
                "next_connection": "Build fixture",
            }
        ],
        "decisions": [],
        "next_initiatives": ["Build fixture"],
    }
    source = json.dumps(plan)
    path = Path(engine.git.root) / PLAN_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    engine.git.git("add", "--", PLAN_PATH)
    engine.git.git("commit", "-m", "Application fixture baseline")
    base = engine.git.git("rev-parse", "HEAD")
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=b.cycle.cycle_id,
            parent_work_item_id=b.cycle.parent_work_item_id,
            assigned_agent="CODEX",
            work_type="development",
            title="Workspace fixture",
            description="No provider execution",
            authority_tier=2,
            allowed_paths=(PLAN_PATH,),
            allowed_tools=("read_file", "write_artifact"),
            execution_permissions=("read", "write_code"),
            review_required=True,
            reviewer="CLAUDE",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture")
    b.host.ledger.reserve("CODEX", work.work_item_id, improvement=True, day=b.day)
    git = ProductGit((PLAN_PATH,), root=engine.git.root, worktrees=engine.git.worktrees)
    metadata = git.isolate(work.work_item_id, "CODEX")
    plan["components"][0]["status"] = "IMPLEMENTED"
    content = json.dumps(plan)
    patch = {
        "files": [
            {
                "path": PLAN_PATH,
                "operation": "WRITE",
                "content": content,
                "original_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        ]
    }
    git.apply(metadata, [ProductFileChange(**patch["files"][0])])
    git.commit(metadata, "CODEX")
    try:
        ApplicationPlan.model_validate(plan)
    except ValidationError as exc:
        failure = str(exc)[:500]
    approval = b.host.append(
        "ProductTurnApproval",
        {
            "cycle_id": b.cycle.cycle_id,
            "builder": "CODEX",
            "reviewer": "CLAUDE",
            "policy_id": "fixture",
            "base_commit": base,
            "proposal": {"files": [PLAN_PATH]},
        },
        owner="triad",
    )
    b.host.append(
        "ProductWorkspaceGrant",
        {
            "profile": PROFILE,
            "work_item_id": work.work_item_id,
            "agent": "CODEX",
            "scope_digest": scope_digest(work),
            "epoch": b.cycle.control_epoch,
            "policy_id": "fixture",
            "base_commit": base,
            "approval_id": approval,
            "writable_files": [PLAN_PATH],
        },
        owner="triad",
        identifier="workspace-" + work.work_item_id,
    )
    b.host.append(
        "ProductBuildCheckpoint",
        {
            "mission_id": b.cycle.cycle_id,
            "work_item_id": work.work_item_id,
            "phase": "ISOLATED",
            "git": {k: v for k, v in metadata.items() if k != "change_commit"},
        },
        owner="triad",
    )
    b.host.append(
        "ProductBuildFailure",
        {
            "mission_id": b.cycle.cycle_id,
            "work_item_id": work.work_item_id,
            "reason": failure,
            "error_class": "ValidationError",
        },
        owner="triad",
    )
    b.host.ledger.put(
        "AgentRunRequest",
        {
            "run_id": "candidate-native-run",
            "work_item_id": work.work_item_id,
            "mission_id": b.cycle.cycle_id,
            "agent_id": "CODEX",
            "role": "IMPLEMENT",
            "control_epoch": b.cycle.control_epoch,
        },
        work_id=work.work_item_id,
    )
    b.host.ledger.put(
        "AgentRunResult",
        {
            "run_id": "candidate-native-run",
            "status": "CODE_CHANGE",
            "analysis_artifacts": [json.dumps(patch)],
        },
        work_id=work.work_item_id,
    )
    b.host.ledger.event(
        "native_executor_evidence",
        work.work_item_id,
        run_id="candidate-native-run",
        boundary="DOCKER_PRODUCT_WORKSPACE",
        denied_operations=0,
    )
    prior = b.daily.current(b.cycle.cycle_id)
    data = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
    data.update(
        failure_code="ValidationError", failures=[{"code": "ValidationError", "message": failure}]
    )
    b.host.append(
        "CycleRecord", CycleRecord.model_validate(data).model_dump(mode="json"), owner="triad"
    )
    b.flow.root = engine.git.root
    b.candidate_git, b.candidate_metadata, b.candidate_work = git, metadata, work
    return b


@pytest.mark.parametrize("denials", [0, 1])
def test_unmerged_candidate_retained_for_fresh_approval_without_rewriting_usage(candidate, denials):
    b = candidate
    if denials:
        from psycopg.types.json import Jsonb

        with b.host.store.connect() as conn:
            row = conn.execute(
                "SELECT id,payload FROM core.day3_records WHERE kind='Event' AND work_item_id=%s",
                (b.candidate_work.work_item_id,),
            ).fetchone()
            row["payload"]["denied_operations"] = denials
            conn.execute(
                "UPDATE core.day3_records SET payload=%s WHERE id=%s",
                (Jsonb(row["payload"]), row["id"]),
            )
    before = totals(b)
    record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert record.status == "CREATED" and count == 0 and day == b.day
    assert totals(b) == {**before, "changes": before["changes"] - 1}
    retained = b.flow.retained_application_candidate
    assert retained["commit"] == b.candidate_metadata["change_commit"]
    assert retained["files"][0]["path"] == PLAN_PATH
    assert retained["application_format_errors"][0]["loc"] == ("components", 0, "status")
    assert "fresh proposal" in retained["authority"]
    assert retained["prior_denied_operations"] == denials
    assert b.host.store.get(b.candidate_work.work_item_id).status == State.FAILED
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)


@pytest.mark.parametrize(
    "tamper",
    [
        "dirty",
        "extra_commit",
        "export_content",
        "export_base_hash",
        "native_run",
        "native_denial",
        "provider_failure",
        "implementation",
        "merge",
        "epoch",
        "policy",
        "reservation",
        "unrelated_failure",
    ],
)
def test_candidate_recovery_rejects_changed_or_ambiguous_proof_atomically(candidate, tamper):
    b = candidate
    if tamper in {"dirty", "extra_commit", "export_content"}:
        path = Path(b.candidate_metadata["worktree"]) / PLAN_PATH
        plan = json.loads(path.read_text())
        plan["goal"] = "Changed after original export"
        path.write_text(json.dumps(plan))
        if tamper != "dirty":
            b.candidate_git.git("add", "--", PLAN_PATH, cwd=b.candidate_metadata["worktree"])
            b.candidate_git.git(
                "commit",
                *(["--amend"] if tamper == "export_content" else []),
                "-m",
                "Changed candidate",
                cwd=b.candidate_metadata["worktree"],
            )
    elif tamper in {"export_base_hash", "native_run", "native_denial"}:
        kind = "Event" if tamper == "native_denial" else "AgentRunResult"
        with b.host.store.connect() as conn:
            row = conn.execute(
                "SELECT id,payload FROM core.day3_records WHERE kind=%s AND work_item_id=%s",
                (kind, b.candidate_work.work_item_id),
            ).fetchone()
            data = row["payload"]
            if tamper == "native_denial":
                data["denied_operations"] = True
            elif tamper == "native_run":
                data["run_id"] = "unrelated"
            else:
                patch = json.loads(data["analysis_artifacts"][0])
                patch["files"][0]["original_sha256"] = "0" * 64
                data["analysis_artifacts"] = [json.dumps(patch)]
            from psycopg.types.json import Jsonb

            conn.execute(
                "UPDATE core.day3_records SET payload=%s WHERE id=%s", (Jsonb(data), row["id"])
            )
    elif tamper == "provider_failure":
        b.host.ledger.event(
            "provider_failed", b.candidate_work.work_item_id, run_id="candidate-native-run"
        )
    elif tamper == "implementation":
        b.host.append(
            "ImplementationRun", {"work_item_id": b.candidate_work.work_item_id}, owner="triad"
        )
    elif tamper == "merge":
        b.host.append(
            "ProductMerge",
            {"mission_id": b.cycle.cycle_id, "implementation_id": "unaccounted"},
            owner="triad",
        )
    elif tamper == "epoch":
        b.host.ledger.operate("pause")
    elif tamper == "policy":
        b.flow.policy["id"] = "different"
    elif tamper == "reservation":
        b.host.ledger.reserve("CODEX", b.candidate_work.work_item_id, improvement=True, day=b.day)
    else:
        prior = b.daily.current(b.cycle.cycle_id)
        data = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
        data.update(
            failure_code="ValueError",
            failures=[{"code": "ValueError", "message": "Unrelated runtime failure"}],
        )
        b.host.append(
            "CycleRecord", CycleRecord.model_validate(data).model_dump(mode="json"), owner="triad"
        )
    before = totals(b)
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert totals(b) == before
    assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"


@pytest.mark.parametrize("variant", ["historical_prose", "ambiguous", "unknown_id"])
def test_retained_legacy_workflow_failure_requires_unique_exact_entry_point(candidate, variant):
    from products.triad.sequential_application import WORKFLOW_ERROR
    from psycopg.types.json import Jsonb

    b = candidate
    path = Path(b.candidate_metadata["worktree"]) / PLAN_PATH
    data = json.loads(path.read_text())
    data["components"][0]["status"] = "PLANNED"
    data["architecture_reasoning"] = "Actual candidate authored design"
    if variant == "ambiguous":
        data["workflows"].append({**data["workflows"][0], "id": "another"})
    content = json.dumps(data)
    path.write_text(content, encoding="utf-8")
    b.candidate_git.git("add", "--", PLAN_PATH, cwd=b.candidate_metadata["worktree"])
    b.candidate_git.git(
        "commit",
        "--amend",
        "-m",
        "Original candidate fixture",
        cwd=b.candidate_metadata["worktree"],
    )
    b.candidate_metadata["change_commit"] = b.candidate_git.git(
        "rev-parse", "HEAD", cwd=b.candidate_metadata["worktree"]
    )
    with b.host.store.connect() as conn:
        row = conn.execute(
            "SELECT id,payload FROM core.day3_records WHERE kind='AgentRunResult' AND work_item_id=%s",
            (b.candidate_work.work_item_id,),
        ).fetchone()
        patch = json.loads(row["payload"]["analysis_artifacts"][0])
        patch["files"][0]["content"] = content
        row["payload"]["analysis_artifacts"] = [json.dumps(patch)]
        conn.execute(
            "UPDATE core.day3_records SET payload=%s WHERE id=%s",
            (Jsonb(row["payload"]), row["id"]),
        )
        grant = b.daily.product.get("workspace-" + b.candidate_work.work_item_id, conn=conn)
        approval = b.daily.host.get(grant["approval_id"], conn=conn)
        approval["proposal"]["value_plan"] = {
            "application_contribution": {
                "workflow": "missing-id"
                if variant == "unknown_id"
                else "Supply data and inspect a chart",
                "entry_point": "/triad/product",
                "input_producer": "Fixture",
                "output_consumer": "Fixture",
                "contracts_and_versions": ["fixture.v1"],
                "integration_checks": ["fixture"],
                "status": "FOUNDATION",
            }
        }
        conn.execute(
            "UPDATE core.intelligence_records SET payload=%s WHERE id=%s",
            (Jsonb(approval), grant["approval_id"]),
        )
    b.host.append(
        "ProductBuildFailure",
        {
            "mission_id": b.cycle.cycle_id,
            "work_item_id": b.candidate_work.work_item_id,
            "reason": WORKFLOW_ERROR,
            "error_class": "ValueError",
        },
        owner="triad",
    )
    prior = b.daily.current(b.cycle.cycle_id)
    data = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
    data.update(
        failure_code="ValueError", failures=[{"code": "ValueError", "message": WORKFLOW_ERROR}]
    )
    b.host.append(
        "CycleRecord", CycleRecord.model_validate(data).model_dump(mode="json"), owner="triad"
    )
    before = totals(b)
    if variant == "historical_prose":
        record, _, _ = resume_patch_failure(b.flow, b.cycle.cycle_id)
        assert record.status == "CREATED"
        assert (
            b.flow.retained_application_candidate["application_format_errors"][0][
                "expected_workflow_id"
            ]
            == "workspace"
        )
        assert totals(b) == {**before, "changes": before["changes"] - 1}
    else:
        with pytest.raises((PermissionError, ValueError)):
            resume_patch_failure(b.flow, b.cycle.cycle_id)
        assert totals(b) == before
        assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"
