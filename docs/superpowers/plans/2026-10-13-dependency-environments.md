# Dependency Environments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Core codebase and runtime, three dependency environments (`.venv` core, `.venv-triad`, `.venv-aegis`) built from lock files, each worker launched on its own interpreter, every test module owned, and no `pytest` invocation that can show a misleading partial green.

**Architecture:** `pyproject.toml` stays one package; extras `triad = []` and `aegis` declare product libraries; `tools/lock.ps1` freezes an environment into its lock; `tools/bootstrap.ps1` builds the three environments from the locks with the base interpreter named in `.venv/pyvenv.cfg`. `tests/conftest.py` owns the scope guard (`TRIAD_PYTEST_SCOPE`, interpreter match, owner markers, deselection, header and summary); `tools/verify.ps1` runs the three scopes with their interpreters; `tools/start_product.ps1` maps product → interpreter, so the supervisor's recovery path and Core's trusted restart need no change.

**Tech Stack:** Python 3.12.10 venvs, pip (`freeze --exclude-editable`), pytest 9 (`pytester` plugin), PowerShell 5/7 scripts, Windows process table (`Win32_Process`).

**Spec:** `docs/superpowers/specs/2026-10-13-dependency-environments-design.md`

## Global Constraints

- No file under `app/trading_core/`, `app/platform_host/`, `app/products/triad/` or `app/products/aegis/` changes (spec §2 item 10). Edits live under `tools/`, `tests/`, `docs/`, the lock files, `pyproject.toml`, `AGENTS.md`.
- One Core runtime: no second gateway, database, provider configuration, supervisor or orchestration; the supervisor task keeps `.venv/Scripts/pythonw.exe` (spec §3.2).
- Exchange stays CLOSED; Triad stays suspended (its worker only relaunches from its interpreter); the `DailySchedule` record `c99fa831` stays disabled; never print secrets.
- Lock files are the truth: `requirements.lock`, `requirements-triad.lock`, `requirements-aegis.lock` are `pip freeze --exclude-editable` output, sorted, regenerated only by `tools/lock.ps1`.
- The base interpreter for every environment is the `home` of `.venv/pyvenv.cfg` (`C:\Users\fordr\AppData\Local\Programs\Python\Python312\python.exe`, 3.12.10); `python` on PATH is 3.11.9 and is never used.
- Lint for this mission's files: `ruff check` and `ruff format --check` over `tests/conftest.py tests/test_pytest_scope.py tests/test_environments.py tools/accept_environments.py` plus the Aegis scope script (`scratchpad/lint_aegis.sh`); never a bare `ruff format`.
- Branch `core/dependency-environments` cut from `main` at the plan commit; `MISSION7_BASE` in the acceptance script is that commit.

## Plan rulings against the spec

