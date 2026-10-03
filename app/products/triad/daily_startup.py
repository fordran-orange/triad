"""Interruptible startup contention is waiting, never permission to replay work."""

import time
from contextlib import ExitStack, contextmanager
from zoneinfo import ZoneInfo

from trading_core.store import ConcurrentUpdate
from trading_core.work import now


class StartupDeferred(ConcurrentUpdate):
    """Nothing started; dispatcher may retry this identity after proving exit."""


@contextmanager
def execution_lease(
    service,
    cycle_id,
    *,
    scheduled=False,
    expected_epoch=None,
    schedule_id=None,
    attempt_id=None,
    timeout=300,
):
    started = time.monotonic()
    waiting = False
    last_notice = -30.0

    def authority():
        service.ledger.guard(epoch=expected_epoch)
        if scheduled:
            config = service.daily.schedule()
            if (
                not config["enabled"]
                or config["id"] != schedule_id
                or config["control_epoch"] != expected_epoch
            ):
                raise PermissionError("Scheduled authority changed while waiting for startup")
            if attempt_id:
                claims = service.daily.product.list(
                    "DailyScheduleClaim", matching={"cycle_id": cycle_id}
                )
                if (
                    not claims
                    or claims[-1]["date"]
                    != now().astimezone(ZoneInfo(config["timezone"])).date().isoformat()
                ):
                    raise PermissionError("Scheduled startup belongs to a different local date")

    while True:
        authority()
        stack = ExitStack()
        try:
            stack.enter_context(service.host.store.lease("triad-daily-product-execution"))
        except ConcurrentUpdate as exc:
            stack.close()
            elapsed = time.monotonic() - started
            if cycle_id and (elapsed - last_notice >= 30 or elapsed >= timeout):
                holders = [
                    {**h, "backend_start": str(h.get("backend_start"))}
                    for h in getattr(exc, "lease_holders", ())
                ]
                service.host.append(
                    "DailyStartupState",
                    {
                        "cycle_id": cycle_id,
                        "attempt_id": attempt_id,
                        "state": "DEFERRED" if elapsed >= timeout else "WAITING",
                        "reason": "Execution lock is busy; no product work started",
                        "holders": holders,
                        "control_epoch": expected_epoch,
                        "schedule_id": schedule_id,
                        "recorded_at": now().isoformat(),
                    },
                    owner="triad",
                )
                last_notice = elapsed
            waiting = True
            if elapsed >= timeout:
                raise StartupDeferred("Startup deferred; execution lock remained busy") from exc
            time.sleep(min(1, timeout - elapsed))
            continue
        try:
            authority()
            if cycle_id:
                service.host.append(
                    "DailyStartupState",
                    {
                        "cycle_id": cycle_id,
                        "attempt_id": attempt_id,
                        "state": "OWNED",
                        "waited": waiting,
                        "control_epoch": expected_epoch,
                        "schedule_id": schedule_id,
                        "recorded_at": now().isoformat(),
                    },
                    owner="triad",
                )
            yield
        finally:
            stack.close()
        return
