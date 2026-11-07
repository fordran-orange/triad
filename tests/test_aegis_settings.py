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


ALLOWED_FROM_SETTINGS = {"AegisSettings", "ROOT"}


def _settings_offenders(package: Path) -> list[tuple[str, str]]:
    """Every way a module of `package` could reach Core's whole `Settings`, or build Core's store
    on it (the QA's mutations M4 and M5): each as (file, what)."""
    offenders = []
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        if "ui" in path.relative_to(package).parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = {alias.name for alias in node.names}
                if module == "trading_core.settings" and not names <= ALLOWED_FROM_SETTINGS:
                    offenders.append((relative, f"from {module} import {sorted(names)}"))
                elif module == "trading_core" and names & {"settings", "store"}:
                    offenders.append((relative, "a Core module alias that reaches Settings"))
                elif module.startswith("trading_core") and "Settings" in names:
                    offenders.append((relative, f"Settings re-exported by {module}"))
                elif module == "trading_core.store" and relative != "server.py":
                    offenders.append((relative, "the store is server.py's alone"))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in (
                        "trading_core",
                        "trading_core.settings",
                        "trading_core.store",
                    ):
                        offenders.append((relative, f"import {alias.name}"))
            elif isinstance(node, ast.Name) and node.id == "Settings":
                offenders.append((relative, "the name Settings"))
            elif isinstance(node, ast.Attribute) and node.attr == "Settings":
                offenders.append((relative, "an attribute Settings"))
            elif isinstance(node, ast.Call):
                func = node.func
                is_store = (isinstance(func, ast.Name) and func.id == "Store") or (
                    isinstance(func, ast.Attribute) and func.attr == "Store"
                )
                if is_store and not any(keyword.arg == "settings" for keyword in node.keywords):
                    offenders.append((relative, "Store(...) without settings="))
    return offenders


def _package(tmp_path: Path, **modules: str) -> Path:
    """A product-shaped package: `server.py` holds the store import, the rest is the test's."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "server.py").write_text("from trading_core.store import Store\n", encoding="utf-8")
    for name, source in modules.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
    return package


def test_no_product_module_names_cores_whole_settings():
    """The product imports Core's product-scoped model and nothing else from its settings."""
    assert _settings_offenders(Path(products.aegis.__file__).parent) == []


def test_the_guard_accepts_the_products_own_shape(tmp_path):
    package = _package(tmp_path, api="from trading_core.settings import AegisSettings, ROOT\n")
    (package / "server.py").write_text(
        "from trading_core.settings import AegisSettings\n"
        "from trading_core.store import Store\n"
        "Store(settings=AegisSettings(), scope='aegis')\n",
        encoding="utf-8",
    )
    assert _settings_offenders(package) == []


@pytest.mark.parametrize(
    ("file", "source"),
    [
        ("other", "from trading_core.settings import Settings\n"),
        ("other", "from trading_core.store import Settings\n"),  # a re-export (QA mutation M4)
        ("other", "from trading_core import settings as cfg\ncfg.Settings()\n"),
        ("other", "from trading_core import store\nstore.Settings()\n"),
        ("other", "import trading_core.settings\n"),
        ("other", "import trading_core\ntrading_core.store.Settings()\n"),
        ("other", "from trading_core.store import Store\n"),  # the store is server.py's alone
        ("server", "from trading_core.store import Store\nStore(scope='aegis')\n"),  # QA M5
        ("other", "import trading_core.store as s\ns.Store(scope='aegis')\n"),
    ],
    ids=[
        "settings-import",
        "store-reexport",
        "settings-module-alias",
        "store-module-alias",
        "settings-module",
        "package-attribute",
        "store-import-elsewhere",
        "store-without-settings",
        "aliased-store-without-settings",
    ],
)
def test_the_guard_catches_every_way_to_cores_whole_settings(tmp_path, file, source):
    assert _settings_offenders(_package(tmp_path, **{file: source})), source


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


def test_the_503_points_at_the_example_file_for_the_postgres_names_only(unconfigured_worker):
    """`.env.example` documents the Postgres names; the product key is issued by
    `tools/issue_product_key.ps1`, so the message must not send the reader there for it."""
    message = unconfigured_worker.get("/aegis/api/status").json()["detail"]["message"]
    assert message.endswith("the Postgres names are in .env.example")
    assert "see .env.example" not in message


def test_an_unreadable_configuration_is_the_same_503(monkeypatch, no_process_values):
    """A `.env` pydantic-settings cannot read raises `SettingsError`, not `ValidationError`
    (QA finding M2); the answer names no field and echoes nothing of the library's message."""
    from pydantic_settings import SettingsError

    def raising():
        raise SettingsError('error parsing value for field "postgres_port" from source "DotEnv"')

    monkeypatch.setattr(api, "AegisSettings", raising)
    monkeypatch.setattr(server, "Store", lambda **_: pytest.fail("the store must not be built"))
    answer = TestClient(server.app, raise_server_exceptions=False).get("/aegis/api/status")
    assert answer.status_code == 503
    detail = answer.json()["detail"]
    assert detail["reason"] == "worker_unconfigured" and detail["fields"] == []
    assert "could not be read" in detail["message"] and "DotEnv" not in answer.text
