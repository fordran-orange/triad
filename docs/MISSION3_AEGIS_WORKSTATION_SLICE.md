# Mission 3 — Aegis workstation slice (2026-10-09 → 2026-10-10)

Follow-up to Mission 2 (`docs/MISSION2_RECONCILE_AND_ADOPT.md`). Builds the first functioning,
inspectable Aegis research workstation on top of the merged `main` (`b018fcc`): real candles from
the pinned raw archives, side-owned strategy contracts, a deterministic backtester with a
canonical `result_hash`, persisted runs with pinned provenance, a per-side grid optimizer with
progressive results, and the React workstation that exposes all of it. Spec:
`docs/superpowers/specs/2026-10-09-aegis-workstation-slice-design.md` (revision 2 carries the
operator's implementation brief). Plan: `docs/superpowers/plans/2026-10-09-aegis-workstation-slice.md`
(15 tasks; this record covers Tasks 1–14, Task 15 is the milestone QA).

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
| Execution | **native** (`superpowers:executing-plans` inline, one branch `aegis/workstation-slice`, final whole-branch review at the end) |

## What was built (branch `aegis/workstation-slice`, 14 commits on `b018fcc`)

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
| 14 Acceptance | this commit | `tests/products/aegis/browser_workstation.py` (Playwright, 22 items) and this record |

Python tests after Task 13: **1040 passed, 596 skipped** (bare `pytest -q`). UI unit tests: 15
(reducer, chart sync, heatmap mapping, temporal breakdown rows).

## Acceptance evidence (Task 14)

Run of `tests/products/aegis/browser_workstation.py` against the worker on 8102 at commit
`d2ec442` + the script, headless Chromium (Playwright 1.63.0), 2026-10-10 03:39Z:
**22 / 22 PASS, 0 page errors, 50.6 s wall.** Report copied to
`docs/evidence/aegis-acceptance-20261010T033903Z.json` (original and two full-page screenshots
under `logs/`, git-ignored).

| Item | Evidence |
|---|---|
| 1–3 | QQQ selected; bars per timeframe over 2023-01-01 → 2024-12-31: 15m 12,974 · 30m 6,488 · 1h 3,493 · 1D 502; 1m over 2024-06-03 → 2024-06-07: 1,827 |
| 4–5 | `GET data/bars` → `source: raw_archive`, `research_eligible: false`, vintage `20260919T233952760505Z`, file sha256 `ad3cdc78a91c…`; 7 chart canvas layers; RAW ARCHIVE · NOT RESEARCH-ELIGIBLE badge visible |
| 6 | EMA 9 / SMA 30 in the legend; indicator response 240 ms for 3,493 bars; warm-up gaps are null |
| 7–8 | run `61d4cfeb`, 4,262 ms server / 5,214 ms wall, hash `c9b6f8f821c0…` (identical to the hash of the same request in a manual run before a worker restart); 250 markers for 125 trades; first entry 2023-01-19 14:30 after its 2023-01-18 20:30 signal |
| 9–11 | long 62 trades, net P&L $51,462, exposure 57.40%; short 63 trades, −$20,438, 40.40%; combined 125 trades, $31,024, 97.80% |
| 12 | breakdown rows ALL, CLOCK:close, CLOCK:open, CROSSOVER:cash_open, CROSSOVER:london_new_york |
| 13–15 | 125 trades listed (62 under the Long filter); 3 equity curves; status strip net P&L $31,024 against API 31,024.18, hash shown |
| 16 | run reloaded from the drawer, `GET runs/{id}` state `ok`, hash unchanged |
| 17–20 | 1D plan "271 valid cells · 1 skipped (fast ≥ slow) · 502 bars · ≈ 1 min 35 s estimated"; progress 0 → 4 of 271 observed while running; cancelled at 5/271 after 1.6 s (320 ms per cell); the 5 completed cells visible in table and heatmap before completion |
| 21 | ranges edited to EMA 5–12 × SMA 20–40: 40/40 cells in 14.7 s (368 ms per cell); best cell applied → long side EMA 12 / SMA 40, combined rerun |
| 22 | two identical requests (runs `ee6bbef7`, `e8f3b6da`) → the same `result_hash` `cdbc9abd2238542ee299e694209241b40561f39bfdd3632f58c93350b237e360` |

Manual checks in the built-in browser through Core's gateway (`http://127.0.0.1:8000/aegis/`)
during Tasks 9–12 agree with the script: 1m over two years → inline `422: range too large:
187072 bars over cap 50000; narrow the range`; Opening Window set to BLOCK changed the run (91
trades, hash `354d34e5715d…`); the full default long grid on 1D 2023–2024 ran 271 cells in
87.3 s with 509 indicator-cache hits.

## Measurements (this host, measured, not rewritten)

- Engine: ≈ 0.6–0.7 ms per bar per side with the current per-row loop (4.3 s for 3,493 1h bars,
  both sides). Optimizer cells on 502 1D bars: 320–368 ms each. The default long grid (271 cells)
  takes ≈ 90 s on two years of 1D bars and ≈ 11 min on two years of 1h bars; the plan preview
  states the estimate before a start and the running job refines it. A vectorized rewrite stays
  out of scope (spec §10) and is the first candidate if the operator wants faster grids.
- Data: first request after a worker start loads the 10-year 1m parquet (several seconds);
  later requests hit the frame cache (indicators 240 ms for 3,493 bars).
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
- Task 11: `estimate_seconds` defaults to the measured 0.7 ms/bar (not the brief's 0.14); the
  400-cell cap applies before skipping; cells carry fast/slow values; an `after_cell` test hook;
  `status()` falls back to the repository; a job persists before publishing its terminal status.
- Task 12: `POST /optimize/plan` added; polling in an always-mounted `JobPoller`; results tab in
  workspace state; Apply unlinks the sides; ranges editable per side.
- Task 13: the Triad-only test file is replaced by parametrized tests; the supervisor checks
  both products every pass and reports the first failure; the Mission 1 record keeps its row with
  a pointer to the new module.
- Task 14: the test page runs with `bypass_csp=True` so Playwright can evaluate its probes; the
  product's own CSP (`script-src 'self' 'unsafe-inline'`, no `unsafe-eval`) is unchanged and was
  verified by the spike. `playwright` is declared in `pyproject.toml` dev extras (it was already
  required by `tests/products/triad/browser_product.py`).

## Known limits carried into QA

- `source_unavailable` is verified at the API level (`test_reload_with_changed_file_hash_is_source_unavailable`)
  and by the UI code path, not by replacing the real archive.
- CAGR and MAR are null (shown as —) for ranges under a year, by the engine's definition.
- Vela's own symbol/volume legend sits top-left; the panel header sits top-right. At widths below
  about 1,000 px the two can touch.
- The Windows scheduled task "Triad Core Supervisor" will run the new `ensure_product_worker.py`
  entry point on its next pass; this was not observed live inside the mission.
- Nothing under `app/products/triad/` changed. Triad's worker remains supervised exactly as
  Mission 1 left it; its autonomy stays disabled.
