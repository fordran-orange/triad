"""The worker's view of Core's configuration (docs/AEGIS_WORKER_ENVIRONMENT.md): its work-item
store and its own product key, nothing of Core's alone. No test here reads ROOT/.env; every value
is a dummy written by the test."""

import ast
from pathlib import Path
from types import SimpleNamespace

import products.aegis
import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from pydantic import SecretStr, ValidationError
from trading_core.settings import AegisSettings, Settings, StoreSettings

pytestmark = pytest.mark.aegis

STORE_FIELDS = {
    "postgres_host",
    "postgres_port",
    "postgres_db",
    "postgres_user",
    "postgres_password",
}
CORE_ONLY = {
    "triad_operator_token",
    "neo4j_password",
    "neo4j_user",
    "neo4j_uri",
    "ollama_url",
    "ollama_model",
    "local_model_enabled",
}
# Every name the repository's .env carries (names only; the values below are dummies).
ENV_NAMES = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "NEO4J_URI",
    "NEO4J_HTTP_PORT",
    "NEO4J_BOLT_PORT",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "LOCAL_MODEL_ENABLED",
    "TRIAD_OPERATOR_TOKEN",
    "AEGIS_PRODUCT_KEY",
]


def dummy(name: str) -> str:
    return f"dummy-{name.lower()}-0123456789"


@pytest.fixture
def no_process_values(monkeypatch):
    """The process holds none of the .env names, so the file (or its absence) decides."""
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_the_worker_settings_hold_its_store_and_its_key_only():
    assert set(StoreSettings.model_fields) == STORE_FIELDS
    assert set(AegisSettings.model_fields) == STORE_FIELDS | {"aegis_product_key"}
    assert not issubclass(AegisSettings, Settings)


def test_a_full_env_file_materializes_no_core_only_value(tmp_path, no_process_values):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "".join(f"{name}={dummy(name)}\n" for name in ENV_NAMES)
        + "POSTGRES_PORT=55432\nLOCAL_MODEL_ENABLED=false\n",
        encoding="utf-8",
    )
    settings = AegisSettings(_env_file=env_file)
    assert settings.postgres_password.get_secret_value() == dummy("POSTGRES_PASSWORD")
    assert settings.aegis_product_key.get_secret_value() == dummy("AEGIS_PRODUCT_KEY")
    assert settings.postgres_host == dummy("POSTGRES_HOST") and settings.postgres_port == 55432
    held = repr(settings) + settings.model_dump_json() + repr(vars(settings))
    for name in ("TRIAD_OPERATOR_TOKEN", "NEO4J_PASSWORD", "NEO4J_URI", "OLLAMA_URL"):
        assert dummy(name) not in held, name
    assert not hasattr(settings, "triad_operator_token")
    assert settings.model_extra in (None, {})


def test_process_values_for_core_only_names_are_not_materialized_either(
    monkeypatch, no_process_values
):
    monkeypatch.setenv("POSTGRES_PASSWORD", dummy("POSTGRES_PASSWORD"))
    monkeypatch.setenv("TRIAD_OPERATOR_TOKEN", dummy("TRIAD_OPERATOR_TOKEN"))
    monkeypatch.setenv("NEO4J_PASSWORD", dummy("NEO4J_PASSWORD"))
    settings = AegisSettings(_env_file=None)
    held = repr(settings) + settings.model_dump_json() + repr(vars(settings))
    assert dummy("TRIAD_OPERATOR_TOKEN") not in held and dummy("NEO4J_PASSWORD") not in held


def test_only_the_postgres_password_is_required(no_process_values):
    with pytest.raises(ValidationError) as caught:
        AegisSettings(_env_file=None)
    assert [error["loc"] for error in caught.value.errors()] == [("postgres_password",)]


def test_the_status_route_hands_the_worker_settings_to_the_store(monkeypatch):
    given = AegisSettings(_env_file=None, postgres_password=SecretStr(dummy("POSTGRES_PASSWORD")))
    seen = {}

    def store(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(list_work=list)

    monkeypatch.setattr(server, "Store", store)
    server.app.dependency_overrides[api.get_worker_settings] = lambda: given
    try:
        body = TestClient(server.app).get("/aegis/api/status").json()
    finally:
        server.app.dependency_overrides.clear()
    assert body["work_items"] == [] and body["exchange"] == "CLOSED"
    assert (
        seen["settings"] is given
        and seen["scope"] == "aegis"
        and set(seen) == {"settings", "scope"}
    )


def test_the_reasoning_client_takes_its_key_from_the_worker_settings():
    given = AegisSettings(
        _env_file=None,
        postgres_password=SecretStr(dummy("POSTGRES_PASSWORD")),
        aegis_product_key=SecretStr("k" * 48),
    )
    assert api.get_core_reasoning(given).key == "k" * 48


def test_the_worker_dependency_builds_the_product_model(monkeypatch):
    built = object()
    monkeypatch.setattr(api, "AegisSettings", lambda: built)
    assert api.get_worker_settings() is built


def test_no_product_module_names_cores_whole_settings():
    """The product imports Core's product-scoped model and nothing else from its settings."""
    package = Path(products.aegis.__file__).parent
    offenders = []
    for path in package.rglob("*.py"):
        if "ui" in path.relative_to(package).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "trading_core.settings":
                names = {alias.name for alias in node.names}
                if not names <= {"AegisSettings", "ROOT"}:
                    offenders.append((str(path.relative_to(package)), sorted(names)))
            elif isinstance(node, ast.Import) and any(
                alias.name == "trading_core.settings" for alias in node.names
            ):
                offenders.append((str(path.relative_to(package)), ["trading_core.settings"]))
    assert offenders == []


@pytest.fixture
def unconfigured_worker(monkeypatch, no_process_values):
    """The worker's settings cannot be built: the dependency meets the real error a checkout
    without `.env` raises, while the process holds dummy values an answer must never show."""
    monkeypatch.setenv("TRIAD_OPERATOR_TOKEN", dummy("TRIAD_OPERATOR_TOKEN"))
    monkeypatch.setenv("POSTGRES_HOST", dummy("POSTGRES_HOST"))
    with pytest.raises(ValidationError) as caught:
        AegisSettings(_env_file=None)
    error = caught.value

    def raising():
        raise error

    monkeypatch.setattr(api, "AegisSettings", raising)
    monkeypatch.setattr(server, "Store", lambda **_: pytest.fail("the store must not be built"))
    return TestClient(server.app, raise_server_exceptions=False)


def test_a_missing_store_credential_is_a_503_naming_the_field(unconfigured_worker):
    answer = unconfigured_worker.get("/aegis/api/status")
    assert answer.status_code == 503
    detail = answer.json()["detail"]
    assert detail["reason"] == "worker_unconfigured"
    assert detail["fields"] == [{"name": "postgres_password", "type": "missing"}]
    assert "postgres_password" in detail["message"]
    assert dummy("TRIAD_OPERATOR_TOKEN") not in answer.text
    assert dummy("POSTGRES_HOST") not in answer.text


def test_the_providers_route_answers_the_same_503(unconfigured_worker):
    answer = unconfigured_worker.get("/aegis/api/phrases/providers")
    assert answer.status_code == 503
    assert answer.json()["detail"]["reason"] == "worker_unconfigured"


def test_health_live_needs_no_configuration(unconfigured_worker):
    assert unconfigured_worker.get("/health/live").json()["status"] == "ok"
