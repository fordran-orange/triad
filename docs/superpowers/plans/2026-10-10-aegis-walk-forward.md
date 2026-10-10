# Aegis Walk-Forward Validation and Core Unthrottle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Aegis workstation rolling walk-forward validation (per side, stitched out-of-sample equity, efficiency and stability, persisted with a pinned source and `result_hash`, lit up in the Walk-Forward tab), and opt Core's gateway and both product workers out of Windows power throttling through one shared Core helper.

**Architecture:** The optimizer's single-worker runner is extracted into `jobs.py` as a generic `JobRunner` with two job kinds (optimization, walk-forward) under one lock and one 409 rule; `walkforward.py` holds pure window cutting, selection, chaining, stitching and stability over the existing engine, which gains `BacktestSettings.evaluate_from` for the warm-up lead; five routes mirror the optimizer's; the UI adds a popover mode and the tab. The Core change is `app/trading_core/process_power.py` plus three lifespan call sites.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pandas; React 18 + Vite 5 + TypeScript 5 + vitest; Playwright 1.63 (Chromium); ruff.

**Spec:** `docs/superpowers/specs/2026-10-10-aegis-walk-forward-design.md`

## Global Constraints

- Core imports neither product (`tests/test_architecture.py`); products may import `trading_core.process_power`.
- The only Core files touched: `app/trading_core/process_power.py` (new), `app/trading_core/api.py` (one call), `app/products/triad/server.py` (one call). No launch-script changes.
- Honesty rule: nothing computed is shown before it is computed; pending windows show `—`; per-side labelling; no combined walk-forward claimed.
- Caps and bounds (spec §5.2): `windows ≥ 1` and `≤ 50`; `in_sample_bars ≥ 35 + longest indicator length`; `out_of_sample_bars ≥ 20`; grid `≤ 400` cells; `total_units = windows · (cells + 1)`.
- Window arithmetic (spec §5.2): window `k` in-sample `[k·oos, k·oos+is)`, out-of-sample `[k·oos+is, k·oos+is+oos)`; `windows = floor((n − is) / oos)`; `unused_tail_bars = n − is − windows·oos`.
- Lead: `longest indicator length of the chosen configuration + 1` bars before the out-of-sample start; `evaluate_from` = timestamp of the first out-of-sample bar.
- Capital chaining: window 0 starts at `settings.initial_capital`; window k at window k−1's out-of-sample ending equity.
- Efficiency: `(oos.net_return / oos_bars) / (is.net_return / is_bars)`, `null` unless `is.net_return > 0`.
- Hash: SHA-256 of the canonical JSON (sorted keys, `(",", ":")` separators, NaN → null) of the walk-forward payload (spec §5.6); envelope fields never enter it.
- 409 detail for both kinds: `"an optimization is already running"`.
- Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; use `git -c core.hooksPath=NUL commit`; write commit messages to a file with the shell.
- Python commands use `.venv/Scripts/python.exe`; pytest with `-p no:cacheprovider`; UI commands run from `app/products/aegis/ui`.
- Worker restarts are detached (WMI `Win32_Process.Create` of `tools/start_product.ps1 -Product aegis`); Core via `tools/ensure_core.ps1 -Restart`; Triad via `tools/start_product.ps1 -Product triad`.

## Review Focus

1. A walk-forward whose in-sample window cannot warm the longest indicator must be refused at plan time, never produce windows of null cells — Task 3 test `test_plan_rejects_in_sample_shorter_than_warmup`.
2. No out-of-sample trade may carry a signal before its window's first bar; the lead only warms indicators — Task 5 test `test_oos_trades_never_signal_before_window_start`.
3. Cancelling between units must leave only complete windows in the stitched series, never a half-evaluated one — Task 5 test `test_cancel_between_units_keeps_completed_windows_only`.
4. A walk-forward started while an optimization runs (and the reverse) must get 409 and must not disturb the running job — Task 6 test `test_cross_kind_busy_is_409_and_first_continues`.
5. A refused power-throttling opt-out must never stop a worker from starting — Task 1 test `test_opt_out_returns_false_and_logs_when_refused`.

