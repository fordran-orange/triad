"""Export portable research definitions for non-Triad consumers."""

import json

from triad.lab.contracts import BacktestRun, Bar, DatasetManifest, Experiment, Hypothesis, LabLimits
from triad.settings import ROOT

target = ROOT / "control-plane/research"
target.mkdir(parents=True, exist_ok=True)
for model in (Bar, DatasetManifest, Experiment, Hypothesis, BacktestRun, LabLimits):
    (target / f"{model.__name__}.schema.json").write_text(
        json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