| # | Ruling | Why |
|---|---|---|
| P1 | `requirements.lock` is regenerated from `.venv` after numba and llvmlite are removed, so it gains `playwright==1.63.0`, `greenlet==3.5.6`, `pyee==13.0.1` (installed ad hoc since Mission 3) and stays free of product libraries. `requirements-triad.lock` is frozen from `.venv-triad` (equal to the core set); `requirements-aegis.lock` from `.venv-aegis` (core set plus `numba==0.68.0`, `llvmlite==0.50.0`). | Spec §3.1: the locks are the truth; the browser acceptance needs playwright from `.venv`. |
| P2 | `bootstrap.ps1` reads the base interpreter from `.venv/pyvenv.cfg` (`home`) when `.venv` exists and from `-Python` otherwise, and refuses anything outside 3.12–3.13. | `python` on PATH is 3.11.9 on this host. |
| P3 | `verify.ps1`'s blocking lint runs over the clean scope (`app/products/aegis tests/test_aegis_*.py tests/products/aegis tools/aegis_contracts.py`) plus this mission's files; the repo-wide `ruff check app tests tools` count is printed as information, not a gate. | 46 pre-existing findings in Core and Triad tests predate this mission (Mission 5 ruling); fixing them is a separate hygiene task; the operator's rule is lint for touched code. |
| P4 | The interpreter's scope is the name of `sys.prefix`'s directory (`.venv` → core, `.venv-triad` → triad, `.venv-aegis` → aegis); `TRIAD_PYTEST_INTERPRETER_SCOPE` overrides it and exists only for the conftest's own tests. | pytester runs in-process on the outer interpreter. |
| P5 | A module with no owner marker, or more than one, makes the session fail with `pytest.UsageError` listing the files (exit 4) in every scope, inventory included. | Spec §2 item 4: never silently collected. |
| P6 | `TRIAD_PYTEST_SCOPE=inventory` is accepted only with `--collect-only`; it counts per owner and never deselects. | Spec §2 item 5. |
| P7 | `pytestmark = pytest.mark.<owner>` is inserted after the module's last top-level import (an `import pytest` is added when absent); `tests/products/aegis/browser_workstation.py` and the three `tests/products/triad/browser_*.py` harnesses are not test modules and carry no marker. | Spec §3.3. |
| P8 | The acceptance (`tools/accept_environments.py`, run from `.venv`) reads each listener's `ExecutablePath` through PowerShell `Get-CimInstance Win32_Process`, restarts both workers through `start_product.ps1`, then stops each and recovers it through `ensure_product_worker.py --product <p>` (the supervisor's path; needs Core healthy and the Store lease, both present on this host). | Spec §2 item 3 and §4. |
| P9 | `start_product.ps1` takes `-EnvironmentRoot` (default: the repo root) so a test can point it at an empty directory and assert the "run tools/bootstrap.ps1 -Product <p>" refusal without touching the real environments. | Review Focus 4 needs a real PowerShell run. |
| P10 | `product_deployment.restart()` and `ensure_product_worker.py` are not edited; both already call the launcher; their existing tests stand. | Spec §3.2, Global Constraints. |
| P11 | The Aegis worker is restarted onto `.venv-aegis` before numba leaves `.venv`; the Triad worker (running today, PID 16572) is restarted onto `.venv-triad`. | Nothing serves from an interpreter about to lose its library. |

## Review Focus

1. **Plain `pytest tests/test_aegis_surface.py` in `.venv`**: exits 4 with the message naming `tools\verify.ps1` and `TRIAD_PYTEST_SCOPE`; no test runs, in particular none on the reference-engine fallback. Test in Task 2 (`test_unset_scope_is_a_usage_error`).
2. **`TRIAD_PYTEST_SCOPE=aegis` under `.venv`**: usage error naming the interpreter found (`.venv`, core) and the one expected (`.venv-aegis`). Test in Task 2 (`test_scope_must_match_the_interpreter`).
3. **A new test module without a marker**: the session fails listing the file, in any scope and in inventory. Test in Task 2 (`test_unowned_module_fails_collection`).
4. **`.venv-aegis` missing on a host**: `start_product.ps1 -Product aegis` exits non-zero with "run tools/bootstrap.ps1 -Product aegis" and launches nothing; the supervisor then logs `NEEDS_ATTENTION` instead of starting the worker on the wrong interpreter. Test in Task 3 (`test_launcher_refuses_without_the_product_environment`, real PowerShell against an empty `-EnvironmentRoot`).
5. **One red scope in `verify.ps1`**: non-zero exit and no "all three scopes green" sentence, even when the other two scopes passed. Acceptance item 8 in Task 5 (an injected failing module, removed afterwards).

---

### Task 1: Environments and locks

**Files:**
- Modify: `pyproject.toml` (extras, pytest markers)
- Create: `tools/lock.ps1`
- Modify: `tools/bootstrap.ps1`
- Create: `requirements-triad.lock`, `requirements-aegis.lock`; regenerate `requirements.lock` in Task 3 (P1)
- Test: `tests/test_environments.py` (owner core)

**Interfaces:**
- Produces: `.venv-triad/`, `.venv-aegis/` on this host; `tools/lock.ps1 -Product core|triad|aegis`; `tools/bootstrap.ps1 [-Product <p>]`; pyproject extras `triad`, `aegis`; registered markers `core`, `triad`, `aegis`.
- Consumed by: Task 2 (markers, interpreters), Task 3 (launcher), Task 5 (acceptance rebuilds from the locks).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_environments.py
"""Dependency environments (Mission 7 spec §2 items 1–2, §3.1): extras, locks and the launcher."""

import re
import tomllib
from pathlib import Path

import pytest

from trading_core.settings import ROOT

