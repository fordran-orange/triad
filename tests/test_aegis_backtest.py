from datetime import UTC, datetime, timedelta

from products.aegis.backtest import BacktestRequest, run_backtest
from products.aegis.indicators import IndicatorCache
from products.aegis.strategy import apply_parameters, default_strategy


def bars():
    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    closes = [100.0] * 35
    closes += [100 + i for i in range(1, 16)]
    closes += [115 - i * 1.5 for i in range(1, 21)]
    closes += [85 + i * 1.8 for i in range(1, 21)]
    output = []
    previous = closes[0]
    for i, close in enumerate(closes):
        opened = previous
        output.append(
            {
                "timestamp": start + timedelta(minutes=30 * i),
                "symbol": "QQQ",
                "open": opened,
                "high": max(opened, close) + 0.5,
                "low": min(opened, close) - 0.5,
                "close": close,
                "volume": 1000 + i,
            }
        )
        previous = close
    return output


def test_reference_backtest_returns_directional_and_combined_results():
    request = BacktestRequest(strategy=default_strategy(), bars=bars())
    result = run_backtest(request)

    assert result["lookahead_policy"] == "closed-bar signal; next-bar-open fill"
    assert result["long"]["metrics"]["trade_count"] >= 1
    assert result["short"]["metrics"]["trade_count"] >= 1
    assert set(result) >= {"long", "short", "combined", "temporal"}
    assert result["combined"]["metrics"]["trade_count"] == (
        result["long"]["metrics"]["trade_count"] + result["short"]["metrics"]["trade_count"]
    )
    assert result["long"]["enabled"] is True and result["short"]["enabled"] is True


def test_entry_fill_occurs_after_signal_bar():
    request = BacktestRequest(strategy=default_strategy(), bars=bars())
    result = run_backtest(request)

    for side in ("long", "short"):
        for trade in result[side]["trades"]:
            signal = datetime.fromisoformat(trade["signal_time"])
            entry = datetime.fromisoformat(trade["entry_time"])
            assert entry > signal


def test_long_and_short_can_be_disabled_independently():
    strategy = default_strategy()
    strategy.short_side.enabled = False
    result = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))

    assert result["long"]["metrics"]["trade_count"] >= 1
    assert result["short"]["metrics"]["trade_count"] == 0
    assert result["short"]["enabled"] is False and result["short"]["series"] == {}


def test_opening_window_is_preserved_in_temporal_breakdown():
    strategy = default_strategy()
    result = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))

    assert "ALL" in result["temporal"]["combined"]
    # Window keys appear only when a trade actually intersects the configured window.
    assert all(
        key == "ALL" or key.startswith(("CLOCK:", "EVENT:", "CROSSOVER:"))
        for key in result["temporal"]["combined"]
    )


def test_sides_simulate_from_their_own_indicator_lengths():
    s = default_strategy()
    s.short_side = apply_parameters(
        s.short_side, {"indicators.ema.length": 6, "indicators.sma.length": 20}
    )
    r = run_backtest(BacktestRequest(strategy=s, bars=bars()))
    assert r["long"]["series"].keys() == {"ema", "sma"}
    assert len(r["long"]["series"]["ema"]) == r["bars"]
    assert r["long"]["series"]["ema"] != r["short"]["series"]["ema"]
    assert r["long"]["series"]["ema"][:8] == [None] * 8  # warm-up gaps are null, not NaN
    assert r["short"]["series"]["ema"][5] is not None


def test_shared_indicator_cache_is_reused_across_runs():
    cache = IndicatorCache()
    request = BacktestRequest(strategy=default_strategy(), bars=bars())
    run_backtest(request, cache=cache)
    run_backtest(request, cache=cache)
    assert cache.hits >= 2
