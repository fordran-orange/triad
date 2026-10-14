"""The local proof must retain Core QA and truthful failure/recovery evidence."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from trading_core.contracts import Limits
from trading_core.providers.autonomous_cli import AutonomousCLIRun

pytestmark = pytest.mark.core

SPEC = importlib.util.spec_from_file_location(
    "milestone_proof", Path(__file__).resolve().parents[1] / "tools/run_milestone1_rotation.py"
)
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


def service(*, failure=None, merge=True):
    evidence = []
    metadata = {"base_commit": "base", "merge_commit": "merged" if merge else None}

    def run(mission):
        if failure:
            raise failure
        return metadata

    dev = SimpleNamespace(
        git=SimpleNamespace(clean_baseline=lambda: "base", root=Path(".")),
        ledger=SimpleNamespace(guard=lambda: None),
        run=run,
        record=lambda kind, mission, **payload: evidence.append((kind, mission, payload.copy())),
    )
    return dev, evidence


def test_unverified_host_execution_fails_before_starting_process():
    with pytest.raises(PermissionError, match="verified isolated execution"):
        AutonomousCLIRun(["provider"], "CLAUDE")


def test_cycle_failure_preserves_started_and_failed_evidence():
    dev, evidence = service(failure=PermissionError("Independent QA requires correction"))
    with pytest.raises(PermissionError):
        proof.run_proof(dev, restart=lambda _: pytest.fail("No merge must not restart"))
    assert [row[2]["status"] for row in evidence] == ["RUNNING", "FAILED"]
    assert evidence[0][1] == evidence[1][1]
    assert evidence[-1][2]["error_class"] == "PermissionError"
    assert "finished_at" in evidence[-1][2]


def test_no_merge_result_does_not_claim_deployment():
    dev, evidence = service(merge=False)
    result = proof.run_proof(dev, restart=lambda _: pytest.fail("Diagnostic must not restart"))
    assert result["status"] == "REVIEWED_NOT_MERGED"
    assert evidence[-1][2]["merge_commit"] is None


def test_merged_result_requires_restart_success():
    dev, evidence = service()
    assert proof.run_proof(dev, restart=lambda _: True)["status"] == "MERGED_AND_HEALTHY"
    assert evidence[-1][2]["merge_commit"] == "merged"


def test_restart_failure_records_actual_recovery_and_remains_failed(monkeypatch):
    dev, evidence = service()
    monkeypatch.setattr(proof, "recover_merge", lambda *args: "revert")
    outcomes = iter((False, True))
    with pytest.raises(RuntimeError, match="PostMergeHealthFailed"):
        proof.run_proof(dev, restart=lambda _: next(outcomes))
    result = evidence[-1][2]
    assert result["status"] == "FAILED"
    assert result["revert_commit"] == "revert" and result["recovery_healthy"] is True


def test_diagnostic_merge_cannot_skip_independent_qa():
    dev = proof.ProofDevelopment.__new__(proof.ProofDevelopment)
    dev.no_merge = True
    dev.quality = SimpleNamespace(require_pass=lambda *args: {"id": "new-qa"})
    dev.ledger = SimpleNamespace(control=lambda: {"limits": Limits().model_dump()})
    dev.exact_checks = lambda *args: pytest.fail("Stale QA must be rejected first")
    with pytest.raises(PermissionError, match="current independent review"):
        dev.merge(
            "mission", SimpleNamespace(affected_components=("docs",)),
            {"implementation_id": "build", "git": {"change_commit": "candidate"}},
            SimpleNamespace(qa_run_id="stale-qa"),
        )


def test_recovery_refuses_moved_checkout_before_git_mutation():
    dev, _ = service()
    dev.host = SimpleNamespace(store=SimpleNamespace(lease=lambda _: nullcontext()))
    dev.git.git = lambda *args: pytest.fail("Moved baseline must not mutate Git")
    with pytest.raises(PermissionError, match="Source moved"):
        proof.recover_merge(dev, {"merge_commit": "different", "base_commit": "base"})


def test_recovery_uses_auditable_revert_and_verifies_base_tree():
    dev, _ = service()
    dev.host = SimpleNamespace(store=SimpleNamespace(lease=lambda _: nullcontext()))
    dev.git.clean_baseline = lambda: "merged"
    commands = []

    def git(*args):
        commands.append(args)
        if args[0] == "rev-list":
            return "merged base candidate"
        if args == ("rev-parse", "HEAD"):
            return "revert"
        return "tree"

    dev.git.git = git
    assert proof.recover_merge(dev, {"merge_commit": "merged", "base_commit": "base"}) == "revert"
    assert ("revert", "--no-edit", "-m", "1", "merged") in commands
    assert not any("reset" in args for args in commands)
