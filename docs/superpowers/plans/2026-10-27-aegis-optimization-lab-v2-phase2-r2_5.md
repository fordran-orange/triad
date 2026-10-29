# Aegis Optimization Lab v2, Phase 2: R2.5 checkpoint note (the vertical slice)

Branch `claude/zen-thompson-50e9bb`, 2026-10-28.

- The pool commit is `7b3bf4b`.
- The walk and this note were first committed at `0f6b45f`.
- The figures below are from the fix-round-1 walk. It ran on `0f6b45f` with the fix-round-1 edits on top, uncommitted; they are committed together with this revision of the note.

Plan: `docs/superpowers/plans/2026-10-27-aegis-optimization-lab-v2-phase2.md`, Task 12.

Spec sections (`docs/AEGIS_OPTIMIZATION_LAB_V2_IMPLEMENTATION_PLAN.md`):
- §9.6a, the Track A budgets;
- §9.8, scenario 30;
- §11, Phase 2c;
- §12, the charting decision.

Nothing was pushed or merged.

**R2.5 passed** by Randall on 2026-10-29 ("Pass R2.5, go"), with the five findings below read. The DSR worked-example test stays the pinned formula check; R2's question 1 (the top bar against the design's stepper) is answered at R3.

## Verdict

**The §12 criteria are met on the 12,000-trial slice, so the `uplot` review does not need to open before Phase 3.** All three hold:

- `charts/canvas.ts` is **299 lines**, against the limit of 800.
- Walk item 106 **PASSES** on the real experiment: keyboard, contrast ≥ 4.5:1, nothing clipped at 1672 × 941 and 1440 × 900.
- Every timed interaction is inside its §9.6a budget:
  - The five rows the slice can time are `exact_slice`, `stat_change`, `filter_heatmap`, `page` and `parallel`.
  - Both the latency rows and the main-thread rule hold: **zero long tasks** on every label.
  - The browser was confirmed to observe `longtask` (`lab_longtask_supported: true`), so the zeros are observed zeros.
  - Three §9.6a rows are not timed by the walk: `open`, `open_cold` and `progress_poll`. See the §9.6a section below.

The tab's JS heap stayed at 12.2 and 12.9 MB, against 300 MB.

Five findings for Randall are listed under "Findings". None of them blocks R2.5.

## The walk

Command, run from the worktree root on the Core interpreter, against the scratch worker:

```
C:\Triad\.venv\Scripts\python.exe tests\products\aegis\browser_workstation.py --base http://127.0.0.1:8103/aegis/ --only lab --data-root C:\Triad\data\temp\lab-scratch --pid-file logs\aegis-scratch.pid
```

Summary line: **`13/13 PASS, 0 FAIL, page errors 0`**.

- **Report:** `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T232955Z.json`.
- **Run fields:** `lab_only: true`, `lab_first_item: 98`, `lab_longtask_supported: true`, total 571 s.
- **Worker:** it serves `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\app` on `C:\Triad\data\temp\lab-scratch`. `/lab/build` agrees, with engine build `8bef56cd6730…`.

The worker was restarted through `tools\start_aegis_scratch.ps1` before the run, so the pool change (`7b3bf4b`) was live. The product worker on 8102 was never touched.

The earlier evidence runs, superseded:

| Report | Result | Why superseded |
|---|---|---|
| `logs\aegis-acceptance-20261028T224912Z.json` | 13/13 | three timed labels, and the walk's old item 106 scroll mechanism |
| `logs\aegis-acceptance-20261028T223237Z.json` | 6/13 | see Finding 2 |

The items, numbered 98 to 110 in this block:

