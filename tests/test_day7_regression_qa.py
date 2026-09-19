"""Independent compatibility checks for immutable legacy reasoning requests."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.intelligence.records import Records
from trading_core.work import WorkItem

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("grant", [512, 8192])
def test_legacy_reasoning_requests_preserve_grant_and_identity(engine, grant):
    work = engine.host.create(
        WorkItem(
            title="Independent legacy allocation boundary",
            description="Request decisions cannot change the immutable grant",
            assigned_agent="CODEX",
            reasoning_budget=grant,
        )
    )
    original = engine.host.store.get(work.work_item_id).model_dump(mode="json")
    for requested, expected in (
        (-1, "DENY"),
        (0, "ALLOW"),
        (grant, "ALLOW"),
        (grant + 1, "REQUIRE_HUMAN_APPROVAL"),
        (1000000, "REQUIRE_HUMAN_APPROVAL"),
        (2049, "ALLOW" if grant > 2049 else "REQUIRE_HUMAN_APPROVAL"),
    ):
        result = engine.request_reasoning(
            work.work_item_id, "CODEX", requested, "Offline independent boundary fixture"
        )
        assert result["decision"] == expected
        assert engine.host.store.get(work.work_item_id).model_dump(mode="json") == original
    requests = engine.ledger.records("ReasoningRequest")
    with pytest.raises(PermissionError, match="identity"):
        engine.request_reasoning(work.work_item_id, "GROK", 1, "Wrong executor")
    assert engine.ledger.records("ReasoningRequest") == requests
    assert not Records(engine.host.store).list("ResourceExtensionDecision")
    assert not engine.ledger.records("Usage")
