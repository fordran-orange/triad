# Aegis Mission 4 — Walk-forward validation and Core unthrottle (design)

Date: 2026-10-10. Builds on the merged Mission 3 slice (`main` at `51b5d3e`,
`docs/MISSION3_AEGIS_WORKSTATION_SLICE.md`). Operator framing approved in chat on 2026-10-10:
unthrottle Core first under governance; a walk-forward engine reusing the per-side optimizer
with stitched out-of-sample equity, parameter stability and an efficiency ratio, persisted like
runs with a pinned source and `result_hash`; the Walk-Forward tab lit up with apply-to-strategy;
the optimizer contract hygiene items folded in; acceptance and milestone QA in the Mission 3
shape; merge and push on the operator's call.

Standing constraints carry over unchanged: honesty rule (nothing fabricated is shown), pinned
raw-archive provenance, one job at a time, Core imports neither product, exchange CLOSED, no
broker path, Triad intentionally suspended and its scheduled autonomy disabled.

## 1. Intent and definition of done

A grid optimum alone is an overfit candidate. This mission gives the operator out-of-sample
evidence inside the workstation: rolling windows, each optimized in-sample and evaluated
out-of-sample with the chosen configuration, stitched into one out-of-sample record whose
numbers are real, inspectable and reproducible. It also removes the host-level slowdown that
made every proxied request cost about 1.4 s.

Definition of done (the acceptance script walks these in order):

1. Core's gateway, the Triad worker and the Aegis worker opt out of Windows power throttling at
   startup; the latency of `GET /aegis/api/status` through the gateway and of Core's
   `GET /health/live` is measured before and after and recorded (not asserted to a target).
2. Open the Optimize popover in walk-forward mode and see the plan for the current selection:
   windows, cells per window, total units, unused tail bars, bars, estimate.
3. Start a walk-forward for the LONG side on QQQ 1D 2023-01-01 → 2024-12-31 and land on the
   Walk-Forward tab.
4. Watch progress advance by window and by cell while the status route stays responsive.
5. Cancel it between cells; the completed windows stay visible and the job is `cancelled`.
6. Start it again and let it complete.
7. Inspect every window: in-sample range, out-of-sample range, chosen configuration, in-sample
   objective value, out-of-sample net P&L, max drawdown, trades, efficiency.
8. Inspect the stitched out-of-sample equity with window boundaries.
9. Inspect stability: per-parameter spread, positive out-of-sample windows, mean efficiency.
10. Apply the final window's configuration to the strategy and rerun the combined backtest.
11. Reload the finished walk-forward from the persisted list and see the same numbers.
12. Rerun an identical walk-forward request and obtain the same `result_hash`.
13. Request a walk-forward on a range too short for one window and get a 422 naming the bar counts.
14. After the restarts, `GET /aegis/api/status` still reports `mode human_directed`,
    `exchange CLOSED`, and the `DailySchedule` record `c99fa831` is still disabled.

## 2. Operator decisions recorded in this design

| Decision | Choice (chat, 2026-10-10) |
|---|---|
| Window scheme | **Rolling, in bars**: fixed in-sample length sliding by the out-of-sample length; out-of-sample windows contiguous and non-overlapping; capital chains window to window |
| Runner structure | **One job runner, two job kinds**: the walk-forward's unit of work is one grid cell inside one window; one lock and one 409 rule cover both kinds |
| Core change | **One shared helper only**: the power-throttling opt-out moves into Core and is called by Core's gateway, the Triad worker and the Aegis worker; nothing else in Core moves. The operator's "go ahead" is the explicit governance decision; independent QA at the milestone commit names the change |
| Scope of walk-forward | **Per side** (long or short), like the optimizer; combined stays a backtest |

## 3. Architecture

Everything product-side lives under `app/products/aegis/`; the one Core addition is
`app/trading_core/process_power.py`. Dependencies still point one way: browser → worker HTTP →
`data`, `indicators`, `backtest`, `optimize`, `walkforward`, `jobs`, `runs`; products import
Core (`local_headers`, `Store`, now `process_power`); Core imports no product
(`tests/test_architecture.py` enforces).

