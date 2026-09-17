"""Read-only verification of the actual Day 3 demonstration and service evidence."""

import json
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from triad.brain import Brain
from triad.day3.cycles import Cycles
from triad.settings import ROOT


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    engine = Cycles()
    ledger = engine.ledger
    demo = json.loads((ROOT / "logs/day3-demo.json").read_text())
    cycle = ledger.get(demo["cycle_id"])
    changes = [r for r in ledger.records("Change") if r["cycle_id"] == cycle["cycle_id"]]
    accepted = set(cycle["summary"]["changes_accepted"])
    assert len(accepted) >= 2 and cycle["mode"] == "SIMULATED"
    evidence = []
    for change in changes:
        work = engine.host.store.get(change["work_item_id"])
        records = engine.host.store.records(work_id=work.work_item_id)
        assert {"JournalEntry", "Handoff", "PolicyDecision"} <= {r["kind"] for r in records}
        metadata = change["git"]
        git("cat-file", "-e", metadata["change_commit"] + "^{commit}")
        paths = git(
            "diff", "--name-only", metadata["base_commit"], metadata["change_commit"]
        ).splitlines()
        assert paths and all(
            p.startswith(("docs/improvements/", "research/improvements/")) for p in paths
        )
        if change["id"] in accepted:
            assert change["status"] == "MERGED" and work.status == "COMPLETED"
            assert change["agent"] != change["reviewer"]
            assert change["review"]["decision"] == "APPROVE"
            assert change["review"]["change_commit"] == metadata["change_commit"]
            assert change["review"]["tests_repeated"]
            git("merge-base", "--is-ancestor", metadata["review_commit"], metadata["merge_commit"])
            git("merge-base", "--is-ancestor", metadata["merge_commit"], "HEAD")
        else:
            assert metadata["merge_commit"] is None and work.status == "BLOCKED"
        lineage = Brain(engine.host.store).lineage(work.work_item_id)
        assert any(r["relationship"] == "CREATED_COMMIT" for r in lineage)
        evidence.append(
            {**change, "files": paths, "work_status": work.status, "lineage_links": len(lineage)}
        )
    real = json.loads((ROOT / "logs/day3-real.json").read_text())
    assert real["status"] == "BLOCKED" and real["agents_run"] == []
    helper = json.loads((ROOT / "logs/day3-support.json").read_text())
    local = engine.host.store.get(helper["work_item_id"])
    assert local.status == "AWAITING_REVIEW" and local.result.execution_mode == "ollama"
    usage = ledger.records("Usage", 1000)
    local_usage = [r for r in usage if r["work_item_id"] == local.work_item_id]
    assert len(local_usage) == 1 and local_usage[0]["provider"] == "ollama"
    assert local_usage[0]["mode"] == "REAL" and local_usage[0]["input_tokens"] > 0
    tests = ET.parse(ROOT / "logs/day3-tests.xml").getroot().find("testsuite").attrib
    tests = {key: int(tests[key]) for key in ("tests", "failures", "errors", "skipped")}
    assert tests["tests"] >= 132 and not any(tests[k] for k in ("failures", "errors", "skipped"))
    with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=30) as response:
        services = json.load(response)
    assert all(
        services[k]["status"] == "up"
        for k in ("postgres", "timescale", "neo4j", "ollama", "git", "backend")
    )
    with urllib.request.urlopen("http://127.0.0.1:8000/api/day3/dashboard", timeout=30) as response:
        dashboard = json.load(response)
    assert len([r for r in dashboard["records"] if r["kind"] == "Change"]) >= 3
    projections = engine.host.store.projection_status()
    assert projections["pending"] == 0
    for item in (cycle, real):
        assert (ROOT / f"docs/vault/02_Journal/generated/cycle-{item['cycle_id']}.md").is_file()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "working_tree": git("status", "--porcelain"),
        "tests": tests,
        "services": services,
        "providers": ledger.records("ProviderHealth"),
        "cycle": cycle,
        "real_cycle": real,
        "changes": evidence,
        "local_helper": helper,
        "usage": usage,
        "estimated_api_cost": sum(r["estimated_cost"] for r in usage),
        "budgets": ledger.totals(),
        "projections": projections,
        "corrections": ledger.records("EvidenceCorrection"),
    }
    (ROOT / "logs/day3-verification.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "checked_at",
                    "branch",
                    "head",
                    "working_tree",
                    "tests",
                    "estimated_api_cost",
                    "budgets",
                    "projections",
                )
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