| # | Item | Result on the run |
|---|---|---|
| 98 | (103) Expand Lab | **PASS.** It also checks the dock overlays:<br>• `#dock-mode-long` reads `Exact slice` (a 2-parameter job).<br>• 9 `.cell-n` badges.<br>• The `.heat-grid` is 109 px tall at the default results height.<br>• The hatch check (`empty == hatched`) passed as **0 == 0**, because this 9-cell grid has no untested square. **The dock's untested-square hatching is therefore not exercised in a browser this phase.** Item 78's hand check below also had 0 empty squares. |
| 99 | (104) keep state, 3 × 3 fixture | **PASS** through the refactored `lab_keep_state`. The table counted `6 of 9` before the row click. The item ends with exactly one selected row, the clicked one. |
| 100 | (105) rewritten | **PASS.**<br>• Experiment: the heatmap and parallel tabs draw `#lab-heatmap-canvas` and `#lab-parallel-canvas`. The placeholders are exactly interactions, pareto and robustness, each naming Phase 3, plus the five views: 8 in all.<br>• Grid job: its parallel tab is a canvas, and its importance tab reads `Importance for a grid job: arrives in Phase 3 (plan §11)`.<br>• Bogus source: `.lab-error` with `Retry`, while `#lab-subnav`, `#lab-kpis`, `#lab-catalog`, `#lab-tabs` and `#lab-rail` stay in place. |
| 101 | (106) clipping, ≥ 11 px, contrast | **PASS**, with the bench step at both sizes. See the item 106 section. |
| 102 | (126) workflow strip | **PASS** |
| 103 | (106b) keyboard model | **PASS** |
| 104 | (RF2/3) running experiment | **PASS** |
| 105 | (107) exact slice with no match | **PASS**, with `exact_slice` timed. |
| 106 | (108) aggregate square | **PASS**, with `stat_change` timed. |
| 107 | (109) counts identical | **PASS**, with `filter_heatmap` and `page` timed. |
| 108 | (110) brush on the 12k experiment | **PASS**, with `brush` (the `parallel` row) timed. |
| 109 | (104b) keep state on 12k | **PASS** |
| 110 | governance | **PASS.** Lab items 98–109 pass, nothing under the frozen paths changed since `1882c81`, and `/lab/build`'s `data_root` equals `/health/live`'s. |

### The bench experiment

The experiment is `lab-walk-20261028t232955z-bench`. It was made through the API on the scratch worker:

- **Strategy:** `lab-bench-10p-20261028T232955Z`.
- **Surface:** the ten `BENCH_SURFACE` paths.
- **Budget:** 12,000, seed 1, objective net_pnl.
- **Data:** QQQ 1h, 2024-01-01 → 2025-06-30.

What it produced:

- **Bars:** 2,603 (`lab_bench_bars`), exactly the §9.1b case A count.
- **Sampler:** `lhs+refine`, which the engine picked: a first pass of 8,000 and a refinement of 4,000.
- **Counts:** 12,000 completed, 0 invalid, 0 failed.
- **Coverage:** 12,000 / 287,570,497,536, shown as `0.0%`.
- **Timing:**
  - POST to `done` took **424.0 s** (`lab_bench_elapsed_s`). The fixture's bound is `LAB_BENCH_WAIT_S = 1,800 s`.
  - The findings report then took **61.5 s**.

**Item 107's slice** is the spec's values off the two axes:
- long side: `long_side.indicators.rsi.length = 14`, `macd.params.slow = 26`, `stop_loss_pct = 2.0`;
- short side: `ema 9`, `sma 30`, `rsi 14`, `macd slow 26`, `stop 2.0`.

These match **0 trials** in the counts view, and the page agrees:
- The exact heatmap reads `0 of 144 squares tested` (`Tested (exact) · empty = untested`).
- The toolbar still reads `12,000 of 12,000 trials` with `Linked · 0 filters`.
- ArrowDown and Enter open `untested: no trial has these values`, with no trial selected.

The canvas's untested squares are on screen here. Their hatch fill is drawn, but the walk does not check it pixel by pixel.

**Item 108's square** is `long_side.indicators.ema.length = 15 · long_side.indicators.sma.length = 30`:
- `n = 58`;
- `IQR -$8,401–$5,666 · range -$19,429–$16,983`;
- a 20-bar histogram;
- `Aggregated from tested (n = 58)`;
- 50 square trials listed.

Pin and Send are disabled with `an aggregate is not a runnable strategy`, and the key `1` pins nothing.

### Gate 3 parity sample (spec:1419)

The fixture took the page's first two trials (`limit: 2`, by net_pnl, best first) and materialized them through Task 6's pinned path. For each one:

