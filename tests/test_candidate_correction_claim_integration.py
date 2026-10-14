# ruff: noqa: F401, F811
from copy import deepcopy
from pathlib import Path

import pytest
from products.triad.sequential_corrections import claim_correction_build
from psycopg.types.json import Jsonb
from test_candidate_correction_integration import engine, prepare, proof, snapshot
from trading_core.work import State

pytestmark = [pytest.mark.integration, pytest.mark.triad]


@pytest.mark.parametrize("tamper", ["bytes", "owner", "payload", "retained_slot"])
def test_claim_rejects_changed_checkpoint_and_retained_bytes(proof, tamper):
    p = proof
    ret = prepare(p)
    p.daily.transition(p.mission, "CORRECTING", ["fixture"])
    before = snapshot(p)
    if tamper == "bytes":
        ret["files"][0]["content"] += "edited"
    elif tamper == "retained_slot":
        ret["reservation_id"] = "another-reservation"
    else:
        with p.host.store.connect() as c:
            if tamper == "owner":
                c.execute(
                    "UPDATE core.day3_records SET owner='aegis' WHERE id=%s",
                    ("candidate-correction-" + p.qa,),
                )
            else:
                c.execute(
                    "UPDATE core.day3_records SET payload=payload || %s WHERE id=%s",
                    (Jsonb({"cycle_id": "other-cycle"}), "candidate-correction-" + p.qa),
                )
    with pytest.raises(PermissionError):
        claim_correction_build(p.flow, p.mission, "CODEX", p.proposal, p.build["approval"], ret)
    assert snapshot(p) == before
    with p.host.store.connect() as c:
        assert not c.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + p.qa,)
        ).fetchone()


def test_prepare_rejects_intermediate_wrong_reservation_reference(proof):
    p = proof
    b = deepcopy(p.build)
    b.pop("id")
    parent = {**b, "implementation_id": "original-predecessor"}
    p.host.append("ProductBuild", parent, owner="triad")
    b.update(
        correction_of="original-predecessor",
        reservation_id="wrong",
        reservation_work_item_id="wrong-work",
    )
    p.host.append("ProductBuild", b, owner="triad")
    p.build = b
    with pytest.raises(PermissionError, match="reservation"):
        prepare(p)


def test_explicit_resume_transaction_preserves_rejection_and_slot(proof, monkeypatch):
    from products.triad.sequential_qa_recovery import resume_citation_failure

    p = proof
    before = snapshot(p)
    p.daily.transition(
        p.mission,
        "BLOCKED",
        ["PermissionError"],
        failures=(
            {
                "code": "PermissionError",
                "message": "Latest independent QA did not pass this revision",
            },
        ),
    )
    monkeypatch.setattr(
        "products.triad.sequential_qa_recovery.health",
        lambda head: {"loaded_revision": head, "development_provider_gate": "PASS"},
    )
    cycle, count, day, retained = resume_citation_failure(p.flow, p.mission, substantive=True)
    assert (
        cycle.status == "AWAITING_QA"
        and count == 0
        and day == p.day
        and retained[-1].decision == "CHANGES_REQUIRED"
    )
    assert (
        p.host.store.get(p.work.work_item_id).status == State.CHANGES_REQUESTED
        and snapshot(p) == before
    )
    assert p.flow._prepared_correction["reservation_work_item_id"] == p.work.work_item_id
    with pytest.raises(PermissionError):
        resume_citation_failure(p.flow, p.mission, substantive=True)
    assert snapshot(p) == before
