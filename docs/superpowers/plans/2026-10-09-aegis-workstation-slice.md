# Aegis Workstation Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the locked Aegis workstation UI real end to end: pinned raw-archive candles with EMA/SMA, deterministic per-side backtests with `result_hash`, persisted runs, and a progressive per-side grid optimizer, served by the single Aegis worker.

**Architecture:** One FastAPI worker (`app/products/aegis/server.py`, port 8102) hosts a Vite/React SPA and the compute routes. Pure Python modules own data (`data.py`), indicators (`indicators.py`), temporal rules (`temporal.py`), the engine (`backtest.py`), result identity (`results.py`), persistence (`runs.py`) and the optimizer (`optimize.py`); `api.py` wires them. The browser talks only HTTP; the chart library sits behind `ui/src/chart/adapter.ts`.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2, pandas, pyarrow, pytest; React 18, Vite 5, TypeScript 5, vitest; `@luxalgo/vela` (Apache-2.0 core only) or `lightweight-charts` (decided by Task 1); Python Playwright for the browser flow.

**Spec:** `docs/superpowers/specs/2026-10-09-aegis-workstation-slice-design.md` (revision 2)

## Global Constraints

- All new code under `app/products/aegis/`, `tests/` (Aegis files), `tools/` (supervisor and build only), `docs/`; nothing under `app/trading_core/`, `app/platform_host/`, `app/products/triad/`, `config/`, `control-plane/`, `infrastructure/`.
- Aegis imports neither `products.triad`, `triad` nor `platform_host` (`tests/test_architecture.py` enforces).
- Status contract unchanged: `/aegis/api/status` returns `mode: "human_directed"`, `exchange: "CLOSED"`.
- Timeframes: exactly `1m, 15m, 30m, 1h, 1D`. Bars cap: 50,000 per response. Grid cap: 400 cells. Bounds: `bars` ≤ 200,000, `events` ≤ 10,000.
- Resampling policy id: `rth-anchored-v1`. Timezone for sessions: `America/New_York`. Bar `time` = open time, epoch milliseconds.
- Provenance fields on every data-bearing response: `source: "raw_archive"`, `research_eligible: false`, plus the pinned descriptor (spec §6).
- Determinism: `result_hash` = SHA-256 of the canonical payload (spec §2b.2); envelope fields never enter it.
- Temporal precedence: BLOCK > ALLOW; ANALYZE never changes execution; MODIFY_RISK → `ValueError("unsupported window mode: MODIFY_RISK")`.
- Honesty rule: no fabricated values anywhere in the UI; empty states say `—`, "not run", "not connected", "feed unavailable".
- Commit after every task with the `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer; bare `pytest` and `ruff check` clean on touched files before each commit.
- Chart library attribution shipped and visible as its license requires; no Pine/PineTS.

## Review Focus

1. A 1m request spanning years (over the 50,000 cap) must return 422 with the range hint, never a hung worker — Task 7 test `test_bars_over_cap_returns_422_with_hint`.
2. Reloading a run whose archive file changed must report `source_unavailable`, never recompute silently against the new file — Task 10 test `test_reload_with_changed_file_hash_is_source_unavailable`.
3. A side whose rules reference an indicator id it does not own must be rejected at validation, not fail mid-simulation — Task 3 test `test_rule_referencing_unknown_indicator_is_rejected`.
4. A second optimization while one is running must get 409 and must not disturb the running job's progress — Task 12 test `test_second_job_while_running_is_409_and_first_continues`.
5. The symbol menu must reflect disk, so a missing archive file shows as absent rather than erroring the whole menu — Task 7 test `test_discovery_skips_symbols_with_missing_parquet`.

---

### Task 1: Chart technology spike (time-boxed, half a day)

**Files:**
- Create: `app/products/aegis/ui/spike/` (throwaway; deleted at the end of this task), `docs/superpowers/plans/2026-10-09-chart-spike-result.md`

**Interfaces:**
- Produces: the decision `CHART_BACKEND = "vela" | "lightweight"` recorded in the result doc, the attribution text required, and whether Core's CSP needs changes.

- [ ] **Step 1: Scaffold a throwaway Vite vanilla-TS page in `ui/spike/` with `npm init -y && npm i vite typescript @luxalgo/vela`; load 500 synthetic bars via `new Vela('#chart', {data, timeframe: '1h', theme: 'dark'})`.**
- [ ] **Step 2: Attempt numeric overlays without Pine: try `addNativeIndicator` with a plugin-SDK native type that plots a supplied array, then `drawings.add` polylines. Record which works and the API used.**
- [ ] **Step 3: Attempt markers: `marks.add({time, glyph, title})` for entries/exits and a price-anchored label via `drawings.add`. Record acceptability (visible at the bar, distinguishable long/short entry/exit).**
- [ ] **Step 4: Serve the built spike through the Aegis worker (temporary static mount) and load it via `http://127.0.0.1:8102`; record any CSP violations from the browser console (blob workers, eval).**
- [ ] **Step 5: Record NOTICE/attribution requirements from the package's LICENSE/NOTICE files and the docs FAQ.**
- [ ] **Step 6: Decide.** If overlays (Step 2) and markers (Step 3) both work under CSP (Step 4): `vela`. Otherwise install `lightweight-charts`, confirm `addLineSeries`/`setMarkers` in ten minutes, and decide `lightweight`. Write the result doc with the decision, the exact API calls, attribution text, and CSP findings.
- [ ] **Step 7: Delete `ui/spike/`; commit the result doc.**

