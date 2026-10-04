# ruff: noqa: F401, F811
"""Maintenance is a closed rejected-review checkpoint, never general retry authority."""

import pytest
from products.triad.sequential_qa_recovery import resume_citation_failure
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, proof, snapshot
from test_correction_renewal_integration import healthy
from trading_core.work import State

pytestmark = pytest.mark.integration


def checkpoint(p, *, change=None, marker=True, owner="core", kind="ControlAction", failure=None):
    qa = p.host.get(p.qa)
    review_id = next(
        e.removeprefix("acceptance-review:")
        for e in qa["evidence"]
        if e.startswith("acceptance-review:")
    )
    review = p.host.get(review_id)
    prior = p.daily.current(p.mission)
    payload = {
        "action": "hold_at_closed_candidate_qa",
        "cycle_id": p.mission,
        "implementation_id": p.build["implementation_id"],
        "qa_id": p.qa,
        "candidate_commit": p.build["git"]["change_commit"],
        "base_commit": p.build["git"]["base_commit"],
        "approval_id": p.build["approval"],
        "review_work_item_id": p.reviewer.work_item_id,
        "review_run_id": review["run_id"],
        "control_epoch": prior["control_epoch"],
        "product_policy_id": "fixture",
        "retained_turn_ids": [],
        "released_change_slots": 0,
    }
    if change:
        payload.update(change)
    if marker:
        p.host.ledger.put("ControlAction", payload, identifier="qa-maintenance-" + p.qa)
        with p.host.store.connect() as c:
            c.execute(
                "UPDATE core.day3_records SET kind=%s,owner=%s WHERE id=%s",
                (kind, owner, "qa-maintenance-" + p.qa),
            )
    code, message = failure or ("ConcurrentUpdate", "Work is already being executed")
    p.daily.transition(
        p.mission,
        "BLOCKED",
        [code],
        failures=({"code": code, "message": message},),
    )


def test_closed_qa_maintenance_resumes_once_preserving_actual_work_and_slot(proof, monkeypatch):
    p = proof
    checkpoint(p)
    healthy(monkeypatch)
    before = snapshot(p)
    cycle, count, day, retained = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and count == 0 and day == p.day
    assert retained[-1].decision == "CHANGES_REQUIRED"
    assert p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
    assert p.flow._prepared_correction["commit"] == p.build["git"]["change_commit"]
    assert snapshot(p) == before
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert snapshot(p) == before


@pytest.mark.parametrize(
    "change_case",
    [
        "missing",
        "owner",
        "kind",
        "cycle_id",
        "implementation_id",
        "qa_id",
        "candidate_commit",
        "base_commit",
        "approval_id",
        "review_work_item_id",
        "review_run_id",
        "control_epoch",
        "product_policy_id",
        "retained_turn_ids",
        "released_change_slots",
        "boolean_slot",
    ],
)
def test_unbound_pause_does_not_authorize_retry(proof, monkeypatch, change_case):
    p = proof
    change = None
    if change_case not in {"missing", "owner", "kind"}:
        key = "released_change_slots" if change_case == "boolean_slot" else change_case
        value = (
            False
            if change_case == "boolean_slot"
            else ["different-turn"]
            if key == "retained_turn_ids"
            else 99
            if key in {"control_epoch", "released_change_slots"}
            else "different"
        )
        change = {key: value}
    checkpoint(
        p,
        marker=change_case != "missing",
        owner="triad" if change_case == "owner" else "core",
        kind="Event" if change_case == "kind" else "ControlAction",
        change=change,
    )
    healthy(monkeypatch)
    before = snapshot(p)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before


@pytest.mark.parametrize(
    "variant",
    [
        "unknown_usage",
        "active_transport",
        "missing_native",
        "partial_native",
        "wrong_provider",
        "write_tools",
        "REJECT",
        "BLOCKED",
    ],
)
def test_checkpoint_never_replaces_closed_independent_review_proof(proof, monkeypatch, variant):
    p = proof
    checkpoint(p)
    healthy(monkeypatch)
    before = snapshot(p)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before


def test_still_paused_cannot_resume_and_product_edits_remain_forbidden(proof, monkeypatch):
    p = proof
    checkpoint(p)
    healthy(monkeypatch)
    p.daily.product.ledger.operate("pause")
    before = snapshot(p)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    p.daily.product.ledger.operate("resume")
    path = p.flow.root / "app/products/triad/unreviewed_product.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("unreviewed = True\n")
    p.git.git("add", ".", cwd=p.flow.root)
    p.git.git("commit", "-m", "Unapproved product drift", cwd=p.flow.root)
    with pytest.raises(PermissionError, match="Product source changed"):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before


def test_protected_source_repair_preserves_native_candidate_and_requires_fresh_plan(
    proof, monkeypatch
):
    p = proof
    checkpoint(p)
    healthy(monkeypatch)
    path = p.flow.root / "app/products/triad/sequential_planning.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Independently reviewed fixture protected repair\n")
    p.git.git("add", ".", cwd=p.flow.root)
    p.git.git("commit", "-m", "Protected fixture repair", cwd=p.flow.root)
    before = snapshot(p)
    cycle, _, _, retained = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert cycle.status == "AWAITING_QA" and retained[-1].decision == "CHANGES_REQUIRED"
    assert p.flow._prepared_correction["base_commit"] == p.build["git"]["base_commit"]
    assert p.flow._prepared_correction["base_commit"] != p.git.git(
        "rev-parse", "HEAD", cwd=p.flow.root
    )
    assert snapshot(p) == before


@pytest.mark.parametrize(
    "failure",
    [
        ("Stopped", "Product is paused"),
        ("ConcurrentUpdate", "Stale work revision"),
        ("ProviderError", "Work is already being executed"),
    ],
)
def test_marker_does_not_convert_other_failures_into_retry_authority(proof, monkeypatch, failure):
    p = proof
    checkpoint(p, failure=failure)
    healthy(monkeypatch)
    before = snapshot(p)
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert p.daily.current(p.mission)["status"] == "BLOCKED" and snapshot(p) == before