---

### Task 1: Core power-throttling helper, three call sites, measured restarts

**Files:**
- Create: `app/trading_core/process_power.py`, `tests/test_process_power.py`
- Modify: `app/trading_core/api.py:23-25` (lifespan start), `app/products/triad/server.py:18-19` (lifespan start), `app/products/aegis/server.py` (delete `opt_out_of_power_throttling`, import it), `tests/test_aegis_api.py` (the existing `test_power_throttling_opt_out_is_safe_to_call` moves to the new test file)

**Interfaces:**
- Produces: `trading_core.process_power.opt_out_of_power_throttling() -> bool` (True when applied; False off Windows or when refused; never raises). Internal seam for tests: `_set_process_information(state) -> tuple[bool, int]` returning `(ok, last_error)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_process_power.py`:

```python
import sys
from trading_core import process_power


def test_opt_out_applies_on_windows_and_declines_elsewhere():
    assert process_power.opt_out_of_power_throttling() is (sys.platform == "win32")


def test_opt_out_returns_false_and_logs_when_refused(monkeypatch, caplog):
    monkeypatch.setattr(process_power, "_set_process_information", lambda state: (False, 87))
    monkeypatch.setattr(process_power.sys, "platform", "win32")
    assert process_power.opt_out_of_power_throttling() is False
    assert "refused" in caplog.text and "87" in caplog.text


def test_every_worker_lifespan_opts_out():
    import inspect
    from products.aegis import server as aegis
    from products.triad import server as triad
    from trading_core import api as core

    for module in (core, triad, aegis):
        source = inspect.getsource(module.lifespan)
        assert "opt_out_of_power_throttling()" in source.split("yield")[0]
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_process_power.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: trading_core.process_power`.

- [ ] **Step 3: Implement** `app/trading_core/process_power.py`: move the function body from `app/products/aegis/server.py` verbatim, splitting the ctypes call into `_set_process_information(state)`; log `"power-throttling opt-out refused: error %s"` on refusal, info on success. Add the call as the first statement of the three lifespans; delete the Aegis copy and `import sys` if unused; Aegis imports `from trading_core.process_power import opt_out_of_power_throttling`. Move the old test out of `tests/test_aegis_api.py`.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_process_power.py tests/test_architecture.py tests/test_aegis_api.py -q -p no:cacheprovider`
Expected: PASS (3 + 6 + 19).

- [ ] **Step 5: Measure before, restart, measure after.** Before restarting, sample ten `GET http://127.0.0.1:8000/aegis/api/status` and ten `GET http://127.0.0.1:8000/health/live` latencies (median, max). Restart the gateway with `powershell -File tools/ensure_core.ps1 -Restart` (detached via WMI, then wait for `/health/live`), the Triad worker with `tools/start_product.ps1 -Product triad` (detached), and the Aegis worker. Sample again. Read `GET http://127.0.0.1:8000/triad/api/daily-schedule` → `enabled: false`, id `c99fa831-…`; `GET /aegis/api/status` → `human_directed` / `CLOSED`. Write all numbers into `docs/MISSION4_WALK_FORWARD.md` (create it with a "Measurements" section now; the rest fills in at Task 8).
Expected: both health routes answer; the daily-schedule record unchanged; latencies recorded whatever they are.

- [ ] **Step 6: Commit.** `git add app/trading_core/process_power.py app/trading_core/api.py app/products/triad/server.py app/products/aegis/server.py tests/test_process_power.py tests/test_aegis_api.py docs/MISSION4_WALK_FORWARD.md` — message: "Core: shared power-throttling opt-out for the gateway and both product workers".

---

### Task 2: Engine `evaluate_from`

**Files:**
- Modify: `app/products/aegis/backtest.py:34-37` (`BacktestSettings`), `:168-331` (`_simulate_side`), `app/products/aegis/ui/src/contracts.ts` (regenerated)
- Test: `tests/test_aegis_backtest.py`

