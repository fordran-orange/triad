"""The local-only middleware's home (2026-11-04): the Aegis worker mounts `local_headers` from
`trading_core.http` without loading Core's operator surface, and what the middleware does is
unchanged: the four headers on every local answer, 403 off localhost."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import products.aegis
import pytest
from fastapi.testclient import TestClient
from products.aegis import server
from trading_core import http

pytestmark = pytest.mark.aegis

# Core's operator surface: the gateway's app module, what it imports and the routers it mounts.
# None of it belongs in a product process; the middleware alone used to drag all of it in.
OPERATOR_SURFACE = {
    "trading_core.api",
    "trading_core.brain",
    "trading_core.orchestrator",
    "trading_core.runtime",
    "trading_core.status",
    "trading_core.operator_api",
    "trading_core.conversation_api",
    "trading_core.product_reasoning_api",
    "trading_core.intelligence.api",
    "trading_core.integrations.api",
    "trading_core.providers.api",
    "trading_core.research.api",
}
# Byte for byte the value `trading_core.api` set before the move (api.py at 7c30d15).
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"


def test_importing_the_worker_leaves_core_operator_surface_out():
    """A fresh interpreter (this scope's, on this checkout's PYTHONPATH) imports the worker's
    server module and reports every Core module that import loaded."""
    code = (
        "import json, sys\n"
        "import products.aegis.server\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('trading_core'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    loaded = set(json.loads(result.stdout.strip().splitlines()[-1]))
    assert "trading_core.http" in loaded, sorted(loaded)
    assert not loaded & OPERATOR_SURFACE, sorted(loaded & OPERATOR_SURFACE)


def test_the_worker_mounts_the_middleware_from_its_home():
    assert server.local_headers is http.local_headers
    assert [m.kwargs.get("dispatch") for m in server.app.user_middleware] == [http.local_headers]


def test_no_aegis_module_imports_the_operator_surface():
    offenders = []
    for path in Path(products.aegis.__file__).parent.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "trading_core.api" or n.startswith("trading_core.api.") for n in names):
                offenders.append(path.name)
    assert offenders == []


def test_the_headers_and_the_local_host_refusal_are_unchanged():
    client = TestClient(server.app)
    response = client.get("/health/live")
    assert response.status_code == 200, response.text
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Security-Policy"] == CSP
    for host in ("127.0.0.1:8102", "localhost:8102", "testserver"):
        assert client.get("/health/live", headers={"host": host}).status_code == 200, host
    refused = client.get("/health/live", headers={"host": "aegis.example.net:8102"})
    assert refused.status_code == 403 and refused.json() == {"detail": "Local host required"}
