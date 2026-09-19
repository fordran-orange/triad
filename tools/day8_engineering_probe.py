"""Explicit real capability evaluation; stages isolated assets, never merges them.

Independent QA must inspect the resulting evidence before capability adoption.
No role or provider capability is enabled by this command.
"""

import hashlib
import json
import subprocess
from pathlib import Path

from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.engineering import issue_grant, run_approved_checks
from trading_core.execution import ExecutionServices
from trading_core.intelligence.capabilities import Capabilities
from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.records import Records
from trading_core.providers.control import ProviderControl
from trading_core.store import Store
from trading_core.work import ComputeBudget, State, WorkItem, now, uid


def main():
    root = Path(__file__).resolve().parents[1]
    host = Records()
    engine = ExecutionServices(Store(host.store.settings, scope="triad"))
    control = ProviderControl(host.ledger)
    control.require_gate()
    model = control.snapshot("claude_code_cli")["workitem"]["actual_model"]
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    mission = "day8-capability-probe-" + uid()
    path = "app/products/triad/features/engineering_probe.html"
    script = (
        "from pathlib import Path; s=Path('"
        + path
        + "').read_text(encoding='utf-8'); assert '<h1>Isolated engineering probe</h1>' in s; assert '<script' not in s; print('PASS: actual isolated staged UI asset')"
    )
    objective = "Stage one HTML file at the exact granted path containing <h1>Isolated engineering probe</h1>. No JavaScript. Use propose_file_change. Return CODE_CHANGE with exact staged contents, empty actions/commands/tests/claims/permission_requests. This is a capability test; no file is merged or deployed."
    proposal = Capability(
        provider="anthropic",
        model=model,
        transport="claude_code_cli",
        capability="isolated_product_ui_edit",
        native_or_tool_mediated="tool_mediated",
        status="RESTRICTED",
        verification_status="CLAIMED",
        discovery_source="operator",
        evidence=("Day8 explicit capability evaluation",),
        limitations=("Exact scoped UI assets only; no host/backend/shell/Git/network tools",),
        permissions_required=("write_code",),
    )
    proposal_id = Capabilities(host).propose(proposal, actor="operator-authorized Day8 host")
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=mission,
            title="Real isolated product UI capability probe",
            description=objective,
            work_type="development",
            assigned_agent="CLAUDE",
            reviewer="CODEX",
            review_required=True,
            authority_tier=2,
            allowed_tools=("read_file", "write_artifact"),
            allowed_paths=(path,),
            execution_permissions=("read", "write_code"),
            reasoning_budget=8192,
            compute_budget=ComputeBudget(
                max_input_chars=24000,
                max_output_tokens=6144,
                timeout_seconds=480,
                max_tool_calls=60,
            ),
            acceptance_criteria=(
                "Actual isolated staging",
                "Pinned offline check",
                "Separate independent QA before adoption",
            ),
        )
    )
    host.append(
        "EngineeringProbePlan",
        {
            "work_item_id": work.work_item_id,
            "proposal_id": proposal_id,
            "required_capability": "isolated_product_ui_edit",
            "candidate_providers": ["CLAUDE", "CODEX", "GROK"],
            "selected_provider": "CLAUDE",
            "reason": "Verified text proposal substrate; evaluating narrowly bounded UI edit extension. Codex is read-only; Grok write is degraded.",
            "base_commit": base,
            "created_at": now().isoformat(),
        },
        owner="core",
    )
    work, policy = engine.start_work(work)
    grant = issue_grant(
        host, work, base_commit=base, files=(path,), test_id="day8-ui-probe-v1", test_script=script
    )
    request = AgentRunRequest(
        agent_id="CLAUDE",
        work_item_id=work.work_item_id,
        mission_id=mission,
        role="IMPLEMENT",
        objective=objective,
        context_packet={"purpose": "Real bounded capability probe"},
        allowed_tools=("propose_file_change",),
        allowed_paths=(path,),
        acceptance_criteria=work.acceptance_criteria,
        reasoning_budget=8192,
        token_budget=6144,
        cost_budget=0,
        execution_permissions=("write_code",),
        policy_decision=policy.model_dump(mode="json"),
        required_output_schema=AgentRunResult.model_json_schema(),
        control_epoch=grant.epoch,
    )
    try:
        result = engine.runtime.execute(request)
        snapshot = {c.path: c.content for c in result.files_changed}
        proof = run_approved_checks(
            grant,
            snapshot,
            script,
            guard=lambda: engine.ledger.guard("CLAUDE", work.work_item_id, grant.epoch),
        )
        if proof["status"] != "PASS":
            raise ValueError("Real isolated probe failed its fixed acceptance check")
        usage = next(
            r for r in engine.ledger.records("Usage", 1000) if r.get("run_id") == request.run_id
        )
        observed = next(
            r
            for r in engine.ledger.records("Event", 1000)
            if r.get("event") == "native_executor_evidence" and r.get("run_id") == request.run_id
        )
        if not any(c.get("tool") == "propose_file_change" for c in observed.get("calls", [])):
            raise PermissionError("No observed native edit")
        evidence = {
            "proposal_id": proposal_id,
            "work_item_id": work.work_item_id,
            "run_id": request.run_id,
            "base_commit": base,
            "grant": grant.model_dump(mode="json"),
            "usage": usage,
            "native_evidence": observed,
            "checks": proof,
            "files": snapshot,
            "sha256": {p: hashlib.sha256(v.encode()).hexdigest() for p, v in snapshot.items()},
            "completed_at": now().isoformat(),
            "status": "AWAITING_INDEPENDENT_QA",
            "merged": False,
        }
        identifier = host.append("EngineeringProbeResult", evidence, owner="core")
        engine.host.advance(
            work, State.AWAITING_REVIEW, "Real probe evidence retained; separate QA required"
        )
        report = root / "logs" / (mission + ".json")
        report.write_text(
            json.dumps({**evidence, "record_id": identifier}, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "report": str(report),
                    "record_id": identifier,
                    "work_item_id": work.work_item_id,
                    "status": evidence["status"],
                }
            )
        )
    except Exception as exc:
        engine.host.advance(
            engine.host.store.get(work.work_item_id),
            State.FAILED,
            "Capability probe failed; no adoption",
            failure_reason=type(exc).__name__,
        )
        raise


if __name__ == "__main__":
    main()