| Unit | Location | Responsibility |
|---|---|---|
| Power-throttling opt-out | `app/trading_core/process_power.py` (new) | `opt_out_of_power_throttling() -> bool`, the guarded Windows call moved from Aegis's server |
| Engine | `app/products/aegis/backtest.py` (revised) | `BacktestSettings.evaluate_from`; entries blocked and equity withheld before it |
| Grid | `app/products/aegis/optimize.py` (reduced) | `expand_grid`, `estimate_seconds`, `heatmap`, `OptimizeRequest`, the optimizer job kind |
| Runner | `app/products/aegis/jobs.py` (new, extracted) | `JobRunner`: one worker thread, one lock, persistence from start, cancel, lost, learned cost; `OptimizerRunner` kept as an alias |
| Walk-forward | `app/products/aegis/walkforward.py` (new) | `WalkForwardRequest`, window cutting, per-window selection, warm-up lead, chaining, stitching, efficiency, stability, canonical payload |
| Identity | `app/products/aegis/results.py` (revised) | `walkforward_payload(...)` beside `canonical_payload`; same `canonical_json` / `result_hash` |
| Persistence | `app/products/aegis/runs.py` (revised) | `save_walkforward` / `get_walkforward` / `list_walkforwards` under `data/aegis/walkforward/`, sidecar summaries as for runs and optimizations |
| API | `app/products/aegis/api.py` (revised) | five walk-forward routes; cancel 404 for unknown ids on both kinds; per-store indicator cache for backtests |
| UI | `app/products/aegis/ui/src/` (revised) | popover mode switch, Walk-Forward tab, poller and reducer for the second kind |
| Acceptance | `tests/products/aegis/browser_workstation.py` (extended) | items 1–14 above appended to the Mission 3 walk |

## 4. Core unthrottle

`opt_out_of_power_throttling()` is the function now in `app/products/aegis/server.py`, moved
verbatim: no-op (returns `False`) off Windows; on Windows calls
`SetProcessInformation(GetCurrentProcess(), ProcessPowerThrottling, &state, sizeof state)` with
`Version = 1`, `ControlMask = PROCESS_POWER_THROTTLING_EXECUTION_SPEED (0x1)`, `StateMask = 0`,
through `ctypes.WinDLL("kernel32", use_last_error=True)` with declared `restype`/`argtypes`;
logs a warning with the Windows error code if refused, an info line if applied; never raises.

Callers, each as the first statement of its lifespan: `app/trading_core/api.py` (the gateway;
`platform_host.api` imports this app), `app/products/triad/server.py`, and
`app/products/aegis/server.py`, which deletes its local copy and imports the helper. The launch
scripts (`start_backend.ps1`, `start_product.ps1`, `ensure_core.ps1`, the supervisor) do not
change; the processes opt themselves out.

Verification: a unit test that the helper returns `True` on `win32` and `False` elsewhere and
never raises; the architecture test; a supervised restart of the gateway
(`tools/ensure_core.ps1 -Restart`) and of the Triad worker
(`tools/start_product.ps1 -Product triad`), with the latency of `GET /aegis/api/status` through
the gateway and of `GET /health/live` measured (ten samples, median and max) before and after
and written into the mission record. After the restarts: Triad's `DailySchedule` record
`c99fa831` is read and must still be disabled; `GET /aegis/api/status` must still report
`human_directed` / `CLOSED`.

Known cost: the gateway restart drops in-flight proxied requests for a few seconds; the Codex
re-verification loop the operator left running may log one failed call and continue.

## 5. Walk-forward engine

### 5.1 Request

`WalkForwardRequest` (Pydantic, `extra="forbid"`): `strategy: StrategySpec`,
`side: Literal["long", "short"]`, `data: DataReference`, `settings: BacktestSettings`,
`objective: Literal["net_pnl", "mar", "max_drawdown", "trade_count"] = "net_pnl"`,
`in_sample_bars: int`, `out_of_sample_bars: int`. The request carries explicit bar counts; the
UI proposes defaults (§7) but never sends a fraction.

### 5.2 Windows

Over the `n` bars of the selected range (same `ArchiveStore.bars` selection and `PinnedSource`
as a backtest), with `is = in_sample_bars`, `oos = out_of_sample_bars`:

- window `k` (0-based) has in-sample bars `[k·oos, k·oos + is)` and out-of-sample bars
  `[k·oos + is, k·oos + is + oos)`;
