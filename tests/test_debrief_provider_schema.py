"""The structured provider schema must permit the host-required debrief answers."""

from types import SimpleNamespace

import pytest
from products.triad.daily import TOMORROW_KEYS, Debrief
from pydantic import Field, ValidationError, create_model
from test_daily_lifecycle import draft
from trading_core.contracts import AgentRunResult
from trading_core.runtime import strict_schema
from trading_core.work import now

pytestmark = pytest.mark.triad


def document():
    return draft(SimpleNamespace(cycle_id="schema-regression", created_at=now()))


def test_actual_artifact_envelope_permits_all_required_tomorrow_answers():
    envelope = create_model(
        "ProductArtifactResult",
        __base__=AgentRunResult,
        analysis_artifacts=(tuple[Debrief, ...], Field(min_length=1, max_length=1)),
    )
    schema = strict_schema(envelope.model_json_schema())
    answers = schema["$defs"]["Debrief"]["properties"]["what_changed_about_tomorrow"]
    assert answers["type"] == "object"
    assert answers["additionalProperties"] is False
    assert set(answers["required"]) == set(TOMORROW_KEYS)
    assert set(answers["properties"]) == set(TOMORROW_KEYS)
    assert all(field["type"] == "string" for field in answers["properties"].values())
    value = document().model_dump(mode="json")
    assert set(value["what_changed_about_tomorrow"]) == set(answers["required"])
    assert Debrief.model_validate(value).model_dump(mode="json") == value


@pytest.mark.parametrize("key", TOMORROW_KEYS)
@pytest.mark.parametrize("invalid", [None, "", " \n\t"])
def test_host_still_rejects_missing_or_blank_required_answers(key, invalid):
    value = document().model_dump(mode="json")
    if invalid is None:
        value["what_changed_about_tomorrow"].pop(key)
    else:
        value["what_changed_about_tomorrow"][key] = invalid
    with pytest.raises(ValidationError, match="all seven answers"):
        Debrief.model_validate(value)


def test_historical_dictionary_shape_and_extra_answers_remain_readable():
    value = document().model_dump(mode="json")
    value["what_changed_about_tomorrow"]["historical_extra"] = "Preserve historical evidence"
    restored = Debrief.model_validate(value)
    assert isinstance(restored.what_changed_about_tomorrow, dict)
    assert restored.model_dump(mode="json") == value
