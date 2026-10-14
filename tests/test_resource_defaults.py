# ruff: noqa: F811
"""Versioned starting allocations preserve cost policy and immutable history."""

import pytest
from psycopg.types.json import Jsonb
from test_day3_integration import engine  # noqa: F401
from trading_core.contracts import AgentRunRequest, AgentRunResult, Limits
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.records import Records
from trading_core.resources import resource
from trading_core.work import WorkItem

pytestmark = pytest.mark.core


def test_reasoning_and_output_are_independent_initial_allocations():
    work = WorkItem(title="Initial envelope", description="Separate allocations")
    assert work.reasoning_budget == 8192
    assert work.compute_budget.model_dump() == {
        "max_input_chars": 24000,
        "max_output_tokens": 6144,
        "timeout_seconds": 480,
        "max_tool_calls": 60,
    }
    request = AgentRunRequest(
        agent_id="CODEX",
        work_item_id=work.work_item_id,
        mission_id=work.mission_id,
        context_packet={},
        role="REVIEW",
        objective=work.description,
        allowed_paths=work.allowed_paths,
        acceptance_criteria=work.acceptance_criteria,
        policy_decision={},
        required_output_schema=AgentRunResult.model_json_schema(),
    )
    assert request.reasoning_budget == 8192 and request.token_budget == 6144
    assert Limits().timeout_seconds == 480
    assert Limits().max_cloud_cost_day == 0


@pytest.mark.integration
def test_upgrade_preserves_legacy_agent_and_lowered_limits(engine):
    from test_intelligence_agents import setup_agents

    setup_agents(engine)
    store = engine.host.store
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM core.agent_instances WHERE id='CODEX'").fetchone()
        legacy = row["definition"]
        legacy["reasoning_budget"] = 2048
        legacy["budget"].update(
            max_output_tokens=2048, total_output_tokens=8192, timeout_seconds=120
        )
        # Reconstruct an old installation solely in this disposable fixture DB.
        conn.execute("DROP TRIGGER protect_agent_definition ON core.agent_instances")
        conn.execute(
            "UPDATE core.agent_instances SET definition=%s WHERE id='CODEX'", (Jsonb(legacy),)
        )
        conn.execute(
            resource("infrastructure/postgres/011_agent_lifecycle.sql").read_text(encoding="utf-8")
        )
        before = conn.execute("SELECT * FROM core.agent_instances WHERE id='CODEX'").fetchone()
        conn.execute("DELETE FROM core.schema_migrations WHERE version='013_resource_allocations'")
        conn.execute(
            "UPDATE core.autonomy_control SET payload=jsonb_set(jsonb_set(payload,'{limits,timeout_seconds}','120'),'{limits,max_output_tokens}','2048')"
        )
        conn.execute(
            resource("infrastructure/postgres/013_resource_allocations.sql").read_text(
                encoding="utf-8"
            )
        )
        assert (
            conn.execute("SELECT * FROM core.agent_instances WHERE id='CODEX'").fetchone() == before
        )
    effective = Agents(Records(store)).get("CODEX")
    assert effective["budget"]["max_output_tokens"] == 6144
    assert effective["reasoning_budget"] == 8192
    assert effective["recorded_budget"]["max_output_tokens"] == 2048
    assert effective["allowed_paths"] == legacy["allowed_paths"]
    assert effective["authority_tier"] == legacy["authority_tier"]
    control = engine.ledger.control()
    assert control["limits"]["max_cloud_cost_day"] == 0
    engine.ledger.operate("lower_limits", limits={"timeout_seconds": 30, "max_output_tokens": 512})
    engine.ledger.initialize()
    after = engine.ledger.control()
    assert after["limits"]["timeout_seconds"] == 30
    assert after["limits"]["max_output_tokens"] == 512
