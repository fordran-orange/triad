# Aegis Workstation — first vertical slice (design)

- Date: 2026-10-09
- Status: design approved in conversation section by section; awaiting operator review of this written spec
- Mission: 3 ("restart the Aegis worker, then start the UI-first slice on top of the existing strategy and backtest modules rather than from the shell")
- Governance: ordinary reversible Aegis product work under `AGENTS.md` product-first rules; one independent QA at the milestone. The supervisor change in §7 touches `tools/` and gets its own tests.
- Predecessors: `CORE_STATE_AUDIT.md`, `docs/MISSION1_QUIET_GREEN_BASELINE.md`, `docs/MISSION2_RECONCILE_AND_ADOPT.md`, `docs/CORE_CHAT_VISION.md` (including the 2026-10-09 operator correction)

## 1. Intent and success criteria

The operator wants a functioning, inspectable trading research application, built UI-first against the locked interface design that is now the Aegis shell on `main` (`app/products/aegis/static/index.html`): a workstation with symbol, timeframe and date-range controls, a candlestick chart with indicator overlays and trade markers, an asymmetric strategy panel, temporal windows, execution settings, optimizer ranges, tabbed results with a heatmap, and a metrics strip.

The slice is done when, in a browser against the real Aegis worker:

1. picking QQQ, 1h and a date range shows real candles from the raw archive with the 9 EMA and 30 SMA drawn on them and a permanent "RAW ARCHIVE · not research-eligible" badge;
2. Run Backtest fills the Backtest Summary, Trades and Equity Curve tabs and the status strip (CAGR, Net P&L, Max DD, MAR, Expectancy, Exposure) from a deterministic run, with entry and exit markers on the chart, for the long side, the short side and the combination independently;
3. Optimize starts a background job over the strategy's EMA × SMA ranges, shows progress, can be cancelled, and on completion fills the heatmap and results table;
4. every run and optimization is persisted and reloadable;
5. two identical requests produce byte-identical results;
6. bare `pytest` stays green, Aegis still imports neither Triad nor the platform host, and one independent QA at the milestone passes.

## 2. Operator decisions recorded in this design

| Decision | Choice | Alternatives declined |
|---|---|---|
| UI stack | React 18 + Vite + TypeScript under `app/products/aegis/ui/` | wiring the vanilla shell; Vite + TS without a framework |
| Chart library | Vela (`@luxalgo/vela`, Apache-2.0 core) first, behind an adapter; TradingView lightweight-charts as the fallback if the spike in §4.4 fails | lightweight-charts first |
| Market data | Aegis reads the raw QQQ/SPY/ITOT 1-minute archives directly and resamples them, labeled raw and not research-eligible; Core's canonical store is untouched | synthetic fixtures only; raw plus fixture toggle |
| Architecture | one Aegis worker hosting both the SPA and the compute (backtest service), §3 | separate compute process; client-side compute |
| Triad | intentionally suspended (2026-10-09), resumes later with Aegis as a base; untouched here | — |

## 3. Architecture and component map

Everything new lives under `app/products/aegis/`. Dependencies point one way: browser → worker HTTP → `data`, `backtest`, `optimize`, `runs`. The worker imports Core only for `local_headers` and `Store` (status), as today; Triad is never imported (`tests/test_architecture.py` enforces).

| Component | Path | Responsibility |
|---|---|---|
| Worker | `app/products/aegis/server.py` (existing) | FastAPI on 8102; keeps `local_headers`, the status contract (`mode human_directed`, `exchange CLOSED`), `GET /aegis/api/strategy/default`; gains the routers below and a static mount for the built UI; serves a one-line "UI not built" page when `ui/dist` is absent. |
| Data layer | `app/products/aegis/data.py` (new) | Archive discovery, loading, time localization, resampling, in-memory cache, provenance block. §6. |
| Engine | `app/products/aegis/backtest.py`, `strategy.py` (existing) | Deterministic closed-bar-signal / next-bar-open-fill backtester; extended per §5 only. |
| Optimizer | `app/products/aegis/optimize.py` (new) | Grid expansion from `StrategySpec.optimization`, background job runner, progress, cancel, heatmap assembly. |
| Persistence | `app/products/aegis/runs.py` (new) | JSON persistence of runs and optimizations under `data/aegis/`, list and fetch. |
| UI | `app/products/aegis/ui/` (new) | Vite React TypeScript app; `src/` committed, `dist/` and `node_modules/` gitignored. |
| Chart adapter | `ui/src/chart/adapter.ts`, `vela.ts`, (`lightweight.ts` only if needed) | Panels depend on the interface, never on a library. |

