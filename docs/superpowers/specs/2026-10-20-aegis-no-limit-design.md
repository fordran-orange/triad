# Mission 10 — "No limit": ten years of 1-minute bars, slim saved runs, and saving what matters (design, 2026-10-20)

Status: approved for planning. The operator approved the draft and its five recommended decisions
on 2026-10-20 ("merge yes", answering "yes" to start Mission 10 with the recommended answers).
This design replaces the draft of the same date. As in earlier missions, the design and the plan
are committed on `main` (after `0ca099a`, the limits change merged) and the branch
`aegis/no-limit` is cut from the plan commit.

## 1. Intent (operator, 2026-10-20)

- "200k after this run. goal is no limit."
- "What about only saving relevant runs? Would that help? Maybe as a selectable option."

Done means: ten years of QQQ 1-minute bars (947,519) can be charted, backtested, saved, opened in
the Library and compared on this laptop, and the operator can choose to save only the runs they
keep.

## 2. Decisions (operator, 2026-10-20)

1. **The result hash keeps its definition.** It is computed over the full result before the run is
   slimmed; every recorded hash (including the acceptance's Mission 3 and 5 hashes) stays valid.
   A slim saved run cannot recompute its own hash from its file; it is re-verified by rerunning.
2. **Equity detail:** each side's per-bar curve is stored resampled to at most 2,000 points,
   keeping the first and last; the metrics stay exact (computed before slimming).
3. **Saving:** the default stays "Save every backtest"; "Save only what I keep" is an option.
4. **Existing saved runs are left as they are.** Readers handle both formats; no migration.
5. **Long-range charts:** at most 20,000 candles per view; more detail as the operator zooms in.

## 3. Measured starting point

- The archive: QQQ 1m 947,519 bars (2016-09-19 → 2026-09-18); 15m 65,107; 30m 32,556;
  1h 17,533; 1D 2,514. Three symbols.
- A saved run is ≈ 412 bytes per bar, 87% of it per-bar data: each side's per-bar equity (≈ 108 B
  per bar per side), per-bar indicator series stored twice (`result.<side>.series` and `series`),
  markers twice. A 161,754-bar run is 66.7 MB.
- `/data/bars` is ≈ 93 bytes per bar (ten years of 1m ≈ 88 MB to the page).
- **Memory, measured out of process** (OS peak working set): selecting 161,754 1m bars brings the
  process from 118 MB to 394 MB (the minute archive held twice); the backtest path then peaks at
  +474 MB, **≈ 2,900 bytes per bar** (dict rows, per-bar dicts, a deep copy, the hash string, the
  saved string, the response). At ten years that is ≈ 3.2 GB in one process; this laptop has
  15.8 GB with ≈ 2.3 GB free while its services run.
- Two 200,000 limits: `BAR_CAP` (every archive selection) and `BacktestRequest.bars` (materialize,
  walk-forward units, study rule runs, serial optimizer cells).
- Per-bar data in saved runs has two readers: the Equity view draws the side curves (by index) and
  the comparison reads their first and last points. No production code recomputes a hash from a
  stored envelope.
- The chart: the adapter's `setBars` rebuilds the chart each call; Vela 0.8.3 offers
  `on('viewport:changed')`, `getVisibleRange`, `setVisibleRange` and an in-place
  `setMarket({timeframe, data, visibleRange})`. Overlays are index-aligned to the drawn bars.

## 4. Slim saved runs (new runs)

- `envelope(...)` computes `result_hash` over the canonical payload exactly as today, then builds
  the stored run:
  - no top-level `series`, no `result.<side>.series` (the charts recompute indicators from the
    archive already);
  - `result.<side>.equity` resampled to at most 2,000 points by index, first and last kept;
  - `result.markers` dropped (the top-level `markers` stays);
  - trades, metrics, combined equity (per trade exit), temporal, data, strategy, settings unchanged;
  - `stored: {"format": 2, "equity_points": {"long": n, "short": n}}` names the format and each
    side's true per-bar count.
- The POST response is the stored run (so GET equals POST, and the browser holds the slim run).
- Readers take both formats: the Equity view defaults missing curves to `[]` and its caption says
  how many bars a resampled curve stands for; the comparison is unchanged (endpoints are kept).

## 5. Memory: ten years of 1-minute bars in one process

