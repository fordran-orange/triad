import hashlib
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from products.triad.no_change import require_no_change
from products.triad.sequential import Proposal, SequentialCycle
from pydantic import ValidationError
from trading_core.product_changes import product_path


def proposal():
    return Proposal(
        outcome="NO_CHANGE",
        title="Keep the tested baseline",
        problem="No evidenced defect found",
        change="Retain current behavior pending useful evidence",
        files=(),
        acceptance=(),
        evidence=("Inspected exact current product source",),
    )


def fixture():
    p = proposal()
    cycle = {"cycle_id": "cycle", "parent_work_item_id": "parent"}
    turn = {
        "outcome": "NO_CHANGE",
        "owner": "triad",
        "mission_id": "cycle",
        "status": "COMPLETED",
        "agent": "CODEX",
        "reviewer": "CLAUDE",
        "no_change_id": "proof",
        "verified_revision": "base",
    }
    approval = {
        "kind": "ProductTurnApproval",
        "owner": "triad",
        "cycle_id": "cycle",
        "builder": "CODEX",
        "reviewer": "CLAUDE",
        "policy_id": "policy",
        "base_commit": "base",
        "proposal": p.model_dump(mode="json"),
        "proposal_sha256": hashlib.sha256(p.model_dump_json().encode()).hexdigest(),
        "author_work_item_id": "author",
        "author_run_id": "author-run",
        "review_work_item_id": "review",
        "run_id": "review-run",
    }
    proof = {
        "kind": "ProductNoChange",
        "owner": "triad",
        "cycle_id": "cycle",
        "agent": "CODEX",
        "reviewer": "CLAUDE",
        "approval_id": "approval",
        "baseline": "base",
        "health": {
            "loaded_revision": "base",
            "development_provider_gate": "PASS",
            "routes": {"/core": 200},
        },
    }
    rows = {"proof": proof, "approval": approval}
    works = {
        key: NS(
            owner="triad",
            mission_id="cycle",
            parent_work_item_id="parent",
            assigned_agent=agent,
            status="COMPLETED",
            work_type="review",
        )
        for key, agent in (("author", "CODEX"), ("review", "CLAUDE"))
    }
    evidence = {
        key: [
            {"kind": "Usage", "payload": {"status": "SUCCESS", "mode": "REAL", "agent": agent}},
            {
                "kind": "AgentRunResult",
                "payload": {
                    "mode": "REAL",
                    "status": "NO_CHANGE_JUSTIFIED",
                    "analysis_artifacts": [p.model_dump_json()] if key == "author" else [],
                    "review_decision": "APPROVE",
                },
            },
            {
                "kind": "AgentRunRequest",
                "payload": {
                    "work_item_id": key,
                    "agent_id": agent,
                    "mission_id": "cycle",
                    "role": "REVIEW",
                    "execution_permissions": ["read"],
                    "context_packet": {
                        "base_commit": "base",
                        "proposal": p.model_dump(mode="json"),
                    },
                },
            },
        ]
        for key, agent in (("author", "CODEX"), ("review", "CLAUDE"))
    }
    conn = NS(execute=lambda sql, args: NS(fetchall=lambda: evidence[args[0]]))
    records = NS(
        get=lambda key, **kw: rows[key],
        list=lambda *a, **kw: [{"owner": "triad", "cycle_id": "cycle", "policy_id": "policy"}],
        store=NS(get=lambda key, **kw: works[key], connect=lambda: nullcontext(conn)),
    )
    return records, turn, cycle, rows, works, evidence


def test_no_change_requires_real_independent_exact_evidence():
    records, turn, cycle, rows, works, evidence = fixture()
    assert require_no_change(records, turn, cycle) == rows["proof"]
    evidence["author"][1]["payload"]["analysis_artifacts"][0] += "]"
    assert require_no_change(records, turn, cycle) == rows["proof"]
    evidence["author"][1]["payload"]["analysis_artifacts"][0] = proposal().model_dump_json()
    for target, key, bad in (
        (turn, "reviewer", "CODEX"),
        (turn, "verified_revision", "stale"),
        (rows["approval"], "owner", "aegis"),
        (rows["approval"], "policy_id", "other"),
        (rows["approval"], "proposal_sha256", "bad"),
        (rows["proof"], "cycle_id", "other"),
        (rows["proof"]["health"], "development_provider_gate", "FAILED"),
        (evidence["author"][0]["payload"], "mode", "SIMULATED"),
        (evidence["review"][1]["payload"], "review_decision", "REQUEST_CHANGES"),
        (evidence["author"][1]["payload"], "analysis_artifacts", []),
        (evidence["author"][1]["payload"], "status", "BLOCKED"),
        (evidence["review"][2]["payload"]["context_packet"], "proposal", {"unrelated": True}),
        (evidence["author"][2]["payload"]["context_packet"], "base_commit", "stale"),
    ):
        old = deepcopy(target[key])
        target[key] = bad
        with pytest.raises(PermissionError):
            require_no_change(records, turn, cycle)
        target[key] = old
    works["review"].mission_id = "other"
    with pytest.raises(PermissionError):
        require_no_change(records, turn, cycle)


def test_no_change_never_disguises_edits_or_missing_tests():
    data = proposal().model_dump()
    for update in (
        {"outcome": "CHANGE"},
        {"files": ("app/products/triad/product_app.py",)},
        {"evidence": (" ",)},
    ):
        with pytest.raises(ValidationError):
            Proposal.model_validate({**data, **update})
    with pytest.raises(PermissionError):
        product_path("app/products/triad/no_change.py")


def test_no_change_checks_health_without_build_merge_or_restart(monkeypatch):
    from trading_core import product_deployment

    _records, _turn, _cycle, rows, _works, _evidence = fixture()
    events = []
    flow = object.__new__(SequentialCycle)
    flow.guard = lambda _: None
    flow.approval = lambda *a: rows["approval"]
    flow.s = NS(
        ledger=NS(store=NS(lease=lambda _: nullcontext())),
        git=NS(clean_baseline=lambda: "base"),
        canonical=NS(append=lambda kind, payload, **kw: events.append((kind, payload)) or kind),
        transition=lambda *a, **kw: events.append(("transition", kw)),
    )
    monkeypatch.setattr(product_deployment, "health", lambda revision: rows["proof"]["health"])
    monkeypatch.setattr(
        product_deployment, "restart", lambda: pytest.fail("No-change must not restart")
    )
    flow.no_change("cycle", "CODEX", proposal(), "approval")
    assert [event[0] for event in events] == ["ProductNoChange", "ProductTurn", "transition"]
    assert events[-1][1]["verified_revision"] == "base"
    flow.s.git.clean_baseline = lambda: "changed"
    with pytest.raises(PermissionError, match="baseline changed"):
        flow.no_change("cycle", "CODEX", proposal(), "approval")
