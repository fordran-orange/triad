# Mission 10 "No limit" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ten years of QQQ 1-minute bars (947,519) charted, backtested, saved, opened in the Library
and compared on this laptop, with slim saved runs and a "Save only what I keep" option.

**Architecture:** The run envelope keeps today's hash but stores a slim copy. Archive bars reach
the engine as a prepared frame instead of dict rows, the hash is fed in C-encoded chunks, and the
pool receives column arrays sized to free memory. The worker chooses display candles (at most
20,000) and samples indicators to them; the page swaps data in place as the operator zooms. A
worker-side preference and an in-memory list of unsaved runs carry the save setting.

**Tech Stack:** Python 3.12 (`.venv-aegis`, pandas, numpy, numba kernel), FastAPI, pytest (scope
`aegis`), React/Vite/TypeScript, Vela 0.8.3, vitest, Playwright acceptance.

**Spec:** `docs/superpowers/specs/2026-10-20-aegis-no-limit-design.md`

## Global Constraints

- The result hash keeps its definition: SHA-256 of `canonical_json(canonical_payload(...))`, the
  bytes of `json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)`.
  `RECORDED_IDENTICAL_HASH` and the recorded walk-forward hashes must still match.
- Stored side equity: at most `EQUITY_POINTS = 2_000` points, first and last kept.
- `BAR_CAP = 2_000_000` (a memory guard); `BacktestRequest.bars` `max_length = 2_000_000`.
- `MAX_DISPLAY_BARS = 20_000` candles per view; display timeframes are the standard ones
  (`15m`, `30m`, `1h`, `1D`), the native timeframe when the window fits.
- Memory target: at most 1,000 bytes per bar above the selected frame on the backtest path,
  measured out of process with the OS peak working set; ten years of 1m must complete.
- `save_runs` is `"every"` (default) or `"kept"`; at most 20 unsaved runs held in memory.
- Existing saved runs are not rewritten. No new package in any environment (`ctypes` for memory).
- Product code only (`app/products/aegis/`, its tests and docs); Core, the platform host and
  Triad are not touched. Lint only through the scope script. Red only for losing money.

## Review Focus

1. **A run saved before this mission** (per-bar series, full side equity): it opens, draws its
   equity, compares and loads exactly as before. Task 1 `test_a_format_one_run_still_reads`.
2. **A run whose side never traded or is disabled** (empty side equity): the slim run stores `[]`
   with `equity_points` 0 and the Equity view draws without that line. Task 1
   `test_slim_run_of_a_disabled_side`.
3. **A window whose native bars fit exactly at 20,000, or a selection already at 1D**: no
   aggregation, `display_timeframe` equals the native one. Task 4
   `test_display_timeframe_at_the_boundary`.
4. **A marker exactly on a display candle's open, before the first candle, or after the last**:
   placed on that candle, the first, or the last. Task 5 `placeMarkers` vitest.
5. **A worker restart while "kept" mode holds unsaved runs**: they are gone; the drawer and Load
   say so, and Keep on a forgotten id answers 404 rather than failing. Task 6
   `test_keep_of_a_forgotten_run_is_404`.

---

### Task 1: Slim saved runs and a streamed hash

**Files:**
- Modify: `app/products/aegis/results.py` (`envelope`, `result_hash`, `_clean`), `app/products/aegis/api.py` (`_envelope` returns the slim run)
- Modify: `app/products/aegis/ui/src/components/EquityTab.tsx`, `app/products/aegis/ui/src/results.ts` (`RunEnvelope.series` optional, `stored?`)
- Test: `tests/test_aegis_results.py`, `tests/test_aegis_api.py`

**Interfaces:**
- Produces: `results.EQUITY_POINTS = 2_000`; `results.slim_equity(points: list[dict], limit: int = EQUITY_POINTS) -> list[dict]`; `results.stream_hash(payload: dict) -> str` (equal to `result_hash`); envelope field `stored = {"format": 2, "equity_points": {"long": int, "short": int}}`; no top-level `series`, no `result.<side>.series`, no `result.markers`.

