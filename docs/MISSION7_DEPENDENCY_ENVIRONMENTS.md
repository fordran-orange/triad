# Mission 7 — Dependency environments: one Core, one interpreter per product (2026-10-13/14)

Branch `core/dependency-environments`, cut from `main` at `9fb3d2f` (the plan commit; the spec at
`d0a19a7`). Spec: `docs/superpowers/specs/2026-10-13-dependency-environments-design.md`. Plan:
`docs/superpowers/plans/2026-10-13-dependency-environments.md` (5 tasks, 11 plan rulings).
Executed natively. The session model changed from Fable 5.1 to Opus 5.5 on 2026-10-14; every
task, test and commit of this branch was made on Opus 5.5, and at the operator's word ("opus is
all that thats available") the whole-branch review and the independent QA ran on Opus 5.5 too.

Core-governed: it touches `tools/`, `pyproject.toml`, the test harness and `AGENTS.md`. Nothing
under `app/trading_core/`, `app/platform_host/`, `app/products/triad/` or `app/products/aegis/`
changed (acceptance item 9). Exchange stays CLOSED; Triad suspended; the `DailySchedule` record
`c99fa831` stays disabled.

## Operator direction (2026-10-13)

The operator corrected a drift: Core is the shared substrate and remains one codebase and one
runtime.

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

Isolation is in code, contracts and dependencies, never duplicate Core installations. Not to be
created: a separate Aegis Core, duplicate Core databases, duplicate provider environments, a
parallel runtime, a second orchestration stack, or infrastructure for cleanliness; an
environment-level change needs a measured blocker surfaced first. After reading the brief the
operator approved three dependency environments and `tools\verify.ps1` — "Core remains one
shared codebase/runtime architecture — this is dependency isolation, not separate Core
implementations" — with two requirements: every collected test has explicit ownership, and the
wrong or default `pytest` cannot produce a misleading partial green. Testing follows blast
radius (now in `AGENTS.md`).

The blocker this answers, measured in Mission 6: numba 0.68 and llvmlite lived unlocked in the
single `.venv` that is also Core's and Triad's runtime, and `requirements.lock` did not pin them,
so a fresh bootstrap would not have reproduced the Aegis worker.

## What was built

| Commit | Delivered |
|---|---|
| `995da67` | `pyproject.toml` extras `triad = []` beside `aegis = ["numba>=0.61,<0.69"]` and the owner markers `core`, `triad`, `aegis`; `tools/lock.ps1` (freeze or `-Check` one environment); `tools/bootstrap.ps1` builds `.venv`, `.venv-triad`, `.venv-aegis` from their locks with the interpreter `.venv` was made from; `requirements.lock` regenerated (now also pins playwright, greenlet, pyee), `requirements-triad.lock` (= core), `requirements-aegis.lock` (+ numba 0.68.0, llvmlite 0.50.0) |
| `0441d78` | one owner marker in every test module (170), decided by each module's own imports; `tests/conftest.py`, the `TRIAD_PYTEST_SCOPE` guard; `tests/test_pytest_scope.py`; the boundary test in `tests/test_architecture.py`; `tools/verify.ps1` running the three scopes; `tools/run_daily_product_cycle.py` gives Triad's trusted post-merge pytest its scope |
| `d055b8c` | `tools/start_product.ps1` launches each worker on `.venv-<product>`, refuses before touching a listener when it is missing, and rejects unknown parameters (`[CmdletBinding()]`); both workers relaunched; numba and llvmlite removed from `.venv` |
| `d872a6a` | `AGENTS.md` (environment principle, blast-radius testing rule); `docs/CORE_CHAT_VISION.md` (the dated correction); the Mission 6 record and spec annotated |
| `da26c91` | `tools/accept_environments.py`, the acceptance |
| `14f6e74` | the fix pass (below) |
| `fe25d3c` | the Mission 6 walk's item 60 checks Mission 6's own pyproject range |
| this commit | this record and the evidence |

### How it behaves

- `pytest` with no `TRIAD_PYTEST_SCOPE` stops with exit code 4 before collecting, in every
  environment, and says how to run: `tools\verify.ps1`, or
  `$env:TRIAD_PYTEST_SCOPE = 'aegis'; .venv-aegis\Scripts\python.exe -m pytest ...`.
