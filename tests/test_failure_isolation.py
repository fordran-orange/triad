# ruff: noqa: F811
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.ledger import Stopped

pytestmark = pytest.mark.integration


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(url, process):
    for _ in range(100):
        assert process.poll() is None, "Acceptance server exited during startup"
        try:
            if httpx.get(url + "/health/live", timeout=1).status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    raise AssertionError("Acceptance server failed to start")


def test_product_crashes_leave_core_controls_enforced(engine):
    ports = {p: free_port() for p in ("core", "triad", "aegis")}
    settings = engine.host.store.settings
    env = {
        **os.environ,
        "POSTGRES_DB": settings.postgres_db,
        "CORE_PROVIDER_MONITOR": "0",
        "TRIAD_WORKER_PORT": str(ports["triad"]),
        "AEGIS_WORKER_PORT": str(ports["aegis"]),
        "TRIAD_OPERATOR_TOKEN": "isolated-acceptance-token-never-production",
    }
    processes = {}
    try:
        for product, module in (
            ("core", "platform_host.api"),
            ("triad", "products.triad.server"),
            ("aegis", "products.aegis.server"),
        ):
            processes[product] = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    module + ":app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ports[product]),
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            wait_up(f"http://127.0.0.1:{ports[product]}", processes[product])
        url = f"http://127.0.0.1:{ports['core']}"
        for product in ("triad", "aegis"):
            assert httpx.get(url + "/" + product).status_code == 200
            processes[product].terminate()
            processes[product].wait(timeout=10)
            assert httpx.get(url + "/" + product).status_code == 503
            assert httpx.get(url + "/core").status_code == 200
            assert httpx.get(url + "/api/status", timeout=30).json()["postgres"]["status"] == "up"
            response = httpx.post(
                url + "/api/core/control",
                json={"action": "kill"},
                headers={"Authorization": "Bearer " + env["TRIAD_OPERATOR_TOKEN"]},
            )
            assert response.status_code == 200
            with pytest.raises(Stopped):
                engine.ledger.guard()
            assert (
                httpx.post(
                    url + "/api/core/control",
                    json={"action": "resume"},
                    headers={"Authorization": "Bearer " + env["TRIAD_OPERATOR_TOKEN"]},
                ).status_code
                == 200
            )
            engine.ledger.guard()
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