**Interfaces:**
- Produces: `BacktestSettings.evaluate_from: datetime | None = None` (must be timezone-aware when set). Engine: for bars with `timestamp < evaluate_from` no pending entry is created, no `_in_position` flag and no equity point are recorded; warm-up and indicators run normally; metrics and exposure cover only the emitted bars.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_aegis_backtest.py`; `bars()` gives 91 half-hour bars from 2026-01-05 14:30 UTC):

```python
def test_evaluate_from_blocks_entries_and_withholds_equity_before_it():
    from datetime import UTC, datetime
    from products.aegis.backtest import BacktestSettings

    rows = bars()
    boundary = datetime(2026, 1, 6, 14, 30, tzinfo=UTC)  # bar index 48
    settings = BacktestSettings(evaluate_from=boundary)
    result = run_backtest(BacktestRequest(strategy=default_strategy(), bars=rows, settings=settings))
    for side in ("long", "short"):
        assert all(t["signal_time"] >= boundary.isoformat() for t in result[side]["trades"])
        assert result[side]["equity"][0]["timestamp"] == boundary.isoformat()
        assert len(result[side]["equity"]) == 91 - 48
    full = run_backtest(BacktestRequest(strategy=default_strategy(), bars=rows))
    assert full["long"]["series"]["ema"][48] == result["long"]["series"]["ema"][48]  # indicators unchanged


def test_evaluate_from_must_be_timezone_aware():
    from datetime import datetime

    import pytest
    from pydantic import ValidationError
    from products.aegis.backtest import BacktestSettings

    with pytest.raises(ValidationError, match="timezone-aware"):
        BacktestSettings(evaluate_from=datetime(2026, 1, 6, 14, 30))
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_backtest.py -q -p no:cacheprovider -k evaluate_from`
Expected: FAIL (`evaluate_from` unknown field → ValidationError on construction).

- [ ] **Step 3: Implement**: the field with a `field_validator` mirroring `EventPoint.aware`; in `_simulate_side` compute `evaluating = settings.evaluate_from is None or timestamp >= settings.evaluate_from` per row and gate the `in_position.append`, `curve.append` and the pending-entry creation on it (exits still process; none can exist before). Keep `_series` over all bars. Regenerate contracts: `.venv/Scripts/python.exe tools/aegis_contracts.py`.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_backtest.py tests/test_aegis_results.py tests/test_aegis_contracts.py tests/test_aegis_api.py -q -p no:cacheprovider`
Expected: PASS; the default-request `result_hash` in `test_backtest_hash_stable_across_two_requests` still passes (payload unchanged without the field).

- [ ] **Step 5: Commit.** "Aegis engine: evaluate_from withholds entries and equity before a warm-up boundary".

---

### Task 3: Walk-forward pure functions

**Files:**
- Create: `app/products/aegis/walkforward.py`, `tests/test_aegis_walkforward.py`
- Modify: `app/products/aegis/results.py` (`walkforward_payload`)

