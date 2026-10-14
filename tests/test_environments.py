"""Dependency environments (Mission 7 spec §2 items 1–2, §3.1): extras, locks and the launcher."""

import re
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
