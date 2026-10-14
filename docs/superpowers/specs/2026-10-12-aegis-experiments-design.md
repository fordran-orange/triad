# Aegis Mission 6 — Experiments: mapping a strategy's control surface (design)

Date: 2026-10-12. Builds on the merged Mission 5 slice (`main` at `3490563`,
`docs/MISSION5_STRATEGY_LAB.md`). Operator framing approved in chat on 2026-10-11/12: an
experiment maps the **entire control surface** of a saved strategy (1 to 10 parameters, no cap on
runs), keeps every run, produces an honest report whose analysis follows the operator's
**peaks to plateaus** principle, records the operator's decision, lights the Experiments page, and
folds in the nine minors deferred from Mission 5.

Standing constraints carry over unchanged: the honesty rule (nothing fabricated is shown), pinned
raw-archive provenance, one job at a time, Core imports neither product, exchange CLOSED, no
broker path, Triad suspended with its scheduled autonomy disabled. This mission changes one file
outside `app/products/aegis/`: the shared `pyproject.toml`, to declare `numba` as the optional
extra `aegis` (§4.4); Core's required dependency list stays byte-for-byte unchanged.

## 1. The principle: peaks to plateaus

Stated by the operator on 2026-10-11 and binding for every analysis in this product:

> The backtester is called peaks to plateaus. The whole point is to find the peaks, mark them as
> fragile, and move on to a region. A peak is still valid if it is supported by a plateau.

A **peak** is a local maximum of the objective over the surface. A peak whose neighbours fall
away is **fragile**. A **plateau** is a connected region where the objective stays within a
tolerance band. The recommendation is a plateau, with its centre as the setting to use; a peak
that lies inside a plateau is **supported** and stays valid. The single best cell is never the
recommendation on its own. §7 defines each term exactly.

## 2. Intent and definition of done

The operator can map every parameter of a saved strategy at once, see where the strategy is
robust and where it merely spiked, get a recommendation with its uncertainty, and keep the whole
thing, decision included, referable by id.

Definition of done (the acceptance script walks these in order, after the 47 Mission 3–5 items,
all of which must pass on the compiled engine):

1. Every earlier acceptance item passes with the kernel engine; item 22 still yields
   `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360`, and the Mission 5
   walk-forward hashes of items 28 and 34 (`783f07c3146b…`, `5d9371614fc0…`) are unchanged; the
   status route reports the kernel available.
2. From the Mission 5 breakout document, define an experiment over four parameters
   (`long_side.indicators.donchian.length` 10–40 step 5, `long_side.indicators.rsi.length`
   7–28 step 7, `short_side.indicators.ema.length` 5–15 step 5, `short_side.indicators.sma.length`
   20–40 step 10; 7 × 4 × 3 × 3 = 252 cells) on QQQ 1h 2023-01-01 → 2024-12-31 with the objective
   MAR; the plan says exhaustive, 252 runs, the estimate priced at the measured cost.
3. Start it; progress advances by chunk while the status route stays responsive.
4. Pause it; restart the worker; the experiment is **paused**, not lost; resume it; it finishes
   with every cell present exactly once.
5. The report names a plateau, its centre, its supported peak if any, and marks every fragile
   peak; main effects, interaction heatmaps and the sensitivity table are shown; outcome clusters
   are shown or refused with the reason.
6. Materialize the centre cell: a full run envelope with a `result_hash` equal to the hash of a
   direct backtest of the same strategy with those parameters; materializing it again returns the
   same hash.
7. Use the centre in the workspace: the document loads with those parameters as unsaved edits
   and a backtest runs on them.
8. Record a decision (accepted, with a note) and see it on the list and on the experiment.
9. Refine: a new experiment is created with the parent linked and ranges prefilled around the
   plateau, not started.
10. Plan a second experiment over budget (the same four parameters at step 1: 31 × 22 × 11 × 21
    = 157,542 cells against a budget of 2,000 runs): the plan says sampled, 2,000 runs, the
    fraction; each way back into scope is listed with its resulting count; freezing the two
    short-side parameters brings it to 682 cells, under budget, and the plan says exhaustive.
11. Recompute the finished experiment's report with the objective net P&L and tolerance 0.10
    without rerunning; both reports are kept.
