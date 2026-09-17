"""Operator CLI: python tools/day2.py init|demo|rotate|local|project|recover."""

import argparse
import json

from triad.brain import Brain
from triad.orchestrator import Orchestrator
from triad.settings import ROOT
from triad.work import ComputeBudget, Provenance, State, WorkItem


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init", "demo", "rotate", "local", "project", "recover"]
    )
    args = parser.parse_args()
    engine = Orchestrator()
    if args.command == "init":
        print(json.dumps(engine.initialize(), indent=2))
    elif args.command == "project":
        print(json.dumps(Brain(engine.store).flush(), indent=2))
    elif args.command == "recover":
        count = 0
        for work in engine.store.list_work(1000):
            if work.status in {State.ASSIGNED, State.IN_PROGRESS, State.VALIDATING, State.APPROVED}:
                with engine.store.lease(work.work_item_id):
                    current = engine.store.get(work.work_item_id)
                    engine.advance(
                        current,
                        State.BLOCKED,
                        "Operator recovered interrupted host run; retry requires fresh policy evaluation",
                        failure_reason="Interrupted run; artifacts must be inspected before retry",
                    )
                    count += 1
        print(json.dumps({"recovered": count}))
    elif args.command in {"demo", "rotate"}:
        items = []
        for agent in (
            engine.registry.rotation if args.command == "rotate" else engine.registry.rotation[:1]
        ):
            work = engine.demo(worker=agent, parent=items[-1].work_item_id if items else None)
            result = engine.run(work.work_item_id)
            items.append(result)
            if result.status != State.COMPLETED:
                raise RuntimeError(
                    f"Demo did not complete: {result.status}, {result.failure_reason}"
                )
        report = [
            {
                "id": w.work_item_id,
                "mission_id": w.mission_id,
                "agent": w.assigned_agent,
                "reviewer": w.reviewer,
                "status": w.status,
                "mode": w.result.execution_mode,
            }
            for w in items
        ]
        output = json.dumps(report, indent=2)
        (ROOT / "logs/day2-demo.json").write_text(output)
        print(output)
    else:
        work = engine.create(
            WorkItem(
                title="Summarize a synthetic operational journal",
                description="Return a short summary of the supplied synthetic observation.",
                work_type="summarize_journal",
                authority_tier=0,
                allowed_tools=("read_file",),
                allowed_paths=("docs",),
                execution_permissions=("read",),
                reasoning_budget=512,
                compute_budget=ComputeBudget(max_output_tokens=512, timeout_seconds=120),
                input_context=(
                    Provenance(
                        kind="OBSERVATION",
                        text="Synthetic journal: 120 records processed, 2 rejected for missing timestamps.",
                        source="synthetic:day2-demo",
                        agent="operator",
                    ),
                ),
            )
        )
        result = engine.run(work.work_item_id, mode="real", auto_review=False)
        output = json.dumps(
            {
                "id": result.work_item_id,
                "status": result.status,
                "result": result.result.model_dump(mode="json") if result.result else None,
                "failure": result.failure_reason,
            },
            indent=2,
        )
        (ROOT / "logs/day2-local.json").write_text(output)
        print(output)
        if result.status != State.AWAITING_REVIEW:
            raise RuntimeError("Local worker did not produce a reviewable result")


if __name__ == "__main__":
    main()
