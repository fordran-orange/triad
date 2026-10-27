"""Provider format schemas must be complete without changing runtime contracts."""

import copy

import pytest
from pydantic import Field, create_model
from trading_core.contracts import AgentRunResult
from trading_core.product_changes import AcceptanceAssessment
from trading_core.runtime import strict_schema

pytestmark = pytest.mark.core


def assert_provider_objects_complete(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert isinstance(node.get("properties"), dict)
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for value in node.values():
            assert_provider_objects_complete(value)
    elif isinstance(node, list):
        for value in node:
            assert_provider_objects_complete(value)


def test_untyped_review_artifact_has_valid_closed_object_branch():
    original = AgentRunResult.model_json_schema()
    saved = copy.deepcopy(original)
    schema = strict_schema(original)
    assert_provider_objects_complete(schema)
    object_branch = schema["properties"]["analysis_artifacts"]["items"]["anyOf"][1]
    assert object_branch["properties"] == {}
    assert schema["properties"]["analysis_artifacts"]["items"]["anyOf"][0] == {"type": "string"}
    assert original == saved
    assert strict_schema(schema) == schema


def test_typed_acceptance_artifact_keeps_all_fields_and_references():
    envelope = create_model(
        "AcceptanceEnvelope",
        __base__=AgentRunResult,
        analysis_artifacts=(tuple[AcceptanceAssessment, ...], Field(min_length=1, max_length=1)),
    )
    original = envelope.model_json_schema()
    schema = strict_schema(original)
    assert_provider_objects_complete(schema)
    assert (
        schema["properties"]["analysis_artifacts"]["items"]
        == original["properties"]["analysis_artifacts"]["items"]
    )
    assert set(schema["$defs"]["AcceptanceAssessment"]["properties"]) == set(
        AcceptanceAssessment.model_fields
    )
    assert set(schema["properties"]) == set(AgentRunResult.model_fields)


def test_nested_dictionary_and_array_union_preserves_existing_fields():
    schema = strict_schema(
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {"type": "object", "additionalProperties": True},
                            {"type": "object", "properties": {"value": {"type": "string"}}},
                            {"type": "null"},
                        ]
                    },
                },
            },
        }
    )
    assert_provider_objects_complete(schema)
    choices = schema["properties"]["items"]["items"]["anyOf"]
    assert choices[1]["properties"] == {"value": {"type": "string"}}
    assert choices[2] == {"type": "null"}