pytestmark = pytest.mark.core
LOCKS = {"core": "requirements.lock", "triad": "requirements-triad.lock", "aegis": "requirements-aegis.lock"}


def pins(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return dict(line.split("==", 1) for line in text.splitlines() if "==" in line)


def test_extras_declare_each_products_libraries():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    assert extras["triad"] == []
    assert extras["aegis"] == ["numba>=0.61,<0.69"]
    assert not any("numba" in d for d in project["dependencies"])


def test_markers_are_registered():
    options = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
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
        assert lines == sorted(lines), name


def test_bootstrap_builds_three_environments_from_the_locks():
    script = (ROOT / "tools" / "bootstrap.ps1").read_text(encoding="utf-8")
    for product, lock in LOCKS.items():
        assert lock in script, (product, lock)
    assert ".venv-triad" in script and ".venv-aegis" in script and "pyvenv.cfg" in script
    assert "tools/verify.ps1" in script
    assert re.search(r"pip install -r requirements\.lock", script)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_environments.py` (until Task 2 lands, run without the variable: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_environments.py`)
Expected: FAIL — `KeyError: 'triad'`, markers missing, `FileNotFoundError: requirements-triad.lock`, bootstrap assertions.

- [ ] **Step 3: `pyproject.toml`**

Add `triad = []` under `[project.optional-dependencies]` (above `aegis`), and extend `markers` to
`["integration: requires the local PostgreSQL and Neo4j services", "core: owned by Core's environment (.venv)", "triad: owned by Triad's environment (.venv-triad)", "aegis: owned by Aegis's environment (.venv-aegis)"]`.

- [ ] **Step 4: `tools/lock.ps1`**

`param([ValidateSet('core','triad','aegis')][string]$Product = 'core')`; resolves the environment (`.venv` for core, `.venv-$Product` otherwise) and the lock name; runs `python -m pip freeze --exclude-editable`, sorts the lines (ordinal, case-insensitive), writes them LF-terminated with `[IO.File]::WriteAllText`; prints the lock name and the line count. `-Check` compares instead of writing and exits 1 on a difference.

- [ ] **Step 5: `tools/bootstrap.ps1`**

Add `param([string]$Python = 'python', [ValidateSet('all','core','triad','aegis')][string]$Product = 'all')`. Add `function Resolve-BaseInterpreter`: when `.venv/pyvenv.cfg` exists, its `home` value joined with `python.exe`; otherwise `$Python`; assert 3.12 ≤ version < 3.14. Add `function New-Environment([string]$Name, [string]$Lock, [string]$Extras)`: `& $Base -m venv $Name` when missing; `& "$Name/Scripts/python.exe" -m pip install -r $Lock`; `& ... -m pip install --no-deps --no-build-isolation -e ".[$Extras]"`; `Assert-Exit` after each. Build `.venv` (`requirements.lock`, `dev`), `.venv-triad` (`requirements-triad.lock`, `dev,triad`), `.venv-aegis` (`requirements-aegis.lock`, `dev,aegis`) according to `-Product`. Replace the `pytest` step with `& (Join-Path $PSScriptRoot 'verify.ps1')` guarded by `Assert-Exit 'Verification'`. Everything else unchanged.

- [ ] **Step 6: Build the two new environments and freeze their locks (this host)**

```powershell
# from the repo root, PowerShell
$Base = 'C:\Users\fordr\AppData\Local\Programs\Python\Python312\python.exe'
& $Base -m venv .venv-triad; & .venv-triad\Scripts\python.exe -m pip install -r requirements.lock; & .venv-triad\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e '.[dev,triad]'
& $Base -m venv .venv-aegis; & .venv-aegis\Scripts\python.exe -m pip install -r requirements.lock; & .venv-aegis\Scripts\python.exe -m pip install 'numba>=0.61,<0.69'; & .venv-aegis\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e '.[dev,aegis]'
tools\lock.ps1 -Product triad; tools\lock.ps1 -Product aegis
```

Expected: `requirements-triad.lock` identical to `requirements.lock`; `requirements-aegis.lock` = the same plus `llvmlite==0.50.0` and `numba==0.68.0`; `.venv-aegis\Scripts\python.exe -c "import numba; print(numba.__version__)"` → `0.68.0`; `.venv-triad\Scripts\python.exe -c "import numba"` → `ModuleNotFoundError`.

