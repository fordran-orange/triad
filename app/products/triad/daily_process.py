"""Dispatch scheduled cycles outside the worker they may restart."""

import os
import subprocess
import sys
import threading
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
    attempt_id = service.host.append(
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
        "--startup-attempt-id",
        attempt_id,
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
            {
                "cycle_id": cycle_id,
                "attempt_id": attempt_id,
                "pid": process.pid,
                **process_info(process.pid),
            },
            owner="triad",
        )
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        raise

    def exited():
        process.wait()
        from products.triad.daily_wakeup import wake

        wake()

    threading.Thread(target=exited, daemon=True).start()
    return {"status": "STARTING", "cycle_id": cycle_id, "pid": process.pid}


def reconcile(service=None):
    from trading_core.store import ConcurrentUpdate

    from products.triad.daily import Daily

    service = service or Daily()
    try:
        # Routine monitoring must never steal the runner's startup lease.
        with service.host.store.lease("triad-daily-process-monitor"):
            return _reconcile_idle(service)
    except ConcurrentUpdate:
        return  # Another monitor is reconciling this state.


def _reconcile_idle(service):
    from products.triad.daily import TERMINAL

    processes = {r["cycle_id"]: r for r in service.product.list("DailyDispatchProcess")}
    dispatches = {r["cycle_id"]: r for r in service.product.list("DailyDispatch")}
    for dispatch in dispatches.values():
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
        from trading_core.store import ConcurrentUpdate

        try:
            with service.host.store.lease("triad-daily-product-execution"):
                attempts = service.product.list("DailyDispatch", matching={"cycle_id": cycle_id})
                if attempts and attempts[-1]["id"] != dispatch["id"]:
                    continue
                refreshed = service.product.list(
                    "DailyDispatchProcess", matching={"cycle_id": cycle_id}
                )
                if refreshed and (not process or refreshed[-1]["id"] != process["id"]):
                    continue
                if process:
                    observed = process_info(process["pid"])
                    if observed["state"] == "UNKNOWN" or (
                        observed["state"] == "RUNNING"
                        and observed.get("creation_id") == process.get("creation_id")
                    ):
                        continue
                # A runner may have created a cycle after the initial read.
                try:
                    latest = service.current(cycle_id)
                except KeyError:
                    latest = None
                if latest is not None and (cycle is None or latest["status"] in TERMINAL):
                    continue
                if not latest and _retry_unstarted(service, dispatch, process):
                    continue
                if latest:
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
        except ConcurrentUpdate:
            continue  # Running work owns all lifecycle writes.


def _retry_unstarted(service, dispatch, process):
    """Only known contention exits with no canonical work may reuse the claim."""
    from zoneinfo import ZoneInfo

    cycle_id = dispatch["cycle_id"]
    states = service.product.list("DailyStartupState", matching={"cycle_id": cycle_id})
    if not process or not states or states[-1]["state"] != "DEFERRED":
        return False
    if (
        not process.get("attempt_id")
        or process["attempt_id"] != dispatch["id"]
        or states[-1].get("attempt_id") != process["attempt_id"]
    ):
        return False
    current = process_info(process["pid"])
    if current["state"] != "EXITED" or (current.get("exit_code") not in {None, 75}):
        return False
    config = service.schedule()
    day = now().astimezone(ZoneInfo(config["timezone"])).date().isoformat()
    claims = service.product.list("DailyScheduleClaim", matching={"cycle_id": cycle_id})
    if not claims or claims[-1]["date"] != day:
        return False
    if (
        not config["enabled"]
        or config["id"] != dispatch["schedule_id"]
        or config["control_epoch"] != dispatch["control_epoch"]
    ):
        return False
    service.product.ledger.guard(epoch=dispatch["control_epoch"])
    retries = service.product.list("DailyStartupRetry", matching={"cycle_id": cycle_id})
    if len(retries) >= 288:
        return False
    with service.host.store.connect() as conn:
        if conn.execute(
            "SELECT 1 FROM core.work_items WHERE mission_id=%s LIMIT 1", (cycle_id,)
        ).fetchone():
            return False
        if conn.execute(
            "SELECT 1 FROM core.intelligence_records WHERE payload->>'mission_id'=%s LIMIT 1",
            (cycle_id,),
        ).fetchone():
            return False
        if conn.execute(
            "SELECT 1 FROM core.day3_records WHERE kind='AgentRunRequest' "
            "AND payload->>'mission_id'=%s LIMIT 1",
            (cycle_id,),
        ).fetchone():
            return False
    service.require_complete(config["manual_prerequisite"])
    service.host.append(
        "DailyStartupRetry",
        {
            "cycle_id": cycle_id,
            "previous_pid": process["pid"],
            "reason": "Stopped before creation on execution-lock contention",
            "recorded_at": now().isoformat(),
        },
        owner="triad",
    )
    launch(
        cycle_id=cycle_id,
        scheduled=True,
        expected_epoch=dispatch["control_epoch"],
        schedule_id=dispatch["schedule_id"],
    )
    return True