- `POST …/cells/<cell>/materialize` answered 200.
- `run.data.sha256` equals the document's `data_pinned.sha256` (`ad3cdc78a91c…`, vintage `20260919T233952760505Z`).
- The run's metrics equal the page row's values exactly, but only for **4 of the 30** scope × metric pairs (`compared: 4`, `compared_of: 30`). The page view projects only the combined objective and its `PAGE_VALUES` columns:
  - `combined.net_pnl`;
  - `combined.max_drawdown`;
  - `combined.trade_count`;
  - `combined.exposure`.

  The other 26 pairs are not in the row to compare. The server's own `materialize` checks all 30 against the stored row before it answers 200.

| trial | cell | run_id | result_hash | compared |
|---|---|---|---|---|
| `exp:lab-walk-20261028t232955z-bench#7933` | 78333013756 | `8bb3a7dd-957d-4fd3-9379-3eac435175ce` | `f497ceeb02cb97874b4044106cd07aa5f1d677f50f6921cbfc0f3291a1a5d7be` | 4 of 30 |
| `exp:lab-walk-20261028t232955z-bench#7169` | 150173393906 | `3df52b73-dc8f-4c10-bcb3-b9b3944bbc54` | `d08af0fe7282de68883c4c23da40ad37accf390d0f481a9c3a8b3d1f2f5faba3` | 4 of 30 |

Seed 1 makes the sample the same from run to run: every bench experiment so far picked trials #7933 and #7169, at the same cells.

The result hashes differ between runs and are expected to. The hashed payload includes the strategy document, and each walk's strategy carries that walk's stamp in its id and name (`lab-bench-10p-20261028t232955z`); the metrics are what match.

## Item 106 on the slice: keyboard, contrast, clipping

At each size, the item first goes through the Phase 1 states:
- the grid job;
- the 3 × 3 fixture with a row selected;
- Variable Intelligence;
- Run Monitor;
- the windowing on `demo-synthetic-100000`.

Then it opens the bench experiment. At the first size, this is where the 12,000-trial fixture is made, so a fixture failure leaves the Phase 1 checks done. With the bench open, the item:
1. switches to the Heatmap tab, clicks `#lab-mode-aggregate` and waits for the answered aggregate basis;
2. focuses `#optlab-page` and presses ArrowDown and Enter, which opens square `ema = 5 · sma = 20` with Pin and Send on screen;
3. takes the screenshot, checks the primary controls and sweeps the texts.

`LAB_PRIMARY` gained `#lab-mode-exact`, `#lab-stat`, `#lab-square-pin` and `.fix-value`.

At the second size, the item waits for the bench heatmap to be redrawn (its canvas `width` changes) before any sweep, so no wait can pass on the first size's content.

| Size | Phase 1 states | Bench state |
|---|---|---|
| 1672 × 941 | 20 controls inside and on top | **31 controls** inside and on top |
| 1440 × 900 | 20 controls inside and on top | **31 controls** inside and on top |

- **Text size:** 1,346 texts checked per size, all ≥ 11 px.
- **Lowest secondary contrast:** `.sub` 5.50, `.trial-table th[aria-sort=none]` 5.50, `.workflow-step[data-state=disabled]` 5.69 and `.not-built` 5.69.
- **Below 4.5:1:** only text inside disabled controls, recorded and exempt under WCAG 1.4.3:

  | Disabled control | Contrast |
  |---|---|
  | `Queue focused follow-up sweep` | 2.61 |
  | `Short`, `Both`, `Pin A`, `Pin B`, `Pin C`, `Compare pinned` | 3.26 |
  | `Long` | 4.30 |

**The rule for a designed scroll list:** a control the user reaches by scrolling the list is not clipped.

- **The catalog is a scroll list.** The parameter catalog is `.lab-catalog { overflow: auto }`. With ten parameters, the lower entries' `.fix-value` inputs sit below its fold:
  - at 1672 × 941, from the short-side EMA down;
  - at 1440 × 900, from the long-side stop down.
- **How the walk reaches them.** The walk scrolls **the catalog list alone** by the control's overhang, never with `scrollIntoView`. `scrollIntoView` would also scroll `overflow: hidden` ancestors such as `.optlab-main`. Only then does it measure the control.
- **What the walk asserts.** Before the checks, it records the scroll offsets of every other element on the page (`scrollTop` / `scrollLeft`) and the window's (`scrollX` / `scrollY`). Afterwards it asserts that none of them moved.
  - This assertion runs before the clipping assertion, so a page or ancestor scroll is reported as itself.
  - **What this guarantees:** the only thing scrolled to reach a control is its own catalog list. A control that is clipped by the page or by any ancestor, rather than below the list's fold, still fails.