12. Every refusal is honest: a surface with no parameters, eleven parameters, a path on the wrong
    side, a fractional step on a whole-number parameter, a budget of zero, a pause on a finished
    experiment, a delete of a running one, each a 422 or 409 naming the problem.
13. `GET /aegis/api/status` still reports `human_directed` / `CLOSED`; no file under
    `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changed; `pyproject.toml`
    changed by the one optional-extra line only, with the required list unchanged.

## 3. Operator decisions recorded in this design

| Decision | Choice (chat, 2026-10-11/12) |
|---|---|
| What an experiment varies | The whole control surface: 1–10 parameter paths across both sides; no cap on runs |
| Over-budget grids | **Exhaustive when the grid fits the budget, sampled otherwise** (default), with ways back into scope offered |
| Whose parameters | The whole strategy, both sides, paths prefixed `long_side.` / `short_side.`; combined objective, per-side metrics kept |
| Recommendation | Peaks to plateaus (§1, §7) |
| Engine | **B: compiled loop with numba**, the current engine kept as the reference oracle |
| Hygiene | The nine Mission 5 deferred minors folded in |

## 4. Architecture

Everything lives under `app/products/aegis/` except the dependency line. Dependencies still point
one way: browser → worker HTTP → `experiments`, `surface`, `analysis`, `kernel`, `backtest`,
`indicators`, `jobs`, `runs`. Core is imported only for `local_headers`, `Store` and
`process_power` (`tests/test_architecture.py` enforces; a new assertion checks that nothing under
`app/trading_core/` imports numba).

| Unit | Location | Responsibility |
|---|---|---|
| Kernel | `kernel.py` (new) | the numba-compiled simulation over arrays; `simulate_arrays(...)`; availability flag |
| Engine switch | `backtest.py` (revised) | `BacktestRequest.engine`; array preparation; tags attached after the loop; identical payloads |
| Pool | `pool.py` (new) | process pool with per-worker bars, indicator cache and compiled kernel; chunk execution |
| Surface | `surface.py` (new) | `Parameter`, `Surface`, grid enumeration, validity skips, Latin hypercube, refinement, the planner and the ways back into scope |
| Analysis | `analysis.py` (new) | neighbours, peaks, plateaus, centres, main effects, interactions, sensitivity, clusters, the report |
| Experiments | `experiments.py` (new) | `ExperimentDocument`, the job kind, chunked execution, Parquet writing, pause/resume, materialize, report files, decision, refine |
| Storage | `runs.py` (revised) | repository kind `experiments` (document + sidecar); Parquet and report files beside it |
| API | `api.py` (revised) | `/experiments` routes; `engine` and `kernel_available` on status and envelopes |
| UI | `ui/src/` (revised) | Experiments page, planner, report view, decision, refine; `#nav-experiments` |
| Acceptance | `tests/products/aegis/browser_workstation.py` (extended) | items 1–13 of §2 appended |

### 4.1 Kernel

`kernel.simulate_arrays(open_, high, low, close, entry, exit_, warm, evaluating, permitted,
side_sign, initial_capital, allocation_fraction, commission, slippage_bps, close_at_end,
carried)` is one `@numba.njit(cache=True)` function. `carried` is a small float array
(`present, entry_price, quantity, entry_fee, capital_at_entry, exit_pending, exit_signal_index`)
or all zeros. It returns fixed-width arrays: per trade `entry_index, exit_index, signal_index,
exit_signal_index, entry_price, exit_price, quantity, gross, net, return, carried_in`; per bar
`equity, drawdown, in_position` for evaluated bars; and the scalars `ending_cash,
ending_equity, open_present, open_entry_index, open_signal_index, open_entry_price,
open_quantity, open_entry_fee, open_capital_at_entry, open_exit_signal_index`.

The arithmetic is the reference engine's, in the same order: fills, budget and quantity
(`floor((cash·fraction − commission) / fill)`), marked equity, running peak and drawdown,
realized settlement `capital_at_entry + net`, the end-of-data close, the travelling exit signal,
the carried `origin_window` (kept in Python). Nothing in the kernel touches strings, dates or
dicts.

### 4.2 Engine switch

