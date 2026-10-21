# Mission 10: no limit — ten years of 1-minute bars (2026-10-20)

Branch `aegis/no-limit`, cut from `main` at `b6960b8` (not merged; merging stays the operator's
answer). Design: `docs/superpowers/specs/2026-10-20-aegis-no-limit-design.md` (`a24f465`). Plan:
`docs/superpowers/plans/2026-10-20-aegis-no-limit.md` (`b6960b8`, 7 tasks). `NO_LIMIT_BASE` =
`b6960b8`. Built natively on Opus 5.5 ("native").

Product work only: nothing under `app/trading_core/`, `app/platform_host/` or `app/products/triad/`
changed (acceptance item 86). No package or environment change. Exchange CLOSED; Triad suspended;
`DailySchedule` `c99fa831` disabled.

## Intent (operator, 2026-10-20)

- "why am I limited to 50000 bars, that's not enough for a 10 year run" → "200k after this run.
  goal is no limit." The limits change raised the cap to 200,000; this mission removes it as a
  product limit.
- "what about only saving relevant runs would that help? maybe as a selectable option."
- Decisions on the design: keep the hash definition, computed before slimming; about 2,000 equity
  points per side curve; "Save every backtest" by default with "Save only what I keep" as an
  option; existing runs untouched; at most 20,000 candles per view, more detail as you zoom.

## What was built

| Commit | Task | What |
|---|---|---|
| `755f030` | 1 | Slim saved runs: the hash is fed to SHA-256 over the full canonical payload in slices (never one string), then the run is stored without per-bar indicator series, with each side's per-bar equity resampled to at most 2,000 points (ends kept) and markers once; `stored = {format: 2, equity_points}`. Format-1 runs still open, compare and list |
| `9009107` | 2 | Ten years in one process: archive paths run on one prepared frame (`prepare_archive_frame` equals the old rows path column for column, so every hash holds) instead of a dict per bar; the store serves 1m from the minute frame itself and selects by instants; pool workers receive the prepared frame, slice windows from it, keep an indicator cache bounded to 128 B/bar, and a pool runs only as many workers as free memory holds |
| `c6613a5` | 3 | The bar cap becomes a 2,000,000-bar memory guard (about twenty years of 1m) |
| `87aed68` | 4 | The worker chooses the candles: `GET /data/bars` and `POST /indicators` take `max_bars` and a window and answer with the finest standard timeframe that fits (`display_timeframe`, `shown`, `window`; `count` stays the native total); indicators are computed on the native bars and sampled at each candle's last bar |
| `3aa7f11` | 5 | The long-range chart, shared by the Charts page and the Library: "N bars · shown as 1h candles", markers on the candle that contains them, zoom that swaps candles in place (Vela `setMarket`) |
| `56b7eea` | 6 | Save every backtest, or only what I keep: `data/aegis/preferences.json`, the last 20 unsaved runs in memory, `POST /runs/{id}/keep`, `save` on one request; the top bar's switch, Keep in the status strip and the Runs drawer |
| `7a36e7d` | 6 | Follow-up from the browser check: the open Runs drawer re-reads after a Keep in the status strip |
| `2107d3b` | 7 | Acceptance items 82–86 (77 and 80 moved to the guard) and this record |

## Measured on this laptop (QQQ, the raw archive; 15.8 GB, about 2.3 GB free, 12 CPUs)

