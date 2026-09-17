"""Day 4 durable queue and provider readiness commands (no permission increases)."""

import argparse
import json
import time

from triad.brain import Brain
from triad.jobs import Jobs
from triad.readiness import readiness
from triad.settings import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["init", "readiness", "jobs", "enqueue", "once", "worker"]
    )
    parser.add_argument("--mode", choices=["REAL", "SIMULATED"], default="REAL")
    args = parser.parse_args()
    jobs = Jobs()
    if args.command == "init":
        jobs.cycles.initialize()
        jobs.initialize()
        result = {"initialized": True}
    elif args.command == "readiness":
        result = readiness(jobs.cycles, probe=True)
        jobs.ledger.put("ReadinessReport", result)
        Brain(jobs.store).flush()
    elif args.command == "jobs":
        result = jobs.list()
    elif args.command == "enqueue":
        result = jobs.submit(args.mode)
    elif args.command == "once":
        result = jobs.once()
    else:
        try:
            while True:
                jobs.once()
                time.sleep(5)
        except KeyboardInterrupt:
            return
    output = json.dumps(result, indent=2, default=str)
    (ROOT / f"logs/day4-{args.command}.json").write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