- [ ] **Step 1: Write the failing tests** in `tests/test_aegis_results.py`:
  - `test_stream_hash_equals_the_canonical_hash` — on a real run's `canonical_payload` (wave bars, both sides), on a nested dict with unicode keys and a list of 25,000 dicts: `stream_hash(p) == result_hash(p)`.
  - `test_slim_equity_keeps_endpoints` — 10,000 points → 2,000 points, `out[0] is points[0]`, `out[-1] is points[-1]`; 1,500 points → unchanged; `[]` → `[]`.
  - `test_the_saved_run_is_slim_and_keeps_its_hash` — `env = envelope(...)`; `env["result_hash"] == result_hash(canonical_payload(...))`; `"series" not in env`; `"series" not in env["result"]["long"]`; `"markers" not in env["result"]`; `len(env["result"]["long"]["equity"]) <= 2000`; `env["stored"] == {"format": 2, "equity_points": {"long": n_long, "short": n_short}}`; trades, metrics, temporal and combined equity equal the engine's.
  - `test_clean_does_not_copy_a_clean_structure` — `_clean(x) is x` for a structure with no NaN; NaN still becomes `None` where present.
  - `test_slim_run_of_a_disabled_side` (Review Focus 2).
  In `tests/test_aegis_api.py`: update the two asserts that read `series` from the POST response (lines ~123, ~129) to assert its absence and `stored.format == 2`; add `test_a_format_one_run_still_reads` (Review Focus 1): write a pre-mission envelope (with `series` and full side equity) through the repository, then GET `/runs/{id}`, GET `/library/compare` against a new run, and the Library's backtest entry all answer.
- [ ] **Step 2: Run** `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_results.py tests/test_aegis_api.py` — expected FAIL (no `stream_hash`, `series` present).
- [ ] **Step 3: Implement.**
  - `stream_hash`: walk the payload. Dicts are written with sorted keys as `{"k":v,...}`. Lists of more than 1,000 items are written in slices: `json.dumps(slice, ...)` with the same options, its brackets stripped, slices joined with `,`. Scalars and small values go through `json.dumps`. Every piece feeds one `hashlib.sha256`, so the bytes equal `canonical_json(payload)`.
  - `_clean` returns the same object when nothing in it changes (copy on write).
  - `envelope` hashes with `stream_hash`, then builds the stored run per the Interfaces block.
  - `EquityView` defaults missing curves to `[]`. Its caption reads "per bar" for format 1, and "per bar, resampled to N of M points" when `stored.equity_points` exceeds the stored count.
- [ ] **Step 4: Run the same tests and `npm --prefix app/products/aegis/ui test`** — expected PASS. Then run the whole Aegis scope: every recorded hash test (`test_aegis_kernel.py`, `test_aegis_walkforward.py`, `test_aegis_experiments.py`, `test_aegis_compare.py`) passes unchanged.
- [ ] **Step 5: Commit** "Aegis runs: slim saved runs with the hash computed before slimming".

### Task 2: Ten years in one process

