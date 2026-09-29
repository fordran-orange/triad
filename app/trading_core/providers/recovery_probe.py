"""Bounded staging compatibility check. No host file publication or Git operations."""

import hashlib

from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.engineering import issue_grant, run_approved_checks
from trading_core.execution import ExecutionServices
from trading_core.intelligence.model_binding import _record
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import ComputeBudget, State, WorkItem, now


def probe_write(control, raw, baseline, *, epoch):
    names = {t["capability"]["capability"] for t in baseline["templates"]}
    engineering = "isolated_product_ui_edit" in names
    if engineering:
        root = next(p for p in raw["allowed_paths"] if p.startswith("app/products/"))
        owner = root.split("/")[2]
        path = f"app/products/{owner}/features/provider_compatibility_probe.html"
        permission = "write_code"
    else:
        owner, path, permission = "core", "docs/provider_compatibility_probe.md", "write_docs"
    content = (
        "<h1>Provider compatibility verified</h1>"
        if engineering
        else "Provider compatibility verified"
    )
    engine = ExecutionServices(
        Store(control.ledger.store.settings, scope=owner if owner != "core" else None)
    )
    objective = (
        "Use propose_file_change to stage exactly "
        + path
        + " containing exactly "
        + content
        + ". No other edits. Return CODE_CHANGE with files_changed EMPTY; Core records observed writes. "
        "No actions, commands, tests or claims. This is an isolated compatibility check, never deployed."
    )
    work = engine.host.create(
        WorkItem(
            owner=owner,
            title="Provider staging compatibility check",
            description=objective,
            assigned_agent=raw["agent_id"],
            reviewer="CODEX",
            work_type="development",
            authority_tier=2 if engineering else 1,
            allowed_paths=(path,) if engineering else ("docs",),
            allowed_tools=("read_file", "write_artifact"),
            execution_permissions=("read", "write_code" if engineering else "write_research"),
            reasoning_budget=2048,
            compute_budget=ComputeBudget(max_output_tokens=2048, timeout_seconds=240),
        )
    )
    work, decision = engine.start_work(work, epoch=epoch)
    grant = None
    script = (
        "from pathlib import Path; assert Path(" + repr(path) + ").read_text() == " + repr(content)
    )
    try:
        if engineering:
            grant = issue_grant(
                Records(control.ledger.store),
                work,
                base_commit="runtime-compatibility",
                files=(path,),
                test_id="provider-compatibility-v1",
                test_script=script,
            )
        request = AgentRunRequest(
            agent_id=raw["agent_id"],
            work_item_id=work.work_item_id,
            mission_id=work.mission_id,
            role="IMPLEMENT",
            acceptance_criteria=work.acceptance_criteria,
            objective=objective,
            context_packet={"purpose": "Isolated compatibility test; no deployment"},
            allowed_tools=("propose_file_change",),
            allowed_paths=work.allowed_paths,
            execution_permissions=(permission,),
            reasoning_budget=2048,
            token_budget=2048,
            policy_decision=decision.model_dump(mode="json"),
            required_output_schema=AgentRunResult.model_json_schema(),
            control_epoch=control.ledger.get("authority-" + work.work_item_id)["epoch"],
        )
        result = engine.runtime.execute(
            request, transport_id=raw["preferred_transport"], compatibility_probe=True
        )
        files = {f.path: f.content for f in result.files_changed}
        if files != {path: content}:
            raise PermissionError("Staging compatibility output did not match the fixed check")
        check = None
        if grant:
            check = run_approved_checks(
                grant,
                files,
                script,
                guard=lambda: control.ledger.guard(raw["agent_id"], work.work_item_id, grant.epoch),
            )
            if check["status"] != "PASS":
                raise PermissionError("Isolated compatibility check failed")
        usage = next(
            u for u in control.ledger.records("Usage", 1000) if u.get("run_id") == request.run_id
        )
        event = next(
            e
            for e in control.ledger.records("Event", 1000)
            if e.get("event") == "native_executor_evidence" and e.get("run_id") == request.run_id
        )
        payload = {
            "agent": raw["agent_id"],
            "run_id": request.run_id,
            "usage_id": usage["id"],
            "event_id": event["id"],
            "model": usage["actual_model"],
            "transport": raw["preferred_transport"],
            "success": True,
            "runtime_identity": usage["runtime_identity"],
            "checks": check,
            "grant_id": "engineering-" + work.work_item_id if grant else None,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "work_item_id": work.work_item_id,
            "path": path,
            "checked_content": content,
            "completed_at": now().isoformat(),
        }
        identifier = Records(control.ledger.store).append("ProviderWriteVerification", payload)
        engine.host.advance(
            work, State.AWAITING_REVIEW, "Compatibility evidence only; no files published"
        )
        return identifier
    except Exception:
        current = engine.host.store.get(work.work_item_id)
        if current.status == State.IN_PROGRESS:
            engine.host.advance(current, State.FAILED, "Provider compatibility check failed")
        raise


