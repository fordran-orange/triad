# Plateau Walk-Forward Studies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A study walks a finished experiment's peaks-to-plateaus choice forward in rolling windows on several symbols and reports, per symbol, the plateau rule against the peak rule and the frozen centre out of sample.

**Architecture:** A new product module pair — `studies.py` (request, document, planning, the job kind, storage) and `study_rules.py` (pure per-window choice, per-side capital chains, flat windows, stitching, hashes, the report) — built on the Mission 6 pool, grid and analysis and the Mission 4/5 window, carry and rebase helpers. The runner gains a fourth resumable kind; the Aegis repository a `studies` kind; the API `/aegis/api/studies`; the Experiments page a study planner and view.

**Tech Stack:** Python 3.12 (`.venv-aegis`: pandas, pyarrow, numba 0.68), FastAPI, pytest (scope `aegis`), React/Vite/TypeScript, vitest, Playwright acceptance.

**Spec:** `docs/superpowers/specs/2026-10-15-aegis-plateau-walk-forward-design.md`

## Global Constraints

- Product work only: files under `app/products/aegis/`, `tests/test_aegis_*.py`, `tests/products/aegis/`, `tools/aegis_contracts.py`, `docs/`. No file under `app/trading_core/`, `app/platform_host/`, `app/products/triad/` changes.
- Every new test module is `tests/test_aegis_*.py` with `pytestmark = pytest.mark.aegis` after its imports; run tests as `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider <files>`.
- Lint through `scratchpad/lint_aegis.sh` or the `tools\verify.ps1` gate only; never a bare `ruff format`.
- Defaults (spec §4): symbols `["QQQ", "SPY", "ITOT"]`; range = the archive's span; in-sample bars = the parent experiment's bar count; out-of-sample bars = `in_sample // 4`.
- Honesty: `—` for an absent value; a no-plateau window states its reason; the frozen column states why it is absent; the label `RAW ARCHIVE · NOT RESEARCH-ELIGIBLE` on every report.
- Exchange stays CLOSED; nothing places an order; Triad suspended; schedule record `c99fa831` untouched.
- Branch `aegis/plateau-walk-forward` cut from `main` at the plan commit; `MISSION8_BASE` in the acceptance script is that commit.

## Plan rulings against the spec

