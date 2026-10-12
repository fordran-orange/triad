# Aegis Mission 6 — Experiments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Map the whole control surface of a saved strategy (1 to 10 parameters, no cap on runs)
on a compiled engine, keep every run compactly and resumably, analyse it by the peaks-to-plateaus
principle, and show the report, the decision and the refinement on an Experiments page.

**Architecture:** A numba kernel replaces the per-bar Python loop behind an engine switch, with
the current engine kept as the reference oracle and byte-identical payloads proven. Experiments
are the runner's third job kind: chunks of cells run on a process pool, rows land in Parquet per
chunk, and an interrupted experiment pauses instead of being lost. The surface, the sampler and
the analysis are pure numpy modules; the page reads reports the worker wrote.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas, pyarrow (Parquet), numba 0.68 as the
optional extra `aegis`; React 18, Vite 5, TypeScript, vitest; Playwright for acceptance.

**Spec:** `docs/superpowers/specs/2026-10-12-aegis-experiments-design.md`

## Global Constraints

- Branch `aegis/experiments` in the `C:\Triad` checkout, cut from `main` at the commit of this
  plan. `MISSION6_BASE` in the acceptance script is that commit.
- Outside `app/products/aegis/` only `pyproject.toml` changes, by one line in
  `[project.optional-dependencies]`: `aegis = ["numba>=0.61,<0.69"]`. Nothing under
  `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changes or imports numba.
- Every hash recorded in Missions 3–5 reproduces on the kernel: item 22
  `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360`, items 28 and 34
  `783f07c3146b…` and `5d9371614fc0…`, the fixture constants in the tests.
- Honesty rule: nothing fabricated is shown; absent values render as `—`; refusals carry the
  server's reason; the sampled fraction is shown wherever a sampled experiment is.
- Exchange stays CLOSED, no broker path, Triad suspended, no scheduler change.
- Python tests: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`; lint:
  `.venv/Scripts/python.exe -m ruff check app/products/aegis tests/test_aegis_*.py tests/products/aegis tools/aegis_contracts.py`
  and the same with `ruff format --check`. Tests use a pool of two workers.
- UI commands only from `app/products/aegis/ui`: `npm test`, `npm run build`.
- Any Pydantic model change is followed by `.venv/Scripts/python.exe tools/aegis_contracts.py`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; commit
  with `git -c core.hooksPath=NUL commit -F <file>`.
- Bash on this host: always `cd /c/Triad && …` with absolute paths; write patch scripts to the
  scratchpad with the Write tool rather than shell heredocs containing quotes.

## Plan rulings against the spec

