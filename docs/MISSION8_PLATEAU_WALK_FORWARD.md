# Mission 8 — Plateau walk-forward studies: does peaks to plateaus hold out of sample? (2026-10-15/19)

Branch `aegis/plateau-walk-forward`, cut from `main` at `31bddc8` (the plan commit; the spec at
`188c1fc`). Spec: `docs/superpowers/specs/2026-10-15-aegis-plateau-walk-forward-design.md`.
Plan: `docs/superpowers/plans/2026-10-16-aegis-plateau-walk-forward.md` (7 tasks, rulings P1–P17).
Executed natively on Opus 5.5 in one session; the ledger carried the state.

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

## Operator decisions (chat, 2026-10-15)

| Decision | Choice |
|---|---|
| What to test first | The plateau rule, per window |
| A window with no plateau | Stay flat and say so: no new entry; a carried position exits at the window's first bar |
| Other symbols | Each symbol walks itself |
| Approach | A new study kind built on the Experiments machinery, started from an experiment |
| Execution | Native |

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

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261019T110530Z.json`: **69/69 PASS, no page errors**, 593 s in
total. Items 1–60 are the Mission 3–6 walk, unchanged and passing. Items 61–69 walk spec §3:

- **61:** plan line "3 symbols · 47 windows · 11,844 runs · ≈ 3 min 24 s (measured on this host)";
  QQQ 16, SPY 16 and ITOT 15 windows of 3,493 + 873 bars; 252 cells per window, exhaustive.
- **62:** started from the page; windows done advanced 0 → 1 → 2; the status route answered in at
  most 59 ms over 35 calls.
- **63:** paused at 3 of 47 windows; worker restarted (19264 → 10928); still paused at 3; resumed
  and finished in 207.6 s; every window present once.
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

The first full run (`20261019T105416Z`) scored 52/69. Two 271-cell optimizations of the built-in
9 EMA / 30 SMA strategy, not started by the walk, held the one-job runner when item 50 started.
The walk's experiment was therefore created queued, and every experiment and study item after it
lacked its parent. The rerun with the runner free passed all 69.

## Results as measured (acceptance study, raw archive, no significance claimed)

The breakout strategy's 252-cell MAR experiment on QQQ 1h 2023–2024 (centre cell 94: Donchian 20,
RSI 21, EMA 10, SMA 30), walked on each symbol 2016-09-19 → 2026-09-18:

| Symbol | MAR plateau / peak / frozen | Net P&L plateau / peak / frozen | Trades plateau / peak / frozen | Flat windows | Plateau found · centre kept · median move |
|---|---|---|---|---|---|
| QQQ | 0.253 / 0.227 / 0.420 | $49,823 / $41,750 / $105,796 | 510 / 550 / 503 | 0 of 16 | 100% · 73% · 0.17 |
| SPY | 0.133 / 0.129 / 0.066 | $31,415 / $24,703 / $15,730 | 469 / 590 / 523 | 1 of 16 | 94% · 69% · 0.37 |
| ITOT | 0.072 / 0.059 / 0.045 | $13,963 / $9,992 / $9,261 | 418 / 617 / 501 | 1 of 15 | 93% · 58% · 0.25 |

The summary line reads "plateau rule ahead of the peak rule on 3 of 3 symbols by MAR". On SPY the
margin is 0.004 MAR, which is why the comparison sentence now shows three decimals when two would
read as a tie. On QQQ the frozen centre beat both re-chosen rules. A study run the night before on
another accepted copy of the same experiment (`breakout-walk-forward-smoke-20261019`, 208 s)
produced the same numbers.

## Measurements (this laptop, pool of 10)

| What | Value |
|---|---|
| Full study, 47 windows × 252 cells + 6 side runs per window | 207.6 s after resume; 234.5 s start to done including the pause and restart |
| Plan estimate | 204 s at 0.0249 ms per cell-bar (measured from the item-51 experiment) |
| Measured during the study | 0.0346 ms per cell-bar |
| Status route while running | ≤ 59 ms |

## Verification

`tools\verify.ps1` on the branch (2026-10-19, before `8d110f2`; that commit changes UI files only):
lint and format passed (repo-wide ruff 46, reported, not a gate). The inventory was core 557, triad
1,058 and aegis 348 (1,963 in total). All three scopes ran in full: core 386 passed and 171
skipped; triad 634 passed and 424 skipped (209 subtests); aegis 347 passed and 1 skipped. It then
stopped at the database health check: `neo4j_stack` was ServiceUnavailable.

The cause is on the host, not in this mission. Since the 2026-10-18 reboot Windows reserves TCP
57225–57824 (`netsh interface ipv4 show excludedportrange`), which covers Neo4j's host ports
57474 and 57687. Docker therefore started `triad-neo4j-1` without publishing them; Postgres's
55432 lies outside the range and works. This was surfaced to the operator. The quick fix (an
elevated `net stop winnat`, then recreating the container, then `net start winnat`) needs an
administrator shell. The durable fix (Neo4j ports below the reserved range) is a Core
configuration decision left to the operator.

UI after the last commit: 73 vitest cases pass and the build succeeds.

## Rulings

Plan rulings P1–P17 are in the plan. Rulings made during execution (from the ledger):

1. The runner builds `list_{name}s`; for "study" it maps the plural (`PLURALS`). The repository
   keeps `list_studies`.
2. A flat window's forced exit carries no synthetic temporal tag. The exit trade is marked
   `window_flat_exit: True`, as `flag_edge_exits` marks edge closes.
3. `run_window(spec, …, flat=False, cache=None)` always takes a spec, because a flat window still
   manages the forced exit with one.
4. `SideChain` carries the marked ending equity the next window is measured from.
5. A window's combined block holds net P&L (marked ending equity minus the previous), trades,
   return and exposure. The full engine metrics are the stitched ones.
6. Exposure is the union of held bars, counted as the engine flags them. This reproduces a
   continuous run's union exposure exactly (test).
7. `map_window` returns the experiment's cell table and the report. Workers keep their raw rows and
   prepare one frame per window slice.
8. The report carries `window_rows`, so the Markdown has the window table. "Ahead" compares the
   oriented objective; a tie is not ahead; a null objective is "not comparable".
9. The plan carries `first_pass`/`refinement` per symbol; the document carries the pinned
   provenance.
10. A resume reruns from the first window missing from the done prefix, and rebuilds the compact
    records from the window files.
11. `POST /studies` answers 409 while another job runs and leaves nothing queued, as spec §5.4
    says; experiments queue instead.
12. `GET /studies/{id}` returns the stored runner envelope, with progress and estimate.
13. The study list, planner and view live in a Walk forward section on the experiment's report.
14. The acceptance re-analyses a window out of process on `.venv-aegis`, and rebuilds its bars from
    `GET /data/bars` for a supplied-bars backtest.

## Defects found during the build and fixed test-first

- The window table printed the centre as a Python dict (browser check, Task 6).
- The frozen centre came from the parent's *latest* report. Acceptance item 58 recomputes that
  report on net P&L at 0.10, so the frozen centre would have come from another objective. Now the
  latest report on the experiment's own objective and tolerance is used; with none, the column is
  absent with the reason.
- The document's window records dropped the chains (each rule's carried in and out), which spec
  §5.5 lists.
- "0.13, against 0.13" beside a line counting SPY ahead (first real-data run).
- The page listed symbols alphabetically, because the repository writes JSON with sorted keys (UI
  fix, no test).
- **The 9 EMA and 30 SMA stopped short (operator report, 2026-10-19).** The lines started on the
  first bar and ended short of the last by their own length. Vela aligns a line's points to the
  bars by index, and since Mission 3 `chart/sync.ts` had dropped the warm-up nulls, shifting
  every line left by its warm-up. The 2026-10-09 chart spike had drawn them with null gaps; the
  fix restores one point per bar. The unit test that encoded the bug was changed and a new case
  added. Checked in the browser on QQQ 1h, December 2024: EMA 9 starts about 9 candles in, SMA 30
  about 30 in, and both end on the last candle.

## Operator additions during the mission (2026-10-19)

- **Losing money is red, always.** In the parameter heatmaps a negative value showed green
  whenever it ranked in the middle or top of the grid. For metrics whose sign is money (net P&L,
  return, CAGR, MAR, expectancy; profit factor below 1), a losing cell is now red whatever its
  rank. Gains rank among themselves (best third bright, the rest muted green). Break-even is
  neutral. Asked directly, the operator confirmed red only for losing money; the locked design mock
  colours weak winners red and is overridden. Commit `a782b4c`, five vitest cases.
- **The results window.** The x/y matrix window under the chart (the locked design's bottom panel)
  is hard to read and will get worse as testing grows. This is recorded as the recommended next
  mission, to be designed with the operator.

## Known limits

- A window's map always starts its indicators cold on the window's bars (as an experiment does).
  The out-of-sample runs use the full prior history.
- The estimate prices the six side runs per window at the metrics-only cell rate. It was close
  here (204 s planned, 208 s run).
- No significance test; few windows per symbol; the report says so beside every comparison.
- The data is the raw archive, not research-eligible; the label is on every report.