**Interfaces:**
- Consumes: `expand_grid(side) -> GridPlan` (Task 11 of Mission 3), `_metrics(trades, curve, initial_capital, exposure)` from `backtest.py`, `canonical_json`/`result_hash` from `results.py`.
- Produces:
  - `WalkForwardRequest(strategy, side: Literal["long","short"], data: DataReference, settings: BacktestSettings = BacktestSettings(), objective: Objective = "net_pnl", in_sample_bars: int = Field(ge=35), out_of_sample_bars: int = Field(ge=20))`, `extra="forbid"`.
  - `MAX_WINDOWS = 50`, `MIN_OOS_BARS = 20`.
  - `@dataclass Window(index: int, is_start: int, is_end: int, oos_start: int, oos_end: int)` (half-open bar indices).
  - `cut_windows(n_bars: int, in_sample: int, out_of_sample: int) -> tuple[list[Window], int]` → `(windows, unused_tail_bars)`; `ValueError("range too short: N bars; one window needs is + oos bars")` when none.
  - `longest_length(side: StrategySide) -> int`.
  - `@dataclass WindowPlan(windows: list[Window], unused_tail_bars: int, grid: GridPlan, cells_per_window: int, total_units: int)`; `plan(request: WalkForwardRequest, n_bars: int) -> WindowPlan` enforcing every bound of spec §5.2 (`ValueError` messages name the numbers).
  - `select_best(cells: list[dict], objective: str) -> dict | None` (cells `{"index", "params", "metrics"}`; `max_drawdown` minimized; null ignored; ties → lowest index).
  - `efficiency(is_metrics: dict, is_bars: int, oos_metrics: dict, oos_bars: int) -> float | None`.
  - `stitch(records: list[dict], initial_capital: float) -> dict` → `{"trades", "equity", "metrics"}` over `status == "done"` records in index order, exposure = in-position bars / evaluated bars (each record carries `oos_in_position: int` and `oos_bars`).
  - `stability(records: list[dict], paths: list[str]) -> dict` → `{"parameters": {path: {min,max,mean,std}}, "positive_oos_windows", "windows_evaluated", "mean_efficiency"}`.
  - `pending_record(window: Window, timestamps: list[str]) -> dict` → the window record of spec §5.3 with nulls and `status: "pending"`.
  - `results.walkforward_payload(records, stitched, stability, request, data_identity, unused_tail_bars) -> dict` with `kind: "walkforward"` and the keys of spec §5.6.

- [ ] **Step 1: Write the failing tests** `tests/test_aegis_walkforward.py`:

```python
def test_cut_windows_rolls_by_out_of_sample_and_reports_the_tail():
    windows, tail = cut_windows(502, 200, 50)
    assert len(windows) == 6 and tail == 2
    assert (windows[0].is_start, windows[0].is_end, windows[0].oos_start, windows[0].oos_end) == (0, 200, 200, 250)
    assert (windows[5].is_start, windows[5].oos_end) == (250, 500)
    assert [w.oos_start for w in windows] == [w.is_end for w in windows]
    with pytest.raises(ValueError, match="range too short: 100 bars"):
        cut_windows(100, 80, 30)

def test_plan_rejects_in_sample_shorter_than_warmup():   # longest length 30 → is must be >= 65
    request = make_request(in_sample_bars=60, out_of_sample_bars=20)
    with pytest.raises(ValueError, match="in_sample_bars 60 below 65"):
        plan(request, 500)

def test_plan_caps_windows_and_grid_and_counts_units(): ...   # 50 windows cap; 401-cell grid → "grid too large"; total_units = windows*(cells+1)

def test_select_best_direction_nulls_and_ties(): ...           # net_pnl max; max_drawdown min; null skipped; tie → lowest index; all null → None

def test_efficiency_is_per_bar_ratio_or_null(): ...            # (0.10/50)/(0.20/200) == 2.0; is_net_return <= 0 → None

def test_stitch_chains_only_done_windows_in_order(): ...       # pending ignored; trades concatenated; equity concatenated; exposure from counts

def test_stability_spread_positive_windows_and_mean_efficiency(): ...

def test_walkforward_payload_hash_identity_and_sensitivity():  # same inputs → same hash; out_of_sample_bars changed → different; no job_id/created_at/elapsed keys anywhere
```

