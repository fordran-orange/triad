"""The experiment process pool (Mission 6 spec §4.3).

Each worker process holds the bars (prepared once, in the host), its own indicator cache and
the compiled kernel, and runs cells through the metrics-only path; it returns rows, never
envelopes. The pool measures the workers' own cost per cell-bar, which is comparable to the
single-threaded optimizer's rate (plan ruling P2). Mission 10: a worker receives the prepared
frame (numpy columns, never a dict per bar) and slices windows from it, and a pool runs only
as many workers as free memory holds.
"""

from __future__ import annotations

import ctypes
import os
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat

import pandas as pd
from pydantic import ValidationError
from trading_core.process_power import opt_out_of_power_throttling

SCOPES = ("combined", "long", "short")
METRICS = (
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
)
CURVE_POINTS = 128
# A worker's memory: a fixed start-up cost and a cost per bar it holds, its peak working set on
# a 100-cell grid measured with tests/products/aegis/memory_probe.py (Mission 10: 156 MB on
# 4,863 1m bars, 215 MB on 161,754, 499 MB on 947,519 - 154 MB + 361 B/bar), rounded up.
POOL_WORKER_BYTES = 160_000_000
POOL_BYTES_PER_BAR = 400
MEMORY_HEADROOM = 0.8  # the share of free memory a pool may take
POOL_CACHE_BYTES_PER_BAR = 128  # a worker's indicator cache: about 16 one-output series

# Worker-process state, set once by the initializer.
_FRAME = None
_DATA_KEY = None
_SPEC = None
_SETTINGS = None
_CACHE = None
_WINDOW = None  # (bounds, frame, data key) of the window slice the worker last ran


def default_workers() -> int:
    configured = os.environ.get("AEGIS_POOL_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, (os.cpu_count() or 2) - 2)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_memory_bytes() -> int:
    """Physical memory available now (GlobalMemoryStatusEx; sysconf off Windows)."""
    if os.name == "nt":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx failed")
        return int(status.ullAvailPhys)
    return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))


def _gb(value: float) -> str:
    return f"{value / 1e9:.1f} GB"


