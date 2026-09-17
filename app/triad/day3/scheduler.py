"""Single durable UTC/date cycle slot; configurable schedule, off until enabled."""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from triad.day3.cycles import Cycles
from triad.settings import ROOT


def tick(cycles=None, instant=None, config=None):
    config = config or json.loads((ROOT / "agents/day3.json").read_text())["scheduler"]
    if not config["enabled"]:
        return {"status": "DISABLED"}
    cycles = cycles or Cycles()
    control = cycles.ledger.control()
    if control["paused"] or control["killed"]:
        return {"status": "PAUSED"}
    local = (instant or datetime.now(UTC)).astimezone(ZoneInfo(config["timezone"]))
    hour, minute = map(int, config["time"].split(":"))
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        raise ValueError("Invalid schedule time")
    if (local.hour, local.minute) < (hour, minute):
        return {"status": "NOT_DUE"}
    cycles.day = local.date().isoformat()
    return cycles.run(mode=config["mode"], scheduled=True)
