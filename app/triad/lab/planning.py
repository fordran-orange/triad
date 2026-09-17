"""Explicit walk-forward window skeleton; no optimizer or validation claim."""

from datetime import timedelta


def walk_forward_windows(start, end, train_days, test_days, maximum=8):
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not 1 <= train_days <= 365
        or not 1 <= test_days <= 90
        or not 1 <= maximum <= 16
    ):
        raise ValueError("Bounded aware walk-forward configuration required")
    windows = []
    cursor = start
    while cursor + timedelta(days=train_days + test_days) <= end:
        boundary = cursor + timedelta(days=train_days)
        windows.append(
            {
                "training": [cursor.isoformat(), boundary.isoformat()],
                "test": [boundary.isoformat(), (boundary + timedelta(days=test_days)).isoformat()],
                "parameter_selection": "NOT_IMPLEMENTED",
                "validation_status": "NOT_RUN",
            }
        )
        if len(windows) > maximum:
            raise ValueError("Walk-forward window ceiling")
        cursor += timedelta(days=test_days)
    return windows