```bash
git add docs/superpowers/plans/2026-10-09-chart-spike-result.md
git commit -m "Aegis: chart technology spike result"
```

---

### Task 2: Contract generation and UI scaffold (the locked shell as components)

**Files:**
- Create: `tools/aegis_contracts.py`, `tests/test_aegis_contracts.py`, `tools/build_aegis_ui.ps1`, `app/products/aegis/ui/{package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html, src/main.tsx, src/App.tsx, src/styles.css, src/contracts.ts, src/api/client.ts, src/state/workspace.tsx, src/state/workspace.test.ts, src/components/*.tsx}`
- Modify: `app/products/aegis/server.py` (static mount + "UI not built" page), `.gitignore`, `pyproject.toml`

**Interfaces:**
- Produces: `tools/aegis_contracts.py` → writes `ui/src/contracts.ts` from `StrategySpec`, `BacktestRequest`, `DataReference`, `PinnedSource` JSON schemas (TS `interface`s/unions; `--check` exits 1 if stale); `WorkspaceState {strategy, selection {symbol, timeframe, start, end}, lastRun, linkSides: boolean, optimization {long?: Job, short?: Job}, selectedConfigs {long, short}}`; reducer actions `SET_SELECTION`, `SET_STRATEGY`, `SET_SIDE_PARAM {side, path, value}` (mirrors to the other side when `linkSides`), `RUN_STARTED/RUN_COMPLETED/RUN_FAILED`, `JOB_UPDATED {side, job}`; `api/client.ts` functions matching spec §7 routes; components: `TopBar`, `SideNav`, `ChartPanel`, `StrategyPanel`, `SideCard`, `TemporalPanel`, `ExecutionPanel`, `OptimizationRanges`, `ResultsTabs`, `SummaryTab`, `TradesTab`, `EquityTab`, `OptimizationTab`, `Heatmap`, `StatusStrip`.

- [ ] **Step 1: Write `tests/test_aegis_contracts.py::test_contracts_ts_is_current`** (regenerate to a string and compare with the file).
- [ ] **Step 2: Implement `tools/aegis_contracts.py` (pydantic `model_json_schema()` → TS; handles object, array, enum, anyOf-null, string/number/integer/boolean, `$ref`) and generate `contracts.ts`.**
- [ ] **Step 3: Scaffold Vite React TS in `ui/` (`base: "/aegis/"`, dev proxy `/aegis/api` → `http://127.0.0.1:8102`); port the shell's CSS tokens to `styles.css`; build every region of the locked layout as components with honest empty states (`—`, "not run", "not connected", "feed unavailable"); disabled nav items, Indicators/Objects, Walk-Forward, Logs. Include the 1m timeframe option. Add the chart library's NOTICE text to an "About" footer/status entry per Task 1.**
- [ ] **Step 4: Write `src/state/workspace.test.ts` (vitest):** `linked param change mirrors to the other side`, `unlinked change affects one side only`, `RUN_COMPLETED stores run and clears error`.
- [ ] **Step 5: `server.py`: mount `ui/dist` at `/aegis/` when present (`StaticFiles(html=True)`), else serve `<p>UI not built; run tools/build_aegis_ui.ps1</p>` at `/aegis`. Keep `/aegis/api/*` routes registered before the mount.**
- [ ] **Step 6: `.gitignore` add `app/products/aegis/ui/node_modules/` and `app/products/aegis/ui/dist/`; `pyproject.toml` package-data for `products.aegis` add `"ui/dist/**"`.**
- [ ] **Step 7: Run `npm run build`, `npm test`, `pytest -q`; open `http://127.0.0.1:8102/aegis/` after restarting the worker and confirm the full layout renders with empty states.**
- [ ] **Step 8: Commit (source only; no `dist`).**

