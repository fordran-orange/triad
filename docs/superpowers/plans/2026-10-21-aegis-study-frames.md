# Aegis Mission 12: studies on frames — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Studies run on one prepared frame per symbol, so a ten-year 1-minute study works, and every study output is byte-identical to today's rows path on the same bars.

**Architecture:** `api._study_bars` hands `StudyJob` prepared frames, and a lazy `IsoTimes` sequence replaces the per-bar ISO lists for planning and records. `study_rules` runs out-of-sample windows with `frame_slice` + `run_prepared` and maps held bars by `searchsorted`. The study cache gains a byte bound, and `STUDY_BAR_CAP` goes. Goldens captured from today's code before any change are the oracle.

**Tech Stack:** Python 3.12, pandas/numpy, pytest under `TRIAD_PYTEST_SCOPE=aegis`, Playwright acceptance.

**Spec:** `docs/superpowers/specs/2026-10-21-aegis-study-frames-design.md` (5fa7c82)

## Global Constraints

- Identity is a hard requirement. The frame path reproduces today's study output exactly:
  - every window record and full window file;
  - the stitched rules and the report;
  - every `run_hash`/`result_hash`.

  The keys that differ between two runs of today's code on the same bars (times, ids, timings) are the only ones excluded from the comparison.
- `STUDY_BAR_CAP` is removed; studies are bounded by `data.BAR_CAP` (2,000,000). Study pools keep `fitted_workers`.
- The study cache is `IndicatorCache(max_data_keys=8, max_bytes=POOL_CACHE_BYTES_PER_BAR × longest symbol's bars)`.
- No per-bar Python object in the study path:
  - no `engine_rows` for studies;
  - no list of ISO strings or datetimes per bar.
- Saved studies open and resume unchanged. No API request or response changes.
- Nothing under `app/trading_core`, `app/platform_host` or `app/products/triad` changes; Exchange CLOSED; no new package. Lint only via the scope script.

## Review Focus

1. **A window whose out-of-sample run carries a position in, and a flat window** (no recommendation): their records, chains and `run_hash` equal today's. Task 1 `test_study_output_equals_the_golden` (the golden study has both).
2. **A trade closed at the end of data, and a position still open at a window's end:** `_held` gives the same bars as today. Task 1 `test_held_by_index_equals_held_by_datetime`.
3. **A study resumed after the mission** from windows written before it: it finishes with the same hashes. Task 1 `test_a_study_resumes_on_frames`.
4. **A symbol with fewer bars than one window, and an unknown symbol:** the plan answers as today. The existing plan tests run unchanged on `IsoTimes`.
5. **Real 1-minute bars** (DST changes, session gaps): identity holds. Task 1's real-data capture and compare (`tests/products/aegis/study_identity.py`).

---

### Task 1: Studies on frames

