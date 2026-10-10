import math

import pandas as pd
import pytest
from products.aegis.indicators import IndicatorCache, compute
from products.aegis.strategy import IndicatorSpec


def frame(closes):
    return pd.DataFrame({"close": closes, "open": closes, "high": closes, "low": closes})


def test_sma_and_ema_match_pandas_definitions():
    f = frame([1.0, 2.0, 3.0, 4.0])
    sma = compute(IndicatorSpec(id="s", kind="SMA", length=3), f).tolist()
    assert math.isnan(sma[0]) and math.isnan(sma[1]) and sma[2:] == [2.0, 3.0]
    ema = compute(IndicatorSpec(id="e", kind="EMA", length=3), f)
    expected = f.close.ewm(span=3, adjust=False, min_periods=3).mean()
    assert ema.tolist()[2:] == expected.tolist()[2:] and math.isnan(ema.tolist()[0])


def test_source_column_is_honoured_and_unknown_kind_raises():
    f = frame([1.0, 2.0, 3.0])
    f["open"] = [10.0, 20.0, 30.0]
    sma = compute(IndicatorSpec(id="s", kind="SMA", length=2, source="open"), f).tolist()
    assert sma[1:] == [15.0, 25.0]
    with pytest.raises(ValueError, match="unknown indicator kind"):
        compute(IndicatorSpec(id="x", kind="RSI", length=2), f)


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
