"""Optimization Lab v2 benchmarks (spec §9.1, §9.6): the §9.6 thresholds as constants and the two
benchmark records, both measured through a scratch worker, never the product's.

    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\lab_benchmark.py explore
        --data-root <scratch> --base http://127.0.0.1:8103/aegis/ --pid-file logs\\aegis-scratch.pid
        [--trials N] [--inprocess]
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\lab_benchmark.py execute
        --base http://127.0.0.1:8103/aegis/ --pid-file logs\\aegis-scratch.pid --data-root <scratch>
        [--cases A,B,C]
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\lab_benchmark.py analytics
        --base http://127.0.0.1:8103/aegis/ --pid-file logs\\aegis-scratch.pid --data-root <scratch>
        [--trials N] [--workers N]

`explore` (Track A, result exploration) writes the DEMO synthetic layout-2 fixture into the
scratch worker's data root when it is absent (`lab_fixture.py`, never through the engine) and
times the Lab's interactions as the HTTP requests the UI issues, plus the worker's memory, the
folder's size and a finalize-style compaction. `execute` (Track B, trial execution) runs the
§9.1b configurations through the worker's own API on the real engine. `analytics` (Phase 3, spec
§9.4) runs the importance task on the 1M fixture beside a running job (case A, back to back until
the task is done) and records the task's time, its fine-grid stage, the job's throughput loss
over the overlap and the Pareto and neighbourhood views. Each writes
`logs/lab-benchmark-<mode>-<stamp>.json` and prints `evaluate()` and `retest_due()`. A number
is labelled by what measured it: `http` through the scratch worker, `inprocess` as a proxy.
Every mode refuses the product store and the product port before anything else.

The module level imports only the standard library, numpy and `products.aegis.strategy` (which
imports only `kinds`), so the walk can import `bench_strategy` and `BENCH_SURFACE` on the Core
interpreter, which has no numba. `products.aegis.surface` (whose `optimize` import reaches the
kernel and numba), the Lab, pyarrow and the fixture are imported inside the functions that
need them. This module never imports `browser_workstation`: the walk imports this one.
"""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
# Run as a script, this checkout's code and never an editable install's (the walk and the tests
# have put it first already; then this changes nothing).
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from products.aegis.strategy import (
    Direction,
    ExecutionSpec,
    IndicatorSpec,
    RuleGroup,
    RuleSpec,
    StrategySide,
    StrategySpec,
    default_strategy,
)

if TYPE_CHECKING:
    from products.aegis.surface import Surface

# --- the benchmark configuration --------------------------------------------------------------


@dataclass(frozen=True)
class BenchPath:
    path: str
    start: float
    stop: float
    step: float
    n_values: int


# The five ranged paths of each side of lab-bench-10p (the same five on both); the spec fixes
# only their product, 2.87 × 10¹¹ cells (spec:1009): (12 · 12 · 14 · 14 · 19)² = 287,570,497,536.
_PER_SIDE = (
    ("indicators.ema.length", 5.0, 60.0, 5.0, 12),
    ("indicators.sma.length", 20.0, 130.0, 10.0, 12),
    ("indicators.rsi.length", 7.0, 20.0, 1.0, 14),
    ("indicators.macd.params.slow", 20.0, 46.0, 2.0, 14),  # an integer MACD parameter
    ("stop_loss_pct", 1.0, 10.0, 0.5, 19),  # a side level
)
BENCH_SURFACE: tuple[BenchPath, ...] = tuple(
    BenchPath(f"{side}_side.{path}", start, stop, step, n_values)
    for side in ("long", "short")
    for path, start, stop, step, n_values in _PER_SIDE
)

# §9.6a, Track A (result exploration), p95 over `runs` of each interaction, HTTP through the
# scratch worker, 1,000,000 completed trials.
TRACK_A_BUDGETS_MS = {
    "open": 1500,
    "open_cold": 4000,
    "filter_heatmap": 400,
    "stat_change": 300,
    "page": 600,
    "exact_slice": 300,
    "parallel": 800,
    "progress_poll": 100,
    "pareto": 800,  # two objectives
    "neighbourhood": 150,  # one trial's, or one candidate's robustness
}
# §9.6a, the importance analytics task (spec:1145): in total, and its fine-grid stage, measured by
# `analytics` beside a running job on the 1M fixture (10 parameters, no blocks).
TRACK_ANALYTICS_LIMITS = {"importance_task_s": 180.0, "fine_stage_s": 30.0}
# What the 1M fixtures cannot give, each row with its owner (the record's `not_measured`).
ANALYTICS_NOT_MEASURED = [
    {
        "row": "the importance task at d = 20 and K = 20 blocks (§9.4's 180 s budget at its stated scale)",
        "why": "the 1M fixtures have 10 parameters and no blocks, so the per-block mains (stage 2's "
        "K x 200 cheap passes) and the d = 20 cost are not measured here; the task is a "
        "10-parameter, 50,000-row one",
        "owner": "Phase 4's 20-parameter fixture (the Task 13 R3.5 note states the budget unmeasured "
        "at its scale until then)",
    },
    {
        "row": "the robustness ranking and a candidate's view at d = 20 (the cache entry, the "
        "840 probes at m = 2)",
        "why": "the fixtures have 10 parameters",
        "owner": "Phase 4's 20-parameter fixture",
    },
    {
        "row": "the Pareto all-on-front worst case",
        "why": "not constructible over HTTP: a metric cannot be named twice (the view refuses "
        "`an objective is named twice`) and no pair of the fixture's metrics is anti-correlated; "
        "the widest front among all pairs is recorded as `pareto_widest` instead",
        "owner": "R3.5 (a synthetic anti-correlated fixture) or the Pareto unit tests",
    },
    {
        "row": "the `opt:` source's importance poll at MAX_CELLS over HTTP",
        "why": "needs a finished 100,000-cell grid job in the store; `opt_frame_rebuild` is an "
        "in-process proxy for the per-poll frame rebuild, without the view on top of it",
        "owner": "R3.5",
    },
    {
        "row": "plan against actual at K = 20 blocks",
        "why": "the blocked run is K = 4",
        "owner": "Task 2's price model; an R3.5 finding",
    },
]
RECORDED_OPERATIONS = ("rankings", "convergence", "pareto_3")  # timed, never judged (no §9.6a line)
WIDE_VALUES = 20  # values per parameter of the second pass's fixture
BLOCKED_K = 4  # the screening blocks of the plan-against-actual run
LAB_TICK_S = 2.0  # the Lab's own refresh tick, which the importance poll's cadence is set against
QUIET_BASIS = (
    "case A alone on the idle worker: steady rows over the run's chunks, its first chunk left "
    "out; a whole-run rate, with the run's start-up gap and its compaction pause in it"
)
QUIET_MATCHED_BASIS = (
    "the quiet run's chunks at the same positions (indices in commit order) as the loaded "
    "window's, read by the loaded rate's own rule (the window's first chunk left out, rows over "
    "the seconds between its first and last chunk)"
)
QUIET_BY_TIME_BASIS = (
    "the quiet run's chunks at the same offsets from its creation as the task's window sat from "
    "the loaded run's; a start-up gap landing at the window's edge moves it across the window"
)
# The task is measured beside a job when the job's runs cover at least this share of its window.
BESIDE_JOB_MIN_COVERAGE = 0.9
ANALYTICS_POLL_S = 0.5  # the importance view, polled as the Lab polls it (every 2 s), faster
ANALYTICS_TASK_TIMEOUT_S = 900.0  # five times the budget: past it the task is cancelled
ANALYTICS_MAX_RUNS = 12  # case A runs, back to back, at most (the task is done long before)
# §9.6a resources (spec:1151-1154): the worker's additional memory with the 1M experiment open,
# the <id>.cells folder, the finalize-style compaction at 1M rows and the browser tab's heap,
# which explore (HTTP only) never sees: the walk measures it on the 12,000-trial slice.
TRACK_A_LIMITS = {
    "worker_rss_delta_mb": 450.0,
    "disk_mb": 350.0,
    "compaction_1m_s": 10.0,
    "browser_heap_mb": 300.0,
}


@dataclass(frozen=True)
class BenchCase:
    timeframe: str
    start: date
    end: date
    trials: int
    bars_nominal: int


# §9.1b's configurations verbatim (spec:1008), never re-cut: a matched bar count on another
# timeframe changes the trade counts and the fixed per-trial cost the §9.6b thresholds were set
# against. (QQQ 1D over the whole archive is ≈ 2,516 bars, not 2,603: a 1D reading would be a
# separate labelled case, never A.)
BENCH_CASES = {
    "A": BenchCase("1h", date(2024, 1, 1), date(2025, 6, 30), 10_000, 2_603),
    "B": BenchCase("15m", date(2024, 1, 1), date(2025, 6, 30), 10_000, 9_669),
    "C": BenchCase("1m", date(2025, 1, 1), date(2025, 6, 30), 2_000, 46_034),
    "A100k": BenchCase("1h", date(2024, 1, 1), date(2025, 6, 30), 100_000, 2_603),
}
# §9.6b, Track B (trial execution): steady trials / s by case label.
TRACK_B_THRESHOLDS = {"A": 150.0, "B": 65.0, "C": 19.0, "A100k": 71.0}
# §9.6b's other rows. worker_peak_mb is (base, per bar): 160 + 400e-6 × bars over the pool
# children (the pool's own model); bars_drift = |bars − bars_nominal| / bars_nominal.
TRACK_B_LIMITS = {
    "first_chunk_s_le_10k_bars": 20.0,
    "first_chunk_s_50k_bars": 35.0,
    "chunk_write_ms_p95": 100.0,
    "host_growth_mb": 100.0,
    "compaction_s": 10.0,
    "invalid": 0,
    "failed": 0,
    "query_throughput_ratio_min": 0.75,
    "query_p95_ratio_max": 2.5,
    "progress_poll_ms_p95": 100.0,
    "worker_peak_mb": (160.0, 400e-6),
    "bars_drift_max": 0.02,
}

HTTP_BASIS = "http (scratch worker)"
INPROCESS_BASIS = "in-process (no HTTP)"
ABSENT = "absent"
NOT_AT_R3 = "not run at R3"
DEFERRED_PAST_R3 = ("A100k",)  # runs at the milestone (§11, §16; decision 9)
CASE_MEASURES = (
    "trials_per_s",
    "first_chunk_s",
    "chunk_write_ms_p95",
    "host_growth_mb",
    "compaction_s",
    "invalid",
    "failed",
    "worker_peak_mb",
    "bars_drift",
    "progress_poll_ms_p95",
)
RETEST_KEYS = (
    "engine_build_changed",
    "surface_larger",
    "bars_over_50k",
    "new_kind",
    "rate_drift_over_15pct",
    "free_memory_under_2gb",
    "new_host",
)
MB = 1_000_000  # every *_mb is decimal megabytes, as the pool's own memory model counts them
PRODUCT_PORT = 8102
FINAL = ("done", "cancelled", "failed")
COMPACTION_ROWS = 10_000  # the compaction proxy's chunks: 50 of CHUNK_CELLS rows
PAGE_ROWS = 500


def bench_strategy() -> StrategySpec:
    """lab-bench-10p (§9.1b): on each side four indicators (EMA, SMA, RSI, MACD), an entry of
    three conditions, an exit of two, a stop and a target; commission 1.0 per side, slippage
    5 bps. Its ten ranged paths and their ranges are BENCH_SURFACE."""

    def side(direction: Direction) -> StrategySide:
        long = direction is Direction.LONG
        above, below = (
            ("crosses_above", "crosses_below") if long else ("crosses_below", "crosses_above")
        )
        more, less = ("greater_than", "less_than") if long else ("less_than", "greater_than")
        return StrategySide(
            direction=direction,
            indicators=[
                IndicatorSpec(id="ema", kind="EMA", length=9),
                IndicatorSpec(id="sma", kind="SMA", length=30),
                IndicatorSpec(id="rsi", kind="RSI", length=14),
                IndicatorSpec(
                    id="macd", kind="MACD", length=12, params={"slow": 26.0, "signal": 9.0}
                ),
            ],
            entry=RuleGroup(
                all_of=[
                    RuleSpec(left="ema", operator=above, right="sma"),
                    RuleSpec(left="rsi", operator=more, right="50"),
                    RuleSpec(left="macd.histogram", operator=more, right="0"),
                ]
            ),
            exit=RuleGroup(
                any_of=[
                    RuleSpec(left="ema", operator=below, right="sma"),
                    RuleSpec(left="rsi", operator=less, right="30" if long else "70"),
                ]
            ),
            stop_loss_pct=2.0,
            take_profit_pct=4.0,
        )

    return StrategySpec(
        id="lab-bench-10p",
        name="Lab benchmark: ten parameters, both sides, costed",
        description="EMA/SMA cross gated by RSI and MACD histogram, stop and target, both sides.",
        long_side=side(Direction.LONG),
        short_side=side(Direction.SHORT),
        temporal=default_strategy().temporal,
        execution=ExecutionSpec(commission_per_side=1.0, slippage_bps=5.0),
    )


