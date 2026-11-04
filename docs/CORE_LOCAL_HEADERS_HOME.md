# The local-only middleware's home: `trading_core.http` (2026-11-04)

Branch `claude/brave-bassi-63d6d0`, cut from `main` at `7c30d15`. A Core change (`AGENTS.md`:
shared Core contracts and the product-isolation boundary): independent QA and explicit Core
governance are mandatory and are the operator's to dispatch; nothing here is merged or pushed
without his word. Exchange CLOSED; Triad suspended; live trading disabled; no secret value was
read, printed or moved by this work (no `.env` exists in this worktree).

The standing item (`docs/AEGIS_WORKER_ENVIRONMENT.md` §6.2 on `claude/infallible-villani-704e0d`):
the Aegis worker imported `trading_core.api` for one small ASGI middleware, and importing that
module loads Core's whole operator surface into the product process.

## 1. Finding

`local_headers` (api.py at `7c30d15`, lines 90–101) refuses a request whose `Host` is not
`127.0.0.1`, `localhost` or `testserver` with 403 `{"detail": "Local host required"}`, and adds
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` and
the Content-Security-Policy to every other answer. It needs `Request` and `JSONResponse` and
nothing else. But it lived in `trading_core.api`, whose module-level imports are Brain, the
Orchestrator, the runtime, status, work and every Core router, so:

| Probe (`.venv-aegis`, `PYTHONPATH` on this worktree's `app`, a fresh interpreter) | `trading_core.*` modules in `sys.modules` after `import products.aegis.server` |
| --- | --- |
| Before (`7c30d15`) | **62**, `trading_core.api` among them: brain, orchestrator, runtime, status, work, conversation, intelligence.\*, integrations.\*, providers.\*, research.\*, product_reasoning\*, security, … |
| After (this branch) | **7**: `trading_core`, `http`, `process_power`, `resources`, `settings`, `store`, `work`; `trading_core.api` absent |

No `.env` is read at import time on either side (the sibling note established that), so this is
surface and startup, not a secret exposure: the product process no longer holds the operator
surface's code, its routers or their dependencies.

## 2. The change

Nothing the middleware does changed: the function body in its new home is the body removed from
`api.py`, byte for byte (`git diff 7c30d15 -- app/trading_core/api.py app/trading_core/http.py`
shows the removed and the added lines side by side).

| File | Change |
| --- | --- |
| `app/trading_core/http.py` (new, 23 lines) | `local_headers`, the same body; the module imports `fastapi.Request` and `fastapi.responses.JSONResponse` and nothing of Core |
| `app/trading_core/api.py:16` | `from trading_core.http import local_headers` (the re-export: anything importing it from `trading_core.api` keeps working, `platform_host.legacy`'s star import included) |
| `app/trading_core/api.py:90` | `app.middleware("http")(local_headers)` where the decorated definition stood, so Core's gateway mounts the same function at the same point |
| `app/products/aegis/server.py:11` | imports `local_headers` from `trading_core.http` (was `trading_core.api`); line 50's mount unchanged |
| `app/products/triad/server.py:10–11` | the three exception handlers (`denied_operation`, `invalid_operation`, `not_found`) still from `trading_core.api`; `local_headers` from `trading_core.http`; line 85's mount unchanged |
| `tests/test_aegis_local_headers.py` (new, aegis) | four tests, §3 |
| `tests/test_architecture.py:172` (core) | `test_local_headers_home_imports_only_the_framework` |
| `tests/products/aegis/browser_workstation.py` | the Core-change baselines, §4 |

Unchanged: `app/platform_host/`, every other file under `app/trading_core/` and
`app/products/`, `tools/`, the launchers, `.env.example`. Triad keeps loading the operator
surface through its exception handlers and its lazy `dashboard` import (`server.py:109`): it runs
Core's runtime in-process by design and is suspended, so nothing else of it moves.

## 3. Proof (2026-11-04, this worktree; `.venv`, `.venv-aegis` and `.venv-triad` are the main checkout's; `PYTHONPATH` on this worktree's `app;tests`; `-p no:cacheprovider`)

- `tests/test_aegis_local_headers.py` (aegis): a fresh interpreter imports
  `products.aegis.server` and the operator surface (`trading_core.api`, brain, orchestrator,
  runtime, status, operator_api, conversation_api, product_reasoning_api and the five routers) is
  absent from `sys.modules` while `trading_core.http` is present; the worker's `local_headers`
  is `trading_core.http.local_headers` and it is the app's only middleware; no module under
  `app/products/aegis` imports `trading_core.api` (AST); on the worker's app `/health/live`
  answers 200 with the four headers, the CSP compared against the literal string, 200 for the
  three local hosts, and 403 `{"detail": "Local host required"}` for a foreign host.
- `tests/test_architecture.py::test_local_headers_home_imports_only_the_framework` (core): the
  new module's imports are all `fastapi`/`starlette` (AST); `trading_core.api.local_headers is
  trading_core.http.local_headers`; Core's app mounts exactly that one middleware.
- Aegis scope on `.venv-aegis`: `test_aegis_local_headers`, `test_aegis_api`,
  `test_aegis_lab_harness`: **71 passed** in 77 s.
- Core scope on `.venv`: `test_architecture`, `test_api`: 8 passed, 3 failed on the worktree
  for its environment only. `test_product_libraries_absent_from_core_and_triad` wants
  `.venv-triad` beside the checkout (the worktree has none). The other two want `.env`:
  `test_core_startup_with_product_imports_blocked` (the kill-control 401) and
  `test_api::test_no_governance_or_trading_endpoints` (`/api/demo` is 409 without `.env`, because
  `Settings()` fails validation inside `require_operator` and Core's `ValueError` handler answers
  409; this one is the same cause as the first and was not on the sibling note's list because it
  did not run `test_api`). With `TRADING_HOME=C:\Triad` (Core's root at the main checkout, this
  worktree's code still on `PYTHONPATH`) both pass: **3 passed**. Nothing fails on the code.
- Triad scope on `.venv-triad`: `test_process_power` (every worker lifespan, Core's and both
  products' servers imported together), `test_isolation`, `test_day7_surfaces`,
  `test_engineering`, `tests/products/triad/test_product_app.py`: **41 passed, 1 skipped** (live
  integration) in 45 s.
- Headers on all three apps through `TestClient`, each on its own interpreter: Core's gateway,
  Triad's worker and Aegis's worker each answer `/health/live` 200 with `nosniff`,
  `no-referrer`, `no-store` and the identical CSP string, and 403 `Local host required` to
  `Host: evil.example.net`.
- Lint: `tools/lint_aegis.sh check` then `fix` green (111 files, none changed); `ruff check` and
  `ruff format --check` green on `app/trading_core/http.py`, `app/trading_core/api.py` and
  `app/products/triad/server.py`; `git diff --check` clean; no control character and no CRLF in
  any touched file.
- Not run here: the walk (needs Core, both workers, Postgres and the product key; a Core change
  is QA'd independently) and `tools\verify.ps1` (main checkout only).

## 4. The walk's Core-change baselines

The governance items compare `git diff --name-only <base> HEAD -- app/trading_core
app/platform_host app/products/triad` with an expected list. This change adds two paths to every
diff from every base (`app/trading_core/http.py`, `app/products/triad/server.py`);
`app/trading_core/api.py` is already in Mission 14's list. As Mission 14 did (`a6ba93b`):

- `LOCAL_HEADERS_FILES` (lines 526–529) names the two; `EXPECTED_CORE_CHANGES` (530) and
  `CORE_CHANGE_NOTE` (531–535) include them; `LAB_EXPECTED_CORE_CHANGES` (536–537) is
  `LAB_MAIN_CORE_FILES` plus the two, for the Lab's governance item.
- Items whose assertion now expects the two files through `EXPECTED_CORE_CHANGES`: **47, 60, 69,
  76, 81, 86, 88, 90, 97, 102** (the brief's "46" is the 422-refusals item; the governance item
  after it is 47). Item 102's sentence (4934–4937) names each list and reads "nothing else under
  app/platform_host or app/products/triad", since Triad's server now appears in the diff.
- The Lab's governance item, **118** (`first + 15`, 7392–7404), asserts `LAB_EXPECTED_CORE_CHANGES`
  and names the home in its sentence.
- The item descriptions in `ITEMS` and `LAB_ITEMS` (lines 114, 128, 138, 146, 177, 200) say
  "… and the local_headers home".

## 5. Independent QA must check

1. `app/trading_core/http.py`'s function body equals the body removed from `api.py` at
   `7c30d15` line for line: the host set, the 403 body and status, the four header names and
   values, the CSP string. (`git diff 7c30d15 -- app/trading_core/api.py` for the removed lines.)
2. `trading_core.http` imports nothing of Core and reads no setting or `.env`; the AST test in
   `test_architecture.py` holds, and `grep -n "trading_core" app/trading_core/http.py` names
   only the docstring.
3. A fresh `.venv-aegis` interpreter importing `products.aegis.server` has no `trading_core.api`
   in `sys.modules` (the first test in `test_aegis_local_headers.py`; or the §1 probe by hand).
4. Core's gateway (`trading_core.api.app`) mounts exactly one middleware and it is
   `trading_core.http.local_headers`; the operator routes, the exception handlers and
   `require_operator` are untouched (`git diff 7c30d15 -- app/trading_core/api.py` is the import,
   the mount and the removed definition, nothing else).
5. The product worker on 8102, restarted through `tools/start_product.ps1 -Product aegis` by the
   operator when he chooses, answers `/health/live` with the four headers and 403 to a foreign
   `Host`; the gateway's proxied `/aegis/api/status` and `/aegis` are unchanged; the supervisor
   log shows HEALTHY afterwards. The same for Triad's worker on its port if it is restarted.
6. Triad's three exception handlers still come from `trading_core.api` and still answer 404,
   409 and 403 (`tests/products/triad/test_product_app.py` and `test_engineering` ran green).
7. The walk's expected lists equal the real diffs: `git diff --name-only 0117490 HEAD -- app/trading_core app/platform_host app/products/triad`
   sorted is `EXPECTED_CORE_CHANGES`, and the same from `1882c81` is
   `LAB_EXPECTED_CORE_CHANGES` (on this branch, or on `main` after the merge).
8. No secret value appears in the diff, this note, the tests or the commit message.

## 6. Open points for the operator

1. Drop the re-export from `trading_core.api` once nothing imports `local_headers` from there?
   Today nothing does but `platform_host.legacy`'s star import, which uses nothing of it;
   keeping it costs nothing and keeps old branches importable.
2. Triad's worker still loads the operator surface through its three exception handlers;
   `not_found`, `invalid_operation` and `denied_operation` need only `JSONResponse` and pydantic's
   `ValidationError` and could join `trading_core.http`, leaving `dashboard` as Triad's one lazy
   import of `trading_core.api`. Triad is suspended; not done here.
3. The walk's three Core-change lists now overlap (`api.py` in Mission 14's; the home's two
   beside it). After the merge, re-cutting the governance items on one base and one list would
   read cleaner; a walk-only change.
4. `test_api::test_no_governance_or_trading_endpoints` is a third worktree-only failure (no
   `.env`), beside the two the sibling note recorded; worth adding to the worktree memory.
5. The walk and `tools\verify.ps1` run on `main` after the merge, as for every Core change.
