"""Restore an absent product worker (Triad on 8101, Aegis on 8102); never replay cycles or stop
a listener. One lease and one log per product; Core must be healthy first."""

import argparse
import json
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from trading_core.store import ConcurrentUpdate, Store

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"triad": 8101, "aegis": 8102}
CORE_PORT = 8000


def healthy(port, product=None):
    try:
        with build_opener(ProxyHandler({})).open(
            f"http://127.0.0.1:{port}/health/live", timeout=3
        ) as response:
            payload = json.load(response)
        return payload.get("status") == "ok" and (
            product is None or payload.get("product") == product
        )
    except (URLError, OSError, ValueError, AttributeError):
        return False


def occupied(port, timeout=10):
    # A closed loopback port on this host is refused only after ~2 s; a shorter
    # probe times out first and the supervisor then never relaunches the worker.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except ConnectionRefusedError:
        return False
    # Timeouts and other network errors are uncertainty, not permission to start.


def ensure(product, store=None):
    port = PORTS[product]
    if healthy(port, product):
        return "HEALTHY"
    if not healthy(CORE_PORT):
        raise RuntimeError("Core unavailable; product recovery deferred")
    try:
        with (store or Store()).lease(f"{product}-product-development"):
            # Recheck after acquiring the same lease used by deployment.
            if healthy(port, product):
                return "HEALTHY"
            if occupied(port):
                raise RuntimeError(f"{product} port occupied but unhealthy; owner left untouched")
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "tools/start_product.ps1"),
                    "-Product",
                    product,
                    "-OnlyIfStopped",
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=True,
                timeout=45,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if healthy(port, product):
                    return "RECOVERED"
                time.sleep(0.5)
            raise RuntimeError(f"{product} launch did not become healthy")
    except ConcurrentUpdate:
        return "DEPLOYMENT_BUSY"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=sorted(PORTS), required=True)
    product = parser.parse_args(argv).product
    event = {"timestamp": datetime.now(UTC).isoformat(), "product": product}
    code = 0
    try:
        event["status"] = ensure(product)
    except Exception as exc:  # noqa: BLE001 - preserve supervisor failure without secrets
        event.update(status="NEEDS_ATTENTION", error_class=type(exc).__name__)
        code = 1
    (ROOT / "logs").mkdir(exist_ok=True)
    with (ROOT / f"logs/{product}-supervisor.log").open("a", encoding="utf-8") as output:
        output.write(json.dumps(event) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
