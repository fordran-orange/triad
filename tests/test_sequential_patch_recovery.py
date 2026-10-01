"""Recovery changes only a proven unapplied reservation in a disposable database."""
# ruff: noqa: F811

from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from products.triad.daily import Daily
from products.triad.sequential_recovery import ERROR, resume_patch_failure
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import State, WorkItem, now

pytestmark = pytest.mark.integration


@pytest.fixture
def blocked(engine, monkeypatch):
    host = Records(Store(engine.host.store.settings))
    daily = Daily(host.store)
    cycle = daily.create()
    day = now().astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    host.append(
        "SequentialDailyProgram",
        {
            "cycle_id": cycle.cycle_id,
            "policy_id": "fixture",
            "order": ["CODEX", "CLAUDE", "GROK"],
            "parent_work_item_id": cycle.parent_work_item_id,
            "control_epoch": cycle.control_epoch,
            "local_date": day,
            "timezone": "America/Chicago",
        },
        owner="triad",
    )
    for state in ("INSPECTING", "SELECTING", "BUILDING"):
        daily.transition(cycle.cycle_id, state, ["fixture"])
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=cycle.cycle_id,
            parent_work_item_id=cycle.parent_work_item_id,
            assigned_agent="CODEX",
            work_type="development",
            title="Fixture",
            description="No provider execution",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture")
    host.ledger.reserve("CODEX", work.work_item_id, improvement=True, day=day)
    host.ledger.reserve("CODEX", work.work_item_id, tokens=123, seconds=2, day=day)
    metadata = engine.git.isolate(work.work_item_id, "CODEX")
    host.append(
        "ProductBuildCheckpoint",
        {
            "mission_id": cycle.cycle_id,
            "work_item_id": work.work_item_id,
            "phase": "ISOLATED",
            "git": metadata,
        },
        owner="triad",
    )
    host.append(
        "ProductBuildFailure",
        {"mission_id": cycle.cycle_id, "work_item_id": work.work_item_id, "reason": ERROR},
        owner="triad",
    )
    daily.transition(
        cycle.cycle_id,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": ERROR},),
    )
    flow = NS(s=NS(daily=daily, git=engine.git), policy={"id": "fixture"})
    flow.guard = lambda _: daily.product.ledger.guard(
        work_id=cycle.parent_work_item_id, epoch=cycle.control_epoch
    )
    monkeypatch.setattr(
        "products.triad.sequential_recovery.health", lambda revision: {"loaded_revision": revision}
    )
    return NS(flow=flow, daily=daily, host=host, cycle=cycle, work=work, metadata=metadata, day=day)


def totals(case):
    with case.host.store.connect() as conn:
        return conn.execute(
            "SELECT changes,reserved_tokens,reserved_seconds FROM core.autonomy_daily WHERE day=%s",
            (case.day,),
        ).fetchone()


def test_recovery_is_atomic_keeps_usage_history_and_cannot_repeat(blocked):
    b = blocked
    before = totals(b)
    record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert count == 0 and record.status == "CREATED"
    assert day == b.day
    assert record.parent_work_item_id == b.cycle.parent_work_item_id
    assert record.failures[-1]["message"] == ERROR
    assert b.host.store.get(b.work.work_item_id).status == State.FAILED
    after = totals(b)
    assert after == {**before, "changes": before["changes"] - 1}
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert totals(b) == after
    with pytest.raises(PermissionError, match="All three"):
        b.daily.require_turns_complete(b.cycle.cycle_id)


@pytest.mark.parametrize(
    "tamper",
    [
        "dirty",
        "policy",
        "epoch",
        "merge",
        "implementation",
        "reservation",
        "duplicate_turn",
        "out_of_order",
    ],
)
def test_unsafe_recovery_changes_nothing(blocked, tamper):
    b = blocked
    if tamper == "dirty":
        from pathlib import Path

        (Path(b.metadata["worktree"]) / "README.md").write_text("different")
    elif tamper == "policy":
        b.flow.policy["id"] = "changed"
    elif tamper == "epoch":
        b.host.ledger.operate("pause")
    elif tamper == "merge":
        b.host.append(
            "ProductMerge",
            {"mission_id": b.cycle.cycle_id, "implementation_id": "unknown"},
            owner="triad",
        )
    elif tamper == "implementation":
        b.host.append("ImplementationRun", {"work_item_id": b.work.work_item_id}, owner="triad")
    elif tamper == "reservation":
        b.host.ledger.reserve("CODEX", b.work.work_item_id, improvement=True, day=b.day)
    else:
        for agent in ["CODEX", "CODEX"] if tamper == "duplicate_turn" else ["CLAUDE"]:
            b.host.append(
                "ProductTurn",
                {"mission_id": b.cycle.cycle_id, "agent": agent, "status": "COMPLETED"},
                owner="triad",
            )
    before = totals(b)
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert totals(b) == before
    assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"