- [ ] **Step 7: Run the tests to watch them pass**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_environments.py`
Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml tools/lock.ps1 tools/bootstrap.ps1 requirements-triad.lock requirements-aegis.lock tests/test_environments.py
git commit -m "Environments: per-product locks and a bootstrap that builds .venv, .venv-triad and .venv-aegis"
```

### Task 2: Ownership markers, the scope guard and verify.ps1

**Files:**
- Create: `tests/conftest.py`, `tests/test_pytest_scope.py` (owner core)
- Modify: every test module under `tests/` (170 with the two new ones): one `pytestmark` line
- Modify: `tests/test_architecture.py` (+ `test_product_libraries_absent_from_core_and_triad`)
- Modify: `tools/verify.ps1`

**Interfaces:**
- Consumes: Task 1's markers and the three interpreters.
- Produces: `TRIAD_PYTEST_SCOPE` (`core|triad|aegis|inventory`), `TRIAD_PYTEST_INTERPRETER_SCOPE` (test hook), `tests/conftest.py` with `OWNERS`, `interpreter_scope()`, `owner_of(item)`; `tools/verify.ps1` exit code and closing sentence `core N passed · triad N passed · aegis N passed · all three scopes green`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pytest_scope.py
"""The scope guard (Mission 7 spec §2 items 4–5, §3.3): a default or wrong pytest cannot show a
partial green; every module is owned."""

from pathlib import Path

import pytest

from trading_core.settings import ROOT

pytestmark = pytest.mark.core
pytest_plugins = ["pytester"]
CONFTEST = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
INI = "[pytest]\nmarkers =\n    core: c\n    triad: t\n    aegis: a\n"


def tree(pytester):
    pytester.makeini(INI)
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(
        test_core_owned="import pytest\npytestmark = pytest.mark.core\ndef test_c(): pass\n",
        test_aegis_owned="import pytest\npytestmark = pytest.mark.aegis\ndef test_a(): pass\ndef test_b(): pass\n",
        test_triad_owned="import pytest\npytestmark = pytest.mark.triad\ndef test_t(): pass\n",
    )


def test_unset_scope_is_a_usage_error(pytester, monkeypatch):
    monkeypatch.delenv("TRIAD_PYTEST_SCOPE", raising=False)
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*TRIAD_PYTEST_SCOPE*", "*tools\\verify.ps1*"])
    assert "passed" not in result.stdout.str()


def test_scope_must_match_the_interpreter(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "aegis")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*scope aegis*interpreter*core*.venv-aegis*"])


def test_matching_scope_runs_only_its_owner_and_says_so(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "aegis")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "aegis")
    tree(pytester)
    result = pytester.runpytest_subprocess("-q")
    result.assert_outcomes(passed=2, deselected=2)
    result.stdout.fnmatch_lines(["*scope aegis: 2 selected*deselected*core 1*triad 1*"])


def test_unowned_module_fails_collection(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "core")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    pytester.makepyfile(test_orphan="def test_o(): pass\n")
    result = pytester.runpytest_subprocess()
    assert result.ret == 4
    result.stderr.fnmatch_lines(["*test_orphan.py*no owner marker*"])
    assert "passed" not in result.stdout.str()


def test_inventory_counts_every_owner_and_only_collects(pytester, monkeypatch):
    monkeypatch.setenv("TRIAD_PYTEST_SCOPE", "inventory")
    monkeypatch.setenv("TRIAD_PYTEST_INTERPRETER_SCOPE", "core")
    tree(pytester)
    result = pytester.runpytest_subprocess("--collect-only", "-q")
    result.stdout.fnmatch_lines(["*inventory: core 1 · triad 1 · aegis 2 · total 4*"])
    assert pytester.runpytest_subprocess().ret == 4  # inventory without --collect-only


def test_every_module_in_this_repository_declares_one_owner():
    modules = [p for p in (ROOT / "tests").rglob("test_*.py")]
    missing = [str(p.relative_to(ROOT)) for p in modules if "pytestmark = pytest.mark." not in p.read_text(encoding="utf-8")]
    assert modules and not missing, missing
