# The Aegis worker's environment: only what Aegis needs (2026-11-03)

Branch `claude/infallible-villani-704e0d`, cut from `main` at `7c30d15`. A credentials change
(`AGENTS.md`: secrets, credentials and product-isolation boundaries): independent QA is mandatory
and is dispatched by the operator's session; nothing here is merged or pushed without his word.
Exchange CLOSED; Triad suspended; live trading disabled; no secret value was printed, moved or
copied anywhere by this work.

The standing item (the Mission 14 design note, §3): "The Aegis worker loads Core's whole `.env`
when it builds `Store(scope="aegis")` (operator token included)". This note records what was
found, the narrowing chosen, and how it is proven.

## 1. Findings

### 1.1 How the worker obtains secrets

| Path | What happens | Finding |
| --- | --- | --- |
| `app/trading_core/settings.py:15` `Settings` | `env_file=ROOT / ".env"`, `extra="ignore"`; 13 fields, two required (`postgres_password`, `neo4j_password`) | Any process that builds `Settings` materializes every mapped `.env` value, the operator token included (probe, 2026-11-03: `triad_operator_token` held in the model) |
| `app/products/aegis/server.py:92` | `Store(scope="aegis").list_work()` on `/aegis/api/status`; `Store.__init__` (`store.py:38`) builds `Settings()` when none is given | The worker builds the whole model on every status call; `Store` itself uses only `postgres_*` (`store.py:41-50`) |
| `app/products/aegis/api.py:154-156` `get_core_reasoning` | `Settings().aegis_product_key` for the Core reasoning client | The worker builds the whole model again to read its own key |
| `tools/start_product.ps1:43` | `Start-Process` of uvicorn with the launcher's inherited environment and the checkout as working directory; no variables set | The launcher passes nothing from `.env`: the worker reads the file itself, from `ROOT` (the checkout holding `trading_core`, or `TRADING_HOME`) |
| `tools/ensure_product_worker.py:52-78` | The supervisor builds its own `Store()` in Core's `.venv` for the lease, then runs the launcher | Core's process, Core's whole settings: correct and untouched |
| `tools/start_aegis_scratch.ps1:98-101` | Sets `PYTHONPATH`, `AEGIS_DATA_ROOT`, `AEGIS_POOL_WORKERS`; inherits the rest | Same: the scratch worker reads `ROOT/.env` when the checkout has one |
| `app/platform_host/api.py:11-40` | The gateway forwards `/aegis/*` to 127.0.0.1:8102 with only `authorization`, `content-type` and `origin` headers | No secret crosses the proxy; nothing to narrow |
| `app/products/aegis/core_client.py` | `AEGIS_CORE_URL` (default 127.0.0.1:8000); the key is given by the caller | Provider keys are never in the product process: the reading goes through Core's `/api/core/products/aegis/reasoning` with the product key (walk item 98 "read by Claude through Core" confirmed by the scratch run below) |

Other environment reads in the product: `AEGIS_DATA_ROOT` (`runs.py:301`), `AEGIS_POOL_WORKERS`
(`pool.py:62`), the Lab cache size (`lab/cache.py:35`), `AEGIS_CORE_URL`. None is a secret. The
product imports five Core names: `Settings`, `Store`, `local_headers`, `opt_out_of_power_throttling`
(twice). `trading_core.security`, `runtime.HttpProvider` and `providers.discovery` also read
`ROOT/.env` through `dotenv_values`, lazily, but nothing in the product calls them.

### 1.2 The variables in `.env` (names only; the live file has 15, `.env.example` adds 12 provider lines that the live file does not carry)

