from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from products.triad.sequential_citations import citation_omission, correct_citations
from trading_core.contracts import AgentRunResult
from trading_core.product_changes import AcceptanceAssessment, RequiredCheck


def fixture():
    required = [
        {"check_id": "behavior", "method": "PYTHON_UNIT_TEST", "description": "Behavior"},
        {"check_id": "source", "method": "SOURCE_REVIEW", "description": "Source"},
    ]
    assessment = AcceptanceAssessment(
        checks=(
            {
                "check_id": "behavior",
                "status": "VERIFIED",
                "evidence_ids": ["first"],
                "reason": "Both tests passed",
            },
            {
                "check_id": "source",
                "status": "VERIFIED",
                "evidence_ids": ["candidate:commit"],
                "reason": "Reviewed source",
            },
        )
    )
    proofs = {
        i: {
            "kind": "EngineeringTestRun",
            "owner": "triad",
            "commit": "commit",
            "status": "PASS",
            "test_status": "PASSED",
            "executed_tests": 31,
        }
        for i in ("first", "second")
    }
    return required, assessment, proofs


@pytest.mark.parametrize("decision", ["APPROVE", "REJECT", "REQUEST_CHANGES", None])
def test_only_approvals_with_omitted_citations_qualify(decision):
    required, assessment, proofs = fixture()
    assert citation_omission(required, assessment, "commit", proofs, decision) == (
        decision == "APPROVE"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("commit", "stale"),
        ("status", "FAIL"),
        ("test_status", "FAILED"),
        ("executed_tests", 0),
        ("kind", "Other"),
        ("owner", "aegis"),
    ],
)
def test_failed_stale_or_foreign_proofs_never_trigger_retry(field, value):
    required, assessment, proofs = fixture()
    proofs["second"][field] = value
    assert not citation_omission(required, assessment, "commit", proofs, "APPROVE")


@pytest.mark.parametrize(
    "change", ["unknown", "missing", "duplicate", "unverified", "source", "complete"]
)
def test_substantive_or_complete_assessments_do_not_retry(change):
    required, assessment, proofs = fixture()
    data = assessment.model_dump()
    if change == "unknown":
        data["checks"][0]["evidence_ids"] = ("invented",)
    elif change == "missing":
        data["checks"] = data["checks"][:1]
    elif change == "duplicate":
        data["checks"] = (data["checks"][0], data["checks"][0])
    elif change == "unverified":
        data["checks"][0]["status"] = "NOT_VERIFIED"
    elif change == "source":
        data["checks"][1]["evidence_ids"] = ("first",)
    else:
        data["checks"][0]["evidence_ids"] = ("first", "second")
    assert not citation_omission(required, data, "commit", proofs, "APPROVE")


@pytest.mark.parametrize(
    "change,accepted",
    [
        ("citations", True),
        ("reason", False),
        ("missing-citation", False),
        ("drop-finding", False),
        ("unknown", False),
        ("reject", False),
    ],
)
def test_correction_is_one_small_review_with_retained_provenance(change, accepted):
    required, assessment, proofs = fixture()
    original = AgentRunResult(
        run_id="original",
        status="NO_CHANGE_JUSTIFIED",
        summary="Reviewed",
        review_decision="APPROVE",
        findings=("Observation",),
    )
    data = deepcopy(assessment.model_dump())
    data["checks"][0]["evidence_ids"] = ("first", "second")
    if change == "reason":
        data["checks"][0]["reason"] = "A new conclusion"
    if change == "missing-citation":
        data["checks"][0]["evidence_ids"] = ("first",)
    if change == "unknown":
        data["checks"][0]["evidence_ids"] = ("first", "second", "invented")
    response = original.model_copy(
        update={
            "run_id": "corrected",
            "review_decision": "REJECT" if change == "reject" else "APPROVE",
            "findings": () if change == "drop-finding" else original.findings,
        }
    )
    corrected = (
        NS(work_item_id="new"),
        response,
        AcceptanceAssessment.model_validate(data),
        {"run_id": "corrected"},
    )
    calls, records = [], []

    def call(*args):
        calls.append(args)
        return corrected

    flow = NS(call=call, s=NS(record=lambda *a, **k: records.append((a, k))))
    completed = (NS(work_item_id="old"), original, assessment, {"run_id": "original"})
    output = correct_citations(
        flow,
        "cycle",
        "CODEX",
        NS(acceptance=tuple(RequiredCheck.model_validate(c) for c in required)),
        {"implementation_id": "impl", "git": {"change_commit": "commit"}},
        completed,
        proofs,
    )
    assert len(calls) == 1 and calls[0][1] == "CLAUDE"
    assert "checks" not in calls[0][3]  # No repeated source/diff packet or build.
    assert calls[0][3]["test_records"] == proofs
    assert records[0][1]["usage"]["run_id"] == "original"
    assert records[1][1]["usage"]["run_id"] == "corrected"
    assert records[1][1]["accepted"] is accepted
    assert output is (corrected if accepted or change == "reject" else completed)
