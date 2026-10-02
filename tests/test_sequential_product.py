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
        acceptance=({"check_id": "source", "method": "SOURCE_REVIEW", "description": "Test"},),
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
@pytest.mark.parametrize("resume", [False, True])
def test_next_author_waits_for_deployment(fail_health, resume, monkeypatch):
    events = []
    flow = object.__new__(SequentialCycle)
    flow.policy = {"id": "policy"}
    from datetime import UTC, datetime

    cycle = NS(
        cycle_id="c",
        parent_work_item_id="p",
        control_epoch=1,
        created_at=datetime(2026, 9, 30, 2, tzinfo=UTC),
    )
    flow.guard = lambda _: None
    if resume:
        monkeypatch.setattr(
            "products.triad.sequential_recovery.resume_patch_failure",
            lambda *a: (cycle, 1, "2026-09-29"),
        )
    flow.s = NS(
        ledger=NS(store=NS(lease=lambda _: nullcontext()), gate=nullcontext),
        host=NS(store=NS(lease=lambda _: nullcontext(), list_work=lambda _: [])),
        daily=NS(
            create=lambda **k: cycle,
            current=lambda _: {"status": "COMPLETED", "parent_work_item_id": "p"},
            schedule=lambda: {"timezone": "UTC" if resume else "America/Chicago"},
        ),
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
            flow.run(verify=verify, cycle_id="c", resume_patch_failure=resume)
        first = "CLAUDE" if resume else "CODEX"
        assert events == ["ready", "propose " + first, "healthy " + first]
    else:
        flow.run(verify=verify, cycle_id="c", resume_patch_failure=resume)
        assert events == ["ready"] + ([] if resume else ["propose CODEX", "healthy CODEX"]) + [
            "propose CLAUDE",
            "healthy CLAUDE",
            "propose GROK",
            "healthy GROK",
        ]
    assert tuple(REVIEWERS[a] for a in ORDER) == ("CLAUDE", "GROK", "CODEX")
    assert flow.improvement_day == "2026-09-29"


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
        host=NS(store=NS(lease=lambda _: nullcontext())),
        product=NS(list=lambda kind: records[kind]),
        current=lambda _: {"status": "BUILDING"},
        transition=lambda *a, **k: changes.append(a),
        history=None,
    )
    monkeypatch.setattr(module, "process_info", lambda _: {"state": state, "creation_id": identity})
    module.reconcile(service)
    assert bool(changes) == blocked


@pytest.mark.parametrize("status", ["NOT_VERIFIED", "BLOCKED"])
def test_approval_cannot_waive_mandatory_checks(status):
    from trading_core.product_changes import acceptance_problems

    required = [
        {
            "check_id": "source",
            "method": "SOURCE_REVIEW",
            "description": "Verify heading in exact source",
        }
    ]
    assessment = {
        "checks": [
            {
                "check_id": "source",
                "status": status,
                "evidence_ids": ["candidate:commit"],
                "reason": "Not performed",
            }
        ]
    }
    assert acceptance_problems(required, assessment, "commit", {})
    assessment["checks"][0]["status"] = "VERIFIED"
    assert not acceptance_problems(required, assessment, "commit", {})
    assessment["checks"][0]["evidence_ids"] = ["candidate:old"]
    assert acceptance_problems(required, assessment, "commit", {})
    assert acceptance_problems(required, {"checks": []}, "commit", {})


def test_unit_acceptance_requires_actual_exact_passing_tests():
    from trading_core.product_changes import acceptance_problems

    required = [
        {"check_id": "tests", "method": "PYTHON_UNIT_TEST", "description": "Exercise behavior"}
    ]
    assessment = {
        "checks": [
            {
                "check_id": "tests",
                "status": "VERIFIED",
                "evidence_ids": ["first", "repeat"],
                "reason": "Actual host checks",
            }
        ]
    }
    proof = {"status": "PASS", "test_status": "PASSED", "executed_tests": 2, "commit": "commit"}
    proofs = {"first": dict(proof), "repeat": dict(proof)}
    assert not acceptance_problems(required, assessment, "commit", proofs)
    for changes in (
        {"executed_tests": 0},
        {"commit": "old"},
        {"status": "FAILED"},
        {"test_status": "NOT_PRESENT"},
    ):
        assert acceptance_problems(
            required, assessment, "commit", {**proofs, "repeat": {**proof, **changes}}
        )


def test_restart_does_not_capture_pipes_inherited_by_worker(monkeypatch):
    import subprocess

    from trading_core import product_deployment as module

    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return NS(returncode=0)

    monkeypatch.setattr(module.subprocess, "run", run)
    module.restart()
    assert calls[0]["stdout"] == subprocess.DEVNULL
    assert calls[0]["stderr"] == subprocess.DEVNULL
    assert not calls[0].get("capture_output")