def test_record_failure_rolls_back_reservation_refund(blocked, monkeypatch):
    before = totals(blocked)
    monkeypatch.setattr(
        blocked.daily.host,
        "append",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("write failed")),
    )
    with pytest.raises(RuntimeError, match="write failed"):
        resume_patch_failure(blocked.flow, blocked.cycle.cycle_id)
    assert totals(blocked) == before
    assert blocked.daily.current(blocked.cycle.cycle_id)["status"] == "BLOCKED"


def test_reconciler_cannot_use_old_process_snapshot_during_recovery(blocked, monkeypatch):
    from products.triad.daily_process import reconcile

    def unexpected(*a, **k):
        pytest.fail("Reconciler must not read stale records while the runner owns the lease")

    monkeypatch.setattr(blocked.daily.product, "list", unexpected)
    with blocked.host.store.lease("triad-daily-product-execution"):
        reconcile(blocked.daily)


def test_scheduled_recovery_atomically_registers_new_runner(blocked, monkeypatch):
    from trading_core.cycle_records import CycleRecord

    b = blocked
    prior = b.daily.current(b.cycle.cycle_id)
    payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
    payload["scheduled"] = True
    b.host.append("CycleRecord", payload, owner="triad")
    monkeypatch.setattr(
        "products.triad.daily_process.process_info",
        lambda _: {"state": "RUNNING", "creation_id": "fixture-identity"},
    )
    record, _, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert day == b.day
    processes = b.host.list("DailyDispatchProcess")
    assert processes[-1]["creation_id"] == "fixture-identity"
    assert processes[-1]["recovery_action"] == record.recovery_action


def test_other_product_checkpoint_cannot_replace_dirty_failed_checkout(blocked):
    from pathlib import Path

    b = blocked
    (Path(b.metadata["worktree"]) / "README.md").write_text("unapplied edit remains")
    other = Records(Store(b.host.store.settings, scope="aegis"))
    other.append(
        "ProductBuildCheckpoint",
        {
            "mission_id": b.cycle.cycle_id,
            "work_item_id": b.work.work_item_id,
            "phase": "ISOLATED",
            "git": {**b.metadata, "worktree": str(b.flow.s.git.root)},
        },
        owner="aegis",
    )
    before = totals(b)
    with pytest.raises(PermissionError, match="clean and unapplied"):
        resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert totals(b) == before
    assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"


def test_other_product_records_do_not_change_recovery_authority(blocked):
    b = blocked
    for kind in (
        "SequentialDailyProgram",
        "DailyCycleTransition",
        "ProductMerge",
        "ProductBuildFailure",
    ):
        b.host.append(
            kind,
            {
                "cycle_id": b.cycle.cycle_id,
                "mission_id": b.cycle.cycle_id,
                "work_item_id": b.work.work_item_id,
                "reason": "unrelated",
            },
            owner="aegis",
        )
    record, _, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert day == b.day
    assert record.status == "CREATED"


@pytest.mark.parametrize(
    "tamper", [None, "grant_epoch", "missing_evidence", "checkpoint", "reservation"]
)
def test_native_result_recovery_requires_proven_unapplied_workspace(engine, blocked, tamper):
    from trading_core.cycle_records import CycleRecord
    from trading_core.product_workspace_grant import PROFILE
    from trading_core.resource_policy import scope_digest

    b = blocked
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=b.cycle.cycle_id,
            parent_work_item_id=b.cycle.parent_work_item_id,
            assigned_agent="CODEX",
            work_type="development",
            title="Native fixture",
            description="No provider execution",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture")
    b.host.append(
        "ProductWorkspaceGrant",
        {
            "profile": PROFILE,
            "work_item_id": work.work_item_id,
            "agent": "CODEX",
            "scope_digest": scope_digest(work),
            "epoch": b.cycle.control_epoch + (1 if tamper == "grant_epoch" else 0),
            "policy_id": "fixture",
            "base_commit": b.flow.s.git.git("rev-parse", "HEAD"),
        },
        owner="triad",
        identifier="workspace-" + work.work_item_id,
    )
    for event, extra in (
        ("provider_failed", {"error_class": "NativeResultViolation"}),
        ("native_executor_evidence", {"boundary": "DOCKER_OFFLINE_TOOLS"}),
    ):
        if tamper != "missing_evidence":
            b.daily.product.ledger.event(
                event, work.work_item_id, run_id="fixture-native-run", **extra
            )
    if tamper == "checkpoint":
        b.host.append(
            "ProductBuildCheckpoint",
            {"mission_id": b.cycle.cycle_id, "work_item_id": work.work_item_id},
            owner="triad",
        )
    if tamper == "reservation":
        b.host.ledger.reserve("CODEX", work.work_item_id, improvement=True, day=b.day)
    prior = b.daily.current(b.cycle.cycle_id)
    payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
    payload.update(
        failure_code="ProviderError",
        failures=[{"code": "ProviderError", "message": "NativeResultViolation"}],
    )
    b.host.append("CycleRecord", payload, owner="triad")
    before = totals(b)
    if tamper:
        with pytest.raises(PermissionError):
            resume_patch_failure(b.flow, b.cycle.cycle_id)
        assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"
    else:
        record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
        assert record.status == "CREATED" and count == 0 and day == b.day
    assert totals(b) == before  # No change slot had been reserved for this native result.