```

And in `tests/test_architecture.py`:

```python
def test_product_libraries_absent_from_core_and_triad():
    import importlib.util
    import os

    scope = os.environ.get("TRIAD_PYTEST_SCOPE")
    present = importlib.util.find_spec("numba") is not None
    assert present == (scope == "aegis"), (scope, present)
```

- [ ] **Step 2: Run them to watch them fail**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_pytest_scope.py tests/test_architecture.py -k "scope or owner or inventory or absent"`
Expected: FAIL — `FileNotFoundError: tests/conftest.py`, the repository ownership test lists 168 modules, the architecture test fails while numba is still in `.venv` under no scope.

- [ ] **Step 3: `tests/conftest.py`**

```python
"""Scope guard: every test module is owned by core, triad or aegis and runs only in that
environment (Mission 7 spec §3.3). Set TRIAD_PYTEST_SCOPE, or run tools\\verify.ps1."""
OWNERS = ("core", "triad", "aegis")
PREFIXES = {".venv": "core", ".venv-triad": "triad", ".venv-aegis": "aegis"}
HOW = "set TRIAD_PYTEST_SCOPE=core|triad|aegis and use that environment's interpreter, or run tools\\verify.ps1 for everything"
```

`interpreter_scope()` → `os.environ.get("TRIAD_PYTEST_INTERPRETER_SCOPE") or PREFIXES.get(Path(sys.prefix).name, "unknown")`.
`pytest_configure(config)`: scope unset → `raise pytest.UsageError(f"TRIAD_PYTEST_SCOPE is not set; {HOW}")`; `inventory` and not `config.option.collectonly` → UsageError; scope not in OWNERS + inventory → UsageError; scope in OWNERS and `interpreter_scope() != scope` → `UsageError(f"scope {scope} needs the {expected} interpreter but this is {found} ({sys.prefix}); {HOW}")`; store `config._triad_scope = scope`.
`owner_of(item)`: `{m.name for m in item.iter_markers() if m.name in OWNERS}`; exactly one → it; else record the module path.
`pytest_collection_modifyitems(config, items)`: build `counts` per owner, `unowned` set of paths with the reason ("no owner marker" / "several owner markers"); unowned → `raise pytest.UsageError("\n".join(f"{path}: {reason}" for ...))`; inventory → keep all; else `kept = [i for i in items if owner_of(i) == scope]`, `removed = the rest`, `items[:] = kept`, `config.hook.pytest_deselected(items=removed)`; store counts and `len(kept)` on config.
`pytest_report_header(config)`: `f"TRIAD_PYTEST_SCOPE={scope} on interpreter {Path(sys.prefix).name}"`.
`pytest_terminal_summary(terminalreporter, exitstatus, config)`: inventory → `inventory: core N · triad N · aegis N · total N`; owner → `scope {scope}: {kept} selected; {deselected} deselected (core n, triad n, aegis n)`.

- [ ] **Step 4: Insert the owner markers (one-off script, not committed)**

A scratchpad script walks `tests/**/test_*.py`, decides the owner (P7 and spec §2 item 4: path `tests/test_aegis_*` or `tests/products/aegis/` → aegis; `tests/products/triad/` or module text matching `products\.triad|\bfrom triad\b|\bimport triad\b` → triad; else core), inserts `pytestmark = pytest.mark.<owner>` after the last top-level `import`/`from` statement (adding `import pytest` when the module has none), and prints the counts per owner: expected 19 aegis, 90 triad (81 top-level modules that import Triad plus the 9 under `tests/products/triad`), and the rest core (the 56 Core modules of the brief, the four reconciled ones, `test_architecture.py`, `test_environments.py` and `test_pytest_scope.py`); the three totals must sum to 170 and the ledger records the exact numbers. Then `.venv/Scripts/python.exe -m ruff format` on the touched test files is NOT run (bare format is forbidden); the inserted line is already formatted.

- [ ] **Step 5: `tools/verify.ps1`**

