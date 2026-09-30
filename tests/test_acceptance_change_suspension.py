from types import SimpleNamespace as NS

import pytest
from trading_core.ledger import Ledger


@pytest.mark.parametrize(
    "owner,mission,enabled,epoch,expected",
    [
        ("triad", "trial", True, 4, True),
        ("aegis", "trial", True, 4, False),
        ("triad", "other", True, 4, False),
        ("triad", "trial", False, 4, False),
        ("triad", "trial", True, 3, False),
        ("triad", "trial", "true", 4, False),
    ],
)
def test_only_exact_operator_trial_is_exempt(owner, mission, enabled, epoch, expected):
    ledger = Ledger(NS(get=lambda identifier: NS(owner=owner, mission_id=mission)))
    control = {
        "epoch": 4,
        "change_limit_suspension": {"cycle_id": "trial", "enabled": enabled, "epoch": epoch},
    }
    assert ledger.change_limit_suspended(control, "work") is expected


def test_missing_grant_fails_closed():
    ledger = Ledger(NS(get=lambda _: (_ for _ in ()).throw(AssertionError())))
    assert not ledger.change_limit_suspended({"epoch": 4}, "work")
