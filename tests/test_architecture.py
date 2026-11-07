"""Executable extraction boundaries, including dynamic imports and installed resources."""

import ast
import subprocess
import sys

import pytest
from trading_core.settings import ROOT

pytestmark = pytest.mark.core


def test_dependency_directions():
    rules = {
        "trading_core": ("products", "triad", "platform_host"),
        "products/aegis": ("products.triad", "triad", "platform_host"),
        "products/triad": ("products.aegis", "platform_host"),
    }
    violations = []
    for package, forbidden in rules.items():
        for path in (ROOT / "app" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")
                elif (
                    isinstance(node, ast.Call)
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    func = node.func
                    if (isinstance(func, ast.Name) and func.id == "__import__") or (
                        isinstance(func, ast.Attribute) and func.attr == "import_module"
                    ):
                        imports.append(str(node.args[0].value))
            for name in imports:
                if any(name == p or name.startswith(p + ".") for p in forbidden):
                    violations.append((str(path.relative_to(ROOT)), name))
    assert not violations


def test_core_startup_with_product_imports_blocked():
    code = """
import importlib.abc, sys
class BlockProducts(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'products','triad','platform_host'}:
            raise ImportError('Products deliberately unavailable')
sys.meta_path.insert(0, BlockProducts())
from trading_core.api import app
import importlib, pkgutil, trading_core
for module in pkgutil.walk_packages(trading_core.__path__, 'trading_core.'):
    importlib.import_module(module.name)
from fastapi.testclient import TestClient
client=TestClient(app)
assert client.get('/health/live').status_code==200
assert client.get('/core').status_code==200
assert client.get('/assets/record-view.js').status_code==200
assert client.post('/api/core/control', json={'action':'kill'}).status_code==401
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr


def test_packaged_defaults_match_maintained_config():
    for name in ("agents", "runtime", "research"):
        assert (ROOT / f"config/core/{name}.json").read_bytes() == (
            ROOT / f"app/trading_core/resources/config/{name}.json"
        ).read_bytes()
    for path in (ROOT / "app/trading_core/resources/sql").glob("*.sql"):
        assert path.read_bytes() == (ROOT / "infrastructure/postgres" / path.name).read_bytes()


def test_no_authority_added_and_exchange_closed():
    import pytest
    from trading_core.exchange import ExchangeCandidate, import_candidate
    from trading_core.gateway import ToolGateway
    from trading_core.work import WorkItem

    work = WorkItem(
        title="boundary",
        description="boundary",
        owner="triad",
        allowed_paths=("app/trading_core", "config", "app/products/aegis", "docs/vault/operator"),
    )
    for path in (
        "app/trading_core/ledger.py",
        "config/core/runtime.json",
        "app/products/aegis/server.py",
        "docs/vault/operator/private.md",
    ):
        with pytest.raises(PermissionError):
            ToolGateway(work).check("read_file", path)
    with pytest.raises(PermissionError):
        import_candidate(
            ExchangeCandidate(
                source_product="triad", destination_product="aegis", record_ids=("x",)
            )
        )


def test_product_rotation_is_independent_of_core_review_defaults():
    from products.triad.cycles import Cycles

    cycle = Cycles.__new__(Cycles)
    cycle.rotation = ("GROK", "CLAUDE", "CODEX")
    assert cycle.next_agent("GROK") == "CLAUDE"
    assert cycle.next_agent("CODEX") == "GROK"


def test_aegis_shell_and_legacy_redirect(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from platform_host.api import app as gateway
    from products.aegis import api, server
    from products.aegis.server import app as product

    response = TestClient(product).get("/aegis")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"] and "Aegis" in response.text
    assert TestClient(product).get("/health/live").json()["product"] == "aegis"
    # The governance contract is the status shape, not the page copy: human-directed,
    # exchange closed. Triad's post-merge verifier and Core dashboards read these fields.
    # No Core configuration is read: the worker's settings and its store are stood in for.
    monkeypatch.setitem(product.dependency_overrides, api.get_worker_settings, lambda: None)
    monkeypatch.setattr(server, "Store", lambda **_: SimpleNamespace(list_work=list))
    status = TestClient(product).get("/aegis/api/status").json()
    assert status["product"] == "aegis" and status["mode"] == "human_directed"
    assert status["exchange"] == "CLOSED" and status["work_items"] == []
    response = TestClient(gateway).get("/p2p/api/status?view=all", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/aegis/api/status?view=all"


def test_numba_is_imported_only_under_aegis():
    """The compiled engine's dependency (Mission 6 spec §4.4) stays a product library."""
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any(n == "numba" or n.startswith("numba.") for n in names):
                relative = path.relative_to(ROOT).as_posix()
                if not relative.startswith("app/products/aegis/"):
                    offenders.append(relative)
    assert offenders == []


def test_product_libraries_absent_from_core_and_triad():
    """Mission 7: numba lives only in Aegis's environment; Core's and Triad's cannot import it."""
    import importlib.util

    assert importlib.util.find_spec("numba") is None, f"numba is installed in {sys.prefix}"
    probe = "import importlib.util as u; print(u.find_spec('numba') is not None)"
    for environment, expected in ((".venv-triad", "False"), (".venv-aegis", "True")):
        python = ROOT / environment / "Scripts" / "python.exe"
        assert python.is_file(), f"missing {environment}: run tools/bootstrap.ps1"
        result = subprocess.run(
            [str(python), "-c", probe], capture_output=True, text=True, timeout=60, check=False
        )
        assert result.stdout.strip() == expected, (environment, result.stdout, result.stderr)


def test_product_settings_carry_no_core_only_secret():
    """A product worker builds its own view of Core's configuration, never the whole `Settings`
    (docs/AEGIS_WORKER_ENVIRONMENT.md): the store it is scoped to and its own key. Core's model
    keeps its fields and its required set; the product model shares the one `.env`, no second file."""
    from trading_core.settings import AegisSettings, Settings, StoreSettings

    core_only = {
        "triad_operator_token",
        "neo4j_password",
        "neo4j_user",
        "neo4j_uri",
        "ollama_url",
        "ollama_model",
        "local_model_enabled",
    }
    store = set(StoreSettings.model_fields)
    assert store == {
        "postgres_host",
        "postgres_port",
        "postgres_db",
        "postgres_user",
        "postgres_password",
    }
    assert set(Settings.model_fields) == store | core_only | {"aegis_product_key"}
    required = {name for name, field in Settings.model_fields.items() if field.is_required()}
    assert required == {"postgres_password", "neo4j_password"}
    assert set(AegisSettings.model_fields) == store | {"aegis_product_key"}
    assert not issubclass(AegisSettings, Settings)
    assert not (core_only & set(dir(AegisSettings)))
    for model in (Settings, AegisSettings):
        assert model.model_config["env_file"] == ROOT / ".env"
        assert model.model_config["extra"] == "ignore"


def test_the_store_accepts_a_product_settings_view():
    """`Store(settings=...)` is typed on the base every product view is built on, not on Core's
    whole `Settings`, and keeps the view it is given (docs/AEGIS_WORKER_ENVIRONMENT.md)."""
    import inspect
    import typing

    from pydantic import SecretStr
    from trading_core.settings import AegisSettings, StoreSettings
    from trading_core.store import Store

    annotation = inspect.signature(Store.__init__).parameters["settings"].annotation
    assert StoreSettings in typing.get_args(annotation)
    view = AegisSettings(_env_file=None, postgres_password=SecretStr("dummy-not-a-secret"))
    assert Store(settings=view, scope="aegis").settings is view


def test_local_headers_home_imports_only_the_framework():
    """The local-only middleware (2026-11-04) lives in `trading_core.http`, which imports the web
    framework and nothing of Core, so a product worker mounting it loads no operator surface;
    `trading_core.api` mounts and re-exports the same function."""
    from trading_core import api, http

    tree = ast.parse((ROOT / "app/trading_core/http.py").read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert imported and all(n.split(".")[0] in {"fastapi", "starlette"} for n in imported), imported
    assert api.local_headers is http.local_headers
    assert [m.kwargs.get("dispatch") for m in api.app.user_middleware] == [http.local_headers]
