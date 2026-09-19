"""Durable one-local-date product slot; enabled only after manual cycle acceptance."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from trading_core.work import uid

from products.triad.daily import Daily, DailySchedule


def scheduled_time(policy, date):
    """Skip nonexistent wall times; use first occurrence of an autumn fold."""
    hour, minute = map(int, policy.time.split(":"))
    zone = ZoneInfo(policy.timezone)
    target = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone, fold=0)
    restored = target.astimezone(UTC).astimezone(zone)
    return target if restored.replace(tzinfo=None) == target.replace(tzinfo=None) else None


def next_cycle(config, instant=None):
    if not config.get("enabled"):
        return None
    instant = instant or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Aware scheduler instant required")
    policy = DailySchedule.model_validate(
        {k: v for k, v in config.items() if k in DailySchedule.model_fields}
    )
    local = instant.astimezone(ZoneInfo(policy.timezone))
    for offset in range(9):
        date = local.date() + timedelta(days=offset)
        target = scheduled_time(policy, date)
        if (
            target is not None
            and date.weekday() in policy.days
            and date.isoformat() >= (config.get("effective_after") or date.isoformat())
            and target.astimezone(UTC) > instant.astimezone(UTC)
        ):
            return target.isoformat()
    return None


def tick(*, service=None, instant=None, run=None):
    service = service or Daily()
    config = service.schedule()
    if not config["enabled"]:
        return {"status": "DISABLED"}
    service.product.ledger.guard(epoch=config["control_epoch"])
    service.require_complete(config["manual_prerequisite"])
    instant = instant or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("Aware scheduler instant required")
    policy = DailySchedule.model_validate(
        {k: v for k, v in config.items() if k in DailySchedule.model_fields}
    )
    local = instant.astimezone(ZoneInfo(policy.timezone))
    date = local.date().isoformat()
    target = scheduled_time(policy, local.date())
    if (
        target is None
        or local.weekday() not in policy.days
        or date < config["effective_after"]
        or instant.astimezone(UTC) < target.astimezone(UTC)
    ):
        return {"status": "NOT_DUE", "next_cycle": next_cycle(config, instant)}
    if run is None:
        raise PermissionError("Scheduled dispatch requires a trusted product runner")
    # Date is deliberately independent of config revision/timezone: changing a
    # schedule cannot buy another primary change on the same recorded local date.
    with service.host.store.lease("triad-daily-schedule-slot"):
        latest = service.schedule()
        if latest["id"] != config["id"]:
            return {"status": "CONFIG_CHANGED"}
        claims = service.product.list("DailyScheduleClaim")
        if any(c["date"] == date for c in claims):
            return {"status": "ALREADY_CLAIMED", "date": date}
        service.product.ledger.guard(epoch=config["control_epoch"])
        identifier = uid()
        service.host.append(
            "DailyScheduleClaim",
            {
                "date": date,
                "cycle_id": identifier,
                "claimed_at": instant.isoformat(),
                "schedule_id": config["id"],
                "control_epoch": config["control_epoch"],
                "status": "CLAIMED",
                "automatic_retry": False,
            },
            owner="triad",
        )
    try:
        cycle = run(
            scheduled=True,
            cycle_id=identifier,
            expected_epoch=config["control_epoch"],
            schedule_id=config["id"],
        )
        return {"status": cycle["status"], "cycle_id": identifier}
    except Exception as exc:  # noqa: BLE001 - persist failed dispatch, never retry the date
        # If the runner failed before canonical creation, still retain a blocked
        # cycle rather than losing the date or silently replaying execution.
        try:
            service.current(identifier)
        except KeyError:
            service.history.blocked(cycle_id=identifier, scheduled=True, code=type(exc).__name__)
        return {"status": "BLOCKED", "cycle_id": identifier, "failure": type(exc).__name__}
