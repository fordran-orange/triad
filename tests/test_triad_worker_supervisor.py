import importlib.util
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(name):
    path = Path(__file__).resolve().parents[1] / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Store:
    @contextmanager
    def lease(self, key):
        assert key == "triad-product-development"
        yield


def test_healthy_worker_is_untouched(monkeypatch):
    m = load("ensure_triad_worker")
    monkeypatch.setattr(m, "healthy", lambda *args: True)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    assert m.ensure() == "HEALTHY"


def test_occupied_unhealthy_port_never_stopped(monkeypatch):
    m = load("ensure_triad_worker")
    monkeypatch.setattr(m, "healthy", lambda port, *args: port == 8000)
    monkeypatch.setattr(m, "occupied", lambda: True)
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    with pytest.raises(RuntimeError, match="left untouched"):
        m.ensure(Store())


def test_absent_worker_launched_hidden_and_verified(monkeypatch):
    m = load("ensure_triad_worker")
    statuses = iter((False, True, False, False, True))
    monkeypatch.setattr(m, "healthy", lambda *args: next(statuses))
    monkeypatch.setattr(m, "occupied", lambda: False)
    monkeypatch.setattr(m.time, "sleep", lambda *_: None)
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *args, **kw: calls.append((args, kw)))
    assert m.ensure(Store()) == "RECOVERED"
    assert len(calls) == 1
    args, options = calls[0]
    assert args[0][-3:] == ["-Product", "triad", "-OnlyIfStopped"]
    assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert options["check"] and options["timeout"] == 45


def test_concurrent_deployment_is_skipped(monkeypatch):
    m = load("ensure_triad_worker")
    monkeypatch.setattr(m, "healthy", lambda port, *args: port == 8000)

    class Busy:
        @contextmanager
        def lease(self, _):
            raise m.ConcurrentUpdate("busy")
            yield

    assert m.ensure(Busy()) == "DEPLOYMENT_BUSY"


def test_recheck_avoids_duplicate_launch(monkeypatch):
    m = load("ensure_triad_worker")
    statuses = iter((False, True, True))
    monkeypatch.setattr(m, "healthy", lambda *args: next(statuses))
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: pytest.fail("Unexpected launch"))
    assert m.ensure(Store()) == "HEALTHY"


def test_core_failure_defers_product(monkeypatch):
    m = load("ensure_triad_worker")
    monkeypatch.setattr(m, "healthy", lambda *args: False)
    with pytest.raises(RuntimeError, match="Core unavailable"):
        m.ensure()


def test_supervisor_runs_product_check_and_propagates_failure(tmp_path, monkeypatch):
    m = load("run_core_supervisor")
    monkeypatch.setattr(m, "__file__", str(tmp_path / "tools/run_core_supervisor.py"))
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1)

    monkeypatch.setattr(m.subprocess, "run", run)
    assert m.main() == 1
    assert calls[1][0][-1] == str(tmp_path / "tools/ensure_triad_worker.py")
    assert calls[1][1]["creationflags"] == subprocess.CREATE_NO_WINDOW
