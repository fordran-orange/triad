# Aegis Optimization Lab v2, Phase 3: linked analytics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Lab its deterministic analytics on the Phase 2 trial store: screening blocks scored with warm-up, importance with its three uncertainties and the coarse decomposition that may propose `Deprioritized` (never exclude), the four robustness categories on a candidate card, Pareto fronts, exact-mode parallel coordinates and convergence. Heavy work runs as Lab tasks beside a running experiment, and Screen B's tabs and Screen E (Parameter Families) show the results with their basis.

**Architecture:** New Aegis-owned modules under `app/products/aegis/lab/`:
- **Analytics:** `analytics.py` (cohort, fine-grid and coarse estimators, intervals, floors, availability, statuses), `neighbours.py` (positions hashing), `robustness.py` (categories A–D, rankings), `pareto.py`, `parallel.py` (the exact sample) and `convergence.py`.
- **Tasks:** `tasks.py`, a single-thread Lab task executor outside `JobRunner`.
- **Engine and job:** `evaluate_from` on the metrics path; block evaluations in the pool and the experiment job.
- **Wiring:** new views on the existing `POST /lab/{src}/query`, and React components that follow the Phase 2 per-panel pattern over `charts/canvas.ts`.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, pyarrow 23, numpy (seeded `np.random.default_rng`), the numba kernel (one new mask argument path, defaults unchanged); React 18, TypeScript, Vite 5, Canvas 2D, vitest (node, `src/**/*.test.ts`); Playwright walk `tests/products/aegis/browser_workstation.py`; PowerShell 7 for the scratch launcher. No new dependency.

**Spec:** `docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`:
- §7.3–7.11: the algorithms, with the policy constants Randall approved under Q6.
- §5.2 and §5.5: Screen B's tabs and rail, and Screen E.
- §5.10: the views.
- §6.3–6.4: the `block` column and `evaluations`.
- §9.4: Lab tasks.
- §9.6a: the Phase 3 rows Pareto, neighbourhood and importance.
- §10.2 rule 2: warm-up is never scored.
- §11, Phase 3 row; §15 rows 5, 14 and 26; §16 R3.5; §20: the sixteen statistical cases and the block, robustness and Pareto tests.

The R3 note (`docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2-r3.md`) carries the Track A and Track B misses into this phase (Task 0).

## Global Constraints

- **Dependencies.** No new Python or JS dependency: `package.json`, `requirements-aegis.lock` and `requirements.lock` are unchanged. scipy, statsmodels, DuckDB and `uplot` are not adopted (§12). `canvas.ts` stays ≤ 800 lines; the R2.5 decision is that the hand-written primitives stay.
- **Frozen areas.** Nothing changes under `app/trading_core`, `app/platform_host` or `app/products/triad`: the walk's governance item keeps `LAB_BASE = "1882c81"` with exactly `LAB_MAIN_CORE_FILES` (Mission 14's four fix-pass files) and nothing else. `canonical_payload`, `strategy_hash`, `results.py`, `tests/fixtures/aegis_engine_golden.json`, `tests/fixtures/aegis_study_golden.json`, `builder_identity.py` and `study_identity.py` are unchanged; with `evaluate_from=None` every engine path is byte-identical to today (§7.3a).
- **Saved data.** Existing saved documents are never rewritten. `ExperimentDocument` and `ExperimentRequest` gain one optional field, `blocks: int = 0`, which keeps every existing and legacy document at no blocks. `contracts.ts` is regenerated on the Aegis interpreter (`C:\Triad\.venv-aegis\Scripts\python.exe tools\aegis_contracts.py`, LF bytes) and `--check` passes.
- **What analytics may do.** Analytics are pure numpy and pyarrow over projected columns, seeded through `np.random.default_rng(seed)` with the seed in every response. They never fit a model or interpolate, and never change a status: Phase 3 computes the **recommended** status and its reason; persisted statuses, operator confirmation (§7.4a condition 6), apply and proposals are Phase 4.
- **Constants.** Every §7 constant lives in `lab/policy.py` with the spec's value (Task 1) and is printed on the panel that uses it. A panel reads its constants from the response, never from a UI literal.
- **Lab tasks.**
  - They never start a pool process, never call `JobRunner.start`, never register a `jobs.KINDS` kind, never take `JobRunner`'s lock beyond one `runner.status` snapshot, and never hold `LOCKS.read` across compute: load the frame through `open_experiment`, release the lock, compute, then `REGISTRY.release`.
  - One task runs at a time. A task yields between resamples (`time.sleep(0)` at every checkpoint) and is cancellable there.
- **Response bounds.** The Phase 2 bounds are kept, and every new view carries `scope`, `snapshot`, `provisional`, the echoed `filter_hash` and its basis line. New bounds:
  - `pareto`: front ≤ 2,000 points, sampled with a label beyond that, plus one 64 × 64 density grid;
  - `parallel` with `parallel_mode = "sample"`: ≤ 5,000 lines;
  - `convergence`: ≤ 1,000 points;
  - `interactions`: ≤ 190 pairs (d ≤ 20);
  - `triples`: top 20.
- **Column projection.** Every new view has an explicit `COLUMNS_FOR` branch before the trailing `parallel` `else`, and `tests/test_aegis_lab_api.py::test_query_loads_projected_columns_only` is extended to every new view.
- **Block 0 by default.** Every ordinary view filters `block = 0` and says so. Blocks feed only the period-uncertainty computations, the per-block mains and category C's selection-period diagnostic (§7.3a).
- **Losses are red.** A P&L-signed value below zero is never green or blue-best. Every chart states its basis (`Tested (exact)`, `Aggregated from tested (n)`, `Sampled subset (n of N)`).
- **Running the tests.** From the worktree, in PowerShell: `$W='C:\Triad\.claude\worktrees\zen-thompson-50e9bb'; Set-Location $W; $env:TRIAD_PYTEST_SCOPE='aegis'; $env:PYTHONPATH="$W\app;$W\tests"; $env:PYTHONDONTWRITEBYTECODE='1'; Remove-Item Env:PYTEST_ADDOPTS -ErrorAction SilentlyContinue; C:\Triad\.venv-aegis\Scripts\python.exe -m pytest -q -p no:cacheprovider <paths>` (written `PYTEST`; the whole scope takes no paths). Every new test module carries `pytestmark = pytest.mark.aegis`.
  - **UI:** `npm test` and `npm run build`, from `app/products/aegis/ui`.
  - **Lint:** `bash tools/lint_aegis.sh fix` (never a bare ruff).
  - **Engine guard set:** `tests\test_aegis_experiments.py tests\test_aegis_pool.py tests\test_aegis_engine_golden.py tests\test_aegis_api.py tests\test_aegis_kernel.py tests\test_aegis_results.py tests\test_aegis_stops.py tests\test_lab_sharpe.py`.
- **Browser evidence and benchmarks.** These come only from the scratch worker: `tools\start_aegis_scratch.ps1 -Port 8103 -DataRoot C:\Triad\data\temp\lab-scratch`, serving this checkout's `ui/dist` after `npm run build`. Never from the product worker on 8102 or `C:\Triad\data\aegis`.
  - **The walk:** `C:\Triad\.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:8103/aegis/ --only lab --data-root C:\Triad\data\temp\lab-scratch --pid-file logs\aegis-scratch.pid`.
  - **Benchmarks:** `lab_benchmark.py` on the Aegis interpreter with `--base`, `--pid-file` and `--data-root`.
- **Independent QA at R3.5 is mandatory** for the statistical fixtures (§16). A reviewer who wrote none of Tasks 4–6 re-derives the sixteen cases' expectations. The builder does not self-approve them.
- **Commits.** Each message is written with the Write tool and committed with `git commit -F`, with the attribution trailer the session's instructions give. Nothing is pushed or merged; merging stays Randall's answer.

## Review Focus

1. **A block whose frame is shorter than a configuration's warm-up** (a long Donchian on block 1 of a short range).
   - Expected: that block's row is `invalid: insufficient bars`, block 0 decides the configuration's status, and importance's missingness counts it, so the rule reads `unavailable: … invalid …` and never silently drops it.
   - Test: Task 2, `test_lab_blocks.py::test_short_block_is_invalid_and_counted`.
2. **An importance request while an experiment job runs, then the source moves to a new snapshot mid-task** (compaction finishes a generation).
   - Expected: the task finishes on the snapshot it pinned at request time and labels its result with it. Polls while it runs keep at most one pending task per source and method (the newest snapshot; older pending ones are dropped). The view shows the newest finished result as `snapshot X · current Y` and never as current when it is not.
   - Test: Task 3, `test_lab_tasks.py::test_snapshot_changes_coalesce`.
3. **Cancel in the middle of the coarse bootstrap.**
   - Expected: stages already delivered stay readable and labelled partial (`cancelled after stage 2 of 3`). No half-computed interval is shown, and the next request restarts at the missing stage.
   - Test: Task 3, `test_cancel_keeps_finished_stages`.
4. **A metric with undefined values for some configurations** (`profit_factor` without losses).
   - Expected: the descriptive estimates say `on n of N configurations; missingness may bias`; the rule is `unavailable: n of N configurations have no finite <metric> (k invalid, m failed, u undefined)`; switching to `net_pnl` makes it available.
   - Test: Task 5, case 16.
5. **A legacy (layout 1) or `opt:` source opened on a Phase 3 tab.**
   - Expected: legacy experiments get positions from their parameter values (no `pos.<k>` columns), Pareto, parallel and convergence work, and importance says `computed on n uniform trials of N` with `design` inferred from `pass`. An `opt:` grid job gets importance on its exhaustive grid with the period uncertainty `not measured: no screening blocks`.
   - Test: Task 7, `test_legacy_experiment_neighbourhood_from_values`; Task 6, `test_importance_on_an_optimization_grid`.

---

### Task 0: R3 carry-over: the 1M query latency and memory, and the job's host growth

R3 recorded four Track A misses at 1M trials:

| Row | Measured | Budget |
|---|---|---|
| warm open | 2,202 ms | 1,500 |
| filter + heatmap | 795 ms | 400 |
| stat change | 851 ms | 300 |
| worker memory | 828 MB | 450 |

It also recorded the job's host growth on Track B: 920 MB on case A and 506 MB on case B, against 100.

