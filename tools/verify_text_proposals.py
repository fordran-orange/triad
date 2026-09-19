"""Bounded real transport probe. Proposed canary text is never applied to the repository."""

import argparse
import json
from pathlib import Path

from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.execution import ExecutionServices
from trading_core.providers.contracts import PREFERRED
from trading_core.work import ComputeBudget, State, WorkItem


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=["CLAUDE", "GROK"])
    agent = parser.parse_args().agent
    service = ExecutionServices()
    path = "docs/improvements/transport-canary-" + agent.lower() + ".md"
    content = (
        "# Isolated transport check\n\nThis is a staged capability probe, not a product change.\n"
    )
    work = service.host.create(
        WorkItem(
            owner="core",
            title="Verify bounded text proposal transport: " + agent,
            description="Use the isolated file tool to stage exactly one new file at "
            + path
            + " containing exactly this text: "
            + json.dumps(content)
            + ". Return DOCUMENTATION_CHANGE with this exact file in files_changed. No tests, commands, claims, actions_taken or permission requests. The host will discard the proposal after checking it.",
            assigned_agent=agent,
            work_type="development",
            authority_tier=1,
            allowed_tools=("write_artifact",),
            allowed_paths=("docs/improvements",),
            execution_permissions=("write_research",),
            reasoning_budget=1024,
            compute_budget=ComputeBudget(
                max_input_chars=12000, max_output_tokens=1024, timeout_seconds=120
            ),
            acceptance_criteria=(
                "Exactly one staged file with the required bytes",
                "Native isolated tool evidence matches returned proposal",
                "No repository file is applied",
            ),
        )
    )
    work, policy = service.start_work(work)
    request = AgentRunRequest(
        agent_id=agent,
        work_item_id=work.work_item_id,
        mission_id=work.mission_id,
        context_packet={"purpose": "Core capability verification; no product conclusions"},
        role="PROPOSE",
        objective=work.description,
        allowed_paths=work.allowed_paths,
        acceptance_criteria=work.acceptance_criteria,
        reasoning_budget=1024,
        token_budget=1024,
        cost_budget=0,
        policy_decision=policy.model_dump(mode="json"),
        required_output_schema=AgentRunResult.model_json_schema(),
        control_epoch=service.ledger.get("authority-" + work.work_item_id)["epoch"],
    )
    try:
        result = service.runtime.execute(request, transport_id=PREFERRED[agent])
        assert len(result.files_changed) == 1
        assert result.files_changed[0].path == path and result.files_changed[0].content == content
        assert not Path(path).exists()
        journal = service.host.journal(
            work,
            kind="review",
            result="Host verified exact staged canary; no repository writes.",
            evidence=("run:" + request.run_id,),
            tests=("Exact path/content and absent repository canary checked",),
            mode="REAL",
        )
        service.host.advance(
            work,
            State.AWAITING_REVIEW,
            "Capability evidence awaits independent Core C QA",
            records=(journal,),
        )
        report = {
            "agent": agent,
            "work_item_id": work.work_item_id,
            "run_id": request.run_id,
            "success": True,
            "host_files_written": 0,
        }
    except Exception as exc:
        service.host.advance(work, State.FAILED, "Capability probe failed: " + type(exc).__name__)
        raise
    destination = Path("logs/day6-" + agent.lower() + "-text-proposal-proof.json")
    destination.write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