Keep the preamble. Replace the `pip check`, `ruff` and `pytest` steps with: for each `('core','.venv','requirements.lock')`, `('triad','.venv-triad','requirements-triad.lock')`, `('aegis','.venv-aegis','requirements-aegis.lock')`: `& "$Env/Scripts/python.exe" -m pip check` → `Assert-Exit`; `$env:TRIAD_PYTEST_SCOPE = $Scope; & "$Env/Scripts/python.exe" -m pytest -q -p no:cacheprovider 2>&1 | Tee-Object -Variable out`; `Assert-Exit "Tests ($Scope)"`; keep the last line as `$Summary[$Scope]`. Then `Remove-Item Env:TRIAD_PYTEST_SCOPE`. Blocking lint: `& .venv/Scripts/python.exe -m ruff check app/products/aegis tests/products/aegis tools/aegis_contracts.py tests/conftest.py tests/test_pytest_scope.py tests/test_environments.py tools/accept_environments.py (Get-ChildItem tests/test_aegis_*.py)` and `ruff format --check` on the same; informational: `& .venv/Scripts/python.exe -m ruff check app tests tools --statistics 2>&1 | Select-Object -Last 1` printed as `repo-wide ruff (not a gate): …`. The inventory line: `$env:TRIAD_PYTEST_SCOPE='inventory'; & .venv/Scripts/python.exe -m pytest --collect-only -q -p no:cacheprovider | Select-String '^inventory:'`. The remaining steps (compose, health, audit, git, containers) unchanged. Final line: `"core $($Summary.core) · triad $($Summary.triad) · aegis $($Summary.aegis) · all three scopes green"`.

- [ ] **Step 6: Run the tests to watch them pass**

Run: `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_pytest_scope.py tests/test_environments.py tests/test_architecture.py`
Expected: all pass except `test_product_libraries_absent_from_core_and_triad`, which fails until Task 3 removes numba from `.venv` (record it in the ledger; it is the RED half of Task 3).
Run: `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_surface.py tests/test_aegis_kernel.py`
Expected: pass, header `TRIAD_PYTEST_SCOPE=aegis on interpreter .venv-aegis`, summary `scope aegis: N selected; 0 deselected`.
Run: `.venv/Scripts/python.exe -m pytest -q tests/test_aegis_surface.py`
Expected: exit 4, `TRIAD_PYTEST_SCOPE is not set; …tools\verify.ps1`.

- [ ] **Step 7: Commit**

```bash
git add tests pyproject.toml tools/verify.ps1
git commit -m "Tests: every module owned by core, triad or aegis; TRIAD_PYTEST_SCOPE guard; verify.ps1 runs the three scopes"
```

### Task 3: The launcher map, the restarts, numba out of Core

**Files:**
- Modify: `tools/start_product.ps1`
- Modify: `requirements.lock` (regenerated, P1)
- Test: `tests/test_environments.py` (+ `test_launcher_refuses_without_the_product_environment`, + `test_launcher_names_the_product_interpreter`), `tests/test_architecture.py` (Task 2's test turns green)

**Interfaces:**
- Consumes: `.venv-triad`, `.venv-aegis` (Task 1).
- Produces: `start_product.ps1 -Product <p> [-OnlyIfStopped] [-EnvironmentRoot <dir>]` launching `<root>/.venv-<p>/Scripts/python.exe -m uvicorn products.<p>.server:app …`; refusal text `run tools/bootstrap.ps1 -Product <p>`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_environments.py`)

```python
def test_launcher_names_the_product_interpreter():
    script = (ROOT / "tools" / "start_product.ps1").read_text(encoding="utf-8")
    assert ".venv-$Product/Scripts/python.exe" in script
    assert "run tools/bootstrap.ps1 -Product $Product" in script
    assert "EnvironmentRoot" in script


def test_launcher_refuses_without_the_product_environment(tmp_path):
    import subprocess

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "tools" / "start_product.ps1"), "-Product", "aegis", "-EnvironmentRoot", str(tmp_path)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    assert result.returncode != 0
    assert "run tools/bootstrap.ps1 -Product aegis" in result.stderr + result.stdout
