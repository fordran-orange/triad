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
| 7 UI | `a16afe6` | Optimize popover Grid / Walk-forward mode with proposed window lengths and the server's plan; Walk-Forward tab (progress by window, cell and unit, cancel, stitched equity with boundaries, windows table, stability, stitched metrics, stale notice, apply final configuration); poller and adoption for both kinds |
| 8 Acceptance + record | `333f467` | `tests/products/aegis/browser_workstation.py` extended to 36 items; this record; evidence under `docs/evidence/` |
| 9 QA, review, fix pass | final commit | independent QA, whole-branch review, one test-first fix pass (below), re-verified |

## Acceptance evidence

`tests/products/aegis/browser_workstation.py` walks the 22 Mission 3 items and the 14 Mission 4
items (spec §1) against the worker on 8102 in headless Chromium. Reports under
`docs/evidence/`: `20261010T193536Z` (Task 8, 36/36, 126 s) and `20261010T201615Z` (after the fix
pass, **36 / 36 PASS, 0 page errors, 138 s**). The table shows the final run.

| Item | Evidence |
|---|---|
| 1 (23) | gateway `/aegis/api/status` 317 ms median / 369 max; Core `/health/live` 8 ms; worker direct 68 ms (before Task 1 the gateway hop was 1.6 s) |
| 2 (24) | plan for QQQ 1D 2023-01-01 → 2024-12-31 with in-sample 200 / out-of-sample 50: "6 windows · 40 cells each · 246 units · 2 unused tail bars · 502 bars · ≈ 4.5 s estimated" (40 cells because the Mission 3 items leave the long ranges at EMA 5–12 × SMA 20–40) |
| 3 (25) | started; "RUNNING · window 1 of 6 · cell 2 of 40 · unit 2 of 246 · in-sample 200 / out-of-sample 50 bars · objective Net P&L" |
| 4 (26) | units advance while running; status route answered in tens of ms |
| 5 (27) | cancelled at window 1 of 6 (unit 64 of 246); the done window stays in the table; `result_hash` null |
| 6 (28) | 6/6 windows, 246 units in 8.1 s (33 ms per unit), hash `4f540c989d80…` |
| 7 (29) | chosen configurations per window EMA/SMA 11/40, 5/20, 11/35, 5/30, 11/20, 6/20; efficiencies 2.47, 1.31, 0.62, 0.00, −0.26, 1.12 |
| 8 (30) | one stitched curve, 5 window boundaries, 300 out-of-sample points; net P&L $22,899, return 22.90%, CAGR 18.90%, **max DD 5.08%, MAR 3.72** (4.71% / 4.01 before the fix pass, when each window measured drawdown from its own start), win rate 83.33%, 6 trades **(5 closed at a window edge)**, exposure 51.67% |
| 9 (31) | EMA 5–11 (mean 8.2, std 2.85); positive out-of-sample windows 4 of 6; mean efficiency 0.87 |
| 10 (32) | applied EMA 6 / SMA 20 → long side "ENTRY: EMA(6) crosses ABOVE SMA(20)"; combined rerun 19 trades |
| 11 (33) | persisted job reloaded from `GET /walkforward`: same hash, same stitched net P&L 22,899.43 |
| 12 (34) | two identical requests (default ranges, 271 cells) → the same `result_hash` `1044cddec07f6bf36ca2440b6f5934b79d14c363401b6603517ec75c76734451` |
| 13 (35) | in-sample 500 / out-of-sample 100 on 502 bars → `422 range too short: 502 bars; one window needs 500 + 100 bars` |
| 14 (36) | `GET /aegis/api/status` human_directed / CLOSED; `DailySchedule c99fa831` enabled=false |

Mission 3 items 1–22 still pass (backtest 0.63–0.82 s server for 3,493 1h bars; optimizer cells
≈ 50 ms on 502 1D bars; identical-request backtest hash `cdbc9abd…` unchanged).

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
throttling; the remaining ≈ 300 ms above the worker's own ≈ 60 ms is Core's proxy implementation
and is outside this mission (spec §9). After the restarts: `DailySchedule`
`c99fa831-0c46-4908-b840-4cbb2d0992b5` still `enabled: false`, `next_cycle: null`; the Triad
worker reports `loaded_revision dff1d3a` (it had been serving `9b61ed2`, the Mission 0 revision,
since before Mission 1); `GET /aegis/api/status` still `human_directed` / `CLOSED`. The QA
confirmed the opt-out is in effect by reading each live process's power-throttling state
(`ControlMask 0x1, StateMask 0x0` on the gateway, Triad and Aegis server processes; the launchers
and a control process `0x0/0x0`). The gateway and Triad processes were started from the then
uncommitted working tree 75 s before commit `2ace5a1`; the code is the same.

