"""Dependency environments (Mission 7 spec §2 items 1–2, §3.1): extras, locks and the launcher."""

import re
import time
import tomllib

import pytest
from trading_core.settings import ROOT

pytestmark = pytest.mark.core
LOCKS = {
    "core": "requirements.lock",
    "triad": "requirements-triad.lock",
    "aegis": "requirements-aegis.lock",
}


def pins(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return dict(line.split("==", 1) for line in text.splitlines() if "==" in line)


def pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_extras_declare_each_products_libraries():
    project = pyproject()["project"]
    extras = project["optional-dependencies"]
    assert extras["triad"] == []
    assert extras["aegis"] == ["numba>=0.61,<0.69"]
    assert not any("numba" in d for d in project["dependencies"])


def test_markers_are_registered():
    options = pyproject()["tool"]["pytest"]["ini_options"]
    names = {m.split(":")[0] for m in options["markers"]}
    assert {"core", "triad", "aegis"} <= names


def test_locks_pin_the_shared_set_and_only_aegis_pins_numba():
    core, triad, aegis = (pins(LOCKS[k]) for k in ("core", "triad", "aegis"))
    assert "numba" not in core and "llvmlite" not in core
    assert triad == core
    assert aegis["numba"] == "0.68.0" and aegis["llvmlite"] == "0.50.0"
    assert {k: v for k, v in aegis.items() if k not in ("numba", "llvmlite")} == core
    for name in LOCKS.values():
        lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
        assert lines == sorted(lines, key=str.upper), name  # lock.ps1: OrdinalIgnoreCase


def test_bootstrap_builds_three_environments_from_the_locks():
    script = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")
    for product, lock in LOCKS.items():
        assert lock in script, (product, lock)
    assert ".venv-triad" in script and ".venv-aegis" in script and "pyvenv.cfg" in script
    assert "verify.ps1" in script
    assert re.search(r"requirements\.lock", script)


def test_launcher_names_the_product_interpreter():
    script = (ROOT / "tools" / "start_product.ps1").read_text(encoding="utf-8")
    assert ".venv-$Product/Scripts/python.exe" in script
    assert "run tools/bootstrap.ps1 -Product $Product" in script
    assert "EnvironmentRoot" in script


def test_launcher_refuses_without_the_product_environment(tmp_path):
    """Review Focus 4: with no .venv-aegis under the root, nothing is stopped or launched."""
    import subprocess

    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "tools" / "start_product.ps1"),
        "-Product",
        "aegis",
        "-EnvironmentRoot",
        str(tmp_path),
    ]
    pid = ROOT / "logs" / "aegis.pid"
    started = time.time()
    # Output to files, never pipes: a worker the launcher started would inherit a pipe and keep
    # the run waiting (the first, red run of this test did exactly that on the old launcher).
    out, err = tmp_path / "out.txt", tmp_path / "err.txt"
    with out.open("w") as stdout, err.open("w") as stderr:
        code = subprocess.run(command, stdout=stdout, stderr=stderr, check=False, timeout=60)
    text = out.read_text(errors="replace") + err.read_text(errors="replace")
    assert code.returncode != 0
    assert "run tools/bootstrap.ps1 -Product aegis" in text, text
    assert not pid.exists() or pid.stat().st_mtime < started  # nothing was launched


def test_launcher_rejects_an_unknown_parameter(tmp_path):
    """A misspelled parameter must stop the launcher, not be ignored while it launches."""
    import subprocess

    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "tools" / "start_product.ps1"),
        "-Product",
        "aegis",
        "-NoSuchParameter",
        "x",
        "-EnvironmentRoot",
        str(tmp_path),
    ]
    out = tmp_path / "out.txt"
    with out.open("w") as stdout:
        code = subprocess.run(
            command, stdout=stdout, stderr=subprocess.STDOUT, check=False, timeout=60
        )
    assert code.returncode != 0
    assert "NoSuchParameter" in out.read_text(errors="replace")


def verify_script():
    return (ROOT / "tools" / "verify.ps1").read_text(encoding="utf-8")