- `windows = floor((n − is) / oos)`; `unused_tail_bars = n − is − windows·oos`;
- bounds: `windows ≥ 1` else `ValueError("range too short: N bars; one window needs is + oos
  bars")` (422 at the API); `windows ≤ 50`; `is ≥ 35 + longest indicator length of the side`;
  `oos ≥ 20`; the side's grid ≤ 400 cells (same `expand_grid` and cap); total units
  `= windows · (cells + 1)` (one unit per in-sample cell, one for the out-of-sample run).

### 5.3 Per window

- **In-sample optimization:** every grid cell is `run_backtest` on the in-sample bars with the
  other side disabled, sharing one `IndicatorCache` across cells and windows (the in-sample bars
  of consecutive windows overlap, but the engine's data key is per frame, so reuse is within a
  window; acceptable). The best cell: maximum of the objective (`max_drawdown` is minimized);
  cells whose objective is `null` are ignored; ties go to the lowest grid index. A window with no
  valid cell is recorded with `status: "no_valid_cell"` and gets no out-of-sample run.
- **Out-of-sample evaluation:** `run_backtest` with the chosen configuration on the bars
  `[oos_start − lead, oos_end)` where `lead = longest indicator length of the chosen
  configuration + 1` (always available because `is ≥ 35 + longest`), with
  `settings.evaluate_from` = the timestamp of the first out-of-sample bar and
  `settings.initial_capital` = the previous window's out-of-sample ending equity (the request's
  `initial_capital` for window 0). Before `evaluate_from` the engine permits no entry and emits
  no equity point, so indicator state is warm and nothing outside the window counts.
- **Window record:** `index`, `is_start`, `is_end`, `oos_start`, `oos_end` (ISO timestamps of
  the first and last bar of each stretch), `is_bars`, `oos_bars`, `cells_evaluated`,
  `best: {params, metrics} | null`, `oos: {trades, equity, metrics} | null`,
  `efficiency: float | null`, `status: "pending" | "done" | "no_valid_cell"`.
- **Efficiency:** `(oos.metrics.net_return / oos_bars) / (best.metrics.net_return / is_bars)`;
  `null` when the in-sample net return is not positive or either run is missing.

### 5.4 Across windows

- **Stitched:** `trades` = out-of-sample trades in window order; `equity` = out-of-sample curves
  concatenated (already chained by capital); `metrics` = `_metrics(trades, equity,
  request.settings.initial_capital, exposure)` with `exposure` = in-position bars over all
  evaluated out-of-sample bars. All ten metric keys as a backtest (CAGR and MAR null under a
  year, as today).
- **Stability:** for each parameter path in the grid, over the windows with a valid choice:
  `min`, `max`, `mean`, `std` (population); `positive_oos_windows` (count with out-of-sample net
  P&L > 0) and `windows_evaluated`; `mean_efficiency` over non-null efficiencies (`null` if none).
- Results fill progressively: the snapshot (§6) recomputes the stitched series and stability
  from completed windows only.

### 5.5 Engine change: `evaluate_from`

`BacktestSettings.evaluate_from: datetime | None = None` (timezone-aware). In
`_simulate_side`, for bars with `timestamp < evaluate_from`: no pending entry is created,
no `in_position` flag is recorded and no equity point is emitted; indicators and warm-up proceed
normally. Because no entry can exist before it, no exit can either. Metrics and exposure are
computed over the emitted curve. `contracts.ts` is regenerated (the staleness test enforces
it). The canonical backtest payload is unchanged for requests without the field.

### 5.6 Identity

`walkforward_payload(result, request, data_identity)` returns the hash-bearing payload:
`kind: "walkforward"`, `strategy`, `data` (pinned descriptor), `side`, `settings`
(`initial_capital`, `allocation_fraction`), `objective`, `in_sample_bars`,
`out_of_sample_bars`, `windows` (every record of §5.3), `unused_tail_bars`, `stitched`,
`stability`. `result_hash` is the SHA-256 of its canonical JSON exactly as for backtests
(NaN → null, sorted keys, no envelope fields). Two identical requests against identical pinned
data yield identical payloads and hashes; changing `out_of_sample_bars`, the objective, a range
or the settings changes the hash. Tests prove both.

