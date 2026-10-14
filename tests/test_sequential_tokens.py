"""Real disposable-store authority tests for advisory subscription tokens."""
# ruff: noqa: F811

import pytest
from products.triad.daily import Daily
from test_day3_integration import engine  # noqa: F401
from test_intelligence_capabilities import qa
from trading_core.contracts import AgentRunRequest, AgentRunResult
from trading_core.intelligence.contracts import ImplementationRun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.product_changes import activate, check_candidate
from trading_core.resource_policy import (
    DEFAULT_ALLOCATIONS,
    ResourceBlocked,
    ResourceSession,
    ResourceType,
)
from trading_core.store import Store
from trading_core.token_targets import advisory
from trading_core.work import WorkItem

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.fixture(autouse=True)
def test_image(monkeypatch):
    monkeypatch.setattr(
        "trading_core.product_changes.reviewed_test_image", lambda: "sha256:" + "a" * 64
    )


def setup(engine):
    records = Records(Store(engine.host.store.settings))
    impl = ImplementationRun(
        owner="core",
        builder="fixture-builder",
        provider="fixture",
        model="fixture",
        transport="fixture",
        base_commit="fixture-base",
        change_commit="fixture-change",
        files=("app/products/triad/sequential.py",),
        tests=("fixture",),
        evidence=("fixture-only",),
    )
    quality = Quality(records)
    quality.implementation(impl)
    quality.review(qa(impl, tests_repeated=("sha256:" + "a" * 64,)))
    policy = activate(records, impl.implementation_run_id, impl.change_commit)
    daily = Daily(records.store)
    cycle = daily.create()
    daily.transition(cycle.cycle_id, "INSPECTING", ["fixture"])
    records.append(
        "SequentialDailyProgram",
        {
            "cycle_id": cycle.cycle_id,
            "policy_id": policy,
            "parent_work_item_id": cycle.parent_work_item_id,
            "control_epoch": cycle.control_epoch,
            "order": ["CODEX", "CLAUDE", "GROK"],
        },
        owner="triad",
    )
    product = Store(engine.host.store.settings, scope="triad")
    from trading_core.execution import ExecutionServices

    service = ExecutionServices(product)
    work = service.host.create(
        WorkItem(
            owner="triad",
            mission_id=cycle.cycle_id,
            parent_work_item_id=cycle.parent_work_item_id,
            assigned_agent="CODEX",
            title="Fixture review",
            description="fixture",
            work_type="review",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=(),
            execution_permissions=("read",),
            review_required=False,
        )
    )
    work, decision = service.start_work(work)
    request = AgentRunRequest(
        agent_id="CODEX",
        work_item_id=work.work_item_id,
        mission_id=cycle.cycle_id,
        role="REVIEW",
        objective="fixture",
        context_packet={},
        allowed_tools=("read_file",),
        allowed_paths=(),
        acceptance_criteria=("fixture",),
        execution_permissions=("read",),
        policy_decision=decision.model_dump(mode="json"),
        required_output_schema=AgentRunResult.model_json_schema(),
        control_epoch=cycle.control_epoch,
    )
    return records, service, request, cycle


def test_large_output_reasoning_and_context_are_observations_not_denials(engine):
    records, _service, request, _cycle = setup(engine)
    run = ResourceSession(
        records.ledger, request, DEFAULT_ALLOCATIONS, billing_source="SUBSCRIPTION"
    )
    for kind in (ResourceType.INPUT, ResourceType.OUTPUT, ResourceType.REASONING):
        for n in (100000, 200000, 500000):
            assert run.ensure(kind, n) == n
    assert len(records.list("TokenTargetObservation")) == 9
    assert not records.list("ResourceExtensionDecision")
    run.started -= 500
    with pytest.raises(ResourceBlocked):
        run.check_time()


def test_exemption_requires_program_parent_billing_and_epoch(engine):
    records, _service, request, cycle = setup(engine)
    assert advisory(records.ledger, request, "SUBSCRIPTION")
    for billing in ("API", "LOCAL", "UNKNOWN"):
        assert not advisory(records.ledger, request, billing)
    assert not advisory(
        records.ledger,
        request.model_copy(update={"control_epoch": cycle.control_epoch + 1}),
        "SUBSCRIPTION",
    )
    assert not advisory(
        records.ledger, request.model_copy(update={"mission_id": "forged"}), "SUBSCRIPTION"
    )
    # A legacy/staging implementation does not receive advisory workspace budgets.
    assert not advisory(
        records.ledger, request.model_copy(update={"role": "IMPLEMENT"}), "SUBSCRIPTION"
    )
    from trading_core.product_workspace_grant import TOOLS

    # Forging the workspace profile still requires its canonical assignment/grant.
    with pytest.raises(PermissionError, match="workspace assignment required"):
        advisory(
            records.ledger,
            request.model_copy(update={"role": "IMPLEMENT", "allowed_tools": TOOLS}),
            "SUBSCRIPTION",
        )
    Daily(records.store).transition(cycle.cycle_id, "BLOCKED", ["fixture"])
    assert not advisory(records.ledger, request, "SUBSCRIPTION")


def test_offline_tests_include_unchanged_product_dependency(engine):
    result = check_candidate(
        {
            "app/products/triad/analytics/helper.py": "def add(a,b): return a+b\n",
            "tests/products/triad/test_add.py": "import unittest\nfrom products.triad.analytics.helper import add\nclass TestAdd(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,3),5)\n",
        },
        lambda: None,
    )
    assert '"unit_tests": 1' in result["stdout"]


def test_runtime_accepts_usage_beyond_all_token_targets(engine):
    from trading_core.runtime import SimulatedProvider

    records, service, request, _cycle = setup(engine)
    with records.store.connect() as conn:
        conn.execute(
            "UPDATE core.autonomy_control SET payload=jsonb_set(jsonb_set(payload,'{daily_execution_caps,SUBSCRIPTION}','true'::jsonb),'{limits,max_tokens_day}','0'::jsonb) WHERE id=1"
        )

    class Large(SimulatedProvider):
        reasoning_tokens = 500000

        def billing_source(self):
            return "SUBSCRIPTION"

        def execute(self, request):
            return (
                AgentRunResult(
                    run_id=request.run_id,
                    status="NO_CHANGE_JUSTIFIED",
                    summary="Fixture large usage",
                ),
                300000,
                200000,
            )

    result = service.runtime.execute(request, mode="SIMULATED", adapter=Large("CODEX"))
    assert result.summary == "Fixture large usage"
    usage = records.ledger.records("Usage")[-1]
    assert usage["status"] == "SUCCESS" and usage["output_tokens"] == 200000
    assert not records.list("ResourceExtensionDecision")


def test_reviewed_dependency_image_runs_fastapi_tests(engine):
    result = check_candidate(
        {
            "app/products/triad/product_app.py": "from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health(): return {'status':'ok'}\n",
            "tests/products/triad/test_health.py": "import unittest\nfrom fastapi.testclient import TestClient\nfrom products.triad.product_app import app\nclass Health(unittest.TestCase):\n def test_health(self): self.assertEqual(TestClient(app).get('/health').json(),{'status':'ok'})\n",
        },
        lambda: None,
        "sha256:b8aad511c92211a227277688aa4423555ff9feb700d2de9c17759a6a5add564e",
    )
    assert result["executed_tests"] == 1 and result["test_status"] == "PASSED"