`backtest.py` keeps `_simulate_side` as the **reference** engine, unchanged, and adds
`_simulate_side_kernel`, which prepares the arrays (signals and warm flags from the existing
evaluator; `evaluating` from `evaluate_from`; `permitted` from `entry_permitted` per bar,
vectorized over the frame's timestamps) and converts the kernel's arrays back into the same
trade dicts, equity points and side result the reference produces, attaching temporal tags from
each trade's entry and exit timestamps exactly as today.

`BacktestRequest.engine: Literal["kernel", "reference"] = "kernel"`. The envelope and every job
snapshot carry `engine`. When numba cannot import, `kernel.AVAILABLE` is false, every request
runs on the reference engine, the envelope says `"reference"`, and `GET /aegis/api/status`
reports `kernel_available: false` with the import error's name. `engine` is not part of any
canonical payload: the two engines must produce byte-identical payloads, and a test proves it
over every fixture of `tests/test_aegis_*.py` and the acceptance scenarios (hash equality).
Optimizer and walk-forward jobs run on the default engine too, so their hashes are part of the
same proof.

### 4.3 Pool

`pool.Pool(max_workers)` wraps `concurrent.futures.ProcessPoolExecutor` with an initializer
that receives the engine rows once and builds a per-worker `IndicatorCache` and warms the kernel.
`max_workers` defaults to `max(1, os.cpu_count() − 2)` (10 on this laptop) and is settable through
`AEGIS_POOL_WORKERS`. A chunk is a list of `(cell_index, parameter values)`; the worker applies the
parameters to the pinned spec, runs the backtest (kernel), and returns the cell rows (§6.2),
never the envelopes. Tests run with a pool of two.

### 4.4 Dependency

`pyproject.toml` gains an optional extra, `aegis = ["numba>=0.61,<0.69"]`, beside the existing
`dev` extra; the required dependency list is untouched. The Aegis worker's install becomes
`pip install -e .[aegis]` (0.68.0 installs for the venv's Python 3.12.10; llvmlite comes with
it). For now the library still lands in the shared `.venv`, so Core and Triad could import it but
never do: the architecture test asserts that no module under `app/trading_core/` or
`app/products/triad/` imports numba. The install is reversible and pinned; the independent QA
names it, as Mission 4's record named the Core helper.

The long-term fix is one environment per product: each product with its own dependency manifest
and virtual environment, and the supervisor launching each worker with its own interpreter, so a
product library never enters Core's runtime. That touches `tools/start_product.ps1`, the Core
supervisor and the install notes, so it is a Core-governed mission of its own with independent
QA; the Mission 6 record carries it as the next open item. The `aegis` extra is the line that
split will follow.

## 5. Surfaces and the planner

### 5.1 Contract

`Parameter(path, start, stop, step)`: `path` is `long_side.indicators.<id>.length`,
`long_side.indicators.<id>.params.<name>`, or the same under `short_side.`; it must resolve on
that side of the pinned spec (the Mission 5 path rules apply per side); whole-number parameters
need integer start, stop and step; `start ≤ stop`, `step > 0`; the value list is
`start, start+step, …` up to `stop`. `Surface(parameters: list[Parameter])` has 1 to 10 distinct
paths (`"a surface needs at least one parameter"`, `"at most 10 parameters"`, `"duplicate
parameter path"`).

`ExperimentRequest`: `name`, `strategy_id`, `data: DataReference`, `settings`, `objective`
(any key of the metric set: `net_pnl, net_return, cagr, max_drawdown, mar, win_rate,
expectancy, profit_factor, trade_count, exposure`), `surface`, `budget: {runs: int | None,
seconds: float | None}` with at least one set and both positive, `tolerance: float = 0.15`
(`0 < tolerance ≤ 1`), `seed: int = 1`. The strategy document must exist; the request pins
`strategy_hash` and a snapshot of the spec at submission, so later edits to the document never
change the experiment.

### 5.2 Grid and validity

The grid is the cartesian product of the value lists. Cells whose applied spec fails validation
(MACD fast ≥ slow and the like) are **skipped** and counted with the reason, found during
enumeration without running anything. The only hard ceiling is the engine's bars limit; there is
no cap on cells.

### 5.3 Budget and mode

`estimate_seconds = planned_runs × bars × ms_per_cell / 1000 / effective_workers`, priced at the
pool's last measured cost on this host (persisted with finished experiments; a starting guess
before any), with `effective_workers = max_workers × 0.8`. A grid **fits** when
`valid_cells ≤ budget.runs` (if set) and `estimate ≤ budget.seconds` (if set); then the mode is
**exhaustive** and every valid cell runs. Otherwise the mode is **sampled** with
`planned_runs = min(budget.runs or ∞, floor(budget.seconds × effective_workers × 1000 /
(bars × ms_per_cell)) or ∞)`, which must be at least `2d + 1` (else `422 "budget too small for a
d-parameter surface"`).

