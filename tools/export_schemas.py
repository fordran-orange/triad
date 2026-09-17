import json

from triad.market import Candle1m
from triad.policy import AuthorityRequest, Intent, RuntimePolicy
from triad.settings import ROOT

for name, model in [
    ("intent", Intent),
    ("runtime_policy", RuntimePolicy),
    ("authority_request", AuthorityRequest),
]:
    (ROOT / f"control-plane/{name}.schema.json").write_text(
        json.dumps(model.model_json_schema(), indent=2) + "\n"
    )
(ROOT / "data/candle_1m.schema.json").write_text(
    json.dumps(Candle1m.model_json_schema(), indent=2) + "\n"
)
print("Exported four JSON schemas")
