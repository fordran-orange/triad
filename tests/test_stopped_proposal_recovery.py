"""Disposable database proof of a rejected read-only planning result."""

# ruff: noqa: F811
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest
from products.triad.daily import Daily
from products.triad.sequential_recovery import resume_patch_failure
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.store import Store
from trading_core.work import State, WorkItem, now

pytestmark = pytest.mark.integration
ERROR = "NativeProposalEvidenceMismatch"


@pytest.fixture
def stopped_proposal(engine, monkeypatch, request):
    variant = getattr(request.node, "callspec", None)
    variant = variant.params.get("tamper") if variant else None
    host = Records(Store(engine.host.store.settings))
    daily = Daily(host.store)
    cycle = daily.create()
    day = now().astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    base = engine.git.clean_baseline()
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
    host.append(
        "ProductTurnStarted",
        {"mission_id": cycle.cycle_id, "agent": "CLAUDE" if variant == "wrong_turn" else "CODEX"},
        owner="triad",
    )
    daily.transition(cycle.cycle_id, "INSPECTING", ["fixture"])
    if variant == "wrong_stage":
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
            title="Read-only planning fixture",
            description="No provider execution",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture result rejected")
    host.ledger.reserve("CODEX", work.work_item_id, tokens=123, day=day)
    run = "failed-read-only-plan"
    payload = {
        "run_id": run,
        "work_item_id": work.work_item_id,
        "mission_id": cycle.cycle_id,
        "agent_id": "CODEX",
        "role": "REVIEW",
        "execution_permissions": ["read"],
        "allowed_tools": ["read_file"],
        "control_epoch": cycle.control_epoch,
    }
    if variant == "request_write":
        payload["allowed_tools"].append("write_artifact")
    host.ledger.put("AgentRunRequest", payload, work_id=work.work_item_id)
    host.append(
        "ProductPlanningContext",
        {"mission_id": cycle.cycle_id, "proposer": "CODEX", "base_commit": base},
        owner="triad",
    )
    host.append(
        "CapabilityRoutingDecision",
        {
            "selected": {
                "agent_id": "CLAUDE" if variant == "route" else "CODEX",
                "provider": "openai",
                "transport": "codex_cli",
            }
        },
        owner="triad",
        identifier="route-" + work.work_item_id,
    )
    host.ledger.event("provider_failed", work.work_item_id, run_id=run, error_class=ERROR)
    if variant != "missing_native":
        host.ledger.event(
            "native_executor_evidence",
            work.work_item_id,
            run_id="another-run" if variant == "run" else run,
            boundary="DOCKER_OFFLINE_TOOLS",
            denials=True if variant == "denial_bool" else 1 if variant == "denials" else 0,
            calls=[
                {
                    "tool": "write_file" if variant == "write_call" else "read_file",
                    "path": "evidence.json",
                }
            ],
            usage_scope="PARTIAL_COMPLETED_TURNS" if variant == "partial_usage" else "COMPLETE",
            input_tokens=100,
            output_tokens=10,
        )
    host.ledger.put(
        "TransportRun",
        {
            "run_id": run,
            "work_item_id": work.work_item_id,
            "agent": "CODEX",
            "provider": "openai",
            "transport": "codex_cli",
            "status": "RUNNING" if variant == "live_transport" else "DEGRADED",
            "error_class": ERROR,
            "completed_at": None if variant == "live_transport" else now().isoformat(),
        },
        work_id=work.work_item_id,
    )
    if variant == "result":
        host.ledger.put("AgentRunResult", {"run_id": run}, work_id=work.work_item_id)
    if variant == "reservation":
        host.ledger.reserve("CODEX", work.work_item_id, improvement=True, day=day)
    daily.transition(
        cycle.cycle_id,
        "BLOCKED",
        ["ProviderError"],
        failures=({"code": "ProviderError", "message": ERROR},),
    )
    flow = NS(s=NS(daily=daily, git=engine.git), policy={"id": "fixture"})
    flow.guard = lambda _: daily.product.ledger.guard(
        work_id=cycle.parent_work_item_id, epoch=cycle.control_epoch
    )
    monkeypatch.setattr(
        "products.triad.sequential_recovery.health", lambda r: {"loaded_revision": r}
    )
    return NS(flow=flow, daily=daily, host=host, cycle=cycle, work=work, day=day)


def totals(b):
    with b.host.store.connect() as conn:
        return conn.execute(
            "SELECT changes,reserved_tokens,reserved_seconds FROM core.autonomy_daily WHERE day=%s",
            (b.day,),
        ).fetchone()


def test_stopped_planning_recovery_keeps_inference_and_requires_new_review(stopped_proposal):
    b = stopped_proposal
    before = totals(b)
    record, count, day = resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)
    assert record.status == "CREATED" and count == 0 and day == b.day
    assert totals(b) == before
    assert b.host.store.get(b.work.work_item_id).status == State.FAILED
    action = b.host.ledger.records("ControlAction")[-1]
    assert (
        action["action"] == "resume_stopped_read_proposal"
        and action["retained_proposal_id"] is None
    )
    assert action["released_change_slots"] == 0
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)


@pytest.mark.parametrize(
    "tamper",
    [
        "wrong_turn",
        "wrong_stage",
        "request_write",
        "route",
        "missing_native",
        "run",
        "denial_bool",
        "denials",
        "write_call",
        "partial_usage",
        "live_transport",
        "result",
        "reservation",
    ],
)
def test_unproved_planning_recovery_has_no_effect(stopped_proposal, tamper):
    b = stopped_proposal
    before = totals(b)
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)
    assert totals(b) == before and b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"
