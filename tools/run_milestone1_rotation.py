"""Milestone-1 real Grok -> Claude -> Codex autonomous provider rotation.

Operator starts one cycle; after that there are no human approval gates. Each subscription CLI
works in the same Core-created Git worktree, commits its own contribution, and hands a concise
summary to the next provider. Core validates protected paths, secrets and regression checks
before an automatic fast-forward merge to main.
"""

from __future__ import annotations

# ruff: noqa: I001

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.git_tools import GitChanges
from trading_core.providers.autonomous_cli import AutonomousCLIRun
from trading_core.providers.contracts import PREFERRED
from trading_core.providers.control import ProviderControl
from trading_core.providers.process import clean_environment
from trading_core.work import now

ROTATION = ("GROK", "CLAUDE", "CODEX")


def run_check(argv: list[str], cwd: Path, timeout: int = 900) -> dict:
    started = time.monotonic()
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=clean_environment(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "argv": argv,
        "exit_code": result.returncode,
        "duration": time.monotonic() - started,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def machine_checks(root: Path) -> list[dict]:
    checks = [
        run_check([sys.executable, "-m", "compileall", "-q", "app", "tests", "tools"], root),
        run_check(["ruff", "check", "app", "tests", "tools"], root),
        run_check(["pytest", "-q"], root, timeout=1800),
    ]
    failed = [item for item in checks if item["exit_code"] != 0]
    if failed:
        raise RuntimeError("Regression gate failed: " + json.dumps(failed, default=str))
    return checks


def core_live(url="http://127.0.0.1:8000/health/live") -> bool:
    try:
        with urlopen(url, timeout=3) as response:
            data = json.loads(response.read().decode())
        return data.get("status") == "ok"
    except Exception:
        return False


def restart_core(root: Path) -> bool:
    if os.name == "nt":
        ensure = root / "tools" / "ensure_core.ps1"
        if ensure.is_file():
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ensure),
                    "-Restart",
                ],
                cwd=root,
                env=clean_environment(),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if core_live():
            return True
        time.sleep(1)
    return False