@pytest.mark.parametrize("decision", ["APPROVE", "REQUEST_CHANGES", "REJECT"])
def test_proposal_revision_preserves_independent_decision(decision):
    flow = object.__new__(SequentialCycle)
    flow.s = NS(rows=lambda *args: [])
    calls = []
    proposal = Proposal(
        title="Change",
        problem="Observed",
        change="Fix",
        files=("app/products/triad/product_app.py",),
        acceptance=({"check_id": "source", "method": "SOURCE_REVIEW", "description": "Test"},),
        evidence=("Source",),
    )

    def attempt(mission, agent, feedback, number):
        calls.append((number, list(feedback)))
        verdict = "APPROVE" if number == 2 else decision
        return (
            proposal,
            "approval" if verdict == "APPROVE" else None,
            {"decision": verdict, "summary": "Fix route mounting"},
        )

    flow.proposal_attempt = attempt
    assert flow.propose("cycle", "CLAUDE") == (proposal, "approval")
    if decision in {"REQUEST_CHANGES", "REJECT"}:
        assert len(calls) == 2
        assert calls[1][1][0]["summary"] == "Fix route mounting"
        assert calls[1][1][0]["decision"] == decision
        assert calls[1][1][0]["proposal"] == proposal.model_dump(mode="json")
    else:
        assert len(calls) == 1


def test_unresolved_proposal_cannot_be_approved_by_exhaustion():
    flow = object.__new__(SequentialCycle)
    flow.s = NS(rows=lambda *args: [])
    proposal = Proposal(
        title="Change",
        problem="Observed",
        change="Fix",
        files=("app/products/triad/product_app.py",),
        acceptance=({"check_id": "source", "method": "SOURCE_REVIEW", "description": "Test"},),
        evidence=("Source",),
    )
    calls = []

    def attempt(mission, agent, feedback, number):
        calls.append(number)
        return proposal, None, {"decision": "REQUEST_CHANGES", "summary": "Still incorrect"}

    flow.proposal_attempt = attempt
    with pytest.raises(PermissionError, match="exhausted"):
        flow.propose("cycle", "CLAUDE")
    assert calls == [1, 2, 3]


@pytest.mark.parametrize("prefixed", [False, True])
def test_exact_host_test_ids_accept_recognized_labels(prefixed):
    from trading_core.product_changes import acceptance_problems

    proof = {"status": "PASS", "test_status": "PASSED", "executed_tests": 5, "commit": "exact"}
    proofs = {"one": proof, "two": dict(proof)}
    ids = ["test_record_id:one", "repeated_test_record_id:two"] if prefixed else ["one", "two"]
    required = [{"check_id": "unit", "method": "PYTHON_UNIT_TEST", "description": "Unit"}]
    assessment = {
        "checks": [
            {"check_id": "unit", "status": "VERIFIED", "reason": "Evidence", "evidence_ids": ids}
        ]
    }
    assert not acceptance_problems(required, assessment, "exact", proofs)
    for invalid in ["test_record_id:foreign", "arbitrary:one", "test_record_id:test_record_id:one"]:
        assessment["checks"][0]["evidence_ids"] = [invalid, "repeated_test_record_id:two"]
        assert acceptance_problems(required, assessment, "exact", proofs)
    assessment["checks"][0]["evidence_ids"] = ids
    proofs["one"]["commit"] = "stale"
    assert acceptance_problems(required, assessment, "exact", proofs)


@pytest.mark.parametrize(
    "error,retry",
    [
        ("Read-only product inspection cannot change files", True),
        ("Expected exactly one structured product artifact", True),
        ("Run cancelled or autonomy paused", False),
        ("Provider blocked this assignment", False),
    ],
)
def test_native_envelope_retry_preserves_authority(error, retry):
    flow = object.__new__(SequentialCycle)
    calls = []
    flow.guard = lambda _: None

    def call(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise PermissionError(error)
        return (None, None, "corrected", {"run_id": "corrected-run"})

    flow.s = NS(
        call=call,
        git=NS(clean_baseline=lambda: "baseline"),
        rows=lambda *a: [],
        record=lambda *a, **k: None,
        daily=NS(current=lambda _: {"parent_work_item_id": "parent"}),
    )
    if retry:
        assert flow.call("mission", "CLAUDE", "Objective", {})[2] == "corrected"
        assert len(calls) == 2
        assert calls[1][4]["response_format_feedback"]
        assert calls[1][1] == "CLAUDE"
    else:
        with pytest.raises(PermissionError, match=error):
            flow.call("mission", "CLAUDE", "Objective", {})
        assert len(calls) == 1


def test_artifact_schema_error_retries_without_silently_dropping_fields():
    from products.triad.development import ProductResponseFormatError

    flow = object.__new__(SequentialCycle)
    seen = []
    flow.guard = lambda _: None

    def call(*args, **kwargs):
        seen.append(args)
        if len(seen) == 1:
            raise ProductResponseFormatError(
                "Invalid product artifact: acceptance.0.extra forbidden"
            )
        return (None, None, "corrected", {"run_id": "corrected-run"})

    flow.s = NS(
        call=call,
        git=NS(clean_baseline=lambda: "baseline"),
        rows=lambda *a: [],
        record=lambda *a, **k: None,
        daily=NS(current=lambda _: {"parent_work_item_id": "parent"}),
    )
    assert flow.call("mission", "CLAUDE", "Objective", {})[2] == "corrected"
    assert "acceptance.0.extra" in seen[1][4]["response_format_feedback"][0]
