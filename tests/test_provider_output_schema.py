"""A Codex turn must survive the vendor's strict structured-output validation.

The Responses API rejects an object node without `properties` (HTTP 400 invalid_json_schema),
so from 2026-10-13 every Codex turn using the AgentRunResult schema ended as CodexTurnFailed.
"""

import pytest
from test_codex_completion_order import App, execute
from trading_core.contracts import AgentRunResult
from trading_core.runtime import strict_schema

pytestmark = pytest.mark.core


def strict_violations(node, path="schema"):
    """Object nodes a strict structured-output validator refuses, by the vendor's path."""
    found = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            if not isinstance(node.get("properties"), dict):
                found.append(path + ".properties")
            elif node.get("additionalProperties") is not False or set(
                node.get("required", ())
            ) != set(node["properties"]):
                found.append(path)
        for key, value in node.items():
            found += strict_violations(value, path + "." + key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found += strict_violations(value, path + "." + str(index))
    return found


def test_agent_run_result_schema_has_no_strict_violations():
    assert strict_violations(strict_schema(AgentRunResult.model_json_schema())) == []


class StrictVendorApp(App):
    """Fails the turn exactly as the vendor does when the output schema breaks strict rules."""

    def send(self, msg):
        if msg.get("method") == "turn/start":
            self.rejected = strict_violations(msg["params"]["outputSchema"])
            if self.rejected:
                self.status = "failed"
        super().send(msg)
        for event in self.queue:
            if event.get("method") == "turn/completed" and getattr(self, "rejected", None):
                event["params"]["turn"]["error"] = {
                    "message": "Invalid schema for response_format 'codex_output_schema': '"
                    + self.rejected[0]
                    + "' is required for object schemas.",
                }


@pytest.mark.parametrize("early", [False, True])
def test_codex_turn_with_agent_run_result_schema_passes_strict_validation(monkeypatch, early):
    app = StrictVendorApp(early)
    result, inputs, outputs = execute(monkeypatch, app)
    assert app.rejected == []
    assert result.run_id == "run" and (inputs, outputs) == (10, 5)
    assert app.closed