def bench_surface() -> Surface:
    """The Surface over BENCH_SURFACE (imported here: see the module docstring)."""
    from products.aegis.surface import Parameter, Surface

    return Surface(
        parameters=[
            Parameter(path=p.path, start=p.start, stop=p.stop, step=p.step) for p in BENCH_SURFACE
        ]
    )


# --- refusals ---------------------------------------------------------------------------------


class Refusal(SystemExit):
    """SystemExit(2) naming what was refused (`str()` is the message; `main` prints it)."""

    def __init__(self, message: str) -> None:
        super().__init__(2)
        self.message = message

    def __str__(self) -> str:
        return self.message


def product_root() -> Path:
    """The product store: the main checkout's `data/aegis`, even from a worktree. The walk's
    PRODUCT_ROOT rule, re-derived here on purpose (the walk imports this module, never the
    other way round)."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(common).parent / "data" / "aegis"


def _port(base: str) -> int:
    parts = urlsplit(base)
    return parts.port or (443 if parts.scheme == "https" else 80)


def health_url(base: str) -> str:
    parts = urlsplit(base)
    return f"{parts.scheme}://{parts.netloc}/health/live"


def health_live(base: str) -> dict:
    """The worker's /health/live (its app_root and data_root); a Refusal when it does not
    answer, since then nothing proves it is not the product worker."""
    url = health_url(base)
    parts = urlsplit(url)
    try:
        connection = http.client.HTTPConnection(parts.hostname, _port(url), timeout=10)
        connection.request("GET", parts.path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
    except OSError as exc:
        raise Refusal(f"refused: no /health/live answer from {url}: {exc}") from exc
    if response.status != 200:
        raise Refusal(f"refused: /health/live of {url} answered HTTP {response.status}")
    return json.loads(body)


def refuse_product_targets(data_root: Path | None, base: str | None) -> None:
    """Refuse the product store as the data root, and a worker on the product port or one whose
    /health/live names the product store; SystemExit(2) naming which."""
    store = product_root().resolve()
    if data_root is not None and Path(data_root).resolve() == store:
        raise Refusal("refused: --data-root is the product root; pass --data-root <scratch>")
    if base is None:
        return
    if _port(base) == PRODUCT_PORT:
        raise Refusal(f"refused: the worker on port {PRODUCT_PORT} is the product worker")
    served = health_live(base).get("data_root")
    if not served:
        raise Refusal(f"refused: /health/live of {base} names no data_root")
    if Path(served).resolve() == store:
        raise Refusal("refused: the worker's data_root is the product root")


def _require_worker_root(base: str, data_root: Path) -> dict:
    """The worker must serve `data_root`: the fixture is written there and its files read."""
    live = health_live(base)
    served = live.get("data_root")
    if not served or Path(served).resolve() != Path(data_root).resolve():
        raise Refusal(f"refused: --data-root {data_root} is not the worker's data_root {served}")
    return live


# --- the host record --------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _cpu() -> dict:
    name = platform.processor()
    try:
        import winreg

        key = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            name = str(winreg.QueryValueEx(handle, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError):
        pass
    return {"name": name, "logical": os.cpu_count()}


def _memory() -> tuple[int, int]:
    """(total, available) physical bytes (GlobalMemoryStatusEx, the pool's own struct)."""
    import ctypes

    from products.aegis.pool import _MemoryStatus

    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def throttling_state(pid: int) -> str | None:
    """A process's explicit power-throttling state for execution speed
    (GetProcessInformation, ProcessPowerThrottling): `never throttled` (opted out),
    `throttled` (opted in) or `system managed`; None when it cannot be read."""
    import ctypes
    from ctypes import wintypes

    class State(ctypes.Structure):
        _fields_ = [
            ("Version", ctypes.c_uint32),
            ("ControlMask", ctypes.c_uint32),
            ("StateMask", ctypes.c_uint32),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            state = State(1, 0, 0)
            if not kernel32.GetProcessInformation(
                handle, 4, ctypes.byref(state), ctypes.sizeof(state)
            ):
                return None
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError):  # not Windows, or too old for the call
        return None
    if not state.ControlMask & 1:
        return "system managed"
    return "throttled" if state.StateMask & 1 else "never throttled"


def host_record() -> dict:
    """The host and the build a record was measured on (§9.1c: what a re-run compares)."""
    from importlib import metadata

    from products.aegis.experiments import CURVES_LIMIT
    from products.aegis.lab import identity
    from products.aegis.pool import default_workers

    def version(package: str) -> str | None:
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return None

    total, free = _memory()
    spec = bench_strategy()
    sides = (spec.long_side, spec.short_side)
    return {
        "cpu": _cpu(),
        "ram_gb": round(total / 1e9, 1),
        "free_memory_gb_at_start": round(free / 1e9, 2),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "numba": version("numba"),
        "numpy": version("numpy"),
        "pyarrow": version("pyarrow"),
        "engine_build": identity.engine_build(),
        "git_head": _git("rev-parse", "HEAD"),
        "app_root": str((ROOT / "app").resolve()),
        "workers": default_workers(),
        # this benchmark process (it runs the in-process measurements); the worker's own and a
        # pool child's states are in the record's `worker` section
        "power_throttling": {"host": throttling_state(os.getpid()), "child": None},
        "curves_kept": {label: case.trials <= CURVES_LIMIT for label, case in BENCH_CASES.items()},
        "measured_at": datetime.now(UTC).isoformat(),
        "indicators_per_side": max(len(side.indicators) for side in sides),
        "ranged_parameters": len(BENCH_SURFACE),
        "bars_max": max(case.bars_nominal for case in BENCH_CASES.values()),
        "kinds": sorted({i.kind for side in sides for i in side.indicators}),
    }


def new_record(mode: str) -> dict:
    """A record's head: the mode, the host, the engine build and the commit, and the sections its
    measurements go in (`operations` for explore, `cases` for execute, both for analytics: the
    two views' timings and the quiet and loaded runs)."""
    host = host_record()
    record = {
        "mode": mode,
        "host": host,
        "engine_build": host["engine_build"],
        "git_head": host["git_head"],
        "measured_at": host["measured_at"],
    }
    for section in {"explore": ("operations",), "analytics": ("operations", "cases")}.get(
        mode, ("cases",)
    ):
        record[section] = {}
    return record


# --- evaluation and the re-test triggers ------------------------------------------------------


def _at_most(value, limit) -> bool | str:
    return ABSENT if value is None else bool(value <= limit)


def _at_least(value, limit) -> bool | str:
    return ABSENT if value is None else bool(value >= limit)


def _evaluate_explore(record: dict) -> dict[str, bool | str]:
    out: dict[str, bool | str] = {}
    proxy = record.get("basis") == INPROCESS_BASIS  # no latency row is evaluated from a proxy
    operations = record.get("operations") or {}
    for key, budget in TRACK_A_BUDGETS_MS.items():
        measured = (operations.get(key) or {}).get("http_ms") or {}
        out[key] = ABSENT if proxy else _at_most(measured.get("p95"), budget)
    resources = record.get("resources") or {}
    for key, limit in TRACK_A_LIMITS.items():
        # explore is HTTP-only and never sees a browser: the heap row is the walk's
        out[key] = ABSENT if key == "browser_heap_mb" else _at_most(resources.get(key), limit)
    return out


def _evaluate_case(label: str, case: dict) -> dict[str, bool | str]:
    limits = TRACK_B_LIMITS
    bars = case.get("bars")
    nominal = case.get("bars_nominal") or BENCH_CASES[label].bars_nominal
    if bars is None:
        first_chunk, peak = ABSENT, ABSENT
    else:
        key = "first_chunk_s_le_10k_bars" if bars <= 10_000 else "first_chunk_s_50k_bars"
        first_chunk = _at_most(case.get("first_chunk_s"), limits[key])
        base, per_bar = limits["worker_peak_mb"]
        peak = _at_most(case.get("worker_peak_mb"), base + per_bar * bars)
    drift = None if bars is None else abs(bars - nominal) / nominal
    verdict = {
        "trials_per_s": _at_least(case.get("trials_per_s"), TRACK_B_THRESHOLDS[label]),
        "first_chunk_s": first_chunk,
        "chunk_write_ms_p95": _at_most(
            case.get("chunk_write_ms_p95"), limits["chunk_write_ms_p95"]
        ),
        "host_growth_mb": _at_most(case.get("host_growth_mb"), limits["host_growth_mb"]),
        "compaction_s": _at_most(case.get("compaction_s"), limits["compaction_s"]),
        "invalid": _at_most(case.get("invalid"), limits["invalid"]),
        "failed": _at_most(case.get("failed"), limits["failed"]),
        "worker_peak_mb": peak,
        "bars_drift": _at_most(drift, limits["bars_drift_max"]),
        "progress_poll_ms_p95": _at_most(
            case.get("progress_poll_ms_p95"), limits["progress_poll_ms_p95"]
        ),
    }
    return {f"{label}.{measure}": verdict[measure] for measure in CASE_MEASURES}


def _evaluate_execute(record: dict) -> dict[str, bool | str]:
    out: dict[str, bool | str] = {}
    cases = record.get("cases") or {}
    for label in TRACK_B_THRESHOLDS:
        case = cases.get(label)
        if case is None:
            missing = NOT_AT_R3 if label in DEFERRED_PAST_R3 else ABSENT
            out.update({f"{label}.{measure}": missing for measure in CASE_MEASURES})
        else:
            out.update(_evaluate_case(label, case))
    queries = record.get("with_queries") or {}
    out["query_throughput_ratio"] = _at_least(
        queries.get("query_throughput_ratio"), TRACK_B_LIMITS["query_throughput_ratio_min"]
    )
    out["query_p95_ratio"] = _at_most(
        queries.get("query_p95_ratio"), TRACK_B_LIMITS["query_p95_ratio_max"]
    )
    return out


def _evaluate_analytics(record: dict) -> dict[str, bool | str]:
    """The task's two lines (its total, its fine-grid stage), `absent` unless it was measured
    beside a running job (a task on an idle worker proves nothing about one beside a job), and
    the two views' §9.6a budgets (Pareto, neighbourhood). The job's throughput loss is recorded,
    never judged: the spec sets no line for it."""
    task = record.get("task") or {}
    wide = (record.get("wide") or {}).get("task") or {}
    out: dict[str, bool | str] = {}
    for key, limit in TRACK_ANALYTICS_LIMITS.items():
        measured = task.get("task_s" if key == "importance_task_s" else key)
        out[key] = _at_most(measured, limit) if task.get("beside_job") is True else ABSENT
    wide_beside = wide.get("beside_job") is True  # the second pass: 20 values per parameter
    out["fine_stage_20_s"] = (
        _at_most(wide.get("fine_stage_s"), TRACK_ANALYTICS_LIMITS["fine_stage_s"])
        if wide_beside
        else ABSENT
    )
    operations = record.get("operations") or {}
    for key, row in (
        ("pareto", "pareto"),
        ("neighbourhood", "neighbourhood"),
        (
            "candidate",
            "neighbourhood",
        ),  # §9.6a's one row: "neighbourhood of one trial / robustness of one candidate"
    ):
        measured = (operations.get(key) or {}).get("http_ms") or {}
        out[key] = _at_most(measured.get("p95"), TRACK_A_BUDGETS_MS[row])
    return out


def evaluate_basis(record: dict) -> dict[str, str]:
    """What each verdict of an analytics record rests on, in words, the fine stage's bound named:
    stage 1 is read by a poll only when it is the latest stage delivered, so the stage a poll
    first reads (stage 2) bounds it from above."""

    def fine(task: dict, what: str) -> str:
        if task.get("fine_stage_is_bound"):
            return (
                f"{what}: an upper bound, not a measurement: stage 1 finished before the first "
                "poll that read a stage, so the first stage read bounds it from above (a pass is "
                "sound, a fail would be conservative)"
            )
        return f"{what}: measured, stage 1's own server elapsed_s"

    task = record.get("task") or {}
    wide = (record.get("wide") or {}).get("task") or {}
    limit = TRACK_A_BUDGETS_MS["neighbourhood"]
    return {
        "importance_task_s": "stage 3's server elapsed_s, the whole task from before its frame "
        "opened, measured beside a job (absent otherwise)",
        "fine_stage_s": fine(task, "the fine-grid stage at the 1M fixture's value counts"),
        "fine_stage_20_s": fine(
            wide, "the fine-grid stage at 20 values per parameter, 10 parameters"
        ),
        "pareto": f"p95 of the HTTP runs, two objectives, cold first included, against {TRACK_A_BUDGETS_MS['pareto']} ms",
        "neighbourhood": f"p95 of the HTTP runs of one trial's neighbourhood against {limit} ms",
        "candidate": f"p95 of the HTTP runs of one candidate's robustness view (A plus B's region "
        f"read, the importance result live) against the {limit} ms of §9.6a's row "
        "'neighbourhood of one trial / robustness of one candidate'",
    }


def evaluate(record: dict) -> dict[str, bool | str]:
    """One key per threshold or budget of the record's mode: True / False when measured,
    `absent` when not (always for an explore record's `browser_heap_mb`, and for every latency
    row of a record whose basis is `in-process (no HTTP)`), `not run at R3` for A100k; a bar
    count off its configuration is False, never absent."""
    mode = record.get("mode")
    if mode == "explore":
        return _evaluate_explore(record)
    if mode == "execute":
        return _evaluate_execute(record)
    if mode == "analytics":
        return _evaluate_analytics(record)
    raise ValueError(f"unknown record mode {mode!r}")


# The cases of an analytics record that are series derived from its runs, not runs: the loaded
# window and the quiet baselines read at the loaded window's chunks or offsets. They move with a
# window's alignment, so §9.1c's rate-drift trigger does not read them.
DERIVED_CASES = (
    "loaded",
    "quiet_matched",
    "quiet_after_matched",
    "quiet_matched_by_time",
    "quiet_after_matched_by_time",
)


def _rates(record: dict) -> dict[str, float]:
    return {
        label: case["trials_per_s"]
        for label, case in (record.get("cases") or {}).items()
        if case.get("trials_per_s") and label not in DERIVED_CASES
    }


def _bars_max(record: dict) -> int:
    measured = [case.get("bars") or 0 for case in (record.get("cases") or {}).values()]
    return max([*measured, (record.get("host") or {}).get("bars_max") or 0])


def retest_due(record: dict, previous: dict | None) -> dict[str, bool]:
    """§9.1c's re-run triggers (spec:1050). Without a previous record every trigger is due
    except the free-memory one, which reads this record alone."""
    host = record.get("host") or {}
    free = host.get("free_memory_gb_at_start")
    memory = free is not None and free < 2.0
    if previous is None:
        return {key: True for key in RETEST_KEYS} | {"free_memory_under_2gb": memory}
    before = previous.get("host") or {}
    now_rates, old_rates = _rates(record), _rates(previous)
    drift = any(
        abs(now_rates[label] - old_rates[label]) / old_rates[label] > 0.15
        for label in now_rates.keys() & old_rates.keys()
    )
    return {
        "engine_build_changed": record.get("engine_build") != previous.get("engine_build"),
        "surface_larger": (host.get("indicators_per_side") or 0) > 4
        or (host.get("ranged_parameters") or 0) > 10,
        "bars_over_50k": _bars_max(record) > 50_000,
        "new_kind": bool(set(host.get("kinds") or ()) - set(before.get("kinds") or ())),
        "rate_drift_over_15pct": drift,
        "free_memory_under_2gb": memory,
        "new_host": any(host.get(key) != before.get(key) for key in ("cpu", "os", "ram_gb")),
    }


# --- HTTP and the worker's processes ----------------------------------------------------------


class _Http:
    """JSON over one kept-alive connection to the worker (as a browser keeps one). Not shared
    between threads: each thread opens its own."""

    def __init__(self, base: str) -> None:
        parts = urlsplit(base)
        self.host, self.port = parts.hostname, _port(base)
        self.prefix = parts.path.rstrip("/") + "/"
        self._connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = http.client.HTTPConnection(self.host, self.port, timeout=600)
        return self._connection

    def call(self, method: str, path: str, body: dict | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        for attempt in (0, 1):
            connection = self._connect()
            try:
                connection.request(method, self.prefix + path, body=payload, headers=headers)
                response = connection.getresponse()
                data = response.read()
                break
            except (http.client.RemoteDisconnected, ConnectionError):
                connection.close()
                self._connection = None
                if attempt:
                    raise
        if response.status >= 400:
            raise RuntimeError(f"{method} {path}: HTTP {response.status}: {data[:2000]!r}")
        return json.loads(data) if data else None

    def get(self, path: str) -> Any:
        return self.call("GET", path)

    def post(self, path: str, body: dict) -> Any:
        return self.call("POST", path, body)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _powershell(script: str) -> str:
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"powershell failed ({done.returncode}): {done.stderr[-2000:]}")
    return done.stdout.strip()


# One sample of the worker: the listener on the port (Get-NetTCPConnection; the pid file holds
# the venv launcher stub, whose child is the listener), its working set (Get-Process) and every
# process whose parent is the listener (Win32_Process: the pool's children).
_SAMPLE = (
    '$rows = @(Get-CimInstance Win32_Process -Filter "ProcessId = $l OR ParentProcessId = $l"'
    " | Select-Object ProcessId, ParentProcessId, Name, WorkingSetSize); "
    "$p = Get-Process -Id $l -ErrorAction SilentlyContinue; "
    "ConvertTo-Json -Compress -Depth 4 -InputObject @{listener = $l; "
    "working_set = $(if ($p) { $p.WorkingSet64 } else { $null }); rows = $rows}"
)


def _listener_pid(port: int) -> int | None:
    out = _powershell(
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue"
        " | Select-Object -First 1 -ExpandProperty OwningProcess)"
    )
    return int(out) if out.isdigit() else None


def _decode_sample(text: str) -> dict:
    raw = json.loads(text)
    rows = raw.get("rows") or []
    rows = rows if isinstance(rows, list) else [rows]
    listener = int(raw["listener"])
    parent = next((r["ParentProcessId"] for r in rows if r["ProcessId"] == listener), None)
    children = [
        {"pid": int(r["ProcessId"]), "working_set": int(r["WorkingSetSize"] or 0)}
        for r in rows
        if r["ParentProcessId"] == listener and str(r["Name"]).lower() == "python.exe"
    ]
    return {
        "listener": listener,
        "parent": parent,
        "working_set": raw.get("working_set"),
        "children": children,
    }


def worker_sample(listener: int) -> dict:
    return _decode_sample(_powershell(f"$l = {listener}; " + _SAMPLE))


def worker_process(base: str, pid_file: Path) -> dict:
    """The scratch worker's listener, checked against the pid file: the listener is the pid
    file's process or its child (never another worker that happens to hold the port)."""
    port = _port(base)
    listener = _listener_pid(port)
    if listener is None:
        raise SystemExit(f"nothing listens on port {port}")
    if not pid_file.is_file():
        raise Refusal(f"refused: no pid file {pid_file} names the scratch worker")
    stub = int(pid_file.read_text(encoding="utf-8").strip())
    sample = worker_sample(listener)
    if stub not in (listener, sample["parent"]):
        raise Refusal(
            f"refused: the listener on port {port} (pid {listener}) is neither the pid file's "
            f"process {stub} nor its child"
        )
    return {"port": port, "listener_pid": listener, "pid_file": str(pid_file), "pid_file_pid": stub}


class _Sampler:
    """The worker sampled every second by one long-running PowerShell loop (a process per
    sample would cost the measured job a start-up each second): the listener's working set and
    every pool child's, kept as maxima."""

    def __init__(self, listener: int) -> None:
        self.listener = listener
        self.samples = 0
        self.listener_max: int | None = None
        self.children: dict[int, int] = {}
        self.pool_size = 0  # the most pool children alive at once: the observed pool
        self.child_throttling: str | None = None  # read while a pool child is alive
        script = f"$l = {listener}; while ($true) {{ {_SAMPLE}; Start-Sleep -Milliseconds 1000 }}"
        self._process = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            try:
                sample = _decode_sample(line)
            except (ValueError, KeyError, TypeError):
                continue
            self.samples += 1
            if sample["working_set"] is not None:
                self.listener_max = max(self.listener_max or 0, int(sample["working_set"]))
            self.pool_size = max(self.pool_size, len(sample["children"]))
            for child in sample["children"]:
                pid, ws = child["pid"], child["working_set"]
                self.children[pid] = max(self.children.get(pid, 0), ws)
                if self.child_throttling is None:
                    self.child_throttling = throttling_state(pid)

    def stop(self) -> None:
        self._process.kill()
        self._process.wait(timeout=30)
        self._thread.join(timeout=30)


# --- measurement helpers ----------------------------------------------------------------------


def _p95(values: Sequence[float]) -> float | None:
    """Nearest rank: the smallest value with at least 95 % of the values at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _stats(samples: Sequence[float]) -> dict:
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "p50": round(ordered[(len(ordered) - 1) // 2], 3),
        "p95": round(_p95(ordered), 3),
        "max": round(ordered[-1], 3),
        "samples": [round(value, 3) for value in samples],
    }


def _folder_bytes(folder: Path) -> int:
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


Step = tuple[str, str, dict | None]


def _operations(
    document, total: int, seed: int, *, task_seed: int = 1, pool: Sequence[str] | None = None
) -> dict[str, Callable[[int], list[Step]]]:
    """§9.6a's interactions as the requests the UI issues for them, per run, and the recorded rows
    beside them (`RECORDED_OPERATIONS`). With a ranking's `pool` of trial ids, also `candidate`:
    one candidate's robustness view, a different trial of the pool each run, B reading the
    importance result of `task_seed`."""
    paths = [p.path for p in document.surface.parameters]
    values = {p.path: p.values() for p in document.surface.parameters}
    objective = document.objective
    lab = f"lab/{quote(f'exp:{document.id}', safe=':')}"
    matrix = {
        "view": "matrix",
        "rows": paths[0],
        "cols": paths[1],
        "metric": objective,
        "mode": "aggregate",
    }
    two_ranges = {
        "ranges": {path: [values[path][1], values[path][-2]] for path in paths[2:4]},
    }
    middle = values[paths[2]][len(values[paths[2]]) // 2]
    offsets = np.random.default_rng(seed).integers(0, max(1, total - PAGE_ROWS), size=4096)
    # The neighbourhood's trials: seeded, one a run (every trial of the fixture completed), so no
    # run is the previous one's answer again.
    candidates = np.random.default_rng([seed, 7_000_007]).integers(0, max(1, total), size=4096)

    def query(flt: dict | None = None, **body) -> Step:
        return ("POST", f"{lab}/query", {"filter": flt or {}, **body})

    picks = None
    if pool:
        picks = np.random.default_rng([seed, 9_000_009]).permutation(len(pool))
    operations = {
        "open": lambda i: [
            ("GET", f"{lab}/summary", None),
            query(**matrix),
            query(view="page", offset=0, limit=PAGE_ROWS),
        ],
        "filter_heatmap": lambda i: [query(two_ranges, **matrix), query(two_ranges, view="counts")],
        "stat_change": lambda i: [query(**matrix | {"stat": "median"})],
        "page": lambda i: [
            query(view="page", offset=int(offsets[i % len(offsets)]), limit=PAGE_ROWS)
        ],
        "exact_slice": lambda i: [query(**matrix | {"mode": "exact", "fixed": {paths[2]: middle}})],
        "parallel": lambda i: [query(view="parallel", axes=paths[:6], metric=objective)],
        "progress_poll": lambda i: [("GET", f"experiments/{document.id}", None)],
        "pareto": lambda i: [
            query(view="pareto", objectives=[objective, "max_drawdown"])  # two objectives
        ],
        "neighbourhood": lambda i: [
            query(
                view="neighbourhood",
                trial=f"exp:{document.id}#{int(candidates[i % len(candidates)])}",
                metric=objective,
            )
        ],
        # Recorded beside them (`RECORDED_OPERATIONS`): no §9.6a line is stated for these.
        "pareto_3": lambda i: [
            query(view="pareto", objectives=[objective, "max_drawdown", "trade_count"])
        ],
        "convergence": lambda i: [query(view="convergence", metric=objective)],
        "rankings": lambda i: [
            query(view="robustness", metric=objective, seed=task_seed)  # pool 300, k 20
        ],
    }
    if picks is not None:
        operations["candidate"] = lambda i: [
            query(
                view="robustness",
                trial=pool[int(picks[i % len(picks)])],
                metric=objective,
                seed=task_seed,
            )
        ]
    return operations


def _timed(
    call: Callable[[str, str, dict | None], Any],
    operation,
    runs: int,
    basis: str,
    on_first: Callable[[], None] | None = None,
) -> dict:
    """`runs` runs of `operation`, each timed: the stats of all of them (the first included, which
    is cold on a fresh worker), the first apart as `cold_ms` and the rest as `warm_ms`. `on_first`
    is called once after the first run, outside its timing."""
    samples = []
    for i in range(runs):
        steps = operation(i)
        started = time.perf_counter()
        for method, path, body in steps:
            call(method, path, body)
        samples.append((time.perf_counter() - started) * 1000)
        if i == 0 and on_first is not None:
            on_first()
    key = "http_ms" if basis == "http" else "inprocess_ms"
    return {
        "basis": basis,
        key: _stats(samples),
        "cold_ms": round(samples[0], 3),
        "warm_ms": _stats(samples[1:]) if len(samples) > 1 else None,
        "requests": [f"{method} {path}" for method, path, _ in operation(0)],
    }


def _inprocess_caller(data_root: Path, experiment_id: str):
    """The Lab routes called in this process over a LabCache of its own: a proxy without HTTP,
    labelled so and never evaluated."""
    from products.aegis import api
    from products.aegis.experiments import ExperimentStore
    from products.aegis.lab.cache import LabCache
    from products.aegis.runs import JsonRunRepository

    store = ExperimentStore(JsonRunRepository(data_root))
    cache = LabCache()
    source = f"exp:{experiment_id}"

    def call(method: str, path: str, body: dict | None) -> Any:
        if path.endswith("/summary"):
            return api.lab_summary(source, runner=None, experiments=store, cache=cache)
        if path.endswith("/query"):
            request = api.QueryRequest.model_validate(body)
            return api.lab_query(source, request, runner=None, experiments=store, cache=cache)
        return store.get(experiment_id).model_dump(mode="json")

    return call


# --- explore (Track A) ------------------------------------------------------------------------


def fixture_id(trials: int, values: int | None = None) -> str:
    base = "demo-synthetic-1m" if trials == 1_000_000 else f"demo-synthetic-{trials}"
    return base if values is None else f"{base}-{values}v"


def _fixture(
    data_root: Path, experiment_id: str, trials: int, seed: int, values: int | None = None
):
    """The fixture under `data_root`: reused when it holds `trials` trials (and `values` lattice
    points on every parameter, when asked), written when absent. Returns (document, seconds spent
    writing it or None)."""
    import lab_fixture
    from products.aegis.experiments import ExperimentStore
    from products.aegis.runs import JsonRunRepository

    store = ExperimentStore(JsonRunRepository(data_root))
    try:
        document = store.get(experiment_id)
    except KeyError:
        document = None
    if document is not None:
        held = (document.counts or {}).get("scheduled")
        if held != trials:
            raise SystemExit(f"fixture {experiment_id} holds {held} trials, not {trials}")
        if values is not None and any(
            len(p.values()) != values for p in document.surface.parameters
        ):
            raise SystemExit(f"fixture {experiment_id} does not hold {values} values per parameter")
        return document, None
    cells = store.cells_dir(experiment_id)
    if cells.exists():
        raise SystemExit(
            f"fixture {experiment_id}: {cells} exists without its document (a torn write); "
            "remove it and run again"
        )
    started = time.perf_counter()
    document = lab_fixture.write_fixture(
        data_root, experiment_id=experiment_id, trials=trials, seed=seed, values=values
    )
    return document, round(time.perf_counter() - started, 3)


def _write_chunks(folder: Path, document, trial_nos: np.ndarray, first: int, seed: int) -> int:
    """CHUNK_CELLS-row layout-2 chunk files of synthetic trials, written as the job writes them
    (`_write_atomic` with the write time stamped), named from `first`; returns their count."""
    import lab_fixture
    from products.aegis.experiments import _write_atomic

    rng = np.random.default_rng([seed, 9_000_009])
    tables = lab_fixture.chunk_tables(document, trial_nos, rng, first_chunk=first)
    for index, table in enumerate(tables, start=first):
        _write_atomic(folder / f"{index:06d}.parquet", table, stamp_write_ms=True)
    return len(tables)


def _compaction_proxy(data_root: Path, document, seed: int) -> dict:
    """compaction_1m_s, in this process: the fixture's cells folder copied outside
    `experiments/` (the worker never serves it), 50 chunks of 200 rows written beside its parts,
    then `compact` (one new generation; `unique` recomputed over every part's param_key) and
    `reclaim` at once, as finalize does; the copy is removed afterwards."""
    from products.aegis.lab import store as lab_store

    source = data_root / "experiments" / f"{document.id}.cells"
    copy = data_root / "bench" / f"{document.id}.cells"
    if copy.exists():
        shutil.rmtree(copy)  # a copy an interrupted run left: this module's own folder
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, copy)
    try:
        manifest = lab_store.read_manifest(copy)
        parts = len(manifest.parts)
        first = lab_store.next_chunk_index(copy, manifest)
        scheduled = int(document.counts["scheduled"])
        trial_nos = np.arange(scheduled, scheduled + COMPACTION_ROWS, dtype=np.int64)
        chunks = _write_chunks(copy, document, trial_nos, first, seed)
        now = time.time()
        started = time.perf_counter()
        compacted = lab_store.compact(copy, now=now)
        merged = time.perf_counter()
        removed = lab_store.reclaim(copy, now=now, retain_seconds=0.0)
        done = time.perf_counter()
    finally:
        shutil.rmtree(copy, ignore_errors=True)
    return {
        "basis": "inprocess (a proxy for the job's own compaction, which runs inside the "
        "worker under its locks)",
        "s": round(done - started, 3),
        "compact_s": round(merged - started, 3),
        "reclaim_s": round(done - merged, 3),
        "parts": parts,
        "generation": compacted.generation,
        "chunks": chunks,
        "rows_merged": COMPACTION_ROWS,
        "reclaimed": len(removed),
        "unique": compacted.unique,
    }


def _compact_10k(data_root: Path, document, seed: int) -> dict:
    """Task 5's 10,000-row timings: 50 chunks of a synthetic layout-2 folder compacted into one
    part, then 7 projected columns read back through `read_latest`, first as a running job's
    periodic compaction leaves the folder (the merged chunks kept for the retention window),
    then once they are reclaimed (as finalize leaves it); the folder is removed."""
    from products.aegis.lab import store as lab_store

    folder = data_root / "bench" / "compact-10k.cells"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    paths = [p.path for p in document.surface.parameters][:4]
    columns = [*paths, f"combined.{document.objective}", "valid", "cell"]
    try:
        _write_chunks(folder, document, np.arange(COMPACTION_ROWS, dtype=np.int64), 0, seed)
        now = time.time()
        started = time.perf_counter()
        lab_store.compact(folder, now=now)
        compacted = time.perf_counter()
        read = lab_store.read_latest(folder, columns)
        finished = time.perf_counter()
        merged_on_disk = len(lab_store.readable_chunks(folder))
        lab_store.reclaim(folder, now=now, retain_seconds=0.0)
        reclaimed = time.perf_counter()
        lab_store.read_latest(folder, columns)
        reread = time.perf_counter()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {
        "basis": "inprocess",
        "compact_10k_s": round(compacted - started, 3),
        "read_7cols_10k_ms": round((finished - compacted) * 1000, 3),
        "merged_chunks_on_disk": merged_on_disk,
        "read_7cols_10k_after_reclaim_ms": round((reread - reclaimed) * 1000, 3),
        "rows": len(read.table),
        "columns": columns,
    }


def explore(
    data_root: Path,
    *,
    base: str,
    pid_file: Path,
    trials: int = 1_000_000,
    seed: int = 1,
    runs: int = 20,
    inprocess: bool = False,
) -> dict:
    """Track A: the fixture (written when absent), then each §9.6a interaction `runs` times over
    HTTP through the scratch worker serving `data_root`, the worker's memory before the first
    open and after the warm set, the folder's size, the compaction proxy and the 10,000-row
    timings; with `inprocess`, the same interactions through the routes in this process. Refuses
    the product store and the product worker before anything else, as `main` does."""
    refuse_product_targets(data_root, base)
    from trading_core.process_power import opt_out_of_power_throttling

    data_root = Path(data_root)
    opt_out_of_power_throttling()  # the in-process timings run here
    _require_worker_root(base, data_root)
    worker = worker_process(base, pid_file)
    experiment_id = fixture_id(trials)
    record = new_record("explore")
    document, written_s = _fixture(data_root, experiment_id, trials, seed)
    http_client = _Http(base)
    build = http_client.get("api/lab/build")
    cache_before = int(build["cache"]["entries"])
    record.update(
        {
            "basis": HTTP_BASIS,
            "base": base,
            "data_root": str(data_root),
            "experiment_id": experiment_id,
            "trials": trials,
            "parameters": len(document.surface.parameters),
            "seed": seed,
            "runs": runs,
            "fixture_write_s": written_s,
            "page_cache": "warm (fixture just written)" if written_s is not None else "unknown",
            "cache_entries_before": cache_before,
            "worker_engine_build": build["engine_build"],
            "worker": worker,
        }
    )
    listener = worker["listener_pid"]
    operations = _operations(document, trials, seed)
    before = worker_sample(listener)

    def over_http(method: str, path: str, body: dict | None) -> Any:
        return http_client.call(method, "api/" + path, body)

    timed = record["operations"]
    if cache_before == 0:  # the first open after a worker restart: nothing cached yet
        timed["open_cold"] = _timed(over_http, operations["open"], 1, "http")
    else:
        timed["open_cold"] = None
        record["open_cold_note"] = (
            f"the worker's Lab cache held {cache_before} entries: restart it for a cold open"
        )
    for name in TRACK_A_BUDGETS_MS:
        if name != "open_cold":
            timed[name] = _timed(over_http, operations[name], runs, "http")
    after = worker_sample(listener)
    for name in RECORDED_OPERATIONS:  # no §9.6a line: recorded, after the judged warm set
        timed[name] = _timed(over_http, operations[name], runs, "http")
    recorded = worker_sample(listener)
    http_client.close()
    record["worker"]["power_throttling"] = {"host": throttling_state(listener), "child": None}
    cells = data_root / "experiments" / f"{experiment_id}.cells"
    compaction = _compaction_proxy(data_root, document, seed)
    record["resources"] = {
        "worker_rss_delta_mb": round((after["working_set"] - before["working_set"]) / MB, 3),
        "worker_rss_delta_after_recorded_rows_mb": round(
            (recorded["working_set"] - before["working_set"]) / MB, 3
        ),
        "worker_working_set_mb": {
            "before_first_open": round(before["working_set"] / MB, 3),
            "after_warm_set": round(after["working_set"] / MB, 3),
            "after_recorded_rows": round(recorded["working_set"] / MB, 3),
        },
        "disk_mb": round(_folder_bytes(cells) / MB, 3),
        "compaction_1m_s": compaction["s"],
    }
    record["compaction"] = compaction
    record["storage_10k"] = _compact_10k(data_root, document, seed)
    record["compact_10k_s"] = record["storage_10k"]["compact_10k_s"]
    record["read_7cols_10k_ms"] = record["storage_10k"]["read_7cols_10k_ms"]
    if inprocess:
        call = _inprocess_caller(data_root, experiment_id)
        proxied = {"open_cold": _timed(call, operations["open"], 1, "inprocess")}  # a new cache
        for name in TRACK_A_BUDGETS_MS:
            if name != "open_cold":
                proxied[name] = _timed(call, operations[name], runs, "inprocess")
        record["inprocess_ms"] = {
            "basis": "inprocess (proxy: the Lab routes called in this process over a LabCache "
            "of its own, no HTTP; never evaluated)",
            "operations": proxied,
        }
    return record


# --- execute (Track B) ------------------------------------------------------------------------


def _experiment_body(
    label: str, case: BenchCase, strategy_id: str, stamp: str, blocks: int = 0
) -> dict:
    body = {
        "name": f"lab-bench {label} {stamp}",
        "strategy_id": strategy_id,
        "data": {
            "symbol": "QQQ",
            "timeframe": case.timeframe,
            "start": case.start.isoformat(),
            "end": case.end.isoformat(),
        },
        "objective": "net_pnl",
        "surface": bench_surface().model_dump(mode="json"),
        "budget": {"runs": case.trials},
        "seed": 1,
    }
    if blocks:
        body["blocks"] = blocks  # each configuration also scored on `blocks` periods (§7.3a)
    return body


def _write_ms(cells_dir: Path, seen: dict[str, float]) -> None:
    """Each chunk file's `aegis.write_ms` (the write up to its footer; the rename is not in it),
    read once per file while the file is still there (finalize reclaims merged chunks)."""
    import pyarrow.parquet as pq
    from products.aegis.experiments import WRITE_MS

    for path in cells_dir.glob("[0-9]*.parquet"):
        if path.name in seen:
            continue
        try:
            metadata = pq.read_metadata(path).metadata or {}
        except Exception:  # noqa: BLE001 - a chunk compacted and reclaimed meanwhile
            metadata = {}
        value = metadata.get(WRITE_MS.encode())
        if value is not None:
            seen[path.name] = float(value)


def _done_cells_s(store, experiment_id: str) -> float | None:
    from products.aegis.lab.store import SnapshotExpired

    for _ in range(3):  # a compaction between the manifest and the files: read again
        started = time.perf_counter()
        try:
            store.done_cells(experiment_id)
        except SnapshotExpired:
            continue
        return round(time.perf_counter() - started, 3)
    return None


def _chunk_times(cells_dir: Path) -> tuple[list[int], list[int], list[float]]:
    """(chunk index, rows, commit time in epoch seconds) per committed chunk, from the trials
    themselves (parts keep each row's `chunk` and `finished_at`)."""
    import pyarrow as pa
    from products.aegis.lab.store import read_latest

    table = read_latest(cells_dir, ["chunk", "finished_at"]).table
    chunk = np.asarray(table.column("chunk").to_numpy(), dtype=np.int64)
    finished = table.column("finished_at").cast(pa.int64()).to_numpy().astype(np.float64) / 1000
    indices, rows = np.unique(chunk, return_counts=True)
    times = [float(finished[chunk == index].max()) for index in indices]
    return indices.tolist(), rows.tolist(), times


def per_trial_cost(case: dict) -> dict:
    """§9.1b's affine model beside the measurement: `model_ms_per_trial = 27 + 0.0079 × bars`
    and the worker time one trial took, `pool_workers × 1000 / trials_per_s`, over the pool
    observed while the case ran (never the size the run expected: a pool of another size than
    `workers_expected` is named in `workers_mismatch`)."""
    bars, rate, pool = case.get("bars"), case.get("trials_per_s"), case.get("pool_workers")
    model = None if bars is None else 27 + 0.0079 * bars
    measured = pool * 1000 / rate if rate and pool else None
    cost = {
        "model_ms_per_trial": None if model is None else round(model, 3),
        "measured_worker_ms_per_trial": None if measured is None else round(measured, 3),
        "measured_to_model": None if measured is None or not model else round(measured / model, 3),
    }
    expected = case.get("workers_expected")
    if expected is not None and pool != expected:
        cost["workers_mismatch"] = f"expected {expected} workers; the pool ran {pool}"
    return cost


def _run_case(
    http_client: _Http,
    label: str,
    strategy_id: str,
    stamp: str,
    data_root: Path,
    listener: int,
    expected_workers: int,
    queries: _QueryLoad | _TaskLoad | None = None,
    blocks: int = 0,
) -> dict:
    """One §9.1b case through the worker's API, polled every second until it finishes; with
    `queries`, that load runs against this very experiment from its creation to its end."""
    from products.aegis.experiments import ExperimentStore
    from products.aegis.lab.store import read_manifest
    from products.aegis.runs import JsonRunRepository

    case = BENCH_CASES[label]
    store = ExperimentStore(JsonRunRepository(data_root))
    _, free = _memory()
    sampler = _Sampler(listener)
    try:
        host_before = worker_sample(listener)["working_set"]
        started = time.time()
        created = http_client.post(
            "api/experiments", _experiment_body(label, case, strategy_id, stamp, blocks)
        )
        experiment_id = created["experiment_id"]
        if created["job_id"] is None:
            raise SystemExit(f"another job is running on the worker: {experiment_id} is queued")
        if queries is not None:
            queries.start(f"exp:{experiment_id}")
        planned = int(created["plan"]["planned_runs"])
        cells_dir = data_root / "experiments" / f"{experiment_id}.cells"
        polls: list[float] = []
        write_ms: dict[str, float] = {}
        before_finalize = None
        final_at = None
        deadline = time.monotonic() + 1800 + case.trials * 0.1
        while True:
            tick = time.perf_counter()
            document = http_client.get(f"api/experiments/{experiment_id}")
            polls.append((time.perf_counter() - tick) * 1000)
            _write_ms(cells_dir, write_ms)
            if document["status"] in FINAL:
                final_at = time.time()
                break
            done = int((document.get("progress") or {}).get("cells_done") or 0)
            if before_finalize is None and done >= 0.9 * planned:
                before_finalize = {
                    "s": _done_cells_s(store, experiment_id),
                    "at_cells_done": done,
                    "chunk_files": len(list(cells_dir.glob("[0-9]*.parquet"))),
                    "parts": len(list(cells_dir.glob("part-*.parquet"))),
                }
            if time.monotonic() > deadline:
                raise SystemExit(f"{experiment_id} did not finish in time")
            time.sleep(max(0.0, 1.0 - (time.perf_counter() - tick)))
    finally:
        if queries is not None:
            queries.stop()
        sampler.stop()
    after_finalize = _done_cells_s(store, experiment_id)
    indices, rows, times = _chunk_times(cells_dir)
    steady_rows, steady_s = sum(rows[1:]), (times[-1] - times[0]) if len(times) > 1 else 0.0
    rate = steady_rows / steady_s if steady_s > 0 else None
    manifest = read_manifest(cells_dir)
    generations = manifest.generations if manifest else []
    compaction = [g["compaction_ms"] for g in generations if g.get("compaction_ms") is not None]
    counts = document.get("counts") or {}
    bars = int(document["plan"]["bars"])
    children = sampler.children
    if sampler.pool_size:
        pool, pool_source = sampler.pool_size, "sampled pool children (the most alive at once)"
    else:
        pool = document.get("workers")
        pool_source = "the document's workers (planned at creation; the job refits at start)"
    record = {
        "experiment_id": experiment_id,
        "status": document["status"],
        "blocks": blocks,
        "rate_unit": "evaluations" if blocks else "trials",  # a blocked trial is blocks + 1 rows
        "plan": {  # what the planner priced the run at, to set against `wall_s`
            key: created["plan"].get(key)
            for key in (
                "estimate_seconds",
                "ms_per_cell_bar",
                "workers",
                "evaluations",
                "price_source",
            )
        },
        "created_at": round(started, 3),  # epoch seconds: the job's interval, for `analytics`
        "final_at": None if final_at is None else round(final_at, 3),
        "timeframe": case.timeframe,
        "range": [case.start.isoformat(), case.end.isoformat()],
        "trials": case.trials,
        "planned_runs": planned,
        "bars": bars,
        "bars_nominal": case.bars_nominal,
        "bars_drift": round(abs(bars - case.bars_nominal) / case.bars_nominal, 5),
        "free_memory_gb_at_start": round(free / 1e9, 2),
        "workers_expected": expected_workers,
        "pool_workers": pool,
        "pool_workers_source": pool_source,
        "chunks": len(indices),
        "trials_per_s": None if rate is None else round(rate, 3),
        "first_chunk_s": round(times[0] - started, 3) if times else None,
        "wall_s": round(times[-1] - started, 3) if times else None,
        "chunk_write_ms_p95": None if not write_ms else round(_p95(list(write_ms.values())), 3),
        "chunk_write_ms_n": len(write_ms),
        "compaction_s": round(max(compaction) / 1000, 3) if compaction else None,
        "generations": len(generations),
        "resume_read_s": {"before_finalize": before_finalize, "after_finalize": after_finalize},
        "worker_peak_mb": round(max(children.values()) / MB, 3) if children else None,
        "pool_children": [
            {"pid": pid, "peak_working_set_mb": round(ws / MB, 3)} for pid, ws in children.items()
        ],
        "host_growth_mb": None
        if sampler.listener_max is None or host_before is None
        else round((sampler.listener_max - host_before) / MB, 3),
        "host_working_set_mb": {
            "before_job": None if host_before is None else round(host_before / MB, 3),
            "peak_during_job": None
            if sampler.listener_max is None
            else round(sampler.listener_max / MB, 3),
        },
        "samples": sampler.samples,
        "child_power_throttling": sampler.child_throttling,
        "invalid": counts.get("invalid"),
        "failed": counts.get("failed"),
        "completed": counts.get("completed"),
        "progress_poll_ms_p95": round(_p95(polls), 3),
        "progress_polls": len(polls),
    }
    record.update(per_trial_cost(record))
    return record


QUERY_RATE = 1  # requests per second, cycling through the set (§9.1b's cadence)
QUIET_REQUESTS = 20  # the quiet baseline's requests, after a warm-up cycle


def _query_set(source: str) -> list[tuple[str, Step]]:
    """§9.1b's query set against `source`, by name: the summary, a two-range counts, an
    aggregate matrix and the top 200 (the Lab's own routes, over every case's bench surface)."""
    surface = bench_surface().parameters
    lab = f"lab/{quote(source, safe=':')}"
    ranges = {p.path: [p.start, (p.start + p.stop) / 2] for p in surface[2:4]}
    matrix = {
        "view": "matrix",
        "rows": surface[0].path,
        "cols": surface[1].path,
        "metric": "net_pnl",
        "mode": "aggregate",
        "stat": "median",
    }
    return [
        ("summary", ("GET", f"{lab}/summary", None)),
        ("counts", ("POST", f"{lab}/query", {"filter": {"ranges": ranges}, "view": "counts"})),
        ("matrix", ("POST", f"{lab}/query", {"filter": {}, **matrix})),
        ("top", ("POST", f"{lab}/query", {"filter": {}, "view": "top", "k": 200})),
    ]


class _QueryLoad:
    """§9.1b's query set against one experiment, one request per second (`QUERY_RATE`) cycling
    through its four requests, on a connection of its own; a refused request (a snapshot
    expired under the running job, say) is counted in `errors`, never timed."""

    def __init__(self, base: str) -> None:
        self.http = _Http(base)
        self.steps: list[tuple[str, Step]] = []
        self.samples: list[tuple[str, float]] = []
        self.errors: list[str] = []
        self._next = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def one(self) -> tuple[str, float] | None:
        name, (method, path, body) = self.steps[self._next % len(self.steps)]
        self._next += 1
        started = time.perf_counter()
        try:
            self.http.call(method, "api/" + path, body)
        except (RuntimeError, OSError, http.client.HTTPException) as exc:
            self.errors.append(f"{name}: {exc}"[:300])
            return None
        return name, (time.perf_counter() - started) * 1000

    def run(self, count: int) -> list[tuple[str, float]]:
        """`count` requests at the same cadence, on the caller's thread."""
        samples = []
        for _ in range(count):
            started = time.perf_counter()
            sample = self.one()
            if sample is not None:
                samples.append(sample)
            time.sleep(max(0.0, 1.0 / QUERY_RATE - (time.perf_counter() - started)))
        return samples

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            sample = self.one()
            if sample is not None:
                self.samples.append(sample)
            self._stop.wait(max(0.0, 1.0 / QUERY_RATE - (time.perf_counter() - started)))

    def start(self, source: str) -> None:
        self.steps = _query_set(source)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=120)

    def close(self) -> None:
        self.http.close()


def _by_request(samples: list[tuple[str, float]]) -> dict:
    names = dict.fromkeys(name for name, _ in samples)
    return {name: _stats([ms for n, ms in samples if n == name]) for name in names}


def execute(
    base: str,
    *,
    cases: Sequence[str],
    pid_file: Path,
    data_root: Path,
    workers: int = 10,
) -> dict:
    """Track B: each case's experiment created through the scratch worker's API (lab-bench-10p,
    LHS over the 2.87 × 10¹¹-cell surface, budget = the case's trials, seed 1, QQQ at the
    case's timeframe and range) and measured while it runs; then, with case A, case A again
    while a thread sends §9.1b's query set against that running experiment, one request per
    second. `workers` is the pool size the run expects (the worker's own setting, never sent):
    the measured cost uses the pool observed, and a case whose pool differs says so. Refuses
    the product store and the product worker before anything else, as `main` does."""
    refuse_product_targets(data_root, base)
    from trading_core.process_power import opt_out_of_power_throttling

    data_root = Path(data_root)
    unknown = [label for label in cases if label not in BENCH_CASES]
    if unknown:
        raise SystemExit(f"unknown cases {unknown}; expected some of {list(BENCH_CASES)}")
    opt_out_of_power_throttling()
    _require_worker_root(base, data_root)
    worker = worker_process(base, pid_file)
    listener = worker["listener_pid"]
    record = new_record("execute")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    http_client = _Http(base)
    strategy = http_client.post(
        "api/strategies",
        {"name": f"lab-bench-10p-{stamp}", "spec": bench_strategy().model_dump(mode="json")},
    )
    record.update(
        {
            "base": base,
            "data_root": str(data_root),
            "workers_expected": workers,
            "strategy_id": strategy["id"],
            "worker": worker,
            "worker_engine_build": http_client.get("api/lab/build")["engine_build"],
            "basis": HTTP_BASIS,
        }
    )
    for label in cases:
        record["cases"][label] = _run_case(
            http_client, label, strategy["id"], stamp, data_root, listener, workers
        )
    if "A" in record["cases"]:
        quiet = record["cases"]["A"]
        load = _QueryLoad(base)
        try:
            loaded = _run_case(
                http_client,
                "A",
                strategy["id"],
                f"{stamp}-q",
                data_root,
                listener,
                workers,
                queries=load,
            )
            during = list(load.samples)
            load.run(len(load.steps))  # the finished experiment's columns into the Lab cache
            baseline = load.run(QUIET_REQUESTS)
        finally:
            load.close()
        during_ms, quiet_ms = [ms for _, ms in during], [ms for _, ms in baseline]
        quiet_p95, loaded_p95 = _p95(quiet_ms), _p95(during_ms)
        record["with_queries"] = {
            "source": f"exp:{loaded['experiment_id']}",
            "queries_per_s": QUERY_RATE,
            "query_set": [f"{name}: {method} {path}" for name, (method, path, _) in load.steps],
            "during_ms": _stats(during_ms) if during_ms else None,
            "during_by_request": _by_request(during),
            "quiet_ms": _stats(quiet_ms) if quiet_ms else None,
            "quiet_basis": "the same requests on the same experiment once finished, the pool "
            "idle, after one warm-up cycle",
            "quiet_by_request": _by_request(baseline),
            "errors": load.errors[:20],
            "error_count": len(load.errors),
            "case": loaded,
            "query_throughput_ratio": None
            if not (loaded["trials_per_s"] and quiet["trials_per_s"])
            else round(loaded["trials_per_s"] / quiet["trials_per_s"], 4),
            "query_p95_ratio": None
            if not (quiet_p95 and loaded_p95)
            else round(loaded_p95 / quiet_p95, 4),
        }
    states = [case["child_power_throttling"] for case in record["cases"].values()]
    record["worker"]["power_throttling"] = {
        "host": throttling_state(listener),
        "child": next((state for state in states if state is not None), None),
    }
    http_client.close()
    return record


# --- analytics (Phase 3): the importance task beside a running job ----------------------------


def throughput_loss(quiet: float | None, loaded: float | None) -> float | None:
    """`1 - loaded / quiet`: the share of the job's rate the task cost it (negative when the
    loaded rate was the higher, kept as measured); None when either rate is missing."""
    if not quiet or loaded is None:
        return None
    return 1 - loaded / quiet


def overlap_rate(runs: Sequence[tuple[Sequence[float], Sequence[int]]], start: float, end: float):
    """The job's steady rate over the window [start, end] (epoch seconds). `runs` are each run's
    (chunk commit times, chunk rows). Per run, the chunks committed inside the window count, the
    first one's rows left out (its work began before the window, as `_run_case`'s own rate leaves
    the run's first chunk out), over the seconds between the first and the last; the runs add up.
    A run with one chunk inside adds nothing; with no seconds counted the rate is None."""
    rows_total, seconds_total, per_run = 0, 0.0, []
    for times, rows in runs:
        inside = [(t, r) for t, r in sorted(zip(times, rows, strict=True)) if start <= t <= end]
        counted = sum(r for _, r in inside[1:])
        seconds = inside[-1][0] - inside[0][0] if len(inside) > 1 else 0.0
        per_run.append({"chunks": len(inside), "rows": counted, "seconds": round(seconds, 3)})
        rows_total += counted
        seconds_total += seconds
    return {
        "trials_per_s": rows_total / seconds_total if seconds_total > 0 else None,
        "rows": rows_total,
        "seconds": seconds_total,
        "runs": per_run,
    }


def window_offsets(
    intervals: Sequence[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    """The window [start, end] as offsets from each job interval's creation, for the intervals it
    overlaps (the window's part inside `(created, final)`), in the intervals' order."""
    offsets = []
    for created, final in intervals:
        low, high = max(start, created), min(end, final)
        if high > low:
            offsets.append((low - created, high - created))
    return offsets


def matched_rate(
    series: tuple[Sequence[float], Sequence[int]],
    created: float,
    offsets: Sequence[tuple[float, float]],
) -> dict:
    """`overlap_rate` of one run (a quiet one, created at `created`) over the same offsets from its
    creation: what the quiet run did at the point of its job the task's window sat at, so start-up
    and compaction pauses weigh as they do in the loaded run's window. The windows add up."""
    parts = [overlap_rate([series], created + low, created + high) for low, high in offsets]
    rows = sum(part["rows"] for part in parts)
    seconds = sum(part["seconds"] for part in parts)
    return {
        "trials_per_s": rows / seconds if seconds > 0 else None,
        "rows": rows,
        "seconds": seconds,
        "windows": [part["runs"][0] for part in parts],
    }


def fine_stage(stages: dict[str, dict]) -> tuple[float | None, str | None, bool | None]:
    """The fine-grid stage's time from the stages a poll read (`stage -> {wall_s, elapsed_s}`):
    stage 1's own server `elapsed_s` when it was read; else the first stage that was read, which
    stage 1 finished before (an upper bound, named as one); else nothing. The third value says
    whether the time is a bound."""
    elapsed = {k: e["elapsed_s"] for k, e in stages.items() if e.get("elapsed_s") is not None}
    if not elapsed:
        return None, None, None
    first = min(elapsed, key=int)
    if first == "1":
        return elapsed["1"], "server elapsed_s of stage 1", False
    basis = (
        f"server elapsed_s of stage {first}, the first stage a poll read "
        "(stage 1 finished before it: an upper bound)"
    )
    return elapsed[first], basis, True


def beside_job(result: dict, coverage: float) -> bool:
    """A task measurement stands as one beside a running job when the task finished, was not
    cached at request, and the job's runs covered at least BESIDE_JOB_MIN_COVERAGE of its window."""
    return (
        result.get("state") == "done"
        and not result.get("cached_at_request")
        and coverage >= BESIDE_JOB_MIN_COVERAGE
    )


def plan_vs_actual(estimate_s: float | None, actual_s: float | None) -> dict:
    """The planner's estimate against the wall time the run took."""
    ratio = None if not estimate_s or actual_s is None else round(actual_s / estimate_s, 3)
    return {"estimate_s": estimate_s, "actual_s": actual_s, "actual_over_estimate": ratio}


def widest_front(
    fronts: dict[tuple[str, str], int],
) -> tuple[tuple[str, str], int] | None:
    """The pair of objectives with the widest front among `fronts` (pair -> front size)."""
    if not fronts:
        return None
    pair = max(fronts, key=lambda p: fronts[p])
    return pair, fronts[pair]


def throughput_basis(
    quiet: float | None,
    quiet_after: float | None,
    loaded: float | None,
    chunks: int,
    seconds: float,
) -> str:
    """The headline throughput loss in words: what its two rates are and which figure to read."""
    article = "an" if str(chunks).startswith("8") or chunks in (11, 18) else "a"
    return (
        "1 - loaded.trials_per_s / quiet.trials_per_s. quiet.trials_per_s "
        f"{quiet if quiet is None else round(quiet, 1)} (and quiet_after.trials_per_s "
        f"{quiet_after if quiet_after is None else round(quiet_after, 1)}) are whole-run rates, a "
        "run's start-up gap and its compaction pause in them; loaded.trials_per_s "
        f"{loaded if loaded is None else round(loaded, 1)} is the rate of {article} {chunks}-chunk "
        f"window ({seconds:.1f} s) while the task ran. They are not comparable here (the loaded "
        "window sits clear of the pauses, so this figure reads as the job speeding up): read "
        "throughput_loss_matched, the window against the quiet run at the same offsets"
    )


def a_rule(category: dict) -> str:
    """§7.6's category A read back from its own inputs (the worker's card): distance and the peak
    line are recomputed from the value and the quartiles, then the state the inputs require and
    the classification they give are compared with the worker's. Returns the classification, or
    `unresolved`; an AssertionError says which input disagrees."""
    i = category["inputs"]
    value, p25, p75, iqr = i.get("value"), i.get("p25"), i.get("p75"), i.get("iqr")
    if value is not None and p25 is not None:
        assert math.isclose(i["distance"], abs(value - p25), rel_tol=1e-9, abs_tol=1e-9), i
    if p75 is not None and iqr is not None:
        peak_line = p75 + i["peak_factor"] * iqr
        assert math.isclose(i["peak_line"], peak_line, rel_tol=1e-9, abs_tol=1e-9), i
    short = i["coverage"] < i["min_coverage"] or i["n"] < i["required_n"]
    reason = category.get("reason") or ""
    if not category["resolved"]:
        if reason.startswith("untested surroundings"):
            assert short, category  # untested surroundings name evidence that fell short
        elif reason == "no spread in the metric (τ = 0)":
            assert not short and i["tau"] <= 0, category  # enough evidence, nothing to tell apart
        elif reason == "undefined metric value":
            assert value is None, category
        else:
            raise AssertionError(f"an unresolved A whose reason the rule does not know: {category}")
        return "unresolved"
    assert not short, category  # a resolved A has the coverage and the n the rule asks for
    assert i["tau"] > 0, category  # and a spread: τ <= 0 reads `no spread`, never a class
    expected = (
        "stable local"
        if abs(value - p25) <= i["tau"]
        else "isolated peak"
        if value > p75 + i["peak_factor"] * iqr
        else "mixed"
    )
    assert category["classification"] == expected, (category["classification"], expected, i)
    return expected


def chunk_window(
    series: tuple[Sequence[float], Sequence[int]], start: float, end: float
) -> tuple[int, int] | None:
    """The chunks of one run (by position, in commit order) committed inside [start, end]: their
    first and last index, or None when there is none."""
    times = sorted(series[0])
    inside = [i for i, t in enumerate(times) if start <= t <= end]
    return (inside[0], inside[-1]) if inside else None


def matched_chunks(
    series: tuple[Sequence[float], Sequence[int]],
    windows: Sequence[tuple[int, int] | None],
) -> dict:
    """The rate of one run (a quiet one) over the same chunk positions a loaded run's windows
    held: per window, the rows of the chunks after its first over the seconds between its first
    and last (`overlap_rate`'s rule), read at those indices whatever the run's own timing. A
    start-up gap landing a fraction of a second either side of a window's edge moves a window
    aligned by time across it, and not one aligned by chunk position; the windows add up."""
    pairs = sorted(zip(series[0], series[1], strict=True))
    rows_total, seconds_total, per_window = 0, 0.0, []
    for window in windows:
        if window is None:
            continue
        first, last = window[0], min(window[1], len(pairs) - 1)
        if first >= len(pairs):
            continue
        rows = sum(r for _, r in pairs[first + 1 : last + 1])
        seconds = pairs[last][0] - pairs[first][0]
        per_window.append(
            {
                "chunks": last - first + 1,
                "rows": rows,
                "seconds": round(seconds, 3),
                "indices": [first, last],
            }
        )
        rows_total += rows
        seconds_total += seconds
    return {
        "trials_per_s": rows_total / seconds_total if seconds_total > 0 else None,
        "rows": rows_total,
        "seconds": seconds_total,
        "windows": per_window,
    }


def job_coverage(intervals: Sequence[tuple[float, float]], start: float, end: float) -> float:
    """The share of the window [start, end] that some job interval covers (their union)."""
    if end <= start:
        return 0.0
    covered, cursor = 0.0, start
    for low, high in sorted(intervals):
        low, high = max(low, cursor), min(high, end)
        if high > low:
            covered += high - low
            cursor = high
    return covered / (end - start)


class _TaskLoad:
    """The importance task on the 1M fixture, started from a thread once the job has committed
    its first chunk and polled to its end as the Lab polls it: the `importance` view, which
    answers the latest stage delivered and the task's status. `_run_case` calls it as it calls a
    `_QueryLoad`: the first `start` (the first loaded run's experiment) launches the thread, later
    runs find it going, `stop` does nothing (the load outlives one run). `finished` is set when
    the task ended, was cancelled at the timeout, or the thread failed; the caller then runs no
    further case."""

    def __init__(self, base: str, source: str, seed: int, timeout_s: float) -> None:
        self.base, self.source, self.seed, self.timeout_s = base, source, seed, timeout_s
        self.finished = threading.Event()
        self.result: dict = {}
        self.window: tuple[float, float] | None = None  # epoch seconds: asked, then seen ended
        self.error: str | None = None
        self._job: str | None = None
        self._thread: threading.Thread | None = None

    def start(self, job_source: str) -> None:
        if self._thread is None:
            self._job = job_source.removeprefix("exp:")
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        return None

    def join(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=self.timeout_s + 120)

    def _wait_for_job(self, http_client: _Http) -> None:
        """Until the job has committed a chunk (or ended, or 3 minutes have passed)."""
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            document = http_client.get(f"api/experiments/{self._job}")
            if document["status"] in FINAL or (document.get("progress") or {}).get("cells_done"):
                return
            time.sleep(0.5)

    def _run(self) -> None:
        http_client = _Http(self.base)
        path = f"api/lab/{quote(self.source, safe=':')}/query"
        body = {"filter": {}, "view": "importance", "seed": self.seed}
        stages: dict[str, dict] = {}
        began = time.time()
        timer = time.perf_counter()
        try:
            self._wait_for_job(http_client)
            began, timer = time.time(), time.perf_counter()
            sent = time.perf_counter()
            answer = http_client.post(path, body)
            latencies = [(time.perf_counter() - sent) * 1000]  # the first is the placing request
            first = answer.get("task") or {}
            polls, status, cancelled = 0, first, False
            while True:
                polls += 1
                status = answer.get("task") or {}
                if not status:  # the worker requested no task: its reason is the finding
                    raise RuntimeError(f"no importance task: {answer.get('reason')}")
                shown = answer.get("importance") or {}
                stage = shown.get("stage")
                if stage and str(stage) not in stages:  # the first answer that carries the stage
                    stages[str(stage)] = {
                        "wall_s": round(time.perf_counter() - timer, 3),
                        "elapsed_s": shown.get("elapsed_s"),
                    }
                if status.get("state") in ("done", "failed", "cancelled"):
                    break
                if time.perf_counter() - timer > self.timeout_s:
                    http_client.post(
                        f"api/lab/{quote(self.source, safe=':')}/tasks/{status['id']}/cancel", {}
                    )
                    cancelled = True
                    break
                time.sleep(ANALYTICS_POLL_S)
                sent = time.perf_counter()
                answer = http_client.post(path, body)
                latencies.append((time.perf_counter() - sent) * 1000)
            ended, wall = time.time(), time.perf_counter() - timer
            final = answer.get("importance") or {}
            done = status.get("state") == "done" and final.get("stage") == final.get("stages")
            fine, fine_basis, fine_bound = fine_stage(stages)
            self.window = (began, ended)
            self.result = {
                "source": self.source,
                "task_id": status.get("id"),
                "seed": self.seed,
                "state": status.get("state"),
                "stages": final.get("stages"),
                "stages_seen": stages,
                "cached_at_request": first.get("state") == "done",
                "cancelled_at_timeout": cancelled,
                "polls": polls,
                "task_s": final.get("elapsed_s") if done else None,
                "task_wall_s": round(wall, 3),
                # Stage 1's own elapsed time when a poll read it; else the elapsed time of the
                # first stage a poll did read, which stage 1 finished before (an upper bound).
                "fine_stage_s": fine,
                "fine_stage_basis": fine_basis,
                "fine_stage_is_bound": fine_bound,
                "poll_ms": _stats(latencies),  # every post, the placing request first
                "poll_ms_after_first": _stats(latencies[1:]) if len(latencies) > 1 else None,
                "poll_cadence_s": ANALYTICS_POLL_S,
                "snapshot": final.get("snapshot"),
                "n": final.get("n"),
                "status": status,
                "error": status.get("error"),
            }
        except Exception as exc:  # noqa: BLE001 - recorded: the run reports why it has no task
            self.error = f"{type(exc).__name__}: {exc}"[:500]
            self.window = (began, time.time())
        finally:
            http_client.close()
            self.finished.set()


def _load_pass(
    http_client: _Http,
    base: str,
    source: str,
    *,
    strategy_id: str,
    stamp: str,
    data_root: Path,
    listener: int,
    workers: int,
    task_seed: int,
    task_timeout_s: float,
    max_runs: int,
) -> dict:
    """Case A back to back with the importance task of `source` polled to its end beside it (a
    thread starting it once the first run commits a chunk; the last run finishing after it): the
    runs, each run's chunk series and job interval, the task's window, how much of it the job
    covered, and the task's record with the verdict `beside_job`."""
    load = _TaskLoad(base, source, task_seed, task_timeout_s)
    runs: list[dict] = []
    try:
        for n in range(max_runs):
            runs.append(
                _run_case(
                    http_client,
                    "A",
                    strategy_id,
                    f"{stamp}-{n + 1}",
                    data_root,
                    listener,
                    workers,
                    queries=load,
                )
            )
            if load.finished.is_set():
                break
    finally:
        load.join()
    began, ended = load.window or (0.0, 0.0)
    series = []
    for run in runs:
        _, rows, times = _chunk_times(data_root / "experiments" / f"{run['experiment_id']}.cells")
        series.append((times, rows))
    intervals = [(r["created_at"], r["final_at"]) for r in runs if r["final_at"] is not None]
    coverage = job_coverage(intervals, began, ended)
    task = load.result | {
        "window_epoch_s": [round(began, 3), round(ended, 3)],
        "job_coverage": round(coverage, 4),
        "job_coverage_min": BESIDE_JOB_MIN_COVERAGE,
        "error": load.error or load.result.get("error"),
    }
    task["beside_job"] = beside_job(task, coverage)
    return {
        "runs": runs,
        "series": series,
        "intervals": intervals,
        "began": began,
        "ended": ended,
        "task": task,
    }


def opt_frame_rebuild(runs: int = 3) -> dict:
    """What every poll of an `opt:` source's importance view pays before it computes anything: the
    optimization's frame rebuilt from its cells (`sources.opt_frame`), at MAX_CELLS cells. In this
    process over a status built here (a 316 x 316 grid of the default strategy's two lengths, no
    engine run), so a proxy: no HTTP, no view on top of the frame."""
    from products.aegis.lab.sources import opt_frame
    from products.aegis.optimize import MAX_CELLS, expand_grid
    from products.aegis.pool import METRICS
    from products.aegis.strategy import OptimizationParameter, default_strategy

    strategy = default_strategy()
    side = strategy.long_side.model_copy(
        update={
            "optimization": [
                OptimizationParameter(path="indicators.ema.length", start=1, stop=316, step=1),
                OptimizationParameter(path="indicators.sma.length", start=400, stop=715, step=1),
            ]
        }
    )
    strategy = strategy.model_copy(update={"long_side": side})
    plan = expand_grid(side)
    assert not plan.skipped and len(plan.cells) <= MAX_CELLS, len(plan.cells)
    cells = [
        {
            "params": params,
            "fast": params.get(plan.fast_path),
            "slow": params.get(plan.slow_path),
            "metrics": {**dict.fromkeys(METRICS, 1.0), "net_pnl": float(i % 97) - 40.0},
        }
        for i, params in enumerate(plan.cells)
    ]
    status = {
        "job_id": "opt-frame-proxy",
        "side": "long",
        "status": "done",
        "objective": "net_pnl",
        "strategy": strategy.model_dump(mode="json"),
        "strategy_hash": "proxy",
        "engine": "kernel",
        "data": {"symbol": "QQQ"},
        "cells": cells,
        "total_cells": len(cells),
        "skipped_cells": 0,
    }
    samples = []
    for _ in range(runs):
        started = time.perf_counter()
        frame = opt_frame(status)
        samples.append((time.perf_counter() - started) * 1000)
    return {
        "basis": INPROCESS_BASIS + ": the rebuild alone, without the view on top of it",
        "cells": len(cells),
        "max_cells": MAX_CELLS,
        "rows": len(frame.table),
        "ms": _stats(samples),
    }


def _row_bases(trials: int, runs: int, task_seed: int) -> dict[str, str]:
    """What each recorded row measured, in words (`operations.<row>`'s counterpart)."""
    return {
        "pareto": f"{runs} HTTP runs, two objectives (the objective against max_drawdown), cold "
        "first included; judged at §9.6a's 800 ms",
        "pareto_3": f"{runs} HTTP runs, three objectives (adding trade_count); recorded beside "
        "the 800 ms row, never judged",
        "pareto_widest": "the pair of the fixture's metrics with the widest front among all pairs "
        f"({runs} HTTP runs of it); the true all-on-front worst case is not constructible over "
        "HTTP (see not_measured)",
        "neighbourhood": f"{runs} HTTP runs of the neighbourhood view, a different seeded trial "
        "each, cold first included; judged at §9.6a's 150 ms",
        "convergence": f"{runs} HTTP runs at {trials:,} trials, d = 10: the first is cold (the "
        "payload is cached after it), the rest warm; recorded with spec §9.6's ≈ 2 s line of the "
        "Task 8 ruling in view, no §9.6a line is stated for it",
        "rankings": "the robustness view's ranking (pool 300, k 20, B on the top 20) before any "
        f"importance result exists, so B is not run: {runs} HTTP runs, the first cold",
        "rankings_importance": "the same ranking with the importance task's result at this "
        f"snapshot (seed {task_seed}), so B runs on the top 20: the costly half; recorded",
        "candidate": f"{runs} HTTP runs of one candidate's robustness view (A plus B's region "
        "read, the importance result live), a different seeded trial of the ranking's pool of "
        "300 each, cold first included; judged at §9.6a's 150 ms row 'neighbourhood of one trial / "
        "robustness of one candidate'",
    }


def analytics(
    data_root: Path,
    *,
    base: str,
    pid_file: Path,
    trials: int = 1_000_000,
    seed: int = 1,
    task_seed: int = 1,
    runs: int = 20,
    workers: int = 10,
    max_runs: int = ANALYTICS_MAX_RUNS,
    task_timeout_s: float = ANALYTICS_TASK_TIMEOUT_S,
    wide_values: int | None = WIDE_VALUES,
    blocked: bool = True,
) -> dict:
    """The importance task on the 1M fixture beside a running job (spec §9.4, R3.5), and the
    Phase 3 views' rows over HTTP. In order, on the idle worker: the neighbourhood, convergence
    and ranking views (each cold first; the worker's resident memory around each first call), the
    Pareto views (two and three objectives, and the widest front among metric pairs); then case A
    alone (the quiet run); case A back to back with a thread starting the importance task once the
    first run commits a chunk and polling it to done (the loaded pass); case A alone again (so
    run-order drift shows); with the task's result in, the ranking again and one candidate's
    robustness view (B live); a K = 4 blocked case A against the planner's estimate; and, when
    `wide_values` is set, a second loaded pass on a 1M fixture with that many values on each
    parameter (the fine stage at 20 values). The record keeps the task's time and its fine-grid
    stage (the server's own `elapsed_s` of stages 3 and 1), the job's throughput over the chunks
    committed while the task ran against each quiet run (whole-run and at the same offsets), and
    names what the fixtures leave unmeasured, each with an owner. Refuses the product store and
    the product worker before anything else, as `main` does."""
    refuse_product_targets(data_root, base)
    from trading_core.process_power import opt_out_of_power_throttling

    data_root = Path(data_root)
    opt_out_of_power_throttling()
    _require_worker_root(base, data_root)
    worker = worker_process(base, pid_file)
    listener = worker["listener_pid"]
    experiment_id = fixture_id(trials)
    source = f"exp:{experiment_id}"
    record = new_record("analytics")
    document, written_s = _fixture(data_root, experiment_id, trials, seed)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    http_client = _Http(base)
    strategy = http_client.post(
        "api/strategies",
        {"name": f"lab-bench-10p-{stamp}", "spec": bench_strategy().model_dump(mode="json")},
    )
    build = http_client.get("api/lab/build")
    record.update(
        {
            "basis": HTTP_BASIS,
            "base": base,
            "data_root": str(data_root),
            "experiment_id": experiment_id,
            "trials": trials,
            "parameters": len(document.surface.parameters),
            "blocks": int(getattr(document, "blocks", 0) or 0),
            "seed": seed,
            "task_seed": task_seed,
            "runs": runs,
            "fixture_write_s": written_s,
            "workers_expected": workers,
            "strategy_id": strategy["id"],
            "worker": worker,
            "worker_engine_build": build["engine_build"],
            "cache_entries_before": int(build["cache"]["entries"]),
            "poll_cadence_s": ANALYTICS_POLL_S,
        }
    )

    def over_http(method: str, path: str, body: dict | None) -> Any:
        return http_client.call(method, "api/" + path, body)

    def rss() -> int:
        return int(worker_sample(listener)["working_set"])

    operations = _operations(document, trials, seed, task_seed=task_seed)
    timed = record["operations"]
    first_call_rss: dict[str, float] = {}
    resident_before = rss()
    for name in ("neighbourhood", "convergence", "rankings"):  # each one's first call is cold
        before, held = rss(), {}
        timed[name] = _timed(
            over_http,
            operations[name],
            runs,
            "http",
            on_first=lambda held=held: held.update(after=rss()),
        )
        first_call_rss[name] = round((held["after"] - before) / MB, 3)
    timed["pareto"] = _timed(over_http, operations["pareto"], runs, "http")
    timed["pareto_3"] = _timed(over_http, operations["pareto_3"], runs, "http")
    from products.aegis.pool import METRICS

    names = [*METRICS, "sharpe_trade"]
    fronts: dict[tuple[str, str], int] = {}
    query_path = f"lab/{quote(source, safe=':')}/query"
    for pair in itertools.combinations(names, 2):
        body = {"filter": {}, "view": "pareto", "objectives": list(pair)}
        fronts[pair] = int(over_http("POST", query_path, body)["front_size"])
    widest = widest_front(fronts)
    if widest is not None:
        pair, size = widest

        def widest_front_request(i: int) -> list[Step]:
            body = {"filter": {}, "view": "pareto", "objectives": list(pair)}
            return [("POST", query_path, body)]

        timed["pareto_widest"] = _timed(over_http, widest_front_request, runs, "http") | {
            "pair": list(pair),
            "front_size": size,
            "pairs_probed": len(fronts),
            "front_sizes": {
                "|".join(p): n for p, n in sorted(fronts.items(), key=lambda kv: -kv[1])[:8]
            },
        }
    resident_after = rss()
    record["resources"] = {
        "first_call_rss_delta_mb": first_call_rss,
        "first_call_rss_note": "the worker's working set before and after each first call, in "
        "this order; the three views read one cached table (design, pass, the ten paths, pos.k, "
        "the metric), so the first call pays for it",
        "worker_working_set_mb": {
            "before_the_views": round(resident_before / MB, 3),
            "after_the_views": round(resident_after / MB, 3),
        },
    }

    quiet = _run_case(
        http_client, "A", strategy["id"], f"{stamp}-quiet", data_root, listener, workers
    )
    first = _load_pass(
        http_client,
        base,
        source,
        strategy_id=strategy["id"],
        stamp=f"{stamp}-loaded",
        data_root=data_root,
        listener=listener,
        workers=workers,
        task_seed=task_seed,
        task_timeout_s=task_timeout_s,
        max_runs=max_runs,
    )
    quiet_after = _run_case(
        http_client, "A", strategy["id"], f"{stamp}-quiet-after", data_root, listener, workers
    )
    task, began, ended = first["task"], first["began"], first["ended"]

    # With the importance result in: the ranking with B on its top k, and one candidate's view.
    ranking_all = over_http(
        "POST",
        query_path,
        {
            "filter": {},
            "view": "robustness",
            "metric": document.objective,
            "seed": task_seed,
            "k": 300,
        },
    )["rankings"]
    pool = [row["trial_id"] for row in ranking_all["peak_ranked"]]
    live = _operations(document, trials, seed, task_seed=task_seed, pool=pool)
    timed["rankings_importance"] = _timed(over_http, live["rankings"], runs, "http")
    timed["candidate"] = _timed(over_http, live["candidate"], runs, "http")
    record["ranking_pool"] = {
        "pool": ranking_all["pool"],
        "k": 20,
        "candidates_drawn_from": len(pool),
        "b_max": ranking_all["b_max"],
    }

    # Plan against actual for a K = 4 blocked case A (the planner's estimate, then the run).
    if blocked:
        body = _experiment_body("A", BENCH_CASES["A"], strategy["id"], f"{stamp}-k4", BLOCKED_K)
        planned = http_client.post("api/experiments/plan", body)
        run = _run_case(
            http_client,
            "A",
            strategy["id"],
            f"{stamp}-k4",
            data_root,
            listener,
            workers,
            blocks=BLOCKED_K,
        )
        record["blocked"] = {
            "blocks": BLOCKED_K,
            "plan": {
                k: planned[k]
                for k in (
                    "estimate_seconds",
                    "ms_per_cell_bar",
                    "workers",
                    "evaluations",
                    "planned_runs",
                    "bars",
                    "price_source",
                )
            },
            "plan_vs_actual": plan_vs_actual(planned["estimate_seconds"], run["wall_s"]),
            "k0_plan_vs_actual": plan_vs_actual(
                (quiet.get("plan") or {}).get("estimate_seconds"), quiet["wall_s"]
            ),
            "case": run,
            "basis": "the K = 4 case-A experiment (10,000 trials, each also scored on 4 blocks) "
            "against the planner's own estimate (POST /experiments/plan, the endpoint the "
            "planner uses) and the K = 0 quiet run's; rows of this run are evaluations (5 a "
            "trial). The price model is Task 2's; a gap here is an R3.5 finding",
        }

    # The fine stage at `wide_values` values per parameter, beside a job (a second loaded pass).
    not_measured = list(ANALYTICS_NOT_MEASURED)
    wide_pass = None
    if wide_values:
        wide_id = fixture_id(trials, wide_values)
        wide_document, wide_written = _fixture(data_root, wide_id, trials, seed, wide_values)
        wide_pass = _load_pass(
            http_client,
            base,
            f"exp:{wide_id}",
            strategy_id=strategy["id"],
            stamp=f"{stamp}-wide",
            data_root=data_root,
            listener=listener,
            workers=workers,
            task_seed=task_seed,
            task_timeout_s=task_timeout_s,
            max_runs=max_runs,
        )
        record["wide"] = {
            "values_per_parameter": wide_values,
            "experiment_id": wide_id,
            "parameters": len(wide_document.surface.parameters),
            "fixture_write_s": wide_written,
            "fixture": "written by this run"
            if wide_written is not None
            else "reused: written by an earlier run into the scratch root",
            "task": wide_pass["task"],
            "runs": [
                {
                    k: r[k]
                    for k in ("experiment_id", "status", "created_at", "final_at", "trials_per_s")
                }
                for r in wide_pass["runs"]
            ],
            "basis": f"the importance task on a {trials:,}-trial fixture with {wide_values} "
            "values on each of its 10 parameters, beside case A, as the first pass; 10 "
            "parameters, not 20",
        }
    else:
        not_measured.append(
            {
                "row": f"fine stage at {WIDE_VALUES} values per parameter beside a job",
                "why": "the second pass was not run (`--no-wide`)",
                "owner": "Task 13 Step 2, or Phase 4's 20-parameter fixture",
            }
        )
    if not blocked:
        not_measured.append(
            {
                "row": "plan against actual for a K = 4 blocked case A",
                "why": "the blocked run was not made (`--no-blocked`)",
                "owner": "Task 13 Step 2",
            }
        )
    record["not_measured"] = not_measured

    # The first pass's composition: the loaded rate, the quiet runs' (whole-run and matched).
    overlap = overlap_rate(first["series"], began, ended)
    offsets = window_offsets(first["intervals"], began, ended)
    loaded_rate = overlap["trials_per_s"]
    quiet_series = _quiet_series(data_root, quiet)
    after_series = _quiet_series(data_root, quiet_after)
    ranges = [chunk_window(s, began, ended) for s in first["series"]]
    matched = matched_chunks(quiet_series, ranges)
    matched_after = matched_chunks(after_series, ranges)
    by_time = matched_rate(quiet_series, quiet["created_at"], offsets)
    by_time_after = matched_rate(after_series, quiet_after["created_at"], offsets)
    loss = throughput_loss(quiet["trials_per_s"], loaded_rate)
    quiet["basis"] = QUIET_BASIS
    quiet_after["basis"] = QUIET_BASIS + "; run after the loaded pass"
    record["task"] = task
    record["cases"] = {
        "quiet": quiet,
        "quiet_matched": _matched_json(matched, QUIET_MATCHED_BASIS),
        "quiet_matched_by_time": _matched_json(by_time, QUIET_BY_TIME_BASIS),
        "loaded": {
            "trials_per_s": None if loaded_rate is None else round(loaded_rate, 3),
            "basis": "steady rows of the chunks committed while the task ran, over their span, "
            "per run, summed (each run's first chunk in the window is left out): a window, "
            f"{overlap['runs'][0]['chunks'] if overlap['runs'] else 0} chunks in the first run",
            "window_s": round(ended - began, 3),
            "window_offsets_from_creation_s": [[round(a, 3), round(b, 3)] for a, b in offsets],
            "counted_rows": overlap["rows"],
            "counted_seconds": round(overlap["seconds"], 3),
            "overlap_runs": overlap["runs"],
            "runs": [
                {
                    "experiment_id": run["experiment_id"],
                    "status": run["status"],
                    "trials_per_s_whole_run": run["trials_per_s"],
                    "created_at": run["created_at"],
                    "final_at": run["final_at"],
                    "pool_workers": run["pool_workers"],
                }
                for run in first["runs"]
            ],
        },
        "quiet_after": quiet_after,
        "quiet_after_matched": _matched_json(matched_after, QUIET_MATCHED_BASIS),
        "quiet_after_matched_by_time": _matched_json(by_time_after, QUIET_BY_TIME_BASIS),
    }
    rate_after = quiet_after["trials_per_s"]
    record["throughput_loss"] = None if loss is None else round(loss, 4)
    record["throughput_loss_basis"] = throughput_basis(
        quiet["trials_per_s"],
        rate_after,
        loaded_rate,
        sum(w["chunks"] for w in overlap["runs"]),
        overlap["seconds"],
    )
    matched_loss = throughput_loss(matched["trials_per_s"], loaded_rate)
    matched_loss_after = throughput_loss(matched_after["trials_per_s"], loaded_rate)
    record["throughput_loss_matched"] = None if matched_loss is None else round(matched_loss, 4)
    record["throughput_loss_matched_after"] = (
        None if matched_loss_after is None else round(matched_loss_after, 4)
    )
    rounded = [(round(a, 1), round(b, 1)) for a, b in offsets]
    record["throughput_loss_matched_basis"] = (
        "1 - loaded.trials_per_s / quiet_matched.trials_per_s (and / quiet_after_matched's, "
        "`throughput_loss_matched_after`): the quiet run read at the same chunk positions as the "
        f"loaded window ({matched['windows']}), {matched['rows']:,} rows over "
        f"{matched['seconds']:.1f} s in {len(matched['windows'])} window against "
        f"{overlap['rows']:,} rows over {overlap['seconds']:.1f} s of the loaded window, which sat "
        f"{rounded} seconds from the loaded run's creation. A short window of about "
        f"{overlap['runs'][0]['chunks'] if overlap['runs'] else 0} chunks, so a range, not a point; "
        "`quiet_run_to_run` is how far the two quiet runs differ over those very chunks, the noise "
        "this loss has to be read against; the same windows aligned by time from creation are "
        "`quiet_matched_by_time` (they straddle the start-up gap when a first chunk lands at a "
        "window's edge)"
    )
    spread = (
        None
        if not (matched["trials_per_s"] and matched_after["trials_per_s"])
        else round(1 - matched_after["trials_per_s"] / matched["trials_per_s"], 4)
    )
    record["quiet_run_to_run"] = spread
    record["importance_poll"] = {
        "poll_ms": task.get("poll_ms"),
        "poll_ms_after_first": task.get("poll_ms_after_first"),
        "cadence_s": ANALYTICS_POLL_S,
        "basis": "the importance view's HTTP latency over the first pass's task (an `exp:` "
        "source: its frame is cached, so a poll reads it and answers the stage); the first "
        f"sample is the request that placed the task. Polled every {ANALYTICS_POLL_S} s, four "
        f"times the Lab's {LAB_TICK_S:g} s tick. The `opt:` source's per-poll frame rebuild is "
        "this record's `opt_frame_rebuild`",
    }
    record["opt_frame_rebuild"] = opt_frame_rebuild()
    record["row_bases"] = _row_bases(trials, runs, task_seed)
    record["worker"]["power_throttling"] = {
        "host": throttling_state(listener),
        "child": next(
            (
                c["child_power_throttling"]
                for c in (quiet, quiet_after, *first["runs"])
                if c["child_power_throttling"]
            ),
            None,
        ),
    }
    http_client.close()
    return record


def _quiet_series(data_root: Path, run: dict) -> tuple[list[float], list[int]]:
    """A finished run's (chunk commit times, chunk rows), read from its cells folder."""
    _, rows, times = _chunk_times(data_root / "experiments" / f"{run['experiment_id']}.cells")
    return times, rows


def _matched_json(matched: dict, basis: str) -> dict:
    return {
        "trials_per_s": None
        if matched["trials_per_s"] is None
        else round(matched["trials_per_s"], 3),
        "basis": basis,
        "counted_rows": matched["rows"],
        "counted_seconds": round(matched["seconds"], 3),
        "windows": matched["windows"],
    }


# --- the command line -------------------------------------------------------------------------


def _previous(mode: str) -> dict | None:
    records = sorted((ROOT / "logs").glob(f"lab-benchmark-{mode}-*.json"))
    if not records:
        return None
    try:
        return json.loads(records[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="lab_benchmark.py", description=__doc__.split("\n")[0])
    modes = parser.add_subparsers(dest="mode", required=True)
    explore_args = modes.add_parser("explore", help="Track A: the Lab over the synthetic fixture")
    explore_args.add_argument("--data-root", type=Path, required=True)
    explore_args.add_argument("--base", required=True)
    explore_args.add_argument("--pid-file", type=Path, required=True)
    explore_args.add_argument("--trials", type=int, default=1_000_000)
    explore_args.add_argument("--seed", type=int, default=1)
    explore_args.add_argument("--runs", type=int, default=20)
    explore_args.add_argument("--inprocess", action="store_true")
    execute_args = modes.add_parser("execute", help="Track B: the §9.1b cases on the real engine")
    execute_args.add_argument("--base", required=True)
    execute_args.add_argument("--pid-file", type=Path, required=True)
    execute_args.add_argument("--data-root", type=Path, required=True)
    execute_args.add_argument("--cases", default="A,B,C")
    execute_args.add_argument(
        "--workers",
        type=int,
        default=10,
        help="the pool size expected (the launcher's -Workers); a different observed pool is "
        "noted in the record, and the measured cost always uses the observed one",
    )
    analytics_args = modes.add_parser(
        "analytics", help="Phase 3: the importance task beside a running job, and two views"
    )
    analytics_args.add_argument("--base", required=True)
    analytics_args.add_argument("--pid-file", type=Path, required=True)
    analytics_args.add_argument("--data-root", type=Path, required=True)
    analytics_args.add_argument("--trials", type=int, default=1_000_000)
    analytics_args.add_argument("--seed", type=int, default=1)
    analytics_args.add_argument(
        "--task-seed",
        type=int,
        default=1,
        help="the importance task's resample seed; a task this worker already computed for the "
        "same seed answers from its cache and is recorded as such (restart the worker, or pass "
        "another seed, for a measurement beside the job)",
    )
    analytics_args.add_argument("--runs", type=int, default=20)
    analytics_args.add_argument(
        "--wide-values",
        type=int,
        default=WIDE_VALUES,
        help="values per parameter of the second pass's 1M fixture (the fine stage at that many); "
        "written into the scratch root when absent",
    )
    analytics_args.add_argument(
        "--no-wide", action="store_true", help="skip the second pass (the fixture write and a pass)"
    )
    analytics_args.add_argument(
        "--no-blocked", action="store_true", help="skip the K = 4 blocked case-A run"
    )
    analytics_args.add_argument(
        "--workers",
        type=int,
        default=10,
        help="the pool size expected (the launcher's -Workers); a different observed pool is "
        "noted in the record",
    )
    args = parser.parse_args(list(argv))
    pid_file = args.pid_file if args.pid_file.is_absolute() else ROOT / args.pid_file
    try:
        refuse_product_targets(args.data_root, args.base)
        if args.mode == "explore":
            record = explore(
                args.data_root,
                base=args.base,
                pid_file=pid_file,
                trials=args.trials,
                seed=args.seed,
                runs=args.runs,
                inprocess=args.inprocess,
            )
        elif args.mode == "analytics":
            record = analytics(
                args.data_root,
                base=args.base,
                pid_file=pid_file,
                trials=args.trials,
                seed=args.seed,
                task_seed=args.task_seed,
                runs=args.runs,
                workers=args.workers,
                wide_values=None if args.no_wide else args.wide_values,
                blocked=not args.no_blocked,
            )
        else:
            record = execute(
                args.base,
                cases=[label.strip() for label in args.cases.split(",") if label.strip()],
                pid_file=pid_file,
                data_root=args.data_root,
                workers=args.workers,
            )
    except Refusal as refusal:
        print(refusal, file=sys.stderr)
        return 2
    previous = _previous(args.mode)
    record["evaluate"] = evaluate(record)
    if args.mode == "analytics":
        record["evaluate_basis"] = evaluate_basis(record)
    record["retest_due"] = retest_due(record, previous)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "logs" / f"lab-benchmark-{args.mode}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    print(f"record: {path}")
    print(
        json.dumps({"evaluate": record["evaluate"], "retest_due": record["retest_due"]}, indent=1)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