---

### Task 3: Side-owned strategy contracts

**Files:**
- Modify: `app/products/aegis/strategy.py`
- Modify: `tests/test_aegis_strategy.py`

**Interfaces:**
- Produces: `StrategySide(direction, enabled, indicators: list[IndicatorSpec], entry: RuleSpec, exit: RuleSpec, optimization: list[OptimizationParameter])`; `MarketCrossover(id, label, enabled=True, start: str, end: str, mode=ANALYZE)`; `StrategySpec(id, name, version, description, long_side, short_side, temporal, execution)` (no top-level `indicators`/`optimization`); `default_strategy()`; `StrategySide.indicator(id) -> IndicatorSpec`; `apply_parameters(side: StrategySide, values: dict[str, float]) -> StrategySide` where keys are side-relative paths `indicators.<id>.length`.

- [ ] **Step 1: Rewrite `tests/test_aegis_strategy.py` tests to the new shape and add:**

```python
def test_each_side_owns_its_indicators_and_ranges():
    s = default_strategy()
    assert [i.length for i in s.long_side.indicators] == [9, 30]
    assert [i.length for i in s.short_side.indicators] == [9, 30]
    assert s.long_side.optimization[0].path == "indicators.ema.length"
    assert s.short_side.optimization is not s.long_side.optimization

def test_sides_can_diverge_without_shared_state():
    s = default_strategy()
    short = apply_parameters(s.short_side, {"indicators.ema.length": 6, "indicators.sma.length": 52})
    assert short.indicator("ema").length == 6 and short.indicator("sma").length == 52
    assert s.long_side.indicator("ema").length == 9

def test_rule_referencing_unknown_indicator_is_rejected():
    with pytest.raises(ValidationError, match="unknown indicator"):
        StrategySide(direction=Direction.LONG, indicators=[], entry=RuleSpec(left="ema", operator="crosses_above", right="sma"), exit=RuleSpec(left="ema", operator="crosses_below", right="sma"))

def test_market_crossovers_are_clock_defined_and_enabled():
    cx = {c.id: c for c in default_strategy().temporal.market_crossovers}
    assert cx["cash_open"].start == "09:25" and cx["cash_open"].end == "09:45" and cx["cash_open"].enabled
    assert cx["london_new_york"].start == "09:30" and cx["london_new_york"].end == "11:30"
```

- [ ] **Step 2: Run `pytest tests/test_aegis_strategy.py -v`; expect failures on missing fields/functions.**
- [ ] **Step 3: Implement in `strategy.py`:** move `indicators` and `optimization` into `StrategySide`; `model_validator` rejecting rules whose `left`/`right` are not owned indicator ids; `MarketCrossover.start/end` (HH:MM) with `enabled=True` default; `apply_parameters` (copy, set `length` as `int`, re-validate); `default_strategy()` per spec §5.1 (ids `ema`, `sma` on each side; EMA 5→20 step 1, SMA 20→100 step 5 per side; crossovers `cash_open` 09:25–09:45, `london_new_york` 09:30–11:30).
- [ ] **Step 4: Run `pytest tests/test_aegis_strategy.py -v`; expect PASS. `tests/test_aegis_backtest.py` will fail until Task 4 — note it, do not fix here.**
- [ ] **Step 5: Regenerate `ui/src/contracts.ts` with `python tools/aegis_contracts.py` and run `pytest tests/test_aegis_contracts.py`.**
- [ ] **Step 6: Commit.**

---

### Task 4: Indicators module and engine on side-owned parameters

**Files:**
- Create: `app/products/aegis/indicators.py`, `tests/test_aegis_indicators.py`
- Modify: `app/products/aegis/backtest.py`, `tests/test_aegis_backtest.py`