### Walk-forward cost

On the unthrottled worker a walk-forward unit (one in-sample cell of 200 1D bars, or one
out-of-sample run) costs 29–33 ms; a 246-unit job completes in ≈ 8 s and a 1,632-unit job (the
default 271-cell grid over 6 windows) in 45–50 s; the learned per-bar cost prices each plan. The
runner's `bars_per_unit` is the in-sample length, so estimates are slightly conservative. Status
polls while a 1,632-unit job ran: median 36–41 ms, one outlier of 1.1 s (the snapshot's deep copy
plus stitching runs under the runner lock once per unit).

## Milestone checks (Task 9 step 1)

At `333f467`: `pytest -q -p no:cacheprovider` **1085 passed, 596 skipped**; `ruff check` and
`ruff format --check` clean over the Aegis sources and tests, `process_power.py`, `tools` and the
supervisor tests; `npm test` 22 passed; `npm run build` clean; acceptance 36/36.

After the fix pass (final commit): **1097 passed, 596 skipped**, ruff clean, `npm test` 23 passed,
build clean, acceptance 36/36 on the restarted worker.

## Independent QA (Task 9 step 2)

- Reviewed revision `333f4670ea64b3ccd87cdc920be6c272d48a1cab`; a separate QA agent (Fable),
  read-only on the repository plus tests, HTTP probes and process inspection, 2026-10-10
  ≈ 19:45–20:05Z; artefacts under `logs/qa_m4/` (git-ignored).
- Verdict: **PASS_WITH_OBSERVATIONS**. Reproduced: the Core change is exactly the three files
  of spec §4 plus the contract generator entry; Core imports no product; governance and
  architecture tests green; both workers and the gateway up, the schedule record disabled, the
  status contract intact; whole suite 1085 passed; ruff clean; UI tests and build clean; the
  36-item walk 36/36; walk-forward determinism over HTTP (two 1,632-unit runs, equal hash,
  byte-identical records; a changed out-of-sample length changes the hash); every out-of-sample
  trade signalled on or after its window's first bar, equity starting exactly at it, capital
  chained to the cent; in-sample bests independently re-derived for three windows by running the
  optimizer on the same date ranges (params and metrics match, tie-break agrees); the Mission 3
  backtest hash unchanged without `evaluate_from`; 409 across kinds, cancel keeping complete
  windows, 404 for unknown ids on both kinds; range validation, cache reuse and eviction; the
  honesty rule in the new tab; persistence shape and summaries.
- Finding F1 (non-blocking): the stitched max drawdown and MAR were measured from each window's
  own start, understating a drawdown that spans a join (5.08% true vs 4.71% shown on the
  acceptance job). Fixed in the pass below.
- Observations: a status line said "cell" for units (fixed); open positions are force-closed at
  each window's last bar (now labelled, see known limits); kind-agnostic status lookups (fixed);
  a cancel landing after the last unit could report `cancelled` (fixed); one 1.1 s status-poll
  outlier under the runner lock (deferred); the out-of-sample EMA state is seeded by the lead
  only (deferred, spec-conformant); the "before" latency cannot be re-measured without a restart.

## Whole-branch review and fix pass (Task 9 step 3)

A separate code reviewer (Fable) read the whole branch at `333f467` against the spec, plan and
ledger rulings: no Critical, 3 Important, 13 Minor; verdict "with fixes". Re-graded by effect on
a person using the product, one fix pass followed, each fix with a test that failed first:

