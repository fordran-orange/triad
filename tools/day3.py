"""Operator CLI: initialize, probe providers, run explicit cycles/support, or tick schedule."""

import argparse
import json

from triad.day3.cycles import Cycles
from triad.day3.scheduler import tick
from triad.day3.support import support
from triad.settings import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init", "health", "demo", "real", "support", "tick", "recover"]
    )
    args = parser.parse_args()
    engine = Cycles()
    if args.command == "init":
        engine.initialize()
        engine.seed_backlog()
        result = {"initialized": True}
    elif args.command == "health":
        result = engine.runtime.health()
    elif args.command in {"demo", "real"}:
        result = engine.run(mode="SIMULATED" if args.command == "demo" else "REAL")
    elif args.command == "recover":
        result = engine.recover()
    elif args.command == "tick":
        result = tick(engine)
    else:
        parents = [
            w
            for w in engine.host.store.list_work(1000)
            if w.assigned_agent == "CODEX"
            and w.status == "COMPLETED"
            and not any(
                r.get("parent_work_item_id") == w.work_item_id
                for r in engine.ledger.records("SupportRequest")
            )
        ]
        if not parents:
            raise RuntimeError(
                "A completed CODEX work item is required for the bounded helper demo"
            )
        result = support(
            engine,
            parents[0].work_item_id,
            "CODEX",
            "SUMMARY",
            "Synthetic journal: 120 records processed. Two records rejected because timestamps were missing.",
        )
    output = json.dumps(result, indent=2, default=str)
    (ROOT / f"logs/day3-{args.command}.json").write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
