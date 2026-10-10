# Mission 4 — Walk-forward validation and Core unthrottle (2026-10-10)

Follow-up to Mission 3 (`docs/MISSION3_AEGIS_WORKSTATION_SLICE.md`). Spec:
`docs/superpowers/specs/2026-10-10-aegis-walk-forward-design.md`; plan:
`docs/superpowers/plans/2026-10-10-aegis-walk-forward.md` (9 tasks, native execution chosen by
the operator). Branch `aegis/walk-forward` on `dff1d3a`.

## Operator decisions (chat, 2026-10-10)

| Decision | Choice |
|---|---|
| Mission framing | Unthrottle Core first under governance; rolling walk-forward per side reusing the optimizer; Walk-Forward tab with apply; optimizer hygiene folded in; acceptance and milestone QA as in Mission 3; merge and push on the operator's call |
| Window scheme | Rolling, in bars (fixed in-sample length sliding by the out-of-sample length; contiguous, non-overlapping out-of-sample; chained capital) |
| Runner structure | One job runner, two job kinds, one lock and one 409 rule |
| Core change | One shared helper (`app/trading_core/process_power.py`) called by the gateway, the Triad worker and the Aegis worker; the operator's approval is the explicit Core governance decision; independent QA names the change |
| Execution | Native (inline), one branch `aegis/walk-forward` in the `C:\Triad` checkout |

## What was built

| Task | Commit | Delivered |
|---|---|---|
| 1 Core unthrottle | `2ace5a1` | `trading_core/process_power.py` (`opt_out_of_power_throttling()`, guarded, logged, never raising); called first in the lifespans of `trading_core/api.py`, `products/triad/server.py`, `products/aegis/server.py` (its local copy removed); supervised restarts measured below |
| 2 Engine | `666204b` | `BacktestSettings.evaluate_from` (timezone-aware): before it no entry, no exposure flag, no equity point; contracts regenerated |
| 3 Walk-forward functions | `38fe721` | `walkforward.py`: `WalkForwardRequest`, `cut_windows`, `longest_length`, `plan` (every bound of spec §5.2), `select_best`, `efficiency`, `lead_bars`, `pending_record`, `stitch`, `stability`; `results.walkforward_payload` |
| 4 Runner extraction | `56ba63b` | `jobs.py` `JobRunner` with job kinds dispatched by name; `OptimizerJob`; `OptimizerRunner` kept as a thin subclass; Mission 3 optimizer tests unchanged and green |
| 5 Walk-forward job kind | `78f58fe` | `WalkForwardJob` (units = cells + one out-of-sample run per window, warm-up lead, chained capital, progressive stitching and stability, `result_hash` on completion); repository `walkforward` kind with sidecars |
| 6 Routes + hygiene | `00e79ab` | `POST /walkforward/plan`, `POST /walkforward` (202/409/422), `GET /walkforward/{id}`, cancel (404 unknown, both kinds), `GET /walkforward`; `OptimizationParameter` range validation; bounded `IndicatorCache` shared by plain backtests (`cache_hits` in the envelope); `WalkForwardRequest` in the TypeScript contracts |
| 7 UI | `a16afe6` | Optimize popover Grid / Walk-forward mode with proposed window lengths and the server's plan; Walk-Forward tab (progress by window and cell, cancel, stitched equity with boundaries, windows table, stability, stitched metrics, stale notice, apply final configuration); poller and adoption for both kinds |
| 8 Acceptance + record | this commit | `tests/products/aegis/browser_workstation.py` extended to 36 items; this record; evidence under `docs/evidence/` |
| 9 QA + review | pending | milestone QA, whole-branch review, fix pass, merge |

Python suite after Task 7: see "Milestone checks" (filled at Task 9). UI unit tests: 22
(reducer, chart sync, heatmap mapping, temporal breakdown rows, walk-forward helpers).

## Acceptance evidence (Task 8)

`tests/products/aegis/browser_workstation.py` now walks the 22 Mission 3 items and the 14
Mission 4 items (spec §1) against the worker on 8102 in headless Chromium. Run
`20261010T193536Z` at the Task 7 code: **36 / 36 PASS, 0 page errors, 126 s**; report copied to
`docs/evidence/aegis-acceptance-20261010T193536Z.json`. Earlier runs of the extended script
failed only on harness assumptions (a hard-coded grid size and a label), never on the product.

