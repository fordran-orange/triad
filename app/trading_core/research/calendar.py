"""Replaceable bounded XNYS 2026 calendar. Unknown years fail closed."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
HOLIDAYS = {
    date.fromisoformat(s)
    for s in (
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
        "2026-07-03",
        "2026-09-07",
        "2026-11-26",
        "2026-12-25",
    )
}
EARLY = {date(2026, 11, 27), date(2026, 12, 24)}


class Calendar:
    version = "XNYS-2026-v1"

    def bounds(self, day):
        if day.year != 2026:
            raise ValueError("Calendar coverage is 2026 only")
        if day.weekday() >= 5 or day in HOLIDAYS:
            return None
        return (
            datetime.combine(day, time(9, 30), NY).astimezone(UTC),
            datetime.combine(day, time(13 if day in EARLY else 16), NY).astimezone(UTC),
        )

    def classify(self, timestamp):
        if timestamp.tzinfo is None:
            raise ValueError("Aware timestamp required")
        local = timestamp.astimezone(NY)
        bounds = self.bounds(local.date())
        if not bounds:
            return "HOLIDAY" if local.date() in HOLIDAYS else "CLOSED"
        if bounds[0] <= timestamp < bounds[1]:
            return "REGULAR"
        if time(4) <= local.time().replace(tzinfo=None) < time(9, 30):
            return "PRE_MARKET"
        late_close = time(17 if local.date() in EARLY else 20)
        if bounds[1] <= timestamp and local.time().replace(tzinfo=None) < late_close:
            return "AFTER_HOURS"
        return "CLOSED"

    def expected(self, start, end):
        if start.tzinfo is None or end.tzinfo is None or end <= start or (end - start).days > 32:
            raise ValueError("Bounded aware interval required")
        result = []
        day = start.astimezone(NY).date()
        while day <= end.astimezone(NY).date():
            bounds = self.bounds(day)
            if bounds:
                minute = bounds[0]
                while minute < bounds[1]:
                    if start <= minute < end:
                        result.append(minute)
                    minute += timedelta(minutes=1)
            day += timedelta(days=1)
        return result
