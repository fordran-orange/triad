import pytest
from pydantic import ValidationError
from triad.research_review import MethodReview


@pytest.mark.parametrize(
    "decision",
    [
        "ACCEPT_RESULT",
        "REQUEST_RERUN",
        "REJECT_METHOD",
        "DATA_QUALITY_FAILURE",
        "LOOKAHEAD_RISK",
        "INCONCLUSIVE",
    ],
)
def test_method_review_verdicts_require_inspection_evidence(decision):
    with pytest.raises(ValidationError):
        MethodReview(decision=decision, findings=(), evidence_checked=(), tests_repeated=())
    assert (
        MethodReview(
            decision=decision,
            findings=("Inspected method",),
            evidence_checked=("artifact checksum",),
            tests_repeated=(),
        ).decision
        == decision
    )


def test_method_review_cannot_claim_unrecognized_verdict_or_model_mode():
    with pytest.raises(ValidationError):
        MethodReview(decision="PROVEN", findings=("x",), evidence_checked=("x",), tests_repeated=())
    with pytest.raises(ValidationError):
        MethodReview(
            decision="ACCEPT_RESULT",
            findings=("x",),
            evidence_checked=("x",),
            tests_repeated=(),
            mode="REAL_MODEL",
        )