The old `static/index.html` is retired once the app renders the same layout.

## 4. Frontend

### 4.1 Build and serving
Vite with `base: "/aegis/"`. `npm run build` → `ui/dist/`; the worker mounts it at `/aegis/` with `index.html` for the app route, reachable through Core's gateway as today. Development: `vite dev` proxies `/aegis/api` to 8102 for hot reload against real data. `tools/build_aegis_ui.ps1` runs `npm ci` and `npm run build`; `package-lock.json` is committed.

### 4.2 Layout (the locked shell, as components)
Live in this slice: topbar (symbol, timeframe, date range, Run Backtest, Optimize); chart panel with symbol tabs, OHLC readout, legend; right panel Strategy tab (indicator lengths, long and short side cards with entry and exit rules and enable toggles, clock windows with mode, execution, optimization ranges); result tabs Backtest Summary, Trades, Equity Curve, Optimization; status strip. Present but inert and visibly disabled, with honest empty states: other sidebar entries, the Indicators and Objects tabs, Walk-Forward and Logs. Nothing fabricated is displayed.

### 4.3 State and contracts
One `WorkspaceProvider` with a reducer over the `StrategySpec` document, the data selection, the last run, and the optimization job; plain `fetch` wrappers; optimization progress polled every second. TypeScript types for `StrategySpec`, `BacktestRequest`, run and optimization results are generated from the Pydantic models' JSON schema by a repo script into `ui/src/contracts.ts`; a Python test fails when the generated file is stale.

### 4.4 Chart adapter and the Vela spike
Interface: `mount(el)`, `setBars(bars, timeframe)`, `setOverlays([{id, color, points}])`, `setMarkers([{time, price, side, kind}])`, `onCrosshair(cb)`, `resize()`, `destroy()`.

Vela facts established before this design (docs.luxalgo.com, npm 0.7.0): constructor `new Vela(container, {data, timeframe, theme})` with bars `{time (epoch ms, open time), open, high, low, close, volume}`; `setMarket({data})`; `renderer.onCrosshairMove`, `renderer.onClick`; `marks.add` for time-anchored glyphs; `drawings.add`; `addNativeIndicator` for plugin-SDK native types; `resize()`, `destroy()`. Not documented: plotting a precomputed numeric line without a scripting engine; the Pine engine addon depends on an AGPL project and is excluded.

The first chart task is a half-day, time-boxed spike answering three questions: (1) can Vela draw our server-computed EMA and SMA arrays without the Pine engine (native indicator via the plugin SDK, or drawings); (2) do `marks.add` plus drawings give acceptable entry and exit markers; (3) does it run under Core's content-security policy (`default-src 'self'; script-src 'self' 'unsafe-inline'`), in particular whether it needs blob-URL workers. If (1) fails, `lightweight.ts` becomes this slice's backend and the Vela adapter is kept for later; if (3) needs a policy change, that decision returns to the operator. The panels are unaffected either way.

