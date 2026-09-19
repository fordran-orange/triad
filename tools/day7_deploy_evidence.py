"""Explicit Day 7 host deployment: append evidence without rewriting history."""

import hashlib
import json
from pathlib import Path

from products.triad.cycle_history import CycleHistory
from trading_core.integrations.data import DataAccess
from trading_core.integrations.registry import ExternalIntegrationRegistry
from trading_core.intelligence.records import Records
from trading_core.settings import ROOT
from trading_core.store import Store
from trading_core.work import now

DEBT = "6402c739-cc23-4e07-9beb-2157e538ff4c"
BLOCKED = "8a16bb3a-925e-4ff3-8131-94bad088fd1e"
RECOVERY = "day6-product-20260919"
ORIGINAL = "docs/improvements/real-market-readiness-criteria.md"
ORIGINAL_SHA = "d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9"
DEFINITIONS = "docs/improvements/real-market-readiness-definitions-v2.md"


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def main():
    # Operator explicitly requested the complete Day 7 build. This trusted host
    # script does not authorize an external source, cycle execution, or trading.
    assert digest(ORIGINAL) == ORIGINAL_SHA
    report_path = "docs/qa/DAY7_GHI_FINAL_QA.md"
    report = (ROOT / report_path).read_text(encoding="utf-8")
    if "**PASS**" not in report or "56e4f96" not in report:
        raise RuntimeError("Require the exact independent G/H/I correction PASS first")
    records = Records()
    debt = records.get(DEBT)
    if debt["kind"] != "QualityDebt" or debt["owner"] != "triad":
        raise RuntimeError("Unexpected original quality-debt identity")
    prior = records.list("QualityDebtResolution")
    resolution = next((r for r in prior if r.get("quality_debt_id") == DEBT), None)
    if not resolution:
        resolution_id = records.append(
            "QualityDebtResolution",
            {
                "quality_debt_id": DEBT,
                "status": "RESOLVED_DEFINITIONS_ONLY",
                "resolution": "Coverage, critical findings and completed checks are defined; the readiness gate remains non-executable and no real-market readiness is claimed.",
                "artifact": DEFINITIONS,
                "artifact_sha256": digest(DEFINITIONS),
                "original_artifact": ORIGINAL,
                "original_artifact_sha256": ORIGINAL_SHA,
                "reviewed_commit": "56e4f96cd9ab43a319302edb694897d75143237a",
                "qa_report": report_path,
                "qa_report_sha256": digest(report_path),
                "resolved_at": now().isoformat(),
                "resolved_by": "Day 7 authorized Core host deployment",
            },
            owner="triad",
        )
    else:
        resolution_id = resolution["id"]
    assert records.get(DEBT) == debt
    registry = ExternalIntegrationRegistry()
    registry.seed()
    DataAccess().seed()
    history = CycleHistory(Store(scope="triad"))
    history.backfill()
    rows = {r["cycle_id"]: r for r in history.list()}
    assert rows[BLOCKED]["status"] == "BLOCKED"
    assert rows[RECOVERY]["status"] == "COMPLETED"
    history.link(BLOCKED, RECOVERY, "recovered_by_cycle_id")
    rows = {r["cycle_id"]: r for r in history.list()}
    assert rows[BLOCKED]["status"] == "BLOCKED"
    assert rows[BLOCKED]["recovered_by_cycle_id"] == RECOVERY
    assert any(d["id"] == DEBT and d.get("resolutions") for d in rows[RECOVERY]["quality_debt"])
    catalog = registry.catalog()
    assert {r["integration_id"] for r in catalog} == {"schwab", "robinhood", "local-canonical"}
    assert all(not r["enabled"] for r in catalog if r["category"] == "BROKER")
    evidence = {
        "recorded_at": now().isoformat(),
        "original_debt_unchanged": True,
        "resolution_id": resolution_id,
        "canonical_cycles": len(rows),
        "blocked_cycle": rows[BLOCKED],
        "recovery_cycle": rows[RECOVERY],
        "integrations": catalog,
        "original_artifact_sha256": digest(ORIGINAL),
    }
    Path(ROOT / "logs/day7-deployed-evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: evidence[k] for k in ("resolution_id", "canonical_cycles", "original_debt_unchanged")}))


if __name__ == "__main__":
    main()
