"""Validate the autonomous product's persistent application map, not its roadmap."""

import json
import re
from typing import Literal

from pydantic import Field, model_validator
from trading_core.product_changes import product_path
from trading_core.product_sdk import SDK_FILES
from trading_core.work import Record

PLAN_PATH = "app/products/triad/application_plan.json"
WORKFLOW_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
WORKFLOW_ERROR = "Candidate application plan must retain the proposed workflow and entry point"
APPLICATION_RULES = (
    "Workflow components are an ordered producer-to-consumer chain, not an inventory of features. "
    "CONNECTED requires at least two EXISTS components and a TESTED directed connection for every "
    "adjacent pair in that exact order. Model parallel branches as separate workflows or leave the "
    "larger journey PARTIAL and identify its next missing connection. Every TESTED connection must "
    "name existing endpoints and actual product test files which pass in the offline image; skips "
    "and expected failures are not proof. EXISTS components must name actual candidate files or "
    "tracked read-only Core source. IDs must be unique and references must resolve exactly. "
    "A proposal application_contribution.workflow is the exact workflows[].id, and entry_point "
    "must match that workflow exactly. These consistency rules validate your own architecture; "
    "they do not prescribe which features or architecture to build."
)


class Component(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1)
    responsibility: str = Field(min_length=1)
    owner: Literal["triad", "core"]
    status: Literal["PLANNED", "EXISTS", "RETIRED"]
    paths: tuple[str, ...]


class Connection(Record):
    producer: str
    consumer: str
    contract: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal["PLANNED", "TESTED"]
    tests: tuple[str, ...]


class Workflow(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    user_outcome: str = Field(min_length=1)
    entry_point: str = Field(min_length=1)
    components: tuple[str, ...] = Field(min_length=1)
    status: Literal["NOT_BUILT", "PARTIAL", "CONNECTED"]
    next_connection: str = Field(min_length=1)


class ApplicationPlan(Record):
    schema_version: Literal["triad.application.v1"]
    goal: str = Field(min_length=1)
    architecture_reasoning: str = Field(min_length=1)
    components: tuple[Component, ...] = Field(min_length=1)
    connections: tuple[Connection, ...]
    workflows: tuple[Workflow, ...] = Field(min_length=1)
    decisions: tuple[str, ...]
    next_initiatives: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent(self):
        ids = [c.id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("Application component identities must be unique")
        if len({w.id for w in self.workflows}) != len(self.workflows):
            raise ValueError("Application workflow identities must be unique")
        for component in self.components:
            for path in component.paths:
                if component.owner == "triad":
                    product_path(path)
                elif not path.startswith("app/trading_core/") or ".." in path.split("/"):
                    raise ValueError("Core references cannot point at another product")
        for connection in self.connections:
            if connection.producer not in ids or connection.consumer not in ids:
                raise ValueError("Connection references an unknown component")
            if connection.status == "TESTED" and not connection.tests:
                raise ValueError("A tested connection requires executable evidence")
            if connection.status == "TESTED" and any(
                c.status != "EXISTS"
                for c in self.components
                if c.id in {connection.producer, connection.consumer}
            ):
                raise ValueError("Tested connection endpoints must exist")
            for path in connection.tests:
                product_path(path)
                if not path.startswith(
                    ("tests/products/triad/test_", "tests/products/triad/browser_")
                ) or not path.endswith(".py"):
                    raise ValueError("Connection evidence must identify product tests")
        for workflow in self.workflows:
            if not set(workflow.components) <= set(ids):
                raise ValueError("Workflow references an unknown component")
            if workflow.status == "CONNECTED":
                if any(
                    c.status != "EXISTS" for c in self.components if c.id in workflow.components
                ):
                    raise ValueError("Connected workflow components must exist")
                edges = {(c.producer, c.consumer) for c in self.connections if c.status == "TESTED"}
                if len(workflow.components) < 2 or any(
                    pair not in edges for pair in zip(workflow.components, workflow.components[1:])
                ):
                    raise ValueError("Connected workflow requires tested adjacent connections")
        return self


class ApplicationContribution(Record):
    workflow: str = Field(min_length=1)
    entry_point: str = Field(min_length=1)
    input_producer: str = Field(min_length=1)
    output_consumer: str = Field(min_length=1)
    contracts_and_versions: tuple[str, ...] = Field(min_length=1)
    integration_checks: tuple[str, ...] = Field(
        min_length=1,
        description="Exact check_id values from this proposal's acceptance criteria, not test paths or descriptions",
    )
    status: Literal["FOUNDATION", "CONNECTED_INCREMENT", "REPAIR", "DEPENDENCY_REMOVAL"]


class CurrentApplicationContribution(ApplicationContribution):
    workflow: str = Field(
        pattern=WORKFLOW_PATTERN,
        description="Exact stable workflows[].id in application_plan.json, for example dataset-workspace. Describe the user journey in user_outcome, not this identifier.",
    )


def contributed_workflow(plan, contribution):
    matches = [w for w in plan.workflows if w.id == contribution.workflow]
    if not re.fullmatch(WORKFLOW_PATTERN, contribution.workflow):
        # Historical approvals used an unconstrained prose workflow field. An
        # exact, unique entry point retains their reference without rewriting
        # that approval or weakening current identifier-based submissions.
        matches = [w for w in plan.workflows if w.entry_point == contribution.entry_point]
    if len(matches) != 1 or matches[0].entry_point != contribution.entry_point:
        raise ValueError(WORKFLOW_ERROR)
    return matches[0]


def validate_plan(files, *, core_paths=SDK_FILES):
    if PLAN_PATH not in files:
        raise ValueError("Retain the agent-owned application plan across product turns")
    plan = ApplicationPlan.model_validate(json.loads(files[PLAN_PATH]))
    for component in plan.components:
        if (
            component.status == "EXISTS"
            and component.owner == "triad"
            and (not component.paths or any(path not in files for path in component.paths))
        ):
            raise ValueError("Existing product components require actual candidate files")
        if (
            component.status == "EXISTS"
            and component.owner == "core"
            and (not component.paths or not set(component.paths) <= set(core_paths))
        ):
            raise ValueError("Existing Core components require tracked protected source")
    for connection in plan.connections:
        if connection.status == "TESTED" and any(path not in files for path in connection.tests):
            raise ValueError("Connection test evidence is missing from the candidate")
    return plan


def validate_connection_proof(plan, proof):
    passed = proof.get("passed_test_files", {})
    if proof.get("status") != "PASS" or any(
        passed.get(path, 0) < 1
        for connection in plan.connections
        if connection.status == "TESTED"
        for path in connection.tests
    ):
        raise ValueError(
            "Every tested application connection requires actual passing tests from its declared files"
        )


def current_plan():
    from importlib.resources import files

    source = files("products.triad").joinpath("application_plan.json").read_text(encoding="utf-8")
    return ApplicationPlan.model_validate_json(source)
