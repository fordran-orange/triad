from datetime import timedelta
from unittest.mock import Mock

import pandas as pd
import pytest
from test_lab import START, experiment
from triad.lab.data import Archive
from triad.lab.engine import run_engine
from triad.lab.service import source_hash


def test_source_identity_ignores_checkout_line_endings(tmp_path):
    path = tmp_path / "engine.py"
    path.write_bytes(b"def run():\n    return 1\n")
    original = source_hash(tmp_path)
    path.write_bytes(b"def run():\r\n    return 1\r\n")
    assert source_hash(tmp_path) == original
    path.write_bytes(b"def run():\n    return 2\n")
    assert source_hash(tmp_path) != original


@pytest.mark.parametrize(
    "direction,exit_price,metric",
    [
        ("LONG", 50, "mae"),
        ("LONG", 150, "mfe"),
        ("SHORT", 150, "mae"),
        ("SHORT", 50, "mfe"),
    ],
)
def test_exit_gap_in_excursion_without_future_exit_bar_prices(direction, exit_price, metric):
    frame = pd.DataFrame(
        [
            {
                "timestamp": START + timedelta(minutes=i),
                "bar_end": START + timedelta(minutes=i + 1),
                "symbol": "LABTEST",
                "open": p,
                "high": p,
                "low": p,
                "close": p,
                "volume": 1,
            }
            for i, p in enumerate([100, 100, exit_price, 100, 100, 100])
        ]
    )
    # Exit at this open; later extremes must not count toward the closed trade.
    frame.loc[2, "high"] = 1000
    frame.loc[2, "low"] = 1
    trade = run_engine(
        frame, experiment(directions=(direction,), parameters={"period": 2, "hold": 1})
    )["trades"][0]
    assert trade[metric] == pytest.approx(-0.5 if metric == "mae" else 0.5)
    assert trade["mfe" if metric == "mae" else "mae"] == 0


@pytest.mark.parametrize("missing,zero_volume", [(False, False), (True, False), (False, True)])
def test_resample_optional_fields(missing, zero_volume):
    rows = [
        {
            "timestamp": START + timedelta(minutes=i),
            "bar_end": START + timedelta(minutes=i + 1),
            "symbol": "LABTEST",
            "open": 100 + i,
            "high": 100 + i,
            "low": 100 + i,
            "close": 100 + i,
            "volume": 0 if zero_volume else i + 1,
            "trade_count": 2,
            "vwap": 100 + i,
        }
        for i in range(5)
    ]
    if missing:
        rows[2].update(trade_count=None, vwap=None)
    archive = object.__new__(Archive)
    archive.load = lambda manifest: pd.DataFrame(rows)
    archive.publish = lambda output, *args, **kwargs: output
    bar = archive.derive(Mock(resolution="1m", dataset_id="base", raw_sources=[{}]), "5m")[0]
    if missing:
        assert bar["trade_count"] is None and bar["vwap"] is None
    else:
        assert bar["trade_count"] == 10
        if zero_volume:
            assert bar["vwap"] is None
        else:
            assert bar["vwap"] == pytest.approx(sum((100 + i) * (i + 1) for i in range(5)) / 15)