- **On this run:** eleven inputs were brought into view this way across the two sizes, and no other element or the window moved.

## §9.6a on the 12,000-trial slice (browser → scratch worker)

**Path:** Playwright → headless Chromium → the scratch worker on 8103, on one host.

**Method.** Each figure is measured in the page's own clock (`performance.now()`):
- A long-task `PerformanceObserver` is installed before the interaction, and the start is stamped then. The install also checks `PerformanceObserver.supportedEntryTypes.includes('longtask')`; it was `true`, recorded as `lab_longtask_supported`.
- The figure ends on the first animation frame where the settle predicate holds.
- One more frame passes, so that queued observer entries arrive, and then the long tasks are counted.

**Harness overhead.** Every `ms` includes overhead the §9.6a budgets do not allow for:
- Playwright's `click`, `select_option`, `fill` or 8-step `mouse` drag;
- the CDP round trip that starts the action;
- the per-frame polling of `wait_for_function`.

The UI's own share is therefore smaller than each figure.

| label | budget_key | ms | budget (`TRACK_A_BUDGETS_MS`) | longtasks_over_50ms | longest_ms | settled when | harness overhead in the figure |
|---|---|---|---|---|---|---|---|
| `exact_slice` | `exact_slice` | **99.8** | 300 | **0** | 0 | `0 of 144 squares tested` and `Tested (exact)` from the exact answer, not loading (from an answered aggregate matrix) | a `click` on `#lab-mode-exact` and frame polling |
| `stat_change` | `stat_change` | **180.5** | 300 | **0** | 0 | `#lab-stat` reads `median`, the basis has an `n`, and `data-loading` is back to `false`. The change renders the new key's pending state in the same render as the picker, so `false` means the median answer is in. | a `select_option` and frame polling |
| `filter_heatmap` | `filter_heatmap` | **225.6** | 400 | **0** | 0 | `Linked · 1 filter`, plus a new aggregate basis `n = 10972`, not loading | a `fill` of `10` into `.range-lo` and frame polling |
| `page` | `page` | **315.9** | 600 | **0** | 0 | the toolbar's `data-filtered` / `data-completed` moved from `[12000, 12000]` | the same fill, from the same start. It is polled only after the heatmap settled, so it is an upper bound if the page landed first. |
| `brush` | `parallel` | **494.9** | 800 | **0** | 0 | `Linked · 1 filter`, plus a new `Aggregated: 2000 of 3027 bundles …` basis, not loading | an 8-step `page.mouse` drag (move, down, 8 moves, up) and frame polling |

The main-thread rule holds on all five labels: no task over 50 ms during any interaction. So there is no long-task finding for the §12 decision.

Earlier runs of the three Task 12 labels, for comparison:

| Run | `filter_heatmap` | `page` | `brush` | Long tasks |
|---|---|---|---|---|
| `…224912Z` | 277.1 ms | 371.0 ms | 518.7 ms | 0 |
| Dry run, warm cache | 332.5 ms | 452.2 ms | 455.3 ms | 0 |

`filter_heatmap` has the least headroom: 226–333 ms of 400.

