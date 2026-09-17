"""Verify persisted Day 2 demo evidence against the current local services."""

import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from triad.brain import Brain
from triad.settings import ROOT
from triad.store import Store


def main():
    store = Store()
    demo = json.loads((ROOT / "logs/day2-demo.json").read_text())
    report = {"checked_at": datetime.now(UTC).isoformat(), "demo": demo}
    for entry in demo:
        work = store.get(entry["id"])
        assert work.status == "COMPLETED" and work.result.execution_mode == "deterministic_demo"
        assert work.assigned_agent != work.reviewer
        records = store.records(work_id=work.work_item_id)
        kinds = {r["kind"] for r in records}
        assert {"PolicyDecision", "ContextPacket", "Handoff", "Review", "JournalEntry"} <= kinds
        review = next(r for r in records if r["kind"] == "Review")
        assert review["decision"] == "APPROVE" and review["tests_repeated"]
        for evidence in review["evidence_checked"]:
            _, digest, path = evidence.split(":", 2)
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for journal in (r for r in records if r["kind"] == "JournalEntry"):
            assert (ROOT / f"docs/vault/02_Journal/generated/{journal['journal_id']}.md").is_file()
        assert any(
            r["relationship"] == "REVIEWED_BY" for r in Brain(store).lineage(work.work_item_id)
        )
        entry["state_events"] = len(store.events(work.work_item_id))
        entry["canonical_records"] = len(records)
        entry["lineage_links"] = len(Brain(store).lineage(work.work_item_id))
    local = json.loads((ROOT / "logs/day2-local.json").read_text())
    actual = store.get(local["id"])
    assert actual.status == "AWAITING_REVIEW" and actual.result.execution_mode == "ollama"
    assert "120" in actual.result.summary and "2" in actual.result.summary
    report["local"] = local
    tests = ET.parse(ROOT / "logs/day2-tests.xml").getroot().find("testsuite").attrib
    report["tests"] = {key: int(tests[key]) for key in ("tests", "failures", "errors", "skipped")}
    assert not any(report["tests"][key] for key in ("failures", "errors", "skipped"))
    with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=30) as response:
        status = json.load(response)
    assert all(
        status[name]["status"] == "up"
        for name in ("postgres", "timescale", "neo4j", "ollama", "backend", "git")
    )
    with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=10) as response:
        assert "Triad" in response.read().decode()
    status["frontend"] = {"status": "up", "served_by": "FastAPI"}
    report["services"] = status
    report["projections"] = store.projection_status()
    assert report["projections"]["pending"] == 0
    (ROOT / "logs/day2-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
