"""Relay lifecycle fixtures run only in a disposable database; no production proofs."""
# ruff: noqa: F811

import pytest
from test_day3_integration import engine  # noqa: F401
from triad.day3.contracts import AgentRunResult
from triad.day5a.control import ProviderControl
from triad.day5a.relay import run_relay
from triad.work import State

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("grok_verdict", ["APPROVE", "REQUEST_CHANGES"])
def test_relay_independent_verdicts_and_durable_lineage(engine, monkeypatch, grok_verdict):
    from triad.day5a import relay

    monkeypatch.setattr(relay, "Cycles", lambda store: engine)
    control = ProviderControl(engine.ledger)
    monkeypatch.setattr(control, "proven", lambda snapshot: True)
    contexts = {}

    def execute(request, **kwargs):
        contexts[request.agent_id] = request.context_packet
        result = AgentRunResult(
            run_id=request.run_id,
            status="NO_CHANGE_JUSTIFIED",
            summary="Explicit test fixture",
            proposed_actions=("Add a settings navigation link",)
            if request.agent_id == "CODEX"
            else (),
            review_decision=grok_verdict if request.agent_id == "GROK" else "APPROVE",
            findings=("Fixture review",),
        )
        engine.ledger.put(
            "Usage",
            {
                "run_id": request.run_id,
                "status": "SUCCESS",
                "billing_source": "LOCAL" if request.agent_id == "LOCAL_QWEN" else "SUBSCRIPTION",
                "actual_model": "explicit-test-fixture",
            },
            work_id=request.work_item_id,
        )
        return result

    monkeypatch.setattr(engine.runtime, "execute", execute)
    proof = run_relay(control)
    assert [s["agent"] for s in proof["steps"]] == ["CODEX", "CLAUDE", "GROK", "LOCAL_QWEN"]
    assert contexts["CLAUDE"] == contexts["GROK"]
    assert "reviews" not in contexts["GROK"]
    assert len(proof["reviews"]) == 2
    main = engine.host.store.get(proof["work_item_id"])
    assert engine.ledger.get(proof["git_record_id"])["files_changed"] == []
    if grok_verdict == "APPROVE":
        assert proof["success"] is True, proof
        assert proof["graph_verified"] and ProviderControl.relay_proven(proof)
        assert main.status == State.COMPLETED
        assert not ProviderControl.relay_proven({**proof, "mode": "SIMULATED"})
        assert not ProviderControl.relay_proven({**proof, "reviews": proof["reviews"][:1]})
    else:
        assert not proof["success"] and main.status == State.BLOCKED
        assert proof["disagreement_check"] == "OPEN"
        assert engine.ledger.records("Disagreement")[0]["status"] == "OPEN"
        assert not ProviderControl.relay_proven(proof)
