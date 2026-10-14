# ruff: noqa: F811
import pytest
from products.triad.cycle_history import CycleHistory
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.ledger import Ledger
from trading_core.store import Store
from trading_core.work import WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.triad]


def test_historical_cycle_capture_preserves_failure_and_is_idempotent(engine):
    store = Store(engine.host.store.settings, scope="triad")
    ledger = Ledger(store)
    ledger.put(
        "Cycle",
        {
            "cycle_id": "old-blocked",
            "mode": "REAL",
            "status": "BLOCKED",
            "summary": {"failures": ["CODEX: UNAVAILABLE / CredentialsOrModelNotConfigured"]},
        },
        identifier="old-blocked",
    )
    before = ledger.get("old-blocked")
    history = CycleHistory(store)
    record = history.capture("old-blocked")
    assert record["failure_code"] == "TRIAD_PROVIDER_GATE_FAILED"
    assert record["parent_work_item_id"] and record["control_epoch"] is None
    assert record["started_at"] is None and record["blocked_at"] is None
    assert history.capture("old-blocked")["created_at"] == record["created_at"]
    assert len(history.records.list("CycleRecord")) == 1
    assert ledger.get("old-blocked") == before
    assert store.get(record["parent_work_item_id"]).owner == "triad"
    with pytest.raises(PermissionError):
        CycleHistory(Store(engine.host.store.settings, scope="aegis"))
    with pytest.raises(PermissionError):
        history.records.append("CycleRecord", record, owner="triad")


def test_live_gate_block_records_work_time_and_no_execution_authority(engine):
    history = CycleHistory(engine.host.store)
    identifier = history.blocked()
    record = history.list()[0]
    assert record["cycle_id"] == identifier and record["blocked_at"]
    work = history.store.get(record["parent_work_item_id"])
    assert work.status == "BLOCKED" and work.allowed_tools == () and work.authority_tier == 0
    assert record["provider_gate_result"]["status"] == "BLOCKED"


def test_real_rollup_links_build_qa_merge_and_preserves_private_scope(engine):
    store = Store(engine.host.store.settings, scope="triad")
    work = store.create(
        WorkItem(owner="triad", mission_id="actual", title="Build", description="Test evidence")
    )
    host = Records(engine.host.store)
    for kind, payload in [
        ("ProductCycle", {"status": "INSPECTING", "schedule_enabled": False}),
        (
            "ProductBuild",
            {
                "implementation_id": "build",
                "work_item_id": work.work_item_id,
                "builder": "CLAUDE",
                "correction": ["fixed failure"],
            },
        ),
        (
            "QARun",
            {
                "qa_run_id": "qa",
                "implementation_run_id": "build",
                "qa_agent": "CODEX",
                "decision": "PASS",
            },
        ),
        (
            "ProductMerge",
            {
                "implementation_id": "build",
                "git": {"merge_commit": "abc", "base_commit": "base"},
                "recorded_at": work.created_at.isoformat(),
                "hashes": {"docs/a.md": "hash"},
            },
        ),
    ]:
        host.append(kind, {"mission_id": "actual", **payload}, owner="triad")
    host.append(
        "ProductCandidate", {"mission_id": "actual", "secret_product": "aegis"}, owner="aegis"
    )
    history = CycleHistory(store)
    record = history.capture("actual")
    assert record["status"] == "COMPLETED" and record["merge_commit"] == "abc"
    assert record["qa_runs"][0]["qa_agent"] == "CODEX" and len(record["correction_runs"]) == 1
    assert record["candidate_improvements"] == []
    blocked = history.blocked()
    history.link(blocked, "actual", "recovered_by_cycle_id")
    old = next(r for r in history.list() if r["cycle_id"] == blocked)
    assert old["status"] == "BLOCKED" and old["recovered_by_cycle_id"] == "actual"
    assert history.records.list("CycleRecord")[0]["status"] == "COMPLETED"