**Files:**
- Create:
  - `tests/fixtures/aegis_study_golden.json` (captured from today's code);
  - `tests/products/aegis/study_identity.py` (real-data capture/compare).
- Modify:
  - `app/products/aegis/studies.py` (`StudyJob`, `STUDY_BAR_CAP` removed, `IsoTimes`);
  - `app/products/aegis/study_rules.py` (`_side_run`, `run_window`, `_held`);
  - `app/products/aegis/api.py` (`_study_bars`, `_timestamps`, the study routes).
- Test: `tests/test_aegis_studies.py`, `tests/test_aegis_study_rules.py`, `tests/test_aegis_api.py` (the Mission 10 cap test becomes a `BAR_CAP` test).

**Interfaces:**
- Produces:
  - `studies.IsoTimes(frame: pd.DataFrame)`: a `Sequence[str]` with `len()` and `[i]` (negative indices too), equal to `engine_rows`' strings;
  - `StudyJob(document, bars_by_symbol: dict[str, list[dict] | pd.DataFrame], pinned_by_symbol, repository, max_workers=None)`: rows go through `prepare_bars`, frames are used as given;
  - `study_rules.run_window(spec, frame: pd.DataFrame, window, chains, settings, last, flat=False, cache=None)`;
  - `study_rules._held(trades, open_position, stamps_ns: np.ndarray, start, end)`.

- [ ] **Step 1: Capture the goldens with today's code (before any change).**
  - **The synthetic study:** run `new_study` + `run_to` on `ROWS_BY_SYMBOL` twice in temporary repositories. Find the keys whose values differ between the two runs, and write the canonical output of the first to `tests/fixtures/aegis_study_golden.json` with those keys removed. The canonical output is the document's `windows` and `report`, plus every `StudyStore.read_window` record, with those keys stripped at any depth.
  - **The real-data capture:** write `tests/products/aegis/study_identity.py`. `capture OUT` runs a study on real QQQ 1m (2025-01-02 → 2025-04-30, in-sample 6,000, out-of-sample 3,000, the 9-cell parent of `make_parent`) in a temporary repository and writes the canonical output; `compare OUT` runs it again and reports the first difference. Run `capture` now into the plan workspace.
- [ ] **Step 2: Write the failing tests:**
  - `test_study_output_equals_the_golden`: a study on `ROWS_BY_SYMBOL` rows, and the same study on their prepared frames, each canonically equal to the golden.
  - `test_iso_times_equal_the_rows`: on a fixture frame, `list(IsoTimes(frame)) == [r["timestamp"] for r in engine_rows(frame, "QQQ")]`; `len`, `[0]` and `[-1]` agree.
  - `test_held_by_index_equals_held_by_datetime`: on trades that enter and exit inside, enter before the window, close at the end of data (`exit_signal_time == exit_time`), and a still-open position, the new `_held` over int64 nanoseconds equals the old one over datetimes. Copy the old body into the test as the oracle.
  - `test_a_study_resumes_on_frames`: windows written by a paused study, resumed on frames, finish with the golden hashes.
  - `test_the_study_cache_is_byte_bounded`: `StudyJob(...).cache.max_bytes == POOL_CACHE_BYTES_PER_BAR * longest`.
  - `tests/test_aegis_api.py`:
    - `test_a_study_over_the_study_bar_cap_is_refused` becomes `test_studies_take_the_general_bar_guard`: with `data.BAR_CAP` patched to 500, the plan answers 422 "over cap"; unpatched it plans 780 bars;
    - `studies` has no `STUDY_BAR_CAP`.
- [ ] **Step 3: Run** `TRIAD_PYTEST_SCOPE=aegis .venv-aegis/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_aegis_studies.py tests/test_aegis_study_rules.py tests/test_aegis_api.py -k "golden or iso_times or held_by or resumes_on_frames or byte_bounded or general_bar_guard"`. Expected: FAIL (`IsoTimes` missing, frames not accepted, the cap still present). The golden test on rows passes before the change: it is the oracle's own check.
- [ ] **Step 4: Implement** as spec §4:
  - `api._study_bars` returns prepared frames, and `_timestamps` returns `IsoTimes`;
  - `StudyJob` holds frames, takes its records' times from `IsoTimes`, sets the byte-bounded cache and passes the frame to the pool;
  - `_side_run`/`run_window` use `frame_slice` + `prepared_request` + `run_prepared`, with `evaluate_from` and the exit signal time taken from the frame's timestamps;
  - `_held` uses `np.searchsorted(stamps_ns, ns(value), side="left")`;
  - remove `STUDY_BAR_CAP` and its check.
- [ ] **Step 5: Run** the whole Aegis scope (expected PASS, every hash test unchanged), then `study_identity.py compare` against the Step 1 capture (expected: identical), then the lint script.
- [ ] **Step 6: Commit** "Aegis studies: one prepared frame per symbol, output unchanged".

### Task 2: Memory, acceptance and the record

**Files:**
- `tests/products/aegis/memory_probe.py` (a `study` mode);
- `tests/products/aegis/browser_workstation.py`:
  - item 89, a real 1m study above the old cap;
  - item 90, governance;
  - `STUDY_FRAMES_BASE` = this plan's commit;
- `docs/MISSION12_STUDY_FRAMES.md`;
- `docs/evidence/aegis-acceptance-<stamp>.json`.

**Interfaces:**
- Consumes: Task 1's routes (unchanged shapes).

- [ ] **Step 1: The probe's `study` mode.** In a temporary repository, run a study on QQQ 1m over `START END` (in-sample 95,000, out-of-sample 47,000, the 9-cell parent), with nothing saved to the operator's store. Report the peak working set, its per-bar figure and the seconds. Measure ten years (2016-09-19 → 2026-09-18) once.
- [ ] **Step 2: The items.**
  - **89:**
    - create a finished 4-cell experiment on QQQ 1m 2023-01-03 → 2023-03-31 through the API;
    - plan and run a study of it over QQQ 1m 2023-01-01 → 2026-09-18 (in-sample 40,000, out-of-sample 20,000); the plan reports more than 200,000 bars, where the old cap answered 422;
    - the study reaches done with every window and a report, and opens in the Library and on the Experiments page.
  - **90:** governance since `STUDY_FRAMES_BASE`; items 1–88 still pass.
- [ ] **Step 3: Restart the worker detached, trial items 89–90 alone, then the full walk.** Expected: 90/90, no page errors. Copy the evidence. Run `tools\verify.ps1` on the branch (it stops at the main-branch check by design).
- [ ] **Step 4: Write `docs/MISSION12_STUDY_FRAMES.md`** (intent, decisions, the identity evidence, the memory before/after, acceptance, verification, rulings) and commit "Aegis: Mission 12 acceptance and the record".