| Item | Evidence |
|---|---|
| 1 (23) | gateway `/aegis/api/status` 362 ms median / 428 max; Core `/health/live` 6 ms; worker direct 58 ms (before Task 1 the gateway hop was 1.6 s) |
| 2 (24) | plan for QQQ 1D 2023-01-01 → 2024-12-31 with in-sample 200 / out-of-sample 50: "6 windows · 40 cells each · 246 units · 2 unused tail bars · 502 bars · ≈ 4.9 s estimated" (40 cells because the Mission 3 items leave the long ranges at EMA 5–12 × SMA 20–40) |
| 3 (25) | started; tab shows "RUNNING · window 1 of 6 · cell 2 of 246 · in-sample 200 / out-of-sample 50 bars · objective Net P&L" |
| 4 (26) | cells 2 → 37 of 246 while running; status route 20 ms |
| 5 (27) | cancelled at window 1 of 6 (cell 74 of 246); the one done window stays in the table; `result_hash` null |
| 6 (28) | 6/6 windows, 246 units in 8.2 s (33 ms per unit), hash `d025057781ac…` |
| 7 (29) | chosen configurations per window EMA/SMA 11/40, 5/20, 11/35, 5/30, 11/20, 6/20; efficiencies 2.47, 1.31, 0.62, 0.00, −0.26, 1.12 |
| 8 (30) | one stitched curve, 5 window boundaries, 300 out-of-sample points; net P&L $22,899, return 22.90%, CAGR 18.90%, max DD 4.71%, MAR 4.01, win rate 83.33%, 6 trades, exposure 51.67% |
| 9 (31) | EMA 5–11 (mean 8.2, std 2.85); positive out-of-sample windows 4 of 6; mean efficiency 0.87 |
| 10 (32) | applied EMA 6 / SMA 20 → long side "ENTRY: EMA(6) crosses ABOVE SMA(20)"; combined rerun 19 trades |
| 11 (33) | persisted job reloaded from `GET /walkforward`: same hash, same stitched net P&L 22,899.43 |
| 12 (34) | two identical requests (default ranges, 271 cells) → the same `result_hash` `6f5791a60436185faf1aef49307d50f8a39b95662cd93985de53cc6cd88b6128` |
| 13 (35) | in-sample 500 / out-of-sample 100 on 502 bars → `422 range too short: 502 bars; one window needs 500 + 100 bars` |
| 14 (36) | `GET /aegis/api/status` human_directed / CLOSED; `DailySchedule c99fa831` enabled=false |

Mission 3 items 1–22 still pass in the same run (backtest 0.53–0.87 s server for 3,493 1h bars;
optimizer cells 50–57 ms on 502 1D bars; identical-request backtest hash `cdbc9abd…` unchanged).

## Measurements

### Before the restarts (Task 1, 2026-10-10 ≈ 18:50Z; 10 samples each, median / max)