```

- [ ] **Step 2: Run them to watch them fail**

Run: `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_environments.py -k launcher`
Expected: FAIL — the script has no `.venv-$Product` and no `-EnvironmentRoot`; the refusal test launches nothing but exits 0 or fails on the missing parameter.

- [ ] **Step 3: `tools/start_product.ps1`**

`param([ValidateSet('triad','aegis')][string]$Product, [switch]$OnlyIfStopped, [string]$EnvironmentRoot = '')`; `$TradingRoot` as today; `$EnvRoot = if ($EnvironmentRoot) { $EnvironmentRoot } else { $TradingRoot }`; `$TradingPython = Join-Path $EnvRoot ".venv-$Product/Scripts/python.exe"`; `if (!(Test-Path -LiteralPath $TradingPython)) { throw "Missing $TradingPython: run tools/bootstrap.ps1 -Product $Product" }` — before the listener check, so nothing is stopped when the interpreter is absent. The rest unchanged (the `ExpectedWorker` regex still matches `uvicorn products.$Product.server:app`).

- [ ] **Step 4: Restart both workers onto their interpreters (this host), then remove numba from `.venv`**

```powershell
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\Triad\tools\start_product.ps1 -Product aegis'; CurrentDirectory='C:\Triad'}
# poll http://127.0.0.1:8102/aegis/api/status until kernel_available true; then the same for triad (port 8101, /health/live)
Get-CimInstance Win32_Process -Filter "ProcessId = $((Get-NetTCPConnection -LocalPort 8102 -State Listen).OwningProcess)" | Select-Object ExecutablePath
.venv\Scripts\python.exe -m pip uninstall -y numba llvmlite
tools\lock.ps1 -Product core
```

Expected: `ExecutablePath` ends `.venv-aegis\Scripts\python.exe` (8102) and `.venv-triad\Scripts\python.exe` (8101); `.venv\Scripts\python.exe -c "import numba"` → `ModuleNotFoundError`; `requirements.lock` now lists `greenlet`, `playwright`, `pyee` and no `numba`/`llvmlite` (P1); `git diff --stat requirements.lock` shows 3 added lines.

- [ ] **Step 5: Run the tests to watch them pass**

Run: `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_environments.py tests/test_architecture.py`
Expected: all pass, including `test_product_libraries_absent_from_core_and_triad`.
Run: `tools\verify.ps1` (PowerShell)
Expected: three scope lines, the inventory line, `core N passed · triad N passed · aegis N passed · all three scopes green`, exit 0 (the compose/health/audit steps need the local services, present on this host).

- [ ] **Step 6: Commit**

```bash
git add tools/start_product.ps1 requirements.lock tests/test_environments.py
git commit -m "Launcher: each worker starts on its product interpreter; numba leaves Core's environment; requirements.lock regenerated"
```

### Task 4: Governance records

**Files:**
- Modify: `AGENTS.md`, `docs/CORE_CHAT_VISION.md`, `docs/MISSION6_EXPERIMENTS.md`, `docs/superpowers/specs/2026-10-12-aegis-experiments-design.md` (section 14, one bullet)
- Memory (outside the repo): `aegis-worker-detached-restart.md` names `.venv-aegis`

- [ ] **Step 1: `AGENTS.md`** — after the "Core owns…" paragraph, add two paragraphs: the environment principle (one Core codebase and runtime; dependency isolation by per-product environments `.venv`, `.venv-triad`, `.venv-aegis` built from lock files; never duplicate Core installations, databases, providers or orchestration; an environment-level change needs a measured blocker surfaced first) and the testing rule verbatim in substance (ordinary Aegis edits: Aegis tests, architecture/isolation tests, lint/type/build for touched code, related shared-contract tests; milestones: `tools\verify.ps1`, frontend tests, browser acceptance, lint/build; shared Core changes: the relevant Core tests immediately).
- [ ] **Step 2: `docs/CORE_CHAT_VISION.md`** — append `### 2026-10-13 — Core stays the shared substrate; dependency isolation, not separate Core environments` under Operator corrections: the tree, the "not to be created" list, the approval of the three dependency environments and `verify.ps1`, the two requirements, the testing rule, the record pointer.
- [ ] **Step 3: Mission 6 annotations** — the record's open item 1 gains "Realised on 2026-10-13 by Mission 7 as dependency isolation: three environments over one Core codebase and runtime, not separate Core environments (`docs/MISSION7_DEPENDENCY_ENVIRONMENTS.md`)"; the Mission 6 spec's section 14 gains the same bullet for §4.4.
- [ ] **Step 4: Verify the governance tests still pass** — Run: `TRIAD_PYTEST_SCOPE=core .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_architecture.py tests/test_governance.py tests/test_acceptance_change_suspension.py` Expected: pass (these read `AGENTS.md`/docs only where they already did).
- [ ] **Step 5: Commit**

