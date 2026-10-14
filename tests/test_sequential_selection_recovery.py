"""Routing failure recovery never replays a write or discards independent findings."""

# ruff: noqa: F811
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from products.triad.daily import Daily
from products.triad.sequential import SequentialCycle
from products.triad.sequential_recovery import SELECTION_ERROR, resume_patch_failure
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import State, WorkItem, now

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.fixture
def selection(engine, monkeypatch):
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
    daily.transition(cycle.cycle_id, "INSPECTING", ["fixture"])
    daily.transition(cycle.cycle_id, "SELECTING", ["fixture"])
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=cycle.cycle_id,
            parent_work_item_id=cycle.parent_work_item_id,
            assigned_agent="CODEX",
            work_type="review",
            authority_tier=0,
            execution_permissions=("read",),
            allowed_tools=("read_file",),
            title="Fixture proposal",
            description="Read-only fixture",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture artifact rejection")
    host.ledger.reserve("CODEX", work.work_item_id, tokens=123, day=day)
    host.ledger.put(
        "AgentRunRequest",
        {
            "work_item_id": work.work_item_id,
            "mission_id": cycle.cycle_id,
            "agent_id": "CODEX",
            "role": "REVIEW",
            "execution_permissions": ["read"],
            "allowed_tools": ["read_file"],
            "control_epoch": cycle.control_epoch,
        },
        work_id=work.work_item_id,
    )
    host.append(
        "ProductPlanningContext",
        {
            "mission_id": cycle.cycle_id,
            "proposer": "CODEX",
            "base_commit": engine.git.clean_baseline(),
        },
        owner="triad",
    )
    daily.transition(
        cycle.cycle_id,
        "BLOCKED",
        ["PermissionError"],
        failures=({"code": "PermissionError", "message": SELECTION_ERROR},),
    )
    flow = NS(s=NS(daily=daily, git=engine.git), policy={"id": "fixture"})
    flow.guard = lambda _: daily.product.ledger.guard(
        work_id=cycle.parent_work_item_id, epoch=cycle.control_epoch
    )
    monkeypatch.setattr(
        "products.triad.sequential_recovery.health", lambda r: {"loaded_revision": r}
    )
    return NS(flow=flow, daily=daily, host=host, cycle=cycle, work=work, day=day)


def test_selection_recovery_preserves_usage_and_cannot_replay(selection):
    b = selection

    def totals():
        with b.host.store.connect() as c:
            return c.execute("SELECT * FROM core.autonomy_daily WHERE day=%s", (b.day,)).fetchone()

    before = totals()
    record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert record.status == "CREATED" and count == 0 and day == b.day
    assert totals() == before
    assert b.host.store.get(b.work.work_item_id).status == State.FAILED
    assert b.host.ledger.records("ControlAction")[0]["released_change_slots"] == 0
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)


@pytest.mark.parametrize(
    "tamper",
    [
        "development",
        "approval",
        "policy",
        "epoch",
        "product_drift",
        "write_review",
        "write_research",
        "checkpoint",
        "reservation",
        "request",
    ],
)
def test_selection_rejects_unproven_recovery(selection, tamper):
    b = selection
    if tamper == "development":
        b.host.store.create(
            WorkItem(
                owner="triad",
                mission_id=b.cycle.cycle_id,
                assigned_agent="CODEX",
                work_type="development",
                title="Write",
                description="fixture",
            )
        )
    elif tamper == "approval":
        b.host.append(
            "ProductTurnApproval", {"cycle_id": b.cycle.cycle_id, "builder": "CODEX"}, owner="triad"
        )
    elif tamper == "policy":
        b.flow.policy["id"] = "different"
    elif tamper == "epoch":
        b.host.ledger.operate("pause")
    elif tamper in {"write_review", "write_research"}:
        b.host.store.create(
            WorkItem(
                owner="triad",
                mission_id=b.cycle.cycle_id,
                parent_work_item_id=b.cycle.parent_work_item_id,
                assigned_agent="GROK",
                work_type="review" if tamper == "write_review" else "research",
                execution_permissions=("write_research",),
                title="Unknown write",
                description="fixture",
            )
        )
    elif tamper == "checkpoint":
        b.host.append(
            "ProductBuildCheckpoint",
            {
                "mission_id": b.cycle.cycle_id,
                "phase": "APPLIED",
                "git": {"change_commit": "unknown"},
            },
            owner="triad",
        )
    elif tamper == "reservation":
        b.host.ledger.reserve("CODEX", b.work.work_item_id, improvement=True, day=b.day)
    elif tamper == "request":
        with b.host.store.connect() as conn:
            conn.execute(
                "UPDATE core.day3_records SET payload=jsonb_set(payload,'{role}','\"IMPLEMENT\"'::jsonb) WHERE kind='AgentRunRequest' AND work_item_id=%s",
                (b.work.work_item_id,),
            )
    else:
        original = b.flow.s.git.git

        def changed(*args, **kw):
            if args[:2] == ("diff", "--name-only"):
                return "app/products/triad/product_app.py"
            return original(*args, **kw)

        b.flow.s.git.git = changed
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id)
    assert b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"


def test_proposal_recovery_reuses_previous_independent_corrections():
    flow = object.__new__(SequentialCycle)
    previous = {
        "proposer": "CLAUDE",
        "decision": "REQUEST_CHANGES",
        "summary": "Fix ties",
        "findings": ["Test a tied maximum drawdown"],
        "proposal": {"title": "Previous"},
    }
    flow.s = NS(rows=lambda *a: [previous])

    def attempt(mission, agent, feedback, number):
        assert feedback[0]["findings"] == previous["findings"]
        assert feedback[0]["proposal"] == previous["proposal"]
        return "new proposal", "independent approval", {}

    flow.proposal_attempt = attempt
    assert flow.propose("cycle", "CLAUDE") == ("new proposal", "independent approval")
