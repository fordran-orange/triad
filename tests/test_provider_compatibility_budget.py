"""The compatibility test must leave room for a verbose model's whole structured answer.

grok-4.7 answered the transport check with 1,028-1,937 output tokens (reasoning included) in 92
blocked runs: a 1,024-token allocation stopped them (ResourceExtensionBlocked) and kept Grok
unroutable. The fixture drives the real verify(), runtime and resource policy. The "test" case is
the failure seen live; the real WorkItem reads README.md, which counts as progress and earns an
extension, so its "workitem" case only guards that the budget alone admits the answer.
"""

# ruff: noqa: F811
import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.contracts import AgentRunResult
from trading_core.providers.control import ProviderControl
from trading_core.providers.verification import verify

pytestmark = [pytest.mark.integration, pytest.mark.core]

LARGEST_OBSERVED_GROK_ANSWER = 1937


class GrokFixture:
    """A subscription CLI transport whose model writes a long structured answer."""

    transport_type = "CLI"
    transport_id = "grok_build_cli"
    agent = "GROK"
    provider = "xai"
    model = "Auto"
    actual_model = None

    def readonly_ready(self):
        return True

    def identity_data(self):
        return {"cli_version": "grok fixture"}

    def billing_source(self):
        return "SUBSCRIPTION"

    def estimate_cost(self, input_tokens, output_tokens):
        return 0.0

    def provider_metadata(self):
        return {"agent": self.agent, "provider": self.provider, "model": self.model, "mode": "REAL"}

    def provenance(self):
        return {
            "transport": self.transport_id,
            "billing_source": "SUBSCRIPTION",
            "requested_model": self.model,
            "actual_model": self.actual_model,
            "runtime_identity": self.identity_data(),
        }

    def cancel(self):
        pass

    def execute(self, request):
        self.actual_model = "grok-4.7"
        result = AgentRunResult(
            run_id=request.run_id, status="NO_CHANGE_JUSTIFIED", summary="TRIAD_TRANSPORT_OK"
        )
        return result, 4808, LARGEST_OBSERVED_GROK_ANSWER


@pytest.mark.parametrize("acceptance", [False, True], ids=["test", "workitem"])
def test_verbose_answer_fits_the_compatibility_budget(engine, monkeypatch, acceptance):
    fixture = GrokFixture()
    control = ProviderControl(engine.ledger)
    monkeypatch.setattr(control, "transport", lambda _: fixture)
    monkeypatch.setattr("trading_core.providers.control.TransportRouter.select", lambda *a: fixture)
    proof = verify(control, "grok_build_cli", acceptance=acceptance)
    assert proof.get("error") is None
    assert proof["success"] is True
    assert proof["actual_model"] == "grok-4.7"