| Variable | Aegis process | Verdict |
| --- | --- | --- |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Needed: `Store(scope="aegis")` lists the product's work items | **Aegis needs** |
| `AEGIS_PRODUCT_KEY` | Needed: presented to Core's reasoning route | **Aegis needs** (Core needs it too, to verify) |
| `NEO4J_PASSWORD` | Received through `Settings`; required by the schema, never used by the product (no Neo4j reference under `app/products/aegis`) | **Merely received**; today's schema still demands a value |
| `NEO4J_URI`, `NEO4J_USER` | Received through `Settings`, unused | Merely received |
| `OLLAMA_URL`, `OLLAMA_MODEL`, `LOCAL_MODEL_ENABLED` | Received through `Settings`, unused | Merely received |
| `TRIAD_OPERATOR_TOKEN` | Received through `Settings`, unused: the worker never calls an operator route | **Core's alone**; its presence in the product process is the finding |
| `NEO4J_HTTP_PORT`, `NEO4J_BOLT_PORT` | Not a `Settings` field (`extra="ignore"`); docker compose reads them | Core's alone |
| `OPENAI_*`, `ANTHROPIC_*`, `XAI_*` (example file only) | Not in the live file; Core's providers run on subscription CLIs; `HttpProvider` would read them lazily in Core | Core's alone |

### 1.3 Scratch-worker evidence (this worktree's code, port 8103, data root `C:\Triad\data\temp\lab-scratch`, never the product worker or `C:\Triad\data\aegis`)

The worktree has no `.env`, so the worker saw exactly the variables a launcher in the scratchpad
copied into its process (values never printed; the summary lines name variables only).

| Run | Variables from `.env` | `/health/live` | `/aegis/api/status` | `/aegis/api/phrases/providers` |
| --- | --- | --- | --- | --- |
| 1 | none | 200 | **500** `ValidationError: 2 validation errors for Settings` (`postgres_password`, `neo4j_password` missing) | **500**, the same error |
| 3 | `POSTGRES_*`, `AEGIS_PRODUCT_KEY`, plus `NEO4J_PASSWORD=dummy-not-a-secret` | 200 | **200**, the work items from Core's Postgres | **200**, Claude / Codex / Grok available, answered by Core on 8000 against the product key |

So the product needs Postgres and its key; a Neo4j value only satisfies the schema; the operator
token, Ollama and the Neo4j connection details are not needed. Two corrections to earlier notes:
the failure is a **500**, not the 409 the R3.5 plan note recorded (the Aegis app registers no
`ValueError` handler; Core's 409 handler belongs to Core's app), and the error text written to the
worker's log names the missing fields without the present values (checked with dummy values:
`str(ValidationError)` carried neither a dummy Postgres password nor a dummy operator token;
`ValidationError.errors()[*]["input"]` does carry them, which only Core's 409 handler touches, and it
emits `loc` and `type` alone).

### 1.4 Triad, for symmetry

The Triad worker builds `Store()` and `Store(scope="triad")` in twelve places and runs Core's
runtime in-process (`cycles.py`, `development.py`, `acceptance.py`: `self.runtime.execute`), so it
legitimately needs the provider configuration that Aegis does not. A `TriadSettings` would need
its own inventory; Triad is suspended, and nothing under `app/products/triad/` changes here.

## 2. Design: a product-scoped settings model in Core, nothing in the launchers

**Chosen:** `app/trading_core/settings.py` gains `StoreSettings` (the five `postgres_*` fields,
the same `env_file` and `extra="ignore"`), `Settings(StoreSettings)` keeps its thirteen fields and
its two required ones unchanged, and `AegisSettings(StoreSettings)` adds `aegis_product_key` and
nothing else. The worker builds `AegisSettings` through one dependency (`api.get_worker_settings`)
for both its uses: `Store(settings=..., scope="aegis")` on the status route, and the key for
`CoreReasoning`. No second settings file, no copied secret: the same `.env`, read for fewer names.

**Not chosen (now):** an allow-list of variables in `tools/start_product.ps1`. The launcher passes
no `.env` variable today; the worker reads the file from `ROOT`. An allow-list would therefore
change nothing unless the worker stopped reading the file, and that would put a second `.env`
parser (PowerShell) on the supervisor's recovery path and in the scratch launcher, and every way of
starting the worker (the supervisor, the scratch script, a manual start) would have to agree with
python-dotenv on quoting. It remains available as a later hardening with its own QA.

**What breaks without care, and why it does not here**

- The supervisor's recovery (`ensure_product_worker.py` → `start_product.ps1`): untouched; the
  worker still finds `.env` at `ROOT`; `/health/live` never needed a credential.
- The scratch worker from a checkout without `.env`: `/health/live` unchanged; `/aegis/api/status`
  still fails until `POSTGRES_PASSWORD` is present, now for that one field only.
