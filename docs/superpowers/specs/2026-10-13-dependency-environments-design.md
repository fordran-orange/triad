# Mission 7 — Dependency environments: one Core, one interpreter per product, tests that cannot lie

Date: 2026-10-13. Governance: Core-governed (touches `tools/`, `pyproject.toml`, the test
harness and `AGENTS.md`); independent QA at the end is mandatory. Nothing under
`app/trading_core/` changes.

## 1. Operator direction (2026-10-13, binding)

Core is the shared substrate and stays one codebase and one runtime:

```
Core
├── providers
├── memory / knowledge
├── storage / provenance
├── shared runtime
└── product hosting / support
      ├── Aegis
      └── Triad — suspended
```

Product isolation is in code, contracts and **dependencies**, never in duplicate Core
installations. Not to be created: a separate Aegis Core, duplicate Core databases, duplicate
provider environments, a parallel runtime, a second orchestration stack, or separate
infrastructure for cleanliness. Any environment-level change needs a measured blocker surfaced
before implementation.

Approved after the brief: three **dependency** environments and `tools\verify.ps1`, as
dependency isolation over one shared codebase and one Core runtime, with two requirements:

1. every collected test has explicit ownership (the tests the import-based classification
   missed are reconciled, file by file);
2. running the wrong or the default `pytest` cannot produce a misleading partial green.

Testing rule (recorded in `AGENTS.md` by this mission): ordinary reversible Aegis changes run the
Aegis tests, the architecture/isolation tests, lint/type/build for touched code and directly
related shared-contract tests; a milestone (before merging a vertical slice) runs everything
(`tools\verify.ps1`, the frontend tests, the browser acceptance, lint/build); anything touching
`app/trading_core/`, the platform host, providers, memory/knowledge, governance, product
isolation, shared schemas or contracts, migrations or credentials runs the relevant Core tests
immediately and is shared-infrastructure work. Aegis implementation continues after this mission.

## 2. Intent and definition of done

The blocker this answers, measured in Mission 6: numba 0.68 (and llvmlite) live unlocked in the
single shared `.venv`, which is also Core's and Triad's runtime; `requirements.lock` does not
pin them, so a fresh `tools/bootstrap.ps1` would not reproduce the Aegis worker that runs today.

Definition of done (the acceptance walks these in order):

1. Three environments, built by `tools/bootstrap.ps1` from lock files, each an editable install
   of the same `app/` tree from the same `pyproject.toml`: `.venv` (Core: `requirements.lock`,
   extra `dev`), `.venv-triad` (`requirements-triad.lock`, extras `dev,triad`), `.venv-aegis`
   (`requirements-aegis.lock`, extras `dev,aegis`). One Core codebase, one database set, one
   gateway, one supervisor; `pip check` clean in each.
2. `python -c "import numba"` fails in `.venv` and `.venv-triad` and succeeds in `.venv-aegis`
   (numba 0.68.0, llvmlite 0.50.0, pinned in `requirements-aegis.lock`).
