"""Independent correction boundaries for transactional daily creation."""
# ruff: noqa: F811

import pytest
from products.triad.daily import Daily
from test_day3_integration import engine  # noqa: F401
from test_day8_daily_qa import reviewed
from trading_core.ledger import Ledger, Stopped
from trading_core.store import Store
from trading_core.work import WorkItem, uid

pytestmark = pytest.mark.integration


def test_daily_late_append_failure_rolls_back_parent_records_events_and_outbox(engine, monkeypatch):
    service = Daily(Store(engine.host.store.settings))
    cycle_id = uid()
    tables = ("work_items", "work_events", "projection_outbox", "intelligence_records")
    with service.host.store.connect() as conn:
        before = {
            t: conn.execute(f"SELECT count(*) AS n FROM core.{t}").fetchone()["n"] for t in tables
        }
    original = service.host.append

    def fail_transition(kind, *args, **kwargs):
        if kind == "DailyCycleTransition":
            raise RuntimeError("QA injected late transition failure")
        return original(kind, *args, **kwargs)

    monkeypatch.setattr(service.host, "append", fail_transition)
    with pytest.raises(RuntimeError, match="QA injected"):
        service.create(cycle_id=cycle_id)
    with service.host.store.connect() as conn:
        after = {
            t: conn.execute(f"SELECT count(*) AS n FROM core.{t}").fetchone()["n"] for t in tables
        }
    assert after == before


def test_store_create_ordinary_and_external_transaction_preserve_ownership_and_rollback(engine):
    store = Store(engine.host.store.settings, scope="triad")
    parent = store.create(WorkItem(owner="triad", title="Committed parent", description="QA"))
    child = WorkItem(
        owner="triad",
        parent_work_item_id=parent.work_item_id,
        title="Rolled back child",
        description="QA",
    )
    with pytest.raises(RuntimeError, match="roll back"), store.connect() as conn:
        assert store.create(child, conn=conn).work_item_id == child.work_item_id
        assert conn.execute(
            "SELECT 1 FROM core.work_items WHERE id=%s", (child.work_item_id,)
        ).fetchone()
        raise RuntimeError("roll back")
    with pytest.raises(KeyError):
        store.get(child.work_item_id)
    alien = Store(engine.host.store.settings).create(
        WorkItem(owner="aegis", title="Foreign parent", description="QA")
    )
    with store.connect() as conn, pytest.raises((PermissionError, KeyError)):
        store.create(
            child.model_copy(update={"parent_work_item_id": alien.work_item_id}), conn=conn
        )
    assert store.get(parent.work_item_id).model_dump() == parent.model_dump()


def test_store_create_parent_child_share_supplied_transaction(engine):
    store = Store(engine.host.store.settings, scope="triad")
    parent = WorkItem(owner="triad", title="Atomic parent", description="QA")
    child = WorkItem(
        owner="triad",
        parent_work_item_id=parent.work_item_id,
        title="Atomic child",
        description="QA",
    )
    with store.connect() as conn:
        store.create(parent, conn=conn)
        store.create(child, conn=conn)
    assert store.get(child.work_item_id).parent_work_item_id == parent.work_item_id


@pytest.mark.parametrize("control", ["parent_stop", "epoch_change"])
def test_publish_revalidates_parent_and_cycle_epoch(engine, control):
    service = Daily(Store(engine.host.store.settings))
    cycle, build, _, draft_id = reviewed(service)
    if control == "parent_stop":
        Ledger(Store(engine.host.store.settings, scope="triad")).operate(
            "stop", work_id=cycle.parent_work_item_id
        )
    else:
        service.host.ledger.operate("pause")
        service.host.ledger.operate("resume")
    with pytest.raises((PermissionError, Stopped)):
        service.publish(
            draft_id,
            build.implementation_run_id,
            classification="LOW",
            reason="Independent downgrade",
            reviewer_action="DOWNGRADE",
        )


def test_stopped_cycle_can_append_terminal_evidence(engine):
    service = Daily(Store(engine.host.store.settings))
    cycle = service.create()
    service.host.ledger.operate("kill")
    result = service.transition(cycle.cycle_id, "CANCELLED", ["actual kill"])
    assert result.status == "CANCELLED" and result.finished_at