- The gateway's `/aegis/*` proxy and the walk's health reads (`/aegis/api/status` through 8000):
  the status shape is unchanged.
- Key rotation (`tools/issue_product_key.ps1 -Rotate`): the worker reads its key per request, as
  before; no cache.
- The tests that stand in for the worker's store (`server.Store` patched with `lambda **_:` in five
  places) keep working because the store receives its settings by keyword; the three sites that
  request the status route also override `api.get_worker_settings`, so no test reads Core's
  configuration.
- Core's own callers (`Store()`, the gateway's engine, the supervisor, the tools) keep building
  `Settings`; the class name, fields and required set are unchanged.

**Boundary kept:** the only Core file changed is `app/trading_core/settings.py` (the model). The
one-line widening of `Store.__init__`'s annotation (`Settings | None` → `StoreSettings | None`,
no runtime effect) is left for the operator's word, as is anything else under `app/trading_core/`.

## 3. What changed

| File | Change |
| --- | --- |
| `app/trading_core/settings.py:15` | `StoreSettings`: the five `postgres_*` fields, `env_file=ROOT / ".env"`, `extra="ignore"` |
| `app/trading_core/settings.py:28` | `Settings(StoreSettings)`: the same thirteen fields and two required ones as before, now on the base |
| `app/trading_core/settings.py:42` | `AegisSettings(StoreSettings)`: `aegis_product_key` and nothing else |
| `app/products/aegis/api.py:153-160` | `get_worker_settings()` builds `AegisSettings` per request; `WORKER_SETTINGS = Depends(...)` |
| `app/products/aegis/api.py:163-165` | `get_core_reasoning(settings=WORKER_SETTINGS)` takes the key from the worker's settings (was `Settings().aegis_product_key`) |
| `app/products/aegis/server.py:84-86` | the status route takes `WORKER_SETTINGS` and calls `Store(settings=settings, scope="aegis")` (was `Store(scope="aegis")`) |
| `tests/test_aegis_settings.py` (new, aegis) | eight tests, §4 below |
| `tests/test_architecture.py:174` (core) | `test_product_settings_carry_no_core_only_secret`; the shell test (`:131`) overrides the settings dependency |
| `tests/test_aegis_api.py:53`, `tests/test_aegis_lab_api.py:71` | the client fixtures override `api.get_worker_settings`, so no request reads `ROOT/.env` |

Unchanged: `tools/start_product.ps1`, `tools/ensure_product_worker.py`, `tools/start_aegis_scratch.ps1`,
`app/platform_host/`, `app/products/triad/`, `app/trading_core/store.py`, `.env.example`.

## 4. Proof (2026-11-03, this worktree; the main checkout untouched)

- `tests/test_aegis_settings.py` (aegis scope), written first and watched fail on the missing
  models: the worker's model holds exactly its store fields and its key; a `.env` carrying every
  Core name materializes none of the Core-only values (checked in `repr`, `model_dump_json` and
  `vars`); Core-only names set in the process are not materialized either; only `postgres_password`
  is required; the status route hands the dependency's settings to the store with
  `scope="aegis"`; the reasoning client takes its key from them; the dependency builds the product
  model; no module under `app/products/aegis` imports anything from `trading_core.settings` but
  `AegisSettings` or `ROOT`.
- `tests/test_architecture.py::test_product_settings_carry_no_core_only_secret` (core scope),
  watched fail first: `StoreSettings` has the five store fields, `Settings` has them plus the seven
  Core-only names plus the key with `postgres_password` and `neo4j_password` required,
  `AegisSettings` has the store fields plus the key, is not a `Settings`, exposes no Core-only
  name, and both models read the same `ROOT/.env` with `extra="ignore"`.
- Aegis scope on `.venv-aegis`, `PYTHONPATH` on this worktree: `test_aegis_settings`,
  `test_aegis_api`, `test_aegis_ai_reading`, `test_aegis_lab_api`, `test_aegis_lab_harness`:
  165 passed. The full owned scope: see the record line at the end of this section.
