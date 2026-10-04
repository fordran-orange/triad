"""Exact supplied schema and directed application-graph consistency."""
import copy
import importlib.util
import json
from pathlib import Path
from typing import Literal, Annotated
import unittest
from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Component(Strict):
    id: Identifier
    name: Text
    responsibility: Text
    owner: Literal["triad", "core"]
    status: Literal["PLANNED", "EXISTS", "RETIRED"]
    paths: list[str]


class Connection(Strict):
    producer: str
    consumer: str
    contract: Text
    version: Text
    status: Literal["PLANNED", "TESTED"]
    tests: list[str]


class Workflow(Strict):
    id: Identifier
    user_outcome: Text
    entry_point: Text
    components: list[str] = Field(min_length=1)
    status: Literal["NOT_BUILT", "PARTIAL", "CONNECTED"]
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


# Exact read-only Core references supplied with this proposal, resolved in the SDK image.
CORE_PATHS = {
    "app/trading_core/research/contracts.py",
    "app/trading_core/research/engine.py",
    "app/trading_core/product_sdk.py",
}


def exists(path):
    if path in CORE_PATHS:
        spec = importlib.util.find_spec(path[4:-3].replace("/", "."))
        return spec is not None and spec.origin and Path(spec.origin).is_file()
    return Path(path).is_file()


def validate(data):
    plan = Plan.model_validate(data)
    def require(condition, message):
        if not condition:
            raise ValueError(message)
    components = {c.id:c for c in plan.components}
    require(len(components)==len(plan.components), "Duplicate component IDs")
    require(len({w.id for w in plan.workflows})==len(plan.workflows), "Duplicate workflow IDs")
    edges = set()
    for c in plan.components:
        if c.status=="EXISTS":
            require(c.paths and all(exists(p) for p in c.paths), "Missing component files")
    for edge in plan.connections:
        require(edge.producer in components and edge.consumer in components, "Missing endpoint")
        key = (edge.producer, edge.consumer)
        require(key not in edges, "Duplicate connection")
        edges.add(key)
        if edge.status=="TESTED":
            require(all(components[x].status=="EXISTS" for x in key), "TESTED endpoint must EXIST")
            require(edge.tests and all(p.startswith("tests/products/triad/") and Path(p).is_file()
                                       for p in edge.tests), "Missing product test files")
    tested = {(e.producer,e.consumer) for e in plan.connections if e.status=="TESTED"}
    for w in plan.workflows:
        require(all(c in components for c in w.components), "Missing workflow component")
        require(len(w.components)==len(set(w.components)), "Duplicate workflow component")
        if w.status=="CONNECTED":
            require(len(w.components)>=2 and all(components[c].status=="EXISTS" for c in w.components),
                    "Connected workflow requires at least two EXISTS components")
            require(all(pair in tested for pair in zip(w.components,w.components[1:])),
                    "Connected workflow requires tested adjacent connections")
    return plan


class ApplicationPlanTest(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(Path("app/products/triad/application_plan.json").read_text())

    def test_schema_graph_and_mount(self):
        plan=validate(self.data)
        workflow=next(w for w in plan.workflows if w.id=="trading-application")
        self.assertEqual(workflow.status,"CONNECTED")
        self.assertEqual(workflow.entry_point,"/triad/product")
        from products.triad.product_app import app
        self.assertIn("/research/dataset-preparation", {r.path for r in app.routes})
        self.assertIn("/triad/product-api/research/dataset-preparation",
                      Path("app/products/triad/static/product.html").read_text())

    def test_invalid_graphs(self):
        mutations = [
            lambda d: d["connections"].__setitem__(slice(None), [e for e in d["connections"]
                       if (e["producer"],e["consumer"])!=("workspace","bar-inspector")]),
            lambda d: next(e for e in d["connections"] if e["producer"]=="workspace").update(
                producer="bar-inspector",consumer="workspace"),
            lambda d: d["components"][0].update(status="PLANNED"),
            lambda d: d["components"][0].update(paths=["missing.py"]),
            lambda d: d["connections"][0].update(tests=["tests/products/triad/missing.py"]),
            lambda d: d["connections"][0].update(consumer="missing"),
            lambda d: d["components"].append(copy.deepcopy(d["components"][0])),
            lambda d: d["workflows"].append(copy.deepcopy(d["workflows"][0])),
            lambda d: d["connections"].append(copy.deepcopy(d["connections"][0])),
            lambda d: d["workflows"][1].update(components=["workspace"]),
            lambda d: d["workflows"][1].update(components=["workspace","missing"]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                data=copy.deepcopy(self.data); mutate(data)
                with self.assertRaises(ValueError):
                    validate(data)

    def test_unsupported_keys_enums_and_required_fields(self):
        for section in (None,"components","connections","workflows"):
            target = self.data if section is None else self.data[section][0]
            for key in target:
                data=copy.deepcopy(self.data)
                node=data if section is None else data[section][0]
                del node[key]
                with self.assertRaises(ValueError):
                    validate(data)
            data=copy.deepcopy(self.data)
            (data if section is None else data[section][0])["unsupported"]=True
            with self.assertRaises(ValueError):
                validate(data)
        for section,key in (("components","status"),("components","owner"),
                            ("connections","status"),("workflows","status")):
            data=copy.deepcopy(self.data); data[section][0][key]="UNSUPPORTED"
            with self.assertRaises(ValueError):
                validate(data)

    def test_handoff_tested_and_chart_overlay_planned(self):
        plan=validate(self.data)
        pairs={(e.producer,e.consumer):e for e in plan.connections}
        handoff=pairs[("dataset-preparation","experiments")]
        self.assertEqual(handoff.status,"TESTED")
        self.assertEqual(handoff.contract,"core.product-research")
        self.assertIn("tests/products/triad/browser_experiment.py", handoff.tests)
        chart=pairs[("experiments","chart-workspace")]
        self.assertEqual(chart.status,"PLANNED")
        self.assertEqual(chart.tests,[])
        self.assertFalse(any(e.producer=="experiments" and e.consumer=="chart-workspace" and e.status=="TESTED" for e in plan.connections))
        decisions=" ".join(plan.decisions)
        self.assertIn("existing eligible core_input", decisions)
        self.assertNotIn("equity-curve fields exist", decisions.lower())
        for workflow in plan.workflows:
            self.assertIn("chart", workflow.next_connection.lower())
        self.assertTrue(plan.next_initiatives[0].lower().startswith("overlay experiment"))
