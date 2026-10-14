"""Independent offline daily UI/API checks; no workers or production services."""

# ruff: noqa: I001 - initialize Core before product routers
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from trading_core import api as core_api
from products.triad import daily_api, server

pytestmark = pytest.mark.triad


@pytest.fixture
def client():
    schedule = {
        "enabled": False,
        "time": "09:00",
        "timezone": "America/Chicago",
        "days": [0, 1, 2, 3, 4, 5, 6],
        "effective_after": None,
    }
    calls = []

    def configure(body):
        calls.append(body.model_dump())
        schedule.update(body.model_dump())
        return "test-schedule"

    # Scheduling notifies the worker through the host store; keep that offline and silent.
    quiet_store = SimpleNamespace(
        connect=lambda: nullcontext(SimpleNamespace(execute=lambda *args, **kwargs: None))
    )
    stub = SimpleNamespace(
        debriefs=list,
        schedule=lambda: dict(schedule),
        configure=configure,
        host=SimpleNamespace(store=quiet_store),
    )
    token = "offline-test-key-" + "x" * 32
    server.app.dependency_overrides[daily_api.daily] = lambda: stub
    server.app.dependency_overrides[core_api.service] = lambda: SimpleNamespace(
        store=SimpleNamespace(settings=SimpleNamespace(triad_operator_token=SecretStr(token)))
    )
    # Do not enter TestClient context: product startup would start a real worker.
    client = TestClient(server.app, raise_server_exceptions=False)
    yield client, stub, calls, token
    server.app.dependency_overrides.clear()


def test_public_history_and_schedule_are_read_only(client):
    c, _, calls, _ = client
    assert c.get("/triad/api/daily-debriefs").json() == {"debriefs": []}
    assert c.get("/triad/api/daily-schedule").json()["enabled"] is False
    assert calls == []


@pytest.mark.parametrize(
    "auth,origin,expected",
    [
        (False, None, 401),
        (True, "https://untrusted.invalid", 403),
        (True, "http://127.0.0.1:8000", 200),
    ],
)
def test_schedule_requires_existing_local_authorization(client, auth, origin, expected):
    c, _, calls, key = client
    headers = {"Authorization": "Bearer " + key} if auth else {}
    if origin:
        headers["Origin"] = origin
    r = c.post(
        "/triad/api/daily-schedule",
        json={"enabled": False, "time": "11:15", "timezone": "America/Chicago", "days": [1, 3]},
        headers=headers,
    )
    assert r.status_code == expected
    assert len(calls) == (1 if expected == 200 else 0)
    assert key not in r.text


def test_invalid_schedule_no_write(client):
    c, _, calls, key = client
    r = c.post(
        "/triad/api/daily-schedule",
        json={"enabled": False, "time": "25:99", "timezone": "America/Chicago", "days": [9]},
        headers={"Authorization": "Bearer " + key},
    )
    assert r.status_code == 422
    assert calls == []


def test_feature_placeholder_is_explicit_not_missing_page(client, monkeypatch, tmp_path):
    monkeypatch.setattr(daily_api, "__file__", str(tmp_path / "daily_api.py"))
    c, _, _, _ = client
    for path in ["/triad/product/research-readiness", "/triad/assets/research-readiness.js"]:
        r = c.get(path)
        assert r.status_code == 503
        assert "review" in r.json()["detail"]


def test_reviewed_feature_assets_are_served_when_present(client, monkeypatch, tmp_path):
    monkeypatch.setattr(daily_api, "__file__", str(tmp_path / "daily_api.py"))
    feature = tmp_path / "features"
    feature.mkdir()
    (feature / "research_readiness.html").write_text("<h1>Fixture readiness</h1>", encoding="utf-8")
    (feature / "research_readiness.js").write_text("// Fixture asset", encoding="utf-8")
    c, _, _, _ = client
    assert c.get("/triad/product/research-readiness").text == "<h1>Fixture readiness</h1>"
    response = c.get("/triad/assets/research-readiness.js")
    assert response.status_code == 200 and "javascript" in response.headers["content-type"]


def test_service_failure_is_readable_and_does_not_write(client):
    c, stub, calls, _ = client

    def denied():
        raise PermissionError("Reviewed evidence is unavailable")

    stub.debriefs = denied
    r = c.get("/triad/api/daily-debriefs")
    assert r.status_code == 403
    assert isinstance(r.json()["detail"], str)
    assert calls == []


@pytest.mark.parametrize(
    "path", ["/triad/product", "/triad/development", "/triad/cycles", "/triad/daily-debrief"]
)
def test_utf8_navigation_remains_readable(client, path):
    c, _, _, _ = client
    r = c.get(path)
    assert r.status_code == 200
    r.content.decode("utf-8", "strict")
    assert "/triad/daily-debrief" in r.text
    assert not any(marker in r.text for marker in ("\u00c2\u00b7", "\u00e2\u20ac", "\ufffd"))