A profile on a copy of the 1M fixture (2026-10-29) found the causes, and matched the HTTP figures in process.
- **Per-request rework.** Each request recomputes work fixed by the snapshot:
  - **The summary** runs the whole `marginals_view` (`sources.py:492`), about 900 ms, only to keep each value's `n`.
  - **The aggregate matrix** (`query.py:515`) recomputes ten parameters' lattice positions (`_positions`, 190 ms), a stable metric argsort (`_by_value`, 150 ms), the completed mask three or four times, and the confounding check (280 ms). None of it depends on `stat`.
  - **Page** runs three stable argsorts (180 ms).
- **The cache** keys the projected table by the ordered column tuple (`sources.py:302`), so the same 15 columns were held three times: 381 MB for 112 MB of data. About 460 MB more is freed Arrow memory that mimalloc keeps.
- **The job's host growth** is the report analysis, not trials. `analysis.neighbours_sampled` builds a 512 × n × 10 float64 difference cube (`analysis.py:103-105`) at the first pass (`_decide_refinement`) and again at finalize: about 830 MB at n = 10,000. `_silhouette` adds a 2,000 × 2,000 × D cube.

Each fix below was prototyped against the current code and is bit-identical in output. The profile scripts and their outputs are committed beside this plan in `docs/superpowers/plans/2026-10-29-aegis-optimization-lab-v2-phase3-profile/`. Case A's rate miss (144.7 against 150 trials/s) is engine cost and stays a finding: no engine speed work in this phase.

**Files:**
- Modify: `app/products/aegis/lab/sources.py`:
  - the cache key at :302 becomes the sorted column set, with a zero-copy `select` in the requested order on a hit;
  - `summary` (:471) computes `tested_per_value` by `np.bincount` over the index's codes, keeping the bucket path for lattices over `MARGINAL_BUCKETS`, and caches its snapshot part under `("exp-summary", id), created_at, generation, watermark`.
- Modify: `app/products/aegis/lab/cache.py`: after a miss's load and after every eviction, call `pa.default_memory_pool().release_unused()`.
- Create: `app/products/aegis/lab/index.py`, the per-snapshot derived index described below.
- Modify: `app/products/aegis/lab/query.py`: `filter_mask`, `matrix_view`, `page_view`, `marginals_view` and `scope_counts` accept `index: FrameIndex | None = None` and use it when given. With `None` they compute exactly as today, which the property test compares against. `matrix_view` in aggregate mode computes all four stats in one pass, cached by `sources` as below.
- Modify: `app/products/aegis/lab/store.py` `_canonical` (:466): skip the sort and `take` when `(trial_no, block)` is strictly increasing lexicographically (true for unblocked and blocked data written in order).
- Modify: `app/products/aegis/analysis.py`: `neighbours_sampled` (:90-110) and `_silhouette` (:358) block their rows by bytes, `block = max(1, 32 MiB // (n · D · 8))`, with the same arithmetic per row, so the relation and the report are unchanged.
- Test: `tests/test_lab_query.py`, `tests/test_aegis_lab_api.py`, `tests/test_lab_store.py` and `tests/test_aegis_analysis.py` (append to each).

**Interfaces:**
- Produces: `@dataclass(frozen=True) FrameIndex` with:
  - `completed: np.ndarray[bool]` (block 0 and `ok`);
  - `codes: dict[str, np.ndarray]` (uint16 per parameter: `pos.<k>` when the frame has them and they equal `_positions` on the first chunk, otherwise `_positions` once);
  - `order(metric_column, descending) -> np.ndarray[int32]`: the stable order of the whole frame, with ties by `trial_no`, built lazily and memoized.

  Also `build_index(frame: TrialFrame) -> FrameIndex`, cached in `LabCache` beside the table under `("exp-index", id), created_at, generation, watermark` and sized by its arrays.
- Produces: `sources.matrix_payload_key(source_identity, snapshot, canonical_filter, scope, rows, cols, metric, fixed, mode)`, where `source_identity` is `("exp", id, created_at)` or `("opt", job_id, cells_done)`, as the summary key has, so one experiment is never served another's heatmap.
  - `canonical_filter` is `json.dumps(LabFilter.model_dump(mode="json", by_alias=True), sort_keys=True)`: a server-side cache key only, never echoed. The client's `filter_hash` is still echoed as given.
  - An aggregate matrix's payload for all four stats is cached under this key, and a stat change answers from it.
- Consumed by Task 7: `index.codes` gives `neighbours.position_codes`.

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_lab_query.py::test_index_answers_equal_per_request_answers`: over `synthetic_frame(20_000, 6, seed)` for 5 seeds and the 200-sequence churn of Phase 2's `test_counts_stable_under_axis_and_filter_churn`. `counts`, `matrix` (exact and every aggregate stat), `page` (both directions, with ties) and `marginals` with `index=build_index(frame)` equal the same views with `index=None`, payload and `scope`, exactly.
  - `test_index_order_ties_by_trial_no`: equal metric values sort by `trial_no` both ascending and descending.
  - `test_pos_codes_equal_positions`: the index's codes equal `_positions` for a layout-2 frame, and a frame whose `pos.<k>` disagree falls back to `_positions`.
  - `tests/test_aegis_lab_api.py`:
    - `test_cache_key_is_the_column_set`: two queries whose projections hold the same columns in different orders make one cache entry, and each table's columns follow its request.
    - `test_stat_change_is_served_from_the_matrix_payload`: a spy on `matrix_view` is called once for `best` then `median` on the same filter.
    - `test_matrix_payload_never_crosses_sources`: two experiments at the same snapshot numbers and filter answer their own matrices.
    - `test_summary_tested_per_value_equals_marginals_n`.
    - `test_memory_released_after_a_load`: a spy on `release_unused` is called after a miss.
  - `tests/test_lab_store.py::test_canonical_skips_the_take_on_identity_order`: a spy on `Table.take` is not called on an in-order blocked table, the table is equal, and a table with a repeated `(trial_no, block)` still dedupes.
  - `tests/test_aegis_analysis.py::test_sampled_neighbours_bounded_and_identical`: for n = 3,000, D = 6 the relation equals the 512-row version, and `tracemalloc`'s peak is < 64 MB.
- [ ] **Step 2: Run them** (`PYTEST tests\test_lab_query.py tests\test_aegis_lab_api.py tests\test_lab_store.py tests\test_aegis_analysis.py`). Expected: FAIL.
- [ ] **Step 3: Implement** as above.
- [ ] **Step 4: Run to pass**, then the whole Aegis scope, the engine guard set, both identity scripts `identical`, and lint.
- [ ] **Step 5: Measure, never re-baseline.** On a freshly restarted scratch worker:
  - `lab_benchmark.py explore --trials 1000000`. Expected: every Track A row True. The profile projects open 300–550 ms, filter + heatmap 250–300 ms, stat change < 50 ms and worker growth 200–250 MB.
  - Restarted with `-Workers 10`, `lab_benchmark.py execute --cases A,B,C`. Expected: host growth well under the R3 figures. The 100 MB limit, case A's rate and the query p95 ratio are recorded as they come.

  A row still missing is a finding for the R3.5 note, with its numbers.
- [ ] **Step 6: Commit** "Lab: the R3 carry-over: a per-snapshot index, one cache entry per column set, released Arrow memory, bounded report neighbours".

---

### Task 1: The Phase 3 policy constants and `evaluate_from` on the metrics path

**Files:**
- Modify: `app/products/aegis/lab/policy.py` (the constants below).
- Modify: `app/products/aegis/backtest.py`: `_side_metrics` (:862) and `run_metrics` (:918), plus the `_metrics_arrays` stamps (:910-911) and `first_time` / `last_time` (:942-943, :973-974).
- Test: extend `tests/test_lab_identity.py::test_policy_constants_match_spec`; create `tests/test_lab_blocks.py` (`pytestmark = pytest.mark.aegis`).

**Interfaces:**
- Produces, in `lab/policy.py`, with these exact values:
  - **Importance and interval constants:** `IMPORTANCE_ROWS = 50_000`, `BOOTSTRAP_B = 200`, `PERMUTATION_P = 200`, `COARSE_BOOTSTRAP_B = 50`, `COARSE_PERMUTATION_P = 50`, `COARSE_BINS = 4`, `INTERVAL = 0.90`, `FLOOR_QUANTILE = 0.95`.
  - **Blocks:** `SCREEN_BLOCKS = 4`, `MAX_BLOCKS = 8`.
  - **Coverage and aliasing:** `IMPORTANCE_MIN_N_FACTOR = 30`, `IMPORTANCE_MIN_PER_VALUE = 20`, `ALIAS_V = 0.3`, `PAIR_MIN_N = 4`, `PAIR_MIN_COVERAGE = 0.5`, `PAIR_BALANCE_TVD = 0.25`, `TRIPLE_TOP = 20`.
  - **The rule:** `RESIDUAL_VETO = 0.3`, `RESIDUAL_INCONSISTENT = -0.05`, `THETA_MIN = 0.01`.
  - **Robustness:** `PLATEAU_MIN_COVERAGE = 0.5`, `NEIGHBOUR_R = 1`, `NEIGHBOUR_M_GRID = 1`, `NEIGHBOUR_M_SAMPLED = 2`, `PEAK_IQR_FACTOR = 3.0`, `REGION_RADIUS = 0.15`, `REGION_AXES = 6`, `REGION_MIN_N = 30`, `FOLDS_MIN = 3`, `FOLD_MIN_TRADES = 30`, `FOLD_RATIO_BAND = (0.5, 2.0)`, `FOLD_DRAWDOWN_FACTOR = 1.5`, `STRESS_KEEP = 0.70`, `STRESS_DRAWDOWN_FACTOR = 1.3`.
  - **Pareto, parallel and convergence:** `PARETO_FRONT_MAX = 2_000`, `PARETO_DENSITY_BINS = 64`, `PARALLEL_MAX_LINES = 5_000`, `PARALLEL_STRATA = 10`, `CONVERGENCE_BATCH = 5_000`, `CONVERGENCE_TOP = 0.01`, `CONVERGENCE_MAX_POINTS = 1_000`.
  - **Task budgets:** `TASK_BUDGET_S = 180`, `FINE_STAGE_BUDGET_S = 30`.
- Produces: `run_metrics(request, frame, data_key, cache, want_curve=False, want_lab=False, *, evaluate_from: datetime | None = None) -> dict` and `_side_metrics(..., evaluate_from=None)`.
  - With `evaluate_from` set, the `evaluating` mask is built exactly as `_simulate_side_kernel` builds it (`backtest.py:686-689`). `first_stamp` and `last_stamp` and `first_time` and `last_time` come from the first and last **evaluated** bars, so `cagr` and `mar` match `run_backtest`.
  - The non-kernel fallback passes `settings.model_copy(update={"evaluate_from": evaluate_from})`.
  - Positional callers are untouched: `engine_golden.py:124` and `builder_identity.py:95-101` pass five arguments, and `test_aegis_stops.py:241-243` passes four.

- [ ] **Step 1: Write the failing tests.**
  - **Constants:** `test_policy_constants_match_spec` asserts every constant above.
  - **`test_block_metrics_equal_full_engine_with_evaluate_from`** is parametrized over `engine in ("kernel", "reference")` on `tests/test_aegis_pool.py`'s `ROWS` (260 thirty-minute bars) with `pinned()`. For `evaluate_from = ROWS[130]["time"]`, `run_metrics(prepared, frame, key, cache, False, True, evaluate_from=at)[scope]` equals `run_backtest(BacktestRequest(..., settings=BacktestSettings(evaluate_from=at)))["metrics"][scope]` for every scope and every one of the ten `pool.METRICS`, within `1e-12`, and `lab_metrics` equal `sharpe_scopes` of the run's trades.
  - **`test_warmup_contributes_no_trades_or_equity`:** with `want_curve=True`, no trade's `entry_time` and no curve point is before `evaluate_from`, and `first_time == evaluate_from`.
  - **`test_evaluate_from_none_is_byte_identical`:** `json.dumps(run_metrics(..., evaluate_from=None), sort_keys=True)` equals the call without the keyword, and the 14 golden keys are unchanged (run `tests\test_aegis_engine_golden.py`).
- [ ] **Step 2: Run them**: `PYTEST tests\test_lab_identity.py tests\test_lab_blocks.py`. Expected: FAIL, because the constants are missing and `evaluate_from` is an unexpected keyword.
- [ ] **Step 3: Implement** the constants and the keyword as described above.
- [ ] **Step 4: Run to pass**, then the engine guard set in full (14 golden keys unchanged). Run `builder_identity.py compare` and `study_identity.py compare` against the Phase 2 baselines (`C:\Users\fordr\AppData\Local\Temp\claude\C--Triad--claude-worktrees-zen-thompson-50e9bb\47846fe8-9b60-40a1-8500-a36e70370397\scratchpad\identity-before.json` and `study-identity-before.json`): both `identical`. Then `bash tools/lint_aegis.sh`.
- [ ] **Step 5: Commit** "Lab Phase 3: the analytics constants and evaluate_from on the metrics path".

### Task 2: Screening blocks in the pool, the experiment job, the planner and the readers

**Files:**
- Modify: `app/products/aegis/pool.py`: `_run_cell` (:163), `Pool.run_chunk` (:243), and a per-worker block-frame dict replacing the single `_WINDOW` for blocks.
- Modify: `app/products/aegis/experiments.py`:
  - `ExperimentRequest` (:96) and `ExperimentDocument` (:121): `blocks: int = 0`, validated `0` or `2 ≤ blocks ≤ policy.MAX_BLOCKS`.
  - `_cells_table_v2` (:291): `block` from the row.
  - The job's `run_unit` (:978) and `commit` (:1002).
  - Block-aware readers: `done_cells` (:461), `cells()` and `_legacy_projection` (:496), `row()` and `_row_of` (:538), `_recount_counters` (:825) and `_count` (:1038).
- Modify: `app/products/aegis/surface.py` `_core` (:501), so the price counts every evaluation's bars.
- Modify: `app/products/aegis/lab/identity.py` (`inputs_key` :128-129 and `sampler` :178 carry `blocks`), `lab/store.py` `Counters.from_document` (:107), and `lab/query.py` `scope_counts` (:261: `evaluations = scheduled × (K + 1)`).
- Modify: `app/products/aegis/ui/src/components/ExperimentPlanner.tsx`: a `#experiment-blocks` checkbox "Screen across periods (4 blocks)" that sets `blocks: 4`. The plan line shows "evaluations: N × 5".
- Test: `tests/test_lab_blocks.py` (append), `tests/test_aegis_experiments.py` (append), and `tests/test_aegis_surface.py` for the price.