## 6. Job runner and API

### 6.1 `JobRunner` (`jobs.py`)

Extracted from `OptimizerRunner` without behaviour change: one `ThreadPoolExecutor(1)`, one
lock, `start()` refuses with `JobBusy` while any job of any kind is queued or running, persists
the queued envelope before submitting (a start that cannot persist registers nothing), persists
after every unit, checks the cancel flag between units, ends in `try/except/finally` so a
terminal status is always published, marks persisted unfinished jobs of both kinds `lost` on
startup, learns `ms_per_bar` from completed jobs (persisted in each job's envelope and read back
at startup), and answers `status()` from memory or the repository. Repository reads and writes
keep their Windows sharing-violation retry.

A job kind is a small object the runner calls: `kind` (`"optimization"` or `"walkforward"`),
`total_units`, `run_unit(index, job)` (executes one unit and records its result on the job under
the runner's lock), `snapshot(job) -> dict` (the kind-specific status document), and the
repository method names to persist and list it. The optimizer kind is the current snapshot and
loop moved over; `tests/test_aegis_optimize.py` keeps passing against `OptimizerRunner =
JobRunner` plus the optimizer kind.

### 6.2 Walk-forward snapshot

`job_id`, `status`, `kind`, `side`, `objective`, `created_at`, `progress {done, total}` in
units, `windows {done, total}`, `current_window`, `window_records` (every window, pending ones
with nulls), `stitched`, `stability`, `unused_tail_bars`, `in_sample_bars`,
`out_of_sample_bars`, `bars`, `cells_per_window`, `elapsed_ms`, `estimated_seconds`,
`ms_per_bar`, `cache_hits`, `data`, `strategy`, `settings`, `result_hash` (set when `done`),
`error`.

### 6.3 Routes

| Route | Behaviour |
|---|---|
| `POST /aegis/api/walkforward/plan` | `{windows, cells_per_window, total_units, unused_tail_bars, bars, estimated_seconds, ms_per_bar}`; 422 for a range too short, a grid over 400 cells, or bounds violated; 404 unknown symbol |
| `POST /aegis/api/walkforward` | 202 `{job_id, windows, cells_per_window, total_units, estimated_seconds}`; 409 `{"detail": "an optimization is already running"}` while any job runs; 422 as the plan |
| `GET /aegis/api/walkforward/{job_id}` | the snapshot; 404 unknown |
| `POST /aegis/api/walkforward/{job_id}/cancel` | `{cancelled: bool}`; 404 unknown (and `POST /optimize/{id}/cancel` now 404s for unknown ids too) |
| `GET /aegis/api/walkforward` | persisted summaries, unfinished included |

### 6.4 Hygiene folded in

- `OptimizationParameter`: `start <= stop`; for paths ending in `.length`, `start`, `stop` and
  `step` must be integer-valued; violations are 422 at every route that expands a grid.
- `POST /backtest` reuses a per-store `IndicatorCache` keyed by the pinned `data_hash`, bounded
  to the most recent 8 data keys (oldest evicted), so repeated runs on the same selection skip
  indicator recomputation; the optimizer and walk-forward keep their per-job caches.

## 7. Frontend

- **Popover mode switch** ("Grid" | "Walk-forward"). Walk-forward mode shows side, objective,
  in-sample and out-of-sample bar inputs, and the server's plan line: "W windows · C cells each ·
  U units · T unused tail bars · B bars · ≈ estimate". Defaults proposed from the loaded bar count
  `n`: `in_sample = max(round(0.4·n), 35 + longest length)`, `out_of_sample = max(round(0.1·n),
  20)`; `250 / 63` when no bars are loaded. Start lands on the Walk-Forward tab; busy and 409
  handling are shared with grid mode.
- **Walk-Forward tab** (per-side chips): status line "window w of W · cell c of C · elapsed · ≈
  remaining · cache hits", Cancel while live; stitched out-of-sample equity as SVG with window
  boundary ticks and first/last timestamps; windows table (window, in-sample range,
  out-of-sample range, chosen configuration, in-sample objective value, out-of-sample net P&L,
  max drawdown, trades, efficiency, status); stability panel; stitched metrics row; "Apply final
  window's configuration" (writes the last valid window's choice into that side, unlinks the
  sides, reruns the combined backtest, lands on the Summary). The stale notice logic applies to
  the job's selection and strategy. A `lost` job says so.
