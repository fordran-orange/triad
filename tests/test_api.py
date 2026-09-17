from fastapi.testclient import TestClient
from triad.api import app

client = TestClient(app)


def test_operator_shell_and_contract():
    response = client.get("/")
    assert response.status_code == 200
    assert "Execution disabled" in response.text
    assert client.get("/health/live").json()["scope"] == "api_process_only"
    assert client.get("/api/foundation").json()["live_trading_authority"] is False


def test_no_mutation_or_trading_endpoints():
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {"/health/live", "/api/foundation"}
    assert all(set(methods) == {"get"} for methods in paths.values())
    assert client.post("/api/policy", json={"live_trading_authority": True}).status_code == 404
