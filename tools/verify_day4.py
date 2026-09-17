"""Read-only Day 4 queue, provider and regression evidence verification."""

import json
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from triad.jobs import Jobs
from triad.readiness import readiness
from triad.settings import ROOT


def main():
    jobs = Jobs()
    rows = jobs.list()
    submitted = json.loads((ROOT / "logs/day4-enqueue.json").read_text())["job"]
    actual = next(r for r in rows if r["id"] == submitted["id"])
    assert submitted["status"] == "QUEUED" and actual["status"] == "BLOCKED"
    assert actual["started_at"] and actual["finished_at"] and actual["worker_id"]
    original = json.loads((ROOT / "logs/day3-real.json").read_text())
    assert actual["result"]["cycle_id"] == original["cycle_id"]
    baseline = json.loads((ROOT / "logs/day3-verification.json").read_text())
    usage = jobs.ledger.records("Usage", 1000)
    assert {r["run_id"] for r in usage} == {r["run_id"] for r in baseline["usage"]}
    assert jobs.ledger.totals() == baseline["budgets"]
    control = jobs.ledger.control()
    assert not control["paused"] and not control["killed"]
    tests = ET.parse(ROOT / "logs/day4-tests.xml").getroot().find("testsuite").attrib
    tests = {k: int(tests[k]) for k in ("tests", "failures", "errors", "skipped")}
    assert tests["tests"] >= 144 and not any(tests[k] for k in ("failures", "errors", "skipped"))
    endpoints = {}
    for path in ("/api/status", "/api/day3/jobs", "/api/day3/readiness", "/api/foundation"):
        with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=30) as response:
            endpoints[path] = json.load(response)
    assert endpoints["/api/foundation"]["live_trading_authority"] is False
    assert all(
        endpoints["/api/status"][name]["status"] == "up"
        for name in ("postgres", "timescale", "neo4j", "ollama", "git", "backend")
    )
    assert any(r["id"] == actual["id"] for r in endpoints["/api/day3/jobs"]["jobs"])
    projection = jobs.store.projection_status()
    assert projection["pending"] == 0 and projection["errors"] == 0
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "tests": tests,
        "job": actual,
        "readiness": readiness(jobs.cycles),
        "usage_unchanged": True,
        "budgets_unchanged": True,
        "projections": projection,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip(),
    }
    (ROOT / "logs/day4-verification.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "checked_at",
                    "tests",
                    "head",
                    "working_tree",
                    "usage_unchanged",
                    "budgets_unchanged",
                    "projections",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
