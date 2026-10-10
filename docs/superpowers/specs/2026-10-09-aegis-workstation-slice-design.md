# Aegis Workstation — first vertical slice (design)

- Date: 2026-10-09 (revision 2, incorporating the operator's implementation brief of the same day)
- Status: **approved for implementation** with the revisions in §2b
- Mission: 3 ("restart the Aegis worker, then start the UI-first slice on top of the existing strategy and backtest modules rather than from the shell")
- Governance: ordinary reversible Aegis product work under `AGENTS.md` product-first rules; one independent QA at the milestone. The supervisor change in §8 touches `tools/` and gets its own tests. If implementation unexpectedly touches live money, exchange/broker execution, credentials, authority, destructive operations, migrations, canonical data, shared Core contracts or product isolation, that part stops and is surfaced separately.
- Predecessors: `CORE_STATE_AUDIT.md`, `docs/MISSION1_QUIET_GREEN_BASELINE.md`, `docs/MISSION2_RECONCILE_AND_ADOPT.md`, `docs/CORE_CHAT_VISION.md` (including the 2026-10-09 operator correction)

## 1. Intent and definition of done

The operator wants a functioning, inspectable trading research application, built UI-first against the locked interface design that is now the Aegis shell on `main` (`app/products/aegis/static/index.html`). **The locked workstation UI is the product contract**: build functionality to make its boxes real; backend architecture does not reshape the interface unless a genuine technical blocker is raised. The 9 EMA / 30 SMA crossover is the first reference strategy, not the architecture.

The milestone is complete only when the operator can open Aegis and:

1. select QQQ; 2. select 1m, 15m, 30m, 1h or 1D; 3. choose a date range; 4. see real candles from the pinned raw archive; 5. see the permanent RAW ARCHIVE / NOT RESEARCH ELIGIBLE indicator; 6. see the 9 EMA and 30 SMA; 7. run a backtest; 8. inspect real entries and exits; 9. inspect LONG results independently; 10. inspect SHORT results independently; 11. inspect COMBINED results; 12. inspect temporal performance; 13. inspect trades; 14. inspect equity; 15. see real KPIs; 16. reload the saved experiment; 17. launch an optimization; 18. watch progress; 19. cancel it; 20. inspect progressively completed parameter cells; 21. view the final heatmap and table; 22. rerun an identical computational request and obtain the same `result_hash`.

Plus: the whole suite green; Aegis imports neither Triad nor the platform host; live execution disabled; exchange CLOSED.

**Permanent honesty rule.** Nothing fabricated is displayed. No placeholder P&L, trade counts, equity, heatmap values, data quality, metrics or event matches may look like a completed calculation. Use empty states, em dashes, disabled controls, "not connected", "not run", "feed unavailable".

## 2. Operator decisions recorded in this design

| Decision | Choice | Alternatives declined |
|---|---|---|
| UI stack | React 18 + Vite + TypeScript under `app/products/aegis/ui/` | wiring the vanilla shell; Vite + TS without a framework |
| Chart library | Vela (`@luxalgo/vela`, Apache-2.0 core only) first, behind an adapter; TradingView lightweight-charts as the fallback if the spike in §4.4 fails. Required NOTICE/attribution kept visible for whichever is used. | lightweight-charts first |
| Market data | Aegis reads the raw QQQ/SPY/ITOT 1-minute archives directly and resamples them, labeled raw and not research-eligible; Core's canonical store is untouched | synthetic fixtures only; raw plus fixture toggle |
| Architecture | one Aegis worker hosting both the SPA and the compute (backtest service), §3 | separate compute process; client-side compute |
| Triad | intentionally suspended (2026-10-09), resumes later with Aegis as a base; untouched here | — |

### 2b. Revisions from the implementation brief (2026-10-09)

1. **Long/short asymmetry is structural.** Each `StrategySide` owns its indicators (and their parameters), entry, exit, enabled state and optimization ranges. Defaults may both be 9 EMA / 30 SMA, but the optimizer must be able to end with, for example, LONG EMA 11 / SMA 35 and SHORT EMA 6 / SMA 52. No four-dimensional joint grid in this slice: optimize LONG independently, optimize SHORT independently, and let COMBINED use the selected long configuration plus the selected short configuration. The UI may offer a "link long/short parameters" convenience; the model never requires symmetry.
2. **Deterministic result identity.** Run envelopes may differ in run id, job id, created timestamp and elapsed time. Determinism applies to a **canonical result payload** (strategy spec and version, data identity, trades, equity series, metrics, indicator series, markers, temporal breakdown), serialized canonically and hashed to `result_hash`. Two identical computational requests against identical data yield identical canonical payloads and identical `result_hash`; tests prove it.
3. **Pinned raw-data provenance.** "Newest vintage wins" applies only when creating a new experiment. Every run and optimization pins its source: symbol, `source=raw_archive`, vintage, relative file path, file SHA-256, first bar, last bar, source row count, timeframe, selected date range, resampling policy/version, filtered/resampled data hash, `research_eligible=false`. Reloading never substitutes a newer archive; if the pinned source is unavailable the run reports an explicit source-unavailable state rather than falling forward.
4. **UI appears early.** Build order is the ten phases in §11: chart spike, then the full React shell with honest empty states, then data, indicators, backtest, results, persistence, optimizer, supervisor/packaging, acceptance and QA. After Phase 2 the product is visibly there; each later phase lights up an existing region.
5. **Temporal precedence.** BLOCK always wins: a signal inside any active BLOCK window suppresses the new entry (exits never suppressed). If a side has one or more ALLOW windows, an entry must fall inside at least one ALLOW window and outside every BLOCK window. ANALYZE never changes execution; it tags observations and trades and produces segmented metrics. MODIFY_RISK is rejected with an explicit unsupported-mode error, never treated as ANALYZE or ALLOW.
6. **Market crossovers are real in the first product.** Clock-derived ANALYZE tags for at least the US cash open / futures-to-cash transition and the London / New York overlap, computed from the strategy's timezone, without external feeds. The same primitive later extends to other transitions.
7. **Rumor/news stays schema-only.** RUMOR_NEWS remains present, ANALYZE-only, "feed unavailable"; the generic event-window contract is what a future mention/rumor feed plugs into. No fabricated events.
8. **Persistence boundary.** A narrow `RunRepository` interface with `JsonRunRepository` under `data/aegis/` for this slice; a Core-backed implementation is a future option and is not built now.
9. **Optimizer responsiveness.** Before starting: total valid cells, skipped cells, estimated runtime. Results become available progressively as cells complete; the heatmap and table update from partial results. Indicator arrays are computed once per unique period and reused across cells. Acceptance coverage: progress advances, the progress route stays responsive while running, cancellation works, the UI/API stays responsive, completed cells are visible before completion. A background thread is the first architecture; if it cannot stay responsive on this host, the optimizer moves to a local process (no process pools preemptively).
10. **1-minute timeframe is in scope** alongside 15m, 30m, 1h and 1D; the bar cap protects oversized requests with a clear range-too-large response. The public data API is not changed later to add it.
11. **Indicator / strategy separation.** Indicator computes series; Strategy Side consumes series and defines entry, exit and side-specific parameters; Temporal Context qualifies and tags; Execution defines signal and fill assumptions; Optimization varies declared parameters. No hard-coded EMA/SMA UI path that blocks future studies.
12. **Core relationship.** Core stays the shared substrate (providers, memory/knowledge, trusted data and provenance patterns, runtime, future intake). Aegis owns indicators, strategy semantics, asymmetry, temporal market context, backtesting, optimization, validation and workstation UX. No trading semantics move into Core; no Core redesign.

## 3. Architecture and component map

Everything new lives under `app/products/aegis/`. Dependencies point one way: browser → worker HTTP → `data`, `indicators`, `backtest`, `optimize`, `runs`. The worker imports Core only for `local_headers` and `Store` (status), as today; Triad is never imported (`tests/test_architecture.py` enforces).

| Component | Path | Responsibility |
|---|---|---|
| Worker | `app/products/aegis/server.py` (existing) | FastAPI on 8102; keeps `local_headers`, the status contract (`mode human_directed`, `exchange CLOSED`), `GET /aegis/api/strategy/default`; gains the routers below and a static mount for the built UI; serves a one-line "UI not built" page when `ui/dist` is absent. |
| Data layer | `app/products/aegis/data.py` (new) | Archive discovery, pinned source descriptors, loading, time localization, resampling (policy version), in-memory cache, data hash, provenance block. §6. |
| Indicators | `app/products/aegis/indicators.py` (new) | Pure series calculators (EMA, SMA; extensible registry keyed by `kind`), cached per (data identity, kind, source, length). |
| Strategy contracts | `app/products/aegis/strategy.py` (existing, revised) | Side-owned indicators, rules, enabled, optimization ranges; temporal context incl. market crossovers; execution. §5.1. |
| Engine | `app/products/aegis/backtest.py` (existing, revised) | Deterministic closed-bar-signal / next-bar-open-fill backtester; per-side simulation from that side's indicators; temporal precedence; canonical result and `result_hash`. §5. |
| Optimizer | `app/products/aegis/optimize.py` (new) | Per-side grid expansion, job runner, progressive results, cancel, indicator cache reuse, heatmap assembly, combined-from-selection. |
| Persistence | `app/products/aegis/runs.py` (new) | `RunRepository` interface; `JsonRunRepository` under `data/aegis/`; pinned source, canonical payload, `result_hash`, envelope. |
| UI | `app/products/aegis/ui/` (new) | Vite React TypeScript app; `src/` committed, `dist/` and `node_modules/` gitignored. |
| Chart adapter | `ui/src/chart/adapter.ts`, `vela.ts`, (`lightweight.ts` only if needed) | Panels depend on the interface, never on a library. No strategy, result, temporal or UI state logic depends on a chart library. |

The old `static/index.html` is retired once the app renders the same layout.

## 4. Frontend

### 4.1 Build and serving
Vite with `base: "/aegis/"`. `npm run build` → `ui/dist/`; the worker mounts it at `/aegis/` with `index.html` for the app route, reachable through Core's gateway as today. Development: `vite dev` proxies `/aegis/api` to 8102 for hot reload against real data. `tools/build_aegis_ui.ps1` runs `npm ci` and `npm run build`; `package-lock.json` is committed. The chart library's NOTICE/attribution ships with the build and stays visible where its license requires.

### 4.2 Layout (the locked shell, as components)
Visual contract: chart-centric, compact information density, workstation feel, clear hierarchy, dark technical language, results and controls visible in context; no CRUD-page or dashboard-template drift, no wasted whitespace. Major regions are not rearranged for backend convenience; a genuine technical issue with the layout is raised as a blocker.

Live in this slice: topbar (symbol, timeframe incl. 1m, date range, Run Backtest, Optimize); chart panel with symbol tabs, OHLC readout, legend; right panel Strategy tab (per-side indicator parameters with a "link long/short" convenience, long and short side cards with entry and exit rules and enable toggles, clock windows with mode, market crossovers, event windows shown as "feed unavailable", execution, per-side optimization ranges); result tabs Backtest Summary (long, short, combined), Trades, Equity Curve, Optimization (per side), plus the temporal breakdown; status strip. Present but inert and visibly disabled, with honest empty states: other sidebar entries, the Indicators and Objects tabs, Walk-Forward and Logs.

### 4.3 State and contracts
One `WorkspaceProvider` with a reducer over the `StrategySpec` document, the data selection, the last run, the selected long and short configurations, and the optimization jobs; plain `fetch` wrappers; optimization progress polled every second. TypeScript types for `StrategySpec`, requests and results are generated from the Pydantic models' JSON schema by a repo script into `ui/src/contracts.ts`; a Python test fails when the generated file is stale.

### 4.4 Chart adapter and the Vela spike
Interface: `mount(el)`, `setBars(bars, timeframe)`, `setOverlays([{id, color, points}])`, `setMarkers([{time, price, side, kind}])`, `onCrosshair(cb)`, `resize()`, `destroy()`.

Vela facts established before this design (docs.luxalgo.com, npm 0.7.0): constructor `new Vela(container, {data, timeframe, theme})` with bars `{time (epoch ms, open time), open, high, low, close, volume}`; `setMarket({data})`; `renderer.onCrosshairMove`, `renderer.onClick`; `marks.add` for time-anchored glyphs; `drawings.add`; `addNativeIndicator` for plugin-SDK native types; `resize()`, `destroy()`. Not documented: plotting a precomputed numeric line without a scripting engine; the Pine engine addon depends on an AGPL project and is excluded.

Phase 1 is a half-day, time-boxed spike answering four questions: (1) can Vela draw server-computed EMA and SMA numeric lines without the AGPL engine; (2) are entry and exit markers acceptable (`marks.add` plus drawings); (3) does it run under Core's content-security policy (`default-src 'self'; script-src 'self' 'unsafe-inline'`), including any blob-URL workers; (4) what NOTICE/attribution must be present. If (1) or (2) fails, lightweight-charts becomes this slice's backend behind the same adapter and the Vela adapter is kept for later; days are not spent forcing Vela. If (3) needs a policy change, that decision returns to the operator.

### 4.5 Browser verification
A Python Playwright script under `tests/products/aegis/` (the repo's existing pattern) drives the definition of done in §1 against the real worker.

## 5. Engine and contracts (test first, each)

### 5.1 Contract revisions (`strategy.py`)
- `StrategySide` gains `indicators: list[IndicatorSpec]` and `optimization: list[OptimizationParameter]`; rules reference the side's indicator ids; paths in `OptimizationParameter` are side-relative (`indicators.ema.length`). Top-level `indicators`/`optimization` are removed; `default_strategy()` gives both sides EMA 9 / SMA 30 with their own ranges (EMA 5→20 step 1, SMA 20→100 step 5).
- `TemporalContext` keeps clock windows, event windows and market crossovers; crossovers carry their clock definition in the strategy timezone (US cash open / futures-to-cash transition, London / New York overlap) and are ANALYZE-only here.
- `StrategySpec.version` is included in the canonical payload.

### 5.2 Engine behaviour (`backtest.py`)
1. Per-side simulation from that side's indicator series; `series` in the result per side.
2. Temporal precedence exactly as §2b.5; crossover and clock ANALYZE tags on trades and the temporal breakdown per side and combined.
3. Exposure metric (fraction of bars with an open position) per side and combined, alongside the existing metrics.
4. `apply_parameters(side, {path: value})` for the optimizer; cells with fast ≥ slow skipped and reported.
5. Canonical result payload and `result_hash` (SHA-256 over a canonical JSON serialization with sorted keys and fixed float formatting); envelope fields (ids, timestamps, elapsed) excluded.
6. Input bounds: `bars` ≤ 200,000, `events` ≤ 10,000.
7. Combined results: computed from the selected long configuration plus the selected short configuration (defaults to the spec's current sides).
8. Performance unchanged for the slice (≈0.14 ms/bar measured); indicator calculations cached and reused; measurements of backtest, indicator and cell durations recorded in the results.

## 6. Data layer (`data.py`)

- Discovery: `data/raw/HFDataLibrary/<vintage>/*_1m_10y.parquet`, newest vintage wins **for new experiments**; root-level orphan copies ignored. `report.json` and `*-daily-coverage.csv` supply coverage (SPY, QQQ ≈97%; ITOT ≈64%) and the vendor splice (PiTrading → IEX, 2022). Gaps shown, never repaired.
- Pinned source descriptor (per §2b.3): symbol, source, vintage, relative path, file SHA-256, first and last bar, row count, timeframe, date range, resampling policy version, resampled data hash, `research_eligible=false`. Reload validates the file hash; mismatch or missing file → `source_unavailable`.
- Loading: PyArrow → pandas (≈0.7 s per symbol). Naive timestamps localized to America/New_York; DST-ambiguous minutes dropped. Bars labeled by open time, emitted as epoch milliseconds.
- Resampling (policy `rth-anchored-v1`): 1m passthrough; 15m, 30m, 1h anchored at 09:30; 1D per trading day. Empty buckets dropped. Regular-session archive, so `regular_session_only` holds; extended hours unavailable.
- Cache and warm-up: all timeframes per symbol computed once and held in memory; background warm-up of the three symbols at worker startup; a request before warm-up waits for its symbol.
- Response cap 50,000 bars (1m full day ≈390 bars; a 1m request beyond the cap gets a clear range-too-large 422).
- Provenance on every response: the pinned descriptor's public fields; the chart header carries the permanent badge. Core's canonical store, manifests and research lab are never read or written.

## 7. Backend API (Aegis worker, `/aegis/api/`)

| Route | Purpose | Notes |
|---|---|---|
| `GET data/symbols` | archives on disk with vintage, first/last bar, rows, timeframes, coverage, provenance | |
| `GET data/bars?symbol&timeframe&start&end` | `{symbol, timeframe, timezone, bars, count, data}` | `timeframe` ∈ {1m, 15m, 30m, 1h, 1D}; `start`/`end` inclusive `YYYY-MM-DD` America/New_York; cap 50,000 → 422 range-too-large |
| `POST indicators` | `{symbol, timeframe, start, end, indicators}` → series per indicator | chart redraw without a run |
| `POST backtest` | `{strategy, data: {symbol, timeframe, start, end}, events, settings}`; `bars` still accepted for tests | response: envelope (`run_id`, `created_at`, `elapsed_ms`) + canonical payload + `result_hash` + pinned `data` + `series` + `markers`; persisted |
| `GET runs`, `GET runs/{run_id}` | list and reload persisted runs | 404 unknown; `source_unavailable` state when the pinned archive is gone |
| `POST optimize` | `{strategy, side: long\|short, data, settings, objective}` → `202 {job_id, total_cells, skipped_cells, estimated_seconds}` | per side; `objective` ∈ {net_pnl, mar, max_drawdown, trade_count}; grid ≤ 400 cells; 409 if a job is running |
| `GET optimize/{job_id}` | `status` queued/running/done/cancelled/failed/lost, `progress {done,total}`, elapsed, **partial cells so far**, heatmap matrices (rows fast ascending, columns slow ascending, null skipped) for all four metrics | progressive |
| `POST optimize/{job_id}/cancel` | cooperative cancel between cells | |
| `GET optimize`, `GET optimize/{job_id}` after completion | persisted optimizations | |

One optimization at a time on a dedicated single-worker thread; the progress route and the rest of the API stay responsive (acceptance-tested). Finished jobs persisted; unfinished jobs are `lost` after a worker restart. No authentication, like every route on this loopback-only host; nothing touches money, credentials or Core state.

## 8. Operations and packaging

- Supervision: `ensure_triad_worker.py` → `ensure_product_worker.py --product aegis|triad` (same health-then-launch logic; 8102 for Aegis); `run_core_supervisor.py` calls it for both. Tests mirror `tests/test_triad_worker_supervisor.py`.
- Build: `tools/build_aegis_ui.ps1`; `ui/node_modules`, `ui/dist` gitignored; worker detects `dist/` at startup. `tools/start_product.ps1` unchanged.
- Packaging: `pyproject.toml` package-data for `products.aegis` widened to `ui/dist/**`.
- Storage: `data/aegis/` (gitignored under `data/*`).
- Security header: Core's CSP kept; the spike confirms compatibility; any needed change is an operator decision.
- Stale copies: `app/products/aegis/resources/product.json` aligned to `config/aegis/product.json`. Core's `static/launch.html` Aegis card is Core-owned and a separate change.
- Runtime: no new ports, processes or scheduled tasks beyond the supervisor change. Exchange CLOSED; `mode human_directed`; providers, credentials, Postgres schema and Triad untouched.

## 9. Testing and verification

- Engine and backend: pytest, DB-free, test first for every behaviour in §5–§7 (side-owned parameters and asymmetric defaults, temporal precedence incl. MODIFY_RISK rejection, crossover tags, exposure, parameter paths, series, bounds, canonical payload and `result_hash` identity across differing envelopes, pinned source and `source_unavailable`, resampler incl. 1m and cache, discovery, repository round-trip, grid expansion with skipped cells, job lifecycle incl. cancel, progressive results and 409, heatmap matrices, indicator cache reuse).
- API: `TestClient` with `Store` stubbed; error paths 422/404/409; responsiveness of the progress route during a running job; contracts-sync test for `ui/src/contracts.ts`.
- Frontend: vitest for reducer, request builders, heatmap mapping, adapter against a mock backend.
- Browser: Playwright flow covering the 22 items of §1 against the real worker, run by hand and recorded as evidence.
- Whole suite: bare `pytest` green; architecture test green; ruff clean on touched files; measurements of backtest, indicator and cell durations and UI responsiveness recorded.
- Milestone QA: one independent agent at the exact commit, as in Missions 1 and 2.

## 10. Non-goals

No live or paper trading, broker, order or account path (Paper Trade stays disabled). No event or rumor feed; event windows ANALYZE-only and "feed unavailable". No MODIFY_RISK, stops, targets, sizing beyond allocation fraction, or multi-symbol portfolios. No joint four-dimensional long×short optimization, walk-forward, plateau or stability scoring, clustering, regime systems or HA-MQI. No vectorized engine rewrite before measurement. No new data downloads, canonical promotion, Core research-lab integration, Graph-RAG, or persistence into Core's Postgres/Neo4j (the `RunRepository` boundary keeps that option open). No Core chat or Intake wiring; no provider or model calls from Aegis; no agent frameworks or planning frameworks. No Pine engine (AGPL), no Vela Pro. No auth, multi-user, CI changes, or React Native. Nothing under `app/products/triad/` changes.

## 11. Build order (ten phases)

1. **Chart technology spike** (time-boxed) → chart backend decision and attribution requirements.
2. **React workstation shell**: the full locked interface as components with honest empty states; navigation, topbar, chart panel, strategy surface with long and short cards, temporal controls, results tabs, optimizer area, status strip. The product is visibly there.
3. **Data**: symbol, timeframe (incl. 1m) and date range wired to pinned raw data.
4. **Indicators**: real candles, EMA and SMA.
5. **Backtest**: Run Backtest real, per side, with `result_hash`.
6. **Results**: trades, equity, metrics, markers, long/short/combined, temporal breakdown.
7. **Persistence**: `RunRepository`, save and reload with pinned source.
8. **Optimizer**: per-side grids, progressive results, cancel, heatmap and table.
9. **Supervisor and packaging**.
10. **Browser acceptance and milestone QA**.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Vela cannot plot numeric overlays or markers without the AGPL engine | adapter boundary; lightweight-charts fallback decided by the spike |
| Vela needs blob-URL workers blocked by CSP | spike detects; policy change is an operator decision |
| Optimizer too slow or unresponsive on a background thread | progressive results, indicator cache, estimate before start, cancel; move to a local process if measured to be necessary |
| Archive gaps (ITOT 64% coverage) distort results | coverage shown per symbol; no silent repair |
| Contracts drift between Python and TypeScript | generated `contracts.ts` with a sync test |
| Aegis worker dies unsupervised | supervisor generalization in §8 |
| Reload against a replaced archive | pinned file hash; explicit `source_unavailable` |