| # | Ruling | Why |
|---|---|---|
| P1 | The planner never enumerates a grid. Cells are addressed by a mixed-radix index over the parameters' value lists; counts are products; validity is decided per indicator from a small table of that indicator's own parameter combinations (every path belongs to exactly one indicator), so `valid_cells` is a product of per-indicator valid counts. | A 10-parameter grid can have millions of cells; enumerating dicts to plan would take minutes and gigabytes. |
| P2 | The experiment kind sets `bars_per_unit = 0` so the runner's shared `ms_per_bar` (single-threaded, per cell-bar) is never fed a wall-clock rate measured across 10 workers. The kind's own `snapshot()` supplies `ms_per_cell_bar` (the workers' mean CPU cost per cell per bar) and `estimated_seconds`, which override the runner's common fields because `_snapshot` spreads the kind's fields last. The planner prices from the last finished experiment's `ms_per_cell_bar`, else `KERNEL_MS_PER_BAR = 0.01`. | Wall time over a pool is not comparable to the optimizer's single-thread cost. |
| P3 | A chunk is at most 200 cells; the runner's unit is one chunk; `total_units` = first-pass chunks + refinement chunks, fixed at start. Refinement chunks whose cells are not yet decided are decided at the first refinement unit; refinement units left without cells (the plateaus had fewer unexplored neighbours than budget) complete as empty units. | The runner fixes the unit count at start (spec §6.1). |
| P4 | Pause reuses the runner's cancel event; `ExperimentJob.finalize(status)` maps `"cancelled"` to the document status `"paused"` when the pause flag was set and to `"cancelled"` otherwise. The runner's own job record keeps `cancelled` either way; the experiment document is the source of truth for its status. | One stop mechanism (spec §6.1). |
| P5 | Parquet files are written whole per commit from the rows held in memory plus the new chunk only while an experiment is small (≤ 20,000 rows); above that, a `ParquetWriter` stays open per job and appends row groups, and resume reads the existing groups then opens a new writer on a sibling file that is merged at completion. A torn last group (pyarrow raises on read) is dropped and its cells rerun. | pyarrow cannot append to a closed file in place. |
| P6 | Sampled-surface neighbours are the `2d` nearest among run cells by brute-force chunked numpy distance when run cells ≤ 50,000; above that the neighbour relation is computed on a seeded random subsample of 50,000 run cells and the report says so. | No scipy; brute force is fine to 50k and the report stays honest beyond. |
| P7 | Materialization and the "curves for named cells" of large experiments go through the pool with the same worker function, with `want_curve=True`; a backtest route call is not used, so no run is persisted unless the operator asked to materialize. | Keeps the runs folder free of report-time byproducts. |
| P8 | `applyCellToStrategy(spec, params)` in the UI applies side-prefixed paths with the existing `setPath` per side; the experiment's pinned spec (not the current document) is the base when materializing, and the current document is the base for "Use in workspace" (parameters only). | The experiment pins a spec snapshot; the workspace document may have moved on. |
| P9 | The reference engine's `entry_permitted` is evaluated lazily only on signal bars; the kernel gets a precomputed `permitted` mask for every bar. Both are pure functions of the bar timestamp, so results are identical; the mask costs one pass per side. | Strings and calendars stay out of the kernel. |
| P10 | The kernel's trades buffer has `n_bars // 2 + 2` rows and raises (via a returned error code, never an exception inside nopython) if exceeded; the Python wrapper turns the code into `RuntimeError`. | Fixed-width buffers without dynamic lists. |
| P11 | Interaction strength = variance of the pair's median matrix minus the variance of the additive fit (row means + column means − grand mean); sensitivity share = variance of a parameter's main-effect medians (weighted by cell counts) / variance of the objective over valid cells; both documented in the report as such. | Spec names them; this pins the arithmetic. |
| P12 | k-means uses Lloyd's algorithm from k-means++ seeds, 20 restarts, 50 iterations max, on standardized (z-scored) `combined.net_return, combined.max_drawdown, combined.trade_count, combined.exposure`; silhouette on a seeded sample of ≤ 2,000 cells. | No scikit-learn. |
| P13 | Report markdown is rendered by `analysis.render_markdown(report)`; the page renders from the JSON. Reports are numbered from 1; the document's `reports` list holds `{report_id, objective, tolerance, generated_at}` and `latest_report`. | One source for both forms. |
| P14 | The nine hygiene items are one task late in the order, each test-first, so the branch's main work is reviewable on its own. | Mission 4 and 5 pattern. |

## Review Focus

1. **numba absent or failing to compile** on a host: every request runs on the reference engine,
   the envelope says `reference`, the status route says `kernel_available: false` with the error
   name, and nothing else changes. Test in Task 1 (`monkeypatch` `kernel.AVAILABLE`).
2. **A worker dies mid-chunk** (a torn last row group, a chunk half-committed): resume runs no
   cell twice and misses none; the cells table has each index exactly once. Test in Task 3.
3. **An objective that is null everywhere** (MAR on a range under a year; profit factor with no
   losses): the report says no valid objective values and makes no recommendation; the page shows
   that sentence, not an empty card. Test in Task 5.
4. **A parameter path the pinned spec cannot resolve** (an indicator the side lacks, a parameter
   the kind lacks, a path on a disabled side, a whole-number parameter with a fractional step): 422
   naming the path, from the plan route and from the create route. Test in Task 2.
5. **A one-parameter surface** (`d = 1`): neighbours are the two adjacent values, a plateau counts
   from 3 cells, main effects are the whole story and the report has no interaction section rather
   than an empty one. Test in Task 5.

---

### Task 1: The kernel, the engine switch and the equivalence proof

**Files:**
- Modify: `pyproject.toml` (one line under `[project.optional-dependencies]`)
- Create: `app/products/aegis/kernel.py`
- Modify: `app/products/aegis/backtest.py` (`BacktestRequest.engine`, `_simulate_side_kernel`, `run_backtest`), `app/products/aegis/api.py` (`_envelope` adds `engine`), `app/products/aegis/server.py` (status adds `kernel_available`, `kernel_error`), `app/products/aegis/optimize.py` and `walkforward.py` (snapshots add `engine`)
- Modify: `tests/test_architecture.py` (numba never imported by Core or Triad)
- Test: `tests/test_aegis_kernel.py` (new), `tests/test_aegis_api.py`

**Interfaces:**
- Produces (`kernel.py`): `AVAILABLE: bool`, `IMPORT_ERROR: str | None`; `trade_capacity(n_bars: int) -> int` (`n_bars // 2 + 2`, P10);
  `simulate_arrays(open_, high, low, close, entry, exit_, warm, evaluating, permitted, side_sign: int, initial_capital: float, allocation_fraction: float, commission: float, slippage_bps: float, close_at_end: bool, carried: np.ndarray) -> tuple[np.ndarray, int, np.ndarray, np.ndarray, np.ndarray, int, np.ndarray, int]`
  returning `(trades[max_trades, 11], n_trades, equity[n], drawdown[n], in_position[n] (uint8), n_points, scalars[10], error_code)`.
  Trade columns, in order: `entry_index, exit_index, signal_index, exit_signal_index, entry_price, exit_price, quantity, gross, net, ret, carried_in` (`entry_index = -1` for a carried position; the wrapper fills its times from the `OpenPosition`). `carried` is `float64[6]`: `present, entry_price, quantity, entry_fee, capital_at_entry, exit_pending` (`exit_pending = 1` fills at the first evaluated bar open). `scalars`: `ending_cash, ending_equity, open_present, open_signal_index, open_entry_index, open_entry_price, open_quantity, open_entry_fee, open_capital_at_entry, open_exit_signal_index` (`-1` when none). `error_code` is `0`, or `1` for a full trades buffer (P10).
- Produces (`backtest.py`): `BacktestRequest.engine: Literal["kernel", "reference"] = "kernel"`;
  `permitted_mask(frame, temporal) -> np.ndarray[bool]`; `_simulate_side_kernel(...)` with the same parameters and return shape as `_simulate_side`; `run_backtest` dispatches on `request.engine` and `kernel.AVAILABLE`, and the result dict gains `"engine": "kernel" | "reference"` (not in `SIDE_KEYS`, never hashed).
- Produces (HTTP): envelopes and job snapshots carry `engine`; `GET /aegis/api/status` carries `kernel_available: bool` and `kernel_error: str | None`.

- [ ] **Step 1: Declare and install the extra.** Add the line to `pyproject.toml`; run
  `.venv/Scripts/python.exe -m pip install -e ".[aegis]"` and confirm
  `.venv/Scripts/python.exe -c "import numba; print(numba.__version__)"` prints `0.68.0`.
- [ ] **Step 2: Write the failing tests** in `tests/test_aegis_kernel.py`:
  - `test_kernel_available_on_this_host`: `kernel.AVAILABLE is True`.
  - `test_kernel_matches_reference_on_every_fixture`: for each of the reference fixture
    `bars()` (default strategy, both sides), the long-only cut-and-carry pair of
    `test_aegis_backtest`, the breakout strategy on `wave_bars(300, 60.0, 8.0)`, the no-indicator
    constant strategy, and a strategy with commission 1.0 and slippage 5 bps: run
    `engine="reference"` and `engine="kernel"`, assert `canonical_payload` hashes equal and the
    side results' `open_position`, `ending_cash`, `ending_equity` equal.
  - `test_kernel_matches_reference_on_carried_windows`: the Mission 5 walk-forward fixture
    (`rsi_walkforward_request()` on `wave_bars(400, 29.0, 6.0)`) run as a job twice with the
    engine monkeypatched to each; `result_hash` equal and every record equal.
  - `test_reference_fallback_when_numba_is_absent`: monkeypatch `kernel.AVAILABLE = False`,
    `kernel.IMPORT_ERROR = "ModuleNotFoundError"`; a kernel request runs on the reference engine
    and reports `engine == "reference"`; the status route reports
    `kernel_available False` and the error name.
  - `test_trades_buffer_overflow_is_an_error_not_a_crash`: a strategy that trades every other
    bar (entry `price.close greater_than price.low`, exit `price.close less_than price.high`) on a
    60-bar frame runs on both engines with equal hashes; with `kernel.trade_capacity` monkeypatched
    to return `1`, the kernel engine raises `RuntimeError("trades buffer full (capacity 1)")`.
  - In `tests/test_aegis_api.py`: `test_status_reports_the_kernel` and
    `test_backtest_envelope_names_its_engine`.
  - In `tests/test_architecture.py`: `test_numba_is_imported_only_under_aegis` (grep the import
    across `app/`).
- [ ] **Step 3: Run them.** `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_kernel.py tests/test_aegis_api.py tests/test_architecture.py`
  Expected: FAIL on the missing module and fields; the architecture test passes (nothing imports numba yet).
- [ ] **Step 4: Implement** `kernel.py` (the reference arithmetic in the reference order: fill
  price `raw × (1 + direction × bps / 10000)`, quantity `floor((cash × fraction − commission) / fill)`
  when positive, marked equity `capital_at_entry + sign × qty × (close − entry) − entry_fee`,
  running peak from `initial_capital`, drawdown `marked / peak − 1`, settlement
  `capital_at_entry + net`, the pending-fill gate `i > signal_index and (evaluating or not carried_exit)`,
  the last-bar travelling exit when `not close_at_end`, the end-of-data close at the last close
  when `close_at_end`, and `equity[-1] = cash` after it); `_simulate_side_kernel` in
  `backtest.py` (arrays from `_side_frame`, `permitted_mask`, the conversion back to the
  reference's dicts including tags from signal timestamps and `carried_from_window`); the
  dispatch; the status and envelope fields; snapshots.
- [ ] **Step 5: Run.** Same command → PASS; then the whole Aegis suite
  `tests/test_aegis_*.py` → PASS with every existing hash constant untouched (the default engine
  is now the kernel, so this run is itself part of the proof).
- [ ] **Step 6: Regenerate contracts, lint, commit** "Aegis engine: numba kernel behind an engine
  switch, byte-identical to the reference".

### Task 2: Surfaces, the grid and the planner

**Files:**
- Create: `app/products/aegis/surface.py`
- Test: `tests/test_aegis_surface.py` (new)

**Interfaces:**
- Produces: `Parameter(BaseModel)`: `path: str`, `start: float`, `stop: float`, `step: float` with
  validators (`step > 0`, `start ≤ stop`; the values list `values() -> list[float]` as
  `start + k·step ≤ stop + 1e-9`, rounded to the step's decimals); `Surface(BaseModel)`:
  `parameters: list[Parameter]` (1–10, distinct paths; messages `"a surface needs at least one parameter"`, `"at most 10 parameters"`, `"duplicate parameter path '<p>'"`).
- Produces: `resolve_path(spec: StrategySpec, path: str) -> tuple[str, str, str]` → `(side_key, indicator_id, field)` or `ValueError("unknown parameter path '<p>'")`; a path on a disabled side raises `ValueError("<path> is on the disabled <side> side")`; whole-number fields with fractional start/stop/step raise the Mission 5 message.
- Produces: `Grid` (dataclass): `shape: tuple[int, ...]`, `values: list[list[float]]`, `paths: list[str]`, `size: int`, `valid_count: int`, `skipped_count: int`, `skip_reasons: dict[str, int]`; `cell_values(index: int) -> dict[str, float]` (mixed radix, first path slowest); `is_valid(index: int) -> bool` and `skip_reason(index) -> str | None` from the per-indicator tables (P1); `valid_indices_iter()` a generator; `apply_cell(spec, params) -> StrategySpec` (per side through `apply_parameters`).
- Produces: `KERNEL_MS_PER_BAR = 0.01`; `effective_workers(max_workers) -> float` (`max_workers × 0.8`);
  `plan(spec, surface, budget: Budget, bars: int, ms_per_cell_bar: float, max_workers: int) -> Plan` with `Budget(runs: int | None, seconds: float | None)` (at least one, both positive) and
  `Plan`: `mode: "exhaustive" | "sampled"`, `grid_cells`, `valid_cells`, `skipped`, `skip_reasons`, `planned_runs`, `first_pass`, `refinement`, `sampled_fraction`, `estimate_seconds`, `ms_per_cell_bar`, `workers`, `bars`, `levers: list[Lever]` with `Lever(kind: "coarsen" | "narrow" | "freeze" | "shorten" | "coarser_timeframe" | "raise_budget", parameter: str | None, label: str, valid_cells: int, estimate_seconds: float, fits: bool, surface: Surface | None, budget: Budget | None, data_hint: str | None)`.
  `estimate_seconds = planned_runs × bars × ms_per_cell_bar / 1000 / effective_workers`; sampled `planned_runs = min(runs, floor(seconds × effective_workers × 1000 / (bars × ms_per_cell_bar)))` over the set budgets, and `ValueError("budget too small for a d-parameter surface")` below `2d + 1`.

- [ ] **Step 1: Write the failing tests** (the breakout spec from Mission 5's tests as the pinned spec, `bars = 3493`, `ms_per_cell_bar = 0.01`, `max_workers = 10`):
  - the spec §2 item-2 surface → `grid_cells == valid_cells == 252`, `mode == "exhaustive"` under `Budget(runs=2000)`, `estimate_seconds == 252 × 3493 × 0.01 / 1000 / 8` to 1e-9;
  - the step-1 surface → `grid_cells == 157542`, sampled, `planned_runs == 2000`, `first_pass == 1334`, `refinement == 666`, `sampled_fraction == 2000 / 157542`;
  - levers on it: freezing `short_side.indicators.ema.length` and `short_side.indicators.sma.length` (apply two levers in turn) → `valid_cells == 682`, `fits`; `coarsen` on donchian → 16 values; `narrow` on rsi (the pinned spec's value 14, range 7–28 step 1: the original values within `[current − span/4, current + span/4]` = `[8.75, 19.25]`) → values 9..19, 11 values; `raise_budget` → `Budget(runs=157542)`; every lever carries the resulting `valid_cells`, `estimate_seconds` and `fits`;
  - a MACD surface (`long_side.indicators.macd.length` 10–30 step 10 × `…params.slow` 20–30 step 10 on a spec with MACD) → `valid_cells == 3`, `skip_reasons == {"MACD fast length must be below slow": 3}` (the reason text taken from the validator message's prefix);
  - `cell_values(0)`, `cell_values(size − 1)` and round trips for 20 random indices;
  - refusals (Review Focus 4): unknown indicator, unknown param, disabled side, fractional step on `…rsi.length`, zero parameters, eleven parameters, duplicate path, `Budget(None, None)`, `Budget(runs=0)`, budget below `2d + 1`.
- [ ] **Step 2: Run.** `pytest tests/test_aegis_surface.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `surface.py`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** "Aegis surfaces: parameters across sides, mixed-radix grids, the planner and its levers".

### Task 3: The pool, the experiment job kind, storage and routes

**Files:**
- Create: `app/products/aegis/pool.py`, `app/products/aegis/experiments.py`
- Modify: `app/products/aegis/jobs.py` (`KINDS` gains `"experiment"`; `resumable`; `mark_lost_on_startup` → paused for resumable kinds), `app/products/aegis/runs.py` (kind `experiments`, `delete_experiment`, file helpers), `app/products/aegis/api.py` (routes), `tools/aegis_contracts.py` (models)
- Test: `tests/test_aegis_pool.py`, `tests/test_aegis_experiments.py` (new), `tests/test_aegis_jobs.py`, `tests/test_aegis_runs.py`, `tests/test_aegis_api.py`

**Interfaces:**
- Produces (`pool.py`): `Pool(max_workers: int)` with `start(rows: list[dict], symbol: str, spec: dict, settings: dict) -> None`, `run_chunk(cells: list[tuple[int, dict[str, float]]], want_curve: bool) -> list[dict]`, `shutdown() -> None`, `mean_ms_per_cell_bar: float | None`; a module-level worker `_run_cell(index, params, want_curve) -> dict` returning `{cell, valid, skip_reason, params, metrics: {combined: {...10}, long: {...}, short: {...}}, elapsed_ms, curve: list[float] | None (128 points), first_time, last_time}`; `resample_curve(points: list[float], n: int = 128) -> list[float]`.
- Produces (`experiments.py`): `ExperimentRequest` (spec §5.1 fields; `tolerance` default 0.15, `seed` default 1), `ExperimentDocument` (`id`, `name`, `strategy_id`, `strategy_hash`, `spec` snapshot, `data`, `settings`, `objective`, `surface`, `budget`, `tolerance`, `seed`, `plan: dict`, `status`, `progress: {cells_done, cells_planned, chunks_done, chunks_total}`, `ms_per_cell_bar`, `engine`, `created_at`, `updated_at`, `parent`, `decision: dict | None`, `reports: list[dict]`, `latest_report: int | None`, `job_id: str | None`, `error: str | None`); `ExperimentJob(document, rows, pinned, pool, repository, library)` as the kind (`name = "experiment"`, `side = "both"`, `resumable = True`, `bars_per_unit = 0`, `total_units`, `run_unit`, `commit`, `snapshot`, `finalize`, `release`); `ExperimentStore(repository)` with `save(doc)`, `get(id)`, `list()`, `cells(id) -> pa.Table | None`, `append_cells(id, rows)`, `curves(id, cells) -> dict[int, list[float]]`, `write_report(id, n, report, markdown)`, `read_report(id, n)`, `delete(id)`; `materialize(store, library, pool_or_none, id, cell) -> envelope` (P7; the envelope persisted under runs with `experiment_id` and `cell`); `pause(runner, doc)`, `resume(...)`.
- Produces (`runs.py`): repository `save_experiment(doc) -> str`, `get_experiment(id)`, `list_experiments()`, `delete_experiment(id)`; `experiment_file(id, suffix) -> Path` under `experiments/`.
- Produces (HTTP): `POST /aegis/api/experiments/plan`, `POST /aegis/api/experiments` (202; `{experiment_id, job_id | null, status}`), `GET /aegis/api/experiments`, `GET /aegis/api/experiments/{id}`, `POST …/{id}/pause`, `POST …/{id}/resume`, `POST …/{id}/cancel`, `GET …/{id}/cells?offset=&limit=&sort=&descending=&valid_only=` (rows as JSON records with `total`), `GET …/{id}/curves?cells=1,2,3`, `POST …/{id}/cells/{cell}/materialize`, `DELETE …/{id}` (409 when queued/running/paused). Errors: 404 unknown; 409 another job running (create still saves the document as `queued`); 422 validation.

- [ ] **Step 1: Write the failing tests.**
  - Pool: `test_pool_runs_a_chunk_and_measures_cost` (two workers, the breakout spec, 60 synthetic cells over `wave_bars`; rows have the 30 metric columns and `valid`; `mean_ms_per_cell_bar > 0`); `test_pool_returns_curves_of_128_points_when_asked`; `test_resample_curve_pads_short_series`.
  - Job: `test_experiment_runs_in_chunks_and_persists_rows` (surface of 2 params, 12 cells, chunk size monkeypatched to 5 → 3 units; after completion the cells table has 12 rows with indices 0..11 once each; the document is `done`, `progress.cells_done == 12`); `test_pause_then_resume_completes_without_duplicates` (pause after the first chunk through the runner's cancel; document `paused`; a new runner resumes; 12 rows once each); `test_restart_marks_an_unfinished_experiment_paused_not_lost` (persist a `running` document, call `mark_lost_on_startup` on a fresh runner → `paused`; an optimization in the same state still becomes `lost`); `test_torn_last_row_group_is_dropped_and_rerun` (Review Focus 2: truncate the cells file after the first chunk; resume; rows exact); `test_cancel_keeps_finished_chunks`; `test_snapshot_overrides_cost_and_estimate` (P2: `ms_per_cell_bar` and `estimated_seconds` present; the runner's `ms_per_bar` unchanged after completion).
  - Materialize: `test_materialize_matches_the_row_and_is_deterministic` (metrics equal the row's; two calls → same `result_hash`; the run envelope carries `experiment_id`, `cell`, `strategy_id`).
  - Repository: `test_experiments_kind_round_trips_and_deletes_files`.
  - API: plan 200 with the spec's fields; create 202 and a queued document under a held runner (409 path) that resumes after the held job; pause/resume/cancel codes; cells paging and sort; curves; materialize; delete 409 while paused then 200 when cancelled; 404s; 422 for a bad path (Review Focus 4 over HTTP).
- [ ] **Step 2: Run** the new and touched test files → FAIL.
- [ ] **Step 3: Implement** in the listed files (P2–P5, P7).
- [ ] **Step 4: Run** → PASS; whole suite → PASS.
- [ ] **Step 5: Regenerate contracts, lint, commit** "Aegis experiments: process pool, resumable chunked job kind, Parquet cells, materialize, routes".

### Task 4: Sampling and refinement

**Files:**
- Modify: `app/products/aegis/surface.py` (`latin_hypercube`), `app/products/aegis/experiments.py` (refinement units)
- Test: `tests/test_aegis_surface.py`, `tests/test_aegis_experiments.py`

**Interfaces:**
- Produces: `latin_hypercube(grid: Grid, count: int, seed: int) -> list[int]` (cell indices; one value per stratum per parameter with a seeded permutation; skipped or duplicate draws redrawn up to `10 × count` tries); `refinement_cells(grid, run_rows, report_plateaus, budget: int) -> list[int]` (unexplored valid cells within one step of the top three plateaus' cells, nearest the centres first; with no plateau, the neighbours of the ten best cells).
- Consumes: Task 5's `analyse()` for the first-pass plateaus (the job imports it lazily at the first refinement unit; until Task 5 lands, the test stubs it).

- [ ] **Step 1: Write the failing tests**: `test_latin_hypercube_covers_every_stratum_once_per_parameter` (count 20 on a 50×50 grid: each parameter's drawn values hit 20 distinct strata); `test_latin_hypercube_is_seeded_and_skips_invalid_cells` (same seed → same indices; a MACD grid never returns an invalid index); `test_refinement_targets_plateau_neighbours_first` (a synthetic first pass with one plateau → refinement cells are its unexplored neighbours, nearest the centre first, and never already-run cells); `test_sampled_experiment_runs_first_pass_then_refinement` (budget 30 on a 20×20 grid with chunk size 10 → units 2 + 1; rows 30 with the `pass` column `sample` × 20 and `refine` × 10, with `analyse` stubbed to return one plateau).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** "Aegis experiments: Latin hypercube sampling and plateau refinement".

### Task 5: The analysis

**Files:**
- Create: `app/products/aegis/analysis.py`
- Test: `tests/test_aegis_analysis.py` (new)

**Interfaces:**
- Produces: `analyse(rows: pa.Table | list[dict], grid: Grid, objective: str, tolerance: float, mode: str, seed: int, data_label: str) -> dict` (the report of spec §8.1 without `report_id`/`generated_at`); the helpers it is built from, each tested alone: `objective_values(rows, objective) -> (values: np.ndarray, valid_mask)` (sign flipped for `max_drawdown`); `neighbours_exhaustive(grid, run_indices) -> dict[int, list[int]]`; `neighbours_sampled(grid, run_indices, k) -> dict[int, list[int]]` (P6); `peaks(values_by_index, neighbours) -> list[int]`; `plateau(peak, values_by_index, neighbours, tau) -> set[int]`; `plateaus(...) -> list[Plateau]` (`Plateau`: `cells`, `median`, `iqr`, `size`, `centre`, `cliff`, `peaks`, `counts: bool`); `main_effects(...)`, `interactions(...)` (P11), `sensitivity(...)` (P11), `clusters(...)` (P12), `render_markdown(report) -> str`.
- Report shape (exact keys): `objective, tolerance, tau, mode, sampled_fraction, valid_cells, skipped, null_objective_cells, neighbour_rule, recommendation (null | {plateau: int, centre: {cell, params, metrics}, supported_peak: {cell, params, objective} | null, fragile_peaks: [...], statement}), plateaus: [...], peaks: [{cell, params, objective, fragile, plateau}], main_effects: {path: [{value, median, p25, p75, count}]}, interactions: [{paths, values_a, values_b, matrix, strength}] | null (d = 1), sensitivity: {shares: {path: float}, remainder: float}, clusters: {k, silhouette, groups: [...]} | {refused: str}, uncertainty: {iqr, cells, sampled_fraction, statement} | null, cells_named: [int]`.

- [ ] **Step 1: Write the failing tests** on synthetic surfaces built in the test (a `Grid` over two parameters 1..9 × 1..9 with objective `f(a, b)`):
  - a flat surface → no recommendation, `tau == 0`, statement names flatness;
  - a plateau at `a ∈ 3..6, b ∈ 3..6` (value 10) with one spike at `(8, 8)` (value 12) and the rest 0: peaks `(8,8)` fragile and one supported peak inside the plateau; the plateau counts (16 ≥ 5 cells), centre `(4,4)` or `(5,5)` by the nearest-to-median rule (pin the exact result), cliff `10`; recommendation centre as pinned; `fragile_peaks == [(8,8)]`;
  - `d = 1` (Review Focus 5): neighbours two per interior cell, plateau from 3 cells, `interactions is None`;
  - null objective everywhere (Review Focus 3): `recommendation is None`, statement "no valid objective values";
  - main effects medians and counts on a known table; interaction strength zero for an additive surface and positive for `a·b`; sensitivity shares sum ≤ 1 and the additive surface's shares match the analytic variances to 1e-6;
  - clusters: two well-separated outcome groups of 30 cells → `k == 2`, silhouette ≥ 0.5; 15 cells → refused "fewer than 20 valid cells"; one blob → refused "no clear structure";
  - sampled neighbours: 400 random run cells of a 50×50 grid → each has `2d = 4` neighbours, nearest by normalized distance; `neighbour_rule` names it;
  - `render_markdown` starts with the recommendation and contains every section heading.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** `analysis.py`. **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** "Aegis analysis: peaks to plateaus, main effects, interactions, sensitivity, clusters, the report".

### Task 6: Reports on the document, decision, refine, contracts

**Files:**
- Modify: `app/products/aegis/experiments.py` (`finalize` writes report 1; `recompute_report`; `decide`; `refine`), `app/products/aegis/api.py` (routes), `tools/aegis_contracts.py` (`ExperimentRequest`, `ExperimentDocument`, `Parameter`, `Surface`, `Budget`)
- Test: `tests/test_aegis_experiments.py`, `tests/test_aegis_api.py`, `tests/test_aegis_contracts.py`

**Interfaces:**
- Produces (HTTP): `POST /aegis/api/experiments/{id}/report` `{objective?, tolerance?}` → the new report (409 while running); `GET …/{id}/report` (latest) and `GET …/{id}/report?n=` (JSON); `GET …/{id}/report.md`; `PUT …/{id}/decision` `{verdict, notes}` → the document; `POST …/{id}/refine` → 201 with the child document (`queued`, `parent`, ranges narrowed to the recommended plateau's span ± one step, same objective/budget/tolerance; 422 when the latest report has no recommendation).
- Produces: `finalize("done")` and `finalize("cancelled")` both write report 1 from the rows present (a cancelled experiment's report says so in `statement`); curves for named cells of large experiments written at report time through the pool (P7).

- [ ] **Step 1: Write the failing tests**: report 1 exists after completion with the spec keys; recompute with another objective and tolerance keeps both reports and `latest_report == 2`; the markdown route serves text starting with the recommendation; decision round trip with `decided_at`; refine narrows ranges as specified and links the parent; refine without a recommendation → 422; contracts staleness and the new interfaces present.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; regenerate contracts.
- [ ] **Step 5: Commit** "Aegis experiments: reports, recompute, decision, refine, contracts".

### Task 7: The Experiments page

**Files:**
- Create: `ui/src/components/ExperimentsPage.tsx`, `ui/src/components/ExperimentPlanner.tsx`, `ui/src/components/ExperimentReport.tsx`, `ui/src/components/MainEffects.tsx`, `ui/src/components/CellsTable.tsx`, `ui/src/experiments.ts` (pure helpers), `ui/src/experiments.test.ts`
- Modify: `ui/src/App.tsx`, `ui/src/components/SideNav.tsx`, `ui/src/state/workspace.tsx` (`page` gains `'experiments'`; `SET_PAGE`), `ui/src/api/client.ts`, `ui/src/results.ts` (report and document types), `ui/src/components/Heatmap.tsx` (generic row/column labels already supported), `ui/src/styles.css`
- Test: `ui/src/experiments.test.ts`, `ui/src/state/workspace.test.ts`

**Interfaces:**
- Produces (`experiments.ts`): `surfaceLine(surface, plan) -> string` ("4 parameters · 252 cells · exhaustive" / "… · sampled 1.3%"); `applyCellToStrategy(spec, params: Record<string, number>) -> StrategySpec` (P8, side-prefixed paths through `setPath`); `cellsView(rows, {sort, descending, plateau}) -> rows`; `recommendationText(report) -> string` (the honest sentence for the card, including "no plateau" and "no valid objective values" cases); `leverLabel(lever) -> string`.
- Produces (client): `api.experimentPlan(body)`, `api.createExperiment(body)`, `api.experiments()`, `api.experiment(id)`, `api.experimentCells(id, query)`, `api.experimentCurves(id, cells)`, `api.pauseExperiment/resumeExperiment/cancelExperiment(id)`, `api.materializeCell(id, cell)`, `api.recomputeReport(id, body)`, `api.experimentReport(id, n?)`, `api.decideExperiment(id, body)`, `api.refineExperiment(id)`, `api.deleteExperiment(id)`.
- Produces (DOM ids, spec §8.2): `#nav-experiments`, `#experiments-list`, `#exp-<id>`, `#experiment-new`, `#experiment-planner`, `#surface-add`, `#surface-path-<n>`, `#surface-start-<n>`, `#surface-stop-<n>`, `#surface-step-<n>`, `#surface-remove-<n>`, `#experiment-objective`, `#budget-runs`, `#budget-seconds`, `#experiment-tolerance`, `#experiment-plan`, `#lever-<kind>-<n>` (`n` the parameter index or `0`), `#experiment-start`, `#experiment-progress`, `#experiment-pause`, `#experiment-resume`, `#experiment-cancel`, `#experiment-report`, `#recommendation`, `#cells-table`, `#materialize-<cell>`, `#use-cell-<cell>`, `#report-objective`, `#report-tolerance`, `#report-recompute`, `#decision-verdict`, `#decision-notes`, `#decision-save`, `#experiment-refine`, `#experiment-error`.

- [ ] **Step 1: Write the failing tests**: `surfaceLine` for both modes; `applyCellToStrategy` sets a long length and a short parameter and leaves the other side alone; `cellsView` sorts by a metric descending and filters by plateau; `recommendationText` for the three cases; `SET_PAGE experiments` in the reducer.
- [ ] **Step 2: Run** `npm test` → FAIL. **Step 3: Implement** the page (list with polling every 2 s while a job runs; the planner with the document gate "save or revert the document first" and both buttons; the report view with SVG main-effect charts, the heatmap for the strongest pairs with `rowLabel`/`colLabel` from the paths, the sensitivity table, clusters or the refusal, the paged cells table with overlays from curves, materialize and use-in-workspace per cell, recompute, decision, refine; every absent value `—`). **Step 4:** `npm test` and `npm run build` → PASS; browser check against a restarted worker: plan, start, finish a 12-cell experiment, read the report, materialize a cell, use it; record the observation in the ledger.
- [ ] **Step 5: Commit** "Aegis UI: Experiments page, planner with levers, report, decision, refine".

### Task 8: Hygiene from Mission 5 (P14)

**Files:** `app/products/aegis/ui/src/api/client.ts`, `app/products/aegis/strategies.py`, `app/products/aegis/walkforward.py`, `app/products/aegis/ui/src/components/RuleEditor.tsx`, `app/products/aegis/optimize.py`, `app/products/aegis/strategy.py`, `app/products/aegis/ui/src/chart/vela.ts`, and their tests.

- [ ] For each item, test first, then the change, then the suite: (1) `errorMessage` renders a list `detail` as the `Value error` messages joined by "; " (falls back to the last entry's `msg`); (2) `StrategyLibrary.get` lets a `ValidationError` through and the route answers 422 `"strategy <id> no longer parses: <field>"`; (3) `plan()` says `"grid has no valid cell: <skip_reason>"`; (4) band operators disabled in the editor when the side has no band, with a title saying so; (5) `WalkForwardRequest` and `OptimizeRequest` refuse `settings.initial_position` and `close_at_end=False` with `"settings.<field> is set by the job itself; leave it unset"`; (6) the P12 test asserts a trade with `carried_from_window == k` exists in a later window; (7) `_values` rounds to the step's decimals; (8) `seriesToOverlay` entries removed with their handles; (9) `CONSTANT` compiled with `re.ASCII`.
- [ ] **Commit** "Aegis hygiene: the nine Mission 5 minors".

### Task 9: Acceptance, worker restart and the mission record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (items 48–60; `MISSION6_BASE`)
- Create: `docs/MISSION6_EXPERIMENTS.md`, `docs/evidence/aegis-acceptance-<stamp>.json`

- [ ] **Step 1: Write the items** (spec §2, in order): 48 kernel on every earlier item (assert the three recorded hashes and `kernel_available`); 49 the 252-cell plan from the Mission 5 document (created by item 37); 50 start and watch chunks advance while `GET /experiments/{id}` answers under 500 ms; 51 pause, restart the worker detached (WMI, as in Mission 5), poll the new PID, see `paused`, resume, wait for `done`, assert 252 rows with distinct indices (`GET …/cells?limit=300`); 52 the report's recommendation, fragile peaks marked, main effects, heatmaps, sensitivity, clusters or refusal, all visible by id; 53 materialize the centre twice → equal hashes, and equal to a direct `POST /backtest` of the pinned spec with those parameters; 54 use the centre → the Charts page with unsaved edits and a run; 55 decision accepted with a note, shown in the list; 56 refine → the child in the list, queued, parent linked, ranges narrowed; 57 the over-budget plan (step-1 surface, budget 2,000) → sampled, levers listed, freeze two short-side parameters → 682 exhaustive; 58 recompute the report with net P&L and tolerance 0.10 → two reports; 59 the refusals of §2 item 12 over HTTP; 60 governance, the Core/platform/Triad diff empty against `MISSION6_BASE`, and `git diff MISSION6_BASE HEAD -- pyproject.toml` containing exactly one added line.
- [ ] **Step 2: Build and restart** (`npm run build`; WMI restart; poll the new PID; confirm `kernel_available`).
- [ ] **Step 3: Run** `.venv/Scripts/python.exe tests/products/aegis/browser_workstation.py` → 60/60 PASS; copy the JSON to `docs/evidence/`.
- [ ] **Step 4: Full verification**: whole pytest suite, ruff, contracts check, `npm test`, `npm run build`; record counts and the kernel's measured cost per cell.
- [ ] **Step 5: Write the record** `docs/MISSION6_EXPERIMENTS.md` (decisions incl. the peaks-to-plateaus principle verbatim, built table by commit, acceptance evidence, measurements incl. the speed-up, plan rulings P1–P14, execution rulings, the per-product-environment mission as the first open item, known limits) and commit "Aegis: Experiments acceptance and the Mission 6 record".

### After Task 9

Milestone QA (independent agent at the exact commit, the spec §10 brief, including the numba
extra and the architecture assertion), whole-branch review on the most capable available model,
one fix pass with every fix test-first, the record completed, and the finishing menu (merge and
push only on the operator's answer).
