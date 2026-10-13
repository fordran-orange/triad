# Mission 6 — Experiments: peaks to plateaus (2026-10-12/13)

Branch `aegis/experiments`, cut from `main` at `5189e12` (the plan commit; the spec at `b258962`
amended at `cabe40e`). Spec: `docs/superpowers/specs/2026-10-12-aegis-experiments-design.md`.
Plan: `docs/superpowers/plans/2026-10-12-aegis-experiments.md` (9 tasks, 14 plan rulings).
Executed natively in one session on Fable 5.1 (the session was compacted once, after Task 7's
browser check; the ledger carried the state).

Nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/` changed
(acceptance item 60 checks it with git against `5189e12`); `pyproject.toml` changed by one added
line, the optional extra `aegis = ["numba>=0.61,<0.69"]`, with the required list unchanged.
Exchange stays CLOSED; no broker path; Triad suspended; the `DailySchedule` record `c99fa831`
stays disabled (item 60).

## The principle

Stated by the operator on 2026-10-11 and binding for every analysis in this product (spec §1):

> The backtester is called peaks to plateaus. The whole point is to find the peaks, mark them as
> fragile, and move on to a region. A peak is still valid if it is supported by a plateau.

A peak is a local maximum of the objective over the surface; a peak whose neighbours fall away is
fragile; a plateau is a connected region where the objective stays within a tolerance band; the
recommendation is a plateau with its centre as the setting to use; a peak inside a plateau is
supported and stays valid. The single best cell is never the recommendation on its own.

## Operator decisions (chat, 2026-10-11/12)

| Decision | Choice |
|---|---|
| What an experiment varies | The whole control surface: 1–10 parameter paths across both sides, no cap on runs |
| Over-budget grids | Exhaustive when the grid fits the budget, sampled otherwise, with the ways back into scope offered as one-click levers |
| Whose parameters | The whole strategy, both sides, paths prefixed `long_side.` / `short_side.`; combined objective, per-side metrics kept |
| Recommendation | Peaks to plateaus (spec §1, §7) |
| Engine | B: a compiled loop with numba, the existing engine kept as the reference oracle and proven byte-identical |
| The one change outside Aegis | numba as the optional extra `aegis` in `pyproject.toml`; per-product environments recorded as a Core-governed follow-on mission (spec §4.4) |
| Hygiene | The nine Mission 5 deferred minors folded in (Task 8) |
| Execution | Native, on Fable 5.1 |

## What was built

| Task | Commit | Delivered |
|---|---|---|
| 1 Kernel and engine switch | `e6869b9` | `kernel.py` (numba `@njit` loop over both sides: fills, sizing, marked equity, drawdown, settlement, travelling exits, carried positions, end-of-data close, fixed trade buffer P10); `BacktestRequest.engine` (`kernel` default when available, `reference` otherwise); `run_prepared`/`run_metrics`; the `permitted` mask cached per data and temporal context (P9); canonical payloads byte-identical between engines on the reference strategy, carried windows and the Mission 3 identical-request hash; status reports `kernel_available` |
| 2 Surfaces and the planner | `aee3466` | `surface.py`: `Parameter`, `Surface` (1–10 distinct paths across both sides), `Budget`, mixed-radix `Grid` with per-indicator validity tables (P1), `resolve_path`, `plan()` exhaustive/sampled with the estimate priced from the last finished experiment, the levers (coarsen, narrow, freeze, shorten, coarser timeframe, raise the budget) |
| 3 Pool, job kind, storage, routes | `b8a0159` | `pool.py` (process pool, `AEGIS_POOL_WORKERS`, metrics-only worker path); the runner's third kind, resumable, one chunk of 200 cells per unit (P3); one Parquet file per committed chunk written atomically (ruling below, instead of P5); pause through the runner's cancel with a `paused` terminal status (P4); `mark_lost_on_startup` → paused; materialize as a hash-identical rerun persisted under runs with `experiment_id` and `cell`; the routes |
| 4 Sampling and refinement | `11573dd` | Latin hypercube first pass (`lhs_stratum`, seeded), `refinement_cells` around the plateaus found so far, the no-plateau fallback around the best cells |
| 5 Analysis | `b4909a2` | `analysis.py`: τ = tolerance × (P90 − P10); peaks, plateaus (BFS within τ, merged on touch, counted from 2d + 1 cells), fragile and supported peaks, the centre (nearest the parameter-wise median), the cliff, main effects, interactions (P11), sensitivity shares, k-means outcome clusters with silhouette (P12) or an honest refusal, uncertainty; the report and its Markdown (P13) |
| 6 Reports, decision, refine, contracts | `e7a0f8d` | report 1 written at finish; recompute with another objective or tolerance, every report kept and numbered; the decision (accepted / rejected / deferred with notes); refine → a queued child pinned to the parent's spec with ranges narrowed around the plateau; contracts regenerated |
| 7 Experiments page | `c2c9e34` | the list, the planner with the levers, the running view (chunks, measured cost, remaining), the report (recommendation first, plateaus, peaks with their standing, main-effect charts, interaction heatmaps, sensitivity, clusters), the sortable paged cells table with equity overlays, Materialize and Use per cell, Recompute, the decision form, Refine; a ten-metric `Objective` type beside the optimizer's `Metric` |
| 8 Hygiene (P14) | `f302c3d` | the nine Mission 5 minors, each test-first: list details rendered as the Value error messages; a document that no longer parses answers 422 naming the field (and may still be deleted); the walk-forward's empty-grid refusal names the skip reason; band operators disabled with the reason until the side has a band; `OptimizeRequest` and `WalkForwardRequest` refuse `initial_position` and `close_at_end=false`; the P12 test asserts the carried trade; grid values rounded to the step's decimals; the chart's series map pruned with its overlays; the constant regex ASCII-only |
| 9 Acceptance and this record | (this commit) | items 48–60 in `tests/products/aegis/browser_workstation.py` (item 51 restarts the worker through WMI); the runner persists a job as running from its first unit (found by the dry run); evidence under `docs/evidence/`; this record |

## Acceptance evidence

Final run `20261013T030527Z` against the worker on the Task 9 tree (restarted by item 51 from
listener PID 8716 to 31132): **60/60 PASS, no page errors, 150 s**. Evidence:
`docs/evidence/aegis-acceptance-20261013T030527Z.json`; screenshots under `logs/`. The run before
it (`20261013T030209Z`, 59/60) failed only item 52's own check, which looked for the word
"centre" where the page says "Plateau 1: use cell 94"; the check was corrected, nothing in the
product changed. Items 1–47 all ran on the kernel engine (item 48).

| Item | Evidence |
|---|---|
| 48 | `kernel_available: true`; every run envelope says `engine: kernel`; item 22 reproduced `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360` (Mission 3); item 28 reproduced `783f07c3146b…` (Mission 5 kept the prefix; the full hash is `783f07c3146b71dad6cefdf77ca17a1454e1e1e0615f96a3a07a5cde16f0cc7b`); item 34 reproduced `5d9371614fc09596e6fb2c8b4a36a7182adc0c427d7d333dab88cf337763230a` |
| 49 | On the breakout document of item 37: `long_side.indicators.donchian.length` 10–40 step 5, `long_side.indicators.rsi.length` 7–28 step 7, `short_side.indicators.ema.length` 5–15 step 5, `short_side.indicators.sma.length` 20–40 step 10, objective MAR, budget 2,000 runs → "4 parameters · 252 cells · exhaustive · ≈ 2.6 s on 10 workers at 82.0 ms per cell", priced at the measured cost of the earlier run's experiment (the 59/60 run's item 49, with no finished experiment on the worker, was priced at the starting guess, 34.9 ms per cell, and said so) |
| 50 | Started; the document read `running` at once; status route 9 ms max over 10 calls while running; progress 0 → 200 of 252 with the first chunk; the pause requested during the first chunk took effect at the chunk boundary |
| 51 | Worker restarted detached (listener 8716 → 31132); after it the experiment read "paused · 200 of 252 cells · chunk 1 of 2"; Resume → done in 10.2 s; `GET …/cells?limit=300` → 252 rows, 252 distinct indices, all valid |
| 52 | Plateau 1: 44 cells, median MAR 0.8248, cliff 1.26, centre cell 94 (donchian 20, rsi 21, ema 10, sma 30); supported peak cell 13 (donchian 10, rsi 14, ema 10, sma 30, MAR 1.039); 8 peaks, all supported, each badge naming its plateau; 4 main-effect charts; 3 interaction heatmaps; sensitivity rsi 83%, donchian 13%, sma 6%, ema 0.1%; clusters 2 groups, silhouette 0.63; uncertainty "in-sample on one symbol and range … no out-of-sample evidence until walked forward" |
| 53 | Cell 94 materialized twice → `e988ce5c0ca4d7ba182d3a71aac213557d2fea101117da9a47b163c2646906c4` both times (two run ids); a direct `POST /backtest` of the pinned spec with those parameters → the same hash; the cells row shows `hash e988ce5c0ca4` |
| 54 | Use the centre → Charts with unsaved edits; long card "price.close crosses ABOVE DONCHIAN(20).upper AND RSI(21) < 70", short card "EMA(10) crosses BELOW SMA(30)"; the backtest run on them hashed `e988ce5c0ca4…`, equal to the materialized hash |
| 55 | Decision accepted with the note "centre is robust on QQQ 1h; walk it forward before any use"; shown on the experiment and in its list row; `decision.decided_at` set |
| 56 | Refine → child `…-refined`, queued, not started, parent linked ("refines …" in the list), plan exhaustive 216 runs; donchian narrowed to 10–35, the other three unchanged (the plateau spans them) |
| 57 | The same four paths at step 1, budget 2,000 → "157,542 cells · sampled 1.3% (2,000 runs)" (first pass 1,334, refinement 666); 15 levers listed with their counts (freeze ema → 14,322; freeze sma → 7,502); both short-side freezes → "682 cells · exhaustive", levers gone |
| 58 | Recompute with net P&L at tolerance 0.10 → report 2 (1 plateau, 3 peaks all supported, the same centre); report 1 (MAR, 0.15) kept; `latest_report` 2; cells untouched (252 done, 2 chunks) |
| 59 | 422 "a surface needs at least one parameter"; 422 "at most 10 parameters"; 422 "unknown parameter path 'short_side.indicators.donchian.length'"; 422 "…ranges of whole-number parameters need integer start, stop and step"; 422 "runs must be positive"; 409 "experiment … is done, not running" for a pause; 409 "experiment …-refined is running; cancel it first" for a delete while the child ran (it was then paused at 200 of 216) |
| 60 | `human_directed` / `CLOSED`, kernel available; `DailySchedule c99fa831` disabled; no change under Core, the platform host or Triad since `5189e12`; `pyproject.toml` one added line, nothing removed |

The acceptance leaves its evidence on the worker: the stamped breakout document, the 252-cell
experiment (done, accepted) with its materialized runs, and the refined child (paused).

## Measurements (final acceptance run, this laptop)

| Measure | Mission 5 (reference engine) | Mission 6 (kernel) |
|---|---|---|
| Backtest server time, QQQ 1h, 3,493 bars, both sides | 557–805 ms | 86–171 ms (7 runs) |
| Optimizer cell, QQQ 1D, completed job | 55 ms | 17.5 ms |
| Walk-forward unit, QQQ 1D 200/50 | 33.3 ms | 21.1 ms (246 units in 5.2 s) |
| Experiment cell, QQQ 1h, per worker, pool of 10 | — | 45.9 ms after the first chunk; 98.7 ms over the whole run (two pool spin-ups); the dry run measured 49.8 ms |
| 252-cell experiment, wall | — | 4.8 s uninterrupted (dry run); 10.2 s for the 52 cells after the restart, pool start included |
| Status route while an experiment ran | — | 9 ms max over 10 calls (dry run 8 ms median, 67 max) |
| Kernel loop alone (Task 1) | ≈1,500 ms per run cold | a few ms; ≈105–150 ms per `run_prepared` with the Python around it |
| Gateway `/aegis/api/status` | 323 ms median | 374 ms median, 401 max |
| Core `/health/live` | 4 ms | 7 ms |
| Worker `/aegis/api/status` direct | 51 ms | 69 ms |

The planner's starting price is `KERNEL_MS_PER_BAR = 0.01` (34.9 ms per cell on 3,493 bars); the
measured cost on this host is 0.023–0.028 ms per cell-bar, and every plan after the first finished
experiment is priced from it.

## Verification (Task 9 tree)

| Check | Result |
|---|---|
| `pytest -q -p no:cacheprovider` (whole repository) | 1265 passed, 596 skipped, 209 subtests passed (234 s) |
| `ruff check` / `ruff format --check` (Aegis sources, Aegis tests, `tools/aegis_contracts.py`) | clean |
| `tools/aegis_contracts.py --check` | current |
| `npm test` | 56 passed (10 files) |
| `npm run build` | built |
| Acceptance | 60/60 PASS (run `20261013T030527Z`) |

## Rulings

Plan rulings P1–P14 are in the plan. Rulings made during execution (ledger), in order:

- The pool's worker runs a metrics-only path (no series, per-bar dicts or tags); a test asserts
  its 30 metrics equal `run_backtest`'s for the same cell.
- The kernel's `permitted` mask is cached per data key and temporal context, 32 entries.
- The shorten lever estimates with a whole bar count, `ceil(bars / 2)`.
- Cells and curves are one Parquet file per committed chunk, written atomically (tmp + replace),
  no appends — instead of P5's open `ParquetWriter`, whose footer is written only on close, so a
  worker death would have lost the file; a torn write is an ignored `.tmp` and resume is trivial.
- The runner publishes its terminal status before `release()`; `_snapshot` ends with the runner's
  own status while the terminal envelope persists the kind's mapped status (P4); `job_kind()` lets
  the pause route set the kind's flag before cancelling.
- The experiment contract models joined the generator in Task 3.
- `refinement_cells` takes `{cell: oriented objective | None}`; plateaus carry `cells` and
  `centre.cell`; `lhs_stratum` is the one stratum boundary rule.
- A peak is a cell at or above every neighbour that beats at least one of them, or sits at the
  surface's maximum — the spec's bare "at or above" made every cell of a flat basin a peak and one
  plateau swallowed the surface; plateaus reached from several peaks merge when they touch.
- Clustering drops an outcome metric whose spread is below 1e-6 or 1% of its mean magnitude and
  refuses when none remains; `cells_named` is every peak, the top three plateaus' cells and each
  cluster's exemplar, capped at 2,000; the report's `statement` summarises the recommendation.
- `refine()` pins the child to the parent's spec snapshot; the child is named "… · refined";
  large experiments' named-cell curves are a chunk numbered 900000 + n; recompute answers 409
  while queued or running and 422 for a bad objective or tolerance.
- Reports live under `experiments/<id>.reports/` (the repository's lister mistook loose report
  files for experiments); the page filters malformed rows; Delete no longer reloads the stale id;
  the no-plateau statement names other fragile peaks only when there are any.
- A ten-metric `Objective` type beside the optimizer's `Metric`; the planner's shorten and
  coarser-timeframe levers act on its own copy of the selection; the cells table filters by
  plateau client-side over a 5,000-row fetch; Use applies to the loaded document, else the pinned
  spec (P8).
- Task 8: `detailText` feeds the `ApiError` constructor so `detail` stays a string; a document
  that no longer parses may still be deleted; the 422 reads `strategy <id> no longer parses:
  <field>` with the id unquoted; one `plain_settings` helper gives every refusal the wording
  `settings.<field> is set by the job itself; leave it unset` (the walk-forward's `evaluate_from`
  included); `step_decimals` lives in `optimize.py` and the surface imports it; the chart adapter
  clears its module registries with the series map on destroy.
- Task 9: the runner persists a job as running when its thread starts (the document read
  `queued` until the first chunk committed, so a pause during a 4 s first chunk was refused);
  item 50 requests the pause during the first chunk and item 51 observes it after the restart;
  item 48 asserts item 28 by its recorded prefix; item 59 exercises "delete while running" on the
  refined child, leaving it paused; the acceptance finds the worker by the PID listening on 8102
  (the pid file holds the venv launcher stub).

### Lint incident (Task 7, reverted before any commit)

A shell chain broke before its scope variable was set and a bare `ruff format` reformatted 87
files outside Aegis (and 7 more by line endings). Everything was reverted with `git checkout`
and verified by `git diff --name-only` filtered to the Aegis scope (0 files) before work resumed;
linting now runs only through a script with the Aegis paths hard-coded. No commit carried any of
it (item 60 confirms the frozen trees).

## Open items

1. **Per-product environments** (spec §4.4; the operator's "yes, amend the spec and add the
   mission" on 2026-10-12): a Core-governed follow-on mission gives each product its own virtual
   environment and dependency set, so a product's compiled dependency never touches the shared
   `pyproject.toml`; until then numba stays the optional extra `aegis`, installed only on hosts
   that run the Aegis worker, and Core never imports it (architecture test).
2. The wrong-side refusal reads "unknown parameter path '<path>'"; it names the path but not that
   the indicator lives on the other side.
3. The acceptance pauses the experiment during its first chunk; a restart that interrupts a
   computing chunk is covered by `test_restart_marks_an_unfinished_experiment_paused_not_lost`,
   not by the browser walk.
4. The first plan on a fresh worker is priced at the starting guess (0.01 ms per cell-bar, about
   a third of this host's measured cost); the planner says which price it used only through the
   estimate and the measured cost appears once an experiment has finished.

## Known limits

- An experiment pins the saved spec at creation; the document may move on, and Use applies the
  cell's parameters to whatever the workspace holds (P8).
- Reports are in-sample on one symbol and range by construction; the uncertainty line says so and
  nothing claims out-of-sample evidence until the setting is walked forward.
- Sampled surfaces use the 2d nearest run cells as neighbours (P6); plateaus on them are
  provisional and the neighbour rule is printed on the report.
- Million-cell maps write about 5,000 Parquet chunk files each (one per 200 cells).
- Result and strategy hashes embed the strategy's id and name (Mission 5 limit), so the same rules
  saved under two names hash differently; identical requests reproduce.