| # | Ruling | Why |
|---|---|---|
| P1 | Each rule keeps one capital chain **per enabled side** (cash and carried position), runs each side's window with the other side disabled (as Mission 4 does), and builds the combined result by merging both sides' trades on the initial capital — the engine's own `_combine` semantics. | The engine carries one position per run and simulates the sides independently; this reproduces a continuous run exactly (Task 2's identity test). |
| P2 | A flat window with a carried position on a side runs that side on `rows[: oos_start + 1]` with `evaluate_from` at `oos_start` and the carried position's `exit_signal_time` set to the timestamp of bar `oos_start - 1`, `exit_tags ["window:flat"]`; the exit fills at the window's first bar open and no entry can fill. Without a carry, a flat side runs nothing and keeps its cash. | Uses the engine's existing travelling exit; no engine change. |
| P3 | Combined exposure of a window or a stitched series = the share of its out-of-sample bars inside any trade's `[entry_time, exit_time]`, union over both sides. | The engine's union exposure needs per-bar arrays that `run_backtest` does not return. |
| P4 | A window's full record (trades per rule and side, chain state) is `studies/<id>.windows/<symbol>/<w>.json`; its in-sample cells `…/<w>.parquet`; the study document keeps a compact record (no trades) per window. Both files are written atomically (tmp + replace); a window counts as done only when both exist and parse. | Keeps the document small enough to persist after every unit; resume reads the files. |
| P5 | One runner unit = one window of one symbol (its whole in-sample map, then up to six side runs). Units are ordered symbol by symbol, window by window. The pool is started for a symbol's first pending unit and shut down when the symbol changes. | Chains depend on window order; a pool per symbol holds that symbol's bars once. |
| P6 | Objective `mar` or `cagr` with an in-sample span under 365 days (from the window's first and last timestamps, per symbol) is refused (422) — every cell would be null. | Mission 4's refusal, same reason. |
| P7 | Deleting an experiment that has studies answers 409 naming them. | A study's parent is part of its evidence. |
| P8 | The best cell = the highest oriented objective (`analysis.objective_values`) among valid cells with a value; ties to the lower cell index; none when no cell has a value, and the peak rule is then flat that window ("no valid cell has a value"). | Spec §5.2; §5.3's "flat only when no cell is valid" extended to cells whose objective is null — there is nothing to rank. |
| P9 | Centre distance = Euclidean distance between consecutive plateau centres' grid positions, each divided by `max(shape_k - 1, 1)`; reported only for consecutive windows that both found a plateau; the stability block gives the median. | Spec §5.5 "normalized by each range". |
| P10 | The chart's curves are each rule's stitched combined equity (trade-exit points), resampled to at most 256 points per rule and symbol, first and last kept. | Bounded document size. |
| P11 | A rule's result hash per symbol = `results.result_hash({"trades": stitched_trades, "metrics": stitched_metrics})`. | Spec §6 "an identical study reproduces it". |
| P12 | The plan's estimate = Σ symbols [windows × planned cells × in-sample bars + windows × 6 × mean(oos_end) bars] × the measured `ms_per_cell_bar` (`ExperimentStore.last_ms_per_cell_bar()`, else `KERNEL_MS_PER_BAR`) ÷ `effective_workers` for the map part only; labelled an estimate with its price source. | Spec §3 item 1. |
| P13 | Window `w` of every symbol samples with seed `experiment.seed + w` (sampled maps only). | Reproducible per window. |
| P14 | The in-sample floor refuses `in_sample_bars < MIN_BARS` ("in_sample_bars 30 below 35") and an in-sample length on which `build_grid(spec, surface, in_sample_bars).valid_count == 0` ("in_sample_bars 40: every cell's warm-up needs more bars"); cells merely skipped for warm-up are named in the plan, not refused. The out-of-sample floor is `MIN_OOS_BARS` (20), since out-of-sample runs see the full prior history. | Spec §5.4 with §12 ("the planner names the skips"). |
| P15 | The plan carries `surface.plan(...)`'s levers for a sampled map and the planner shows them; applying one means a new experiment, because a study inherits its experiment's definition (spec §4). | Spec §8 shows the levers; §4 fixes the definition. |
| P16 | Each side run in a window record carries `run_hash = results.result_hash({"trades": side["trades"], "metrics": side["metrics"]})`; acceptance item 65 computes the same hash from `POST /backtest`'s side block. | A window-level hash both sides can compute without reproducing the backtest route's data identity. |
| P17 | Build order: the report (Task 4) precedes the job kind (Task 5), whose `finalize` stores it; all routes, the plan route included, land with the job kind. | The spec's §11 order with the report pulled forward for its consumer. |

## Review Focus

1. **Symbols with different bar counts in the same range** (gaps, late listing): each symbol gets its own window count; the plan line and the report never assume equal windows. Test in Task 1 (`test_plan_counts_windows_per_symbol`).
2. **A window whose in-sample objective is null in every cell** (MAR under a year, a dead market): the plateau and peak rules are flat that window and say why; the chain continues. Test in Task 2 (`test_null_objective_window_is_flat_for_both_choosing_rules`).
3. **A worker restart in the middle of a symbol**: the study resumes at the first missing window with each rule's chain restored from the last window file, no window twice, the pool started for the right symbol. Test in Task 5 (`test_resume_restores_the_chains_from_the_last_window_file`).
4. **Deleting the parent experiment of a study**: refused 409 naming the study (P7). Test in Task 5 (`test_experiment_with_studies_cannot_be_deleted`).
5. **A parent experiment without a recommendation**: the study runs; the frozen column is absent with the reason "the parent report has no recommendation" in the report and the Markdown. Test in Task 4 (`test_frozen_column_absent_with_its_reason`).

---

### Task 1: Study request, planning and the repository kind

**Files:**
- Create: `app/products/aegis/studies.py`
- Modify: `app/products/aegis/runs.py` (studies kind)
- Test: `tests/test_aegis_studies.py`, `tests/test_aegis_runs.py`

**Interfaces:**
- Consumes: `experiments.ExperimentStore`, `ExperimentDocument`; `walkforward.cut_windows(n_bars, in_sample, out_of_sample) -> (list[Window], tail)`, `walkforward.MIN_OOS_BARS`; `surface.build_grid(spec, surface, bars)`, `surface.plan(...)`, `surface.effective_workers`, `surface.KERNEL_MS_PER_BAR`; `backtest.MIN_BARS`.
- Produces:
  - `StudyRequest(BaseModel)`: `experiment_id: str`, `name: str | None = None`, `symbols: list[str] = ["QQQ","SPY","ITOT"]` (non-empty, distinct, upper-cased), `start: date | None`, `end: date | None`, `in_sample_bars: int | None`, `out_of_sample_bars: int | None`; `extra="forbid"`.
  - `SymbolPlan(BaseModel)`: `symbol`, `bars`, `windows: int`, `unused_tail_bars: int`, `first_window: dict` (dates), `mode: Literal["exhaustive","sampled"]`, `cells_per_window: int`, `runs: int`.
  - `StudyPlan(BaseModel)`: `experiment_id`, `timeframe`, `in_sample_bars`, `out_of_sample_bars`, `symbols: list[SymbolPlan]`, `total_runs`, `estimate_seconds`, `ms_per_cell_bar`, `price_source: Literal["measured","starting_guess"]`, `workers`, `levers: list[surface.Lever]` (P15).
  - `plan_study(request: StudyRequest, experiment: ExperimentDocument, bars_by_symbol: dict[str, list[str]], ms_per_cell_bar: float | None, workers: int) -> StudyPlan` — `bars_by_symbol` maps each symbol to its timestamps (ISO) in the range; raises `ValueError` with the refusal text.
  - `StudyDocument(BaseModel)`: `id, name, experiment_id, strategy_id, spec, surface, objective, tolerance, budget, seed, timeframe, settings, symbols, start, end, in_sample_bars, out_of_sample_bars, frozen_centre: dict | None, frozen_absent: str | None, plan: dict, status: Literal["queued","running","paused","done","cancelled","failed"], progress: dict, windows: dict[str, list[dict]] = {}, report: dict | None = None, decision: dict | None = None, ms_per_cell_bar: float | None = None, job_id: str | None = None, error: str | None = None, created_at, updated_at`.
  - Repository (`RunRepository` protocol and `JsonRunRepository`): `save_study(document: dict) -> str`, `get_study(id) -> dict`, `list_studies() -> list[dict]`, `delete_study(id) -> None` (removes `studies/<id>.json`, its summary and `studies/<id>.windows/`), `study_dir(id) -> Path` (`studies/<id>.windows`). Summary keys: `id, name, experiment_id, status, progress, symbols, objective, created_at, updated_at, decision`.

- [ ] **Step 1: Write the failing tests** (`tests/test_aegis_studies.py`)

```python
def test_defaults_come_from_the_experiment():
    # experiment fixture: 3,493 bars of 1h, objective mar, tolerance 0.15, 252-cell surface
    plan = plan_study(StudyRequest(experiment_id=exp.id), exp, three_symbols(17_500), None, 10)
    assert (plan.in_sample_bars, plan.out_of_sample_bars) == (3493, 873)
    assert [s.symbol for s in plan.symbols] == ["QQQ", "SPY", "ITOT"]
    assert plan.symbols[0].windows == (17_500 - 3493) // 873 == 16
    assert plan.symbols[0].cells_per_window == 252 and plan.symbols[0].mode == "exhaustive"
    assert plan.price_source == "starting_guess"

def test_plan_counts_windows_per_symbol():                      # Review Focus 1
    plan = plan_study(req, exp, {"QQQ": ts(17_500), "SPY": ts(9_000), "ITOT": ts(4_400)}, 0.028, 10)
    assert [s.windows for s in plan.symbols] == [16, 6, 1]
    assert plan.total_runs == sum(s.runs for s in plan.symbols)

@pytest.mark.parametrize(("mutate", "message"), [
    (dict(experiment_status="running"), "experiment fresh-surface is running; a study needs a finished experiment with a report"),
    (dict(symbols=["NOPE"]), "unknown symbol 'NOPE'"),
    (dict(timeframes={"SPY": []}), "symbol 'SPY' has no 1h bars in the range"),
    (dict(bars={"QQQ": 4000}), "range too short: 4000 bars; one window needs 3493 + 873 bars"),
    (dict(out_of_sample_bars=10), "out_of_sample_bars 10 below 20"),
    (dict(in_sample_bars=30), "in_sample_bars 30 below 35"),                                    # P14
    (dict(in_sample_bars=40, long_warmups=True), "in_sample_bars 40: every cell's warm-up needs more bars"),
    (dict(budget_runs=3, sampled=True), "budget too small for a 2-parameter surface"),   # surface.plan's refusal
    (dict(span_days=200), "objective mar needs an in-sample span of at least 365 days"),   # P6
])
def test_refusals_name_the_problem(mutate, message): ...
```

and in `tests/test_aegis_runs.py`: `test_studies_kind_round_trips_and_deletes_its_windows` (save, list summary keys, get, `study_dir` created and removed by `delete_study`, a report file inside is gone).

- [ ] **Step 2: Run them — expected FAIL** (`ModuleNotFoundError: products.aegis.studies`; `AttributeError: save_study`).
- [ ] **Step 3: Implement** `StudyRequest`, `SymbolPlan`, `StudyPlan`, `StudyDocument`, `plan_study` in `studies.py`, and the studies kind in `runs.py` mirroring the experiments kind (`_save("studies", "id", document, _study_summary)`). The floors are P14's; the per-window map is `surface.plan(spec, surface, budget, in_sample_bars, ms, workers, timeframe, price_source)` (its `mode`, `planned_runs`, levers and `ValueError` pass through).
- [ ] **Step 4: Run — expected PASS.**
- [ ] **Step 5: Commit** "Aegis studies: request, planning per symbol, refusals, the studies repository kind".

### Task 2: The rules, the chains and flat windows (pure)

**Files:**
- Create: `app/products/aegis/study_rules.py`
- Test: `tests/test_aegis_study_rules.py`

**Interfaces:**
- Consumes: `backtest.run_backtest`, `BacktestRequest`, `BacktestSettings`, `OpenPosition`, `backtest._combine`, `backtest._metrics`; `walkforward.Window`, `walkforward.flag_edge_exits`; `analysis.objective_values`, `analysis._columns`; `surface.Grid`, `surface.apply_params`; `results.result_hash`.
- Produces:
  - `RULES = ("plateau", "peak", "frozen")`.
  - `best_cell(rows, objective: str) -> int | None` (P8).
  - `centre_inside(previous_plateau_cells: list[int] | None, centre: int | None) -> bool | None`; `move_distance(grid, a: int, b: int) -> float` (P9).
  - `SideChain` dataclass: `cash: float`, `carry: dict | None`.
  - `run_window(strategy: StrategySpec | None, rows: list[dict], window: Window, chains: dict[str, SideChain], settings: BacktestSettings, last: bool) -> dict` — `strategy is None` means flat (P2). Returns `{"sides": {side: {"trades", "metrics", "ending_cash", "carried_in", "open_position", "flat": bool, "run_hash"}}, "combined": {"trades", "metrics", "exposure", "net_pnl"}, "chains": {side: SideChain}}` (P16); window combined metrics are measured from the previous combined running equity.
  - `stitch_rule(window_results: list[dict], initial_capital: float, oos_timestamps: list[str]) -> dict` → `{"trades", "equity", "metrics", "exposure", "result_hash"}` (P1, P3, P11).
  - `resample(points: list[dict], limit: int = 256) -> list[dict]` (P10).

- [ ] **Step 1: Write the failing tests** (synthetic `wave_bars(n=600)` from `test_aegis_walkforward`; `pinned()` from `test_aegis_surface`; windows from `cut_windows(600, 200, 100)`):

```python
def test_frozen_chain_equals_one_continuous_run():
    # the same parameters every window, chained per side, == one run from the first OOS bar
    chained = stitch_rule([run_window(spec, rows, w, chains, settings, last=(w is ws[-1])) ...], 100_000, oos_ts)
    continuous = run_backtest(BacktestRequest(strategy=spec, bars=rows[: ws[-1].oos_end],
        settings=settings.model_copy(update={"evaluate_from": first_oos})))
    assert [t["net_pnl"] for t in chained["trades"]] == [t["net_pnl"] for t in continuous["combined"]["trades"]]
    assert chained["metrics"]["net_pnl"] == pytest.approx(continuous["combined"]["metrics"]["net_pnl"])

def test_flat_window_closes_a_carried_position_at_its_first_bar_and_opens_nothing():
    # a window ending with an open long, then a flat window
    flat = run_window(None, rows, ws[k + 1], chains_with_open_long, settings, last=False)
    exit_ = flat["sides"]["long"]["trades"][-1]
    assert exit_["exit_time"] == rows[ws[k + 1].oos_start]["timestamp"] and "window:flat" in exit_["exit_tags"]
    assert flat["sides"]["long"]["open_position"] is None and len(flat["sides"]["long"]["trades"]) == 1
    assert flat["sides"]["long"]["flat"] is True

def test_window_net_is_its_ending_equity_minus_the_previous(): ...
def test_best_cell_ties_to_the_lower_index_and_skips_nulls(): ...
def test_null_objective_window_is_flat_for_both_choosing_rules():   # Review Focus 2
    assert best_cell(all_null_rows, "mar") is None
def test_centre_inside_and_move_distance():
    assert centre_inside([3, 4, 5], 4) is True and centre_inside(None, 4) is None
    assert move_distance(grid2((1, 9, 1), (1, 9, 1)), cell(1, 1), cell(9, 9)) == pytest.approx(math.sqrt(2))
def test_stitched_hash_reproduces_and_changes_with_a_trade(): ...
def test_resample_keeps_ends_and_bounds_the_count(): ...
```

- [ ] **Step 2: Run — expected FAIL** (`ModuleNotFoundError: products.aegis.study_rules`).
- [ ] **Step 3: Implement** the interfaces above. `run_window` builds, for each enabled side of `strategy` (or of the chain when flat), a strategy with the other side disabled, `settings` with `evaluate_from = rows[window.oos_start]["timestamp"]`, `initial_capital = chain.cash`, `initial_position = OpenPosition(**chain.carry)` when set, `close_at_end = last`, bars `rows[: window.oos_end]` (flat: `rows[: window.oos_start + 1]` and the P2 exit fields; no carry → no run). New open positions get `origin_window = window.index`.
- [ ] **Step 4: Run — expected PASS.**
- [ ] **Step 5: Commit** "Aegis studies: per-side chains, flat windows, choice helpers, stitching and hashes".

### Task 3: In-sample maps on a window slice

**Files:**
- Modify: `app/products/aegis/pool.py`
- Modify: `app/products/aegis/studies.py` (`map_window`)
- Test: `tests/test_aegis_pool.py`, `tests/test_aegis_studies.py`

**Interfaces:**
- Consumes: `Pool`, `_init_worker`, `_run_cell`; `surface.latin_hypercube(grid, count, seed)`, `surface.refinement_cells(grid, run_cells, plateaus, budget)`; `analysis.analyse(rows, grid, objective, tolerance, mode, seed, data_label)`.
- Produces:
  - `Pool.run_chunk(cells, want_curve, window: tuple[int, int] | None = None) -> list[dict]`; workers slice their frame to `[start, end)` and keep one `(frame, data_key)` per window; `window=None` behaves exactly as today.
  - `map_window(pool: Pool, grid: Grid, mode: str, first_pass: int, refinement: int, objective: str, tolerance: float, seed: int, window: tuple[int, int], data_label: str) -> tuple[list[dict], dict]` → the window's cell rows (as `ExperimentStore` rows: `cell, pass, valid, skip_reason, params, metrics`) and the `analyse` report.

- [ ] **Step 1: Write the failing tests**
  - `test_pool_window_slice_equals_a_backtest_on_those_bars` (pool of 2, 4 cells, window `(100, 300)` of `ROWS`): each row's 30 metrics equal `run_backtest(BacktestRequest(strategy=apply_params(spec, params), bars=ROWS[100:300]))`.
  - `test_map_window_exhaustive_matches_analyse` and `test_map_window_sampled_stays_within_budget` (first pass + refinement = planned runs; seeded: two calls give the same cells).
- [ ] **Step 2: Run — expected FAIL** (`TypeError: run_chunk() got an unexpected keyword argument 'window'`).
- [ ] **Step 3: Implement**; `map_window` reuses the experiment's sampled path (Latin hypercube first pass, analyse, `refinement_cells` on the oriented objective) without persisting anything.
- [ ] **Step 4: Run — expected PASS**, plus the existing `tests/test_aegis_pool.py` and `tests/test_aegis_experiments.py` unchanged.
- [ ] **Step 5: Commit** "Aegis studies: in-sample maps on a window slice of the pool".

### Task 4: The report and its Markdown (pure)

**Files:**
- Modify: `app/products/aegis/study_rules.py` (`study_report`, `render_study_markdown`)
- Test: `tests/test_aegis_study_rules.py`

**Interfaces:**
- Consumes: Task 2's stitched rule results; window records (spec §5.5 fields).
- Produces: `study_report(document: StudyDocument, per_symbol: dict[str, dict]) -> dict` with keys `objective, data_label, raw_archive: True, symbols: {symbol: {rules: {rule: {metrics, trades, flat_windows, windows, result_hash} | {"absent": reason}}, comparison, stability: {plateau_share, centre_kept_share, median_move, centre_path: {path: [value|None]}}, curves: {rule: [...]}}}, summary, caveats`; `render_study_markdown(report) -> str` beginning `# Plateau walk-forward:`.

- [ ] **Step 1: Write the failing tests**
  - `test_comparison_sentence_by_objective`: "On SPY the plateau rule's out-of-sample MAR was 0.61, against 0.42 for the peak rule and 0.55 for the frozen centre." (two decimals; `—` for a null metric).
  - `test_flat_windows_line`: "flat in 3 of 16 windows".
  - `test_cross_symbol_line_and_caveats`: "plateau rule ahead of the peak rule on 2 of 3 symbols by MAR"; caveats name the window counts, the flat windows and "no significance test is claimed".
  - `test_frozen_column_absent_with_its_reason` (Review Focus 5): `{"absent": "the parent report has no recommendation"}` in the report and that sentence in the Markdown.
  - `test_markdown_carries_the_raw_archive_label`: `"RAW ARCHIVE · NOT RESEARCH-ELIGIBLE"` in the Markdown.
- [ ] **Step 2: Run — expected FAIL** (`ImportError: study_report`).
- [ ] **Step 3: Implement.** "Ahead" compares the oriented objective (lower is better for `max_drawdown`); a symbol where either rule's objective is null is "not comparable" and counted separately in the summary.
- [ ] **Step 4: Run — expected PASS.**
- [ ] **Step 5: Commit** "Aegis studies: the report, comparison sentences, stability and Markdown".

### Task 5: The study job kind, storage and routes

**Files:**
- Modify: `app/products/aegis/studies.py` (`StudyStore`, `create_study`, `StudyJob`, `decide_study`, `cancel_idle_study`)
- Modify: `app/products/aegis/jobs.py` (`KINDS`, `RESUMABLE`)
- Modify: `app/products/aegis/api.py` (routes; experiment delete refusal P7)
- Modify: `tools/aegis_contracts.py` (StudyRequest, StudyDocument, StudyPlan) and regenerate `ui/src/contracts.ts`
- Test: `tests/test_aegis_studies.py`, `tests/test_aegis_api.py`, `tests/test_aegis_jobs.py`, `tests/test_aegis_contracts.py`

**Interfaces:**
- Consumes: Tasks 1–4; `jobs.JobRunner`; `optimize.engine_rows`, `optimize.provenance`; `api._select`.
- Produces:
  - `StudyStore(repository)`: `save, get, list, delete, free_id, window_paths(id, symbol, w) -> (json_path, parquet_path), write_window(id, symbol, w, record, rows), read_window(id, symbol, w) -> dict | None, done_windows(id) -> dict[str, set[int]]`.
  - `create_study(store, experiments: ExperimentStore, request, bars_by_symbol, workers) -> StudyDocument` (status `queued`, `frozen_centre` from the parent's latest report recommendation, else `frozen_absent`).
  - `StudyJob(document, rows_by_symbol: dict[str, list[dict]], pinned_by_symbol, repository, max_workers=None)`: `name = "study"`, `side = "both"`, `resumable = True`, `bars_per_unit = 0`, `units: list[tuple[str, int]]` (pending only), `pause_requested`, `run_unit(i)`, `commit(i, result)`, `snapshot()`, `finalize(status)`, `release()`.
  - Window record (`run_unit`'s result; the compact copy in `StudyDocument.windows[symbol]` drops `trades`): `index, is_start, is_end, oos_start, oos_end` (timestamps), `mode, cells_run, skipped`, `plateau: {id, size, median, cliff, centre_cell, centre_params} | None`, `no_plateau: str | None` (the analysis statement), `peaks, fragile`, `best: {cell, params, objective} | None`, `rules: {rule: run_window's result without "chains" | {"absent": reason}}`, `chains_out: {rule: {side: SideChain}}`, `centre_inside: bool | None`, `moved: float | None` (P9).
  - Runner: `KINDS = ("optimization", "walkforward", "experiment", "study")`, `RESUMABLE = ("experiment", "study")`.
  - Routes (`/aegis/api/studies`): `POST /plan` (200 `StudyPlan`), `POST /` (202 `{study_id, job_id, status, plan}`), `GET /`, `GET /{id}`, `POST /{id}/pause`, `POST /{id}/resume` (202), `POST /{id}/cancel`, `DELETE /{id}`, `PUT /{id}/decision`, `GET /{id}/windows/{symbol}/{w}/cells?offset&limit`, `GET /{id}/report.md`. `DELETE /experiments/{id}` answers 409 "experiment {id} has studies: {ids}" when any exists.

- [ ] **Step 1: Write the failing tests**
  - `test_study_runs_to_done_with_every_window_once` (two synthetic symbols in a tmp archive, 3×3 surface, small windows): status `done`; `done_windows == {"QQQ": {0..n-1}, "SPY": {0..m-1}}`; each rule's `result_hash` is 64 hex.
  - `test_identical_study_reproduces_every_hash`.
  - `test_pause_lands_at_a_window_boundary_then_resumes`.
  - `test_resume_restores_the_chains_from_the_last_window_file` (Review Focus 3): restart after window 1 of SPY (runner record `running`, `mark_lost_on_startup` → `paused`), resume → no window rerun, the second half's first window starts with the chain cash written in window 1's file.
  - `test_study_routes_plan_create_get_decide_delete` and `test_study_route_refusals` (each §5.4 refusal, 409 for busy runner / pause on done / delete while running or paused).
  - `test_experiment_with_studies_cannot_be_deleted` (Review Focus 4).
  - `test_contracts_include_the_study_models` (staleness test passes after regeneration).
- [ ] **Step 2: Run — expected FAIL** (`AttributeError: StudyJob` / 404 on `/aegis/api/studies/plan`).
- [ ] **Step 3: Implement.** `run_unit` starts or switches the pool for the unit's symbol (P5), maps the window (Task 3), chooses (Task 2), runs the three rules' windows from the chains restored on construction from the last window file per symbol, and returns the full record; `commit` writes the window files (P4) and updates the compact record and progress; `finalize("done")` stitches each symbol's rules and stores `report`; a cancel after a pause request maps to `paused` (Mission 6 P4). Rows for every symbol come from `_select(store, symbol, timeframe, start, end)` in the route.
- [ ] **Step 4: Run — expected PASS**, plus `tests/test_aegis_experiments.py`, `tests/test_aegis_jobs.py`, `tests/test_architecture.py` (scope core) unchanged.
- [ ] **Step 5: Commit** "Aegis studies: the resumable study job kind, window files, routes and contracts".

### Task 6: The page

**Files:**
- Modify: `app/products/aegis/ui/src/api/client.ts`, `ui/src/results.ts`, `ui/src/components/ExperimentReport.tsx`, `ui/src/components/ExperimentsPage.tsx`, `ui/src/styles.css`
- Create: `ui/src/studies.ts`, `ui/src/studies.test.ts`, `ui/src/components/StudyPlanner.tsx`, `ui/src/components/StudyView.tsx`, `ui/src/components/StudyReport.tsx`

**Interfaces:**
- Consumes: Task 5's routes and contracts.
- Produces: `api.studyPlan(body)`, `createStudy(body)`, `studies()`, `study(id)`, `pauseStudy`, `resumeStudy`, `cancelStudy`, `deleteStudy`, `decideStudy(id, {verdict, notes})`, `studyWindowCells(id, symbol, w, query)`, `studyMarkdownUrl(id)`; `studies.ts`: `planLine(plan) -> string` ("3 symbols · 48 windows · 12,096 runs · ≈ 2 min (measured on this host)"), `ruleRows(report, symbol)`, `equityPaths(curves, width, height)`, `flatShading(windows)`. Element ids: `#experiment-walk-forward`, `#study-planner`, `#study-symbols`, `#study-start-date`, `#study-end-date`, `#study-in-sample`, `#study-out-of-sample`, `#study-plan`, `#study-start`, `#study-error`, `#studies-of-experiment`, `#study-<id>`, `#study-progress`, `#study-pause`, `#study-resume`, `#study-cancel`, `#study-delete`, `#study-report`, `#study-summary`, `#study-symbol-<SYMBOL>`, `#study-rules-<SYMBOL>`, `#study-chart-<SYMBOL>`, `#study-windows-<SYMBOL>`, `#study-window-<SYMBOL>-<w>`, `#study-decision`, `#study-decision-verdict`, `#study-decision-notes`, `#study-decision-save`.

- [ ] **Step 1: Write the failing vitest cases** (`studies.test.ts`): `planLine` for exhaustive and sampled plans and both price sources; `ruleRows` shows `—` for a null metric and the absent frozen reason; `equityPaths` keeps first and last points and scales to the box; `flatShading` returns one band per flat window.
- [ ] **Step 2: Run** `npm --prefix app/products/aegis/ui test` — expected FAIL (cannot resolve `./studies`).
- [ ] **Step 3: Implement** the helpers and components: the experiment report's "Walk forward" opens `StudyPlanner` (symbols checkboxes from `/data/symbols`, range, window lengths, live plan line with a 300 ms debounce, the levers of a sampled map shown with "apply in a new experiment" (P15), Start); the experiment report lists its studies; `StudyView` polls every 2 s while running, shows progress (symbol, window, cells, measured cost, remaining) with Pause, Resume, Cancel, Delete, then `StudyReport` (summary line, per-symbol rules table, SVG chart with window boundaries and shaded flat windows, stability block, window table whose rows open the window's in-sample cells, Markdown link) and the decision form.
- [ ] **Step 4: Run** the UI tests and `npm --prefix app/products/aegis/ui run build` — expected PASS and built; a browser check against the restarted worker: plan, start and finish a 2-symbol, 3×3 study from a throwaway experiment, read the report, delete both (ledger the evidence).
- [ ] **Step 5: Commit** "Aegis UI: walk an experiment forward — planner, study view, report, decision".

### Task 7: Acceptance and the record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (items 61–69, `MISSION8_BASE`)
- Create: `docs/MISSION8_PLATEAU_WALK_FORWARD.md`, `docs/evidence/aegis-acceptance-<stamp>.json`

- [ ] **Step 1: Write items 61–69** (spec §3 items 1–9, in order): 61 plan from the item-49 experiment (exhaustive, 252 cells per window, per-symbol windows, priced); 62 start on QQQ/SPY/ITOT 1h full range with default windows, progress by window, `GET /studies/{id}` under 500 ms; 63 pause, `restart_worker()`, paused not lost, resume to `done`, every `(symbol, window)` once (`GET /studies/{id}` windows); 64 report visible by id (`#study-summary`, three `#study-rules-*`, `#study-chart-*`, `#study-windows-*`, the raw-archive label); 65 recompute one window: re-analyse its cells (`/windows/{symbol}/{w}/cells`) to the same centre or no-plateau statement, and match each side of its plateau-rule out-of-sample run with a direct `POST /backtest` (same bars, that side alone enabled, `evaluate_from`, the chain cash and carried position from the previous window file) by P16's `run_hash`; 66 an identical study via the API reproduces every rule hash; 67 the §5.4 refusals over HTTP; 68 decision accepted with a note, shown on the study and under its experiment; 69 governance: status human_directed / CLOSED, no Core/platform/Triad change since `MISSION8_BASE`.
- [ ] **Step 2: Build and restart** the worker (WMI, as items 51 and earlier missions do; it relaunches on `.venv-aegis`); confirm `/health/live`.
- [ ] **Step 3: Run** `.venv/Scripts/python.exe tests/products/aegis/browser_workstation.py` → 69/69 PASS; copy the JSON to `docs/evidence/`.
- [ ] **Step 4: Full verification**: `tools\verify.ps1` on the branch (it ends at the foundation audit's main-branch check by design), UI tests and build; record the counts and the measured study cost.
- [ ] **Step 5: Write the record** `docs/MISSION8_PLATEAU_WALK_FORWARD.md` (decisions, built table by commit, the acceptance evidence, the per-symbol results of the acceptance study as measured, rulings P1–P13 and the ledger's, known limits) and commit "Aegis: plateau walk-forward acceptance and the Mission 8 record".

### After Task 7

Independent milestone QA at the exact commit and a whole-branch review (the operator chooses the model), one fix pass with every fix test-first, the record completed, `tools\verify.ps1` on `main` after the merge, and merge and push only on the operator's answer.
