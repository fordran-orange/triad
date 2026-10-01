from fastapi.testclient import TestClient
from platform_host.legacy import app

client = TestClient(app)


def test_operator_shell_and_contract():
    response = client.get("/")
    assert response.status_code == 200
    assert "Live trading disabled" in response.text
    assert client.get("/health/live").json()["scope"] == "api_process_only"
    assert client.get("/api/foundation").json()["live_trading_authority"] is False


def test_no_governance_or_trading_endpoints():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/dashboard" in paths
    assert "/api/policy" not in paths
    assert "/api/trades" not in paths
    assert client.post("/api/demo", json={}).status_code == 401
    assert client.post("/api/policy", json={"live_trading_authority": True}).status_code == 404