**Interfaces:**
- Consumes: Task 1's `run_metrics(..., evaluate_from=)`.
- Produces: `block_bounds(n_bars: int, k: int) -> list[tuple[int, int]]` in `experiments.py`.
  - It returns `k` contiguous `[start, end)` bar ranges of equal length, the last taking the remainder, and is pure.
  - Block `b`'s evaluation runs on `frame_slice(frame, 0, end_b)` with `evaluate_from = timestamps[start_b]`: warm-up comes from all prior history in the range, and only the block is scored (decision 1).
- Produces: `Pool.run_chunk(cells, want_curve, window=None, blocks: list[tuple[int, int]] | None = None) -> list[dict]`. Each cell returns `1 + len(blocks)` rows carrying `block` (0 first), all with the cell's `params` and `trial_no`.
  - Only block-0 rows carry curves; `_curves_table` stays keyed by cell.
  - `_cell_bars_total` adds each evaluation's own bars: `bars` for block 0 and `end_b` for block `b` (pool.py:262-265). Otherwise `ms_per_cell_bar` comes out about 30 % low at K = 4 and misprices every later plan (review B7).
  - The worker's `IndicatorCache` is sized by the sum of its prefix frames' lengths.
  - A block frame shorter than `MIN_BARS = 35` (`backtest.py:150`) is refused by the planner: 422 `blocks: <K> blocks of <n> bars leave <m> per block, under the 35-bar minimum`. A block that still fails `frame_slice` in the job becomes an `invalid: insufficient bars` row.
  - `TrialFrame` gains `blocks: int` (set by `open_experiment` from the document). Ordinary views filter to block 0 **before caching**, so a blocked experiment costs the cache no more than an unblocked one; the importance task loads every block.
- Produces: the job writes one chunk file per unit holding every block row of its cells, so a crash leaves a whole configuration or none.
  - `done_cells` counts a configuration done from its block-0 row.
  - `cells()`, `row()`, `analyse`, `_decide_refinement`, `_write_report`, `recompute_report`, the GET cells route and `materialize` read block 0 only.
  - `cells_done` and progress count configurations. `evaluations` and `evaluations_done` are reported beside them.
- Produces: `surface._core` prices `per_configuration_bars = bars + Σ_b end_b`, which is ≈ 3.5 × bars at K = 4 (decision 1). `Plan` gains `blocks: int` and `evaluations: int`.

- [ ] **Step 1: Write the failing tests** (`test_lab_blocks.py` unless named):
  - **`test_block_bounds_are_contiguous_and_cover_the_range`:** `block_bounds(260, 4) == [(0,65),(65,130),(130,195),(195,260)]`; `block_bounds(263, 4)[-1] == (195, 263)`.
  - **`test_pool_returns_one_row_per_block`:** a 3-cell chunk with `blocks=block_bounds(len(ROWS), 4)` gives 15 rows, blocks `0..4` per cell in order. Each block row's metrics equal `run_metrics(frame_slice(frame, 0, end), evaluate_from=time[start])` for that block.
  - **`test_configuration_identity_across_blocks`:** a 12-cell experiment with `blocks=4` run through the API (the `world` fixture). Every `trial_no` has exactly 5 canonical rows sharing `param_key` and `params`. Then:
    - `compact` → `read_latest` holds 60 rows and `duplicates == 0`;
    - a resume after a forced stop after one unit re-runs only the missing configurations;
    - `materialize` reproduces block 0's metrics;
    - `scope_counts` gives `completed == 12`, `evaluations == 60`, `evaluations_done == 60`.
  - **`test_canonical_attempt_after_retry_across_compacted_files`:** hand-written chunks give `(trial 7, block 2)` attempt 0 `failed` in a part and attempt 1 `ok` in a later chunk, plus a copy of attempt 1 in a second chunk. The canonical table has one `ok` row for it, and `duplicates == 1`.
  - **`test_short_block_is_invalid_and_counted`** (Review Focus 1): a Donchian length longer than block 1's 65 bars but shorter than the 260-bar range. Block 1's row is `status == "invalid"` with `skip_reason` starting `insufficient bars`, block 0's row is `ok`, and `scope_counts` gives `completed == 1`.
  - **`tests/test_aegis_experiments.py::test_legacy_readers_see_block_zero_only`:** the experiment's report, `cells()` length and `GET /experiments/{id}/cells` are identical to the same experiment with `blocks=0`, apart from `blocks` and the evaluation counts.
  - **`tests/test_aegis_surface.py::test_plan_prices_every_evaluation`:** at `blocks=4` the per-run seconds equal the `blocks=0` figure × `(bars + Σ end_b) / bars`, and `plan.evaluations == planned_runs × 5`.
  - **`test_blocks_must_be_zero_or_two_to_eight`:** `blocks=1` and `blocks=9` give 422 from `POST /experiments/plan`, and so does `blocks=8` on a 200-bar range (25 bars per block).
  - **`test_measured_rate_counts_each_evaluations_bars`:** after a blocked run, the persisted `ms_per_cell_bar` is within 10 % of an unblocked run's on the same surface.
  - **`test_inputs_key_changes_with_blocks`.**
- [ ] **Step 2: Run them** (`PYTEST tests\test_lab_blocks.py tests\test_aegis_experiments.py tests\test_aegis_surface.py tests\test_lab_identity.py`). Expected: FAIL.
- [ ] **Step 3: Implement.** `_run_cell(index, params, want_curve, window=None, block: tuple[int, int, int] | None = None)` takes `(block_no, start, end)`. The worker keeps a dict of up to `MAX_BLOCKS + 1` prepared prefix frames keyed by `end`, each with its own `data_key`.
  - The job computes `block_bounds(len(self.frame), document.blocks)` once.
  - The plan popover's checkbox sends `blocks`, and `api.ExperimentBody` gains `blocks?: number`.
- [ ] **Step 4: Run to pass**, plus the engine guard set and `tests\test_aegis_studies.py tests\test_aegis_runs.py tests\test_lab_store.py tests\test_lab_query.py tests\test_aegis_lab_api.py`. Then `npm test`, `npm run build`, `tools\aegis_contracts.py` (regenerate, then `--check`) and lint.
- [ ] **Step 5: Commit** "Lab Phase 3: screening blocks in the pool, the job, the planner and the readers".