### 5.4 Sampling

The first pass takes `⌈2/3 × planned_runs⌉` cells by a Latin hypercube over the discrete grid:
for each parameter the stratum boundaries are placed over its value list, one value per stratum
per draw, with a random permutation per parameter seeded by `seed`; a draw that lands on a
skipped or already drawn cell is redrawn (up to 10 × planned tries, then the pass is shorter and
the plan says so). The remaining budget is **refinement**: after the first pass is analysed (§7),
unexplored cells within one step of the top three plateaus' cells are taken nearest the centres
first; with no plateau, the neighbours of the ten best cells. `sampled_fraction = planned_runs /
valid_cells` is stated everywhere the experiment is shown.

### 5.5 Ways back into scope

The plan response lists, for an over-budget grid, each lever with the resulting valid-cell count
and estimate: for each parameter, **coarsen** (double the step), **narrow** (the half-length range centred on
the document's current value, clipped to the original range, same step), **freeze** (the
document's current value only); for the data, **shorten** (the last half of
the range) and **coarsen the timeframe** (the next coarser available); and **raise the budget** to
the exhaustive count. The page applies any lever as an edit to the definition and re-plans.

### 5.6 Routes

`POST /aegis/api/experiments/plan` → `{mode, grid_cells, valid_cells, skipped, skip_reasons,
planned_runs, first_pass, refinement, sampled_fraction, estimate_seconds, ms_per_cell, workers,
bars, levers: [...]}`. `POST /aegis/api/experiments` (202) creates the document and starts the
job (409 while another job runs; the document is still created, status `queued`, and can be
started later with `POST /experiments/{id}/resume`).

## 6. Execution and storage

### 6.1 Job kind

`ExperimentJob` is the runner's third kind (`name = "experiment"`). A unit is a chunk of up to 200
cells sent to the pool; `commit` appends the rows to Parquet (§6.2) and advances the counters;
`snapshot` carries counters, the mode, the sampled fraction, the learned `ms_per_cell` and the
remaining estimate, never the rows. `total_units` is fixed at start as the first-pass chunks plus
the refinement chunks the plan allows; in sampled mode the first refinement unit, when it runs,
analyses the first pass (§7) and decides the refinement cells for all refinement units, so no
unit count changes mid-job. `finalize("done")` runs the analysis and writes the report (§7–§8). The one-job rule and the 409 hold across all three kinds.

Kinds may declare `resumable = True`. `mark_lost_on_startup` sets a resumable unfinished job to
**paused** instead of `lost`. `POST /experiments/{id}/pause` uses the runner's cooperative cancel with the terminal status
`paused` instead of `cancelled`, so the job stops after the current chunk and releases the pool; `POST /experiments/{id}/resume` starts a new runner job that
continues from the first cell without a row (409 while another job runs); `POST
/experiments/{id}/cancel` keeps finished chunks and marks the experiment `cancelled`, after which
the report is still computed from what exists and says so. Status values: `queued, running,
paused, done, cancelled, failed`.

### 6.2 Files

Repository kind `experiments` holds the document `experiments/<id>.json` and its sidecar summary.
Beside it: `experiments/<id>.cells.parquet` (one row group per chunk, written with a
`pyarrow.parquet.ParquetWriter` kept open while the job runs and reopened in append mode on
resume by rewriting from the read rows plus the new group), `experiments/<id>.curves.parquet`,
`experiments/<id>.report.<n>.json` and `.md` per report.

Cells columns: `cell` (its index in the plan), `pass` (`grid | sample | refine`), `valid`,
`skip_reason`, one column per parameter path (the applied value), then for each scope in
`combined, long, short` the ten metrics as `<scope>.<metric>`, plus `elapsed_ms`. Curves
columns: `cell`, `first_time`, `last_time`, `equity` (128 `float32`, the combined realized curve
resampled by index to 128 points; fewer points are padded with the last value). Curves are written
for every cell of an experiment planned at ≤ 20,000 runs; above that, only for the cells the
report names (plateau members, peaks, cluster exemplars), written at report time by
materializing them in the pool.

