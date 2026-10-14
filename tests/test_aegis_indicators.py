import math

import pandas as pd
import pytest
from products.aegis.indicators import IndicatorCache, compute
from products.aegis.strategy import IndicatorSpec

pytestmark = pytest.mark.aegis


def frame(closes):
    return pd.DataFrame({"close": closes, "open": closes, "high": closes, "low": closes})


def test_sma_and_ema_match_pandas_definitions():
    f = frame([1.0, 2.0, 3.0, 4.0])
    sma = compute(IndicatorSpec(id="s", kind="SMA", length=3), f)["s"].tolist()
    assert math.isnan(sma[0]) and math.isnan(sma[1]) and sma[2:] == [2.0, 3.0]
    ema = compute(IndicatorSpec(id="e", kind="EMA", length=3), f)["e"]
    expected = f.close.ewm(span=3, adjust=False, min_periods=3).mean()
    assert ema.tolist()[2:] == expected.tolist()[2:] and math.isnan(ema.tolist()[0])


def test_source_column_is_honoured_and_unknown_kind_raises():
    f = frame([1.0, 2.0, 3.0])
    f["open"] = [10.0, 20.0, 30.0]
    sma = compute(IndicatorSpec(id="s", kind="SMA", length=2, source="open"), f)["s"].tolist()
    assert sma[1:] == [15.0, 25.0]
    with pytest.raises(ValueError, match="unknown indicator kind"):
        IndicatorSpec(id="x", kind="XYZ", length=2)


def test_cache_returns_same_object_for_same_key_and_spec():
    cache = IndicatorCache()
    f = frame([1.0, 2.0, 3.0, 4.0])
    spec = IndicatorSpec(id="s", kind="SMA", length=2)
    first = cache.get("data-1", spec, f)
    second = cache.get("data-1", spec, f)
    assert first is second and cache.hits == 1
    other = cache.get("data-1", IndicatorSpec(id="s2", kind="SMA", length=3), f)
    assert other is not first and cache.hits == 1
    assert cache.get("data-2", spec, f) is not first and cache.hits == 1


def test_cache_evicts_oldest_data_key_beyond_the_bound():
    cache = IndicatorCache(max_data_keys=2)
    f = frame([1.0, 2.0, 3.0, 4.0])
    spec = IndicatorSpec(id="s", kind="SMA", length=2)
    cache.get("k1", spec, f)
    cache.get("k2", spec, f)
    cache.get("k3", spec, f)
    assert cache.data_keys == ["k2", "k3"]
    cache.get("k1", spec, f)  # evicted: recomputed, not a hit
    assert cache.hits == 0 and cache.data_keys == ["k3", "k1"]
    cache.get("k3", spec, f)
    assert cache.hits == 1


def test_cache_survives_concurrent_gets_with_eviction():
    import threading

    cache = IndicatorCache(max_data_keys=2)
    f = frame([float(i) for i in range(1, 40)])
    spec = IndicatorSpec(id="s", kind="SMA", length=3)
    errors = []

    def hammer(prefix):
        try:
            for i in range(300):
                cache.get(f"{prefix}-{i % 5}", spec, f)
        except Exception as exc:  # noqa: BLE001 - the test records any failure
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(p,)) for p in ("a", "b", "c", "d")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(cache.data_keys) <= 2


# --- Mission 5: the indicator library --------------------------------------------------------

NAN = float("nan")


def hlc(highs, lows, closes):
    return pd.DataFrame({"high": highs, "low": lows, "close": closes, "open": closes})


def values(series):
    return [None if math.isnan(v) else round(v, 5) for v in series.tolist()]


def test_rsi_uses_wilder_smoothing_seeded_by_the_mean():
    out = compute(IndicatorSpec(id="rsi", kind="RSI", length=2), frame([1.0, 2.0, 3.0, 2.0, 3.0]))
    assert list(out.columns) == ["rsi"]
    assert values(out["rsi"]) == [None, None, 100.0, 50.0, 75.0]


def test_atr_uses_true_range_from_the_previous_close():
    f = hlc([10, 12, 13, 11], [9, 10, 11, 8], [9.5, 11, 12, 9])
    out = compute(IndicatorSpec(id="atr", kind="ATR", length=2), f)
    assert values(out["atr"]) == [None, None, 2.25, 3.125]


def test_donchian_uses_the_previous_bars_only():
    f = hlc([10, 12, 13, 11], [9, 10, 11, 8], [9.5, 11, 12, 9])
    out = compute(IndicatorSpec(id="dc", kind="DONCHIAN", length=2), f)
    assert list(out.columns) == ["dc.upper", "dc.lower", "dc.middle"]
    assert values(out["dc.upper"]) == [None, None, 12.0, 13.0]
    assert values(out["dc.lower"]) == [None, None, 9.0, 10.0]
    assert values(out["dc.middle"]) == [None, None, 10.5, 11.5]


def test_bollinger_uses_the_population_deviation_and_multiplier():
    out = compute(
        IndicatorSpec(id="bb", kind="BB", length=2, params={"multiplier": 2}),
        frame([1.0, 3.0, 5.0]),
    )
    assert list(out.columns) == ["bb.upper", "bb.middle", "bb.lower"]
    assert values(out["bb.middle"]) == [None, 2.0, 4.0]
    assert values(out["bb.upper"]) == [None, 4.0, 6.0]
    assert values(out["bb.lower"]) == [None, 0.0, 2.0]


def test_macd_outputs_wait_for_the_signal_line():
    spec = IndicatorSpec(id="macd", kind="MACD", length=2, params={"slow": 3, "signal": 2})
    out = compute(spec, frame([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
    assert list(out.columns) == ["macd.line", "macd.signal", "macd.histogram"]
    assert values(out["macd.line"]) == [None, None, None, 0.39352, 0.44367, 0.47081]
    assert values(out["macd.signal"]) == [None, None, None, 0.3642, 0.41718, 0.45293]
    assert values(out["macd.histogram"]) == [None, None, None, 0.02932, 0.02649, 0.01788]


@pytest.mark.parametrize("kind", ["EMA", "SMA", "RSI", "ATR", "BB", "DONCHIAN", "MACD"])
def test_first_value_index_is_warmup_minus_one(kind):
    from products.aegis.kinds import KINDS, warmup

    n = 200
    closes = [100 + 10 * math.sin(i / 7) + 0.1 * i for i in range(n)]
    f = hlc([c + 1 for c in closes], [c - 1 for c in closes], closes)
    info = KINDS[kind]
    spec = IndicatorSpec(id="x", kind=kind, length=info.default_length)
    out = compute(spec, f)
    expected = warmup(kind, spec.length, spec.effective_params()) - 1
    for column in out.columns:
        assert out[column].first_valid_index() == expected, (kind, column)


def test_cache_distinguishes_parameters():
    cache = IndicatorCache()
    f = frame([float(i) for i in range(1, 30)])
    two = IndicatorSpec(id="bb", kind="BB", length=5, params={"multiplier": 2})
    three = IndicatorSpec(id="bb", kind="BB", length=5, params={"multiplier": 3})
    cache.get("k", two, f)
    cache.get("k", three, f)
    assert len(cache) == 2 and cache.hits == 0
    cache.get("k", IndicatorSpec(id="other", kind="BB", length=5), f)  # default multiplier 2
    assert len(cache) == 2 and cache.hits == 1