- **Stitched drawdown across window joins** (Important; QA F1): `stitch()` now recomputes the
  drawdown of the concatenated out-of-sample curve with one running peak seeded at the initial
  capital, so the headline max drawdown and MAR describe the curve on screen. The per-window
  records keep their own figures. This changes the `result_hash` of every walk-forward (persisted
  jobs from before the fix carry the old hashes; identical requests still agree with each other:
  the 271-cell request's hash moved from `6f5791a6…` to `1044cdde…`).
- **Window-edge forced closes** (Important, minimum fix): the engine's end-of-data close fires
  at each window's last bar, so a position straddling a boundary is closed and never carried
  into the next window; for crossover strategies this systematically shortens trades (5 of the
  6 trades on the acceptance job). Trades now carry `window_edge_exit`, the windows table and the
  stitched row say how many closed at an edge, and the limitation is recorded below. Carrying
  the open position into the next window is an engine semantics change (an `initial_position`
  for the out-of-sample run) and is left for the operator to decide as a Mission 5 candidate.
- **Plan-time dead ends** (Important): the plan refuses the `mar` objective when window 0's
  in-sample span is under 365 days (every cell's MAR would be null) and a grid with no valid cell
  (every cell fast ≥ slow), naming the numbers; the route passes the bar timestamps.
- **Re-graded minors fixed**: one kind's status and cancel routes answered for the other kind's
  id (404 now); the worker-wide backtest cache had no lock on a threadpool (locked); a cancel
  landing after the last unit reported `cancelled` with no hash (guarded); a walk-forward request
  could carry its own `evaluate_from` into every in-sample cell (rejected); job kinds release
  their bar rows and cache after the terminal save; the status line counts cells within the
  window and units overall; acceptance item 25 asserts the full progress line; a BLOCK clock
  window straddling `evaluate_from` is pinned by a test; the Core helper catches every
  exception (it must never stop a worker).
- Deferred minors (ledger): the popover requests the plan twice on open; per-unit persistence
  writes the full envelope every unit; cache eviction is insertion-ordered; the 1.1 s poll
  outlier under the lock on long jobs; the lead-only EMA seeding of out-of-sample runs.

Spec amendments recorded here rather than by rewriting the spec: §5.4 stitched drawdown is
measured over the concatenated curve; §5.3 positions do not carry across windows and window-edge
closes are labelled.

## Rulings made during execution

- Setup: the branch lives in the `C:\Triad` checkout, not a worktree, because the workers and
  the supervisor run from it and Task 1 restarts them.
- Pre-flight: stitched exposure is the bar-weighted mean of each done window's exposure;
  `OptimizerRunner` subclasses `JobRunner` and accepts either a request triple or a job kind;
  plan response keys and the tab's DOM ids were pinned before Tasks 6–8.
- Task 1: `_set_process_information` is the seam tests stand in for; the residual ≈ 300 ms proxy
  hop is Core's and out of scope.
- Task 2: the envelope's settings carry `evaluate_from: null` on plain runs; a Mission 3 test
  asserting the exact settings dict was widened to its three keys.
- Task 3: `longest_length` counts the upper ends of the enabled length ranges as well as the
  current lengths (floor 135 bars for the default long side); `lead_bars = max(longest + 1, 35)`;
  request bar floors are validators that name the numbers.
- Task 4: `MS_PER_BAR` and `estimate_seconds` live in `jobs.py`; `list_jobs()` without a kind
  merges every kind newest first; `known(job_id)` backs the cancel 404.
- Task 5: a cancelled or failed walk-forward has `result_hash` null; snapshots deep-copy the
  window records; `bars_per_unit` is the in-sample length.
- Task 6: `cache_hits` counts the hits a request added; the worker-wide cache keys by the
  engine's content hash and keeps 8 data keys; the 409 detail stays "an optimization is already
  running" for both kinds.
- Task 7: proposed window lengths stop following the loaded bars once edited; the tab's stale
  notice compares the job's pinned data and strategy inline.
- Task 8: the persisted-reload item is verified through the API list and get; the scripted plan
  assertion checks the window layout, not the grid size; the popover opener is idempotent.
- Final: the reviewer's set-aside list stands (per-side only, API list for finished jobs, the
  proxy hop, the `OptimizerRunner` shim, disabled-side jobs, the 135-bar floor, `cache_hits`
  semantics, conservative estimates, launch scripts unchanged); spec amendments live in this
  record; the full position carry-over is the operator's call.

## Known limits

- Walk-forward is per side; combined stays a backtest (spec §2).
- Positions are closed at each window's last bar and not carried into the next window; such
  exits are labelled "closed at a window edge" in the tab and flagged `window_edge_exit` in the
  data. For crossover strategies this shortens trades that straddle a boundary and can suppress
  a re-entry in the next window (a fresh cross is needed). Mission 5 candidate: carry the open
  position across windows.
- The `mar` objective needs in-sample windows of at least 365 days (the engine defines CAGR and
  MAR over a year); the plan refuses shorter ones.
- A finished walk-forward is reachable through the API list after a reload, not through a UI
  list; the app adopts only unfinished jobs on load.
- `longest_length` makes the in-sample floor 135 bars for the default long side (SMA range to
  100), so a 1D walk-forward needs at least 135 + 20 bars of range.
- Persisted walk-forward hashes from before the fix pass differ from hashes the fixed code
  produces for the same request (the stitched drawdown entered the payload differently).
- Core's gateway still adds ≈ 300 ms per proxied request; the worker answers in tens of
  milliseconds. Core's proxy is outside this mission.
- Triad's worker now runs the current revision with the opt-out; its autonomy stays disabled.