### 6.3 Materialize

`POST /experiments/{id}/cells/{cell}/materialize` reruns the cell as an ordinary backtest
(kernel) from the pinned spec and parameters, persists the envelope under runs with
`experiment_id` and `cell`, and returns it. The envelope's metrics must equal the row's; a
mismatch marks the row `mismatch` and returns 500 with both values (never expected). The same
cell materialized twice returns the same `result_hash`; that identity is the proof that a row and
a run are the same computation. `strategy_id` on the envelope is the pinned document's.

## 7. Analysis: peaks to plateaus, exactly

All of it in numpy from the cells table; `d` is the number of parameters; the objective is the
experiment's unless a report recomputation names another; for `max_drawdown` the sign is flipped
so higher is always better; cells with a null objective are set aside and counted.

- **Tolerance** `τ = tolerance × (P90 − P10)` of the valid objective values. When `P90 == P10`
  the surface is flat: the report says so and makes no recommendation.
- **Neighbours.** Exhaustive: cells differing by exactly one step in exactly one parameter.
  Sampled: the `2d` nearest run cells by Euclidean distance in parameter space normalized by each
  range (ties by lower cell index); the report states this.
- **Peak.** A valid cell whose objective is ≥ every neighbour's.
- **Plateau of a peak.** Breadth-first over neighbours from the peak, admitting cells with
  objective ≥ `peak − τ`. Plateaus reached from several peaks are one plateau. A plateau
  **counts** when it has at least `2d + 1` cells.
- **Fragile peak.** A peak whose plateau does not count. **Supported peak.** A peak inside a
  counting plateau.
- **Ranking.** Counting plateaus by median objective, descending; ties by size.
- **Centre.** The plateau cell nearest (normalized Euclidean) to the plateau's parameter-wise
  median. **Cliff.** The lowest objective among the plateau's outside neighbours, reported as its
  drop below the plateau median.
- **Recommendation.** The top plateau: its centre's parameters and metrics, its supported peak
  (the best peak inside it) or none, the ranked list of all counting plateaus, and every fragile
  peak marked. With no counting plateau the recommendation is **none**: the report says the best
  cell is fragile and lists the peaks.
- **Main effects.** Per parameter and value: median, P25, P75 and count of the objective over
  cells with that value.
- **Interactions.** Per pair: the matrix of median objective by the two values; strength = the
  variance of that matrix's entries not explained by the additive main effects (residual of the
  two-way additive fit); the report shows the three strongest pairs (all pairs when `d ≤ 3`).
- **Sensitivity.** Each parameter's first-order share: variance of its main-effect medians
  divided by the variance of the objective over valid cells; and the remainder.
- **Outcome clusters.** k-means (numpy, k = 2..6, 20 restarts, seeded) on the standardized
  combined `net_return, max_drawdown, trade_count, exposure`; silhouette on at most 2,000 cells;
  reported only when valid cells ≥ 20 and the best silhouette ≥ 0.5, with each cluster's size,
  metric medians and parameter ranges; otherwise `clusters: {refused: "<reason>"}`.
- **Uncertainty.** For the recommended plateau: its interquartile range, cell count, the
  sampled fraction, and the sentence "In-sample on one symbol and range (<symbol> <timeframe>
  <start> → <end>); no out-of-sample evidence until walked forward."

## 8. Report, page, decision

### 8.1 Report

`report.<n>.json` holds `{report_id, objective, tolerance, generated_at, mode,
sampled_fraction, valid_cells, skipped, recommendation, plateaus, peaks, main_effects,
interactions, sensitivity, clusters, uncertainty, cells_named}`; `report.<n>.md` renders the same
in Markdown with the recommendation first. `POST /experiments/{id}/report` with `{objective?,
tolerance?}` recomputes from the stored cells, keeps the new report beside the old, and returns
it; `GET /experiments/{id}/report.md` serves the latest or a named one.

### 8.2 Page

Sidebar item **Experiments** (`#nav-experiments`), a third page beside Charts and the Lab.

