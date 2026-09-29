"""Explicit single-cycle host command. Never scheduled or automatically retried."""

import argparse
import json

from products.triad.development import Development


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission", help="Resume read-only inspection checkpoints only")
    args = parser.parse_args()
    print(
        json.dumps(
            Development().run(args.mission), indent=2
        )
    )


if __name__ == "__main__":
    main()