**§9.6a rows the walk does not time:**
- `open` and `open_cold`: opening a source. The Lab's open runs the experiment list, the document, the summary and the first page and matrix, with no single settle point the walk owns. These rows are `lab_benchmark.py explore`'s HTTP figures (Task 13's 1M record).
- `progress_poll`: a server-time row, measured by `execute` (Task 9) and `explore`, not in the browser.

These are the slice figures on 12,000 trials. The 1M latency figures are Task 13's `explore` record, and the 1M heap is the milestone walk's.

## The tab's heap (`TRACK_A_LIMITS["browser_heap_mb"]`, 300 MB)

Both samples were taken on the **12,000-trial tab**. This is not the 1M row.

| sample | `usedJSHeapSize` (MB) | limit (MB) |
|---|---|---|
| `after_109` (filter, page, KPI; range blanked) | **12.2** | 300 |
| `after_110` (brush on the parallel coordinates, back to the heatmap, Esc) | **12.9** | 300 |

The walk's Chromium starts with `--enable-precise-memory-info`. A probe showed why. Without the flag, Chromium's `performance.memory` is quantized and cached, so an allocation of about 90 MB left the reading at 9.54 MB. With the flag, the reading went from 0.9 to 95.9 MB.

## Item 78 by hand: the Library view shares `.dock-matrix`

This is a Playwright pass, not a walk item. Its evidence sits beside the walk reports in `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\`:

- `aegis-handcheck-item78-20261028T230000Z.json`: the checks and the before / after states.
- `aegis-handcheck-item78-20261028T230000Z-before.png` and `…-after.png`: the screenshots.
- `aegis-handcheck-item78-20261028T230000Z.py`: the script.
- `aegis-handcheck-item78-20261028T230000Z-followup.py` and `…-followup.txt`: the follow-up and its output.

The setup: a 3-parameter grid job (`cac88249`) was run into the scratch store. It uses lab-bench-10p's long side with EMA × SMA × RSI (27 cells) on QQQ 1h, 2024-01-02 → 2024-03-28. It was then opened from the Library's optimization list.

**10/10 checks passed:**
- The Library view holds the dock's `.dock-matrix`.
- The mode chip reads `Aggregated: best of the rest`.
- The basis line reads `Aggregated: best of the rest · empty = untested · Tested · Untested (hatched) · Selected · Robust plateau (Phase 3)`.
- There are 9 `.cell-n` badges.
- The grid is 109 px tall.
- Switching `#matrix-cols-long` to `indicators.rsi.length` redraws the shared matrix: 9 squares with badges.
- A square's title names its best of the rest: `EMA↓ 5 / RSI→ 10 · Net P&L $382 · … · best of 3 · SMA 20 · n 3`.

This job also has **0 empty squares**, so the hatch rule passed as 0 == 0 here too and is not exercised.

One observation, outside this task. Between the select change and the matrix response, the first pass read a frame in which the column label already said RSI while the values were still SMA's (`RSI→ 20`). The follow-up waited for the `/matrix` response. After it:
- the columns read `10 / 12 / 14`;
- the square titles read `RSI→ 10 / 12 / 14`.

This is the Phase 1 dock component's transient state, not a stale final state.

## The screenshots against UX Pilot B and E

The walk's screenshots are the viewport at item 106's bench step:
- `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T232955Z-lab-1672x941.png`
- `C:\Triad\.claude\worktrees\zen-thompson-50e9bb\logs\aegis-acceptance-20261028T232955Z-lab-1440x900.png`

Screen E's subject is the parallel coordinates, which the walk does not photograph. So I added two hand screenshots of the bench experiment's Parallel coords tab at 1440 × 900, before and after the walk's brush. They are not walk evidence:
- `logs\aegis-handcheck-parallel-20261028T230000Z-1440x900-before.png`
- `logs\aegis-handcheck-parallel-20261028T230000Z-1440x900-brushed.png`

Both were taken on the previous run's bench experiment, `…224912z-bench`. The same seed gives the same trials.

**Method.** I used UX Pilot `get-design-preview` (read-only) for two designs:
- `ZaslUVrP3YsPnEfVCUmi`: Screen B, "AegisQuant - Expanded Optimization Lab", 1440 × 1024.
- `g9iUzZy6mY2l7PnDTjhg`: Screen E, "AegisQuant - Parameter Families", 1440 × 1035.

I viewed their preview PNGs in the browser pane, downscaled and zoomed by region, and compared them region by region with the screenshots above. Nothing was generated, edited or commented on in the design tool.

### Screen B (Trial Lab, heatmap on the slice)

Matches:
- **Region layout:** context bar, KPI strip, parameter rail with X / Y per variable, the centre's six tabs with Maximize, the trials table under the centre, and the Intelligence rail.
- **Basis label:** the heatmap states its basis as the design does.
  - The design has an `AGGREGATED FROM TESTED` chip.
  - Ours reads `Aggregated from tested (n = 12000) · Aggregated n ≥ 8 / n < 8 low`, in a toolbar with the Exact / Aggregate toggle and the Stat picker. The design puts `Exact slice / Aggregated` in the parameter rail instead.
- **Square values and `n`:** squares carry their value, and the `n` is in each square's title. The selected square's panel shows `n = 44`, `Aggregated from tested (n = 44)`, the IQR, the range, a 20-bar histogram and `confounded by …`.
- **Untested squares** are hatched and never filled (item 107's exact slice).
- **Table:** each row carries a `Tested` state, with `Pin A/B/C`, `Compare pinned` and the linked chip. The toolbar reads `12,000 of 12,000 trials · Tested (exact)`.
- **No runnable aggregate:** the selected aggregate square cannot be pinned or sent, as the design notes ("not a runnable strategy").

Differs, and why:
- **Colour scale:** the design uses a blue density scale with `n` per square. Ours uses the dock's tones (losses red, gains green), with the value printed where the square is wide enough. At 1440 × 900 the 12 × 12 squares are too small for text, so only the colours and the confounded corners show. The values are in the titles.
- **Right column:** the design has a cell legend, mini Pareto, mini parallel coordinates and a sensitivity ranking. Our panel beside the heatmap is the selected square's distribution.
  - Pareto and sensitivity are Phase 3.
  - The parallel coordinates are a full tab, not a mini panel.
- **KPI strip:** ours is Trials, Valid (287,570,497,536), Planned, Coverage (`0.0%`), Best and Failed. The design's Best Sharpe IS, Median OOS and Robust regions need partitions and robustness (Phases 3 and 5).
- **Table columns:** the design has Sharpe IS, OOS, Stability and an IS/OOS state. Ours has the parameters and the Phase 2 metrics.
- **Findings rail:** ours prints the report's plateau as raw dict text (Finding 4). The design has short bullet findings.
- **Top bar:** unchanged from R2. The design's stage stepper is still R2's open question 1.

### Screen E (Parameter Families: the parallel coordinates)

Matches:
- **Basis line:** E's honesty line is carried almost verbatim. E says "Bundles are backend-computed… 0 raw lines drawn". Ours reads `Aggregated: 2000 of 9195 bundles (≥ 1 trials each) · 0 raw lines drawn`, and `2000 of 3027` after the brush.
- **Linked brushing:** a brush on an axis draws its range box and writes the shared filter, and every count follows — E's "Brushing any chart updates scope counts…". After the brush:
  - the chip reads `Linked · 1 filter`;
  - the KPI sub line reads `3,717 filtered`;
  - the table reads `3,717 of 12,000`;
  - the heatmap shows `n = 3717`.
- **Axis labels:** short names (`L ema.le…`, `S stop_lo…`), with the full path as the title.

Differs, and why:
- **Where it lives:** E is a separate view (the Parameter Families sub-nav entry). It has a scope breadcrumb (`Run → Valid unique → Filtered → Brushed`), a family tree, a trellis of pairwise interactions, importance and interaction strength, a robust neighbourhood and a contributing-trials table. All of those are Phase 3. Our Parameter Families view is still the `arrives in Phase 3` placeholder, and the parallel coordinates live on Trial Lab's Parallel coords tab.
- **Density:** E shows density bands ("48 bundles by density"). On 12,000 trials over ten axes at q = 4 bins, almost every bin vector holds one trial: 9,195 bundles, the largest of 17. So the 2,000 drawn bundles read as a lattice of hairlines between four bin centres per axis, not as E's bands. The picture says what it is, but it carries less density information than the design.
- **Axes:** E shows "12 axes shown of 18" within a family scope. Ours shows the ten active parameters (`PARALLEL_MAX_AXES = 10`), with no family scoping yet.

## Findings (for Randall; none blocks R2.5)

1. **The fixture's pace on this host.** The bench took 424.0 s from POST to `done` on this run. Earlier runs took 427.8 s and about 565 s.
   - The brief's "≈ 1 minute at 188 trials/s" does not hold on this laptop, which misses it by 7–9×.
   - Only **4 pool workers** fit in the 2.9 GB of free memory, out of 10 configured.
   - At 0.0333 ms per cell-bar, each trial costs about **86.6 ms of worker time**: 1.8 × §9.1b's 47.6 ms model. Before Step 0 the cost was 4.2 ×.
   - The pool children read **"never throttled"** after Step 0.
   - The fixture's wait is now `LAB_BENCH_WAIT_S = 1,800 s` (ruling 1), about 3 × the slowest run observed. The walk still never reuses an existing bench experiment.
2. **The findings report over 12,000 trials of ten parameters takes about 62 s** (61.5–64 s). The first walk run failed every bench item on the request's default 30 s bound for `POST …/report`. The fixture now gives that one request 300 s. The report time is not a §9.6a row, but Phase 3 should know it.
3. **Confounding flags are everywhere on an LHS + refine sample.** In the 12 × 12 aggregate (`long ema × long sma`), 128 of 144 squares carry `confounded`: the total-variation distance is ≥ 0.25 on another parameter. The most frequent are `long_side.stop_loss_pct` (73 squares) and `short_side.stop_loss_pct` (58). The amber corners cover almost the whole heatmap in the screenshots. Phase 3's reading of aggregate squares should expect this from refinement-concentrated samples.
4. **The Findings rail prints the report's plateau as raw Python dict text** (`{'long_side.indicators.ema.length': 30.0, …}`). This is a Phase 1 report-statement formatting issue, made obvious by ten parameters.
5. **A brush does not show in the catalog's range inputs.** After a parallel-coordinates brush, the chip says `Linked · 1 filter`, but the brushed parameter's catalog inputs still show their placeholders (`5` / `60`). `RangeInputs` only syncs from the store when a range is cleared. The filter itself is right everywhere it counts.

## Host and scratch root

**Host:**
- **CPU:** 12th Gen Intel Core i7-1255U, 12 logical processors.
- **Memory:** 17 GB RAM, 2.94 GB free when sampled.
- **OS:** Windows 11 (10.0.26200).
- **Python stack:** Python 3.12.10, numba 0.68.0, numpy 2.5.3, pyarrow 23.0.1.
- **Engine build:** `8bef56cd67307f57afe0e464ee7b7ca3ffec7bfcd4a8d964e423cabee3307b44`, from `lab_benchmark.host_record()` on the Aegis interpreter, read for this note only.
- **Browser:** the walk's Chromium is Playwright's headless build (HeadlessChrome/153).

**Scratch root:** `C:\Triad\data\temp\lab-scratch`.
- **Size:** after this walk it measured **69,565,718 bytes** (`lab_scratch_size_bytes`).
- **It holds:**
  - Task 1's walk fixtures and Task 9's `demo-synthetic-100000`;
  - this task's three 12,000-trial bench experiments, one per evidence run;
  - the walks' 9-cell fixtures and grid jobs;
  - the item 78 hand check's 27-cell job.
- **Deletion:** nothing was deleted here. Its deletion after the milestone is Q11.

The product store under `C:\Triad\data\aegis` and the product worker on 8102 were not used.

## Checks beside the walk

| Command (from the worktree) | Result |
|---|---|
| The engine guard set (`tests\test_aegis_experiments.py`, `test_aegis_pool.py`, `test_aegis_engine_golden.py`, `test_aegis_api.py`, `test_aegis_kernel.py`, `test_aegis_results.py`, `test_aegis_stops.py`, `test_lab_sharpe.py`) on `.venv-aegis`, at Step 0 | `155 passed, 5 warnings in 320.49s`. The warnings are the known starlette, anyio and "Mean of empty slice" ones. |
| `tests\test_aegis_pool.py`, fix round 1 | `9 passed in 15.44s`. It includes the new `test_init_worker_opts_the_process_out_of_power_throttling_first`, the Step 0 guard. |
| `tests/fixtures/aegis_engine_golden.json` | unchanged (14 keys) |
| `bash tools/lint_aegis.sh` | `All checks passed!`, `92 files already formatted`, `lint_aegis (check): ok` |
| `npm test` (from `app/products/aegis/ui`) | `Test Files 32 passed (32)`, `Tests 372 passed (372)`, with no stderr and no warnings |
| `npm run build` | `tsc --noEmit` clean; `vite build` built in 13.22 s (`index-CILHbmFT.js`, unchanged by this task) |
| `wc -l app/products/aegis/ui/src/lab/charts/canvas.ts` | `299` |
