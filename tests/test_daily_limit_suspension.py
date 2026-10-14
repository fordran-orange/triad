from datetime import UTC, datetime, timedelta

import pytest
from triad.day3.ledger import Ledger

pytestmark = pytest.mark.triad


def grant(at):
    return {
        "daily_execution_limit_suspension": {
            "operator_authorized": True,
            "scope": ["max_tokens_day", "max_compute_seconds_day"],
            "starts_at": at.isoformat(),
            "expires_at": (at + timedelta(hours=10)).isoformat(),
        }
    }


def test_suspension_expires_without_a_restart():
    at = datetime(2026, 9, 18, 18, tzinfo=UTC)
    control = grant(at)
    assert Ledger.daily_execution_limits_suspended(control, at)
    assert not Ledger.daily_execution_limits_suspended(control, at - timedelta(seconds=1))
    assert not Ledger.daily_execution_limits_suspended(control, at + timedelta(hours=10))


@pytest.mark.parametrize("invalid", [None, [], {}, {"starts_at": "bad"}])
def test_malformed_suspension_fails_closed(invalid):
    assert not Ledger.daily_execution_limits_suspended(
        {"daily_execution_limit_suspension": invalid}
    )


def test_unauthorized_or_unbounded_grants_fail_closed():
    at = datetime(2026, 9, 18, 18, tzinfo=UTC)
    control = grant(at)
    control["daily_execution_limit_suspension"]["operator_authorized"] = False
    assert not Ledger.daily_execution_limits_suspended(control, at)
    control = grant(at)
    control["daily_execution_limit_suspension"]["expires_at"] = (at + timedelta(days=2)).isoformat()
    assert not Ledger.daily_execution_limits_suspended(control, at)
