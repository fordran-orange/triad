# ruff: noqa: F811
"""Resource grants reach real execution boundaries without expanding tool scope."""

import pytest
from test_day3_integration import active, engine  # noqa: F401
from test_resource_policy import session
from trading_core.contracts import AgentRunResult
from trading_core.providers.bounded_tools import BoundedTools
from trading_core.providers.native_agents import NativeRun
from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.runtime import SimulatedProvider

pytestmark = pytest.mark.integration


def test_runtime_continues_after_initial_time_with_progress(engine):
    class Progress(SimulatedProvider):
        def billing_source(self):
            return "LOCAL"

        def execute(self, request):
            self.resources.observe("test_result", "fixture-host-check-completed")
            self.resources.started -= 121
            return (
                AgentRunResult(
                    run_id=request.run_id,
                    status="NO_CHANGE_JUSTIFIED",
                    summary="Completed beyond initial time",
                ),
                1,
                1,
            )

    work, policy = active(engine)
    request = engine.request(work, policy, "IMPLEMENT", {})
    result = engine.runtime.execute(
        request, mode="SIMULATED", adapter=Progress("CODEX"), day=engine.day
    )
    assert result.summary == "Completed beyond initial time"
    assert engine.ledger.records("Usage")[0]["status"] == "SUCCESS"
    decisions = [
        r
        for r in engine.ledger.records("ResourceExtensionDecision")
        if r["run_id"] == request.run_id
    ]
    assert decisions[0]["decision"] == "ALLOW"
    assert engine.host.store.get(work.work_item_id).allowed_paths == work.allowed_paths


def test_runtime_records_resource_denial_instead_of_generic_failure(engine):
    class Idle(SimulatedProvider):
        def execute(self, request):
            self.resources.started -= 121
            return (
                AgentRunResult(
                    run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="No progress"
                ),
                1,
                1,
            )

    work, policy = active(engine)
    request = engine.request(work, policy, "IMPLEMENT", {})
    with pytest.raises(ResourceBlocked):
        engine.runtime.execute(request, mode="SIMULATED", adapter=Idle("CODEX"), day=engine.day)
    usage = engine.ledger.records("Usage")[0]
    assert usage["status"] == "BLOCKED_RESOURCE_LIMIT"
    assert usage["error_class"] == "ResourceExtensionBlocked"


def test_offline_tools_extend_then_reject_repeated_reads(engine):
    run = session(engine)
    # Lower the test's initial allocation before creating its independent session.
    from trading_core.resource_policy import ResourceSession
    from trading_core.work import uid

    run = ResourceSession(
        engine.ledger,
        run.request.model_copy(update={"run_id": uid()}),
        {**run.initial, ResourceType.TOOLS: 1},
        billing_source="LOCAL",
        day=engine.day,
    )
    broker = BoundedTools({"README.md": "# Actual offline fixture"}, max_calls=1, resources=run)
    try:
        assert "Actual offline" in broker.call("read_file", {"path": "README.md"})
        assert "Actual offline" in broker.call("read_file", {"path": "README.md"})
        with pytest.raises(ResourceBlocked):
            broker.call("read_file", {"path": "README.md"})
        assert run.tool_calls == 3
    finally:
        broker.cancel()


def test_native_guard_uses_shared_extension_and_cancellation(engine):
    run = session(engine)
    native = NativeRun([], lambda: None, resources=run)
    native.deadline = 0  # Obsolete fixed native ceiling cannot terminate a governed run.
    native.check()
    run.observe("authorized_read", "actual-snapshot")
    run.started -= 481
    native.check()
    assert run.time_allocation == 960
    native.cancel()
    with pytest.raises(Exception, match="DeadlineExceeded"):
        native.check()