**Interfaces:**
- Produces: `indicators.compute(spec: IndicatorSpec, frame: pd.DataFrame) -> pd.Series` (NaN until warm; `kind` in `{"EMA","SMA"}` else `ValueError("unknown indicator kind")`); `indicators.IndicatorCache` with `get(data_key: str, spec: IndicatorSpec, frame) -> pd.Series` and `hits: int`; `backtest.run_backtest(request, cache: IndicatorCache | None = None) -> dict` whose per-side result gains `series: dict[str, list[float | None]]` (one entry per bar, keyed by the side's indicator ids) and `enabled: bool`.

- [ ] **Step 1: Write `tests/test_aegis_indicators.py`:**

```python
def test_sma_and_ema_match_pandas_definitions(): ...  # SMA(3) of [1,2,3,4] -> [nan,nan,2,3]; EMA uses ewm(span, adjust=False, min_periods=length)
def test_unknown_kind_raises(): ...
def test_cache_returns_same_object_for_same_key_and_spec(): ...  # second get -> hits == 1
```

- [ ] **Step 2: Update `tests/test_aegis_backtest.py` to the side-owned contract and add:**

```python
def test_sides_simulate_from_their_own_indicator_lengths():
    s = default_strategy(); s.short_side = apply_parameters(s.short_side, {"indicators.ema.length": 6, "indicators.sma.length": 20})
    r = run_backtest(BacktestRequest(strategy=s, bars=bars()))
    assert r["long"]["series"].keys() == {"ema", "sma"} and len(r["long"]["series"]["ema"]) == r["bars"]
    assert r["long"]["series"]["ema"] != r["short"]["series"]["ema"]
```

- [ ] **Step 3: Run both files; expect FAIL (`indicators` missing; `strategy.indicators` gone).**
- [ ] **Step 4: Implement `indicators.py`; in `backtest.py` replace `_indicator_lengths`/`_crosses` with `_side_frame(frame, side, cache, data_key) -> DataFrame` that computes each owned indicator and the side's `entry_signal`/`exit_signal` columns from `RuleSpec` (`crosses_above`: left > right and previous left ≤ previous right; `crosses_below` symmetric; other operators → `ValueError`). `_simulate_side` takes the side object. Add `series` and `enabled` to the side result.**
- [ ] **Step 5: Run `pytest tests/test_aegis_indicators.py tests/test_aegis_backtest.py tests/test_aegis_strategy.py -v`; expect PASS. Run `pytest -q`; expect green.**
- [ ] **Step 6: Commit.**

---

### Task 5: Temporal rules, precedence and crossover tags

**Files:**
- Create: `app/products/aegis/temporal.py`, `tests/test_aegis_temporal.py`
- Modify: `app/products/aegis/backtest.py`

**Interfaces:**
- Produces: `temporal.validate(temporal: TemporalContext) -> None` (raises `ValueError("unsupported window mode: MODIFY_RISK")`); `temporal.tags(ts: pd.Timestamp, temporal, events, symbol) -> tuple[str, ...]` returning sorted `CLOCK:<id>`, `CROSSOVER:<id>`, `EVENT:<type>`; `temporal.entry_permitted(ts, temporal) -> bool` (BLOCK wins; if any ALLOW clock windows exist, must be inside one); `backtest._simulate_side` uses `entry_permitted` for entries only.

- [ ] **Step 1: Write `tests/test_aegis_temporal.py`:**

```python
def test_block_suppresses_entry_but_not_exit(): ...        # entry signal inside BLOCK 09:30-10:00 -> no trade opens; an open position exits inside BLOCK
def test_allow_requires_inside_allow_and_outside_block(): ...  # ALLOW 10:00-15:00 + BLOCK 12:00-12:30: 11:00 permitted, 12:15 not, 09:40 not
def test_analyze_never_changes_execution(): ...          # trade counts equal with and without an ANALYZE window
def test_modify_risk_is_rejected_explicitly(): ...        # ValueError match "unsupported window mode"
def test_crossover_tags_are_clock_derived(): ...          # 09:30 ET bar -> {"CROSSOVER:cash_open","CROSSOVER:london_new_york"}; 14:00 -> none
def test_rumor_news_window_without_events_tags_nothing(): ...
```

- [ ] **Step 2: Run; expect FAIL (`temporal` missing).**
- [ ] **Step 3: Update `test_opening_window_is_preserved_in_temporal_breakdown` to accept `CROSSOVER:` keys. Implement `temporal.py` (move `_clock_tags`/`_event_tags` logic here, add crossovers and `entry_permitted`); call `validate` at the top of `run_backtest`; apply `entry_permitted` where pending ENTER is set.**
- [ ] **Step 4: Run `pytest tests/test_aegis_temporal.py tests/test_aegis_backtest.py -v`; expect PASS.**
- [ ] **Step 5: Commit.**

---

### Task 6: Exposure metric, markers, canonical payload and `result_hash`

**Files:**
- Create: `app/products/aegis/results.py`, `tests/test_aegis_results.py`
- Modify: `app/products/aegis/backtest.py`

**Interfaces:**
- Produces: `backtest` side metrics gain `exposure: float` (bars with open position / bars); `backtest.markers(result) -> list[dict]` items `{time: int(ms), price: float, side: "LONG"|"SHORT", kind: "entry"|"exit"}`; `results.canonical_payload(result: dict, strategy: StrategySpec, data_identity: dict) -> dict` (keys: `strategy`, `data`, `long`, `short`, `combined`, `temporal`, `markers`); `results.result_hash(payload: dict) -> str` (sha256 hex of `json.dumps(payload, sort_keys=True, separators=(",",":"), allow_nan=False)` after NaN→None).

- [ ] **Step 1: Write `tests/test_aegis_results.py`:**

```python
def test_identical_requests_yield_identical_hash(): ...   # two run_backtest calls -> equal canonical payloads and hashes
def test_hash_ignores_envelope_fields(): ...              # payload unchanged when run_id/created_at/elapsed_ms differ in the envelope
def test_hash_changes_when_a_parameter_changes(): ...     # short EMA 9 -> 6 changes hash
def test_exposure_is_fraction_of_bars_in_position(): ...  # 0 <= exposure <= 1; disabled side -> 0.0
def test_markers_have_entry_and_exit_per_trade(): ...     # len(markers) == 2 * trade_count(combined)
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement `results.py` and the `exposure`/`markers` additions.**
- [ ] **Step 4: Run; expect PASS. Run `pytest -q`; green.**
- [ ] **Step 5: Commit.**

---

### Task 7: Data layer — discovery, pinned sources, resampling, cache

**Files:**
- Create: `app/products/aegis/data.py`, `tests/test_aegis_data.py`

**Interfaces:**
- Produces: `ArchiveSource(symbol, source="raw_archive", vintage, relative_path, sha256, first_bar, last_bar, row_count, vendor_sources: list[str], coverage_pct: float | None, research_eligible=False)`; `PinnedSource(ArchiveSource + timeframe, start: date, end: date, resampling_policy="rth-anchored-v1", data_hash: str)`; `discover_archives(root: Path = DATA_ROOT) -> list[ArchiveSource]` (newest vintage dir wins; skips symbols whose parquet is missing); `class ArchiveStore(root)` with `symbols() -> list[ArchiveSource]`, `bars(symbol, timeframe, start, end) -> tuple[pd.DataFrame, PinnedSource]`, `load_pinned(pinned: PinnedSource) -> pd.DataFrame` (raises `SourceUnavailable` on missing file or sha mismatch), `warm(symbols: list[str]) -> None`; exceptions `BarsTooLarge(count, cap)`, `SourceUnavailable(reason)`; `to_records(frame) -> list[dict]` with `time` ms and `open, high, low, close, volume`; `TIMEFRAMES = ("1m","15m","30m","1h","1D")`; `BAR_CAP = 50_000`.

- [ ] **Step 1: Write `tests/test_aegis_data.py` using a `tmp_path` vintage dir with a tiny synthetic 1-minute parquet (two trading days, 09:30–15:59, plus a DST-ambiguous day) and a `report.json`:**

```python
def test_discovery_prefers_newest_vintage_and_reads_coverage(): ...
def test_discovery_skips_symbols_with_missing_parquet(): ...
def test_1m_passthrough_and_hourly_bars_anchor_at_0930(): ...   # first 1h bar time == 09:30 ET, last == 15:30 stub
def test_daily_bars_aggregate_the_session(): ...                # open=first, high=max, low=min, close=last, volume=sum
def test_bars_over_cap_returns_422_with_hint(): ...             # ArchiveStore.bars raises BarsTooLarge; api maps to 422 (Task 8)
def test_pinned_source_has_file_sha_and_data_hash(): ...
def test_load_pinned_detects_changed_file(): ...                # rewrite parquet -> SourceUnavailable
def test_cache_computes_each_timeframe_once(): ...              # second call does not re-resample (counter)
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement `data.py` (pyarrow read; localize `America/New_York`, `ambiguous="NaT"` drop; resample with `origin` at 09:30 for intraday; `data_hash` = sha256 of the resampled frame's `to_json(orient="split", date_format="epoch")`).**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit.**

---

### Task 8: API — data, indicators, backtest, runs (with `RunRepository`)

**Files:**
- Create: `app/products/aegis/runs.py`, `app/products/aegis/api.py`, `tests/test_aegis_runs.py`, `tests/test_aegis_api.py`
- Modify: `app/products/aegis/server.py`

**Interfaces:**
- Produces: `runs.RunRepository` (Protocol: `save_run(envelope: dict) -> str`, `get_run(run_id) -> dict`, `list_runs() -> list[dict]`, `save_optimization`, `get_optimization`, `list_optimizations`); `runs.JsonRunRepository(root: Path = ROOT/"data/aegis")`; `api.router` with routes of spec §7 (`/aegis/api/data/symbols`, `/aegis/api/data/bars`, `/aegis/api/indicators`, `/aegis/api/backtest`, `/aegis/api/runs`, `/aegis/api/runs/{run_id}`); `api.get_store() -> ArchiveStore` and `api.get_repository() -> RunRepository` as FastAPI dependencies (overridable in tests); `BacktestRequest` gains `data: DataReference | None` where `DataReference(symbol, timeframe, start: date, end: date)`; `bars: list[dict] = Field(default_factory=list, max_length=200_000)`; `events` `max_length=10_000`; validator: exactly one of `data`/`bars`. Backtest response = `{run_id, created_at, elapsed_ms, result_hash, data: PinnedSource, strategy, result: <canonical payload>, series: {long, short}, markers}`.

- [ ] **Step 1: Write `tests/test_aegis_runs.py`:** `test_json_repository_round_trips_run_and_lists_newest_first`, `test_unknown_run_raises_key_error`.
- [ ] **Step 2: Write `tests/test_aegis_api.py`** with `TestClient(server.app)` and dependency overrides for a `tmp_path` store (synthetic archive from Task 7's helper) and repository: `test_symbols_lists_archives_with_provenance`, `test_bars_returns_epoch_ms_and_cap_422`, `test_indicators_endpoint_returns_series_per_indicator`, `test_backtest_by_data_reference_persists_and_returns_hash`, `test_backtest_bars_over_bound_is_422`, `test_runs_list_and_get`, `test_status_contract_unchanged`.
- [ ] **Step 3: Run; expect FAIL.**
- [ ] **Step 4: Implement `runs.py`, `api.py`; include the router in `server.py`; map `BarsTooLarge` → 422 `{"detail": "range too large: N bars over cap 50000; narrow the range"}`, `SourceUnavailable` → 409 `{"detail": "source unavailable: ..."}`, `KeyError` → 404.**
- [ ] **Step 5: Run `pytest tests/test_aegis_api.py tests/test_aegis_runs.py tests/test_architecture.py -v`; expect PASS. `pytest -q` green.**
- [ ] **Step 6: Commit.**

---

### Task 9: Chart adapter and real candles + indicators in the UI (Phases 3–4)

**Files:**
- Create: `ui/src/chart/adapter.ts`, `ui/src/chart/vela.ts` or `ui/src/chart/lightweight.ts` (per Task 1), `ui/src/chart/adapter.test.ts`
- Modify: `ChartPanel.tsx`, `TopBar.tsx`, `api/client.ts`, `state/workspace.tsx`

**Interfaces:**
- Produces: `interface ChartAdapter { mount(el: HTMLElement): void; setBars(bars: Bar[], timeframe: Timeframe): void; setOverlays(series: Overlay[]): void; setMarkers(markers: Marker[]): void; onCrosshair(cb: (p: CrosshairPoint | null) => void): void; resize(): void; destroy(): void }` with `Bar {time, open, high, low, close, volume}`, `Overlay {id, color, points: {time, value}[]}`, `Marker {time, price, side, kind}`; `createChartAdapter(): ChartAdapter` picks the backend chosen in Task 1.

- [ ] **Step 1: Write `adapter.test.ts`** against a `MockAdapter`: `ChartPanel calls setBars then setOverlays when selection changes`, `overlay points drop null values`.
- [ ] **Step 2: Implement the adapter and the real backend; wire TopBar selection → `GET data/bars` + `POST indicators` → chart; show the permanent "RAW ARCHIVE · not research-eligible" badge and vintage in the chart header; show the 422 range hint inline when the cap is hit.**
- [ ] **Step 3: `npm test`; build; load QQQ 1h for 2023-01-01→2024-12-31 and 1m for one week in the browser; confirm candles and both overlays.**
- [ ] **Step 4: Commit.**

---

### Task 10: Run Backtest, results, persistence in the UI (Phases 5–7)

**Files:**
- Modify: `StrategyPanel.tsx`, `SideCard.tsx`, `TemporalPanel.tsx`, `ExecutionPanel.tsx`, `ResultsTabs.tsx`, `SummaryTab.tsx`, `TradesTab.tsx`, `EquityTab.tsx`, `StatusStrip.tsx`, `ChartPanel.tsx`, `api/client.ts`, `state/workspace.tsx`
- Create: `ui/src/components/RunsDrawer.tsx`, `tests/test_aegis_api.py` additions

**Interfaces:**
- Consumes: Task 8 backtest response; `GET runs`, `GET runs/{id}`.
- Produces: Summary tab shows long / short / combined metric columns (net P&L, net return, CAGR, max DD, MAR, win rate, expectancy, profit factor, trades, exposure) and the temporal breakdown table; Trades tab lists trades with side, times, prices, qty, net P&L, tags; Equity tab draws combined and per-side curves (SVG, no chart library); StatusStrip shows CAGR, Net P&L, Max DD, MAR, Expectancy, Exposure and `result_hash` short form; markers appear on the chart; RunsDrawer lists persisted runs and reloads one (restoring selection, strategy, results); a `source_unavailable` reload shows that state.

- [ ] **Step 1: Add API tests:** `test_reload_with_changed_file_hash_is_source_unavailable` (`GET runs/{id}` after rewriting the parquet → `{"state": "source_unavailable", ...}` with the envelope still returned), `test_backtest_hash_stable_across_two_requests`.
- [ ] **Step 2: Run; FAIL; implement the server side (`GET runs/{id}` validates the pinned sha via `load_pinned`).**
- [ ] **Step 3: Wire the UI: strategy panel edits the spec (per-side lengths with the link toggle, rule display, enable toggles, clock window modes incl. MODIFY_RISK shown disabled "not supported", crossovers listed as ANALYZE, event windows "feed unavailable", execution fields); Run Backtest posts `{strategy, data, settings}`; populate tabs/strip/markers; RunsDrawer.**
- [ ] **Step 4: `npm test`, `pytest -q`; browser: run QQQ 1h 2023–2024, inspect long/short/combined, trades, equity, reload the run.**
- [ ] **Step 5: Commit.**

---

### Task 11: Optimizer module — per-side grids, progressive results, cancel, cache reuse

**Files:**
- Create: `app/products/aegis/optimize.py`, `tests/test_aegis_optimize.py`

**Interfaces:**
- Produces: `expand_grid(side: StrategySide) -> GridPlan` with `GridPlan(cells: list[dict[str, float]], skipped: list[dict], fast_values: list[float], slow_values: list[float])` (skip when the entry rule's left indicator length ≥ right indicator length; cells over 400 → `ValueError("grid too large")`); `estimate_seconds(cells: int, bars: int, ms_per_bar: float = 0.14) -> float`; `class OptimizerRunner(repository: RunRepository, max_workers=1)` with `start(request: OptimizeRequest, frame: pd.DataFrame, pinned: PinnedSource) -> str` (raises `JobBusy` if a job is running), `status(job_id) -> dict` (`status`, `progress {done,total}`, `elapsed_ms`, `cells` done so far each `{params, metrics}`, `matrices {metric: {long|short: [[...]]}}` built from completed cells, `estimated_seconds`, `skipped`), `cancel(job_id) -> bool`, `mark_lost_on_startup()`; `OptimizeRequest(strategy, side: Literal["long","short"], data: DataReference, settings, objective: Literal["net_pnl","mar","max_drawdown","trade_count"])`; `heatmap(cells, fast_values, slow_values, metric) -> list[list[float | None]]` (rows fast ascending, columns slow ascending, `None` skipped/pending).

- [ ] **Step 1: Write `tests/test_aegis_optimize.py`:**

```python
def test_grid_expands_from_side_ranges_and_skips_fast_ge_slow(): ...   # default long: 16*17=272 total, skipped count == cells with ema>=sma
def test_grid_over_400_cells_is_rejected(): ...
def test_estimate_uses_cells_bars_and_ms_per_bar(): ...
def test_job_runs_to_completion_with_progress_and_partial_cells(): ...   # small grid, synthetic bars; status mid-run has 0 < done < total and len(cells)==done
def test_cancel_stops_between_cells(): ...
def test_second_job_while_running_is_409_and_first_continues(): ...     # JobBusy raised; first job finishes with full progress
def test_indicator_cache_is_reused_across_cells(): ...                   # cache.hits > 0 after a 2x2 grid
def test_heatmap_matrix_shape_and_none_for_skipped(): ...
def test_completed_job_is_persisted_via_repository(): ...
```

- [ ] **Step 2: Run; FAIL. Implement `optimize.py` (ThreadPoolExecutor(1); each cell: `apply_parameters` on the chosen side, other side disabled, `run_backtest(..., cache=shared)`; cooperative cancel flag checked between cells; results appended under a lock; persisted on done/cancelled).**
- [ ] **Step 3: Run; PASS. `pytest -q` green.**
- [ ] **Step 4: Commit.**

---

### Task 12: Optimizer API and Optimization tab (Phase 8)

**Files:**
- Modify: `app/products/aegis/api.py`, `tests/test_aegis_api.py`, `OptimizationTab.tsx`, `Heatmap.tsx`, `OptimizationRanges.tsx`, `TopBar.tsx`, `api/client.ts`, `state/workspace.tsx`, `ui/src/components/heatmap.test.ts`

**Interfaces:**
- Produces: `POST /aegis/api/optimize` → 202 `{job_id, total_cells, skipped_cells, estimated_seconds}`; 409 `{"detail": "an optimization is already running"}`; `GET /aegis/api/optimize/{job_id}` → `OptimizerRunner.status`; `POST /aegis/api/optimize/{job_id}/cancel` → `{cancelled: bool}`; `GET /aegis/api/optimize` → persisted list. UI: Optimize button opens side choice (long/short) with the pre-run summary (valid cells, skipped, estimate); progress bar; heatmap and table fill progressively (1 s polling); Cancel; metric selector; clicking a cell selects that configuration for its side; "Apply selected long + short" updates the strategy and reruns Combined.

- [ ] **Step 1: API tests:** `test_optimize_returns_202_with_plan`, `test_optimize_status_progresses_and_is_responsive_while_running` (poll status while a job runs; each call returns within 500 ms), `test_optimize_cancel`, `test_second_job_while_running_is_409_and_first_continues` (API level).
- [ ] **Step 2: Run; FAIL; implement routes with `OptimizerRunner` as a module-level singleton created per app (dependency `get_runner()`), `mark_lost_on_startup()` in lifespan.**
- [ ] **Step 3: `heatmap.test.ts`:** `matrix maps to cells with fast rows and slow columns`, `null cells render as skipped`.
- [ ] **Step 4: Wire the UI per Interfaces; `npm test`; browser: run a long-side optimization on QQQ 1D full range (~272 cells, ~2 min), watch cells fill, cancel one, rerun to completion, select a cell, apply, rerun combined.**
- [ ] **Step 5: Commit.**

---

### Task 13: Supervisor generalization and packaging alignment (Phase 9)

**Files:**
- Create: `tools/ensure_product_worker.py`, `tests/test_product_worker_supervisor.py`
- Modify: `tools/run_core_supervisor.py`, `tests/test_triad_worker_supervisor.py` (point at the new module), `app/products/aegis/resources/product.json`
- Delete: `tools/ensure_triad_worker.py` (after tests moved)

**Interfaces:**
- Produces: `ensure_product_worker.py --product {triad,aegis}` with `PORTS = {"triad": 8101, "aegis": 8102}`, `healthy(port, product)`, `occupied(port, timeout=10)`, `ensure(product, store=None)` (lease `f"{product}-product-development"`), log `logs/{product}-supervisor.log`; `run_core_supervisor.py` runs it for `triad` then `aegis`, each with `timeout=100`.

- [ ] **Step 1: Move and parametrize the existing supervisor tests; add `test_aegis_uses_port_8102_and_its_own_lease_and_log`, `test_supervisor_runs_both_products_and_reports_first_failure`.**
- [ ] **Step 2: Run; FAIL; implement; delete the old module; update `docs/MISSION1_QUIET_GREEN_BASELINE.md` reference line.**
- [ ] **Step 3: Align `resources/product.json` to `config/aegis/product.json`.**
- [ ] **Step 4: `pytest -q`; commit.**

---

### Task 14: Browser acceptance flow and evidence (Phase 10, part 1)

**Files:**
- Create: `tests/products/aegis/browser_workstation.py`, `docs/MISSION3_AEGIS_WORKSTATION_SLICE.md`

**Interfaces:**
- Consumes: the running worker at `http://127.0.0.1:8102/aegis/`.
- Produces: a Playwright script walking the 22 definition-of-done items, writing `logs/aegis-acceptance-<stamp>.json` with each item PASS/FAIL, timings (backtest ms, indicator ms, optimizer cell ms), and the two `result_hash` values for item 22; the mission note recording decisions, measurements and evidence.

- [ ] **Step 1: Write the script (Chromium via `playwright`, same pattern as `tests/products/triad/browser_product.py`).**
- [ ] **Step 2: Build the UI, restart the Aegis worker (detached), run the script; fix anything it exposes under the normal TDD loop; rerun until all 22 PASS.**
- [ ] **Step 3: Write the mission note; commit.**

---

### Task 15: Milestone QA (Phase 10, part 2)

- [ ] **Step 1: Run `pytest -q`, `ruff check` on all Aegis and tools files, `npm test`, `npm run build`; confirm `tests/test_architecture.py` green; record outputs in the mission note.**
- [ ] **Step 2: Dispatch one independent QA agent at the exact commit with the brief: re-run the suite and the browser flow, probe `result_hash` identity, pinned-source behaviour, temporal precedence, 409/422/404 paths, CSP, attribution, and the governance contract; report PASS/FAIL with evidence.**
- [ ] **Step 3: Record the QA verdict in the mission note; push `main`.**