| Route | Median | Max |
|---|---|---|
| `GET http://127.0.0.1:8000/aegis/api/status` (through Core's gateway) | 1,602 ms | 2,151 ms |
| `GET http://127.0.0.1:8000/triad/api/daily-schedule` (through the gateway) | 1,600 ms | 1,863 ms |
| `GET http://127.0.0.1:8000/health/live` (Core itself) | 30 ms | 35 ms |
| `GET http://127.0.0.1:8102/aegis/api/status` (Aegis worker direct) | 76 ms | 93 ms |

Core answered its own health route in 30 ms, so the 1.6 s was spent on the proxy hop to a
product worker. Triad `DailySchedule` before: id `c99fa831-0c46-4908-b840-4cbb2d0992b5`,
`enabled: false`, `next_cycle: null`.

### After the restarts (Task 1, 2026-10-10 ≈ 19:00Z; gateway PID 25776 → 37244, Triad 7472 → 37848, Aegis 7840 → 11348)

| Route | Median | Max | Before |
|---|---|---|---|
| `GET http://127.0.0.1:8000/aegis/api/status` (through the gateway) | 359 ms | 538 ms | 1,602 ms |
| `GET http://127.0.0.1:8000/triad/api/daily-schedule` (through the gateway) | 356 ms | 455 ms | 1,600 ms |
| `GET http://127.0.0.1:8000/health/live` (Core itself) | 18 ms | 41 ms | 30 ms |
| `GET http://127.0.0.1:8102/aegis/api/status` (Aegis worker direct) | 63 ms | 107 ms | 76 ms |
| `GET http://127.0.0.1:8101/health/live` (Triad worker direct) | 4 ms | 27 ms | not sampled |

The proxied hop fell from about 1.6 s to about 0.36 s once the gateway opted out of power
throttling; the remaining ≈ 300 ms above the worker's own 63 ms is Core's proxy implementation
and is outside this mission (spec §9). After the restarts: `DailySchedule`
`c99fa831-0c46-4908-b840-4cbb2d0992b5` still `enabled: false`, `next_cycle: null`; the Triad
worker reports `loaded_revision dff1d3a` (it had been serving `9b61ed2`, the Mission 0 revision,
since before Mission 1); `GET /aegis/api/status` still `human_directed` / `CLOSED`. None of the
three stderr logs contains a "refused" line. The acceptance run later in the day measured the
same gateway hop at 300–362 ms median.

### Walk-forward cost

On the unthrottled worker a walk-forward unit (one in-sample cell of 200 1D bars, or one
out-of-sample run) costs 29–33 ms; a 246-unit job completes in 7–8 s and a 1,632-unit job (the
default 271-cell grid over 6 windows) in about 45 s; the learned per-bar cost prices each plan.
The runner's `bars_per_unit` is the in-sample length, so estimates are slightly conservative.

## Rulings made during execution

- Setup: the branch lives in the `C:\Triad` checkout, not a worktree, because the workers and
  the supervisor run from it and Task 1 restarts them.
- Pre-flight: stitched exposure is the bar-weighted mean of each done window's exposure (the
  engine reports only the fraction); `OptimizerRunner` subclasses `JobRunner` and accepts either
  a request triple or a job kind; plan response keys and the tab's DOM ids were pinned before
  Tasks 6–8.
- Task 1: `_set_process_information` is the seam tests stand in for; the residual ≈ 300 ms proxy
  hop is Core's and out of scope.
- Task 2: the envelope's settings carry `evaluate_from: null` on plain runs; a Mission 3 test
  asserting the exact settings dict was widened to its three keys.
- Task 3: `longest_length` counts the upper ends of the enabled length ranges as well as the
  current lengths, so every in-sample cell can warm up (floor 135 bars for the default long
  side); `lead_bars = max(longest + 1, 35)` because the engine refuses fewer than 35 bars;
  request bar floors are validators that name the numbers.
- Task 4: `MS_PER_BAR` and `estimate_seconds` live in `jobs.py` so the runner never imports the
  optimizer; `list_jobs()` without a kind merges every kind newest first; `known(job_id)` backs
  the cancel 404.
- Task 5: a cancelled or failed walk-forward has `result_hash` null; snapshots deep-copy the
  window records; `bars_per_unit` is the in-sample length.
- Task 6: `cache_hits` counts the hits a request added (a cold run already shows 2 because the
  short side reuses the long side's series); the worker-wide backtest cache keys by the engine's
  own content hash and keeps 8 data keys; the 409 detail stays "an optimization is already
  running" for both kinds.
- Task 7: proposed window lengths stop following the loaded bars once edited; the tab's stale
  notice compares the job's pinned data and strategy inline.
- Task 8: the persisted-reload item is verified through `GET /walkforward` and
  `GET /walkforward/{id}` (the app adopts unfinished jobs on load; finished ones are not listed in
  the UI); the scripted plan assertion checks the window layout, not the grid size, because the
  Mission 3 items leave edited ranges behind; the popover opener is idempotent.

## Known limits

- Walk-forward is per side; combined stays a backtest (spec §2).
- A finished walk-forward is reachable through the API list after a reload, not through a UI
  list; the app adopts only unfinished jobs on load.
- `longest_length` makes the in-sample floor 135 bars for the default long side (SMA range to
  100), so a 1D walk-forward needs at least 135 + 20 bars of range.
- Core's gateway still adds ≈ 300 ms per proxied request; the worker answers in tens of
  milliseconds. Core's proxy is outside this mission.
- Triad's worker now runs the current revision with the opt-out; its autonomy stays disabled.

## Milestone checks and QA

pending (Task 9)
