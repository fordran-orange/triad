# Aegis Optimization Lab v2, Phase 2: R2.5 checkpoint note (the vertical slice)

Branch `claude/zen-thompson-50e9bb`. The pool commit is `7b3bf4b`; the walk ran on the worktree with the Task 12 walk edits uncommitted on top of it, and they are committed together with this note. Date: 2026-10-28.

Plan: `docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2.md`, Task 12. Spec: `docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`:
- §9.6a, the Track A budgets;
- §9.8, scenario 30;
- §11, Phase 2c;
- §12, the charting decision.

Nothing was pushed or merged. The operator reviews this later.

## Verdict

**The §12 criteria are met on the 12,000-trial slice, so the `uplot` review does not need to open before Phase 3.** All three criteria hold:

- `charts/canvas.ts` is **299 lines** (limit 800).
- Walk item 106 (keyboard, contrast ≥ 4.5:1, nothing clipped at 1672 × 941 and 1440 × 900) **PASSES** on the real experiment.
- Every measured interaction is inside its §9.6a budget, on both the latency rows and the main-thread rule. **Zero long tasks** were counted on any label.

The tab's JS heap stayed at 13.3 and 16.9 MB, against 300 MB.

Five findings for Randall are listed under "Findings" below. None of them blocks R2.5.

## The walk

Command, run from the worktree root on the Core interpreter, against the scratch worker:

```
C:\Triad\.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:8103/aegis/ --only lab --data-root C:\Triad\data\temp\lab-scratch --pid-file logs\aegis-scratch.pid
```

Summary line: **`13/13 PASS, 0 FAIL, page errors 0`**.

- Report: `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T224912Z.json`.
- Run fields: `lab_only: true`, `lab_first_item: 98`, total 569 s.
- Worker: it serves `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\app` on `C:\Triad\data\temp\lab-scratch`. `/lab/build` agrees, with engine build `8bef56cd6730…`.

The worker was restarted through `tools\start_aegis_scratch.ps1` before the run, so the pool change (`7b3bf4b`) was live. The product worker on 8102 was never touched.

The items, numbered 98 to 110 in this block:

| # | Item | Result on the run |
|---|---|---|
| 98 | (103) Expand Lab | **PASS.** Also covers the dock overlays:<br>• `#dock-mode-long` reads `Exact slice` (a 2-parameter job);<br>• 9 `.cell-n` badges;<br>• 0 of 0 empty squares, all hatched;<br>• the dock's `.heat-grid` is 109 px tall at the default results height. |
| 99 | (104) keep state, 3 × 3 fixture | **PASS** through the refactored `lab_keep_state`. The table counted `6 of 9` before the row click. It ends with exactly one selected row, the clicked one. |
| 100 | (105) rewritten | **PASS.**<br>• Experiment: the heatmap and parallel tabs draw `#lab-heatmap-canvas` and `#lab-parallel-canvas`. The placeholders are exactly interactions, pareto and robustness, each naming Phase 3, plus the five views: 8 in all.<br>• Grid job: its parallel tab is a canvas, and its importance tab reads `Importance for a grid job: arrives in Phase 3 (plan §11)`.<br>• Bogus source: `.lab-error` with `Retry`, while `#lab-subnav`, `#lab-kpis`, `#lab-catalog`, `#lab-tabs` and `#lab-rail` stay in place. |
| 101 | (106) clipping, ≥ 11 px, contrast | **PASS**, with the bench step at both sizes. See the next section. |
| 102 | (126) workflow strip | **PASS** |
| 103 | (106b) keyboard model | **PASS** |
| 104 | (RF2/3) running experiment | **PASS** |
| 105 | (107) exact slice with no match | **PASS** |
| 106 | (108) aggregate square | **PASS** |
| 107 | (109) counts identical | **PASS**: `filter_heatmap` and `page` timed. |
| 108 | (110) brush on the 12k experiment | **PASS**: `brush` timed. |
| 109 | (104b) keep state on 12k | **PASS** |
| 110 | governance | **PASS**: Lab items 98–109 PASS, no change under the frozen paths since `1882c81`, and `/lab/build`'s `data_root` equals `/health/live`'s. |