(`make_request` builds a `WalkForwardRequest` from `default_strategy()` and `DataReference(symbol="QQQ", timeframe="1h", start="2023-01-01", end="2024-12-31")`.)

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_walkforward.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: products.aegis.walkforward`.

- [ ] **Step 3: Implement** the functions above as pure code (no threads, no I/O). `stitch` builds the stitched curve by concatenation and calls `_metrics` with `initial_capital` from the request; `stability` uses population std; `walkforward_payload` passes everything through `results._clean`.

- [ ] **Step 4: Run** the file again. Expected: PASS (8).

- [ ] **Step 5: Commit.** "Aegis: walk-forward windows, selection, stitching, stability and payload".

---

### Task 4: Extract `JobRunner` with the optimizer kind

**Files:**
- Create: `app/products/aegis/jobs.py`
- Modify: `app/products/aegis/optimize.py` (keep `expand_grid`, `estimate_seconds`, `heatmap`, `engine_rows`, `OptimizeRequest`; add `OptimizerJob`; `OptimizerRunner` becomes a thin subclass/alias), `app/products/aegis/api.py` (`get_runner` returns `JobRunner`; `/optimize` starts `OptimizerJob(request, frame, pinned)`)
- Test: `tests/test_aegis_optimize.py` (unchanged, must stay green), `tests/test_aegis_jobs.py` (new, small)

**Interfaces:**
- Produces:
  - `class JobKind(Protocol)`: `name: str` (`"optimization"` | `"walkforward"`), `side: str`, `bars_per_unit: int`, `total_units: int`, `run_unit(index: int) -> Any` (heavy work, no lock), `commit(index: int, result: Any) -> None` (under the runner lock), `snapshot() -> dict` (under the lock; kind fields), `finalize(status: str) -> dict` (under the lock at a terminal status; extra fields such as `result_hash`).
  - `JobRunner(repository, max_workers=1, after_unit=None)` with `start(kind: JobKind) -> str` (`JobBusy` while any kind is unfinished; persists the queued envelope first), `status(job_id) -> dict`, `cancel(job_id) -> bool`, `mark_lost_on_startup() -> list[str]` (both kinds), `list_jobs(kind_name) -> list[dict]`, `ms_per_bar: float` (learned; persisted as `ms_per_bar` in every envelope; read back from the newest completed job of either kind).
  - Common envelope fields written by the runner: `job_id, kind, status, created_at, progress {done,total}, elapsed_ms, estimated_seconds, ms_per_bar, bars, error`; the kind's `snapshot()` merged on top (the optimizer kind reproduces today's keys exactly, including `side`, `objective`, `cells`, `matrices`, `cache_hits`, `data`, `strategy`, `settings`, `total_cells`, `skipped_cells`, `skipped`, `fast_values`, `slow_values`, `fast_path`, `slow_path`).
  - Repository dispatch by name: `save_{name}`, `get_{name}`, `list_{name}s`.
  - `OptimizerRunner(repository, max_workers=1, after_cell=None)` keeps its signature: `start(request, frame, pinned)` wraps `OptimizerJob`; `after_cell` maps to `after_unit`.

- [ ] **Step 1: Write the failing test** `tests/test_aegis_jobs.py`:

```python
def test_runner_dispatches_by_kind_name_and_learns_cost(tmp_path):
    class Counting:   # a trivial kind: 3 units, each returns its index
        name = "optimization"; side = "long"; bars_per_unit = 10; total_units = 3
        def __init__(self): self.seen = []
        def run_unit(self, index): return index
        def commit(self, index, result): self.seen.append(result)
        def snapshot(self): return {"seen": list(self.seen)}
        def finalize(self, status): return {"final": status}
    runner = JobRunner(JsonRunRepository(tmp_path))
    job_id = runner.start(Counting())
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    status = runner.status(job_id)
    assert status["seen"] == [0, 1, 2] and status["final"] == "done" and status["kind"] == "optimization"
    assert status["progress"] == {"done": 3, "total": 3} and status["ms_per_bar"] > 0
    assert [j["job_id"] for j in runner.list_jobs("optimization")] == [job_id]
```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_jobs.py -q -p no:cacheprovider`
Expected: FAIL with `ImportError` (`JobRunner`).

- [ ] **Step 3: Implement** `jobs.py` by moving `_Job`, the lock, `start`, `_run`, `_snapshot` (now common fields + `kind.snapshot()`), `status`, `cancel`, `mark_lost_on_startup`, `list_jobs`, `_learned_ms_per_bar` from `optimize.py`; `OptimizerJob` holds the plan, rows, cells, cache, `fast/slow` cell keys and produces today's snapshot; `OptimizerRunner` wraps it. `api.get_runner()` returns `JobRunner`.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_jobs.py tests/test_aegis_optimize.py tests/test_aegis_api.py -q -p no:cacheprovider`
Expected: PASS with no change to `tests/test_aegis_optimize.py` (15) or the optimizer API tests.

