"""Mission 10 memory probe: peak memory of Aegis's ten-year paths, out of process, nothing saved.

    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\memory_probe.py backtest 2016-01-01 2025-12-31
    .venv-aegis\\Scripts\\python.exe tests\\products\\aegis\\memory_probe.py worker 2016-01-01 2025-12-31

`backtest` runs the /backtest path (archive select, prepared frame, engine, slim envelope, JSON)
in this process and reports the peak working set above the selected frame per bar. `worker`
starts a one-worker pool on the same bars, runs a 10 x 10 grid of the default strategy's long EMA
and SMA lengths through it and reports the worker's peak private bytes; two ranges give the
pool's POOL_WORKER_BYTES and POOL_BYTES_PER_BAR. The OS's own counters (GetProcessMemoryInfo)
are read, so no extra package is needed. The bar cap is lifted in this process only.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "app"))


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


_K32 = ctypes.WinDLL("kernel32", use_last_error=True)
_K32.GetCurrentProcess.restype = wintypes.HANDLE
_K32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_K32.OpenProcess.restype = wintypes.HANDLE
_K32.CloseHandle.argtypes = [wintypes.HANDLE]
_K32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
_K32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
_QUERY = 0x1000 | 0x0010  # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ


def counters(pid: int | None = None) -> _Counters:
    handle = _K32.GetCurrentProcess() if pid is None else _K32.OpenProcess(_QUERY, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"cannot open process {pid}")
    try:
        out = _Counters()
        out.cb = ctypes.sizeof(_Counters)
        if not _K32.K32GetProcessMemoryInfo(handle, ctypes.byref(out), out.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return out
    finally:
        if pid is not None:
            _K32.CloseHandle(handle)


def mb(value: float) -> str:
    return f"{value / 1e6:,.0f} MB"


def _select(start: str, end: str):
    from products.aegis import data

    data.BAR_CAP = 10**9  # this process only: the probe measures past today's cap
    store = data.ArchiveStore()
    return store, *store.bars("QQQ", "1m", start, end)


def backtest(start: str, end: str) -> None:
    from products.aegis.backtest import (
        BacktestSettings,
        _data_key,
        prepare_archive_frame,
        prepared_request,
        run_prepared,
    )
    from products.aegis.results import envelope
    from products.aegis.strategy import default_strategy

    base = counters().WorkingSetSize
    started = time.perf_counter()
    _, frame, pinned = _select(start, end)
    selected = counters().WorkingSetSize
    spec, settings = default_strategy(), BacktestSettings()
    prepared = prepare_archive_frame(frame, "QQQ")
    result = run_prepared(prepared_request(spec, settings), prepared, _data_key(prepared))
    run = envelope(result, spec, settings, pinned.model_dump(mode="json"), 0)
    stored = len(json.dumps(run, allow_nan=False))
    peak = counters().PeakWorkingSetSize
    bars = len(frame)
    print(
        f"backtest {bars:,} bars: base {mb(base)}, after select {mb(selected)}, peak {mb(peak)} "
        f"(+{mb(peak - selected)} over the selected frame, {(peak - selected) / bars:,.0f} B/bar), "
        f"stored run {stored / 1e6:.2f} MB, {time.perf_counter() - started:.1f} s"
    )


def worker(start: str, end: str) -> None:
    from products.aegis.backtest import prepare_archive_frame
    from products.aegis.pool import Pool
    from products.aegis.strategy import default_strategy

    _, frame, _ = _select(start, end)
    prepared = prepare_archive_frame(frame, "QQQ")
    pool = Pool(max_workers=1)
    pool.start(prepared, "QQQ", default_strategy().model_dump(mode="json"), {})
    cells = [
        (
            i,
            {
                "long_side.indicators.ema.length": 5 + (i // 10) * 2,
                "long_side.indicators.sma.length": 30 + (i % 10) * 5,
            },
        )
        for i in range(100)
    ]
    started = time.perf_counter()
    try:
        rows = pool.run_chunk(cells[:1], want_curve=False)  # the worker exists after a first cell
        assert pool._executor is not None
        [pid] = list(pool._executor._processes)
        idle = counters(pid)
        rows += pool.run_chunk(cells[1:], want_curve=False)
        busy = counters(pid)
    finally:
        pool.shutdown()
    valid = sum(1 for row in rows if row["valid"])
    bars = len(prepared)
    print(
        f"worker {bars:,} bars: after one cell private {mb(idle.PagefileUsage)}; 100 cells "
        f"({valid} valid) peak private {mb(busy.PeakPagefileUsage)}, peak working set "
        f"{mb(busy.PeakWorkingSetSize)}; {time.perf_counter() - started:.1f} s"
    )


if __name__ == "__main__":
    mode, first, last = sys.argv[1:4]
    {"backtest": backtest, "worker": worker}[mode](first, last)