### 4.5 Browser verification
A Python Playwright script under `tests/products/aegis/` (the repo's existing pattern) drives the acceptance flow in §1 against the real worker.

## 5. Engine additions (test first, each)

1. **Indicator series in results**: `series: {ema_9: [...], sma_30: [...]}` aligned to bar times, taken from the values the engine traded on. Markers are derived from existing trade records in the server layer.
2. **Clock window modes**: BLOCK suppresses new entries whose signal bar falls inside the window; ALLOW permits entries only inside its windows; exits are never suppressed; MODIFY_RISK is rejected with a clear error. Event windows stay ANALYZE-only (no feed); the `events` array keeps working for hand-supplied points.
3. **Exposure metric**: fraction of bars with an open position, per side and combined.
4. **Parameter paths**: `apply_parameters(spec, {"indicators.ema_9.length": 12, ...})` returns a new `StrategySpec`; cells with fast ≥ slow are skipped and reported, not run.
5. **Input bounds**: `bars` ≤ 200,000 and `events` ≤ 10,000 (`max_length`), closing the Mission 2 QA finding.
6. **Performance unchanged**: ≈0.14 ms per bar measured on this machine (10-year 1h = 17,533 bars → 2.4 s; 1D → 0.4 s). The default 272-cell grid on 1h data is ≈11 minutes behind the job runner. A vectorized crossover path is the first follow-on if needed; not built here.

## 6. Data layer (`data.py`)

- Discovery: `data/raw/HFDataLibrary/<vintage>/*_1m_10y.parquet`, newest vintage wins, symbol from filename; root-level orphan copies ignored. `report.json` and `*-daily-coverage.csv` supply coverage (SPY, QQQ ≈97%; ITOT ≈64%) and the vendor splice (PiTrading → IEX, 2022) for `GET data/symbols`. Gaps are shown, never repaired.
- Loading: PyArrow → pandas (≈0.7 s per symbol). Naive timestamps localized to America/New_York; DST-ambiguous minutes dropped. Bars labeled by open time, emitted as epoch milliseconds.
- Resampling: 1D per trading day; 15m, 30m, 1h anchored at 09:30 (hourly bars 09:30–10:30 …, final 15:30–16:00 stub). Empty buckets dropped. The archive is regular-session only, so `regular_session_only` holds and extended hours are documented as unavailable.
- Cache and warm-up: all four timeframes per symbol computed once (≈6 s) and held in memory; a background thread warms the three symbols at worker startup (≈20 s); a request before warm-up waits for its symbol.
- Provenance on every response: `data: {source: "raw_archive", vintage, vendor_sources, research_eligible: false}`; the chart header carries the permanent badge. Core's canonical store, manifests and research lab are never read or written.

## 7. Backend API (Aegis worker, `/aegis/api/`)

| Route | Purpose | Notes |
|---|---|---|
| `GET data/symbols` | archives on disk with vintage, first/last bar, 1-minute rows, timeframes, coverage, provenance | |
| `GET data/bars?symbol&timeframe&start&end` | `{symbol, timeframe, timezone, bars, count, data}` | `timeframe` ∈ {1D, 1h, 30m, 15m}; `start`/`end` are inclusive `YYYY-MM-DD` dates in America/New_York; cap 50,000 bars → 422 with "narrow the range" |
| `POST indicators` | `{symbol, timeframe, start, end, indicators}` → series per indicator | lets the chart redraw without a run |
| `POST backtest` | existing body plus `data` reference `{symbol, timeframe, start, end}` as the normal input; `bars` still accepted | response adds `run_id`, `series`, `markers`, `data`; persisted |
| `GET runs`, `GET runs/{run_id}` | list and fetch persisted runs | 404 unknown |
| `POST optimize` | `{strategy, data, settings, objective}` → `202 {job_id, total, estimated_seconds}` | `objective` ∈ {net_pnl, mar, max_drawdown, trade_count} selects the default heatmap; grid ≤ 400 cells; fast ≥ slow cells skipped; 409 if a job is running |
| `GET optimize/{job_id}` | `status` queued/running/done/cancelled/failed/lost, `progress {done,total}`, elapsed; on completion cell results and heatmap matrices for net P&L, MAR, max drawdown, trade count | matrices are rows = fast (EMA) lengths ascending, columns = slow (SMA) lengths ascending, `null` for skipped cells; one matrix per side (long, short, combined) per metric |
| `POST optimize/{job_id}/cancel` | cooperative cancel between cells | |

One optimization at a time on a dedicated single-worker thread; request handling stays responsive. Finished jobs persisted; unfinished jobs are marked `lost` after a worker restart. Estimate = cells × bars × 0.14 ms. No authentication, like every route on this loopback-only host; nothing touches money, credentials or Core state.

## 8. Operations and packaging

- Supervision: `ensure_triad_worker.py` becomes `ensure_product_worker.py --product aegis|triad` (same health-then-launch logic; 8102 for Aegis), and `run_core_supervisor.py` calls it for both products. This closes the audit's "nothing supervises Aegis" gap (the worker restarted on 2026-10-09 survives only because it was spawned detached). Tests mirror `tests/test_triad_worker_supervisor.py`.
- Build: `tools/build_aegis_ui.ps1`; `ui/node_modules`, `ui/dist` gitignored; worker detects `dist/` at startup. `tools/start_product.ps1` unchanged.
- Packaging: `pyproject.toml` package-data for `products.aegis` widened to `ui/dist/**`.
- Storage: `data/aegis/` (gitignored under `data/*`).
- Security header: Core's CSP kept; the spike confirms compatibility; any needed change is an operator decision.
- Stale copies: `app/products/aegis/resources/product.json` aligned to `config/aegis/product.json` (ACTIVE_DEVELOPMENT). Core's `static/launch.html` Aegis card is Core-owned and listed as a separate change, not part of this slice.
- Runtime: no new ports, processes or scheduled tasks beyond the supervisor change. Exchange CLOSED; `mode human_directed`; providers, credentials, Postgres schema and Triad untouched.

## 9. Testing and verification

- Engine and backend: pytest, DB-free, test first for every behaviour in §5, §6, §7 (window gating, exposure, parameter paths, series, bounds, data-reference runs, resampler and cache, discovery, persistence round-trip, grid expansion, job lifecycle incl. cancel and 409, heatmap matrices); determinism tests kept.
- API: `TestClient` with `Store` stubbed; error paths 422/404/409; contracts-sync test for `ui/src/contracts.ts`.
- Frontend: vitest for reducer, request builders, heatmap mapping, adapter against a mock backend.
- Browser: Playwright flow of §1 against the real worker, run by hand and recorded as evidence; the milestone acceptance test.
- Whole suite: bare `pytest` green; architecture test green; ruff clean on touched files.
- Milestone QA: one independent agent at the exact commit, as in Missions 1 and 2.

## 10. Non-goals

No live or paper trading, broker, order or account path (Paper Trade stays disabled). No event feed; event windows ANALYZE-only. No MODIFY_RISK, stops, targets, sizing beyond allocation fraction, or multi-symbol portfolios. No walk-forward, plateau or stability scoring, or clustering. No vectorized engine. No new data downloads, canonical promotion, Core research-lab integration, or persistence into Core's Postgres/Neo4j. No Core chat or Intake wiring; no provider or model calls from Aegis. No Pine engine (AGPL), no Vela Pro. No auth, multi-user, CI changes, or React Native. Nothing under `app/products/triad/` changes.

## 11. Suggested build order (input to the implementation plan)

1. Vela spike (time-boxed) → choose chart backend for the slice.
2. Data layer with tests; `data/symbols`, `data/bars`, `indicators` routes.
3. Engine additions with tests (series, window modes, exposure, parameter paths, bounds).
4. Backtest route with data reference, markers, persistence; `runs` routes.
5. Optimizer module, job runner, routes, persistence.
6. UI scaffold, contracts generation and sync test, `WorkspaceProvider`, static mount, build script.
7. Chart panel via adapter; topbar and Strategy panel; results tabs and status strip; Optimization tab with polling and heatmap.
8. Supervisor generalization with tests; packaging and stale-copy alignment.
9. Browser flow, evidence, milestone QA.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Vela cannot plot numeric overlays without the AGPL engine | adapter boundary; lightweight-charts fallback decided by the spike |
| Vela needs blob-URL workers blocked by CSP | spike detects; policy change is an operator decision |
| Optimizer too slow on 15m/30m ranges | job runner with progress and cancel; grid cap; estimate shown before start; vectorized path as follow-on |
| Archive gaps (ITOT 64% coverage) distort results | coverage shown per symbol; no silent repair |
| Contracts drift between Python and TypeScript | generated `contracts.ts` with a sync test |
| Aegis worker dies unsupervised | supervisor generalization in §8 |
