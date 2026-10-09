"""Restore an absent Triad UI worker; never replay cycles or stop a listener."""

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


def occupied(port=8101, timeout=10):
    # A closed loopback port on this host is refused only after ~2 s; a shorter
    # probe times out first and the supervisor then never relaunches the worker.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except ConnectionRefusedError:
        return False
    # Timeouts and other network errors are uncertainty, not permission to start.


def ensure(store=None):
    if healthy(8101, "triad"):
        return "HEALTHY"
    if not healthy(8000):
        raise RuntimeError("Core unavailable; product recovery deferred")
    try:
        with (store or Store()).lease("triad-product-development"):
            # Recheck after acquiring the same lease used by deployment.
            if healthy(8101, "triad"):
                return "HEALTHY"
            if occupied():
                raise RuntimeError("Triad port occupied but unhealthy; owner left untouched")
            subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-NonInteractive",
                    "-ExecutionPolicy", "Bypass", "-File",
                    str(ROOT / "tools/start_product.ps1"),
                    "-Product", "triad", "-OnlyIfStopped",
                ],
                cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=True, timeout=45,
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if healthy(8101, "triad"):
                    return "RECOVERED"
                time.sleep(0.5)
            raise RuntimeError("Triad launch did not become healthy")
    except ConcurrentUpdate:
        return "DEPLOYMENT_BUSY"


def main():
    event = {"timestamp": datetime.now(UTC).isoformat()}
    code = 0
    try:
        event["status"] = ensure()
    except Exception as exc:  # noqa: BLE001 - preserve supervisor failure without secrets
        event.update(status="NEEDS_ATTENTION", error_class=type(exc).__name__)
        code = 1
    (ROOT / "logs").mkdir(exist_ok=True)
    with (ROOT / "logs/triad-supervisor.log").open("a", encoding="utf-8") as output:
        output.write(json.dumps(event) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
