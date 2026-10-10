import json

from products.aegis.backtest import BacktestRequest, markers, run_backtest
from products.aegis.results import canonical_payload, result_hash
from products.aegis.strategy import apply_parameters, default_strategy
from test_aegis_backtest import bars

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
