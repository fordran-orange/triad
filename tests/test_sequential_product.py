"""Product protection, exact proposal binding, sequential deployment and rollback."""

from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential import ORDER, REVIEWERS, Proposal, SequentialCycle
from trading_core.governance import assert_product_merge_allowed
from trading_core.product_changes import ProductGit, product_path


@pytest.mark.parametrize(
    "path",
    [
        "app/trading_core/ledger.py",
        "app/products/triad/daily.py",
        "app/products/triad/development.py",
        "app/products/triad/sequential.py",
        "app/products/triad/server.py",
        "app/products/triad/static/cycles.js",
        "app/products/aegis/server.py",
        "config/core/agents.json",
        "app/products/triad/../triad/static/product.html",
        "app/products/triad/AGENTS.md",
    ],
)
def test_protected_boundaries(path):
    with pytest.raises(PermissionError):
        product_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "app/products/triad/static/product.html",
        "app/products/triad/product_app.py",
        "app/products/triad/analytics/returns.py",
        "tests/products/triad/test_returns.py",
        "products/triad/docs/help.md",
    ],
)
def test_product_scope_is_not_two_ui_files(path):
    assert product_path(path) == path
    assert_product_merge_allowed((path,))


def test_hardlink_rejected_before_read(tmp_path):
    import os

    private = tmp_path / "private.txt"
    private.write_text("not exposed")
    target = tmp_path / "app/products/triad/product_app.py"
    target.parent.mkdir(parents=True)
    os.link(private, target)
    broker = ProductGit(("app/products/triad/product_app.py",), root=tmp_path)
    with pytest.raises(PermissionError, match="linked"):
        broker.path(tmp_path, "app/products/triad/product_app.py")


def test_approval_cannot_authorize_another_proposal():
    import hashlib

    proposal = Proposal(
        title="Change",
        problem="Observed",
        change="Fix",
        files=("app/products/triad/product_app.py",),
        acceptance=("Test",),
        evidence=("Source",),
    )
    row = {
        "kind": "ProductTurnApproval",
        "owner": "triad",
        "cycle_id": "cycle",
        "builder": "CODEX",
        "reviewer": "CLAUDE",
        "policy_id": "policy",
        "proposal": proposal.model_dump(mode="json"),
        "proposal_sha256": hashlib.sha256(proposal.model_dump_json().encode()).hexdigest(),
    }
    flow = object.__new__(SequentialCycle)
    flow.policy = {"id": "policy"}
    flow.guard = lambda m: None
    flow.s = NS(canonical=NS(get=lambda i: row))
    assert flow.approval("cycle", "CODEX", proposal, "approval") == row
    for change in (
        {"files": ("app/products/triad/another.py",)},
        {"change": "different implementation"},
    ):
        with pytest.raises(PermissionError):
            flow.approval("cycle", "CODEX", proposal.model_copy(update=change), "approval")
    row["reviewer"] = "CODEX"
    with pytest.raises(PermissionError):
        flow.approval("cycle", "CODEX", proposal, "approval")


@pytest.mark.parametrize("fail_health", [False, True])
def test_next_author_waits_for_deployment(fail_health):
    events = []
    flow = object.__new__(SequentialCycle)
    flow.policy = {"id": "policy"}
    cycle = NS(cycle_id="c", parent_work_item_id="p", control_epoch=1)
    flow.guard = lambda _: None
    flow.s = NS(
        ledger=NS(store=NS(lease=lambda _: nullcontext()), gate=nullcontext),
        host=NS(store=NS(lease=lambda _: nullcontext())),
        daily=NS(create=lambda **k: cycle, current=lambda _: {"status": "COMPLETED"}),
        canonical=NS(append=lambda *a, **k: None),
        transition=lambda *a, **k: None,
        record=lambda *a, **k: None,
        debrief=lambda *a: {"decision": "PASS"},
    )
    flow.readiness = lambda _: events.append("ready")

    def propose(m, a):
        events.append("propose " + a)
        return NS(model_dump=lambda **k: {}), "approval"

    flow.propose = propose
    flow.build = lambda m, a, p, r: (None, {"implementation_id": a})
    flow.qa = lambda m, a, p, g, b: NS(qa_run_id="qa")
    flow.merge = lambda m, a, g, b, q: {"merge_commit": a}

    def verify(m):
        events.append("healthy " + m["merge_commit"])
        return {"status": "FAILED" if fail_health else "PASS"}

    if fail_health:
        with pytest.raises(PermissionError):
            flow.run(verify=verify)
        assert events == ["ready", "propose CODEX", "healthy CODEX"]
    else:
        flow.run(verify=verify)
        assert events == [
            "ready",
            "propose CODEX",
            "healthy CODEX",
            "propose CLAUDE",
            "healthy CLAUDE",
            "propose GROK",
            "healthy GROK",
        ]
    assert tuple(REVIEWERS[a] for a in ORDER) == ("CLAUDE", "GROK", "CODEX")


def test_failed_deployment_reverts_only_exact_reviewed_merge(monkeypatch):
    from trading_core import product_deployment as module

    head = ["merge"]
    commands = []

    def git(*args):
        commands.append(args)
        if args[:1] == ("rev-parse",):
            return head[0]
        if args[:1] == ("revert",):
            head[0] = "rollback"
        return ""

    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module, "restart", lambda: None)

    def health(revision):
        if revision == "merge":
            raise RuntimeError("broken endpoint")
        return {"loaded_revision": revision}

    monkeypatch.setattr(module, "health", health)
    result = module.verify({"merge_commit": "merge", "base_commit": "base"})
    assert result["rolled_back"] and result["rollback_commit"] == "rollback"
    assert ("revert", "--no-edit", "-m", "1", "merge") in commands


def test_rollback_failure_retains_original_health_failure(monkeypatch):
    from trading_core import product_deployment as module

    def git(*args):
        if args[0] == "revert":
            raise RuntimeError("revert unavailable")
        return "merge" if args[0] == "rev-parse" else ""

    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module, "restart", lambda: None)
    monkeypatch.setattr(
        module, "health", lambda _: (_ for _ in ()).throw(RuntimeError("bad health"))
    )
    result = module.verify({"merge_commit": "merge", "base_commit": "base"})
    assert result["error"] == "bad health"
    assert result["rollback_error"] == "revert unavailable"
    assert not result["rolled_back"]


@pytest.mark.parametrize(
    "state,identity,blocked",
    [
        ("RUNNING", "original", False),
        ("RUNNING", "reused", True),
        ("EXITED", "original", True),
        ("UNKNOWN", None, False),
    ],
)
def test_detached_runner_reconciliation(monkeypatch, state, identity, blocked):
    from products.triad import daily_process as module

    changes = []
    records = {
        "DailyDispatch": [{"cycle_id": "c", "control_epoch": 1}],
        "DailyDispatchProcess": [{"cycle_id": "c", "pid": 123, "creation_id": "original"}],
    }
    service = NS(
        product=NS(list=lambda kind: records[kind]),
        current=lambda _: {"status": "BUILDING"},
        transition=lambda *a, **k: changes.append(a),
        history=None,
    )
    monkeypatch.setattr(module, "process_info", lambda _: {"state": state, "creation_id": identity})
    module.reconcile(service)
    assert bool(changes) == blocked