- [ ] **Step 5: Commit.** "Aegis: extract JobRunner from the optimizer; optimizer becomes a job kind".

---

### Task 5: Walk-forward job kind

**Files:**
- Modify: `app/products/aegis/walkforward.py` (`WalkForwardJob`), `app/products/aegis/runs.py` (`save_walkforward`, `get_walkforward`, `list_walkforwards`, folder `walkforward`)
- Test: `tests/test_aegis_walkforward.py`, `tests/test_aegis_runs.py`

**Interfaces:**
- Consumes: `JobRunner`, `JobKind` (Task 4); `plan`, `select_best`, `stitch`, `stability`, `pending_record`, `walkforward_payload` (Task 3); `run_backtest` with `evaluate_from` (Task 2); `engine_rows`.
- Produces: `WalkForwardJob(request: WalkForwardRequest, frame: pd.DataFrame, pinned)` implementing `JobKind` with `name = "walkforward"`, `bars_per_unit = in_sample_bars`, `total_units = windows · (cells + 1)`; unit `u` maps to window `u // (cells + 1)` and, within it, cell `u % (cells + 1)` for `< cells` else the out-of-sample run; `commit` appends the cell or stores `best`, runs nothing; the out-of-sample unit's `run_unit` reads the window's `best` (chosen at commit time of the last cell), builds the lead rows, chains capital from the previous done window and calls `run_backtest(..., settings=settings.model_copy(update={"evaluate_from": first_oos_timestamp, "initial_capital": chained}))`; `snapshot()` returns spec §6.2; `finalize("done")` sets `result_hash` from `walkforward_payload`.

- [ ] **Step 1: Write the failing tests** (append):

```python
def test_walkforward_job_completes_with_chained_capital_and_hash(tmp_path):
    # 91 synthetic bars; in_sample 40, out_of_sample 20 → 2 windows, tail 11; grid 2x2 via small_strategy ranges
    ...
    assert status["windows"] == {"done": 2, "total": 2} and status["unused_tail_bars"] == 11
    first, second = status["window_records"]
    assert first["status"] == "done" and second["oos"]["equity"][0]["equity"] == pytest.approx(first["oos"]["equity"][-1]["equity"])
    assert len(status["result_hash"]) == 64 and status["stitched"]["metrics"]["trade_count"] == len(status["stitched"]["trades"])

def test_oos_trades_never_signal_before_window_start(tmp_path):
    ...
    for record in status["window_records"]:
        for trade in record["oos"]["trades"]:
            assert trade["signal_time"] >= record["oos_start"]

def test_cancel_between_units_keeps_completed_windows_only(tmp_path):
    # hold after the first window's last unit; cancel; the stitched series equals window 0 only; window 1 stays pending
    ...

def test_walkforward_hash_is_identical_across_two_jobs_and_persisted(tmp_path):
    ...   # two jobs → same result_hash; repository.get_walkforward(job_id)["result_hash"] equal; list_walkforwards has both

def test_mark_lost_covers_walkforward_jobs(tmp_path): ...
```

and in `tests/test_aegis_runs.py`: `test_walkforward_kind_round_trips_with_sidecar`.

- [ ] **Step 2: Run** the two files. Expected: FAIL (`WalkForwardJob` / `save_walkforward` missing).

- [ ] **Step 3: Implement** `WalkForwardJob` and the repository kind.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_walkforward.py tests/test_aegis_runs.py tests/test_aegis_jobs.py tests/test_aegis_optimize.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit.** "Aegis: walk-forward job kind with warm-up lead, chained capital, progressive stitching and result_hash".

---

### Task 6: Routes, contracts, hygiene

**Files:**
- Modify: `app/products/aegis/api.py`, `app/products/aegis/strategy.py:47-53`, `app/products/aegis/indicators.py` (`IndicatorCache(max_data_keys=8)`), `tools/aegis_contracts.py` (add `WalkForwardRequest`), `app/products/aegis/ui/src/contracts.ts` (regenerated)
- Test: `tests/test_aegis_api.py`, `tests/test_aegis_strategy.py`, `tests/test_aegis_indicators.py`

