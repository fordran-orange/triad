"""Bounded research laboratory CLI; fixtures are engine tests, never alpha research."""

import argparse
import json

from triad.lab.service import Laboratory
from triad.settings import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["demo", "run", "review", "catalog", "recover-ingestion"]
    )
    parser.add_argument("identifier", nargs="?")
    args = parser.parse_args()
    lab = Laboratory()
    if args.command == "demo":
        lab.cycles.initialize()
        result = lab.demo()
    elif args.command == "run":
        result = lab.run(args.identifier).model_dump(mode="json")
    elif args.command == "review":
        result = lab.review(args.identifier)
    elif args.command == "recover-ingestion":
        result = lab.recover_ingestion(args.identifier).model_dump(mode="json")
    else:
        result = lab.catalog()
    output = json.dumps(result, indent=2, default=str, allow_nan=False)
    (ROOT / f"logs/research-{args.command}.json").write_text(output + "\n", encoding="utf-8")
    if args.command == "demo":
        print(
            json.dumps(
                {
                    "dataset": result["dataset"]["dataset_id"],
                    "experiment": result["experiment"]["experiment_id"],
                    "runs": [r["run_id"] for r in result["runs"]],
                    "reproducible": result["reproducible"],
                },
                indent=2,
            )
        )
    else:
        print(output)


if __name__ == "__main__":
    main()
