"""Opt the current process out of Windows power throttling (efficiency mode).

Workers launched without a window by the supervisor are scheduled by Windows 11 as background
work on hybrid CPUs; measured in Aegis Mission 3, the same backtest took about eight times
longer than in a foreground process. This is the documented per-process opt-out
(`SetProcessInformation(ProcessPowerThrottling)` with execution speed never throttled). It
touches nothing outside the calling process, is a no-op off Windows, logs when refused, and
never raises, so a host that refuses it still starts its worker.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger("trading_core.process_power")

_VERSION = 1
_EXECUTION_SPEED = 0x1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
_PROCESS_POWER_THROTTLING = 4  # PROCESS_INFORMATION_CLASS.ProcessPowerThrottling


def _set_process_information(state) -> tuple[bool, int]:
    """The raw Windows call; returns (ok, last_error). Separated so tests can stand in for it."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.SetProcessInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetProcessInformation.restype = ctypes.c_int
    ok = kernel32.SetProcessInformation(
        kernel32.GetCurrentProcess(),
        _PROCESS_POWER_THROTTLING,
        ctypes.byref(state),
        ctypes.sizeof(state),
    )
    return bool(ok), ctypes.get_last_error()


def opt_out_of_power_throttling() -> bool:
    """Ask Windows never to throttle this process's execution speed. True when applied."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        class State(ctypes.Structure):
            _fields_ = [
                ("Version", ctypes.c_uint32),
                ("ControlMask", ctypes.c_uint32),
                ("StateMask", ctypes.c_uint32),
            ]

        # Control execution speed; a state mask of 0 means "never throttle".
        ok, error = _set_process_information(State(_VERSION, _EXECUTION_SPEED, 0))
    except (OSError, AttributeError, ValueError) as exc:
        log.warning("power-throttling opt-out unavailable: %s", exc)
        return False
    if not ok:
        log.warning("power-throttling opt-out refused: error %s", error)
        return False
    log.info("power-throttling opt-out applied (execution speed never throttled)")
    return True


__all__ = ["opt_out_of_power_throttling"]
