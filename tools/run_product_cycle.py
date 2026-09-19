"""Explicit single-cycle host command. Never scheduled or automatically retried."""

import argparse
import json

from products.triad.development import Development


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission", help="Resume read-only inspection checkpoints only")
    parser.add_argument(
        "--operator-authorized",
        action="store_true",
        help="Operator explicitly authorized this bounded cycle and governed merge",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            Development().run(args.mission, operator_authorized=args.operator_authorized), indent=2
        )
    )


if __name__ == "__main__":
    main()