Target, measured with the same out-of-process probe: **at most 1,000 bytes per bar above the
selected frame** on the backtest path, and the selected frame itself without a second copy of the
minute archive. Means:

- archive bars reach the engine as a frame, not as a list of dict rows (`/backtest`, materialize,
  experiments, studies, the optimizer and walk-forward);
- the hash is streamed: the canonical JSON is encoded incrementally into SHA-256, never held as one
  string; the canonical payload is not deep-copied when it needs no cleaning;
- `/data/bars` and `/data/indicators` build their responses from columns, not record lists;
- the store keeps one copy of the minute archive;
- the process pool receives column arrays, not dict rows, and a pooled job sizes its workers to
  the free memory (Windows `GlobalMemoryStatusEx` through `ctypes`, no new package): fewer workers
  when bars × workers would not fit, and a 422 naming the shortfall when even one worker would not.

## 6. The bar cap

- `BAR_CAP` becomes a memory guard of 2,000,000 bars (about twenty years of 1-minute bars); the
  refusal names the count as today.
- `BacktestRequest.bars` (supplied bars over HTTP) keeps a request-size guard of 2,000,000; the
  internal paths that built `BacktestRequest(bars=rows)` pass frames instead (§5).

## 7. The long-range chart

- **The worker chooses the candles.** `GET /data/bars` gains `max_bars` (the page sends 20,000) and
  an optional window (`from_ms`, `to_ms`). When the window's native bars exceed `max_bars`, it
  answers with the finest of the standard timeframes (15m, 30m, 1h, 1D) whose bars over the window
  fit, and says so: `display_timeframe`, `count` (the true native count over the whole selection,
  as today) and `shown`.
- **Indicators follow the candles.** `POST /data/indicators` takes the same `display_timeframe` and
  window: indicators are computed on the native bars of the whole selection (their warm-up is
  unchanged) and each displayed candle carries the native value at its bucket's last bar, so the
  series stay index-aligned to what is drawn.
- **Markers** keep their native times and true count; the page places each on the displayed candle
  that contains it.
- **Zoom.** The adapter exposes the visible range and its changes, and swaps data in place
  (`setMarket`) keeping the view. When the operator zooms or pans, the page (debounced) asks for the
  visible window with a margin; the worker answers at the finest timeframe that fits, down to the
  native one. The header keeps the true bar count and says "shown as 1h candles" when aggregated.
- The Charts page and the Library's run view share one long-range loader; a selection of at most
  20,000 bars behaves exactly as today.

## 8. Saving what matters

- A worker-side preference, `data/aegis/preferences.json`, with `save_runs`: `"every"` (default) or
  `"kept"`; `GET`/`PUT /aegis/api/preferences`. The Charts page's top bar shows the mode and switches
  it.
- In "kept" mode, `POST /backtest` returns the run but does not write it; the worker holds the last
  20 unsaved runs in memory, so Load, the Runs drawer (marked "not kept; gone on restart") and
  `GET /runs/{id}` work for them. `POST /runs/{id}/keep` saves one; the status strip and the drawer
  offer Keep. A worker restart forgets unsaved runs.
- Always saved, whatever the mode: materialized experiment cells. Unsaved runs never hold a
  strategy against deletion and never enter the Library.
- `POST /backtest` takes an optional `save` that overrides the preference for one request.

## 9. What stays

The pinned raw archive and `research_eligible: false`; the engine's results and metrics; every
recorded hash; existing saved runs readable as they are; the exchange closed; every Mission 3–9
and limits acceptance item (item 77's and item 80's bar-cap checks move to the new guard).

## 10. Verification

- Tests first: the hash equal before and after slimming and to the recorded identical-request hash;
  the stored run's fields and sizes; old-format runs still read; resampling keeps endpoints; the
  memory paths produce identical results and hashes to today's on the same bars; bucket sampling of
  indicators and the display timeframe choice; marker placement; preferences, unsaved runs, Keep,
  materialize always saving; vitest for the page's pure helpers.
- The memory probe (out of process, OS peak working set) on 161,754 and 947,519 1m bars, recorded.
- Acceptance items after the 81: a slim run's file and hash; ten years of 1m charted (aggregated,
  then zoomed to native candles), backtested, saved, opened in the Library and compared; "Save only
  what I keep" with Keep; governance.

## 11. Out of scope

Converting existing runs; pruning old unstarred runs automatically; candles coarser than 1D;
changing the hash definition.