def test_verify_checks_each_lock_and_clears_inherited_pytest_options():
    """Review: drift between an environment and its lock is what this mission exists to stop, and
    an inherited PYTEST_ADDOPTS must not narrow a scope that verify.ps1 then calls green."""
    script = verify_script()
    assert "lock.ps1" in script and "-Check" in script
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        assert f"Remove-Item Env:{name}" in script, name
    assert "run, the full scope" in script


def test_verify_lints_every_python_file_this_mission_touched():
    script = verify_script()
    for path in (
        "tests/conftest.py",
        "tests/test_pytest_scope.py",
        "tests/test_environments.py",
        "tests/test_architecture.py",
        "tests/test_day8_workflow_qa.py",
        "tools/run_daily_product_cycle.py",
        "tools/accept_environments.py",
    ):
        assert f"'{path}'" in script, path


def acceptance():
    import importlib.util

    path = ROOT / "tools" / "accept_environments.py"
    spec = importlib.util.spec_from_file_location("accept_environments", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_needs_the_databases_before_it_stops_a_worker(monkeypatch):
    """Review finding 3: /health/live answers with only the API process up; the supervisor item
    must not stop a worker unless Postgres (the supervisor's lease) and Neo4j are up."""
    module = acceptance()
    status = {"postgres": {"status": "down"}, "neo4j": {"status": "up"}}
    answers = {
        "http://127.0.0.1:8000/health/live": {"status": "ok", "scope": "api_process_only"},
        "http://127.0.0.1:8000/api/status": status,
    }
    monkeypatch.setattr(module, "get", lambda url, timeout=5: answers[url])
    calls = []
    monkeypatch.setattr(module, "powershell", lambda command, timeout=120: calls.append(command))
    assert module.services_up() is False
    with pytest.raises(AssertionError, match="postgres"):
        module.Acceptance("t").supervisor()
    assert not any("Stop-Process" in str(c) for c in calls)
    status["postgres"]["status"] = "up"
    assert module.services_up() is True


RED_LOG = (
    "== scope core on .venv ==",
    "scope core: 5 run, the full scope; 6 owned by other scopes deselected (triad 3, aegis 3)",
    "5 passed in 1.00s",
    "== scope triad on .venv-triad ==",
    "scope triad: 3 run, the full scope; 8 owned by other scopes deselected (core 5, aegis 3)",
    "3 passed in 1.00s",
    "== scope aegis on .venv-aegis ==",
    "FAILED tests/test_zz_injected_failure.py::test_fails - AssertionError",
    "scope aegis: 3 run, the full scope; 8 owned by other scopes deselected (core 5, triad 3)",
    "1 failed, 2 passed in 1.00s",
)


def test_a_red_run_counts_only_after_two_green_scopes():
    """Review finding 4: Review Focus 5 asks for one red scope after the other two passed."""
    module = acceptance()
    assert "pytest.mark.aegis" in module.INJECTED
    log = "\n".join(RED_LOG)
    assert module.red_run_is_honest(log, 1)
    assert not module.red_run_is_honest(log, 0)
    assert not module.red_run_is_honest(
        log + "\ncore: x; triad: y; aegis: z; all three scopes green", 1
    )
    assert not module.red_run_is_honest(log.replace("5 passed in", "1 failed, 4 passed in", 1), 1)
    assert not module.red_run_is_honest(log.split("== scope aegis")[0], 1)


def test_on_a_branch_only_the_main_branch_audit_may_stop_verify():
    """tools/audit_foundation.py refuses any branch but main by design; on a branch, item 5 may
    accept that one failure, and only after the three scopes ran in full and passed."""
    module = acceptance()
    scopes = "\n".join(
        f"scope {s}: 3 run, the full scope; 6 owned by other scopes deselected (x)"
        for s in ("core", "triad", "aegis")
    )
    audit = (
        "AssertionError: Wrong Git branch\nFoundation and secret audit failed (1)\n"
        "FullyQualifiedErrorId : Foundation and secret audit failed (1)"
    )
    assert module.only_the_branch_audit_failed(scopes + "\n" + audit, "core/x")
    assert not module.only_the_branch_audit_failed(scopes + "\n" + audit, "main")
    assert not module.only_the_branch_audit_failed(audit, "core/x")  # the scopes never ran
    other = audit.replace("Wrong Git branch", "Secret found in docs/x.md")
    assert not module.only_the_branch_audit_failed(scopes + "\n" + other, "core/x")
