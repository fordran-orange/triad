"""Independent legacy-lineage promotion control regression; disposable DB only."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from test_day6_qa_b import reviewed_promotion
from test_intelligence_agents import request, setup_agents
from trading_core.execution import ExecutionServices
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.records import Records
from trading_core.ledger import Stopped
from trading_core.store import Store
from trading_core.work import ComputeBudget, WorkItem

pytestmark = pytest.mark.integration


def test_current_aegis_pause_blocks_promotion_of_legacy_p2p_specialist(engine):
    setup_agents(engine)
    host_services = ExecutionServices(engine.host.store)
    parent = host_services.host.create(
        WorkItem(
            owner="p2p",
            title="Historical parent",
            description="Preserved temporary specialist",
            assigned_agent="CODEX",
            authority_tier=0,
            allowed_tools=("read_file",),
            allowed_paths=("docs/improvements",),
            execution_permissions=("read",),
            compute_budget=ComputeBudget(max_output_tokens=2048, timeout_seconds=120),
            reasoning_budget=1024,
        )
    )
    parent, _ = host_services.start_work(parent)
    current = ExecutionServices(Store(engine.host.store.settings, scope="aegis"))
    manager = Agents(Records(current.host.store))
    agent = manager.request(request(parent))["agent_id"]
    assert manager.get(agent)["owner"] == "p2p"
    host, proposal, governance = reviewed_promotion(engine, manager, agent, evidence_owner="p2p")
    current.ledger.operate("pause")
    with pytest.raises((Stopped, PermissionError), match="[Pp]roduct.*paused"):
        host.promote(proposal, governance.implementation_run_id, governance.change_commit)
