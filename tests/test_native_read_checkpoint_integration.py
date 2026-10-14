"""Actual database checkpoint recovery retains author, usage and cycle identity."""
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


@pytest.mark.parametrize("cleanup", [True, False])
def test_real_stopped_native_read_checkpoint(engine, monkeypatch, cleanup):
    host = Records(Store(engine.host.store.settings))
    daily = Daily(host.store)
    cycle = daily.create()
    day = now().astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    base = engine.git.git("rev-parse", "HEAD")
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
    for state in ("INSPECTING", "SELECTING"):
        daily.transition(cycle.cycle_id, state, ["fixture"])
    works = []
    for agent, status in (("CODEX", State.COMPLETED), ("CLAUDE", State.FAILED)):
        work = engine.host.create(
            WorkItem(
                owner="triad",
                mission_id=cycle.cycle_id,
                parent_work_item_id=cycle.parent_work_item_id,
                assigned_agent=agent,
                work_type="review",
                authority_tier=0,
                title="Read-only fixture",
                description="No provider execution",
                review_required=False,
                execution_permissions=("read",),
                allowed_tools=("read_file",),
            )
        )
        for state in (State.VALIDATING, State.APPROVED, State.ASSIGNED, State.IN_PROGRESS, status):
            work = engine.host.advance(work, state, "fixture")
        works.append(work)
        daily.product.ledger.put(
            "AgentRunRequest",
            {
                "run_id": work.work_item_id,
                "work_item_id": work.work_item_id,
                "mission_id": cycle.cycle_id,
                "agent_id": agent,
                "role": "REVIEW",
                "execution_permissions": ["read"],
                "allowed_tools": ["read_file"],
                "control_epoch": cycle.control_epoch,
            },
            work_id=work.work_item_id,
        )
    author, reviewer = works
    proposal = {
        "outcome": "NO_CHANGE",
        "title": "Fixture only",
        "problem": "No inference",
        "change": "None",
        "files": [],
        "acceptance": [],
        "evidence": ["Fixture"],
    }
    host.append(
        "ProductProposal",
        {"mission_id": cycle.cycle_id, "proposer": "CODEX", "proposal": proposal, "attempt": 1},
        owner="triad",
    )
    host.append(
        "ProductPlanningContext",
        {"mission_id": cycle.cycle_id, "proposer": "CODEX", "base_commit": base},
        owner="triad",
    )
    daily.product.ledger.put(
        "AgentRunResult",
        {
            "run_id": author.work_item_id,
            "analysis_artifacts": [proposal],
        },
        work_id=author.work_item_id,
    )
    daily.product.append(
        "RoutingDecision",
        {
            "selected": {
                "agent_id": "CLAUDE",
                "provider": "anthropic",
                "transport": "claude_code_cli",
            }
        },
        owner="triad",
        identifier="route-" + reviewer.work_item_id,
    )
    daily.product.ledger.put(
        "TransportRun",
        {
            "run_id": reviewer.work_item_id,
            "work_item_id": reviewer.work_item_id,
            "agent": "CLAUDE",
            "provider": "anthropic",
            "transport": "claude_code_cli",
            "status": "DEGRADED",
            "error_class": "NativeReadEvidenceMissing",
            "completed_at": now().isoformat(),
        },
        work_id=reviewer.work_item_id,
    )
    daily.product.ledger.event(
        "provider_failed",
        reviewer.work_item_id,
        run_id=reviewer.work_item_id,
        error_class="NativeReadEvidenceMissing",
    )
    if cleanup:
        daily.product.ledger.event(
            "native_executor_evidence",
            reviewer.work_item_id,
            run_id=reviewer.work_item_id,
            boundary="DOCKER_OFFLINE_TOOLS",
            denials=0,
            calls=[{"tool": "read_file", "path": "evidence/part.txt"}],
        )
    daily.product.ledger.reserve("CLAUDE", reviewer.work_item_id, tokens=123, seconds=2, day=day)
    daily.transition(
        cycle.cycle_id,
        "BLOCKED",
        ["ProviderError"],
        failures=({"code": "ProviderError", "message": "NativeReadEvidenceMissing"},),
    )
    flow = NS(s=NS(daily=daily, git=engine.git), policy={"id": "fixture"})
    flow.guard = lambda _: daily.product.ledger.guard(epoch=cycle.control_epoch)
    monkeypatch.setattr(
        "products.triad.sequential_recovery.health", lambda revision: {"loaded_revision": revision}
    )
    with host.store.connect() as conn:
        before = conn.execute("SELECT * FROM core.autonomy_daily WHERE day=%s", (day,)).fetchone()
    if not cleanup:
        with pytest.raises(PermissionError, match="Canonical stopped native read"):
            resume_patch_failure(flow, cycle.cycle_id, read_failure=True)
        assert daily.current(cycle.cycle_id)["status"] == "BLOCKED"
    else:
        recovered, count, original_day = resume_patch_failure(
            flow, cycle.cycle_id, read_failure=True
        )
        assert recovered.cycle_id == cycle.cycle_id and count == 0 and original_day == day
        assert recovered.parent_work_item_id == cycle.parent_work_item_id
        assert flow.saved_selection["author_work_id"] == author.work_item_id
        assert flow.saved_selection["failed_work_id"] == reviewer.work_item_id
        with pytest.raises(PermissionError):
            resume_patch_failure(flow, cycle.cycle_id, read_failure=True)
    with host.store.connect() as conn:
        after = conn.execute("SELECT * FROM core.autonomy_daily WHERE day=%s", (day,)).fetchone()
    assert after == before  # No inference credits or change slots are refunded.