- **List** (`#experiments-list`, rows `#exp-<id>`): name, strategy document, surface line
  ("4 parameters · 252 cells"), mode and fraction, cells done of planned, status, objective,
  decision.
- **New experiment** (`#experiment-new`) from the workspace's loaded document; with unsaved edits
  the page says "save or revert the document first" and offers both.
- **Planner** (`#experiment-planner`): the surface editor (add a parameter from the document's
  paths, both sides; `#surface-add`, rows `#surface-<n>` with start/stop/step inputs), objective,
  budget runs and seconds, tolerance, the plan line (`#experiment-plan`), the levers
  (`#lever-<kind>-<n>` buttons), Start (`#experiment-start`).
- **Running** (`#experiment-progress`): chunks, cells done of planned, cost per cell, remaining
  estimate; Pause (`#experiment-pause`), Resume (`#experiment-resume`), Cancel
  (`#experiment-cancel`).
- **Report** (`#experiment-report`): the recommendation card (`#recommendation`: centre
  parameters and metrics, supported peak, fragile peaks marked, the uncertainty statement, or the
  honest "no plateau" statement); main-effect charts (SVG, one per parameter); interaction
  heatmaps (the existing heatmap component); the sensitivity table; clusters or the refusal; the
  cells table (`#cells-table`, sortable, filter by plateau, paged); equity overlays for ticked
  cells (SVG, from curves); per cell **Materialize** (`#materialize-<cell>`) and **Use in
  workspace** (`#use-cell-<cell>`); **Recompute report** with objective and tolerance.
- **Decision** (`#decision`): accepted / rejected / deferred, a note, Save; shown with its
  timestamp. **Refine** (`#experiment-refine`) creates the child experiment and opens its planner.

### 8.3 Decision and refine

`PUT /experiments/{id}/decision` with `{verdict: "accepted" | "rejected" | "deferred", notes}`
stores `decision: {verdict, notes, decided_at}` on the document. `POST /experiments/{id}/refine`
creates a new document (status `queued`, not started) with `parent` set and the surface's ranges
narrowed to each parameter's span over the recommended plateau extended by one step each way,
the same objective, budget and tolerance. `DELETE /experiments/{id}` removes the document and its
files; 409 while it is queued, running or paused.

## 9. Hygiene folded in

The nine minors deferred from Mission 5, each test-first: union validation errors shown as the
value-error messages, not a JSON list; a saved document that no longer parses answered with 422
naming the field; the empty-grid walk-forward refusal using the skip reason; the rule editor
refusing band operators when the side has no band; `WalkForwardRequest` and `OptimizeRequest`
refusing `initial_position` and `close_at_end=false`; the P12 test asserting the carried trade
closes; parameter grid values rounded to the step's decimals; the Vela series map pruned when
handles are removed; constants matched with `re.ASCII`.

## 10. Verification and QA

- Test first for every behaviour of §4–§9 (pytest, DB-free, pool of two; vitest for the page's
  pure helpers, the reducer's experiment state and the planner's lever arithmetic).
- Contracts regenerated (`ExperimentRequest`, `Parameter`, `Surface`, `ExperimentDocument`,
  the report shape) with the staleness test.
- Acceptance: the Mission 3–5 walks on the kernel engine plus items 1–13 of §2; evidence copied
  under `docs/evidence/`.
- Milestone QA at the exact commit: numba installed and never imported by Core; kernel
  equivalence re-derived independently over HTTP (reference vs kernel on several strategies and
  carried windows); plateau, fragile and supported peaks hand-checked on a synthetic surface with
  a known answer; pause, a real worker restart and resume with no duplicated or missing cell;
  materialize hashes against direct backtests; the report's refusals; the page's honesty.
  Whole-branch review by a fresh reviewer, then one fix pass with every fix test-first.
- Record: `docs/MISSION6_EXPERIMENTS.md`; merge and push on the operator's call.

## 11. Non-goals

No NVDA or any new market data (a market-data source and its credentials are a Core-governed
mission of their own); no HA-MQI (undefined); no automatic walk-forward of the plateau (available
by hand through Use in workspace); no Core chat delivery or knowledge-graph publication; no
multi-symbol or multi-strategy experiments; no compiled indicators; no GPU; no broker path;
nothing re-enabling Triad's autonomy.

