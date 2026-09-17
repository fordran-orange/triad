"""Export canonical runtime contracts without secrets or operational data."""

import json

from triad import work
from triad.settings import ROOT


def main():
    target = ROOT / "control-plane/day2"
    target.mkdir(parents=True, exist_ok=True)
    names = (
        "WorkItem",
        "Agent",
        "PolicyDecision",
        "JournalEntry",
        "Handoff",
        "Review",
        "ContextPacket",
        "Provenance",
        "ElevationRequest",
        "WorkResult",
    )
    for name in names:
        (target / f"{name}.schema.json").write_text(
            json.dumps(getattr(work, name).model_json_schema(), indent=2) + "\n", encoding="utf-8"
        )
    print(f"Exported {len(names)} Day 2 schemas")


if __name__ == "__main__":
    main()
