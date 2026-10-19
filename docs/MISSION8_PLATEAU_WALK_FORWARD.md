# Mission 8 — Plateau walk-forward studies: does peaks to plateaus hold out of sample? (2026-10-15/19)

Branch `aegis/plateau-walk-forward`, cut from `main` at `31bddc8` (the plan commit; the spec at
`188c1fc`). Spec: `docs/superpowers/specs/2026-10-15-aegis-plateau-walk-forward-design.md`.
Plan: `docs/superpowers/plans/2026-10-16-aegis-plateau-walk-forward.md` (7 tasks, rulings P1–P17).
Executed natively on Opus 5.5 in one session; the ledger carried the state. The milestone QA and
the whole-branch review ran on Fable 5.1 (the operator's choice) as independent read-only agents
at `dbb15d6`; one fix pass followed (`25fba41`).

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 69 checks it with git against `31bddc8`). Exchange stays CLOSED; no broker
path; Triad suspended; the `DailySchedule` record `c99fa831` stays disabled (item 69).

## Intent

Mission 6 recommends a plateau's centre and never a lone peak. Mission 4's walk-forward
re-optimizes per window and trades the best single cell, which is the peak-picking the principle
warns against. This mission tests the method itself out of sample. In rolling windows it maps the
experiment's whole surface in-sample, chooses by peaks to plateaus, and trades the choice on the
bars that follow, beside two baselines: the peak rule and the parent's centre held fixed. It runs
on QQQ, SPY and ITOT, with each symbol walked on its own.

## Operator decisions (chat, 2026-10-15/19)

| Decision | Choice |
|---|---|
| What to test first | The plateau rule, per window |
| A window with no plateau | Stay flat and say so: no new entry; a carried position exits at the window's first bar |
| Other symbols | Each symbol walks itself |
| Approach | A new study kind built on the Experiments machinery, started from an experiment |
| Execution | Native; QA and review on Fable 5 |
| Heatmap colours (2026-10-19) | Losing money is red, always; red only for losing money |

## What was built

