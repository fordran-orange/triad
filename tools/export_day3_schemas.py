"""Export canonical Day 3 contracts for review and provider integration."""

import json

from triad.day3 import contracts
from triad.settings import ROOT
from triad.work import Record


def main():
    target = ROOT / "control-plane/day3"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for name in dir(contracts):
        value = getattr(contracts, name)
        if (
            isinstance(value, type)
            and issubclass(value, Record)
            and value.__module__ == contracts.__name__
        ):
            (target / f"{name}.schema.json").write_text(
                json.dumps(value.model_json_schema(), indent=2) + "\n"
            )
            count += 1
    print(f"Exported {count} Day 3 schemas")


if __name__ == "__main__":
    main()