```bash
git add AGENTS.md docs/CORE_CHAT_VISION.md docs/MISSION6_EXPERIMENTS.md docs/superpowers/specs/2026-10-12-aegis-experiments-design.md
git commit -m "Governance: Core stays the shared substrate; dependency isolation and the blast-radius testing rule recorded"
```

### Task 5: Acceptance and the record

**Files:**
- Create: `tools/accept_environments.py` (run from `.venv`; not a test module)
- Create: `docs/MISSION7_DEPENDENCY_ENVIRONMENTS.md`, `docs/evidence/environments-acceptance-<stamp>.json`

**Interfaces:**
- Consumes: everything above. `MISSION7_BASE` = the plan commit.

- [ ] **Step 1: Write `tools/accept_environments.py`** — items, each PASS/FAIL with detail, written to `logs/environments-acceptance-<stamp>.json` and printed:
  1. The three environments exist; each `pip check` clean; each `pip freeze --exclude-editable` sorted equals its lock (`tools/lock.ps1 -Check`).
  2. `import numba` fails in `.venv` and `.venv-triad`, succeeds in `.venv-aegis` with `0.68.0`.
  3. Default `pytest` in each environment exits 4 with the message; `TRIAD_PYTEST_SCOPE=aegis` under `.venv` exits 4 naming both interpreters.
  4. Inventory totals from `TRIAD_PYTEST_SCOPE=inventory … --collect-only` sum to the whole collection; each scope's selected count equals its inventory count.
  5. `tools\verify.ps1` exits 0 and its last line is `core N passed · triad N passed · aegis N passed · all three scopes green`.
  6. Both workers restarted through `start_product.ps1` (WMI launch, as the Mission 6 acceptance did): `ExecutablePath` of the 8101 and 8102 listeners end in `.venv-triad\Scripts\python.exe` and `.venv-aegis\Scripts\python.exe`; `/aegis/api/status` reports `kernel_available: true`.
  7. Supervisor path: stop each worker (`Stop-Process` on the listener), run `.venv\Scripts\python.exe tools\ensure_product_worker.py --product <p>`, read `logs/<p>-supervisor.log`'s last line (`RECOVERED`) and the listener's `ExecutablePath` again.
  8. Review Focus 5: write `tests/test_zz_injected_failure.py` (`pytestmark = pytest.mark.core`, `def test_fails(): assert False`), run `tools\verify.ps1`, assert a non-zero exit and no "all three scopes green" line, delete the file, confirm `git status --porcelain tests/` is empty.
  9. Governance: `git diff --name-only MISSION7_BASE HEAD -- app/trading_core app/platform_host app/products/triad app/products/aegis` empty; `GET http://127.0.0.1:8000/aegis/api/status` says `human_directed` / `CLOSED`; the schedule record `c99fa831` disabled.
  10. The Mission 6 browser acceptance (`.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py`) → 60/60 against the worker on `.venv-aegis` (its item 51 relaunches through the new launcher).
- [ ] **Step 2: Run it** — Expected: 10/10 PASS; copy the JSON to `docs/evidence/`.
- [ ] **Step 3: Write `docs/MISSION7_DEPENDENCY_ENVIRONMENTS.md`** — the operator direction (verbatim in substance: the tree, the prohibitions, the approval, the two requirements, the testing rule), what was built (commits), the ownership table (core / triad / aegis counts and the reconciled modules), the acceptance table, measurements (bootstrap minutes, disk per environment, verify.ps1 duration per scope), verification, rulings P1–P11 and the ledger's, deferred items (the 46 pre-existing ruff findings; `requirements.lock` drift history), known limits; commit "Mission 7: environments acceptance and record".

### After Task 5

Independent QA (Core-governed: mandatory) at the exact commit: rebuild `.venv-triad` and `.venv-aegis` from the locks into temporary names and diff their freezes; the import probes; the three refusals; the supervisor path; `verify.ps1`; the architecture test; the record's claims. Whole-branch review on the most capable model; one fix pass test-first; the record completed; the finishing menu (merge and push only on the operator's answer).
