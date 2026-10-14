# ruff: noqa: F811
import pytest
from fastapi.testclient import TestClient
from platform_host.api import app
from products.triad.server import app as product_app
from test_day3_integration import engine  # noqa: F401
from trading_core.api import service
from trading_core.integrations.api import access
from trading_core.integrations.data import DataAccess

pytestmark = pytest.mark.triad


@pytest.mark.integration
def test_integration_ui_readonly_and_changes_require_operator(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("CORE_PROVIDER_MONITOR", "0")
    data = DataAccess(engine.host.store, tmp_path)
    data.registry.seed()
    data.seed()
    app.dependency_overrides[service] = lambda: engine.host
    app.dependency_overrides[access] = lambda: data
    try:
        with TestClient(app) as client:
            assert client.get("/core/integrations").status_code == 200
            assert client.get("/assets/integrations.js").status_code == 200
            snapshot = client.get("/api/core/integrations").json()
            assert len(snapshot["integrations"]) == 3 and snapshot["live_execution"] == "DENIED"
            assert client.post("/api/core/integrations/schwab/check", json={}).status_code == 401
            assert client.post("/api/core/integrations/candidates", json={}).status_code == 401
            response = client.post(
                "/api/core/integrations/match",
                json={
                    "symbols": ["SPY"],
                    "start": "2026-09-17T13:30:00Z",
                    "end": "2026-09-17T20:00:00Z",
                },
            )
            assert response.status_code == 200 and response.json()["eligible"] == []
            assert data.registry.candidates() == []
    finally:
        app.dependency_overrides.clear()


def test_launcher_and_honest_product_shell(monkeypatch):
    monkeypatch.setenv("CORE_PROVIDER_MONITOR", "0")
    with TestClient(app) as client:
        page = client.get("/launch")
        assert page.status_code == 200
        for path in ("/core", "/triad/product", "/triad/development", "/triad/cycles", "/aegis"):
            assert path in page.text
        assert "EARLY PRODUCT SHELL" in page.text
    client = TestClient(product_app)
    page = client.get("/triad/product")
    assert page.status_code == 200 and "EARLY PRODUCT" in page.text
    assert "There is no live account" in page.text
    assert "do not establish real-market readiness or strategy performance" in page.text
    assert 'href="/core' not in page.text and 'href="/settings' not in page.text