Memory, with `tests/products/aegis/memory_probe.py` (out of process, the OS's own counters):

| What | Before (limits) | After (Mission 10) |
|---|---|---|
| The /backtest path on 161,754 1m bars, above the selected frame | 2,933 B/bar (peak 868 MB) | 1,351 B/bar (peak 540 MB), 7.9 s |
| The /backtest path on 947,519 1m bars (ten years) | refused (about 3.2 GB needed with 2.3 GB free) | 1,180 B/bar (peak 1.47 GB), 29.4 s |
| A pool worker on a 100-cell grid | rows pickled per worker | 156 MB at 4,863 bars, 215 MB at 161,754, 499 MB at 947,519 → 160 MB + 400 B/bar (rounded up) |

Sizes and times:

| What | Before | After |
|---|---|---|
| Item 22's run (QQQ 1h 2023–2024) | 1,395,000 bytes | 553,521 bytes, same hash `cdbc9abd2238…` |
| A ten-year 15m run (65,107 bars) | 25.7 MB | 2.74 MB |
| A ten-year 1m run (947,519 bars) | — | 38–42 MB (72,498–80,116 trade markers; the trades are the size) |
| Ten years of 1m in the page | refused | 947,519 bars shown as 17,533 1h candles in 1.1–1.8 s; the backtest 10–18 s on the worker, 23–31 s end to end |
| The worker's peak working set across the ten-year 1m backtest | — | 645 → 1,676 MB (item 83) |

## Acceptance evidence

`docs/evidence/aegis-acceptance-20261020T233322Z.json`: **86/86 PASS, no page errors**, 797 s.
Items 1–81 are the Mission 3–9 and limits walk (77 and 80 moved to the 2,000,000-bar guard).
Items 82–86:

- **82:** item 22's run is 553,521 bytes, format 2, side equity 2,000 + 2,000 points of 3,493
  bars, hash `cdbc9abd2238…` unchanged; a run saved before the mission (`21930eba`, 17:45) opens in
  the Library with its 3,493-point equity.
- **83:** QQQ 1m 2016-09-19 → 2026-09-18: 947,519 bars in 1.8 s, shown as 1h candles (17,533);
  a wheel zoom swapped to native 1m candles; the indicators answered on the same 17,533 candles;
  the backtest ran in 17,555 ms on the worker (30.5 s wall), 72,498 markers in the legend, a
  38.3 MB file; the worker's peak working set went from 645 to 1,676 MB.
- **84:** the ten-year run opens in the Library ("shown as 1h candles") and compares with item
  22's run (different periods: shared 2023-01-01 → 2024-12-31; two curves).
- **85:** in "Save only what I keep" a backtest answered `saved: false`, listed as not kept and
  stayed out of the Library; Keep saved it and the Library listed it; the mode is back to "Save
  every backtest".
- **86:** governance unchanged since `b6960b8`; items 1–81 pass.

Before the full walk, items 82–86 ran alone against the store: 5/5 (the trial made item 22's pair
fresh from the last walk's strategy and settings; its hash matched the recorded one).

In this walk the pooled grids ran on 8 and 7 workers (item 78: 13.4 s; item 80's plan "on the
pool (7 workers)"): the pool now takes only the workers free memory holds at the time.

## Verification

- `tools\verify.ps1` on the branch (2026-10-20, after the walk): lint and format passed; the
  inventory was core 557, triad 1,058 and aegis 435; all three scopes ran in full and passed (core
  386 passed / 171 skipped; triad 634 / 424 with 209 subtests; aegis 434 / 1). It stopped at the
  foundation audit's "Wrong Git branch" check, by design; it runs to the end on `main` after a merge.
- UI: 17 vitest files, 110 cases; `tsc` clean; the build succeeds.

## Rulings (from the ledger, in order)

1. Task 1: the strategy-identity test checks the hash against a direct engine run's full payload
   (a slim run cannot recompute its own hash, by decision 1).
2. Task 2: studies keep dict rows (a ten-year 1m study is out of scope); the pool prepares a
   study's rows once in the host.
3. Task 2: `keep_rows` is gone: a worker holds only the prepared frame and slices windows from it.
4. Task 2: the pool initializer receives the prepared DataFrame itself.
5. Task 2: a pool worker's indicator cache is bounded to 128 B/bar, least recently used first (not
   in the plan): unbounded, a wide grid's distinct configurations would outgrow any fixed figure.
6. Task 2: workers are sized on the worker's peak working set (free memory is physical memory),
   with 20% headroom.
7. Task 2: the ten-year path's 1,180 B/bar stands (the plan's 1,000–1,500 band; the run
   completes); the remaining holders are inside the hashed result (per-bar equity dicts, ISO
   timestamp lists, indicator series).
8. Task 2: the walk-forward full-history test builds its own rows as the independent oracle.
9. Task 4: the indicators route stays `POST /aegis/api/indicators` (the plan said
   `/data/indicators`).
10. Task 4: a daily candle's bucket is its session day; intraday buckets start at the candles.
11. Task 4: without `max_bars` both routes answer every native bar, as before.
12. Task 5: zoom follows the chart's capacity, not only the 20,000 bound: Vela keeps candles at
    least 0.5 px apart, so it never shows more than about twice its plot width in candles and
    cannot zoom past its data. Coarser at 85% of capacity, more at an end of the loaded candles,
    finer when they would fill at most half the chart; the worker answers over three visible
    spans at 1.5 × capacity. The first load still asks for 20,000.
13. Task 5: only a selection of more than 20,000 native bars zooms through the worker; a smaller
    one behaves exactly as before.
14. Task 5: a marker before the first drawn candle is dropped and only markers inside the loaded
    window are placed (the header keeps the true count).
15. Task 6: `save` lives on a route-only request model, not the engine's.
16. Task 6: `saved` is answered by POST /backtest and GET /runs/{id}, never written into a file.
17. Task 6: `preferences.json` lives beside the run repository's root.
18. Task 6: the Runs drawer opens only kept runs in the Library.
19. Task 7: the drawer's stale "not kept" row after a Keep in the status strip was fixed
    (`7a36e7d`).
20. Fix pass: review I1 is closed by a study bar cap (200,000 per symbol) and memory-sized study
    workers, not by moving studies onto frames; that is a follow-up. Cost if wrong: a ten-year 1m
    study is refused until then.
21. Fix pass: D1 detects the zoom-out limit from a wheel-out the chart did not follow (Vela's
    spacing scale makes a capacity estimate unreliable), adds `at_least` to the two data routes,
    checks the finer rule before the edge rule, and blocks finer candles after a coarser swap until
    the operator's next wheel-in (width-based guards misfire because Vela spaces candles by index
    across gaps). Cost if wrong: after a coarser swap, a zoom-in by keyboard keeps coarser candles
    until a wheel-in or a new selection.
