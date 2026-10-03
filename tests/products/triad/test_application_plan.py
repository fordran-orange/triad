"""Exact application-plan field and enum rules, plus reference integrity."""
import copy
import json
from pathlib import Path
from typing import Literal, Annotated
import unittest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

Text = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
class Component(Strict):
    id: Identifier
    name: Text
    responsibility: Text
    owner: Literal["triad","core"]
    status: Literal["PLANNED","EXISTS","RETIRED"]
    paths: list[str]
class Connection(Strict):
    producer: str
    consumer: str
    contract: Text
    version: Text
    status: Literal["PLANNED","TESTED"]
    tests: list[str]
class Workflow(Strict):
    id: Identifier
    user_outcome: Text
    entry_point: Text
    components: list[str] = Field(min_length=1)
    status: Literal["NOT_BUILT","PARTIAL","CONNECTED"]
    next_connection: Text
class Plan(Strict):
    schema_version: Literal["triad.application.v1"]
    goal: Text
    architecture_reasoning: Text
    components: list[Component] = Field(min_length=1)
    connections: list[Connection]
    workflows: list[Workflow] = Field(min_length=1)
    decisions: list[str]
    next_initiatives: list[str] = Field(min_length=1)

class ApplicationPlanTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(Path("app/products/triad/application_plan.json").read_text())

    def test_complete_schema_and_references(self):
        plan=Plan.model_validate(self.data)
        ids=[c.id for c in plan.components]
        self.assertEqual(len(ids),len(set(ids)))
        workflows=[w.id for w in plan.workflows]
        self.assertEqual(len(workflows),len(set(workflows)))
        for c in plan.connections:
            self.assertIn(c.producer,ids)
            self.assertIn(c.consumer,ids)
            if c.status=="TESTED":
                self.assertTrue(c.tests)
            for path in c.tests:
                self.assertTrue(Path(path).is_file(),path)
        for w in plan.workflows:
            self.assertTrue(set(w.components)<=set(ids))
        self.assertEqual(plan.workflows[0].status,"PARTIAL")

    def test_retained_manifest_errors_rejected(self):
        for key,value in (("identity_specification",{}),("transformations",[]),
                          ("provenance_limits",[]),("verification_references",[]),("remaining_gaps",[])):
            with self.assertRaises(ValidationError):
                Plan.model_validate({**self.data,key:value})
        for section,key,value in [
            ("components","status","IMPLEMENTED"),
            ("connections","status","IMPLEMENTED_REQUIRES_INDEPENDENT_QA"),
            ("workflows","status","CONNECTED_INCREMENT"),
            ("workflows","api","/invalid")]:
            data=copy.deepcopy(self.data)
            data[section][0][key]=value
            with self.assertRaises(ValidationError):
                Plan.model_validate(data)
        data=copy.deepcopy(self.data)
        del data["connections"][0]["version"]
        with self.assertRaises(ValidationError):
            Plan.model_validate(data)