### Task 3: Lab tasks: a single-thread executor beside the job

**Files:**
- Create: `app/products/aegis/lab/tasks.py`.
- Modify: `app/products/aegis/lab/sources.py` `open_experiment` (:272): a `snapshot: Snapshot | None = None` keyword that reads at that snapshot instead of the latest.
- Modify: `app/products/aegis/api.py`:
  - `get_lab_tasks()` with `lru_cache(maxsize=1)`, injected as `LAB_TASKS` like `get_lab_cache` (:1302);
  - `POST /lab/{src}/tasks/{task_id}/cancel`;
  - `server.py`'s lifespan calls `get_lab_tasks().shutdown()` on exit.
- Test: create `tests/test_lab_tasks.py`.

**Interfaces:**
- Produces: `class Cancelled(Exception)`, and `class Checkpoint` with `__call__() -> None`. Each call yields the CPU (`time.sleep(0)`) and raises `Cancelled` when the task was cancelled.
- Produces: `@dataclass TaskStatus` with:
  - `id: str`, `key: tuple`, `label: str`;
  - `state: Literal["queued","running","done","cancelled","failed"]`;
  - `stage: int`, `stages: int`, `progress: float`;
  - `result: dict | None` (the latest finished stage's result, labelled `partial` until the last stage);
  - `error: str | None`, `started_at: str | None`, `finished_at: str | None`;
  - `sharing_cpu: bool` (true while an experiment job is running, read from one `runner.status` snapshot).
- Produces: `class LabTasks(max_results: int = 32)` with:
  - `request(key: tuple, label: str, stages: int, fn: Callable[[Checkpoint], Iterator[dict]]) -> TaskStatus`. It starts the task, joins a running or queued one with the same key, or returns the cached `done` result. `fn` yields one result per finished stage. One task runs at a time; others wait `queued`.
  - `status(task_id) -> TaskStatus`, `cancel(task_id) -> bool` and `shutdown() -> None`.
  - Finished results are cached in memory, at most `max_results` least recently used, and lost on restart (decision 6).
- Keys (review B5): a task **coalesces** on `(source identity, method, metric, scope, seed)` and its result is cached per `(that key, snapshot)`.
  - The source identity is `("exp", id, created_at)` for experiments, or `("opt", job_id, cells_done)` for `opt:` sources, whose snapshot is None.
  - At request time the task pins the source's current snapshot (`REGISTRY.open`), reads its frame at that snapshot (`open_experiment(..., snapshot=pinned)`, a new keyword) and releases it in a `finally`.
  - Per coalescing key at most one task runs and one waits: a request for a newer snapshot replaces the waiting one, never queues behind it. A running experiment's snapshot changes with every chunk, so without this a 2 s poll would queue a 180 s task per chunk.
  - The view answers with the newest finished result, labelled `snapshot X · current Y` when the source has moved on, and the task line for the one computing.
  - Importance ignores the filter (§7.3), so `filter_hash` is not part of either key.

- [ ] **Step 1: Write the failing tests:**
  - `test_one_task_runs_at_a_time`: a second key waits `queued` until the first finishes.
  - `test_same_key_joins`.
  - `test_done_result_is_cached`.
  - `test_cancel_keeps_finished_stages` (Review Focus 3): cancelled after stage 2 of 3 → `state == "cancelled"`, `result["stage"] == 2`, `result["partial"] is True`. A new request with the same key restarts and reaches `done`.
  - `test_snapshot_changes_coalesce` (Review Focus 2): ten requests for ten successive snapshots while the first runs. At no point are more than two tasks running or waiting for the key; the first's result carries its own snapshot; the last request's snapshot is the one computed next; the view's label reads `snapshot X · current Y` in between.
  - `test_failure_is_reported_not_raised`: `fn` raises → `state == "failed"` and `error` holds the message.
  - `test_tasks_never_start_a_pool`: monkeypatch `pool.Pool.__init__` to raise. A task still runs.
  - `test_cancel_route_answers_404_for_an_unknown_task`.
- [ ] **Step 2: Run them**: `PYTEST tests\test_lab_tasks.py`. Expected: FAIL.
- [ ] **Step 3: Implement** with a single `threading.Thread`, daemon, started lazily, and a `queue.Queue` of pending keys; status reads are served under a `threading.Lock`.
- [ ] **Step 4: Run to pass**, then lint.
- [ ] **Step 5: Commit** "Lab Phase 3: Lab tasks, one at a time beside the job".

### Task 4: Importance on the fine grid: the cohort, shares, intervals, floors, coverage and aliasing

**Files:**
- Create: `app/products/aegis/lab/analytics.py`.
- Create: `tests/test_lab_analytics.py`, holding the test helper `stat_frame(...)` below.
- Create: `tests/lab_stat_fixtures.py`, a plain helper module imported by the tests, with no `test_` prefix.

**Interfaces:**
- Produces: `@dataclass(frozen=True) Cohort`, with fields:
  - `paths: tuple[str, ...]`, `X: np.ndarray` (int16, n × d, value indices) and `B: np.ndarray` (values per parameter);
  - `Y: np.ndarray` (float64, block 0, the oriented metric);
  - `blocks: dict[int, np.ndarray]` (block → `Y` aligned to the same configurations; empty when K = 0);
  - `n: int` (rows used), `n_uniform_total: int` (uniform configurations of the space), `sampled_from: int | None` (set when the rows were subsampled to `IMPORTANCE_ROWS`, seeded);
  - `missing: dict[str, int]` (`invalid`, `failed`, `undefined`, counted over block 0 and every block);
  - `invalid_share: float` (`(space − valid) / space`);
  - `seed: int`.
- Produces: `cohort(frame: TrialFrame, *, metric: str, scope: str, seed: int) -> Cohort`.
  - The rows are uniform (`design == "uniform"`), of the current space (every row of one experiment in Phase 3; reused parent rows are Phase 4), and unfiltered.
  - Block 0 decides inclusion. A configuration is in the cohort when its block-0 row and every block row are `ok` with a finite metric; the others are counted in `missing`.
  - The metric is oriented so larger is better (`max_drawdown` negated).
- Produces: `fine_shares(X, Y, B) -> tuple[np.ndarray, np.ndarray]`, returning `(S_adj[d], J_adj[d, d])`.
  - It uses the spec's count-weighted η² with `S_adj = max(0, S − (B_i − 1)/(N − B_i) · (1 − S))`, applied to pairs with `B_i · B_j` cells. Group means are computed by `np.bincount`.
- Produces: `incremental(S, J) -> np.ndarray`, with `Δ[i, j] = J[i, j] − S[j]`, and `interaction(S, J)` (`I`, display only).
- Produces: `intervals(fn, X, Y, *, b: int, seed: int, checkpoint) -> tuple[np.ndarray, np.ndarray]`: the 90 % bounds of `fn` over `b` row resamples, **re-centred on the point estimate**: `[θ̂ + q₀.₀₅* − mean*, θ̂ + q₀.₉₅* − mean*]`. An adjusted share's bootstrap distribution centres on the raw estimate, so plain percentiles are biased upward by about the degrees of freedom over n (review B2; decision 19).
- Produces: `floors(fn, X, Y, *, p: int, seed: int, checkpoint, families: dict[str, np.ndarray]) -> Floors{share: np.ndarray, family: np.ndarray}`.
  - `share` is each share's 95th percentile over `p` permutations of `Y`: a display tick.
  - `family` is the **family-wise** floor by max-T (review B1; decision 18). Each permutation's shares are standardized by their own null mean and SD over the `p` permutations; `t` is the 95th percentile of the per-permutation maximum standardized share within the family; a share's floor is `mean + t · sd`. It still grows with a parameter's bins.
  - The families are the fine mains, the fine `Δ_{i|j}` (all ordered pairs), the own-direction coarse `Δ_{i|jk}^c`, and each block's mains.
  - "Detected" (§7.3) means the point estimate exceeds its family floor.
- Produces: `coverage_label(X, B, n) -> list[str]`, giving `"Measured"` or `"Insufficient coverage"` per §7.3.
- Produces: `pair_quality(X, B) -> (coverage[d, d], balance_tvd[d, d])`.
- Produces: `cramers_v(X, B) -> np.ndarray` (d × d), computed over **every scheduled uniform configuration**, not over the cohort (so outcome-dependent missingness never shows as aliasing; case 16), and `aliased(V) -> list[tuple[int, int]]` (V > `ALIAS_V`).
- Produces: `block_mains(cohort, *, seed, checkpoint) -> dict[int, (S, lo, hi, floor)]`, one bootstrap of `BOOTSTRAP_B` per block.
- Test helper `stat_frame(*, d: int, values: int | list[int], n: int = 5_000, seed: int, y: Callable[[np.ndarray], np.ndarray], blocks: dict[int, Callable] | None = None, valid: Callable | None = None, design: str = "uniform", undefined: Callable | None = None) -> TrialFrame`.
  - `y` takes value-normalised inputs in [0, 1] (n × d) plus the rng's noise. Built on `tests/test_lab_query.py::synthetic_frame`'s vectorised writer, it puts block `b`'s rows beside block 0, drops invalid cells from `space − valid`, and marks `undefined` rows' metric as null.

- [ ] **Step 1: Write the failing tests** (the fine-grid half of the sixteen cases, statuses asserted in Task 5):
  - `test_strong_first_order_is_detected` (case 1): `x₁` lower > its floor; every noise `S_i` upper < `THETA_MIN`.
  - `test_xor_has_mains_below_the_floor_and_a_large_increment` (case 2): `Δ_{1|2}` upper > 0.2.
  - `test_aliased_inputs_share_credit` (case 4): `aliased(V) == [(0, 1)]`.
  - `test_uneven_sampling_flags_confounded_squares` (case 5): the (x₁, x₂) aggregate matrix flags `confounded`, and `Δ_{1|2}` upper > `THETA_MIN`.
  - `test_sparse_values_are_insufficient_coverage` (case 6): 40 values, 8 present → `"Insufficient coverage"`.
  - `test_one_block_regime_shows_a_block_range` (case 8): block 2's `S₁` lower > 0.5, blocks 1, 3 and 4 have upper < `THETA_MIN`.
  - `test_coarse_cancellation_keeps_the_fine_share_detected` (case 11, fine half).
  - `test_refinement_rows_excluded`: adding 2,000 `design == "adaptive"` rows changes no share.
  - `test_interval_coverage_known_variance`: for `Y = a·x₁ + ε` with the true `S₁` computed analytically, the 90 % interval covers it in ≥ 85 of 100 seeds.
  - `test_permutation_floor_scales_with_bins`: the per-share and the family floor at `B = 20` exceed those at `B = 4` on the same `n`.
  - `test_family_floors_control_false_detections`: pure noise, d = 20, 5,000 rows, seeds 1–20: at most 4 seeds show any detection in the mains or the `Δ` family (≈ 2 expected); the rate is printed. Per-share floors flag about 7 of 20 parameters per seed (review B1).
  - `test_recentred_intervals_cover_the_point_estimate`: for every share the interval contains `θ̂`, and on pure noise the mains' intervals contain 0.
  - `test_cohort_subsamples_to_the_cap`: 60,000 rows → `n == 50_000`, `sampled_from == 60_000`, and the same seed gives the same rows.
- [ ] **Step 2: Run them**: `PYTEST tests\test_lab_analytics.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the functions above. Bootstrap and permutation call `checkpoint()` between resamples.
- [ ] **Step 4: Run to pass**, then lint.
- [ ] **Step 5: Commit** "Lab Phase 3: importance on the fine grid with its intervals, floors, coverage and aliasing".

### Task 5: The coarse decomposition, the residual, availability, and the recommended statuses (the sixteen cases)

**Files:**
- Modify: `app/products/aegis/lab/analytics.py`.
- Test: `tests/test_lab_analytics.py` (append).

**Interfaces:**
- Consumes: Task 4.
- Produces: `coarse_bins(X, B, q=COARSE_BINS) -> np.ndarray`, which bins each parameter's value indices into `q` quantile bins.
- Produces: `@dataclass Coarse` with `S: d`, `J: d × d`, `Delta3: (d, d, d)` own-direction increments `Δ_{i|jk}`, `R: float`, and `lo` / `hi` intervals for `R`. Also `triples_top(Coarse, k=TRIPLE_TOP)`.
- Produces: `coarse(Xq, Y) -> Coarse`. One pass by `np.bincount` over group keys gives the mains, every pair and every triple, and `R = 1 − ΣS − ΣI_pair − ΣI_triple` on the same grid. Every term is the **bias-adjusted, unclamped** share; clamping at 0 is for display only (review B2: clamping biased `R` from 1.00 to 0.76 on pure noise at d = 20).
- Produces: `coarse_intervals(Xq, Y, candidates: list[int], *, b=COARSE_BOOTSTRAP_B, seed, checkpoint)`. It bounds `R`, and every triple containing a candidate in all three directions, re-centred as `intervals` is.
- Produces: `coarse_floors(Xq, Y, *, p=COARSE_PERMUTATION_P, seed, checkpoint)`.
- Produces: `availability(cohort, V, R_hi, R_lo) -> Availability{available: bool, reason: str | None, reasons: list[str], hint: str | None}`. The first failing reason wins, in this order:
  1. `no uniform rows of the current space`;
  2. `aliased inputs`;
  3. `inputs are not a product design ({p} % of the grid is invalid)`, with the hint `freeze or narrow the constrained ranges`;
  4. `{m} of {N} configurations have no finite {metric} ({k} invalid, {f} failed, {u} undefined)`, with the hint `choose a metric defined everywhere (net_pnl, max_drawdown, trade_count, exposure) or retry the failed trials`;
  5. `decomposition inconsistent`, when `R` upper < `RESIDUAL_INCONSISTENT`.

  The panel prints `empirical deprioritization unavailable: <reason>`.
- Produces: `veto(R_lo) -> str | None`. When `R_lo > RESIDUAL_VETO` it returns `structure not captured by mains, pairs and triples: deprioritization unsafe`, and the panel also shows the warning `unexplained share high: noise or higher-order structure`.
- Produces: `statuses(result) -> list[ParameterStatus{path, status, reason, flags: list[str], label, proposable: bool, failing: str | None}]`. The status is the first rule that holds, in this order (decision 21):
  1. `Insufficient coverage · unresolved` (label not `Measured`), listed last with its coverage;
  2. `Deprioritized · proposable`: the rule is available, there is no veto, and §7.4a conditions 1–5 hold (condition 1 on block 0 and every block; with `K = 0`, block 0 only, decision 4). It comes before detection because §7.4a's conditions are practical bounds: a share that is detected but negligible (upper < `THETA_MIN`) stays proposable (review B1);
  3. `Investigate · period-dependent`: blocks exist, some block's `S_i` exceeds that block's family floor with upper > `THETA_MIN`, and another block's upper is < `THETA_MIN`;
  4. `Active · detected`: block 0's fine `S_i` exceeds its family floor;
  5. `Investigate · interaction not ruled out`: some `Δ_{i|j}` exceeds its family floor **and** its upper is > `THETA_MIN` ("not ruled out" reads the practical bound too);
  6. `Investigate · three-way effect not ruled out`: some own-direction `Δ_{i|jk}^c` exceeds its family floor and its upper is > `THETA_MIN`;
  7. otherwise `Active · not detected`.

  `failing` is set on **every** non-proposable parameter: the availability reason when the rule is unavailable, else the veto, else the first failed §7.4a condition as `not proposable: condition <n> (<what>)` (review B4).

  Flags: `aliased · credit shared with <other path>` for every aliased pair member. `proposable` is true only for rule 2. Condition 6, the operator's confirmation, is Phase 4.
- Produces: `evidence_scope(document, cohort) -> dict` with `strategy_hash`, `data identity`, `ranges`, `sampler`, `blocks`, `search_space.hash` and `snapshot`. Also `compare_scope(evidence: dict, current: dict) -> str`, which returns `"current"` or `"stale: <field> changed"` (case 9).

- [ ] **Step 1: Write the failing tests.** These are the sixteen §20 cases on `stat_frame`: 8–20 parameters, 5,000 uniform rows (20,000 for cases 1 and 13, decision 20), 4 blocks only where stated, `seed=1`. Each asserts the exact status and reason strings above:
  - case 1 `test_case01_strong_first_order` (20,000 rows): `x₁` `Active · detected`; every noise parameter `Deprioritized · proposable`. Its companion `test_case01_at_5000_rows_proposes_nothing_honestly` asserts that at 5,000 rows the noise parameters are `Active · not detected` with `failing` naming condition 3: a noise triple increment's null SD is about √(2·48)/n, so its upper bound passes `THETA_MIN` too often at 5,000 rows (review B3).
  - case 2 `test_case02_xor`: both `Investigate · interaction not ruled out`.
  - case 3 `test_case03_three_way_only`: all three `Investigate · three-way effect not ruled out`.
  - case 4 `test_case04_aliased`: flags `aliased · credit shared with …` on both; neither proposable; availability reason `aliased inputs`.
  - case 5 `test_case05_uneven_sampling`: the generator is `3·x₂ + x₁·(x₂ − ½)` (centred, so `x₁` has no main effect, review B4), with `x₃` drawn depending on `x₁` so the squares are really confounded. The (x₁, x₂) squares are flagged `confounded`, `x₁` is not proposable, and condition 2's check on the pair (x₁, x₂) fails (`Δ_{1|2}` upper > `THETA_MIN`), whatever condition `failing` names first.
  - case 6 `test_case06_sparse_coverage`: `Insufficient coverage · unresolved`, last in the list.
  - case 7 `test_case07_pure_noise`: every status `Active · not detected`, the veto text above, and the warning `unexplained share high: noise or higher-order structure`.
  - case 8 `test_case08_one_block_regime`: `x₁` `Investigate · period-dependent`; never proposable.
  - case 9 `test_case09_range_change`: the wide-range evidence's `compare_scope` on the narrow child reads `stale: ranges changed`, and the child's fresh `S₁` is below its floor.
  - case 10 `test_case10_correlated_inputs`: a `valid` constraint `x₂ ≥ x₁ + 2`; availability reason `aliased inputs`; no parameter proposable.
  - case 11 `test_case11_coarse_bin_cancellation`: `S₁^c ≈ 0` and `x₁` `Active · detected`.
  - case 12 `test_case12_higher_order`: four-way parity; the veto is raised, with `structure not captured by mains, pairs and triples: deprioritization unsafe`.
  - case 13 `test_case13_own_direction_triple` (20,000 rows): `x₂` `Deprioritized · proposable`, although `Δ_{1|23}^c` > 0.5.
  - case 14 `test_case14_pairwise_independent_jointly_dependent`: availability reason starts `inputs are not a product design`, while the fine lists still have entries.
  - case 15 `test_case15_weak_constraint`: not aliased, with reason `inputs are not a product design (2 % of the grid is invalid)` and the hint.
  - case 16 `test_case16_outcome_dependent_missingness`: reason `1,240 of 5,000 configurations have no finite profit_factor (0 invalid, 0 failed, 1,240 undefined)`. The descriptive note reads `on 3,760 of 5,000 configurations; missingness may bias`. With `net_pnl` the rule is available.

  Also `test_rule_unavailable_when_aliased_or_adaptive` (adaptive-only rows → `no uniform rows of the current space`), `test_stale_then_rescreen_refreshes_evidence` (a fresh uniform cohort on the child is `current`), `test_recentred_r_interval_contains_one_on_pure_noise` (d = 20) and `test_failing_is_set_on_every_non_proposable_parameter`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** The fixture's generator constants (the value counts per parameter and the noise σ) are chosen in `lab_stat_fixtures.py` once so that the spec's expectations hold at `seed=1`. They are not tuned per assertion, and each choice is commented with the reason. The review found these traps; the fixtures respect them:
  - case 11: `sin(8π·x)` is zero on every grid point when `B₁` is 5 or 9, so `B₁ ≥ 17`;
  - case 10: Cramér's V passes 0.3 only for `B ≤ 8` (`B = 10` gives 0.27), so `B = 8`;
  - case 16: assert the fixture's own undefined count at seeds 2 and 3 (`1,240` holds at seed 1 only);
  - case 8: blocks whose Y is 0 carry ε, and a block with `Var(Y) = 0` reports `not measured in block <b>`;
  - case 9: the child's Y is computed on the parent's scale, not on [0, 1] re-normalised to the child's range.

  Strings: `{p} %` prints an integer when ≥ 1 and one decimal below (`0.4 %`); counts use thousands separators; `N` is the scheduled uniform configurations, not the space size.
- [ ] **Step 4: Run to pass, three seeds.** The sixteen cases also run at `seed=2` and `seed=3`, parametrized; a case flipping on another seed is a finding for R3.5, never hidden. Then lint.
- [ ] **Step 5: Commit** "Lab Phase 3: the coarse decomposition, availability and the recommended statuses (the sixteen cases)".

### Task 6: The staged importance task and the `importance`, `interactions` and `triples` views

**Files:**
- Modify: `app/products/aegis/lab/analytics.py`: `importance_stages(frame, *, metric, scope, seed, checkpoint: Checkpoint) -> Iterator[dict]`.
- Modify: `app/products/aegis/lab/sources.py`: `VIEWS`, `_REQUIRED`, `COLUMNS_FOR` branches, and dispatch for `exp:` and `opt:`.
- Modify: `app/products/aegis/api.py`: `QueryRequest.view` gains `importance`, `interactions` and `triples`, `QueryRequest` gains `seed: int = 1` (it is `extra="forbid"`), and the route passes `LAB_TASKS`.
- Test: `tests/test_lab_analytics.py` (append) and `tests/test_aegis_lab_api.py` (append).

**Interfaces:**
- Consumes: Tasks 3–5.
- The task's `fn` opens its own frame with `open_experiment` (or one `opt_frame` snapshot), computes with `importance_stages(..., checkpoint=cp)`, and calls `REGISTRY.release(handle)` in a `finally`. It never holds `LOCKS.read` across compute (Global Constraints).
- Produces: the three stages:
  1. Fine mains and pairs, with bootstrap 200 and null 200, delivered first within `FINE_STAGE_BUDGET_S`.
  2. The coarse point estimates (every triple) and the per-block mains with their intervals.
  3. The coarse bootstrap `B_c = 50` for `R` and the candidates' triples.

  Each stage's dict carries everything the panel prints: shares, intervals, floors, labels, coverage, `n`, `N`, `sampled_from`, the block range per parameter, `availability`, `veto`, `statuses`, the constants used, `seed`, `snapshot`, `stage`, `stages` and `partial`.
- Produces the views:
  - **`importance`** answers `{task: TaskStatus, importance: <latest stage> | null}` and polls through `LabTasks.request`. It ignores the filter, and its basis line reads `computed on n uniform trials of N; adaptive rows excluded; ignores the active filter`.
  - **`interactions`** reads the latest result: every pair with `J`, `Δ_{i|j}`, `Δ_{j|i}`, `I`, intervals, floor, coverage, balance and `unresolved`. Unresolved pairs come last, sorted by `max(S_i upper, S_j upper)` then lowest coverage.
  - **`triples`** gives the top 20 by `Δ^c`, with intervals where stage 3 has them.
- Columns: `importance`, `interactions` and `triples` load `BASE` + `design` + `pass` + every path + the metric column per scope.

- [ ] **Step 1: Write the failing tests:**
  - `test_importance_stages_arrive_in_order`: stages 1, 2, 3 with `partial` true, true, false.
  - `test_stage_results_carry_their_timings`: each stage's dict has `elapsed_s`. The budgets are measured by `lab_benchmark.py analytics` (Task 12), never asserted in a unit test.
  - `test_importance_view_starts_then_answers` (API): the first poll is `queued`, `running` or `done` (a small fixture may finish at once), and a later poll is `done` with stage 3.
  - `test_importance_ignores_the_filter`: the same answer with and without `filter.ranges`.
  - `test_interactions_view_lists_every_pair`: 45 at d = 10.
  - `test_importance_on_an_optimization_grid` (Review Focus 5): an `opt:` source answers with the period uncertainty `not measured: no screening blocks`.
  - The extended `test_query_loads_projected_columns_only` covers the three views.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass**, then `tests\test_lab_query.py tests\test_aegis_lab_api.py` and lint.
- [ ] **Step 5: Commit** "Lab Phase 3: the staged importance task and the importance, interactions and triples views".

### Task 7: Neighbourhoods, the four robustness categories, rankings and the candidate card

**Files:**
- Create: `app/products/aegis/lab/neighbours.py` and `app/products/aegis/lab/robustness.py`.
- Modify: `lab/sources.py` and `api.py`: the views `neighbourhood` and `robustness`, whose columns load `pos.<k>` (layout 2), or every path for legacy sources; `QueryRequest` gains `trial: str | None` (a trial id, `exp:<id>#<n>`).
- Test: create `tests/test_lab_robustness.py`.

**Interfaces:**
- Consumes: Task 0's `FrameIndex.codes`.
- Produces: `position_codes(frame, index) -> np.ndarray`, mapping each block-0 row to an int64 hash of its positions (the index's codes: `pos.<k>` for layout 2; value indices for legacy and `opt:`). Also `neighbourhood(frame, trial_no, *, r=NEIGHBOUR_R, m: int | None = None) -> Neighbourhood`, where `m` defaults to `NEIGHBOUR_M_GRID` on exhaustive grids and `NEIGHBOUR_M_SAMPLED` otherwise.
  - Fields: `trial_no`, `probes` (≤ 840 at d = 20, m = 2), `valid`, `tested`, `coverage`, `trials`, `values`, `p25`, `p75` and `iqr`.
  - Lookups go by hash (`np.searchsorted` on sorted codes), never O(n²).
- Produces: `tau(frame, metric, scope, tolerance) -> float`, computed as `tolerance × (P90 − P10)` exactly as `analysis.py:508-511`.
- Produces: `category_a(nb, value, tau, d) -> Category`, `category_b(frame, trial_no, axes: list[str], tau) -> Category`, `category_c(folds: list[FoldEvidence] | None, blocks: list[BlockEvidence]) -> tuple[Category, Finding | None]` and `category_d(replays: dict[str, ReplayEvidence] | None) -> Category`.
  - `Category` has `{name, resolved: bool, classification: str | None, reason: str | None, inputs: dict}`, with exactly the §7.6 table's classifications and unresolved reasons.
  - `FoldEvidence` is `{bars, trades, net_pnl, max_drawdown}`; `BlockEvidence` and `ReplayEvidence` are likewise.
  - In Phase 3, C receives no folds and D no replays (decision 12), so the card reads `unresolved · selection-period only` (with the blocks' `selection-period consistency` finding when blocks exist) and `no replay yet (stage 2)`.
- B's axes are the top `REGION_AXES` parameters of the latest importance result for the snapshot. With none computed, B is unresolved: `importance not computed for this snapshot`. The tolerance is the experiment's (`ExperimentDocument.tolerance`); an `opt:` source uses `0.15`, labelled `default tolerance 0.15`.
- Produces: `candidate_card(frame, trial_no, *, metric, scope, tolerance, axes) -> dict` with the four categories, which were tested and which remain unknown, never summed. Also `rankings(frame, *, metric, scope, tolerance, k=20) -> {peak: [trial_id], robust: [trial_id], disagree: bool, stable: trial_id | None}`, where `robust` is lexicographic over the resolved categories and unresolved categories sort last.

- [ ] **Step 1: Write the failing tests** (spec §20 robustness list):
  - `test_unresolved_when_untested`: A with coverage 0.2 is `untested surroundings (coverage 0.2 of 0.5)`.
  - `test_fully_tested_corner_resolves`.
  - `test_isolated_peak_vs_stable_local`.
  - `test_sparse_region_never_reported_as_local`: an LHS-only surface where B is resolved and A unresolved; the card never says `local`.
  - `test_isolated_peak_needs_coverage`.
  - `test_constant_per_unit_time_across_folds_is_consistent`: folds of 100, 300 and 900 bars with the same net P&L per 1,000 bars.
  - `test_blocks_alone_leave_c_unresolved_and_cannot_change_it`.
  - `test_negative_and_zero_baselines_resolve_not_profitable`.
  - `test_sub_year_replays_resolve_d_without_mar`.
  - `test_negative_base_replay_is_not_profitable_at_base`.
  - `test_rankings_shown_side_by_side`: the two rankings disagree on a spike-and-plateau fixture, `stable` names the plateau trial.
  - `test_four_category_states`.
  - `test_every_classification_carries_its_inputs`.
  - `test_neighbourhood_probes_by_hash`: a counting stub over `np.searchsorted` proves ≤ 840 lookups at d = 20, m = 2 and no pairwise scan. The 150 ms budget is measured by `explore` (Task 12).
  - `test_legacy_experiment_neighbourhood_from_values` (Review Focus 5).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass**, then lint.
- [ ] **Step 5: Commit** "Lab Phase 3: neighbourhoods, the four robustness categories and the candidate card".

### Task 8: Pareto, the exact parallel sample and convergence

**Files:**
- Create: `app/products/aegis/lab/pareto.py`, `app/products/aegis/lab/parallel.py` and `app/products/aegis/lab/convergence.py`.
- Modify: `lab/sources.py` and `api.py`:
  - views `pareto` and `convergence`;
  - `QueryRequest` gains `objectives: list[str] | None` (2 or 3) and `parallel_mode: Literal["bundles", "sample"] = "bundles"` (decision 8: the matrix's `mode` defaults to `"exact"`, so it is not reused).
- Test: create `tests/test_lab_pareto.py`; append to `tests/test_lab_query.py`.

**Interfaces:**
- Produces: `front_2d(a, b) -> np.ndarray` (indices, sort plus sweep) and `front_3d(a, b, c) -> np.ndarray` (sort by the first objective plus a block-nested skyline). Both work on oriented values, larger better.
- Produces: `pareto_view(frame, flt, *, objectives, scope) -> {front: [trial_id], front_size, dominated, density: {bins: 64, counts: [[int]]}, sampled: bool, points}`.
- Produces: `sample_view(frame, flt, *, axes, metric, k=PARALLEL_MAX_LINES, seed) -> {lines, sampled_from, strata: 10}`, stratified by metric decile. Its basis reads `Sampled n of N (stratified by decile of <metric>)`.
- Produces: `convergence_view(frame, flt, *, metric, scope) -> {best: [[trial_no, value]], robust: [{batch, median, p25, p75}], provisional}`.
  - `best` is best-so-far by `trial_no`, at most `CONVERGENCE_MAX_POINTS`, thinned evenly.
  - `robust` is per `CONVERGENCE_BATCH`: the median of the neighbourhood P25 of the batch's top `CONVERGENCE_TOP`, with an IQR band. It is never extrapolated.

- [ ] **Step 1: Write the failing tests:**
  - `test_front_2d_matches_brute_force` and `test_front_3d_matches_brute_force`, each over 50 random seeds of 2,000 points with ties.
  - `test_pareto_respects_orientation`: `max_drawdown` minimized.
  - `test_front_size_capped_with_a_label`: a 5,000-point front → 2,000 drawn, `sampled: true`. The 800 ms budget is measured by `explore` (Task 12).
  - `test_sample_view_is_stratified_and_seeded`.
  - `test_parallel_mode_default_is_bundles`.
  - `test_convergence_is_best_so_far_and_labelled_provisional_while_running`.
  - `test_counts_identical_across_new_views`: `scope` equal for `pareto`, `parallel` (both modes), `convergence` and `counts` on the same frame and filter.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass**, then the extended projection test and lint.
- [ ] **Step 5: Commit** "Lab Phase 3: Pareto, the exact parallel sample and convergence".

### Task 9: The UI data layer for the new views and tasks

**Files:**
- Modify: `app/products/aegis/ui/src/results.ts`:
  - `LabQueryView` (:420) gains `importance | interactions | triples | neighbourhood | robustness | pareto | convergence`;
  - new payload interfaces `LabImportance`, `LabInteractions`, `LabTriples`, `LabNeighbourhood`, `LabRobustness`, `LabPareto` and `LabConvergence`;
  - `LabTask`, mirroring `TaskStatus`;
  - `LabParallel` gains `lines?` and `sampled_from?`;
  - `LabQueryBody` gains `objectives?`, `parallel_mode?`, `trial?` and `seed?`.
- Modify: `api/client.ts`: `labCancelTask(src, id)`.
- Modify: `lab/labQuery.ts`: `optBody` prefixes `objectives` and `axes`; `RANKED` gains `pareto`.
- Modify: `lab/labStore.ts`: `tab: LabTab` in the state, and `SET_TAB` (decision 13).
- Create: `lab/labTask.ts`, with `taskLine(task: LabTask, now: number) -> string` (e.g. `Importance · stage 1 of 3 · sharing CPU with the running job`) and `pollDelay(task) -> number | null` (2,000 ms while running).
- Test: `lab/labTask.test.ts`, `lab/labQuery.test.ts` (append) and `lab/labStore.test.ts` (append: `SET_TAB` keeps filter, selection and pins).

- [ ] **Step 1: Write the failing vitest cases** listed above, plus `labQuery.test.ts::optBody prefixes objectives`.
- [ ] **Step 2: Run them** with `npm test -- src/lab`. Expected: FAIL.
- [ ] **Step 3: Implement**, moving `OptLabPage.tsx`'s local tab state (:37) into the store.
- [ ] **Step 4: Run to pass**: `npm test`, `npm run build` and `tools\aegis_contracts.py --check`.
- [ ] **Step 5: Commit** "Optimization Lab: the data layer for the analytics views and Lab tasks".

### Task 10: Screen B: the Pareto, Importance, Interaction and Robustness tabs, and the candidate card

**Files:**
- Create in `app/products/aegis/ui/src/lab/`:
  - `ParetoView.tsx` and `paretoModel.ts`: a canvas scatter plus the density bitmap and the front;
  - `ImportanceView.tsx` and `importanceModel.ts`: a ranked list with the three uncertainties side by side (bootstrap whiskers, block range, floor tick), labels, the availability line, the veto, the caveat text verbatim and the task line;
  - `InteractionMatrix.tsx`: pairs as a canvas matrix of `J` with `Δ` on hover, coverage hatched, and the unresolved list below;
  - `RobustnessView.tsx`: the peak and robust rankings side by side, with the disagreement named;
  - `CandidateCard.tsx` and `candidateModel.ts`, in the rail's `#lab-selected`, replacing `TrialCard`'s "temporal consistency: Phase 3" line: four categories, tested or unknown, the reason and the inputs.
- Modify: `LabCenter.tsx`: replace the `NotBuilt` branches (:162-185) and the `opt` importance branch; the robustness tab label becomes "Robustness (A–D)".
- Modify: `IntelligenceRail.tsx` (`#lab-selected` uses `CandidateCard`) and `charts/canvas.ts`: `ScatterHit` (point hit-testing over ≤ 2,000 points), `drawWhisker` and `niceTicks(domain, count)`. The file stays ≤ 800 lines.
- Modify: `styles.css`: `lab-pareto`, `pareto-toolbar`, `lab-importance`, `importance-row`, `lab-interactions` and `lab-robustness` (the naming rule of the Lab section).
- Test: `paretoModel.test.ts`, `importanceModel.test.ts` (labels, ordering with unresolved last, caveat text), `candidateModel.test.ts` (`candidateCard.testedUnknown`: every category's tested or unknown state, and the reason shown for unresolved ones) and `charts/canvas.test.ts` (`ScatterHit`, `niceTicks`).

**Interfaces:**
- Consumes: Task 9.
- Element ids for the walk:
  - Pareto: `#lab-pareto`, `#lab-pareto-basis`, `#lab-pareto-front-size`.
  - Importance: `#lab-importance`, `#lab-importance-row-<index>`, `#lab-importance-availability`, `#lab-importance-task`.
  - The rest: `#lab-interactions`, `#lab-robustness-peak`, `#lab-robustness-robust`, and `#lab-candidate-<A|B|C|D>` with `data-state="resolved|unresolved"`.

- [ ] **Step 1: Write the failing vitest cases.**
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** with the Phase 2 per-panel pattern (`viewKey`, `seq` / `asked`, `answered()`, `LabError` with Retry, `data-loading`); logic stays in the pure models.
- [ ] **Step 4: Run to pass**: `npm test` and `npm run build`. `wc -l charts/canvas.ts` must be ≤ 800.
- [ ] **Step 5: Commit** "Optimization Lab: Screen B's analytics tabs and the candidate card".

### Task 11: Screen E: Parameter Families

**Files:**
- Create in `app/products/aegis/ui/src/lab/`:
  - `FamiliesPage.tsx`, `ScopeBreadcrumb.tsx` (completed → valid unique → filtered → brushed) and `Trellis.tsx` (the top pairs by `interactions` priority, each an aggregated matrix ≤ 16 × 16 with `n` and cells `n < 30` hatched and excluded);
  - `NeighbourhoodMap.tsx`: the aggregate median matrix with `n`, IQR rings for the top quartile of IQRs, untested hatched, and the selected candidate's A and B states printed;
  - `familiesModel.ts`.
- Modify: `OptLabPage.tsx` (`families` renders `FamiliesPage` and leaves `PLACEHOLDERS`), `ParallelCoords.tsx` (an aggregated / exact toggle `#lab-parallel-mode` driving `parallel_mode`, with the sampled basis line), `ParameterCatalog.tsx` (a `families` mode that groups by indicator id and side), and `IntelligenceRail.tsx` (a compact `ConvergenceChart`, decision 10).
- Create: `ConvergenceChart.tsx` and `convergenceModel.ts`.
- Test: `familiesModel.test.ts`, `convergenceModel.test.ts` and `parallelBundles.test.ts` (append: the sample-mode basis line).

- [ ] **Step 1: Write the failing vitest cases.**
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run to pass**: `npm test`, `npm run build`, canvas ≤ 800 lines.
- [ ] **Step 5: Commit** "Optimization Lab: Screen E, Parameter Families".

### Task 12: Walk items 111, 112 and 124, the existing items Phase 3 changes, and `lab_benchmark.py analytics`

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py`:
  - `LAB_ITEMS` gains `(111) a spike and a plateau are labelled …`, `(112) Parameter Families …` and `(124) a candidate card shows four categories …` before governance.
  - The governance item counts 15 (6272/6274/6279), is registered at `self.item(first + 15, lab_governance)` (was `first + 12`, near :6281), and the docstring and `run_lab` say 16.
  - `LAB_PLACEHOLDER_VIEWS` (:230) drops `families` (item 105 asserts its length), and `VariableIntelligence.tsx:32`'s "screening experiments arrive in Phase 3" names Phase 4.
  - Item 105 no longer expects the interactions / pareto / robustness / families placeholders (5474-5484, 5506-5508); item `RF2/3` reads the importance task line, not "no report yet" (5914-5919).
- Modify: `tests/products/aegis/lab_benchmark.py`:
  - an `analytics` subparser and `new_record` branch;
  - `TRACK_A_BUDGETS_MS` gains `pareto: 800` and `neighbourhood: 150`, and `explore`'s `_operations` times the `pareto` view (two objectives) and a seeded trial's `neighbourhood` view over HTTP like the Phase 2 rows;
  - `TRACK_ANALYTICS_LIMITS = {"importance_task_s": 180.0, "fine_stage_s": 30.0}`;
  - `_evaluate_analytics`.
- Test: `tests/test_aegis_lab_benchmark.py` (append `test_analytics_record`).

**Interfaces:**
- `analytics` keeps case A's experiment running back to back (`_run_case` in a loop) until a thread that started the importance task on the 1M fixture has polled it to done, so the whole task runs beside a job; only the overlap is measured. The record states that the 1M fixture has 10 parameters and no blocks, so per-block mains and the d = 20 cost are not measured here. It records:
  - `task_s` and `fine_stage_s`;
  - `throughput_loss = 1 − loaded.trials_per_s / quiet.trials_per_s`, the quiet run being case A alone;
  - `pareto` and `neighbourhood` timed over HTTP, 20 runs.

- [ ] **Step 1: Write the items and the record test.**
  - **Item 111:** the bench experiment's Robustness tab shows the peak and robust rankings. The top peak trial's card reads A `isolated peak` or `untested surroundings (coverage c of 0.5)`, and a plateau trial reads `stable local`, each with its inputs.
  - **Item 112:** Parameter Families on the bench:
    - search finds a path;
    - the trellis shows `n` per cell;
    - maximize and Esc;
    - a square's `n` equals the drill-down table's total (count-preserving).
    - 10 parameters (decision 11).
  - **Item 124:** a candidate card shows `#lab-candidate-A..D` with `data-state`. C reads `unresolved · selection-period only` and D `no replay yet (stage 2)`, each with its reason.
  - **The record test:** `test_analytics_record`.
- [ ] **Step 2: Run** `PYTEST tests\test_aegis_lab_benchmark.py`; then `npm run build`, the scratch worker, and the walk with `--only lab` → `16/16`, page errors 0.
- [ ] **Step 3: Run `lab_benchmark.py analytics`** against the scratch worker started with `-Workers 10`. Record `evaluate()`. A miss is a finding, never a re-baseline.
- [ ] **Step 4: Lint.**
- [ ] **Step 5: Commit** "Optimization Lab walk: items 111, 112 and 124; lab_benchmark analytics".

### Task 13: Phase checks, independent QA of the statistics, and the R3.5 hand-off

- [ ] **Step 1: Checks.** The whole Aegis scope; the core-scope `test_architecture.py::test_dependency_directions` and `test_pytest_scope.py::test_every_module_in_this_repository_declares_one_owner` under the worktree `PYTHONPATH`; `npm test`; `npm run build`; contracts `--check`; lint; both identity scripts `identical`; the engine guard set (14 golden keys); and `git status --short` clean. Take the product-store manifest before Step 2 and after Step 3 (script and format of the R3 note), and diff them: the diff must be empty.
- [ ] **Step 2: Track A again** (`lab_benchmark.py explore --trials 1000000`) on a freshly restarted scratch worker: Task 0's targets met, or each miss recorded. Then `lab_benchmark.py analytics` as in Task 12.
- [ ] **Step 3: The Lab walk:** `16/16`, page errors 0, at both widths, with screenshots.
- [ ] **Step 4: Independent QA** (mandatory, §16 R3.5), by a reviewer who wrote none of Tasks 4–6:
  - re-derives each of the sixteen cases' expected statuses and reasons from §7.3–7.4a and §20 alone, before reading the tests;
  - re-runs `tests\test_lab_analytics.py tests\test_lab_blocks.py tests\test_lab_robustness.py tests\test_lab_pareto.py` and the engine guard set;
  - checks `test_interval_coverage_known_variance` by its own simulation;
  - injects one estimator fault of its choosing (an off-by-one in the bias correction, or a swapped triple direction) and confirms a test fails;
  - records the verdict.
- [ ] **Step 5: Write `docs/superpowers/plans/2026-10-29-aegis-optimization-lab-v2-phase3-r35.md`.** It holds:
  - the checks and their counts;
  - the sixteen cases with their statuses and reasons at seeds 1–3;
  - the importance task's measured stage times beside a running job, and the throughput loss;
  - the Track A record before and after Task 0;
  - the walk report path with `lab_timings_ms` and `lab_heap_mb`;
  - the QA verdict;
  - the product-store manifest diff;
  - the scratch root size;
  - the decisions below, each with its reasoning;
  - the open questions for Randall.
- [ ] **Step 6: Commit** the note and the records; hand over for checkpoint **R3.5**.

## Self-review notes

- **Spec coverage**, from the Phase 3 row of §11:
  - blocks with warm-up and the scoring mask: Tasks 1 and 2;
  - `design`-based row selection: Task 4 (`cohort`);
  - importance with the three uncertainties: Task 4;
  - fine shares and `Δ`: Task 4;
  - the coarse decomposition, residual veto and candidate-only triple intervals: Task 5;
  - Cramér's V aliasing disabling the rule: Tasks 4 and 5;
  - the four robustness categories, per-unit-time rules, rankings and `CandidateCard`: Tasks 7 and 10;
  - Pareto: Tasks 8 and 10;
  - exact-mode parallel: Tasks 8 and 11;
  - convergence: Tasks 8 and 11;
  - `lab_benchmark.py analytics`: Task 12;
  - Screen B's tabs: Task 10;
  - Screen E: Task 11.
- **Walk items** 111, 112 and 124 are in Task 12. Scenarios 5, 14 and 26 are in Tasks 7, 8, 11 and 12. §20's named tests are in Tasks 1, 2, 4, 5, 7 and 8. The §9.6a Phase 3 rows are in Tasks 6, 7, 8 and 12. R3.5's pass conditions are in Task 13.
- **Not in this phase:**
  - persisted variable statuses, proposals, apply, focus and re-screen children, budgets (§8, Phase 4);
  - partitions, stage-2 replays, folds, Run Monitor (Phases 5–6);
  - the 20-parameter fixture and `MAX_PARAMETERS = 20` (Phase 4);
  - `summary.findings` as a server field (the rail composes its findings from the views it already fetched, decision 14).

### Decisions this plan makes that the spec left open

1. **Blocks subdivide the experiment's whole range in Phase 3.** There are no partitions until Phase 5; then they subdivide its selection partition (§10.2 rule 7). Block `b` runs on the bars from the range's start to the block's end, scored from the block's start. Indicators warm up on all prior history, while the kernel starts flat at the block (`kernel.py:198-199`). Block 1 therefore warms up exactly as block 0 does. A configuration costs `bars + Σ end_b` bar-evaluations, ≈ 3.5 × bars at K = 4; the planner prices it exactly, and the popover says so.
2. **`blocks` is an optional request field, default 0.** It accepts `0` or `2..8`. The planner's checkbox offers `SCREEN_BLOCKS = 4`. Existing clients, walk fixtures and benchmarks are unchanged.
3. **A block too short for a configuration's warm-up** is an `invalid: insufficient bars` block row. Block 0 decides the configuration's status, and the rule's missingness counts it.
4. **Without blocks** the period uncertainty reads `not measured: no screening blocks`, and condition 1 applies to block 0 only. §20 case 1 is proposable without blocks.
5. **Phase 3 computes recommended statuses and reasons.** Persisting them, the operator's confirmation and staleness of persisted statuses are Phase 4. Case 9's `stale` is `compare_scope` over the evidence scope.
6. **Lab task results live in memory**, at most 32 and least recently used. They are recomputed after a restart. `opt:` sources are keyed by `(job_id, cells_done)`, since they have no snapshot.
7. **Importance always runs unfiltered** (§7.3) and says so, so `filter_hash` is not in its key. The fast views (Pareto, robustness, convergence) honour the filter like every Phase 2 view.
8. **Exact-mode parallel is `parallel_mode`, not `mode`:** `QueryRequest.mode` defaults to `"exact"` for the matrix (`api.py:1323-1353`).
9. **Neighbourhoods hash positions.** Layout 2 uses `pos.<k>`; legacy and `opt:` sources use value indices from `ParameterInfo.values`. Nothing is O(n²), unlike `analysis.neighbours_sampled`.
10. **`ConvergenceChart` sits in Trial Lab's rail, compact.** The Run Monitor (Phase 5) adopts the same component.
11. **Walk 112 runs on the 10-parameter bench.** The 20-parameter version follows Phase 4 (§15 row 14 spans Phases 3–4).
12. **The candidate card's C and D classifiers are pure functions over evidence**, tested on fixtures now and fed real folds (Phase 6) and replays (Phase 5) later. In Phase 3, C is `unresolved · selection-period only` with the blocks' diagnostic, and D is `no replay yet (stage 2)`.
13. **The centre tab moves into the Lab store,** so a mini view's click opens its tab.
14. **The rail's deterministic findings** combine the report statement with the importance and robustness findings the views already fetched. `summary.findings` stays unbuilt.
15. **Ordering rules the spec leaves implicit:** the availability reasons (Task 5: aliasing before product design, matching cases 10, 14 and 15); the status precedence is decision 21.
16. **The veto shows both texts:** `structure not captured by mains, pairs and triples: deprioritization unsafe` and the warning `unexplained share high: noise or higher-order structure`, so cases 7 and 12 each find theirs.
17. **The statistical fixtures' generator constants are fixed once.** They live in `tests/lab_stat_fixtures.py` with a comment each, and the sixteen cases run at three seeds. A flip is reported at R3.5, never tuned away.
18. **"Detected" uses family-wise floors (max-T), not per-share floors.** §7.3 defines the floor per share; with 20 mains and 190 pairs about ten noise shares cross a per-share 95 % floor by chance, so §20 case 7 ("every status Active · not detected") could never hold, and case 1's noise mains fail too (the review's simulation: 7 of 20 noise parameters flagged). The per-share floor stays on the panel as a tick. **Changes a spec definition: open question 1.**
19. **Intervals are bootstrap distributions re-centred on the point estimate, and the coarse terms are adjusted and unclamped.** Plain percentile intervals of an adjusted share are biased upward by about df/n. On pure noise at d = 20 the residual's bootstrap mean was −5.5 against a point estimate of 1.00, so every d = 20 case read `decomposition inconsistent` and the veto could never rise. **Changes §7.3's "90 % percentile interval": open question 2.**
20. **Cases 1 and 13, which expect a proposal, run on 20,000 uniform rows; at 5,000 rows the rule honestly proposes nothing** (a companion test pins that). A noise triple increment's null SD is about √(2·48)/n whatever the value counts or σ, so at 5,000 rows its upper bound passes `THETA_MIN` too often. Product consequence: on real experiments, deprioritization needs roughly 20,000 uniform trials at d ≈ 8 before it can propose anything. **Changes §20's 5,000 rows for two cases: open question 3.**
21. **Status precedence:** coverage, then proposable, then period-dependent, then detected, then interaction, then three-way, then not detected (Task 5). "Not ruled out" requires both a family-wise detection and an upper bound above `THETA_MIN`.

### Open questions for Randall (before execution)

1. **Family-wise detection floors** (decision 18): accept max-T floors for "Detected", or keep §7.3's per-share floors and change §20 case 7's expectation?
2. **Re-centred intervals and unclamped coarse terms** (decision 19): accept?
3. **The rule's row requirement** (decision 20): accept 20,000 rows for the two proposal cases, and the consequence that real experiments need about that many uniform trials before deprioritization can propose?
4. **Walk 112 on 10 parameters** (decision 11), with the 20-variable version at Phase 4: accept?
5. **R2's question 1**, still open from R3: the workstation top bar against the design's stepper.
6. **Execution method:** subagent-driven or native.

- **Proportion:** fourteen tasks. The statistics (Tasks 4–6) and the UI (Tasks 9–11) carry most of the code; the plan fixes signatures, constants, reason strings, element ids and test names, and leaves the bodies they determine to the implementer.