- **Plumbing:** `results.ts` walk-forward types; client functions `walkforwardPlan`,
  `walkforward`, `walkforwards`, `walkforwardJob`, `cancelWalkforward`; reducer state
  `walkforward: {long?, short?}` with `WALKFORWARD_UPDATED` and `WALKFORWARD_LOST`; `JobPoller`
  polls unfinished jobs of both kinds; App adopts unfinished walk-forward jobs on load; vitest
  for the reducer additions, the stitched-equity point mapping (window boundaries) and the
  windows-table ordering.
- **Honesty:** pending windows show dashes; stitched series and stability come only from
  completed windows; everything is labelled per side; no combined walk-forward is claimed; the
  estimate is priced at the learned cost.

## 8. Verification and QA

- Engine and runner (pytest, DB-free, test first): window cutting (counts, tail, too short,
  caps), `evaluate_from` (no entry, no equity, warm indicators), selection (objective
  direction, null cells, ties, no valid cell), capital chaining, stitching and metrics,
  efficiency and stability arithmetic, hash identity and sensitivity, both job kinds under one
  lock, progress in units and windows, cancel between units, persistence from start, lost on
  restart, learned cost, the five routes with 404/409/422, repository round-trip for the new
  kind, the Core helper, range validation, cancel 404, backtest cache reuse.
- Contracts: `tools/aegis_contracts.py` adds `WalkForwardRequest`; the staleness test holds.
- Acceptance: the Mission 3 walk plus items 1–14 of §1, run against the restarted workers;
  the report copied under `docs/evidence/`.
- Milestone QA: one independent agent at the exact commit; its brief names the Core change
  (files touched, that only process scheduling priority changed, both workers restart, Triad
  remains suspended), reruns the suite and the acceptance walk, measures the gateway latency,
  probes determinism, the warm-up lead (no out-of-sample trade may carry a signal before its
  window's start), 409 and cancel across both kinds, and the governance contract.
- Whole-branch review by a fresh reviewer, then one fix pass with every fix test-first.
- Record: `docs/MISSION4_WALK_FORWARD.md` (decisions, measurements, rulings, known limits);
  merge and push on the operator's call.

## 9. Non-goals

No combined (long × short) walk-forward, anchored or calendar windows, plateau or cluster
scoring, Monte Carlo, parameter smoothing, or portfolio of symbols. No event or rumor feed. No
broker, order or paper path. No vectorized engine rewrite. No Core change beyond
`process_power.py` and its three call sites. No launch-script changes. Nothing that re-enables
Triad's scheduled autonomy. No new data downloads or canonical promotion.

## 10. Build order

1. Core helper, three call sites, unit test; supervised restarts; latency measured and recorded.
2. Engine `evaluate_from` (test first); contracts regenerated.
3. `walkforward.py`: windows, selection, lead, chaining, stitching, efficiency, stability, payload
   and hash (test first, synthetic bars).
4. `jobs.py` extraction with the optimizer kind (existing tests green), then the walk-forward kind.
5. Repository kind, routes, contracts; API tests.
6. UI: types, client, reducer, poller, popover mode, Walk-Forward tab; vitest.
7. Hygiene items; acceptance items; worker restart; mission record.
8. Milestone QA, whole-branch review, fix pass, merge and push.

## 11. Risks

| Risk | Mitigation |
|---|---|
| Runner extraction regresses the optimizer | the Mission 3 optimizer tests run unchanged against the extracted runner before the second kind is added |
| `evaluate_from` interacts with temporal gating | entries are blocked before it regardless of clock windows; tests cover a BLOCK window straddling the boundary |
| 1h walk-forwards are long (windows × cells × bars) | plan preview with the learned cost, progress per cell, cancel between cells, 50-window and 400-cell caps |
| Gateway restart side effects | announced in the record; the supervisor relaunches on failure; the Codex loop tolerates one failed call |
| Windows file sharing during per-unit persistence | the repository retry from Mission 3 |
| The opt-out is refused on some future host | the helper logs and returns `False`; nothing else depends on it |
