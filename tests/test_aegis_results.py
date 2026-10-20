import json

import pytest
from products.aegis.backtest import BacktestRequest, BacktestSettings, markers, run_backtest
from products.aegis.results import (
    EQUITY_POINTS,
    _clean,
    canonical_payload,
    envelope,
    result_hash,
    slim_equity,
    stream_hash,
)
from products.aegis.strategy import apply_parameters, default_strategy
from test_aegis_backtest import bars

pytestmark = pytest.mark.aegis

DATA = {"symbol": "QQQ", "source": "test", "data_hash": "abc"}


def test_identical_requests_yield_identical_hash():
    first = run_backtest(BacktestRequest(strategy=default_strategy(), bars=bars()))
    second = run_backtest(BacktestRequest(strategy=default_strategy(), bars=bars()))
    a = canonical_payload(first, default_strategy(), DATA)
    b = canonical_payload(second, default_strategy(), DATA)
    assert a == b
    assert result_hash(a) == result_hash(b)
    assert len(result_hash(a)) == 64


def test_hash_ignores_envelope_fields():
    result = run_backtest(BacktestRequest(strategy=default_strategy(), bars=bars()))
    payload = canonical_payload(result, default_strategy(), DATA)
    envelope_a = {"run_id": "r-1", "created_at": "2026-10-09T00:00:00Z", "elapsed_ms": 5, **payload}
    envelope_b = {"run_id": "r-2", "created_at": "2026-10-10T00:00:00Z", "elapsed_ms": 9, **payload}
    strip = {"run_id", "created_at", "elapsed_ms"}
    assert {k: v for k, v in envelope_a.items() if k not in strip} == payload
    assert result_hash({k: v for k, v in envelope_b.items() if k not in strip}) == result_hash(
        payload
    )
    assert set(payload) == {"strategy", "data", "long", "short", "combined", "temporal", "markers"}
    json.dumps(payload, allow_nan=False)  # canonical payload is strict JSON


def test_hash_changes_when_a_parameter_changes():
    base = default_strategy()
    changed = default_strategy()
    changed.short_side = apply_parameters(changed.short_side, {"indicators.ema.length": 6})
    a = canonical_payload(run_backtest(BacktestRequest(strategy=base, bars=bars())), base, DATA)
    b = canonical_payload(
        run_backtest(BacktestRequest(strategy=changed, bars=bars())), changed, DATA
    )
    assert result_hash(a) != result_hash(b)
    c = canonical_payload(
        run_backtest(BacktestRequest(strategy=base, bars=bars())),
        base,
        {**DATA, "data_hash": "zzz"},
    )
    assert result_hash(a) != result_hash(c)


def test_exposure_is_fraction_of_bars_in_position():
    result = run_backtest(BacktestRequest(strategy=default_strategy(), bars=bars()))
    for side in ("long", "short", "combined"):
        exposure = result[side]["metrics"]["exposure"]
        assert 0.0 < exposure <= 1.0
    assert result["combined"]["metrics"]["exposure"] >= max(
        result["long"]["metrics"]["exposure"], result["short"]["metrics"]["exposure"]
    )
    strategy = default_strategy()
    strategy.short_side.enabled = False
    disabled = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))
    assert disabled["short"]["metrics"]["exposure"] == 0.0


def test_markers_have_entry_and_exit_per_trade():
    result = run_backtest(BacktestRequest(strategy=default_strategy(), bars=bars()))
    points = markers(result)
    assert len(points) == 2 * result["combined"]["metrics"]["trade_count"]
    assert {p["kind"] for p in points} == {"entry", "exit"}
    assert {p["side"] for p in points} == {"LONG", "SHORT"}
    first = points[0]
    assert isinstance(first["time"], int) and first["time"] > 1_600_000_000_000
    assert isinstance(first["price"], float)
    assert points == sorted(points, key=lambda p: (p["time"], p["side"], p["kind"]))


# --- Mission 10: slim saved runs, the hash computed before slimming ---------------------------------


def _wave_run(strategy=None, n=4_000):
    from test_aegis_walkforward import wave_bars

    spec = strategy or default_strategy()
    return run_backtest(BacktestRequest(strategy=spec, bars=wave_bars(n=n))), spec


def test_stream_hash_equals_the_canonical_hash():
    result, spec = _wave_run()
    payload = canonical_payload(result, spec, DATA)
    assert stream_hash(payload) == result_hash(payload)
    nested = {"b": [{"z": 1, "a": [1.5, None, "é"]}] * 3, "a": {"y": {"x": True}}, "ü": "ß"}
    assert stream_hash(nested) == result_hash(nested)
    big = {"points": [{"t": i, "v": i / 3} for i in range(25_000)], "empty": [], "one": [7]}
    assert stream_hash(big) == result_hash(big)


def test_slim_equity_keeps_endpoints():
    points = [{"timestamp": str(i), "equity": float(i), "drawdown": 0.0} for i in range(10_000)]
    out = slim_equity(points)
    assert len(out) == EQUITY_POINTS == 2_000 and out[0] is points[0] and out[-1] is points[-1]
    short = points[:1_500]
    assert slim_equity(short) == short
    assert slim_equity([]) == []


def test_the_saved_run_is_slim_and_keeps_its_hash():
    result, spec = _wave_run()
    long_bars, short_bars = len(result["long"]["equity"]), len(result["short"]["equity"])
    assert long_bars > EQUITY_POINTS  # the test needs a run longer than the stored resolution
    run = envelope(result, spec, BacktestSettings(), DATA, 5)
    assert run["result_hash"] == result_hash(canonical_payload(result, spec, DATA))
    assert "series" not in run and "markers" not in run["result"]
    for side in ("long", "short"):
        assert "series" not in run["result"][side]
        assert len(run["result"][side]["equity"]) <= EQUITY_POINTS
    assert run["stored"] == {"format": 2, "equity_points": {"long": long_bars, "short": short_bars}}
    payload = canonical_payload(result, spec, DATA)
    for side in ("long", "short", "combined"):
        assert run["result"][side]["trades"] == payload[side]["trades"]
        assert run["result"][side]["metrics"] == payload[side]["metrics"]
    assert run["result"]["combined"]["equity"] == payload["combined"]["equity"]
    assert run["result"]["temporal"] == payload["temporal"] and run["markers"] == payload["markers"]
    json.dumps(run, allow_nan=False)


def test_clean_does_not_copy_a_clean_structure():
    clean = {"a": [1.0, {"b": [2.0, None]}], "c": "x"}
    assert _clean(clean) is clean
    dirty = {"a": [1.0, float("nan")], "b": {"c": float("inf")}, "d": [1]}
    out = _clean(dirty)
    assert out == {"a": [1.0, None], "b": {"c": None}, "d": [1]} and out["d"] is dirty["d"]


def test_slim_run_of_a_disabled_side():  # Review Focus 2
    spec = default_strategy()
    spec = spec.model_copy(
        update={"short_side": spec.short_side.model_copy(update={"enabled": False})}
    )
    result, spec = _wave_run(spec)
    run = envelope(result, spec, BacktestSettings(), DATA, 5)
    assert run["result"]["short"]["equity"] == [] and run["stored"]["equity_points"]["short"] == 0