- A scope on another environment's interpreter stops the same way, naming the one it needs.
- A matching scope runs only the modules it owns and ends with
  `scope aegis: 298 run, the full scope; 1608 owned by other scopes deselected (...)`; anything
  narrower — paths, `-k`, `-m`, `--deselect`, `--ignore`, `--last-failed`, an inherited
  `PYTEST_ADDOPTS` — prints `N run of M owned here, PARTIAL (narrowed by ...)` instead.
- A module with no owner marker, or two, fails collection in every scope.
- `tools\verify.ps1` checks each environment against its lock, lints the touched files, takes the
  inventory, runs the three scopes on their interpreters, accepts a scope only on its full-scope
  line with the inventory's count, and prints `core: …; triad: …; aegis: …; all three scopes
  green` only when everything passed.

### Ownership

| Owner | Modules | Tests (inventory at the final commit) |
|---|---|---|
| core | 70 | 550 |
| triad | 72 + 9 under `tests/products/triad` | 1,058 |
| aegis | 19 | 298 |
| total | 170 | 1,906 (1,871 before the mission + 35 new) |

Ownership is each module's own imports (AST, nested and `importlib` imports included): Aegis by
name, Triad when the module imports `products.triad` or the `triad` package, Core otherwise.
Named: `test_architecture.py` (the shared-boundary test) is Core's; `test_engineering.py` and
`test_application_plan_validator.py` are Triad's, as the spec says; `test_readiness.py` is
Triad's because Triad's trusted post-merge gate runs it. The brief's "missing 27" were 31 tests in
four Core modules that name the product without needing its libraries: `test_day7_a2_qa.py` (5),
`test_governance.py` (4), `test_ownership_integration.py` (5), `test_product_worker_supervisor.py`
(17).

## Acceptance evidence

Final run `20261014T233145Z` on the fix-pass tree (`fe25d3c`), with Docker, Postgres, Neo4j and Core up: **11/11 PASS** in 849 s. Evidence: `docs/evidence/environments-acceptance-20261014T233145Z.json` and the Mission 6 walk it ran, `docs/evidence/aegis-acceptance-20261014T234319Z.json` (60/60). Earlier runs: `20261014T120100Z` 7/11 with Docker down (the four failures were the Docker-dependent items); `20261014T231555Z` 10/11, failing only the Mission 6 walk's item 60, whose pyproject check read HEAD instead of Mission 6's own range (fixed in `fe25d3c`).

| Item | Check | Result | Evidence |
|---|---|---|---|
| 1 | three environments built from their locks, pip check clean | PASS | requirements.lock matches .venv (41 pins); requirements-triad.lock matches .venv-triad (41 pins); requirements-aegis.lock matches .venv-aegis (43 pins); pip check clean in all three |
| 2 | numba only in .venv-aegis | PASS | numba importable: {'core': 'False', 'triad': 'False', 'aegis': 'True'}; .venv-aegis has numba 0.68.0 |
| 3 | a bare or mismatched pytest refuses before running anything | PASS | bare pytest on .venv -> exit 4; bare pytest on .venv-triad -> exit 4; bare pytest on .venv-aegis -> exit 4; scope aegis on .venv -> exit 4 'it needs .venv-aegis' |
| 4 | every collected test owned; each scope selects exactly its own | PASS | inventory: core 550, triad 1058, aegis 298, total 1906; collected 1906; each scope runs exactly what it owns, in full |
| 5 | tools\verify.ps1 green across the three scopes | PASS | the three scopes ran in full and passed, the database health check passed; the foundation audit then refused branch core/dependency-environments (it guards main only), so the closing 'all three scopes green' line comes from the run on main after the merge; log environments-acceptance-20261014T233145Z-verify.log |
| 6 | both workers relaunched on their own interpreters | PASS | triad: listener 26892 -> 27260, parent C:\Triad\.venv-triad\Scripts\python.exe, site-packages C:\Triad\.venv-triad, llvmlite False; aegis: listener 21900 -> 22880, parent C:\Triad\.venv-aegis\Scripts\python.exe, site-packages C:\Triad\.venv-aegis, llvmlite True |
| 7 | the supervisor's recovery path relaunches each on its interpreter | PASS | triad: stopped 27260 (parent C:\Triad\.venv-triad\Scripts\python.exe), supervisor RECOVERED, new listener 33736 on C:\Triad\.venv-triad\Scripts\python.exe; aegis: stopped 22880 (parent C:\Triad\.venv-aegis\Scripts\python.exe), supervisor RECOVERED, new listener 26160 on C:\Triad\.venv-aegis\Scripts\python.exe |
| 8 | one red scope cannot end green (Review Focus 5) | PASS | core and triad passed in full, the injected aegis test failed -> exit 1, no 'all three scopes green' line, module removed; log environments-acceptance-20261014T233145Z-verify-red.log |
| 9 | governance and the frozen trees | PASS | no change under app/trading_core, app/platform_host, app/products/triad, app/products/aegis since 9fb3d2f; aegis human_directed / CLOSED, kernel True; DailySchedule c99fa831 enabled=False |
| 10 | the Mission 6 browser acceptance on .venv-aegis | PASS | 60/60 PASS, 0 FAIL, page errors 0 -> C:\Triad\logs\aegis-acceptance-20261014T234319Z.json |
| 11 | Triad's trusted verification runs whole under its scope | PASS | Triad's trusted post-merge command under the Triad scope: 17 run of the 17 its two modules hold, none owned elsewhere, passed |

## Measurements

| Measure | Value |
|---|---|
| Build one environment from the pip cache (pip 25.0.1) | ≈ 230 s |
| Disk | `.venv` 433 MB, `.venv-triad` 427 MB, `.venv-aegis` 574 MB |
| `tools\verify.ps1` scopes (fix-pass tree) | core 378 passed, 171 skipped (79 s); triad 634 passed, 424 skipped, 209 subtests (73 s); aegis 297 passed, 1 skipped (112 s) |
| Repo-wide ruff (reported, not a gate) | 46 findings, all predating the mission |

## Verification

| Check | Result |
|---|---|
| `tools\verify.ps1` on the branch | locks match all three environments; lint gate clean; inventory core 550, triad 1,058, aegis 298, total 1,906; every scope in full and green; database health passed; the foundation audit refuses a branch other than `main` (acceptance item 5) |
| `tools\verify.ps1` on `main` after the merge | pending: run on `main` after the merge, before any push (the audit guards `main` only) |
| Ruff (Aegis scope and the mission's files) | clean; repo-wide 46 findings reported, all predating the mission |
| Acceptance | 11/11 (run `20261014T233145Z`) |

## Whole-branch review (Opus 5.5, `9fb3d2f..da26c91`) and fix pass

Verdict **with fixes**: no Critical, five Important, sixteen Minor. Fixed in one pass, each test
first (commit `14f6e74`):

1. The guard counted before pytest's own `-k`, `-m` and `--deselect`, and `verify.ps1` compared
   that count, so an inherited `PYTEST_ADDOPTS` could still end green → the final count is taken
   in `pytest_collection_finish`, a narrowed run says PARTIAL, `verify.ps1` clears the inherited
   options and accepts only a full-scope line with the inventory's count.
2. (Ruling, not code) the regenerated `requirements.lock` renamed Triad's reviewed product-test
   image — see Triad resumption below.
3. The acceptance read `/health/live`, which answers with only the API process up, and would
   have stopped the Triad worker with Postgres down → it reads `/api/status` first and relaunches
   a worker in a `finally` if recovery fails.
4. The red run's injected module was Core's, so it never proved "after the other two passed" → it
   is Aegis's, the last scope, and the run must show core and triad green first.
5. Triad's trusted gate depended on an unpinned ownership override → a test parses the gate's
   command and requires Triad ownership of every module it names; the spec's named owners are
   pinned.

Raised from Minor by effect: `verify.ps1` now runs `lock.ps1 -Check` (lock drift is what this
mission exists to stop); the refusal's example runs in PowerShell; the lint gate covers every
Python file the mission touched. `test_engineering.py` returned to Triad as the spec names it.

## Independent QA (Opus 5.5)

Runs at the commit that adds this record; its result is added here.

### Deferred minors

- `--noconftest` and `--confcutdir` bypass the guard (explicit flags; known limit).
- `TRIAD_PYTEST_INTERPRETER_SCOPE` is honoured inside the real repository.
- Import-based ownership hides some tests from the blast-radius rule: `test_process_power.py` is
  Triad's but tests Core's helper and the Aegis lifespan; `test_day7_a2_qa.py` imports the Aegis
  server but is Core's. Run them with an Aegis change that touches the lifespan or the server.
- `-EnvironmentRoot` is a test hook in the production launcher.
- The Review Focus 4 test does not assert that nothing was stopped.
- `pytest --help` and `pytest --markers` exit 4 without a scope.
- `.github/workflows/milestone1-stabilization.yml` (dormant) still runs a bare `pytest`.
- `tools/lock.ps1` ignores `pip freeze` lines without `==` (direct-URL installs).
- `tools/audit_foundation.py`'s "nothing under `.venv/` is tracked" does not name `.venv-triad/`
  or `.venv-aegis/` (both are git-ignored).

## Rulings

Plan rulings P1–P11 are in the plan. Rulings made during execution and review (ledger), in order:

- - T1→T3: Task 1 freezes requirements-triad.lock from .venv-triad and expects it equal to requirements.lock; Task 3 regenerates requirements.lock after removing numba and adding nothing — so after Task 3 the core lock gains playwright/greenlet/pyee (P1) while the triad lock was frozen from an environment installed from the *old* core lock (no playwright). Conflict: Task 1's test `triad == core` would fail after Task 3. Ruling below.
- the playwright/greenlet/pyee drift is resolved in Task 1, not Task 3 — `.venv-triad` and `.venv-aegis` are built from the *current* `.venv` freeze minus numba/llvmlite (which includes playwright, greenlet, pyee, so the browser acceptance and verify.ps1 can run from any environment), requirements.lock is regenerated in Task 1 from that same set, and Task 3's regeneration then only confirms numba is gone (no diff expected) — so the three locks agree from the first commit and Task 1's `triad == core` test holds through Task 3 — cost if wrong: requirements.lock changes one task earlier than the plan said (3 added lines).
- the brief's test code exceeded the 100-column limit and asserted `sorted(lines)` (case-sensitive) against a lock.ps1 that sorts OrdinalIgnoreCase; the test was reformatted and sorts with key=str.upper, which is the same ordinal order over uppercased ASCII — cost if wrong: none (lock.ps1 -Check is the authority and agreed).
- .gitignore gains `.venv-triad/` and `.venv-aegis/` (it ignored only `.venv/`); the plan's file list omitted it — cost if wrong: none.
- the brief's Step 6 installed numba with a range (`numba>=0.61,<0.69`); it was installed pinned (`numba==0.68.0 llvmlite==0.50.0`) so the frozen lock reproduces today's worker exactly — cost if wrong: none.
- ownership is decided from each module's own imports through the AST (nested imports and importlib calls included), not a text search — the text rule put test_architecture.py under Triad (its rules table names products.triad) while the spec assigns it to Core; overrides: test_architecture.py → core, test_readiness.py → triad — cost if wrong: a module's owner is wrong and it runs in another environment, which all three can host except for numba.
- test_engineering.py is owned by Core, not Triad as the spec's example said — it imports only Core (trading_core.engineering); the spec's own rule ("imports products.triad → triad") decides and its premise for this file was false — cost if wrong: none (Core's environment has every module's code).
- no transitive ownership through imported test modules — test_day3_integration (Triad) is imported by dozens of Core modules and by test_aegis_lineage_migration; each module is owned by its own imports — cost if wrong: none.
- Triad's trusted post-merge verification (app/products/triad/daily_verification.py, called only by tools/run_daily_product_cycle.py, which the Triad worker launches with its own interpreter) runs `python -m pytest tests/test_readiness.py tests/test_day8_daily_ui_qa.py` without a scope; under the guard that exits 4 and the cycle would block, and the two modules had different owners — test_readiness.py is owned by Triad (Triad's post-merge gate runs it; it depends on triad.lab through test_lab) and the cycle runner sets TRIAD_PYTEST_SCOPE=triad before running the cycle (test_daily_cycle_runner_scopes_its_trusted_verification_to_triad RED "None == 'triad'" → GREEN); the exact verification command under .venv-triad runs 17 tests with 0 deselected and passes; no file under app/ changed — cost if wrong: an operator running the cycle runner by hand with .venv's python gets a usage error (a closed failure, never a partial green).
- existing module-level pytestmark assignments (58: 57 `integration`, 1 `skipif`) became lists with the owner appended; the repository ownership test reads the owner marks from the AST so both forms count — cost if wrong: none.
- the guard's messages and verify.ps1's closing line use ASCII separators ("core: …; triad: …; aegis: …; all three scopes green") instead of the plan's "·" — Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI and pytester decodes child output by locale, so a non-ASCII separator would print as mojibake — cost if wrong: none.
- the unset-scope message is two lines ("TRIAD_PYTEST_SCOPE is not set: no tests were run." then the way to run) so it reads as a refusal first; the scope summary line ends "this is one scope of three, tools\verify.ps1 runs them all" — cost if wrong: none.
- verify.ps1 additionally checks that each scope selected exactly the count the inventory gives its owner (a collection failure or a missing marker cannot shrink a scope silently) and fails otherwise — cost if wrong: none.
- start_product.ps1 gains [CmdletBinding()] and a mandatory -Product, so an unknown or misspelled parameter stops the launcher instead of being ignored while it launches (test_launcher_rejects_an_unknown_parameter) — cost if wrong: a caller passing an extra positional argument now fails; no caller in the repository does.
- the launcher tests write the child's output to files, never pipes (a launched worker would inherit a pipe and hold the run open — the same reason product_deployment.restart uses DEVNULL) — cost if wrong: none.
- on Windows a venv's Scripts\python.exe is a launcher stub that starts the base interpreter, so the listener's ExecutablePath is C:\Users\fordr\AppData\Local\Programs\Python\Python312\python.exe for both workers; the environment is proven instead by the listener's parent (the stub, also the PID in logs/<p>.pid) and by the site-packages root of the extension modules the listener has loaded — cost if wrong: none; the spec's literal check would have failed on a correct launch.
- the acceptance gained item 11 (Triad's trusted post-merge command runs whole under the Triad scope: 17 selected, 0 deselected) to pin the Task 2 finding, and items that need Core (7 supervisor, 9 governance status, 10 browser walk) check Core's health first and fail with the reason instead of acting; the supervisor item never stops a worker it could not bring back — cost if wrong: none.
- item 6 proves each worker's environment from the listener's parent stub and the site-packages root of its loaded extension modules (Task 3 ruling), not the listener's ExecutablePath — cost if wrong: none.
- the mission record and the final evidence copy wait for an 11/11 rerun once Docker Desktop runs again; this commit carries only the acceptance script — cost if wrong: the record lands one commit later than the plan says.
- tests/test_engineering.py returns to Triad, as spec §2 item 4 names it; the reviewer showed the spec's reason holds (it drives Triad's product workspace through Core: owner="triad", paths under app/products/triad), so the Task 2 ruling that its premise was false is withdrawn — cost if wrong: none (every environment has the code); inventory now core 549, triad 1,058, aegis 298, total 1,905.
- regenerating requirements.lock changed the digest that names Triad's reviewed product-test image (triad-product-tests:f14afa20b399b07a → d0ac3ff6cd7d50b3; app/trading_core/product_changes.py test_image_digest over the Dockerfile, requirements.lock, product-tests.lock and the SDK files), so the next Triad candidate check fails closed until tools/build_product_test_image.py rebuilds it; the image is not rebuilt now — Triad is suspended, the rebuild adds playwright, greenlet and pyee to that image's dependency set, which is the operator's to review when Triad resumes, and every later lock regeneration has the same effect — recorded as the first Triad-resumption item in the Mission 7 record — cost if wrong: the first Triad candidate check after resumption fails until one build command runs.
- acceptance item 5 on a branch accepts exactly one failure, tools/audit_foundation.py's "Wrong Git branch" (it guards the main checkout by design), and only after the three scopes ran in full and passed (only_the_branch_audit_failed, test_on_a_branch_only_the_main_branch_audit_may_stop_verify RED→GREEN); verify.ps1's closing green line is taken from the run on main after the merge, before any push — cost if wrong: the secret, lock-pin and venv checks of the audit run one step later, on main.
- Ruling (declined: unittest-based paths) — product_changes.check_candidate's offline discovery and unittest.main() in tests/products/triad are outside pytest; the operator's requirement is about pytest runs — cost if wrong: none now.
- Ruling (declined: ~600 integration skips without TRIAD_INTEGRATION=1) — pre-existing, and every scope line and the closing line show the skip counts — cost if wrong: none.
- Ruling (declined: PYTEST_DISABLE_PLUGIN_AUTOLOAD and -p no:<conftest>) — deliberate bypasses by someone who names them, like --noconftest — cost if wrong: none.
- Ruling (declined: the interpreter detected by directory name only) — the editable install binds every environment to C:\Triad\app, so a directory named .venv elsewhere is a different tree — cost if wrong: none.
- Ruling (declined: no transitive ownership) — documented in Task 2, fails closed — cost if wrong: none.
- Ruling (declined: test_failure_isolation.py launches the Aegis worker on .venv) — it tests Core's isolation and asserts nothing about the kernel — cost if wrong: none.
- Ruling (declined: PowerShell 5.1 native stderr under Stop) — the reviewer probed it and it does not happen here — cost if wrong: none.
- Ruling (declined: the Docker-dependent failures) — they pass with Docker up (verification above) — cost if wrong: none.
- Ruling (declined: agents in a Triad cycle inheriting TRIAD_PYTEST_SCOPE=triad) — speculative while Triad is suspended; a Triad-resumption note — cost if wrong: a Triad agent's own pytest runs in the Triad scope.
- Ruling (declined: disk and bootstrap time) — an accepted risk in the spec (≈230 s and one environment's disk per product) — cost if wrong: none.
- the Mission 6 walk's item 60 asserted pyproject.toml changed by one line over 5189e12..HEAD; Mission 7's triad extra and owner markers fall in that range, so item 60 now diffs Mission 6's own range 5189e12..90e94d0 (Mission 6's merged head), and the frozen-tree check keeps reading HEAD — the assertion was about Mission 6, not about every later mission — cost if wrong: a later pyproject change outside Mission 6 is checked by its own mission's governance item, not by item 60.

## Triad resumption items

1. **Rebuild the reviewed product-test image.** Its tag is a digest over the Dockerfile,
   `requirements.lock`, `infrastructure/product-tests.lock` and the SDK files
   (`app/trading_core/product_changes.py`); the regenerated lock moved it from
   `triad-product-tests:f14afa20b399b07a` to `…:d0ac3ff6cd7d50b3`, so the first candidate check
   fails closed until `tools/build_product_test_image.py` builds it. The rebuild adds playwright,
   greenlet and pyee to that image; review it then. Every later lock regeneration does the same.
2. Triad's cycle writes unittest modules under `tests/products/triad`; each needs
   `pytestmark = pytest.mark.triad`, or every run refuses until it has one (fails closed).
3. The daily cycle runner sets `TRIAD_PYTEST_SCOPE=triad`; agents a cycle launches inherit it.

## Known limits

- The guard's interpreter check reads the environment directory's name (`.venv`, `.venv-triad`,
  `.venv-aegis`); the editable install binds every environment to this checkout's `app/`.
- On Windows a venv's `Scripts\python.exe` is a launcher stub; the listening worker is the base
  interpreter configured for that venv. The environment is proven by the parent stub (also the
  PID in `logs/<product>.pid`) and the worker's loaded `site-packages`.
- `tools/audit_foundation.py` refuses any branch but `main`, so `verify.ps1`'s closing line is
  only reachable on `main`.
- The Core supervisor waits 30 s for Core after starting it; a cold start on this laptop took
  33 s on 2026-10-14, so the first pass after a reboot logs a false failure and the next pass
  (5 minutes later) confirms Core (observed 17:37 and 17:42).
