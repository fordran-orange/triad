"""Independent G/H/I HTTP authorization and truthful surface acceptance."""
# ruff: noqa: F811

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from platform_host.api import app
from pydantic import SecretStr
from test_day3_integration import engine  # noqa: F401
from trading_core.api import service
from trading_core.integrations.api import access
from trading_core.integrations.data import DataAccess


@pytest.fixture
def operator_client(engine, monkeypatch, tmp_path):
    token = "independent-fixture-operator-key-000000000000"
    monkeypatch.setattr(
        engine.host.store,
        "settings",
        engine.host.store.settings.model_copy(update={"triad_operator_token": SecretStr(token)}),
    )
    monkeypatch.setenv("CORE_PROVIDER_MONITOR", "0")
    data = DataAccess(engine.host.store, tmp_path)
    data.registry.seed()
    data.seed()
    app.dependency_overrides[service] = lambda: engine.host
    app.dependency_overrides[access] = lambda: data
    try:
        with TestClient(app) as client:
            yield (
                client,
                data,
                {"Authorization": "Bearer " + token, "Origin": "http://127.0.0.1:8000"},
            )
    finally:
        app.dependency_overrides.clear()


def proposal(provider="QA fixture"):
    return {
        "provider": provider,
        "category": "HISTORICAL_DATA",
        "reason": "Independent offline QA proposal",
        "capabilities": ["HISTORICAL_BARS"],
        "documentation": ["https://example.com/docs"],
        "cost": "Unknown",
        "limitations": ["No connection installed"],
    }


@pytest.mark.integration
def test_operator_origin_lifecycle_and_unsupported_controls(operator_client):
    client, data, headers = operator_client
    before = data.registry.catalog()
    assert client.post("/api/core/integrations/candidates", json=proposal()).status_code == 401
    assert (
        client.post(
            "/api/core/integrations/candidates",
            json=proposal(),
            headers={**headers, "Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert data.registry.candidates() == []
    response = client.post(
        "/api/core/integrations/candidates",
        json=proposal("<img src=x onerror=alert(1)>"),
        headers=headers,
    )
    assert response.status_code == 201
    identifier = response.json()["candidate_id"]
    path = f"/api/core/integrations/candidates/{identifier}/decision"
    assert (
        client.post(
            path,
            json={"status": "APPROVED_FOR_IMPLEMENTATION", "review": "Cannot skip research"},
            headers=headers,
        ).status_code
        == 409
    )
    assert (
        client.post(
            path, json={"status": "IMPLEMENTED", "review": "Cannot self-install"}, headers=headers
        ).status_code
        == 422
    )
    for status in ("RESEARCHING", "APPROVED_FOR_IMPLEMENTATION"):
        assert (
            client.post(
                path,
                json={
                    "status": status,
                    "review": "Reviewed fixture scope; separate implementation and QA required",
                },
                headers=headers,
            ).status_code
            == 200
        )
    assert data.registry.candidates()[0]["status"] == "APPROVED_FOR_IMPLEMENTATION"
    assert data.registry.catalog() == before
    assert client.post(
        "/api/core/integrations/schwab/configure", json={}, headers=headers
    ).status_code in {404, 405}
    assert client.post(
        "/api/core/integrations/schwab/order", json={}, headers=headers
    ).status_code in {404, 405}
    assert (
        client.get("/api/core/integrations", headers={"Host": "untrusted.example"}).status_code
        == 403
    )
    latest = client.get("/api/core/integrations").json()
    assert latest["candidates"][0]["provider"] == "<img src=x onerror=alert(1)>"
    assert latest["live_execution"] == "DENIED"


def test_rejected_metadata_never_reflects_credential_like_fixture():
    token = "independent-validation-fixture-key-000000000000"
    engine_stub = SimpleNamespace(
        store=SimpleNamespace(settings=SimpleNamespace(triad_operator_token=SecretStr(token)))
    )
    calls = []
    service_stub = SimpleNamespace(
        registry=SimpleNamespace(propose=lambda candidate: calls.append(candidate))
    )
    app.dependency_overrides[service] = lambda: engine_stub
    app.dependency_overrides[access] = lambda: service_stub
    try:
        client = TestClient(app)
        marker = "q9"
        response = client.post(
            "/api/core/integrations/candidates",
            json=proposal("http://u:" + marker + "@example.com"),
            headers={"Authorization": "Bearer " + token},
        )
        assert response.status_code in {409, 422}
        assert not calls
        assert marker not in response.text
        assert "input_value" not in response.text
    finally:
        app.dependency_overrides.clear()


def test_readiness_v2_preserves_original_and_declares_nonexecuting_scope():
    root = Path(__file__).parents[1]
    original = root / "docs/improvements/real-market-readiness-criteria.md"
    assert (
        hashlib.sha256(original.read_bytes()).hexdigest()
        == "d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9"
    )
    definitions = (root / "docs/improvements/real-market-readiness-definitions-v2.md").read_text(
        encoding="utf-8"
    )
    assert "NOT EXECUTABLE" in definitions
    assert "zero missing expected regular-session bars" in definitions
    assert "zero expected bars or missing reports are NOT a pass" in definitions
    assert "explicit trading authority" in definitions
