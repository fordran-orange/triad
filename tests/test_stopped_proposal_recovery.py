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

pytestmark = [pytest.mark.integration, pytest.mark.triad]
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
        "context_packet": {
            "base_commit": base,
            "schema": {"title": "CurrentProposal"},
            "product_planning": {
                "cycle_id": cycle.cycle_id,
                "shared_core": {"source_revision": base},
                "application_plan": {"source_revision": base},
            },
        },
    }
    if variant == "request_write":
        payload["allowed_tools"].append("write_artifact")
    elif variant == "missing_context":
        payload.pop("context_packet")
    elif variant == "context_core":
        payload["context_packet"]["product_planning"]["shared_core"]["source_revision"] = "0" * 40
    elif variant == "context_cycle":
        payload["context_packet"]["product_planning"]["cycle_id"] = "other-cycle"
    elif variant == "context_schema":
        payload["context_packet"]["schema"]["title"] = "AcceptanceAssessment"
    host.ledger.put("AgentRunRequest", payload, work_id=work.work_item_id)
    # Genuine telemetry is bound by payload/run, not the legacy SQL work column.
    # It is not native execution/transport evidence and cannot veto safe recovery.
    host.append(
        "ResourceProgress", {"run_id": run, "work_item_id": work.work_item_id}, owner="triad"
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
    assert not b.host.list("ProductPlanningContext")
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
        "missing_context",
        "context_core",
        "context_cycle",
        "context_schema",
    ],
)
def test_unproved_planning_recovery_has_no_effect(stopped_proposal, tamper):
    b = stopped_proposal
    before = totals(b)
    with pytest.raises(PermissionError):
        resume_patch_failure(b.flow, b.cycle.cycle_id, read_failure=True)
    assert totals(b) == before and b.daily.current(b.cycle.cycle_id)["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "owner",
        "action",
        "work",
        "cycle",
        "prefix",
        "health",
        "day",
        "revision",
        "refund_bool",
        "reservation",
        "failure",
        "after_turn",
        "implementation",
        "build",
        "merge",
    ],
)
def test_settled_predecessor_requires_exact_host_action(engine, tamper):
    from products.triad.sequential_stopped_proposal import settled_failed_turn_work

    host = Records(Store(engine.host.store.settings))
    daily = Daily(host.store)
    cycle = daily.create()
    base = engine.git.clean_baseline()
    day = now().astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    host.append(
        "SequentialDailyProgram", {"cycle_id": cycle.cycle_id, "local_date": day}, owner="triad"
    )
    work = engine.host.create(
        WorkItem(
            owner="triad",
            mission_id=cycle.cycle_id,
            parent_work_item_id=cycle.parent_work_item_id,
            assigned_agent="CODEX",
            work_type="development",
            authority_tier=2,
            execution_permissions=("read", "write_code"),
            allowed_tools=("read_file", "write_artifact"),
            title="Disposable failed predecessor",
            description="No provider execution",
        )
    )
    work = engine.host.advance(work, State.VALIDATING, "fixture")
    work = engine.host.advance(work, State.FAILED, "fixture")
    host.ledger.reserve("CODEX", work.work_item_id, improvement=True, day=day)
    with host.store.connect() as conn:
        reservation = conn.execute(
            "SELECT id FROM core.day3_records WHERE kind='BudgetReservation' AND work_item_id=%s",
            (work.work_item_id,),
        ).fetchone()["id"]
        # This fixture simulates the already settled slot; recovery must never
        # decrement it again. Production settlement itself is tested separately.
        conn.execute("UPDATE core.autonomy_daily SET changes=changes-1 WHERE day=%s", (day,))
    failures = [{"code": "ValidationError", "message": "fixture rejected unapplied plan"}]
    host.append(
        "CycleRecord",
        {"cycle_id": cycle.cycle_id, "status": "BLOCKED", "failures": failures},
        owner="triad",
    )
    payload = {
        "action": "resume_unapplied_product_patch",
        "cycle_id": cycle.cycle_id,
        "failed_work_item_id": work.work_item_id,
        "retained_turn_ids": [],
        "day": day,
        "revision": base,
        "health": {
            "loaded_revision": base,
            "development_provider_gate": "PASS",
            "routes": {"/core": 200},
        },
        "released_change_slots": 1,
        "reservation_id": reservation,
        "prior_failure": failures,
    }
    bad = {
        "action": ("action", "unrelated"),
        "work": ("failed_work_item_id", "other"),
        "cycle": ("cycle_id", "other"),
        "prefix": ("retained_turn_ids", ["other"]),
        "day": ("day", "2001-01-01"),
        "revision": ("revision", "0" * 40),
        "refund_bool": ("released_change_slots", True),
        "reservation": ("reservation_id", "other"),
        "failure": ("prior_failure", []),
    }
    if tamper in bad:
        key, value = bad[tamper]
        payload[key] = value
    if tamper == "health":
        payload["health"]["routes"]["/core"] = 503
    turn_payload = {"agent": "CODEX", "verified_revision": base, "mission_id": cycle.cycle_id}
    if tamper == "after_turn":
        turn_id = host.append("ProductTurn", turn_payload, owner="triad")
    host.append(
        "ControlAction",
        payload,
        owner="triad" if tamper == "owner" else "core",
        identifier="patch-recovery-" + work.work_item_id,
    )
    if tamper != "after_turn":
        turn_id = host.append("ProductTurn", turn_payload, owner="triad")
    if tamper in {"implementation", "build", "merge"}:
        kind = {
            "implementation": "ImplementationRun",
            "build": "ProductBuild",
            "merge": "ProductMerge",
        }[tamper]
        host.append(kind, {"work_item_id": work.work_item_id}, owner="triad")
    turns = [host.get(turn_id)]
    prior = {"parent_work_item_id": cycle.parent_work_item_id}
    with host.store.connect() as conn:
        before = conn.execute(
            "SELECT changes FROM core.autonomy_daily WHERE day=%s", (day,)
        ).fetchone()
        if tamper:
            with pytest.raises(PermissionError):
                settled_failed_turn_work(
                    daily, cycle.cycle_id, prior, [work], turns, conn, engine.git
                )
        else:
            assert settled_failed_turn_work(
                daily, cycle.cycle_id, prior, [work], turns, conn, engine.git
            ) == {work.work_item_id}
        assert (
            before
            == conn.execute(
                "SELECT changes FROM core.autonomy_daily WHERE day=%s", (day,)
            ).fetchone()
        )