**Files:**
- Modify: `app/products/aegis/backtest.py` (`prepare_archive_frame`), `app/products/aegis/data.py` (one minute copy, vectorized selection), `app/products/aegis/api.py` (`/backtest`, materialize and studies paths use frames), `app/products/aegis/optimize.py`, `app/products/aegis/walkforward.py`, `app/products/aegis/experiments.py`, `app/products/aegis/studies.py`/`study_rules.py` (frames instead of `engine_rows`), `app/products/aegis/pool.py` (column arrays; `free_memory_bytes()`; workers sized to memory)
- Create: `tests/products/aegis/memory_probe.py` (the out-of-process probe; `ctypes` `K32GetProcessMemoryInfo`)
- Test: `tests/test_aegis_backtest.py`, `tests/test_aegis_data.py`, `tests/test_aegis_pool.py` (or the existing pool tests' module)

**Interfaces:**
- Consumes: Task 1's slim envelope.
- Produces:
  - `backtest.prepare_archive_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame` — identical to `_prepare_frame(engine_rows(frame, symbol))`;
  - `pool.Pool.start(frame: pd.DataFrame, symbol, spec, settings, keep_rows=True)` taking the prepared frame's columns;
  - `pool.free_memory_bytes() -> int`;
  - `pool.workers_for(bars: int, wanted: int, free: int) -> int`, with `POOL_BYTES_PER_BAR` measured;
  - `ArchiveStore` serving `1m` from the minute frame itself.

- [ ] **Step 1: Write the failing tests:**
  - `test_archive_frame_equals_the_rows_path` — on a store fixture and on wave bars: `prepare_archive_frame(f, "QQQ").equals(_prepare_frame(engine_rows(f, "QQQ")))`, the same `_data_key`, and `run_prepared` on both gives the same `result_hash`.
  - `test_the_store_holds_one_minute_copy` — `store._frame(archive, "1m") is store._frames[minutes_key]`.
  - `test_selection_is_unchanged` — the vectorized date mask selects the same rows as the date-object mask on a DST-spanning fixture.
  - `test_workers_fit_free_memory` — `workers_for(947_519, 10, free)` is fewer than 10 when `free` is small, at least 1 when one fits, and raises `ValueError` naming the shortfall when none fits.
  - `test_pool_from_a_frame_equals_the_rows_pool` — the cells of a small grid are equal both ways.
- [ ] **Step 2: Run them** — expected FAIL.
- [ ] **Step 3: Implement.**
  - Every archive path calls `run_prepared(request, prepare_archive_frame(frame, symbol), key, cache)` or passes the frame on, instead of building `engine_rows`. A walk-forward unit's slice is a frame slice, not a row-list slice.
  - The pool initializer receives the frame's columns as numpy arrays.
  - A pooled job's and an experiment's worker count is `min(default, workers_for(...))`, and the plan reports it.
- [ ] **Step 4: Run** the whole Aegis scope — expected PASS, with every hash test unchanged. Then measure with `tests/products/aegis/memory_probe.py` on 161,754 and 947,519 1m bars: record bytes per bar above the frame, the peak, the seconds and the stored size. Expected: at most 1,000 B/bar, and the ten-year run completes. If the result is between 1,000 and 1,500 B/bar and the run completes, record a ruling; above that, find the next largest holder before committing.
- [ ] **Step 5: Commit** "Aegis: ten years of 1-minute bars in one process".

### Task 3: The bar cap becomes a memory guard

**Files:** `app/products/aegis/data.py` (`BAR_CAP`), `app/products/aegis/backtest.py` (`BacktestRequest.bars` `max_length`); tests `tests/test_aegis_data.py`, `tests/test_aegis_api.py`.

- [ ] **Step 1: Failing tests:**
  - `assert BAR_CAP == 2_000_000` (test_aegis_data.py, the existing pin);
  - the API's "at most 200000" assertion moves to 2,000,000;
  - `test_ten_years_of_one_minute_bars_select` on the real archive: when it is present, `store.bars("QQQ", "1m", "2016-09-19", "2026-09-18")` returns 947,519 rows; skip without the archive.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** the two constants (comment: a memory guard, about twenty years of 1m). **Step 4: Run** — PASS. **Step 5: Commit** "Aegis: the bar cap becomes a 2,000,000-bar memory guard".

### Task 4: Display candles and indicators on the worker

**Files:**
- Modify: `app/products/aegis/data.py` (`display_frame`), `app/products/aegis/api.py` (`GET /data/bars`, `POST /data/indicators`), `app/products/aegis/indicators.py` or a new `app/products/aegis/display.py` (`sample_at_buckets`)
- Test: `tests/test_aegis_display.py` (owned `aegis`), `tests/test_aegis_api.py`

**Interfaces:**
- Produces:
  - `display.MAX_DISPLAY_BARS = 20_000`;
  - `display.choose_timeframe(native: str, counts: dict[str, int], max_bars: int) -> str` — the finest standard timeframe at or above `native` whose count over the window fits;
  - `display.sample_at_buckets(native_times_ms: np.ndarray, values: Sequence[float | None], bucket_times_ms: np.ndarray, window_end_ms: int) -> list[float | None]` — the value at each bucket's last native bar, `None` for an empty bucket;
  - `GET /data/bars?symbol&timeframe&start&end[&max_bars&from_ms&to_ms]` answers `{bars, count, shown, display_timeframe, window: {from_ms, to_ms}, data, ...}`, with `count` the native bars of the whole selection;
  - `POST /data/indicators` body gains optional `max_bars`, `from_ms`, `to_ms` and answers `times`/`series` index-aligned to the display bars, plus `display_timeframe`.
  - Responses are built from columns, not `to_records`.

- [ ] **Step 1: Failing tests** (`tests/test_aegis_display.py`, `pytestmark = pytest.mark.aegis`):
  - `test_display_timeframe_at_the_boundary` (Review Focus 3): native counts `{"1m": 20_000}` → `"1m"`; `{"1m": 20_001, "15m": 1_334}` → `"15m"`; native `"1D"` → `"1D"`.
  - `test_sample_at_buckets_takes_the_last_native_value` — three buckets, the middle one empty → `[v2, None, v9]`.
  - `test_bars_route_aggregates_a_long_window` on the store fixture with `max_bars` small: `shown <= max_bars`, `count` equals the native count, `display_timeframe` coarser, and a window narrowed to fit returns native bars.
  - `test_indicators_follow_the_display_bars` — `len(series[k]) == len(bars)` for the same window, and each value equals the native series at its bucket's last bar.
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the Aegis scope — PASS. **Step 5: Commit** "Aegis data: display candles and indicators for long ranges".

### Task 5: The long-range chart in the page

**Files:**
- Modify: `ui/src/chart/adapter.ts` (`onViewport`, `replaceBars`), `ui/src/chart/vela.ts` (`chart.on('viewport:changed')` debounced in the page, `setMarket({timeframe, data, visibleRange})` for in-place swaps, overlays and markers re-applied after the swap), `ui/src/api/client.ts` (`bars`/`indicators` take an optional view)
- Modify: `ui/src/components/ChartPanel.tsx`, `ui/src/components/LibraryChart.tsx` (both use the loader)
- Create: `ui/src/chart/longRange.ts`, `ui/src/chart/longRange.test.ts`, `ui/src/chart/useLongRange.ts`

**Interfaces:**
- Consumes: Task 4's routes.
- Produces:
  - `longRange.placeMarkers(markers: Marker[], barTimes: number[]): Marker[]` — each marker on the candle containing it (Review Focus 4);
  - `longRange.viewWindow(visible: {from: number; to: number}, selection: {from: number; to: number}, margin = 1): {from: number; to: number}` — the visible span widened by `margin` spans on each side, clamped;
  - `longRange.shownAs(displayTf, nativeTf): string | null` — "shown as 1h candles", or null when native;
  - `useLongRange(adapter, selection, indicators, markers)` returning `{count, shown, displayTimeframe, loading, error}`.

- [ ] **Step 1: Failing vitest** (`longRange.test.ts`):
  - `placeMarkers` with a marker on a candle open, between candles, before the first and after the last;
  - `viewWindow` clamps to the selection;
  - `shownAs("1h", "1m") === "shown as 1h candles"` and `shownAs("1m", "1m") === null`.
- [ ] **Step 2: Run** `npm --prefix app/products/aegis/ui test` — FAIL.
- [ ] **Step 3: Implement.** The loader:
  - fetches the selection once with `max_bars = 20_000`;
  - on `viewport:changed` (debounced 400 ms), re-asks for `viewWindow(...)` when the visible span would fit a finer timeframe or leaves the loaded window, and swaps with `replaceBars`;
  - keeps the header's true `count` and adds the "shown as" badge.

  A selection that fits draws exactly as today (`setBars`).
- [ ] **Step 4: Run vitest, `tsc`, the build; a browser check:**
  - QQQ 1m ten years reads "947,519 bars" and "shown as 1h candles";
  - zooming swaps to finer candles and to native 1m;
  - the strategy's indicators and the run's markers stay aligned;
  - the Library's run view behaves the same;
  - a 1h two-year selection is unchanged.
- [ ] **Step 5: Commit** "Aegis UI: a long-range chart with display candles and zoom".

### Task 6: Save only what I keep

**Files:**
- Create: `app/products/aegis/preferences.py` (`Preferences`), `app/products/aegis/unsaved.py` (`UnsavedRuns`)
- Modify: `app/products/aegis/api.py` (`GET`/`PUT /preferences`, `POST /backtest` `save`, `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/keep`)
- Modify: `ui/src/components/TopBar.tsx` (`#save-mode`), `ui/src/components/StatusStrip.tsx` (`#keep-run`), `ui/src/components/RunsDrawer.tsx` (not-kept rows with Keep), `ui/src/api/client.ts`, `ui/src/results.ts` (`saved?: boolean`)
- Test: `tests/test_aegis_preferences.py` (owned `aegis`), `tests/test_aegis_api.py`

**Interfaces:**
- Produces:
  - `Preferences(root).get() -> {"save_runs": "every" | "kept"}` and `.set(save_runs) -> dict`, stored atomically in `data/aegis/preferences.json`;
  - `UnsavedRuns(limit=20)` with `add(envelope)`, `get(run_id)`, `list() -> list[dict]` (summaries with `"kept": False`) and `pop(run_id)`;
  - `POST /backtest` body `save: bool | None`, response `saved: bool`;
  - `POST /runs/{id}/keep` → `{"saved": run_id}`, 404 for an unknown or forgotten id, 200 for an already saved run.

- [ ] **Step 1: Failing tests:**
  - `test_preferences_default_and_round_trip` (default `"every"`; a bad value → `ValueError`);
  - `test_kept_mode_holds_unsaved_runs` — in `"kept"` mode POST `/backtest` answers `saved: false`. The run is in GET `/runs` as `kept: false` and served by GET `/runs/{id}`, but is not in the Library or `list_runs`. Keep saves it, the Library then lists it, and the hash is unchanged;
  - `test_unsaved_runs_keep_only_the_last_20`;
  - `test_save_overrides_the_preference`;
  - `test_materialize_always_saves`;
  - `test_keep_of_a_forgotten_run_is_404` (Review Focus 5: a new `UnsavedRuns` stands in for a restart).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** the Aegis scope, then vitest and the build; a browser check of the switch, Keep in the status strip and in the drawer. **Step 5: Commit** "Aegis: save every backtest, or only what I keep".

### Task 7: Acceptance and the record

**Files:** `tests/products/aegis/browser_workstation.py` (items 82–86, `NO_LIMIT_BASE` = this plan's commit; items 77 and 80 move to the new guard), `docs/MISSION10_NO_LIMIT.md`, `docs/evidence/aegis-acceptance-<stamp>.json`.

- [ ] **Step 1: Write the items:**
  - **77:** its bar assertion becomes `50_000 < bars <= 2_000_000`.
  - **80:** its first check (ten years of 1m refused) becomes "ten years of 1m now select: 947,519 bars" (the guard is unit-tested in Task 3).
  - **82:** a slim run. Its file has no `series`, at most 2,000 side-equity points, `stored.format` 2, and is under 1 MB for item 22's request; its hash equals `RECORDED_IDENTICAL_HASH`; a format-1 run from before the mission opens in the Library with its equity.
  - **83:** ten years of 1m in the page. The header reads 947,519 bars, shown as aggregated candles (at most 20,000); a mouse-wheel zoom swaps to finer candles; markers and indicators align; Run Backtest completes. The run's file size and the worker's peak working set (read through PowerShell, before and after) are recorded.
  - **84:** the ten-year run opens in the Library and compares with item 22's run.
  - **85:** "Save only what I keep": a backtest is not listed in the Library; Keep lists it; the mode is switched back to "every".
  - **86:** governance since `NO_LIMIT_BASE`; items 1–81 pass.
- [ ] **Step 2: Rebuild, restart the worker, run items 82–86 alone first** (as for Mission 9 and the limits change), then the full walk: 86/86. Copy the evidence.
- [ ] **Step 3: `tools\verify.ps1` on the branch** (stops at the main-branch check by design), vitest and the build.
- [ ] **Step 4: Write the record** with the probe's numbers before and after, and commit "Aegis: Mission 10 acceptance and the record".