**Interfaces:**
- Produces: the five routes of spec §6.3 (`POST /aegis/api/walkforward/plan` → `{windows, cells_per_window, total_units, unused_tail_bars, bars, estimated_seconds, ms_per_bar}`; `POST /aegis/api/walkforward` → 202 `{job_id, windows, cells_per_window, total_units, estimated_seconds}`; `GET /aegis/api/walkforward/{id}`; `POST /aegis/api/walkforward/{id}/cancel` with 404 for unknown ids, also applied to `/optimize/{id}/cancel`; `GET /aegis/api/walkforward`); `OptimizationParameter` validators (`start <= stop`; integer-valued `start/stop/step` for `.length` paths; message names the path); `IndicatorCache.max_data_keys` eviction and `api.get_cache()` singleton used by `POST /backtest` (keyed by `pinned.data_hash`).

- [ ] **Step 1: Write the failing tests:** in `tests/test_aegis_api.py`: `test_walkforward_plan_and_start_return_the_window_plan`, `test_walkforward_status_progresses_and_cancel_keeps_completed_windows`, `test_cross_kind_busy_is_409_and_first_continues` (hold an optimizer job, POST a walk-forward → 409; and the reverse), `test_walkforward_too_short_range_is_422_with_bar_counts`, `test_cancel_unknown_job_is_404_for_both_kinds`, `test_backtest_reuses_the_store_cache_across_requests` (second identical request reports `cache_hits > 0` via a new `cache_hits` envelope field); in `tests/test_aegis_strategy.py`: `test_optimization_parameter_rejects_reversed_and_fractional_length_ranges`; in `tests/test_aegis_indicators.py`: `test_cache_evicts_oldest_data_key_beyond_the_bound`.

- [ ] **Step 2: Run** the three files. Expected: FAIL on the new tests only.

- [ ] **Step 3: Implement** routes (mirroring the optimizer routes; `_select` for bars; `JobBusy` → 409; `ValueError` → 422; `KeyError` → 404), validators, cache eviction (insertion-ordered dict of data keys), `get_cache()`; regenerate contracts.