def workers_for(bars: int, wanted: int, free: int) -> int:
    """How many of `wanted` workers holding `bars` bars fit in `free` bytes; a ValueError
    naming the shortfall when not even one does."""
    each = POOL_WORKER_BYTES + bars * POOL_BYTES_PER_BAR
    usable = free * MEMORY_HEADROOM
    fit = int(usable // each) if each else wanted
    if fit < 1:
        raise ValueError(
            f"not enough free memory for the pool: one worker on {bars:,} bars needs about "
            f"{_gb(each)} and {_gb(usable)} of the {_gb(free)} free is usable; narrow the "
            "range or close other programs"
        )
    return max(1, min(wanted, fit))


def fitted_workers(bars: int, wanted: int | None = None) -> int:
    """`wanted` (default: the configured workers) capped to what free memory holds now."""
    return workers_for(bars, wanted or default_workers(), free_memory_bytes())


def pool_frame(bars: list[dict] | pd.DataFrame, symbol: str) -> pd.DataFrame:
    """The prepared frame a pool runs on: a prepared frame as given, or rows prepared once with
    the pool's symbol where a row has none (a study's rows)."""
    from products.aegis.backtest import _prepare_frame

    frame = bars if isinstance(bars, pd.DataFrame) else _prepare_frame(bars)
    return frame if "symbol" in frame.columns else frame.assign(symbol=symbol)


def resample_curve(points: list[float], n: int = CURVE_POINTS) -> list[float]:
    """`n` points by index: the first and last are kept, short series are padded by repetition."""
    if not points:
        return [0.0] * n
    if len(points) == 1:
        return [float(points[0])] * n
    last = len(points) - 1
    return [float(points[(k * last) // (n - 1)]) for k in range(n)]


def _init_worker(bars: list[dict] | pd.DataFrame, symbol: str, spec: dict, settings: dict) -> None:
    """Each pool process's start. It first opts out of Windows power throttling: a process does
    not inherit its windowless parent worker's opt-out (Lab Phase 2 Task 9 measured the children
    "system managed", at about 4x §9.1b's per-trial cost). Then it holds the frame, the spec, the
    settings and its indicator cache."""
    global _FRAME, _DATA_KEY, _SPEC, _SETTINGS, _CACHE, _WINDOW
    opt_out_of_power_throttling()
    from products.aegis.backtest import BacktestSettings, _data_key
    from products.aegis.indicators import IndicatorCache
    from products.aegis.strategy import StrategySpec

    _WINDOW = None
    _FRAME = pool_frame(bars, symbol)
    _DATA_KEY = _data_key(_FRAME)
    _SPEC = StrategySpec.model_validate(spec)
    _SETTINGS = BacktestSettings.model_validate(settings)
    _CACHE = IndicatorCache(max_bytes=POOL_CACHE_BYTES_PER_BAR * len(_FRAME))


def _window_frame(window: tuple[int, int] | None):
    """The frame and data key a cell runs on: the whole bars, or one window's slice of them
    (Mission 8: a study maps each window in-sample only)."""
    global _WINDOW
    if window is None:
        return _FRAME, _DATA_KEY
    from products.aegis.backtest import _data_key, frame_slice

    bounds = (int(window[0]), int(window[1]))
    if _WINDOW is None or _WINDOW[0] != bounds:
        frame = frame_slice(_FRAME, bounds[0], bounds[1])
        _WINDOW = (bounds, frame, _data_key(frame))
    return _WINDOW[1], _WINDOW[2]


def _run_cell(
    index: int, params: dict[str, float], want_curve: bool, window: tuple[int, int] | None = None
) -> dict:
    from products.aegis.backtest import prepared_request, run_metrics
    from products.aegis.surface import apply_params, skip_reason_of

    started = time.perf_counter()
    row = {
        "cell": index,
        "valid": True,
        "skip_reason": None,
        "params": dict(params),
        "metrics": None,
        "lab_metrics": None,  # the trade Sharpe per scope, beside the metrics (Lab Phase 2b)
        "elapsed_ms": 0.0,
        "curve": None,
        "first_time": None,
        "last_time": None,
        "engine": None,
    }
    try:
        strategy = apply_params(_SPEC, params)
    except ValidationError as exc:
        row.update(valid=False, skip_reason=skip_reason_of(exc))
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    except ValueError as exc:
        row.update(valid=False, skip_reason=str(exc))
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    request = prepared_request(strategy, _SETTINGS)
    try:
        frame, data_key = _window_frame(window)
        result = run_metrics(request, frame, data_key, _CACHE, want_curve, want_lab=True)
    except ValueError as exc:  # the engine's own refusal (a warm-up longer than the data)
        message = str(exc)
        reason = "insufficient bars" if message.startswith("insufficient bars") else message
        row.update(valid=False, skip_reason=reason)
        row["elapsed_ms"] = (time.perf_counter() - started) * 1000
        return row
    row.update(
        metrics={scope: result[scope] for scope in SCOPES},
        lab_metrics=result["lab_metrics"],
        curve=resample_curve(result["curve"]) if want_curve else None,
        first_time=result["first_time"],
        last_time=result["last_time"],
        engine=result["engine"],
    )
    row["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return row


class Pool:
    """A process pool bound to one set of bars, one pinned spec and one settings object."""

    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers or default_workers()
        self._executor: ProcessPoolExecutor | None = None
        self._bars = 0
        self._cell_ms_total = 0.0
        self._cell_bars_total = 0

    def start(
        self, bars: list[dict] | pd.DataFrame, symbol: str, spec: dict, settings: dict
    ) -> None:
        """Bind the pool to the prepared frame (or rows, prepared here once) for `symbol`."""
        frame = pool_frame(bars, symbol)
        self._bars = len(frame)
        self._executor = ProcessPoolExecutor(
            max_workers=self.max_workers,
            initializer=_init_worker,
            initargs=(frame, symbol, spec, settings),
        )

    @property
    def mean_ms_per_cell_bar(self) -> float | None:
        if not self._cell_bars_total:
            return None
        return self._cell_ms_total / self._cell_bars_total

    def run_chunk(
        self,
        cells: list[tuple[int, dict[str, float]]],
        want_curve: bool,
        window: tuple[int, int] | None = None,
    ) -> list[dict]:
        """Run cells on the whole bars, or with `window` = (start, end) on that slice only."""
        if self._executor is None:
            raise RuntimeError("pool not started")
        bars = self._bars if window is None else window[1] - window[0]
        indices = [index for index, _ in cells]
        params = [values for _, values in cells]
        chunksize = max(1, len(cells) // (self.max_workers * 4))
        rows = list(
            self._executor.map(
                _run_cell,
                indices,
                params,
                repeat(want_curve),
                repeat(window),
                chunksize=chunksize,
            )
        )
        for row in rows:
            if row["valid"]:
                self._cell_ms_total += row["elapsed_ms"]
                self._cell_bars_total += bars
        return rows

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None


__all__ = [
    "CURVE_POINTS",
    "METRICS",
    "POOL_BYTES_PER_BAR",
    "POOL_WORKER_BYTES",
    "SCOPES",
    "Pool",
    "default_workers",
    "fitted_workers",
    "free_memory_bytes",
    "pool_frame",
    "resample_curve",
    "workers_for",
]