def validate_write(records, raw, value, *, conn, require_engineering=False):
    proof = _record(conn, value["write_proof"], "ProviderWriteVerification")["payload"]
    work = records.store.get(proof["work_item_id"])

    def related(identifier, kind):
        row = conn.execute(
            "SELECT owner,kind,work_item_id,payload FROM core.day3_records WHERE id=%s",
            (identifier,),
        ).fetchone()
        if (
            not row
            or row["kind"] != kind
            or row["owner"] != work.owner
            or row["work_item_id"] != work.work_item_id
        ):
            raise PermissionError("Staging evidence owner or work linkage mismatch")
        return row["payload"]

    usage = related(proof["usage_id"], "Usage")
    event = related(proof["event_id"], "Event")
    run = related("transport-run-" + proof["run_id"], "TransportRun")
    expected = {
        "agent": raw["agent_id"],
        "provider": raw["provider"],
        "transport": raw["preferred_transport"],
        "actual_model": value["model"],
        "run_id": proof["run_id"],
        "status": "SUCCESS",
        "billing_source": "SUBSCRIPTION",
        "runtime_identity": value["runtime_identity"],
    }
    engineering = bool(proof.get("grant_id"))
    if require_engineering != engineering:
        raise PermissionError("Staging proof does not cover the required capability")
    path = (
        f"app/products/{work.owner}/features/provider_compatibility_probe.html"
        if engineering
        else "docs/provider_compatibility_probe.md"
    )
    content = (
        "<h1>Provider compatibility verified</h1>"
        if engineering
        else "Provider compatibility verified"
    )
    if (
        proof.get("success") is not True
        or proof["model"] != value["model"]
        or proof["agent"] != raw["agent_id"]
        or proof["transport"] != raw["preferred_transport"]
        or proof.get("runtime_identity") != value["runtime_identity"]
        or proof.get("path") != path
        or proof.get("checked_content") != content
        or proof.get("content_sha256") != hashlib.sha256(content.encode()).hexdigest()
        or work.assigned_agent != raw["agent_id"]
        or usage.get("usage_known") is not True
        or usage.get("mode") != "REAL"
        or any(record.get(k) != v for record in (usage, run) for k, v in expected.items())
        or event.get("run_id") != proof["run_id"]
        or event.get("boundary") != "DOCKER_OFFLINE_TOOLS"
        or not any(
            c.get("tool") == "propose_file_change" and c.get("path") == path
            for c in event.get("calls", [])
        )
    ):
        raise PermissionError("Canonical staging evidence does not match the runtime")
    if engineering:
        from trading_core.resource_policy import scope_digest

        grant = records.get(proof["grant_id"], conn=conn)
        checks = proof["checks"]
        script = (
            "from pathlib import Path; assert Path("
            + repr(path)
            + ").read_text() == "
            + repr(content)
        )
        digest = hashlib.sha256(script.encode()).hexdigest()
        if (
            grant["kind"] != "EngineeringGrant"
            or grant["owner"] != work.owner
            or grant["scope_digest"] != scope_digest(work)
            or grant["agent"] != raw["agent_id"]
            or grant["writable_files"] != [path]
            or grant["test_sha256"] != digest
            or checks.get("status") != "PASS"
            or checks.get("exit_code") != 0
            or checks.get("test_sha256") != digest
            or checks.get("snapshot") != {path: proof["content_sha256"]}
        ):
            raise PermissionError(
                "Engineering compatibility check no longer matches the exact grant"
            )