### The bench experiment

The fixture is `lab-walk-20261028t224912z-bench`. It was made through the API on the scratch worker:

- strategy `lab-bench-10p-20261028T224912Z`;
- the ten `BENCH_SURFACE` paths;
- budget 12,000, seed 1, objective net_pnl;
- QQQ 1h, 2024-01-01 → 2025-06-30.

Its numbers:

- **Bars:** 2,603 (`lab_bench_bars`, the §9.1b case A count exactly).
- **Sampler:** `lhs+refine`, which the engine picked: a first pass of 8,000 and a refinement of 4,000.
- **Counts:** completed 12,000; invalid 0; failed 0.
- **Coverage:** 12,000 / 287,570,497,536, shown as `0.0%`.
- **Elapsed:** POST to `done` in **427.8 s** (`lab_bench_elapsed_s`). The findings report then took **61.9 s**.

Item 107's slice:
- The spec's values off the two axes are `long_side.indicators.rsi.length = 14`, `macd.params.slow = 26`, `stop_loss_pct = 2.0`, and the short side's `ema 9`, `sma 30`, `rsi 14`, `macd slow 26`, `stop 2.0`.
- They match **0 trials** in the counts view, so the exact heatmap reads `0 of 144 squares tested` (`Tested (exact) · empty = untested`).
- The toolbar still reads `12,000 of 12,000 trials` with `Linked · 0 filters`.
- ArrowDown and Enter open `untested: no trial has these values` with no trial selected.

Item 108's square, `long_side.indicators.ema.length = 15 · long_side.indicators.sma.length = 30`, shows:
- `n = 58`;
- `IQR -$8,401–$5,666 · range -$19,429–$16,983`;
- a 20-bar histogram;
- `Aggregated from tested (n = 58)`;
- 50 square trials listed.

Pin and Send are disabled with `an aggregate is not a runnable strategy`, and the key `1` pins nothing.

### Gate 3 parity sample (spec:1419)

The page's first two trials (`limit: 2`, by net_pnl, best first) were materialized through Task 6's pinned path. For each one:
- `POST …/cells/<cell>/materialize` answered 200;
- `run.data.sha256` equals the document's `data_pinned.sha256` (`ad3cdc78a91c…`, vintage `20260919T233952760505Z`);
- every `<scope>.<metric>` of the page row whose metric is one of the ten `METRICS` equals the run's metric exactly.

| trial | cell | run_id | result_hash |
|---|---|---|---|
| `exp:lab-walk-20261028t224912z-bench#7933` | 78333013756 | `fb5246a8-5434-4fa8-b573-b67dc9fdb957` | `3c7ef502260eebbbf1a4bc1550e21d27ea420f1c8358b65c6759e1ece31d6565` |
| `exp:lab-walk-20261028t224912z-bench#7169` | 150173393906 | `f99df905-e1bd-4da1-96ef-93bf57d019d1` | `736e47115b91810a2089e8ce0beb9d6746cf26de0f0365824aa6e92a029aa2b2` |

