"""Dispatch scheduled cycles outside the worker they may restart."""

import os
import subprocess
import sys
from datetime import datetime, timedelta

from trading_core.settings import ROOT
from trading_core.work import now


def process_info(pid):
    """Read Windows process identity without confusing a reused PID with this run."""
    if os.name != "nt":
        return {"state": "UNKNOWN"}
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return {"state": "EXITED" if ctypes.get_last_error() == 87 else "UNKNOWN"}
    try:
        exit_code = wintypes.DWORD()
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetExitCodeProcess(
            handle, ctypes.byref(exit_code)
        ) or not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return {"state": "UNKNOWN"}
        return {
            "state": "RUNNING" if exit_code.value == 259 else "EXITED",
            "creation_id": f"{times[0].dwHighDateTime:08x}{times[0].dwLowDateTime:08x}",
            "exit_code": exit_code.value,
        }
    finally:
        kernel.CloseHandle(handle)


def launch(**kwargs):
    cycle_id = kwargs["cycle_id"]
    from uuid import UUID

    UUID(cycle_id)
    from products.triad.daily import Daily

    service = Daily()
    service.host.append(
        "DailyDispatch",
        {
            "cycle_id": cycle_id,
            "created_at": now().isoformat(),
            "control_epoch": kwargs["expected_epoch"],
            "schedule_id": kwargs["schedule_id"],
        },
        owner="triad",
    )
    log = ROOT / "logs" / ("daily-" + cycle_id + ".log")
    args = [
        sys.executable,
        str(ROOT / "tools/run_daily_product_cycle.py"),
        "--operator-authorized",
        "--cycle-id",
        cycle_id,
        "--scheduled",
        "--expected-epoch",
        str(kwargs["expected_epoch"]),
        "--schedule-id",
        kwargs["schedule_id"],
    ]
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with log.open("ab") as output:
        process = subprocess.Popen(
            args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output, **options
        )
    try:
        service.host.append(
            "DailyDispatchProcess",
            {"cycle_id": cycle_id, "pid": process.pid, **process_info(process.pid)},
            owner="triad",
        )
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        raise
    return {"status": "DISPATCHED", "cycle_id": cycle_id, "pid": process.pid}


def reconcile(service=None):
    from trading_core.store import ConcurrentUpdate

    from products.triad.daily import Daily

    service = service or Daily()
    try:
        # Read process identity and lifecycle only after acquiring the runner's
        # lease. Recovery may atomically replace an exited scheduled PID.
        with service.host.store.lease("triad-daily-product-execution"):
            return _reconcile_idle(service)
    except ConcurrentUpdate:
        return  # A live runner owns lifecycle transitions.


def _reconcile_idle(service):
    from products.triad.daily import TERMINAL

    processes = {r["cycle_id"]: r for r in service.product.list("DailyDispatchProcess")}
    for dispatch in service.product.list("DailyDispatch"):
        cycle_id = dispatch["cycle_id"]
        try:
            cycle = service.current(cycle_id)
            if cycle["status"] in TERMINAL:
                continue
        except KeyError:
            cycle = None
        process = processes.get(cycle_id)
        if process:
            current = process_info(process["pid"])
            if current["state"] == "UNKNOWN" or (
                current["state"] == "RUNNING"
                and current.get("creation_id") == process.get("creation_id")
            ):
                continue
        elif now() - datetime.fromisoformat(dispatch["created_at"]) < timedelta(minutes=2):
            continue
        if cycle:
            service.transition(
                cycle_id,
                "BLOCKED",
                ["Daily runner exited before completion"],
                failures=(
                    {
                        "code": "DailyRunnerExited",
                        "message": "Scheduled runner exited; retained for inspection without replay",
                    },
                ),
            )
        else:
            service.history.blocked(
                cycle_id=cycle_id,
                scheduled=True,
                code="DailyRunnerExitedBeforeCreation",
                cycle_type="DAILY_PRODUCT",
                control_epoch=dispatch["control_epoch"],
            )