| Commit | Task | What |
|---|---|---|
| `46036d0` | 1 | `studies.py`: StudyRequest (default QQQ/SPY/ITOT), the per-symbol plan (windows, cells per window, runs, estimate priced from the measured experiment cost, levers of a sampled map), the refusals; repository kind `studies/<id>.json` + `studies/<id>.windows/` |
| `1afefc5` | 2 | `study_rules.py` (pure): per-side capital chains (cash, carried position, marked equity), flat windows, best cell, centre containment and normalized move, per-side run hashes, per-rule stitching on the engine's combined convention with union exposure, per-rule result hashes |
| `b8dfb54` | 3 | `Pool.run_chunk(..., window=(start, end))`: a window's cells run on that slice prepared as its own bars; `map_window` (exhaustive, or Latin hypercube + plateau refinement seeded with seed + window) |
| `1737b3e`, `2eb3576` | 4 | The report: per symbol the three rules, flat windows, one comparison sentence, stability, bounded chart curves, the window table; the cross-symbol line with caveats; the raw-archive label; Markdown |
| `1029d54` | 5 | `StudyJob`, the runner's fourth kind (resumable; one window of one symbol per unit; a pool per symbol; chains restored from the last window file), StudyStore, routes under `/aegis/api/studies`, the experiment delete refused while studies name it, contracts |
| `85030a2` | 6 | The page: Walk forward on the experiment report (planner with the live plan line, the experiment's studies with their decisions, the study view with progress, report, chart, window cells, Markdown, decision) |
| `4a4d05e` | 7 | The frozen centre comes from the parent's report on its own objective and tolerance; the document's window records keep each rule's carried in and out |
| `46e5d1c` | 7 | Acceptance items 61–69 |
| `0268885` | 7 | A two-decimal tie reads with three decimals; the page keeps the study's symbol order |
| `a782b4c` | 7 | Heatmaps: losing money is red, always (operator rule, 2026-10-19) |
| `8d110f2` | 7 | Chart: indicator lines keep one point per bar (operator report, 2026-10-19) |
| `25fba41` | fix pass | A travelling entry at window joins (both engines, the study chains); decisions refused while a study runs; the window table shows peaks, fragile and each rule's flat flag; the window cells rank best first by the objective |

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261019T120413Z.json`, run after the fix pass: **69/69 PASS, no
page errors**, 547 s in total. Items 1–60 are the Mission 3–6 walk, unchanged and passing. Items
61–69 walk spec §3:

- **61:** plan line "3 symbols · 47 windows · 11,844 runs · ≈ 3 min 17 s (measured on this host)";
  QQQ 16, SPY 16 and ITOT 15 windows of 3,493 + 873 bars; 252 cells per window, exhaustive.
- **62:** started from the page; windows done advanced 0 → 1 → 2; the status route answered in at
  most 97 ms over 32 calls.
- **63:** paused at 3 of 47 windows; worker restarted (15564 → 10928); still paused at 3; resumed
  and finished in 186.3 s; every window present once.
- **64:** the report in the page: the summary, the label, three rules × three symbols, the charts,
  the window tables.
- **65:** QQQ window 1 recomputed independently. Its 252 cells, re-analysed out of process, give
  the recorded centre cell 202. The plateau rule's long run (8 trades from $94,828, with a carried
  position) and short run (16 trades from $98,212) each equal a direct `POST /backtest` on the same
  bars, evaluate_from, capital and carry, by hash.
- **66:** an identical study reproduced all nine per-rule hashes.
- **67:** eleven refusals over HTTP, each 422 or 409 naming the problem.
- **68:** the decision is shown on the study and in its row under the experiment.
- **69:** governance unchanged.

The same walk had passed 69/69 before the fix pass (`20261019T110530Z`). The first full run of the
day (`20261019T105416Z`) scored 52/69: two 271-cell optimizations of the built-in strategy, started
in the app during the walk, held the one-job runner when item 50 started. The walk's experiment was
therefore created queued, and every experiment and study item after it lacked its parent.

**After the fix pass, the frozen centre equals one continuous run on real data.** A direct
`POST /backtest` of the frozen parameters was run from the first out-of-sample bar to the last.
Stitched and continuous agree exactly:

| Symbol | Trades | Net P&L | MAR |
|---|---|---|---|
| QQQ | 503 | $105,796 | 0.420 |
| SPY | 524 | $16,625 | 0.070 |
| ITOT | 502 | $13,238 | 0.071 |

## Results as measured (acceptance study after the fix pass, raw archive, no significance claimed)

The breakout strategy's 252-cell MAR experiment on QQQ 1h 2023–2024 (centre cell 94: Donchian 20,
RSI 21, EMA 10, SMA 30), walked on each symbol 2016-09-19 → 2026-09-18:

| Symbol | MAR plateau / peak / frozen | Net P&L plateau / peak / frozen | Trades plateau / peak / frozen | Flat windows | Plateau found · centre kept · median move |
|---|---|---|---|---|---|
| QQQ | 0.253 / 0.227 / 0.420 | $49,823 / $41,750 / $105,796 | 510 / 550 / 503 | 0 of 16 | 100% · 73% · 0.17 |
| SPY | 0.137 / 0.129 / 0.070 | $32,319 / $24,703 / $16,625 | 470 / 590 / 524 | 1 of 16 | 94% · 69% · 0.37 |
| ITOT | 0.104 / 0.059 / 0.071 | $18,859 / $9,992 / $13,238 | 419 / 617 / 502 | 1 of 15 | 93% · 58% · 0.25 |

The summary reads "plateau rule ahead of the peak rule on 3 of 3 symbols by MAR". On QQQ the
frozen centre beat both re-chosen rules. The figures before the fix pass understated the plateau
rule and the frozen centre on SPY and ITOT, where entries signalled on a window's last bar had been
dropped; the peak rule happened to have none.

## Measurements (this laptop, pool of 10)

| What | Value |
|---|---|
| Full study, 47 windows × 252 cells + 6 side runs per window | 186.3 s after resume; 209.8 s start to done including the pause and restart |
| Plan estimate | 197 s at 0.0240 ms per cell-bar (measured from the item-51 experiment) |
| Measured during the study | 0.0316 ms per cell-bar |
| Status route while running | ≤ 97 ms |

## Verification

- `tools\\verify.ps1` on the branch (2026-10-19, after Neo4j's ports were restored): lint and
  format passed. The inventory was core 557, triad 1,058 and aegis 348. All three scopes ran in
  full and passed (core 386 passed / 171 skipped; triad 634 / 424 with 209 subtests; aegis 347 /
  1). The database health check passed. It stopped at the foundation audit's "Wrong Git branch"
  check, by design; it runs on `main` after the merge.
- After the fix pass: Aegis scope 353 passed and 1 skipped; UI 75 vitest cases; `tsc` clean; the
  build succeeds; lint passes.
- **`tools\verify.ps1` on `main` after the merge (2026-10-19): exit 0, "all three scopes green"**:
  core 386 passed / 171 skipped; triad 634 / 424 (209 subtests); aegis 353 / 1. Database health,
  the foundation and secret audit, compose, whitespace and git checks passed.
- Host issue met on the way: since the 2026-10-18 reboot Windows reserved TCP 57225–57824, which
  covers Neo4j's host ports 57474 and 57687, so Docker published neither. The operator restored
  them with an elevated `net stop winnat`, recreating the container and `net start winnat`. The
  durable fix (Neo4j ports below the reserved range) is a Core configuration decision left open.

## Milestone QA (Fable 5.1, read-only, at `dbb15d6`)

**PASS_WITH_OBSERVATIONS.** QA recomputed the following independently:

- SPY window 5 with a carried long: all six side runs, by hash.
- The flat windows SPY 12 and ITOT 10: the forced exit at the first bar, by hash.
- All nine stitched hashes, from the window files.
- That `chains_in` equals the previous `chains_out` at every join.
- Every comparison sentence, the stability shares, and 30+ refusals over HTTP.
- A lifecycle with an identical twin: 6 rule hashes, 132 side hashes, 22 centres.
- The page, the heatmaps and the chart. Aegis 162, core 8 and UI 73 tests passed.

**Defect D1 (fixed):** an entry signalled on a window's last bar was dropped at the join. The
engine carried a travelling exit but no travelling entry. So the frozen chain was not one
continuous run on SPY (523 vs 524 trades) or ITOT (501 vs 502). Observations O1 and O2 are under
Deferred minors; O3 to O5 needed no action.

## Whole-branch review (Fable 5.1, `31bddc8..dbb15d6`) and fix pass

**"With fixes"**: 0 Critical, 1 Important, 9 Minor. The review confirmed the money, the resume and
the hashes against the engine's own continuous run. After re-grading by effect, four findings
entered the one fix pass (`25fba41`), each test-first:

1. **QA D1, the travelling entry.** `PendingEntry` and `BacktestSettings.initial_entry`. Both
   engines report `pending_entry` when `close_at_end` is off and an entry signals on the last bar,
   and fill a carried entry at the first evaluated bar. Study chains carry it; a flat window drops
   it. Kernel and reference stay identical (test); a window cut on an entry signal chains to the
   continuous run (test).
2. **A decision saved on a running study was lost** (the runner's next save overwrote it). It is
   now refused 409 while the study is queued or running, and the form is disabled.
3. **"Best 20 by max drawdown" listed the worst 20** (re-graded from Minor). The cells now rank
   best first by the objective.
4. **The window table lacked peaks, fragile and each rule's flat flag** (re-graded from Minor;
   spec §7 says "as §5.5"). The page and the Markdown now show them.

### Deferred minors

- The chart's time axis runs from the first to the last trade exit, not the stitched out-of-sample
  span; window marks before the first exit clamp to the left edge.
- The Markdown prints stability shares as fractions, and lists symbols alphabetically because the
  repository writes sorted JSON keys (QA O1).
- Window folders use `slug(symbol).upper()` while resume compares the document's symbol: a symbol
  with punctuation (BRK.B) would resume from window 0. Results stay correct.
- Resume re-selects the archive without comparing the pinned provenance stored in `document.data`
  (as experiments do).
- On resume, a symbol gone from the archive or a shortened range surfaces as 500 rather than 422.
- Code quality: `StudyJob.pinned` is unused; `study_document` parses twice; `run_window` re-parses
  timestamps per rule and window; `write_window` lacks `_retry`; private helpers are imported
  across modules.
- A no-plateau choice reads "no plateau: no plateau at tolerance …", and the statement embeds a
  Python dict for the best cell's parameters (QA O2, from Mission 6's analysis).

## Rulings

Plan rulings P1–P17 are in the plan. Rulings made during execution (the ledger holds each with its
cost if wrong):

1. The runner builds `list_{name}s`; for "study" it maps the plural (`PLURALS`).
2. A flat window's forced exit carries no synthetic temporal tag. The trade is marked
   `window_flat_exit: True`.
3. `run_window(spec, …, flat=False, cache=None)` always takes a spec.
4. `SideChain` carries the marked ending equity, and since the fix pass a pending entry.
5. A window's combined block holds net P&L (marked), trades, return and exposure. The full engine
   metrics are the stitched ones.
6. Exposure is the union of held bars, counted as the engine flags them.
7. `map_window` returns the experiment's cell table and the report. Workers prepare one frame per
   window slice.
8. The report carries `window_rows`. "Ahead" compares the oriented objective; a tie is not ahead; a
   null objective is "not comparable".
9. The plan carries `first_pass`/`refinement` per symbol; the document carries the provenance.
10. A resume reruns from the first window missing from the done prefix, and rebuilds the compact
    records from the window files.
11. `POST /studies` answers 409 while another job runs and leaves nothing queued.
12. `GET /studies/{id}` returns the stored runner envelope.
13. The study list, planner and view live in a Walk forward section on the experiment's report.
14. The acceptance re-analyses a window out of process and rebuilds its bars for a supplied-bars
    backtest.
15. A carried entry is the previous window's configuration's signal. It fills at the next window's
    first bar, and that window's configuration manages the position, as carried positions and
    exits already do. A flat window drops it.
16. Mission 4's walk-forward still drops a boundary entry; it is unchanged here (open item).
17. Declined-to-judge lines, ruled to stand:
    - combined CAGR/MAR/drawdown on the trade-exit curve (the engine's definition);
    - an experiment decision while running (unreachable from the page);
    - the remaining documented limits.

## Defects found during the build and fixed test-first

- The window table printed the centre as a Python dict (browser check, Task 6).
- The frozen centre came from the parent's *latest* report. Item 58 recomputes that report on net
  P&L, which would have frozen another objective's centre. It now comes from the parent's report on
  its own objective and tolerance; with none, the column is absent with the reason.
- The document's window records dropped the chains (spec §5.5).
- "0.13, against 0.13" beside a line counting SPY ahead.
- The page listed symbols alphabetically (UI fix, no test).
- **The 9 EMA and 30 SMA stopped short (operator report, 2026-10-19).** Vela aligns a line's points
  to the bars by index, and since Mission 3 the warm-up nulls had been dropped, shifting every line
  left by its warm-up. Lines now keep one point per bar.
- **Heatmaps: losing money is red, always (operator rule, 2026-10-19).** A losing cell is red
  whatever its rank. Gains rank among themselves (best third bright, the rest muted green).
  Break-even is neutral. Asked directly, the operator confirmed red only for losing money; this
  overrides the locked design mock, which colours weak winners red.

## Open items

- **The results window (operator, 2026-10-19).** The x/y matrix window was unreadable: a 16 × 17
  matrix squeezed into a 300 px column of a fixed 248 px strip. Branch `aegis/results-panel`
  (worktree `data/temp/aegis-results-panel`, cut from `dbb15d6`) holds the operator-approved fix:
  - a draggable divider (with keyboard support), whose height each viewer keeps;
  - Maximize and Restore (Esc);
  - a matrix that grows into the space, with compact values, full numbers on hover and pinned
    labels.

  It was browser-checked on a 271-cell optimization and lands after this mission merges.
- Saved optimizations cannot be reopened in the UI; the tab shows only jobs started in the page.
- Mission 4's walk-forward drops an entry signalled on a window's last bar. The engine now supports
  carrying it (`initial_entry`); the walk-forward job does not use it yet.
- Neo4j's host ports sit inside a range Windows may reserve at boot (see Verification).

## Known limits

- A window's map starts its indicators cold on the window's bars (as an experiment does). The
  out-of-sample runs use the full prior history.
- The estimate prices the six side runs per window at the metrics-only cell rate. It was close here
  (197 s planned, 186 s run).
- No significance test; few windows per symbol; the report says so beside every comparison.
- The data is the raw archive, not research-eligible; the label is on every report.
