from copy import deepcopy

import pytest
from products.triad.sequential_application import (
    ApplicationContribution,
    ApplicationPlan,
    contributed_workflow,
    current_plan,
)

pytestmark = pytest.mark.triad


def fixture_plan(ambiguous=False):
    data = current_plan().model_dump(mode="json")
    workflow = deepcopy(data["workflows"][0])
    workflow.update(
        id="dataset-workspace", entry_point="/triad/product#dataset-workspace", status="NOT_BUILT"
    )
    data["workflows"] = [workflow]
    if ambiguous:
        data["workflows"].append({**workflow, "id": "another-workflow"})
    return ApplicationPlan.model_validate(data)


def contribution(workflow, entry_point="/triad/product#dataset-workspace"):
    return ApplicationContribution(
        workflow=workflow,
        entry_point=entry_point,
        input_producer="Fixture",
        output_consumer="Fixture",
        contracts_and_versions=("fixture.v1",),
        integration_checks=("fixture",),
        status="FOUNDATION",
    )


def test_identifier_and_unchanged_historical_prose_resolve_exact_workflow():
    p = fixture_plan()
    assert contributed_workflow(p, contribution("dataset-workspace")).id == "dataset-workspace"
    assert (
        contributed_workflow(p, contribution("Supply bars and inspect a chart")).id
        == "dataset-workspace"
    )


@pytest.mark.parametrize(
    "name,entry,ambiguous",
    [
        ("unknown-workflow", "/triad/product#dataset-workspace", False),
        ("dataset-workspace", "/different", False),
        ("Supply bars", "/different", False),
        ("Supply bars", "/triad/product#dataset-workspace", True),
    ],
)
def test_ambiguous_or_changed_workflow_reference_cannot_pass(name, entry, ambiguous):
    with pytest.raises(ValueError, match="retain the proposed workflow"):
        contributed_workflow(fixture_plan(ambiguous), contribution(name, entry))