3. Each worker runs on its own interpreter: the process listening on 8101 executes
   `.venv-triad\Scripts\python.exe`, the one on 8102 `.venv-aegis\Scripts\python.exe` (read from
   the listener's `Win32_Process.ExecutablePath`), whether launched by `tools/start_product.ps1`,
   by the supervisor's `tools/ensure_product_worker.py --product <p>`, or by Core's trusted
   restart (`trading_core.product_deployment.restart`): all three go through the one launcher,
   which maps product → interpreter. Core on 8000 and the supervisor task keep `.venv`.
4. Every test module declares exactly one owner marker, `core`, `triad` or `aegis`, at module
   level; the three markers are registered; a module without exactly one is a collection error
   and never runs silently. Ownership: `tests/test_aegis_*.py` and `tests/products/aegis/` →
   aegis; `tests/products/triad/` and every top-level module that imports `products.triad` →
   triad (including `test_engineering.py` and `test_application_plan_validator.py`, which drive
   Triad's product workspace through Core); everything else → core, including the four modules
   the import-based classification dropped because they name the product or import its server
   module without needing its libraries (`test_day7_a2_qa.py` 5 tests, `test_governance.py` 4,
   `test_ownership_integration.py` 5, `test_product_worker_supervisor.py` 17 — 31 tests) and
   `test_architecture.py`, the shared-boundary test. The inventory prints the three totals and
   they sum to the whole collection.
5. `TRIAD_PYTEST_SCOPE` governs every run. Unset: pytest stops with a usage error (exit code 4)
   that names `tools\verify.ps1` and the variable, runs no test and prints no green. Set to a
   scope whose interpreter does not match (`.venv-aegis` running `core`): usage error. Set and
   matching: only that owner's tests run, and the header says so ("scope aegis: 298 selected;
   1,573 owned by core/triad deselected"). A path-restricted run is a partial run by explicit
   selection and the header still names the scope. `TRIAD_PYTEST_SCOPE=inventory` is accepted
   only with `--collect-only` and prints the ownership totals without deselecting.
6. `tools/verify.ps1` runs the three scopes, each with its interpreter and `pip check`, keeps ruff
   over `app tests tools` from `.venv`, prints each scope's pass count, fails on the first red,
   and ends with the three totals and the one sentence that means everything passed. Non-zero
   exit otherwise.
7. The Mission 6 browser acceptance still runs from `.venv` (playwright is a `dev` extra) against
   the Aegis worker on `.venv-aegis`, 60/60; its item 51 restart lands on `.venv-aegis`.
8. `AGENTS.md` carries the environment principle and the testing rule; `docs/CORE_CHAT_VISION.md`
   carries the dated 2026-10-13 correction; `tools/bootstrap.ps1` is the install note; the
   Mission 6 record's open item 1 and spec §4.4 are annotated as realised by dependency
   isolation, not separate Core environments.
9. Reversible: `pip install -e .[aegis]` into `.venv` restores today's state. No product route,
   datum or behaviour changes; exchange CLOSED; Triad suspended (its worker merely relaunches
   from its interpreter; nothing else of Triad runs).
10. No file under `app/trading_core/`, `app/platform_host/`, `app/products/triad/` or
    `app/products/aegis/` changes; the edits are under `tools/`, `tests/`, `docs/`, the lock files,
    `pyproject.toml` and `AGENTS.md`. The architecture test additionally asserts that the Core
    and Triad interpreters cannot import numba.

## 3. Architecture

### 3.1 Environments and locks

`pyproject.toml` keeps one package and gains `triad = []` beside `aegis = ["numba>=0.61,<0.69"]`;
the required list is untouched. Each environment is `python -m venv .venv-<p>`, then
`pip install -r requirements-<p>.lock`, then `pip install --no-deps --no-build-isolation -e
.[dev,<p>]`, as `bootstrap.ps1` does today for `.venv`. The lock files are `pip freeze
--exclude-editable` of a built environment: `requirements-triad.lock` equals `requirements.lock`
today; `requirements-aegis.lock` adds `numba==0.68.0` and `llvmlite==0.50.0`. `tools/lock.ps1
-Product <p>` regenerates a lock from its environment so the three never drift by hand.
`bootstrap.ps1` builds all three (or one with `-Product`), and the rest of its steps (compose,
migrations, tests, health) run once from `.venv`; its test step becomes `tools/verify.ps1`.

### 3.2 The launcher map

`tools/start_product.ps1` resolves `$ProductPython = <root>/.venv-$Product/Scripts/python.exe`
and stops with "run tools/bootstrap.ps1 -Product $Product" when it is missing; everything else
(port, the owner check on the listener's command line, Stop-Process, Start-Process hidden, the
pid file, the logs) is unchanged. `ensure_product_worker.py` and `product_deployment.restart()`
already call that script and are not edited. The supervisor task (`install_core_supervisor.ps1`,
`run_core_supervisor.py`) keeps `.venv/Scripts/pythonw.exe`: the supervisor is Core.

### 3.3 Ownership markers and the scope guard

`tests/conftest.py` (new) owns the rule:

- `OWNERS = ("core", "triad", "aegis")`, registered in `pyproject.toml`'s pytest markers.
- `interpreter_scope()`: the owner implied by `Path(sys.prefix).name` (`.venv` → core,
  `.venv-triad` → triad, `.venv-aegis` → aegis, anything else → unknown).
- `pytest_configure`: reads `TRIAD_PYTEST_SCOPE`; unset → `pytest.UsageError` with the two ways
  to run; `inventory` without `--collect-only` → usage error; an owner whose interpreter does not
  match → usage error naming both.
- `pytest_collection_modifyitems`: each item's owner is the module-level marker; a module with
  none or several is reported and the session errors; items of other owners are deselected;
  `inventory` counts only.
- `pytest_report_header` and `pytest_terminal_summary`: the scope, the selected count, the
  deselected count by owner, so no output of a single run reads as the whole.

Ownership is written into every test module as `pytestmark = pytest.mark.<owner>` (one line
after the imports), 168 modules today. The decisions are §2 item 4; a new module without a
marker fails collection everywhere, so ownership cannot be forgotten.

### 3.4 `tools/verify.ps1`

For each of core, triad, aegis: `.venv[-p]/Scripts/python.exe -m pip check`, then
`TRIAD_PYTEST_SCOPE=<p> … -m pytest -q -p no:cacheprovider`, keeping the last line of each.
Ruff runs once from `.venv` over `app tests tools` as today; the compose, health, audit, git and
container steps stay. The script ends with "core N passed · triad N passed · aegis N passed ·
all three scopes green" or the first failing step's name, and exits accordingly.

### 3.5 What does not change

Core's code, its one database set, the gateway and its proxying of `/triad/*` and `/aegis/*`,
the provider integration, memory and knowledge, the supervisor's interpreter and schedule, the
products' routes and data, the Aegis UI build (`npm` under `app/products/aegis/ui`, unchanged).

## 4. Verification

- Test first: `tests/test_pytest_scope.py` (owner core) drives the conftest through the
  `pytester` plugin on a small copied tree: unset scope → exit code 4 and the message; mismatched
  interpreter → usage error; matching scope → only that owner's tests run and the header line;
  a module without a marker → collection error; `inventory` totals. The interpreter name is
  taken from a function the tests override.
- `tests/test_architecture.py` gains `test_product_libraries_absent_from_core_and_triad`:
  under scope core or triad, `importlib.util.find_spec("numba") is None`; under aegis, not None.
- `tests/test_product_worker_supervisor.py` keeps passing unchanged (the launcher path is the
  same script).
- Acceptance (recorded in `docs/MISSION7_DEPENDENCY_ENVIRONMENTS.md`): bootstrap of the two new
  environments from the locks on this host; the three import probes; `tools\verify.ps1` green
  with the three totals summing to the inventory; the default `pytest` refused in each
  environment; both workers restarted through the launcher and through the supervisor's recovery
  path, their `ExecutablePath` read from the process table; Core's trusted-restart path proven by
  a unit test of `product_deployment.restart` calling the launcher (existing); the Mission 6
  browser acceptance 60/60 on the new worker interpreter; `git diff` empty under the four
  protected trees except test markers.
- Independent QA at the exact commit: the environments rebuilt from the locks, the import
  probes, the partial-green refusals, the supervisor path, the architecture test; whole-branch
  review; one fix pass test-first; record; merge and push on the operator's call.

## 5. Build order

1. `pyproject.toml` extras (`triad = []`), `tools/lock.ps1`, the two new lock files generated from
   freshly built environments, `tools/bootstrap.ps1` building all three; `.venv` untouched.
2. Ownership markers in every test module; `tests/conftest.py`; the pytester tests;
   `tools/verify.ps1`; the architecture test; markers registered. Until step 3 the Aegis scope
   runs in `.venv-aegis` and the core scope in `.venv`, which still holds numba.
3. `tools/start_product.ps1` interpreter map; both workers restarted through it and again
   through `ensure_product_worker.py`; numba and llvmlite uninstalled from `.venv`; `verify.ps1`
   green.
4. `AGENTS.md`, `docs/CORE_CHAT_VISION.md`, the Mission 6 record and spec annotations, the
   detached-restart memory.
5. Acceptance evidence, the Mission 7 record; then independent QA and the whole-branch review.

## 6. Risks

- Disk: two more environments of roughly 600 MB each; bootstrap time grows by two installs.
- A developer's reflex `pytest` now stops with an error by design; the message names the two
  ways to run.
- `pythonw.exe` for the supervisor and the venv launcher stub (the pid file holds the stub, the
  listener is its child) are unchanged behaviours; the acceptance reads the listener's process.
- The owner markers touch every test module once (one line each); the Triad test files change
  only by that line, and Triad stays suspended.