## 12. Build order

1. Kernel and engine switch; equivalence over every fixture and acceptance scenario; dependency.
2. Pool; surface contract, grid, validity, budget, planner, levers.
3. Experiment job kind, Parquet storage, pause/resume/cancel, materialize, routes.
4. Sampling (Latin hypercube, refinement).
5. Analysis and the report (JSON and Markdown), recompute.
6. Decision, refine, delete; contracts regenerated.
7. Experiments page.
8. Hygiene (§9).
9. Acceptance items, worker restart, mission record; QA, review, fix pass, merge.

## 13. Risks

| Risk | Mitigation |
|---|---|
| numba fails to install or compile on this host | the reference engine runs and says so; the mission's speed goal is then unmet and the record says it |
| Kernel results drift from the reference | one arithmetic order, bit-identical payloads asserted over every fixture and scenario; the reference stays the oracle |
| Windows process start cost and pickling | bars sent once per worker in the initializer; chunks of 200; tests use two workers |
| Parquet append on resume | rows read back and rewritten with the new group; a torn last group is dropped and its cells rerun |
| Long jobs block the runner lock | snapshots carry counters only; rows are written outside the lock |
| A 10-parameter sampled map yields no plateau | the report says so honestly and lists the peaks; refinement spends budget around the best cells |
| Clustering overclaims | refused below 20 cells or silhouette 0.5 |


## 14. Execution amendments (2026-10-13)

Recorded after the build so that this binding document matches the code; each item is a ruling
in the execution ledger and in `docs/MISSION6_EXPERIMENTS.md`.

- **§5.2 validity also covers the data.** A parameter combination whose indicator warm-up the
  engine would refuse on the planned bar count (`backtest._check_warmup`: bars ≤ warm-up) is a
  skipped cell with the reason `insufficient bars`, counted in the plan like any other skip; a
  cell the engine still refuses at run time is written as an invalid row with that reason, never
  a failed experiment. A `failed` experiment keeps its chunks and resumes like a paused one.
- **§5.3 the plan names its price source.** `Plan.price_source` is `measured` when the cost
  came from a finished experiment on this host and `starting_guess` when it is
  `KERNEL_MS_PER_BAR`; the planner prints it beside the per-cell cost. The measured price is the
  newest finished experiment's with at least 50 cells (a smaller one is priced by its workers'
  cold first cells), and a smaller one's only when nothing bigger has finished.
- **§5.6 create while another job runs.** `POST /aegis/api/experiments` answers 202 with status
  `queued` and no job id (the document is saved and resumes when the runner is free), not 409.
- **§6.1 pause and cancel.** A paused (or never-started queued) experiment can be cancelled
  without a live job: the status is written directly and report 1 is computed from the cells
  present, as it is when a running job is cancelled; delete then follows.
- **§6.2 files.** Cells and curves are one Parquet file per committed chunk under
  `experiments/<id>.cells/` and `experiments/<id>.curves/`, each written atomically (tmp +
  replace), never appended; a torn write is a leftover `.tmp` and is ignored. Reports live under
  `experiments/<id>.reports/<n>.json|md`, not beside the document.
- **§7 peaks.** A peak is a cell at or above every neighbour that beats at least one of them, or
  that sits at the surface's maximum; the bare "at or above every neighbour" made every cell of
  a flat basin a peak and one plateau then swallowed the surface. Plateaus reached from several
  peaks are one plateau: a new plateau unions every plateau it touches, not only the first.
- **§7 the flat case.** When the 10th and 90th percentiles coincide the tolerance band is empty:
  the report says so, names no plateau and lists the best cell as a fragile peak; only when every
  valid value is identical does it call the surface flat.
- **§7 clusters.** An outcome metric whose spread across cells is below 1e-6 or 1% of its mean
  magnitude is left out of the clustering; when none remains the clusters are refused with that
  reason.

- **§4.4 realised (2026-10-14).** The follow-on was carried out by Mission 7 as dependency
  isolation, not separate Core environments (operator correction 2026-10-13): one Core codebase
  and runtime; `.venv`, `.venv-triad` and `.venv-aegis` built from lock files; numba only in
  `.venv-aegis`; `tools/start_product.ps1` launches each worker on its own interpreter.
