"""Local identity evidence survives outages, never current connection failures."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from trading_core.providers.control import ProviderControl
from trading_core.runtime import ProviderError
from trading_core.work import now


class LocalFixture:
    transport_type = "LOCAL"
    agent = "LOCAL_QWEN"

    def __init__(self):
        self.base = "http://127.0.0.1:11434"
        self.version = "0.17.0"
        self.fail_at = None

    def detect(self):
        return {"auth_state": "NOT_AUTHENTICATED", "install_status": "NOT_APPLICABLE"}

    def health_check(self):
        down = self.fail_at == "health"
        return SimpleNamespace(
            status="UNAVAILABLE" if down else "AVAILABLE",
            error_class="ConnectionRefused" if down else None,
            latency=0,
        )

    def list_models(self):
        if self.fail_at in {"health", "models"}:
            raise ProviderError("UNAVAILABLE", "ConnectionRefused")
        return {"endpoint": self.base, "models": ["qwen3:4b"]}

    def adapter(self):
        return self

    def transport(self, path):
        assert path == "/api/version"
        if self.fail_at == "version":
            raise ProviderError("UNAVAILABLE", "LocalTimeout")
        return {"version": self.version}


@pytest.fixture
def local_control():
    adapter = LocalFixture()
    proof = {"success": True, "mode": "REAL", "completed_at": now().isoformat()}
    state = {
        "endpoint": adapter.base,
        "local_version": adapter.version,
        "test": proof,
        "workitem": proof,
    }
    history = []

    def put(kind, value, **kwargs):
        assert kind == "TransportStatus"
        state.clear()
        state.update(deepcopy(value))
        history.append(deepcopy(value))

    host = SimpleNamespace(
        transport=lambda _: adapter,
        snapshot=lambda _: deepcopy(state),
        ledger=SimpleNamespace(put=put),
    )
    return host, adapter, proof, history


@pytest.mark.parametrize("failure", ["health", "models", "version", "missing_version"])
def test_outage_retains_identity_but_stays_offline_then_recovers(local_control, failure):
    host, adapter, proof, history = local_control
    adapter.fail_at = failure
    if failure == "missing_version":
        adapter.version = None
    for _ in range(2):
        failed = ProviderControl._refresh(host, "ollama")
        assert failed["test"] == failed["workitem"] == proof
        assert failed["local_version"] == "0.17.0"
        assert failed["reachability"] == "UNAVAILABLE" and failed["error"]
        assert not ProviderControl.proven(failed)
        assert ProviderControl.readiness_state(failed) != "ONLINE"
    adapter.fail_at = None
    adapter.version = "0.17.0"
    recovered = ProviderControl._refresh(host, "ollama")
    assert recovered["test"] == recovered["workitem"] == proof
    assert recovered["error"] is None and recovered["reachability"] == "AVAILABLE"
    assert ProviderControl.readiness_state(recovered) == "ONLINE"
    assert len(history) == 3


def test_real_version_change_after_outage_invalidates_proofs(local_control):
    host, adapter, _, _ = local_control
    adapter.fail_at = "health"
    ProviderControl._refresh(host, "ollama")
    adapter.fail_at = None
    adapter.version = "0.18.0"
    changed = ProviderControl._refresh(host, "ollama")
    assert changed["test"] is changed["workitem"] is None
    assert changed["local_version"] == "0.18.0"
    assert ProviderControl.readiness_state(changed) == "VERIFICATION_REQUIRED"


@pytest.mark.parametrize("failure", [None, "health", "version"])
def test_endpoint_change_invalidates_even_when_identity_probe_fails(local_control, failure):
    host, adapter, _, _ = local_control
    adapter.base = "http://127.0.0.1:11435"
    adapter.fail_at = failure
    changed = ProviderControl._refresh(host, "ollama")
    assert changed["endpoint"] == adapter.base
    assert changed["test"] is changed["workitem"] is None
    assert not ProviderControl.proven(changed)
    adapter.fail_at = None
    recovered = ProviderControl._refresh(host, "ollama")
    assert recovered["test"] is recovered["workitem"] is None
    assert ProviderControl.readiness_state(recovered) == "VERIFICATION_REQUIRED"


def test_outage_without_prior_identity_does_not_create_proof(local_control):
    host, adapter, _, _ = local_control
    host.snapshot = lambda _: {}
    adapter.fail_at = "health"
    failed = ProviderControl._refresh(host, "ollama")
    assert failed["test"] is failed["workitem"] is None
    assert not ProviderControl.proven(failed)
