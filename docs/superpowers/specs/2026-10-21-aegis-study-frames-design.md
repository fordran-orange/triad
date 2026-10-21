# Aegis Mission 12: studies on frames — design (2026-10-21)

## 1. Intent

Mission 10 moved backtests, experiments, the optimizer and walk-forwards onto one prepared frame,
so ten years of 1-minute bars run in about 1.5 GB. Studies stayed on dict rows; a fix pass capped
them at 200,000 bars per symbol (`STUDY_BAR_CAP`) to keep that path safe. The operator, offered
this as the next mission: "do it", then "yes" to the four recommendations below.

Success: a ten-year 1-minute study runs. Its windows, trades, run hashes and report are exactly what
today's path produces on the same bars. Memory stays near the Mission 10 figures.

## 2. Decisions (the operator: "yes", 2026-10-21)

1. **Identical results, a hard requirement.** On the same bars, the frame path produces
   byte-identical study output to today's rows path: every window record (times, cells, plateau,
   best cell, the three rules' trades, metrics, chains and `run_hash`), the stitched rules and the
   report. A test pins it on real archive data; any difference blocks the merge.
2. **The study cap is lifted.** `STUDY_BAR_CAP` goes; studies are bounded by the general 2,000,000-bar
   guard (`data.BAR_CAP`) like every other path. Study pools keep taking only the workers free
   memory holds (Mission 10 fix pass).
3. **The per-bar holders go:**
   - studies hold one prepared frame per symbol;
   - the bars a side held are found from the frame's timestamp column (no list of datetime objects
     per window and rule);
   - planning reads timestamps lazily (no list of ISO strings per bar);
   - the study's indicator cache is bounded by bytes as well as by data keys, as the pool workers'
     are.
4. **Acceptance:** one new item runs a real 1-minute study above the old cap: QQQ, 1m,
   2023-01-01 → 2026-09-18 (about 360,000 bars), from a small 4-cell experiment, with about 40,000
   in-sample and 20,000 out-of-sample bars, finishing in about two minutes. A full ten-year,
   three-symbol study works but is not walked (its time).

## 3. Where a study holds a bar today

| Place | Holder | Per bar |
|---|---|---|
| `api._study_bars` | `engine_rows(frame, symbol)` per symbol | a dict and an ISO string |
| `api._timestamps` (plan, create) | an ISO string per bar per symbol | a string |
| `StudyJob.rows` | the same rows for the job's life | a dict |
| `study_rules.run_window` | `moments = [datetime per bar up to the window's end]`, per window and rule | a datetime |
| `study_rules._side_run` | `run_backtest(bars=rows[: …])`, re-preparing a frame from dicts each run | dicts → a frame |
| `StudyJob.cache` | `IndicatorCache(max_data_keys=8)`: each out-of-sample run is a new slice, so up to 8 slices × the rules' configurations × 7.6 MB per series on ten years | arrays |

## 4. Design

### 4.1 Bars

- **API selection:** `api._study_bars` selects each symbol's archive frame as today and returns
  `prepare_archive_frame(frame, symbol)` instead of rows. It still answers 422 for an unknown range
  or a selection over `BAR_CAP`.
- **Job:** `StudyJob` takes those frames (`frames_by_symbol`) and keeps them for the job's life.
- **Pool:** the pool already accepts a prepared frame (Mission 10), so `_switch_pool` passes the
  frame.

### 4.2 Timestamps for planning and records

A small read-only sequence over a frame's timestamp column, `IsoTimes(frame)`, answers `len()` and
`[i]` with the ISO string today's rows carry (`Timestamp.isoformat()`, the string `engine_rows`
wrote). `plan_study` and `create_study` receive it in place of the list (they only take lengths and
index), and `StudyJob` uses it for every window record's times. Nothing builds a string per bar.

### 4.3 Out-of-sample runs

`_side_run` and `run_window` take the symbol's prepared frame:
- the bars of a run are `frame_slice(frame, 0, end)`, equal to `_prepare_frame(rows[:end])`
  (Mission 10, verified by its QA on real 1h walk-forwards);
- the run is `run_prepared(prepared_request(strategy, settings), bars, _data_key(bars), cache)`;
- `evaluate_from` and a carried position's `exit_signal_time` come from the frame's timestamps,
  the same datetime and the same ISO string as today.

`_held` maps a trade's times to bar indices by `searchsorted` over the window's timestamp column
(int64 nanoseconds), giving the same indices as today's `bisect_left` over datetimes.

### 4.4 The study's indicator cache

`IndicatorCache(max_data_keys=8, max_bytes=POOL_CACHE_BYTES_PER_BAR × the longest symbol's bars)`,
the least recently used configuration going first. The cap never changes a result; an evicted
series is recomputed.

### 4.5 Not changed

- A study's document, its window records and report, and every hash.
- The pool's window maps (already on frames).
- The experiment a study comes from; the API's requests and responses.
- Studies saved before the mission open and resume unchanged.

## 5. Verification

- **Tests first:**
  - **Identity:** the same study (two symbols, several windows, all three rules, a carried position
    and a flat window) run through today's rows path and through frames gives equal window records,
    stitched rules, report and `run_hash` values. One run uses the archive fixture; one uses real
    QQQ 1m bars from a short range, skipping without the archive.
  - **`IsoTimes`:** equals `[row["timestamp"] for row in engine_rows(frame)]` element by element,
    and has the same length.
  - **`_held`:** gives the same set as today's datetime path on trades that enter, exit, close at
    the end of data and stay open.
  - **Cap and memory:** a study over more than 200,000 bars plans instead of answering 422; the
    study's cache never exceeds its byte bound.
- **Memory probe:** the probe gains a `study` mode (one symbol, ten years of 1m, a small surface)
  that records the peak working set and seconds.
- **Acceptance** (§2 item 4); the full walk, `tools\verify.ps1`, the milestone QA and the
  whole-branch review.

## 6. Out of scope

Coarser-than-1D candles; converting saved documents; changing how a study chooses windows or
rules; multi-symbol ten-year studies in the acceptance walk.