22. Fix pass: the reviewer's "declined to judge" lines stand as rulings: coarser than 1D,
    pruning and converting runs (spec §11); bars without `max_bars` (as today); the daily bucket
    for a pre-market marker (no such bars); the save switch read once per mount.

## Milestone QA and whole-branch review (Fable 5.1, read-only, at `2107d3b`)

The operator chose Fable 5.1 for both.

**QA: FAIL on one defect, everything else verified independently.** The QA recomputed:
- the hash definition on a format-1 run and on fresh runs;
- frames against rows on real 1m, 15m, 1h and 1D selections, the pool, walk-forward, experiments
  and materialize;
- the memory probe (1,180 B/bar and a 1,491 MB peak, the record's numbers);
- display candles at the boundaries, across DST and for daily buckets;
- "Save only what I keep" end to end; the tests and the build; governance.

**D1:** after a wheel zoom to native 1m candles, zooming out stalled and never came back to coarser
candles. Observation O1: item 83 could pass without a real zoom, because over the chart the
crosshair readout hides the badge.

**Review: "With fixes", 0 Critical, 2 Important, 5 Minor.**
- **I1:** the 2,000,000-bar guard made a ten-year 1m study reachable while studies still hold a dict
  per bar and start their default workers.
- **I2:** the unsaved-runs memory was bounded by count only, so twenty ten-year runs (about 111 MB
  each in memory) exceed this laptop's free memory.

## Fix pass (the operator: "go ahead with the fixes")

| Commit | Fix |
|---|---|
| `83aa30f` | I1: a study runs on at most 200,000 bars per symbol (422 naming the cap on plan, start and resume) and its pool takes only the workers free memory holds. I2: unsaved runs stay under about 512 MB as well as 20 runs, the oldest going first; the keep 404 says unsaved runs are forgotten after newer ones too |
| `ed3d358` | D1: the chart reports a wheel-out it did not follow (its zoom-out limit), and the page then asks for candles at least the next coarser timeframe (`at_least` on GET /data/bars and POST /indicators); asks never come back finer except from the finer rule, which waits for the operator's next wheel-in after a coarser swap; one zoom request at a time. O1: item 83 reads the badge off the chart and requires the worker's answers (native 1m, then aggregated) |
| `9d34afe` | Item 82 finds its runs past the Library's first page (more walks had pushed them off) |

Measured with real wheel events on ten years of QQQ 1m: a deep and a gentle zoom to native candles
both come back out to 1h candles within 12 notches, and zoom in to native again.

After the fix pass: Aegis scope 438 passed, 1 skipped; vitest 17 files, 115 cases; `tsc` clean;
the build succeeds. The walk again: `docs/evidence/aegis-acceptance-20261021T020455Z.json`,
**86/86 PASS, no page errors**, 821 s. Item 83 now reads "zoom in → native 1m candles (answers
['1m']); out → shown as 15m candles"; the ten-year backtest ran in 17,942 ms on the worker with a
38.3 MB file; the worker's peak working set went from 615 to 1,669 MB. `tools\verify.ps1` on the
branch after the fix pass: lint and format passed; inventory core 557, triad 1,058, aegis 439; all
three scopes green (core 386 / 171 skipped; triad 634 / 424 with 209 subtests; aegis 438 / 1); it
stopped at the "Wrong Git branch" check, by design.

## Deferred minors

- Walk-forward still holds one ISO string per bar (~75 MB on ten years of 1m).
- `VelaAdapter.replaceBars` has no rejection path.
- Item 82 needs a 1h run saved before Mission 10 in the store.
- `Preferences.set` shares one temporary file name across concurrent writes.
- A windowed bars or indicators request re-selects the coarser frames to count candles.
- The host's indicator caches (serial optimizer, walk-forward, the shared cache of 8 selections)
  are not bounded by bytes.
- A zoom made while the chart reloads is discarded.
- `display.choose` answers 1D above `max_bars` when even daily candles exceed it (unreachable from
  the page).
- `optimize.POOL_PREPARE_SECONDS_PER_BAR` over-states a pooled plan's start-up by seconds on ten
  years.

Follow-ups: studies on frames end to end (lifting their 200,000-bar cap); compressing saved runs
(a ten-year 1m run is 38–42 MB, nearly all of it trades).

## Merged (2026-10-21)

The operator answered "merge yes": `main` fast-forwarded from `b6960b8` to `2e77e4b` (Mission 10's
twelve commits on top of its spec and plan). `tools\verify.ps1` on `main` exited 0: lint and format
passed; inventory core 557, triad 1,058, aegis 439; core 386 passed / 171 skipped, triad 634 / 424
with 209 subtests, aegis 438 / 1; "all three scopes green".