- [ ] **Step 4: Run** `.venv/Scripts/python.exe -m pytest tests/test_aegis_api.py tests/test_aegis_strategy.py tests/test_aegis_indicators.py tests/test_aegis_contracts.py tests/test_aegis_optimize.py tests/test_aegis_walkforward.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit.** "Aegis API: walk-forward routes, cross-kind 409, cancel 404, range validation, per-store backtest cache".

---

### Task 7: Walk-Forward tab and popover mode

**Files:**
- Create: `app/products/aegis/ui/src/components/WalkForwardTab.tsx`, `app/products/aegis/ui/src/components/walkforward.test.ts`
- Modify: `ui/src/results.ts`, `ui/src/api/client.ts`, `ui/src/state/workspace.tsx` (+ `workspace.test.ts`), `ui/src/components/JobPoller.tsx`, `ui/src/App.tsx`, `ui/src/components/OptimizePopover.tsx`, `ui/src/components/ResultsTabs.tsx`, `ui/src/styles.css`

**Interfaces:**
- Consumes: the routes of Task 6; `useRunBacktest`, `applyConfigs`, `StaleNotice`, `Heatmap` conventions from Mission 3.
- Produces: `results.ts` types `WalkForwardStatus`, `WindowRecord`, `WalkForwardPlan`, `WalkForwardStarted`; client `walkforwardPlan(body)`, `walkforward(body)`, `walkforwards()`, `walkforwardJob(id)`, `cancelWalkforward(id)` with `WalkForwardBody = OptimizeBody & { in_sample_bars: number; out_of_sample_bars: number }`; reducer state `walkforward: { long?: WalkForwardStatus; short?: WalkForwardStatus }`, actions `WALKFORWARD_UPDATED {side, job}`, `WALKFORWARD_LOST {side, job_id}`, `ResultsTab` gains `'walkforward'`; pure helpers exported from `WalkForwardTab.tsx`: `defaultWindowBars(bars: number | null, longest: number) -> {inSample, outOfSample}` (spec §7), `stitchedPoints(records) -> {points, boundaries}` (x by cumulative bar index, boundaries at window starts), `finalChoice(records) -> Record<string, number> | null`.

- [ ] **Step 1: Write the failing tests:** `walkforward.test.ts` (`defaultWindowBars` → 502 bars, longest 30 → `{200, 50}`; `{250, 63}` when bars null; floors `35 + longest` and 20), `stitchedPoints` (two done windows of 3 and 2 points → 5 points, boundaries `[0, 3]`), `finalChoice` (last done window's params, null when none); `workspace.test.ts` (`WALKFORWARD_UPDATED` stores per side; `WALKFORWARD_LOST` marks lost; `SET_RESULTS_TAB 'walkforward'`).

- [ ] **Step 2: Run** `npm test` in `app/products/aegis/ui`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement** types, client, reducer, poller (polls both kinds; 404 → lost), App adoption of unfinished walk-forwards, the popover mode switch with the plan line and defaults, `WalkForwardTab` (spec §7: status line, Cancel, stitched SVG with boundary ticks, windows table, stability panel, stitched metrics row, Apply final configuration → `applyConfigs` + unlink + rerun combined + Summary), `ResultsTabs` enabling the tab.

- [ ] **Step 4: Run** `npm test` and `npm run build`. Expected: all vitest files pass; build clean.

- [ ] **Step 5: Commit.** "Aegis UI: Walk-Forward tab, popover walk-forward mode, poller for both job kinds".

---

### Task 8: Acceptance items, record

**Files:**
- Modify: `tests/products/aegis/browser_workstation.py` (items 23–36 = spec §1 items 1–14; item 1 reads the measured latencies from `docs/MISSION4_WALK_FORWARD.md` is not needed — the script records fresh samples), `docs/MISSION4_WALK_FORWARD.md`, `docs/evidence/`

**Interfaces:**
- Consumes: the running workers (Aegis restarted after Task 7's build), the routes of Task 6, the tab of Task 7.
- Produces: `ITEMS` extended to 36; the JSON report gains `walkforward` timings (cells per second, per-window seconds, total) and the two identical-request hashes for item 12; the mission record's sections: operator decisions, what was built, acceptance evidence, measurements (gateway and worker latency before/after, per-cell cost, the full QQQ 1D walk-forward), rulings, known limits.

- [ ] **Step 1: Extend the script** with items 23–36 following the Mission 3 item style (QQQ 1D 2023-01-01 → 2024-12-31, in-sample 200, out-of-sample 50 → 6 windows; cancel at the first window; rerun to completion; apply; reload from `GET /walkforward`; identical rerun → same hash; a too-short request → 422; status still `human_directed` / `CLOSED`).

- [ ] **Step 2: Build the UI, restart the Aegis worker detached, run** `.venv/Scripts/python.exe tests/products/aegis/browser_workstation.py`
Expected: `36/36 PASS, 0 FAIL, page errors 0`; fix product defects under TDD and rerun until so.

- [ ] **Step 3: Write the record**, copy the final report under `docs/evidence/`.

- [ ] **Step 4: Commit.** "Aegis: walk-forward acceptance items and the Mission 4 record".

---

### Task 9: Milestone QA, review, fix pass, merge

- [ ] **Step 1:** `pytest -q`, `ruff check` and `ruff format --check` on every touched file, `npm test`, `npm run build`; record outputs in the mission note.
- [ ] **Step 2:** dispatch one independent QA agent at the exact commit with the brief of spec §8 (naming the Core change), and the whole-branch reviewer (fresh context, most capable model) with the review package, the plan's Review Focus verbatim and the ledger's rulings.
- [ ] **Step 3:** re-grade findings; one fix pass, each fix test-first; rerun the suite and the acceptance walk; record the verdicts and the pass in the mission note; commit.
- [ ] **Step 4:** finishing-a-development-branch: present the integration choice to the operator; merge and push only on their answer.
