"""Mission 10 Task 4: display candles and indicators for long ranges (spec §7)."""

import numpy as np
import pytest
from test_aegis_api import RANGE, client  # noqa: F401 - the shared API fixture

pytestmark = pytest.mark.aegis


def test_display_timeframe_at_the_boundary():  # Review Focus 3
    from products.aegis.display import MAX_DISPLAY_BARS, choose_timeframe

    assert MAX_DISPLAY_BARS == 20_000
    assert choose_timeframe("1m", {"1m": 20_000}, 20_000) == "1m"
    assert choose_timeframe("1m", {"1m": 20_001, "15m": 1_334}, 20_000) == "15m"
    assert choose_timeframe("1D", {"1D": 50_000}, 20_000) == "1D"


def test_sample_at_buckets_takes_the_last_native_value():
    from products.aegis.display import sample_at_buckets

    native = np.array([0, 1, 2, 9, 10, 11], dtype=np.int64)
    values = [1.0, 2.0, None, 7.0, 8.0, 9.0]
    # buckets [0, 5), [5, 9) (empty), [9, end]: the last native value of each, None when empty
    assert sample_at_buckets(native, values, np.array([0, 5, 9]), 11) == [None, None, 9.0]
    assert sample_at_buckets(native, [1.0, 2.0, 3.0, 7.0, 8.0, 9.0], np.array([0, 5, 9]), 11) == [
        3.0,
        None,
        9.0,
    ]


def _bars(c, **params):
    response = c.get(
        "/aegis/api/data/bars", params={"symbol": "QQQ", "timeframe": "1m", **RANGE, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_bars_route_aggregates_a_long_window(client):  # noqa: F811
    c, _, _ = client
    native = _bars(c)
    assert native["count"] == native["shown"] == 780 and native["display_timeframe"] == "1m"
    wide = _bars(c, max_bars=100)
    assert wide["count"] == 780 and wide["shown"] == len(wide["bars"]) <= 100
    assert wide["display_timeframe"] == "15m" and wide["shown"] == 52
    assert wide["bars"][0]["time"] == native["bars"][0]["time"]
    first = native["bars"][0]["time"]
    narrow = _bars(c, max_bars=100, from_ms=first, to_ms=first + 50 * 60_000)
    assert narrow["display_timeframe"] == "1m" and narrow["shown"] == 51
    assert narrow["bars"] == native["bars"][:51] and narrow["count"] == 780
    assert narrow["window"] == {"from_ms": first, "to_ms": first + 50 * 60_000}


def test_indicators_follow_the_display_bars(client):  # noqa: F811
    c, _, _ = client
    body = {
        "symbol": "QQQ",
        "timeframe": "1m",
        **RANGE,
        "indicators": [{"id": "s", "kind": "SMA", "length": 5}],
    }
    native = c.post("/aegis/api/indicators", json=body).json()
    shown = c.post("/aegis/api/indicators", json={**body, "max_bars": 100}).json()
    bars = _bars(c, max_bars=100)["bars"]
    assert shown["display_timeframe"] == "15m"
    assert shown["times"] == [bar["time"] for bar in bars] and len(shown["series"]["s"]) == len(
        bars
    )
    times = np.array(native["times"])
    for k, start in enumerate(shown["times"]):
        end = shown["times"][k + 1] if k + 1 < len(shown["times"]) else times[-1] + 1
        last = int(np.searchsorted(times, end, side="left")) - 1
        assert times[last] >= start and shown["series"]["s"][k] == native["series"]["s"][last]


def test_at_least_keeps_the_candles_this_coarse(client):  # noqa: F811 - QA D1
    """A zoom that must not go finer (more of the selection after a coarser swap, or a zoom-out at
    the chart's limit) asks for candles at least this coarse, even where finer ones would fit."""
    c, _, _ = client
    native = _bars(c)
    coarse = _bars(c, max_bars=100_000, at_least="15m")
    assert coarse["display_timeframe"] == "15m" and coarse["shown"] == 52 and coarse["count"] == 780
    assert (
        _bars(c, max_bars=100_000, at_least="1m")["bars"] == native["bars"]
    )  # the native one: no-op
    assert (
        _bars(c, max_bars=10, at_least="15m")["display_timeframe"] == "1D"
    )  # still within max_bars
    bad = c.get(
        "/aegis/api/data/bars",
        params={"symbol": "QQQ", "timeframe": "1m", **RANGE, "max_bars": 100, "at_least": "2h"},
    )
    assert bad.status_code == 422
    body = {
        "symbol": "QQQ",
        "timeframe": "1m",
        **RANGE,
        "indicators": [{"id": "s", "kind": "SMA", "length": 5}],
        "max_bars": 100_000,
        "at_least": "15m",
    }
    series = c.post("/aegis/api/indicators", json=body).json()
    assert series["display_timeframe"] == "15m"
    assert series["times"] == [bar["time"] for bar in coarse["bars"]]