Seed 1 makes the sample the same from run to run. A dry run against an earlier bench experiment (`…223237z-bench`) picked the same two trials (#7933, #7169) and the same cells.

## Item 106 on the slice: keyboard, contrast, clipping

At each size, after the Phase 1 sweeps, the item opens the bench experiment:
- Heatmap tab, `#lab-mode-aggregate`, wait for the answered aggregate basis.
- It focuses `#optlab-page` and presses ArrowDown and Enter. Square `ema = 5 · sma = 20` opens its panel, with Pin and Send on screen.
- It takes the screenshot, checks the primary controls and sweeps the texts.

`LAB_PRIMARY` gained `#lab-mode-exact`, `#lab-stat`, `#lab-square-pin` and `.fix-value`.

At the second size, the item waits for the bench heatmap to redraw (its canvas `width` changed) before any sweep, so no wait passes on the first size's content.

| Size | Phase 1 states | Bench state |
|---|---|---|
| 1672 × 941 | 20 controls inside and on top | **31 controls** inside and on top |
| 1440 × 900 | 20 controls inside and on top | **31 controls** inside and on top |

- **Texts:** 1,346 texts checked per size, every one ≥ 11 px.
- **Contrast:** the lowest secondary contrast is `.sub` 5.50, then `.trial-table th[aria-sort=none]` 5.50, `.workflow-step[data-state=disabled]` 5.69 and `.not-built` 5.69.
- **Below 4.5:1:** only text inside disabled controls, recorded and exempt under WCAG 1.4.3:

  | Disabled control | Contrast |
  |---|---|
  | `Queue focused follow-up sweep` | 2.61 |
  | `Short`, `Both`, `Pin A`, `Pin B`, `Pin C`, `Compare pinned` | 3.26 |
  | `Long` | 4.30 |

- **Page scroll:** the page never scrolled, sideways or vertically.

**One judgment call on the clipping predicate.** The parameter catalog is a scroll list (`.lab-catalog { overflow: auto }`). With ten parameters, the lower entries' `.fix-value` inputs sit below its fold:
- at 1672 × 941, from the short-side EMA down;
- at 1440 × 900, from the long-side stop down.

A probe on the 100,000-trial demo showed the walk would report those inputs as "clipped".

So the walk now scrolls a control into view *inside the catalog list only* before measuring it. It then asserts that `window.scrollX` and `window.scrollY` are still 0, so a page-level clip can never be masked. Eleven inputs were scrolled into view across the two sizes. Without this change, a reachable control in a scroll list would fail the item. The reviewer may prefer another rule.

## §9.6a on the 12,000-trial slice (browser → scratch worker)

**Path:** Playwright → headless Chromium → the scratch worker on 8103, one host.

**Method:** each figure runs in the page's own clock (`performance.now()`):
- **Start:** a long-task `PerformanceObserver` is installed and the start is stamped, both before the interaction.
- **End:** the first animation frame on which the settle predicate holds.
- **Counting:** one more frame passes so queued observer entries arrive, then the long tasks are counted.

Each `ms` includes harness overhead that §9.6a's budgets do not allow for:
- Playwright's `fill`, or its 8-step `mouse` drag;
- the CDP round trip that starts the action;
- the per-frame polling of `wait_for_function`.

The UI's own share is therefore smaller than each figure.

| label | budget_key | ms | budget (`TRACK_A_BUDGETS_MS`) | longtasks_over_50ms | longest_ms | settled when | harness overhead in the figure |
|---|---|---|---|---|---|---|---|
| `filter_heatmap` | `filter_heatmap` | **277.1** | 400 | **0** | 0 | `Linked · 1 filter`, plus a new aggregate basis `n = 10972`, not loading | a `fill` of `10` into `.range-lo`, its CDP round trip and frame polling |
| `page` | `page` | **371.0** | 600 | **0** | 0 | the toolbar's `data-filtered` / `data-completed` moved from `[12000, 12000]` | the same fill, from the same start; polled only after the heatmap settled, so it is an upper bound when the page landed first |
| `brush` | `parallel` | **518.7** | 800 | **0** | 0 | `Linked · 1 filter`, plus a new `Aggregated: 2000 of 3027 bundles …` basis, not loading | an 8-step `page.mouse` drag (move, down, 8 moves, up) and frame polling |

The main-thread rule holds on every label: no task over 50 ms during any of the three interactions. So there is no long-task finding for the §12 decision.

For comparison, the earlier dry run (same code, against the first bench experiment, a warm Lab cache) measured:

| label | ms | long tasks |
|---|---|---|
| `filter_heatmap` | 332.5 | 0 |
| `page` | 452.2 | 0 |
| `brush` | 455.3 | 0 |

`filter_heatmap` has the least headroom: 277–333 ms of 400.

These are the slice figures on 12,000 trials. The 1M latency figures are Task 13's `explore` record, and the 1M heap is the milestone walk's.

## The tab's heap (`TRACK_A_LIMITS["browser_heap_mb"]`, 300 MB)

Both samples were taken on the **12,000-trial tab**. This is not the 1M row.

| sample | `usedJSHeapSize` (MB) | limit (MB) |
|---|---|---|
| `after_109` (filter, page, KPI; range blanked) | **13.3** | 300 |
| `after_110` (brush on the parallel coordinates, back to the heatmap, Esc) | **16.9** | 300 |

The walk's Chromium now starts with `--enable-precise-memory-info`. A probe showed that without it, Chromium's `performance.memory` is quantized and cached:
- an allocation of about 90 MB left the reading at 9.54 MB;
- with the flag, the reading went from 0.9 to 95.9 MB.

The dry run's two identical 14.5 MB samples, taken without the flag, were that cached value.

## Item 78 by hand: the Library view shares `.dock-matrix`

This is a Playwright pass, not a walk item:
- Script: `C:\Users\fordr\AppData\Local\Temp\claude\C--Triad--claude-worktrees-zen-thompson-50e9bb\47846fe8-9b60-40a1-8500-a36e70370397\scratchpad\handcheck12_item78.py`.
- Evidence: `…\scratchpad\handcheck12\item78.json`, with `item78-library-before.png` and `item78-library-after.png`.

Setup: a 3-parameter grid job (`cac88249`, lab-bench-10p's long side, EMA × SMA × RSI = 27 cells, QQQ 1h, 2024-01-02 → 2024-03-28) ran into the scratch store and opened from the Library's optimization list.

**10/10 checks passed:**
- The Library view holds the dock's `.dock-matrix`.
- The mode chip reads `Aggregated: best of the rest`.
- The basis line reads `Aggregated: best of the rest · empty = untested · Tested · Untested (hatched) · Selected · Robust plateau (Phase 3)`.
- 9 `.cell-n` badges; 0 empty squares, all hatched.
- The grid is 109 px tall.
- Switching `#matrix-cols-long` to `indicators.rsi.length` redraws the shared matrix: 9 squares with badges.
- A square's title names its best of the rest: `EMA↓ 5 / RSI→ 10 · Net P&L $382 · … · best of 3 · SMA 20 · n 3`.

One observation, outside this task. Between the select change and the matrix response, the first read caught a frame in which the column label already said RSI while the values were still SMA's (`RSI→ 20`). A follow-up that waited for the `/matrix` response (`…\scratchpad\handcheck12_item78b.py`) showed the correct `10 / 12 / 14` columns and titles. This is the Phase 1 dock component's transient state, not a stale final state.

## The screenshots against UX Pilot B and E

Walk screenshots, the viewport at item 106's bench step:
- `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T224912Z-lab-1672x941.png`
- `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T224912Z-lab-1440x900.png`

Screen E's subject is the parallel coordinates, which the walk does not photograph. So I added a hand screenshot of the bench experiment's Parallel coords tab after the walk's brush, at 1440 × 900:
- `…\scratchpad\handcheck12\parallel-1440x900-before.png`
- `…\scratchpad\handcheck12\parallel-1440x900-brushed.png`

These are not walk evidence.

**Method:** UX Pilot `get-design-preview` (read-only) for:
- `ZaslUVrP3YsPnEfVCUmi` (Screen B, "AegisQuant - Expanded Optimization Lab", 1440 × 1024);
- `g9iUzZy6mY2l7PnDTjhg` (Screen E, "AegisQuant - Parameter Families", 1440 × 1035).

Their preview PNGs were viewed in the browser pane, downscaled and zoomed by region, and compared region by region with the screenshots above. Nothing was generated, edited or commented on in the design tool.

### Screen B (Trial Lab, heatmap on the slice)

Matches:
- **Region layout:** context bar, KPI strip, parameter rail with X / Y per variable, the centre's six tabs with Maximize, the trials table under the centre, and the Intelligence rail.
- **Heatmap labelling:** the heatmap states its basis the way the design does. The design's `AGGREGATED FROM TESTED` chip matches our `Aggregated from tested (n = 12000) · Aggregated n ≥ 8 / n < 8 low`. Ours sits in a toolbar with the Exact / Aggregate toggle and the Stat picker; the design puts `Exact slice / Aggregated` in the parameter rail.
- **Values and n:** squares carry their value. The `n` is in each square's title, and in the square panel's `n = 44` line for the selected square (`Aggregated from tested (n = 44)`, IQR, range, a 20-bar histogram, `confounded by …`).
- **Untested squares** are hatched and never filled (item 107's exact slice).
- **Table:** a `Tested` state per row, `Pin A/B/C`, `Compare pinned`, and the linked chip. The toolbar reads `12,000 of 12,000 trials · Tested (exact)`.
- **Aggregate is not runnable:** the selected aggregate square cannot be pinned or sent. The design notes the same ("not a runnable strategy").

Differs, and why:
- **Colour scale:** the design uses a blue density scale with `n` per square. Ours uses the dock's tones (losses red, gains green), with the value printed when the square is wide enough. At 1440 × 900 the 12 × 12 squares are too small for text, so only colours and the confounded corners show; the values are in the titles.
- **Right column:** the design has a cell legend, mini Pareto, mini parallel coordinates and a sensitivity ranking. Our panel beside the heatmap is the selected square's distribution. Pareto and sensitivity are Phase 3. The parallel coordinates are a full tab, not a mini panel.
- **KPI strip:** ours is Trials, Valid (287,570,497,536), Planned, Coverage (`0.0%` for 12,000 of 2.87 × 10¹¹), Best and Failed. The design's Best Sharpe IS, Median OOS and Robust regions need partitions and robustness (Phases 3 and 5).
- **Table columns:** the design has Sharpe IS, OOS, Stability and a state with IS/OOS. Ours has the parameters and the Phase 2 metrics, with the trade Sharpe on layout 2.
- **Findings rail:** the report statement prints its plateau as raw `{'long_side…': 30.0, …}` dictionaries (Finding 4). The design shows short bullet findings.
- **Top bar:** unchanged from R2. The design's stage stepper is still R2's open question 1.

### Screen E (Parameter Families: the parallel coordinates)

Matches:
- **Basis wording:** the server-side bundled parallel coordinates carry E's honesty line almost verbatim. E says "Bundles are backend-computed… 0 raw lines drawn". Ours reads `Aggregated: 2000 of 9195 bundles (≥ 1 trials each) · 0 raw lines drawn`, and `2000 of 3027` after the brush.
- **Brush:** a brush on an axis draws its range box and writes the shared filter. After the brush:
  - the chip reads `Linked · 1 filter`;
  - the KPI sub line reads `3,717 filtered`;
  - the table reads `3,717 of 12,000`;
  - the heatmap `n = 3717`.

  That is E's "Brushing any chart updates scope counts…" linked behaviour.
- **Axis labels:** short names (`L ema.le…`, `S stop_lo…`) with the full path as the title.

Differs, and why:
- **Where it lives:** E is a separate view (the Parameter Families sub-nav entry) with a scope breadcrumb (`Run → Valid unique → Filtered → Brushed`), a family tree, a trellis of pairwise interactions, importance and interaction strength, a robust neighbourhood and a contributing-trials table. All of those are Phase 3. Our Parameter Families view is still the `arrives in Phase 3` placeholder. The parallel coordinates live on Trial Lab's Parallel coords tab.
- **Density:** E shows density bands ("48 bundles by density"). On 12,000 trials over ten axes at q = 4 bins, almost every bin vector holds one trial: 9,195 bundles, largest 17. So the drawn 2,000 read as a lattice of hairlines between four bin centres per axis rather than E's bands. The picture says what it is, but carries less density information than the design.
- **Axes:** E shows "12 axes shown of 18" with a family scope. Ours shows the ten active parameters (`PARALLEL_MAX_AXES = 10`), with no family scoping yet.

## Findings (for Randall; none blocks R2.5)

1. **The fixture's pace on this host.** The bench took 427.8 s from POST to `done` here, and about 565 s in the first run, against the brief's 600 s bound. The brief's "≈ 1 minute at 188 trials/s" does not hold on this laptop.
   - **Pool:** the worker fits only **4 pool workers** to the 2.9 GB of free memory, out of 10 configured.
   - **Per-trial cost:** 0.0333 ms per cell-bar, about **86.6 ms of worker time per trial**: 1.8 × §9.1b's 47.6 ms model.
   - **Before Step 0:** Task 9 measured 4.2 × with the children "system managed".
   - **After Step 0:** the pool children read **"never throttled"** (sampled during run 1).

   A slower afternoon could cross 600 s.
2. **The findings report over 12,000 trials of ten parameters takes about 62–64 s.** The first walk run failed every bench item on the request's default 30 s bound for `POST …/report`. The fixture now gives that one request 300 s. The report time is not a §9.6a row, but Phase 3 should know it.
3. **Confounding flags are everywhere on an LHS + refine sample.** In the 12 × 12 aggregate (`long ema × long sma`), 128 of 144 squares carry `confounded`, with total-variation distance ≥ 0.25 on another parameter. The most frequent are `long_side.stop_loss_pct` (73) and `short_side.stop_loss_pct` (58). The amber corners cover almost the whole heatmap in the screenshots. Phase 3's reading of aggregate squares should expect this from refinement-concentrated samples.
4. **The Findings rail prints the report's plateau as raw Python dict text** (`{'long_side.indicators.ema.length': 30.0, …}`). This is a Phase 1 report-statement formatting issue, made obvious by ten parameters.
5. **A brush does not show in the catalog's range inputs.** After a parallel-coordinates brush, the chip says `Linked · 1 filter`, but the brushed parameter's catalog inputs still show their placeholders (`5` / `60`). `RangeInputs` only syncs from the store when a range is cleared. The filter itself is right everywhere it counts.

## Host and scratch root

- **CPU:** 12th Gen Intel Core i7-1255U, 12 logical processors.
- **Memory:** 17 GB RAM, 2.94 GB free when sampled.
- **Software:** Windows 11 (10.0.26200); Python 3.12.10, numba 0.68.0, numpy 2.5.3, pyarrow 23.0.1.
- **Engine build:** `8bef56cd67307f57afe0e464ee7b7ca3ffec7bfcd4a8d964e423cabee3307b44`, taken from `lab_benchmark.host_record()` on the Aegis interpreter, read for this note only.
- **Browser:** the walk's Chromium is Playwright's headless build (HeadlessChrome/153).
- **Scratch root:** `C:\Triad\data\temp\lab-scratch`. After the walk it measured **61,834,025 bytes** (`lab_scratch_size_bytes`).
  - It holds Task 1's walk fixtures, Task 9's `demo-synthetic-100000`, both 12,000-trial bench experiments of this task (run 1's and run 2's), their walks' 9-cell fixtures and grid jobs, and the hand check's 27-cell job.
  - Nothing was deleted. Its deletion after the milestone is Q11.
- **Product store and worker:** the product store under `C:\Triad\data\aegis` and the product worker on 8102 were not used.

## Checks beside the walk

| Command (from the worktree) | Result |
|---|---|
| The engine guard set: `tests\test_aegis_experiments.py`, `test_aegis_pool.py`, `test_aegis_engine_golden.py`, `test_aegis_api.py`, `test_aegis_kernel.py`, `test_aegis_results.py`, `test_aegis_stops.py` and `test_lab_sharpe.py`, on `.venv-aegis` | `155 passed, 5 warnings in 320.49s`. The warnings are the known starlette, anyio and "Mean of empty slice" ones. |
| `tests\test_aegis_pool.py` | `8 passed in 16.00s` |
| `tests/fixtures/aegis_engine_golden.json` | unchanged (14 keys) |
| `bash tools/lint_aegis.sh` | `All checks passed!`, `92 files already formatted`, `lint_aegis (check): ok` |
| `npm test` (from `app/products/aegis/ui`) | `Test Files 32 passed (32)`, `Tests 372 passed (372)`, no stderr or warnings |
| `npm run build` | `tsc --noEmit` clean; `vite build` built in 13.22 s (`index-CILHbmFT.js`, unchanged by this task) |
| `wc -l app/products/aegis/ui/src/lab/charts/canvas.ts` | `299` |

The first walk run (`logs\aegis-acceptance-20261028T223237Z.json`) read `6/13 PASS`. Every bench item failed on Finding 2's 30 s report timeout. The bench experiment itself finished, at about 565 s.
