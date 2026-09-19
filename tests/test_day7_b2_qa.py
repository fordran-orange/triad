"""Independent B2 continuation and native accounting probes; no provider inference."""
# ruff: noqa: F811

import threading
import time

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.contracts import AgentRunResult
from trading_core.gateway import ToolGateway
from trading_core.providers.codex_executor import CodexExecutor
from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.runtime import SimulatedProvider
from trading_core.work import ComputeBudget, WorkItem


def work_request(engine, *, timeout=10, context=None):
    work = engine.host.create(
        WorkItem(
            owner="triad",
            title="Independent B2 probe",
            description="Read bounded fixture",
            assigned_agent="CODEX",
            authority_tier=2,
            allowed_paths=("docs",),
            reasoning_budget=64,
            compute_budget=ComputeBudget(
                max_input_chars=4000,
                max_output_tokens=64,
                timeout_seconds=timeout,
                max_tool_calls=3,
            ),
        )
    )
    work, policy = engine.start_work(work)
    return work, engine.request(work, policy, "IMPLEMENT", context or {})


class ReadProgress(SimulatedProvider):
    def __init__(self, work, root, *, delay=0, outputs=1):
        super().__init__("CODEX")
        self.work, self.root, self.delay, self.outputs = work, root, delay, outputs
        self.invocations = 0
        self.cancelled = threading.Event()

    def billing_source(self):
        return "LOCAL"

    def execute(self, request):
        self.invocations += 1
        ToolGateway(self.work, self.root, resources=self.resources).read("docs/evidence.md")
        self.cancelled.wait(self.delay)
        return (
            AgentRunResult(
                run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Fixture finished"
            ),
            1,
            self.outputs,
        )

    def cancel(self):
        self.cancelled.set()


def prepare_file(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/evidence.md").write_text("Actual bounded fixture evidence", encoding="utf-8")


@pytest.mark.integration
def test_elapsed_time_extension_continues_same_adapter(engine, tmp_path):
    prepare_file(tmp_path)
    work, request = work_request(engine, timeout=1)
    adapter = ReadProgress(work, tmp_path, delay=1.3)
    started = time.monotonic()
    result = engine.runtime.execute(request, mode="SIMULATED", adapter=adapter, day=engine.day)
    assert time.monotonic() - started > 1
    assert adapter.invocations == 1 and not adapter.cancelled.is_set()
    assert result.summary == "Fixture finished"
    decisions = adapter.resources.host.list("ResourceExtensionDecision")
    assert any(
        d["resource_type"] == ResourceType.TIME and d["decision"] == "ALLOW" for d in decisions
    )
    assert engine.host.store.get(work.work_item_id).compute_budget.timeout_seconds == 1


@pytest.mark.integration
def test_runtime_output_extension_uses_authorized_file_progress(engine, tmp_path):
    prepare_file(tmp_path)
    work, request = work_request(engine)
    adapter = ReadProgress(work, tmp_path, outputs=65)
    engine.runtime.execute(request, mode="SIMULATED", adapter=adapter, day=engine.day)
    assert adapter.resources.allocation(ResourceType.OUTPUT) == 128
    assert engine.ledger.records("Usage")[0]["status"] == "SUCCESS"
    assert engine.ledger.records("Usage")[0]["output_tokens"] == 65


@pytest.mark.integration
def test_input_extension_allows_bounded_context_before_adapter(engine):
    work, request = work_request(engine, context={"bounded_fixture": "x" * 4500})

    class NoTools(SimulatedProvider):
        def billing_source(self):
            return "LOCAL"

        def execute(self, request):
            assert self.resources.allocation(ResourceType.INPUT) == 8000
            return (
                AgentRunResult(
                    run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Context accepted"
                ),
                1,
                1,
            )

    engine.runtime.execute(request, mode="SIMULATED", adapter=NoTools("CODEX"), day=engine.day)
    assert engine.host.store.get(work.work_item_id).compute_budget.max_input_chars == 4000


@pytest.mark.parametrize("method", ["fs/getMetadata", "fs/readDirectory"])
def test_codex_workspace_operations_consume_shared_tool_budget(method):
    class Counter:
        def __init__(self):
            self.calls = 0

        def consume_tool(self):
            self.calls += 1

    counter = Counter()
    executor = CodexExecutor({"README.md": "fixture"}, guard=lambda: None, resources=counter)
    executor.mediate({"id": 1, "method": method, "params": {"path": "/workspace/README.md"}})
    assert counter.calls == 1


@pytest.mark.integration
def test_failed_utf8_read_does_not_create_host_progress(engine, tmp_path):
    work, request = work_request(engine)
    from trading_core.resource_policy import DEFAULT_ALLOCATIONS, ResourceSession

    run = ResourceSession(
        engine.ledger, request, DEFAULT_ALLOCATIONS, billing_source="LOCAL", day=engine.day
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/evidence.md").write_bytes(b"invalid text \xff")
    with pytest.raises(UnicodeDecodeError):
        ToolGateway(work, tmp_path, resources=run).read("docs/evidence.md")
    assert not run.host.list("ResourceProgress")


@pytest.mark.integration
def test_api_input_extension_blocks_before_provider_execution(engine):
    _, request = work_request(engine, context={"bounded_fixture": "x" * 4500})

    class NoCall(SimulatedProvider):
        invoked = False

        def billing_source(self):
            return "API"

        def execute(self, request):
            self.invoked = True
            raise AssertionError("Unapproved extra API context cannot run")

    adapter = NoCall("CODEX")
    with pytest.raises(ResourceBlocked) as failure:
        engine.runtime.execute(request, mode="SIMULATED", adapter=adapter, day=engine.day)
    assert not adapter.invoked
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"
    assert engine.ledger.records("Usage")[0]["status"] == "BLOCKED_RESOURCE_LIMIT"


@pytest.mark.integration
def test_specialist_output_extension_requires_new_reviewed_grant(engine):
    from test_intelligence_agents import child, setup_agents
    from test_intelligence_agents import request as specialist_request

    manager, services, parent = setup_agents(engine)
    identifier = manager.request(specialist_request(parent))["agent_id"]
    work = child(manager, services, parent, identifier)
    from test_day6_qa_b import runtime_request

    envelope = runtime_request(
        services, work, role="SUPPORT", allowed_tools=(), execution_permissions=("read",)
    )

    class Specialist(SimulatedProvider):
        def billing_source(self):
            return "LOCAL"

        def execute(self, request):
            self.resources.observe("test_result", "synthetic host quota probe")
            return (
                AgentRunResult(
                    run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="Quota probe"
                ),
                1,
                513,
            )

    with pytest.raises(ResourceBlocked) as failure:
        services.runtime.execute(
            envelope, mode="SIMULATED", adapter=Specialist("CODEX"), day=engine.day
        )
    assert failure.value.decision["decision"] == "REQUIRE_HUMAN_APPROVAL"
    assert "Specialist lifetime" in failure.value.decision["reason"]
    assert manager.get(identifier)["tokens_reserved"] == 512