- Core scope on `.venv`: `test_architecture` 7 passed and 2 failed for the worktree's environment
  only (`test_product_libraries_absent_from_core_and_triad` wants `.venv-triad` beside the
  checkout; `test_core_startup_with_product_imports_blocked` needs a `.env` for the kill-control
  401 and passes with this worktree's code once `TRADING_HOME` points Core's root at the main
  checkout); `test_core_product_reasoning_api` and `test_core_product_reasoning` 28 passed,
  16 skipped (live integration).
- Lint: `tools/lint_aegis.sh fix` then `check` green on the scope; `ruff check` and
  `ruff format --check` green on `app/trading_core/settings.py`; `git diff --check` clean; no
  control character in any touched file.
- Scratch worker on the narrowed code (port 8103, `C:\Triad\data\temp\lab-scratch`, this
  worktree's `app`, no `.env` in the checkout):

  | Run | Variables in the process | `/health/live` | `/aegis/api/status` | `/aegis/api/phrases/providers` |
  | --- | --- | --- | --- | --- |
  | N1 | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `AEGIS_PRODUCT_KEY` and nothing else from `.env` (no Neo4j value at all) | 200 | **200**, 29 work items from Core's Postgres | **200**, Claude / Codex / Grok available, answered by Core against the product key |
  | N2 | none | 200 | 500, log: `1 validation error for AegisSettings ... Field required ... input_value={}` (`postgres_password`) | 500, the same |

  Before the change the same N1 environment failed both routes on `neo4j_password` (§1.3, run 1
  and the dummy in run 3). The worker on 8102 was not touched.
- The walk is not re-run by this branch (a credential change is QA'd independently); item 98 and
  the status reads exercise the two changed call sites.

Full Aegis scope record (`.venv-aegis`, `PYTHONPATH` on this worktree, `pytest -q -p no:cacheprovider`
from the worktree root): `scope aegis: 1282 run, the full scope; 1662 owned by other scopes
deselected (core 604, triad 1058)`; `1280 passed, 2 skipped` (the QQQ archive is not on this
machine; live integration) in 10 min 59 s.

## 5. Independent QA must check (dispatched by the operator's session)

1. No secret value appears in the diff, the note, the tests, the commit message or the logs under
   `logs/` written during this work (`logs/aegis-scratch.*.log` in the worktree).
2. `Settings` is unchanged for Core: the field set, the required set, `env_file`, `extra`; Core's
   gateway, the supervisor and `tools/health_check.py` still build it.
3. `AegisSettings` has no field, property or method that yields `triad_operator_token`,
   `neo4j_*`, `ollama_*` or `local_model_enabled`; `issubclass(AegisSettings, Settings)` is false.
4. The worker's two call sites (`server.py` status route, `api.py` reasoning client) build
   `AegisSettings` only; `grep -rn "trading_core.settings" app/products/aegis` names nothing else.
5. The product worker on 8102, restarted through `tools/start_product.ps1 -Product aegis` by the
   operator when he chooses, answers `/aegis/api/status` with work items and `/aegis/api/phrases/providers`
   with providers; the supervisor log shows HEALTHY afterwards.
6. A scratch worker from a checkout without `.env` and with only `POSTGRES_*` and
   `AEGIS_PRODUCT_KEY` in its environment answers both routes 200.
7. Key rotation still takes effect without a worker restart (rotate on a scratch copy, never the
   live key, unless the operator says so).
8. The three test sites that request `/aegis/api/status` override the settings dependency and
   `TestClient` requests never read `ROOT/.env` (run the aegis scope from a checkout without
   `.env`, as this worktree is: the overrides make it pass).

## 6. Open points for the operator

1. Widen `Store.__init__`'s annotation to `StoreSettings | None` (one line in `store.py`)?
2. The worker imports `trading_core.api` for `local_headers`, which loads Core's operator surface
   (Brain, Orchestrator, runtime) into the product process. A lighter home for the middleware would
   shrink the product's Core surface; it is a Core change beyond this note.
3. The launcher allow-list (§2, not chosen): wanted later as defence in depth, or not?
4. A missing store credential is a bare 500 on `/aegis/api/status`; a 503 naming the missing field
   would read better in the walk and the supervisor log. Product-only, not done here.
5. The Aegis work item chip `task_1efcb8c1` (the standing item) closes after merge.
