import pytest
from products.triad.development import parse_product_artifact
from pydantic import ValidationError
from trading_core.product_changes import AcceptanceAssessment

BODY = '{"checks":[{"check_id":"exact_source","status":"VERIFIED","evidence_ids":["candidate:abc"],"reason":"Observed source"}]}'


def test_normalizes_observed_redundant_array_closer_without_changing_review():
    original, normalized = parse_product_artifact(AcceptanceAssessment, BODY)
    assert normalized is False
    fixed, normalized = parse_product_artifact(AcceptanceAssessment, "  " + BODY + "]\n")
    assert normalized is True and fixed == original


@pytest.mark.parametrize(
    "text",
    [
        BODY + "{}",
        BODY + " instructions",
        BODY + "]]",
        BODY + "}",
        "[{}]]",
        '{"checks":[],"checks":[]} ]',
        '{"checks":"bad"}]',
        '{"checks":[]',
        '{"checks":[],"approved":true}]',
        '{"checks":[],"checks":[]}',
        '{"checks":[{"check_id":"a","status":"BLOCKED","status":"VERIFIED","evidence_ids":["a"],"reason":"claim"}]}',
    ],
)
def test_does_not_repair_extra_values_keys_or_invalid_schema(text):
    with pytest.raises(ValidationError):
        parse_product_artifact(AcceptanceAssessment, text)
