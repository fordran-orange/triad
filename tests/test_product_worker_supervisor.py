"""Product worker supervision for Triad (8101) and Aegis (8102): health first, launch only when
the port is provably free, never stop a listener, one lease and one log per product."""

import importlib.util
import json
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

PRODUCTS = [("triad", 8101), ("aegis", 8102)]


def load(name):
    path = Path(__file__).resolve().parents[1] / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Store:
    def __init__(self, expected):
        self.expected = expected
        self.leases = []

    @contextmanager
    def lease(self, key):
        assert key == self.expected
        self.leases.append(key)
        yield


def test_ports_are_fixed_per_product():
    assert load("ensure_product_worker").PORTS == {"triad": 8101, "aegis": 8102}


@pytest.mark.parametrize(("product", "port"), PRODUCTS)
def test_healthy_worker_is_untouched(monkeypatch, product, port):
    m = load("ensure_product_worker")
    seen = []
    monkeypatch.setattr(m, "healthy", lambda p, name=None: seen.append((p, name)) or True)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    assert m.ensure(product) == "HEALTHY"
    assert seen == [(port, product)]


@pytest.mark.parametrize(("product", "port"), PRODUCTS)
def test_occupied_unhealthy_port_never_stopped(monkeypatch, product, port):
    m = load("ensure_product_worker")
    monkeypatch.setattr(m, "healthy", lambda p, *args: p == 8000)
    probed = []
    monkeypatch.setattr(m, "occupied", lambda p, timeout=10: probed.append(p) or True)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    with pytest.raises(RuntimeError, match="left untouched"):
        m.ensure(product, Store(f"{product}-product-development"))
    assert probed == [port]


@pytest.mark.parametrize(("product", "port"), PRODUCTS)
def test_absent_worker_launched_hidden_and_verified(monkeypatch, product, port):
    m = load("ensure_product_worker")
    statuses = iter((False, True, False, False, True))
    monkeypatch.setattr(m, "healthy", lambda *args: next(statuses))
    monkeypatch.setattr(m, "occupied", lambda p, timeout=10: False)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kw: calls.append((args, kw)))
    store = Store(f"{product}-product-development")
    assert m.ensure(product, store) == "RECOVERED"
    assert store.leases == [f"{product}-product-development"]
    assert len(calls) == 1
    args, options = calls[0]
    assert args[0][-3:] == ["-Product", product, "-OnlyIfStopped"]
    assert args[0][-4].endswith("start_product.ps1") and args[0][-5] == "-File"
    assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert options["check"] and options["timeout"] == 45


def test_concurrent_deployment_is_skipped(monkeypatch):
    m = load("ensure_product_worker")
    monkeypatch.setattr(m, "healthy", lambda port, *args: port == 8000)

    class Busy:
        @contextmanager
        def lease(self, _):
            raise m.ConcurrentUpdate("busy")
            yield

    assert m.ensure("aegis", Busy()) == "DEPLOYMENT_BUSY"


def test_recheck_avoids_duplicate_launch(monkeypatch):
    m = load("ensure_product_worker")
    statuses = iter((False, True, True))
    monkeypatch.setattr(m, "healthy", lambda *args: next(statuses))
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    assert m.ensure("triad", Store("triad-product-development")) == "HEALTHY"


@pytest.mark.parametrize(("product", "port"), PRODUCTS)
def test_core_failure_defers_product(monkeypatch, product, port):
    m = load("ensure_product_worker")
    monkeypatch.setattr(m, "healthy", lambda *args: False)
    with pytest.raises(RuntimeError, match="Core unavailable"):
        m.ensure(product)


def test_unknown_product_is_rejected():
    m = load("ensure_product_worker")
    with pytest.raises(KeyError):
        m.ensure("p2p")
    with pytest.raises(SystemExit):
        m.main(["--product", "p2p"])


def test_aegis_uses_port_8102_and_its_own_lease_and_log(monkeypatch, tmp_path):
    m = load("ensure_product_worker")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "healthy", lambda p, name=None: p == 8000)
    probed = []
    monkeypatch.setattr(m, "occupied", lambda p, timeout=10: probed.append(p) or True)
    store = Store("aegis-product-development")
    monkeypatch.setattr(m, "Store", lambda: store)
    assert m.main(["--product", "aegis"]) == 1
    assert probed == [8102]
    assert store.leases == ["aegis-product-development"]
    event = json.loads((tmp_path / "logs/aegis-supervisor.log").read_text().splitlines()[-1])
    assert event["status"] == "NEEDS_ATTENTION" and event["error_class"] == "RuntimeError"
    assert "timestamp" in event and "error" not in event  # never the message, never secrets
    assert not (tmp_path / "logs/triad-supervisor.log").exists()


def test_supervisor_runs_both_products_and_reports_first_failure(tmp_path, monkeypatch):
    m = load("run_core_supervisor")
    monkeypatch.setattr(m, "__file__", str(tmp_path / "tools/run_core_supervisor.py"))
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode={1: 0, 2: 3, 3: 0}[len(calls)])

    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.main() == 3
    script = str(tmp_path / "tools/ensure_product_worker.py")
    assert calls[1][0][1:] == [script, "--product", "triad"]
    assert calls[2][0][1:] == [script, "--product", "aegis"]
    for _, options in calls[1:]:
        assert options["timeout"] == 100
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_supervisor_stops_when_core_recovery_fails(tmp_path, monkeypatch):
    m = load("run_core_supervisor")
    monkeypatch.setattr(m, "__file__", str(tmp_path / "tools/run_core_supervisor.py"))
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.main() == 2
    assert len(calls) == 1 and calls[0][-1].endswith("ensure_core.ps1")


def test_closed_loopback_port_is_not_occupied():
    # Real sockets on purpose: the supervisor failed for days because a closed
    # loopback port on this host answers only after ~2 s, so probes must outlast it.
    m = load("ensure_product_worker")
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert m.occupied(port) is False


def test_listening_loopback_port_is_occupied():
    m = load("ensure_product_worker")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        assert m.occupied(listener.getsockname()[1]) is True
