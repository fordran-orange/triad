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
