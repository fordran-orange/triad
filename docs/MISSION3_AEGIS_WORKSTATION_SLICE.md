# Mission 3 — Aegis workstation slice (2026-10-09 → 2026-10-10)

Follow-up to Mission 2 (`docs/MISSION2_RECONCILE_AND_ADOPT.md`). Builds the first functioning,
inspectable Aegis research workstation on top of the merged `main` (`b018fcc`): real candles from
the pinned raw archives, side-owned strategy contracts, a deterministic backtester with a
canonical `result_hash`, persisted runs with pinned provenance, a per-side grid optimizer with
progressive results, and the React workstation that exposes all of it. Spec:
`docs/superpowers/specs/2026-10-09-aegis-workstation-slice-design.md` (revision 2 carries the
operator's implementation brief). Plan: `docs/superpowers/plans/2026-10-09-aegis-workstation-slice.md`
(15 tasks).

Standing constraints were preserved throughout: Triad intentionally suspended (scheduled
autonomy disabled by `DailySchedule` record `c99fa831`, untouched), Aegis human-directed,
exchange CLOSED, no live or paper broker path, Core imports neither product, nothing fabricated
shown in the UI.

## Operator decisions (chat, 2026-10-09)

| Decision | Choice |
|---|---|
| Frontend stack | **A**: React 18 + Vite 5 + TypeScript 5 (vitest for unit tests) |
| Chart library | **Vela** 0.8.3 (`@luxalgo/vela`, Apache-2.0 core) behind a `ChartAdapter`; lightweight-charts is the agreed fallback, never needed |
| Data source | **Aegis reads the raw archives directly** (`data/raw/HFDataLibrary/<vintage>/*_1m_10y.parquet`, newest vintage wins only when a new experiment starts) |
| Process topology | **1**: one Aegis worker (8102) hosts the built SPA and the compute routes; Core's gateway (8000) keeps proxying `/aegis/*` |
| Spec revisions | The pasted implementation brief (structural long/short asymmetry, canonical payload + `result_hash`, pinned provenance with `source_unavailable`, UI-early build order, temporal precedence, clock-derived crossovers, rumor/news schema-only, `RunRepository`, progressive optimizer, 1m timeframe, chart attribution, indicator/strategy separation, permanent honesty rule, 22-item definition of done) |
| Execution | **native** (`superpowers:executing-plans` inline, one branch `aegis/workstation-slice`, final whole-branch review and independent QA at the end) |

## What was built (branch `aegis/workstation-slice` on `b018fcc`)

| Task | Commit | Delivered |
|---|---|---|
| 1 Chart spike | `a9d85d8` | Vela proven for native overlays, arrow-label markers, crosshair, CSP without `unsafe-eval`, visible attribution; decision in `docs/superpowers/plans/2026-10-09-chart-spike-result.md` |
| 2 Shell | `3a088f0` | `app/products/aegis/ui/` (Vite `base: /aegis/`), the locked layout as components with honest empty states, `tools/aegis_contracts.py` → `ui/src/contracts.ts` (+ staleness test), worker serves `ui/dist` |
| 3 Contracts | `be40cb4` | `StrategySide` owns indicators, rules, `enabled`, optimization ranges; `apply_parameters`; `MarketCrossover` clock windows; both sides default EMA 9 / SMA 30 |
| 4 Indicators + engine | `195700b` | `indicators.py` (`ema`, `sma`, `IndicatorCache`), per-side simulation from side-owned series, shared cache across runs |
| 5 Temporal | `a4a3b51` | BLOCK > ALLOW, ANALYZE only tags, `MODIFY_RISK` rejected; `CLOCK:`/`CROSSOVER:`/`EVENT:` tags on trades |
| 6 Results | `fba166d` | exposure metric, chart markers, canonical payload and SHA-256 `result_hash` (envelope fields excluded) |
| 7 Data layer | `aa96c44`, `28f402e` | archive discovery, `PinnedSource` (file sha256, data hash, vintage, policy `rth-anchored-v1`), 1m passthrough and 09:30-anchored 15m/30m/1h/1D resampling, 50,000-bar cap, `SourceUnavailable` |
| 8 API + runs | `fa38bc2` | `/aegis/api/data/symbols`, `/data/bars`, `/indicators`, `/backtest` (by pinned reference), `/runs`, `/runs/{id}` (`state: ok | source_unavailable`); `JsonRunRepository` under `data/aegis/` |
| 9 Chart | `eb11a04` | `ChartAdapter` + `VelaAdapter`; real candles, EMA/SMA overlays, markers, RAW badge + vintage, crosshair readout, inline 422 range hint |
| 10 Run + results | `496aeb8` | Run Backtest, Summary (long / short / combined + temporal breakdown), Trades, Equity (SVG), status strip, markers, RunsDrawer reload incl. `source_unavailable`; strategy panel edits the spec |
| 11 Optimizer core | `63e7008` | `optimize.py`: grid expansion with fast ≥ slow skipped, ≤ 400 cells, single-worker runner, progressive cells, cooperative cancel, persisted jobs, `lost` on restart |
| 12 Optimizer UI | `39b45c7` | `/optimize/plan`, `/optimize` (202 / 409 / 422), status, cancel, list; Optimize popover, 1 s poller, Optimization tab (progress, per-metric heatmap, ranked table, select, apply + rerun combined), editable ranges |
| 13 Supervision | `d2ec442` | `tools/ensure_product_worker.py --product {triad,aegis}` (ports 8101/8102, per-product lease and log); `run_core_supervisor.py` runs both; Aegis manifest aligned to `config/aegis/product.json` |
| 14 Acceptance | `2002fb7` | `tests/products/aegis/browser_workstation.py` (Playwright, 22 items) and this record |
| 15 QA + fix pass | final commit | whole-branch review, independent QA, one fix pass (below), merge |

## Acceptance evidence

`tests/products/aegis/browser_workstation.py` walks the 22 definition-of-done items against the
worker on 8102 in headless Chromium (Playwright 1.63.0) and writes `logs/aegis-acceptance-<stamp>.json`.
Reports copied under `docs/evidence/`:

| Run | Commit | Result | Notes |
|---|---|---|---|
| `20261010T033903Z` | `2002fb7` | 22 / 22 PASS, 0 page errors, 50.6 s | before the fix pass; backtest 4.3 s server, optimizer 320–368 ms per 502-bar cell |
| `20261010T035249Z` | `2002fb7` | 22 / 22 PASS (independent QA's own run) | same hashes as the builder's run |
| `20261010T043645Z` | final | 22 / 22 PASS, 0 page errors, 16.0 s | after the fix pass and the power-throttling opt-out; backtest 0.65–0.84 s server, optimizer 50–62 ms per cell |

Per-item evidence (identical across all three runs unless noted):

| Item | Evidence |
|---|---|
| 1–3 | QQQ selected; bars per timeframe over 2023-01-01 → 2024-12-31: 15m 12,974 · 30m 6,488 · 1h 3,493 · 1D 502; 1m over 2024-06-03 → 2024-06-07: 1,827 |
| 4–5 | `GET data/bars` → `source: raw_archive`, `research_eligible: false`, vintage `20260919T233952760505Z`, file sha256 `ad3cdc78a91c…`; 7 chart canvas layers; RAW ARCHIVE · NOT RESEARCH-ELIGIBLE badge visible |
| 6 | EMA 9 / SMA 30 in the legend; indicator response 129–240 ms for 3,493 bars; warm-up gaps are null |
| 7–8 | hash `c9b6f8f821c0…` for the default request on QQQ 1h 2023–2024, identical in every run, across worker restarts and in the QA's own process; 250 markers for 125 trades; first entry 2023-01-19 14:30 after its 2023-01-18 20:30 signal |
| 9–11 | long 62 trades, net P&L $51,462, exposure 57.40%; short 63 trades, −$20,438, 40.40%; combined 125 trades, $31,024, 97.80% |
| 12 | breakdown rows ALL, CLOCK:close, CLOCK:open, CROSSOVER:cash_open, CROSSOVER:london_new_york |
| 13–15 | 125 trades listed (62 under the Long filter); 3 equity curves; status strip net P&L $31,024 against API 31,024.18, hash shown |
| 16 | run reloaded from the drawer, `GET runs/{id}` state `ok`, hash unchanged |
| 17–20 | 1D plan "271 valid cells · 1 skipped (fast ≥ slow) · 502 bars"; progress observed advancing while running; cancelled with partial cells kept and visible in table and heatmap before completion |
| 21 | ranges edited to EMA 5–12 × SMA 20–40: 40/40 cells; best cell applied → long side EMA 12 / SMA 40, combined rerun |
| 22 | two identical requests → the same `result_hash` `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360` in every run |

Manual checks in the built-in browser through Core's gateway (`http://127.0.0.1:8000/aegis/`)
agree: 1m over two years → inline `422: range too large: 187072 bars over cap 50000; narrow the
range`; Opening Window set to BLOCK changed the run (91 trades, hash `354d34e5715d…`); the full
default long grid on 1D 2023–2024 ran 271 cells in 87.3 s on the throttled worker (509 cache
hits); after the fix pass, switching the symbol to SPY shows the STALE badge, the per-tab notice
("the selection changed since") and "markers hidden (run is for QQQ · 1h)", and switching back
clears them; the symbol menu lists ITOT, QQQ, SPY from disk with vintage, range, row count,
coverage (64.2% / 97.0% / 97.3%) and vendor sources; the governance line reads
`GET /aegis/api/status`.

## Milestone checks (Task 15 step 1)

At `2002fb7` and again after the fix pass:

- `pytest -q -p no:cacheprovider`: 1040 → **1053 passed, 596 skipped, 5 warnings, 209 subtests passed**, exit 0 (≈ 2.4 min). `tests/test_architecture.py`: 6 passed.
- `ruff check` over `app/products/aegis`, `tools`, the Aegis tests, `tests/test_product_worker_supervisor.py` and `tests/products/aegis`: clean. `ruff format --check`: 6 pre-existing files would be reformatted and were left as authored (`app/products/aegis/backtest.py`, `tools/check_extraction_services.py`, `tools/day7_deploy_evidence.py`, `tools/preserve_baseline.py`, `tools/provider_recovery.py`, `tools/run_milestone1_rotation.py`; all already so at `b018fcc`).
- `npm test`: 15 → **18 tests passed**. `npm run build` (`tsc --noEmit && vite build`): clean; `ui/dist` is not committed.

## Independent QA (Task 15 step 2)

- Reviewed revision: `2002fb7b955c9806752ca63ea00ebec52eca80a0`; reviewer: a separate QA agent (Fable), read-only on the repository plus test execution and HTTP probes against the live worker, 2026-10-10 ≈ 03:40–03:55Z; artefacts under `logs/qa-mission3/` (git-ignored).
- Verdict: **PASS_WITH_OBSERVATIONS**, no blocking findings, all 12 probes reproduced: whole suite 1040 passed; `ruff` clean; UI tests and a build byte-identical to the served `dist`; the 22-item walk 22/22 with the same hashes as the committed evidence; `result_hash` equal across two identical HTTP requests and different after a commission change, with no envelope or timing field inside the canonical payload; pinned provenance validated on reload by file sha256 and resampled data hash with no recomputation; temporal precedence as specified; 422/404/409 paths live, status route 139–239 ms while a job ran, cancel to `cancelled` with partial cells; CSP served without `unsafe-eval` and the page clean under it with no bypass; Vela attribution visible; governance contract intact and `app/products/triad/` untouched; honesty rule held in every panel; supervisor tests green and the scheduled task observed running the new entry point every five minutes.
- Findings (non-blocking): F1 an uncommitted documentation addition (committed since); F2 BLOCK/ALLOW on crossovers and event windows accepted but ignored (fixed, below); F3 stale `api.py` docstring (fixed); F4 legacy `static/index.html` still packaged (retired); F5 `GET /runs` parsed every full envelope (fixed with sidecar summaries); F6 pre-existing formatting differences in `backtest.py` (left as authored).

## Whole-branch review and fix pass

A separate code reviewer (Fable) read the whole branch at `2002fb7` against the spec, plan and
ledger rulings and verdict "with fixes": 1 Critical, 10 Important, 13 Minor. Re-graded by effect
on a person using the product, one fix pass followed, each fix with a test that failed first:

- **Critical** — a grid with a single enabled range (reachable from the ranges panel) crashed
  `heatmap()`, returned 500 from the status route, killed the worker thread and left every later
  start answering 409 until a restart. Fixed: one-axis cells are ignored by the heatmap, the job
  loop ends in `try/except/finally` so a terminal status is always published, a failed save fails
  the job visibly and frees the runner.
- **Important** — unfinished jobs could never become `lost` (nothing was persisted before
  completion) and a running job was invisible after a page reload: jobs now persist as `queued` on
  start and after every cell, `GET /optimize` lists them, the poller treats 404 as `lost`, the app
  adopts unfinished jobs on load.
- **Important (honesty)** — results and markers from the last run stayed on screen for another
  selection or edited strategy: a STALE badge and per-tab notice now say what changed, and markers
  are drawn only for the run's own selection and archive.
- **Important** — the run envelope lacked its settings (initial capital, allocation), so a
  reloaded run could not be rerun identically: settings are in the envelope and restored on load.
- **Important** — the symbol menu was hard-coded: it now comes from `GET /data/symbols` with
  vintage, range, rows, coverage and vendor sources; absent archives are absent.
- **Important** — gating modes on crossovers and event windows were silently treated as ANALYZE:
  `validate()` rejects them ("ANALYZE-only in this slice").
- **Important** — `GET /runs` parsed every full envelope (1.7–2.4 s at 13–22 runs): sidecar
  summaries are written on save (67–244 ms now); legacy files are summarized once.
- **Important** — the spec's background warm-up was missing: the lifespan starts a daemon thread
  that resamples every discovered symbol.
- **Important** — the "0.7 ms per bar" estimate described a throttled process (see Measurements):
  the runner now learns the observed cost from completed jobs, persists it, and prices the plan
  with it; the UI copy no longer states a number.
- **Minor re-graded** — a range too short to warm an indicator returned a confident zero result:
  the engine now rejects it ("insufficient bars … warm-up"). Also fixed: the governance line in
  the shell reads `GET /aegis/api/status`; the legacy `static/index.html` and its package-data
  entry are retired; the Mission 1 record names the renamed supervisor test file.
- **Found by the new tests** — on Windows, replacing a run file while another thread reads it
  raises `PermissionError`; repository reads and writes now retry.

Deferred minors (recorded in the ledger and the final report): range validation (reversed ranges,
fractional steps), job row lists kept in memory, cancel of an unknown id answering 200, duplicate
`StrategySpec` emission in `contracts.ts`, the 1m date filter cost and discovery cache (a new
vintage needs a worker restart), `result_hash` including coverage/vendor fields of the pinned
descriptor, a fresh `IndicatorCache` per backtest request, temporal tags computed for every warm
bar, the equity SVG's independent x scales, and the pre-existing formatting of `backtest.py`.

## Measurements (this host, measured, not asserted)

- **Power throttling.** The supervisor launches workers without a window
  (`Start-Process -WindowStyle Hidden`); on this hybrid 12th-gen i7-1255U Windows 11 then runs
  them in efficiency mode (priority Normal, affinity all 12 CPUs, yet ≈ 8× slower). The same
  3,493-bar 1h backtest: 3.1–4.7 s on the supervised worker, 0.48–0.55 s on a foreground
  `uvicorn` on another port. `server.py` now opts the worker out at startup
  (`SetProcessInformation(ProcessPowerThrottling)`, execution speed never throttled); the
  supervised worker then measures 0.49–0.55 s server / 0.68–0.79 s wall, indicators 96 ms, the
  first bars fetch after warm-up 103 ms. Core's gateway (also windowless) still answers
  `/aegis/api/status` in ≈ 1.4 s versus 50 ms direct; that is Core-owned and untouched here.
- **Engine.** ≈ 0.08 ms per bar per side once unthrottled (≈ 0.65 throttled). Optimizer cells on
  502 1D bars: 50–62 ms (was 320–368); the full default long grid (271 cells) is ≈ 15–20 s on 1D
  2023–2024 and ≈ 1.5–2 min on 1h 2023–2024. The plan preview uses the last observed cost; the
  first plan after this restart still quoted the throttled 0.65 ms/bar until a job completed.
- **Startup.** The warm-up thread loads the three 10-year 1m parquets and resamples 15 frames;
  requests in the first ≈ 30–60 s after a restart compete with it (one backtest measured 15 s in
  that window). Steady state afterwards.
- Loopback quirk unchanged: closed 127.0.0.1 ports refuse only after ≈ 2 s; the supervisor probe
  keeps `timeout=10`.

## Rulings made during execution (ledger, in order)

- Setup: the branch lives in the `C:\Triad` checkout, not a separate worktree, because the
  Aegis/Core/Triad workers and the supervisor run from it.
- Task 1: the spike has no automated tests by design; `tests/test_architecture.py` is its sanity gate.
- Task 2: `contracts.ts` generated from the models that existed; components read either contract
  shape until Task 3; Run / Optimize rendered disabled with "not connected yet".
- Task 3: the backtest tests are red between Tasks 3 and 4 by the plan's own sequencing.
- Task 4: the indicator-cache data key is a content hash of the prepared bars, not the pinned hash.
- Task 8: `GET /runs/{id}` reports drift as `state: source_unavailable` (not 409); the 200,000-bar
  bound is proven at the model level; the branch's app-level `POST /aegis/api/backtest` was removed
  (it shadowed the router).
- Task 9: `ChartAdapter.clear()` added so a failed fetch never leaves old candles under a new
  header; overlays carry a title and Vela's own overlay legend rows are hidden.
- Task 10: initial capital and allocation fraction are editable and posted with every run; the
  chart always shows the current archive and says so when the loaded run is pinned elsewhere;
  `data/aegis/` is git-ignored.
- Task 11: the estimate defaults to the measured cost, not the brief's 0.14 ms/bar; the 400-cell
  cap applies before skipping; cells carry fast/slow values; an `after_cell` test hook; `status()`
  falls back to the repository; a job persists before publishing its terminal status.
- Task 12: `POST /optimize/plan` added; polling in an always-mounted `JobPoller`; results tab in
  workspace state; Apply unlinks the sides; ranges editable per side.
- Task 13: the Triad-only test file is replaced by parametrized tests; the supervisor checks
  both products every pass and reports the first failure; the Mission 1 record keeps its row with
  a pointer to the new module.
- Task 14: the test page runs with `bypass_csp=True` so Playwright can evaluate its probes; the
  product's own CSP (`script-src 'self' 'unsafe-inline'`, no `unsafe-eval`) is unchanged and was
  verified by the spike and by QA. `playwright` is declared in `pyproject.toml` dev extras.
- Final: the reviewer's set-aside list stands as set aside (Vela bundle size, the app-level
  default-strategy route, the 40-cell scripted completion, `bypass_csp` in the harness, no React
  component test for the chart panel, the legend overlap below ≈ 1,000 px and the other cosmetic
  items); the power-throttling opt-out is a per-process setting that touches nothing outside the
  worker.

## Known limits carried forward

- `source_unavailable` is verified at the API level (`test_reload_with_changed_file_hash_is_source_unavailable`)
  and by the UI code path, not by replacing the real archive.
- CAGR and MAR are null (shown as —) for ranges under a year, by the engine's definition.
- Vela's own symbol/volume legend sits top-left; the panel header sits top-right. At widths below
  about 1,000 px the two can touch.
- A new archive vintage is discovered at worker start only (discovery is cached for the worker's
  life); the supervisor restarts the worker only when it is unhealthy.
- Core's gateway adds ≈ 1.4 s per proxied request on this host (likely the same throttling);
  the worker itself answers in tens of milliseconds. Core is outside this slice.
- Nothing under `app/products/triad/` changed. Triad's worker remains supervised exactly as
  Mission 1 left it (without the throttling opt-out); its autonomy stays disabled.