def request_for(agent: str, run_id: str, objective: str, workspace: Path, handoff: dict):
    return AgentRunRequest(
        run_id=f"{run_id}-{agent.lower()}",
        agent_id=agent,
        work_item_id=f"{run_id}-{agent.lower()}",
        mission_id=run_id,
        role="IMPLEMENT",
        objective=objective,
        context_packet={
            "_core_execution": {"workspace": str(workspace)},
            "prior_handoff": handoff,
            "milestone": "Milestone 1 autonomous provider rotation",
        },
        allowed_tools=("read_file", "write_file", "shell", "git", "web"),
        allowed_paths=("app", "products", "tests", "docs", "research", "tools"),
        forbidden_paths=(),
        acceptance_criteria=(
            "Make one concrete, useful, reversible Triad improvement",
            "Run relevant deterministic checks before finishing",
            "Do not edit protected Core governance",
            "Do not merge to main or push",
            "Leave the worktree in a coherent state for the next provider",
        ),
        reasoning_budget=8192,
        token_budget=6144,
        cost_budget=0,
        execution_permissions=("write_code",),
        policy_decision={
            "decision": "ALLOW",
            "reason": "Operator-authorized Milestone 1 machine-gated provider verification",
        },
        required_output_schema=AgentRunResult.model_json_schema(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--objective",
        default=(
            "Inspect the current Triad product and implementation state. Make one small but real "
            "improvement that moves Triad toward a reliable autonomous trading-application "
            "development loop. Prefer fixing a concrete defect or missing operational behavior "
            "over adding architecture. You are one member of a Grok -> Claude -> Codex rotation. "
            "Inspect the existing work from prior members before changing anything."
        ),
    )
    parser.add_argument("--no-merge", action="store_true", help="Prove the cycle but retain branch")
    args = parser.parse_args()

    git = GitChanges()
    base = git.clean_baseline()
    run_id = "m1-" + now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    git.git("tag", f"pre-run/{run_id}", base)
    metadata = git.isolate(run_id, "rotation")
    workspace = Path(metadata["worktree"])
    control = ProviderControl()
    journal = []
    handoff: dict = {"from": "CORE", "summary": "Start of Milestone 1 rotation", "commit": base}

    for agent in ROTATION:
        transport_id = PREFERRED[agent]
        adapter = control.transport(transport_id)
        detected = adapter.detect()
        auth = adapter.authentication_status()
        if detected.get("install_status") != "INSTALLED":
            raise RuntimeError(f"{agent} provider is not installed: {detected}")
        if detected.get("compatibility_status") == "VERSION_MISMATCH":
            raise RuntimeError(f"{agent} provider version mismatch: {detected}")
        if auth.get("auth_state") != "AUTHENTICATED":
            raise RuntimeError(f"{agent} subscription is not authenticated: {auth}")

        request = request_for(agent, run_id, args.objective, workspace, handoff)
        runner = AutonomousCLIRun(adapter.command(), agent)
        result, inputs, outputs = runner.execute(request, workspace, adapter.model)
        if not runner.actual_model:
            raise RuntimeError(f"{agent} run did not provide evidence of the actual model")

        metadata, diff_checks = git.commit_autonomous(
            metadata, agent, summary="Milestone 1 autonomous rotation"
        )
        proof = {
            "proof_id": request.run_id,
            "success": True,
            "mode": "REAL",
            "agent": agent,
            "transport": transport_id,
            "provider": adapter.provider,
            "actual_model": runner.actual_model,
            "billing_source": "SUBSCRIPTION",
            "completed_at": now().isoformat(),
            "boundary": "CORE_RUN_WORKTREE",
            "input_tokens": inputs if inputs is not None else "UNKNOWN",
            "output_tokens": outputs if outputs is not None else "UNKNOWN",
            "change_commit": metadata["change_commit"],
            "files": diff_checks["files"],
        }
        journal.append(
            {
                **proof,
                "summary": result.summary,
                "recommended_next_step": result.recommended_next_step,
                "handoff_request": result.handoff_request,
            }
        )
        handoff = {
            "from": agent,
            "summary": result.summary,
            "commit": metadata["change_commit"],
            "files": diff_checks["files"],
            "recommended_next_step": result.recommended_next_step,
        }

    checks = machine_checks(workspace)

    # Capability truth is recorded only after the whole rotation survives machine validation.
    for proof in journal:
        control.ledger.put(
            "AutonomousProviderProof",
            proof,
            identifier="autonomous-proof-" + proof["transport"],
        )
        snapshot = control.snapshot(proof["transport"])
        control.ledger.put(
            "TransportStatus",
            {
                **snapshot,
                "transport": proof["transport"],
                "auth_state": "AUTHENTICATED",
                "billing_source": "SUBSCRIPTION",
                "health": "ONLINE",
                "error": None,
                "autonomous_worktree": proof,
                "updated_at": now().isoformat(),
            },
            identifier="transport-status-" + proof["transport"],
        )

    evidence = {
        "run_id": run_id,
        "base_commit": base,
        "branch": metadata["branch"],
        "final_change_commit": metadata["change_commit"],
        "providers": journal,
        "machine_checks": checks,
        "merge": "SKIPPED" if args.no_merge else "PENDING",
    }

    if not args.no_merge:
        git.merge_autonomous(metadata)
        evidence["merge"] = metadata["merge_commit"]
        if not restart_core(git.root):
            # main is a clean fast-forward from the pre-run tag; restore it deterministically.
            git.git("reset", "--hard", base)
            evidence["merge"] = "REVERTED_CORE_HEALTH_FAILURE"
            raise RuntimeError("Core failed post-merge health check; main restored to pre-run tag")

    control.ledger.put(
        "Milestone1Rotation",
        evidence,
        identifier="milestone1-rotation-" + run_id,
    )
    print(json.dumps(evidence, indent=2, default=str))


if __name__ == "__main__":
    main()
