from datetime import UTC, datetime, timedelta

import pytest
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


def test_insufficient_bars_for_indicator_warmup_is_rejected():
    import pytest

    strategy = default_strategy()
    long_side = apply_parameters(strategy.long_side, {"indicators.sma.length": 100})
    request = BacktestRequest(
        strategy=strategy.model_copy(update={"long_side": long_side}), bars=bars()
    )
    with pytest.raises(ValueError, match="warm-up"):
        run_backtest(request)  # 91 bars cannot warm a 100-period indicator


def test_evaluate_from_blocks_entries_and_withholds_equity_before_it():
    from datetime import UTC, datetime

    from products.aegis.backtest import BacktestSettings

    rows = bars()
    boundary = datetime(2026, 1, 6, 14, 30, tzinfo=UTC)  # bar index 48 of the 90 synthetic bars
    settings = BacktestSettings(evaluate_from=boundary)
    result = run_backtest(
        BacktestRequest(strategy=default_strategy(), bars=rows, settings=settings)
    )
    for side in ("long", "short"):
        assert all(t["signal_time"] >= boundary.isoformat() for t in result[side]["trades"])
        assert result[side]["equity"][0]["timestamp"] == boundary.isoformat()
        assert len(result[side]["equity"]) == len(rows) - 48
    full = run_backtest(BacktestRequest(strategy=default_strategy(), bars=rows))
    assert (
        full["long"]["series"]["ema"][48] == result["long"]["series"]["ema"][48]
    )  # indicators warm


def test_evaluate_from_must_be_timezone_aware():
    from datetime import datetime

    import pytest
    from products.aegis.backtest import BacktestSettings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="timezone-aware"):
        BacktestSettings(evaluate_from=datetime(2026, 1, 6, 14, 30))  # noqa: DTZ001 - naive on purpose


def test_block_window_straddling_evaluate_from_counts_nothing_before_it():
    from datetime import UTC, datetime

    from products.aegis.backtest import BacktestSettings
    from products.aegis.strategy import ClockWindow, WindowMode

    strategy = default_strategy()
    blocked = strategy.temporal.model_copy(
        update={
            "clock_windows": [
                ClockWindow(
                    id="straddle",
                    label="Straddle",
                    start="09:00",
                    end="10:00",
                    mode=WindowMode.BLOCK,
                )
            ]
        }
    )
    boundary = datetime(2026, 1, 6, 14, 30, tzinfo=UTC)  # 09:30 New York: inside the BLOCK window
    result = run_backtest(
        BacktestRequest(
            strategy=strategy.model_copy(update={"temporal": blocked}),
            bars=bars(),
            settings=BacktestSettings(evaluate_from=boundary),
        )
    )
    for side in ("long", "short"):
        assert result[side]["equity"][0]["timestamp"] == boundary.isoformat()
        for trade in result[side]["trades"]:
            assert trade["signal_time"] >= boundary.isoformat()
            local = datetime.fromisoformat(trade["signal_time"]).astimezone(
                __import__("zoneinfo").ZoneInfo("America/New_York")
            )
            assert not ("09:00" <= local.strftime("%H:%M") < "10:00"), trade["signal_time"]


# --- Mission 5: carrying an open position in and out of a run ------------------------------

PLAIN_FIXTURE_HASH = "fc356e7edacda9a6865fe287e5626c58294582f4c72b04ca327648890e598ada"


def _long_only():
    strategy = default_strategy()
    strategy.short_side.enabled = False
    return strategy


def _run(rows, **settings):
    from products.aegis.backtest import BacktestSettings

    return run_backtest(
        BacktestRequest(strategy=_long_only(), bars=rows, settings=BacktestSettings(**settings))
    )


def test_close_at_end_false_reports_the_open_position():
    # The fixture's first long trade is held from bar 36 to bar 59; cut while it is open.
    result = _run(bars()[:50], close_at_end=False)
    side = result["long"]
    open_position = side["open_position"]
    assert open_position["side"] == "LONG"
    assert open_position["quantity"] > 0
    assert not any(t["exit_signal_time"] == t["exit_time"] for t in side["trades"])
    assert side["ending_cash"] == 100_000
    assert side["ending_equity"] == side["equity"][-1]["equity"]


def test_carried_position_reproduces_the_continuous_run():
    from datetime import datetime as _dt

    from products.aegis.backtest import OpenPosition

    rows = bars()
    continuous = _run(rows)["long"]["trades"][0]
    first = _run(rows[:50], close_at_end=False)["long"]
    second = _run(
        rows[50 - 35 :],
        initial_capital=first["ending_cash"],
        initial_position=OpenPosition(**{**first["open_position"], "origin_window": 0}),
        evaluate_from=_dt.fromisoformat(rows[50]["timestamp"].isoformat()),
    )["long"]
    carried = second["trades"][0]
    assert carried["exit_time"] == continuous["exit_time"]
    assert carried["exit_price"] == pytest.approx(continuous["exit_price"], abs=1e-9)
    assert carried["net_pnl"] == pytest.approx(continuous["net_pnl"], abs=1e-9)
    assert carried["carried_from_window"] == 0


def test_exit_signal_on_the_last_bar_travels_with_the_position():
    from products.aegis.backtest import OpenPosition

    rows = bars()
    continuous = _run(rows)["long"]["trades"][0]
    signal_index = next(
        i
        for i, r in enumerate(rows)
        if r["timestamp"].isoformat() == continuous["exit_signal_time"]
    )
    first = _run(rows[: signal_index + 1], close_at_end=False)["long"]
    assert first["open_position"]["exit_signal_time"] == continuous["exit_signal_time"]
    second = _run(
        rows[signal_index + 1 - 35 :],
        initial_capital=first["ending_cash"],
        initial_position=OpenPosition(**{**first["open_position"], "origin_window": 0}),
        evaluate_from=rows[signal_index + 1]["timestamp"],
    )["long"]
    carried = second["trades"][0]
    assert carried["exit_signal_time"] == continuous["exit_signal_time"]
    assert carried["exit_time"] == rows[signal_index + 1]["timestamp"].isoformat()
    assert carried["net_pnl"] == pytest.approx(continuous["net_pnl"], abs=1e-9)


def test_initial_position_side_mismatch_is_refused():
    from products.aegis.backtest import BacktestSettings, OpenPosition

    strategy = default_strategy()
    strategy.long_side.enabled = False
    position = OpenPosition(
        side="LONG",
        entry_time="2026-01-05T15:00:00+00:00",
        signal_time="2026-01-05T14:30:00+00:00",
        entry_price=100.0,
        quantity=10,
        entry_fee=0.0,
        capital_at_entry=100_000.0,
        entry_tags=[],
    )
    with pytest.raises(ValueError, match="does not match"):
        run_backtest(
            BacktestRequest(
                strategy=strategy,
                bars=bars(),
                settings=BacktestSettings(initial_position=position),
            )
        )


def test_plain_run_result_is_unchanged():
    from products.aegis.results import canonical_payload, result_hash

    strategy = default_strategy()
    result = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))
    identity = {"source": "supplied_bars", "bar_count": len(bars())}
    assert result_hash(canonical_payload(result, strategy, identity)) == PLAIN_FIXTURE_HASH


def test_warmup_check_uses_the_kind():
    from products.aegis.strategy import IndicatorSpec

    strategy = _long_only()
    strategy.long_side.indicators.append(IndicatorSpec(id="rsi", kind="RSI", length=40))
    with pytest.raises(ValueError, match=r"warm-up of RSI\(40\) \(41 bars\)"):
        run_backtest(BacktestRequest(strategy=strategy, bars=bars()[:41]))
    run_backtest(BacktestRequest(strategy=strategy, bars=bars()[:42]))


# --- Mission 5: rule evaluation --------------------------------------------------------------


def _frame(**columns):
    import pandas as pd

    return pd.DataFrame(columns)


def _cond(left, operator, right):
    from products.aegis.strategy import RuleSpec

    return RuleSpec(left=left, operator=operator, right=right)


def test_comparisons_against_constants_and_crossing_a_constant():
    from products.aegis.backtest import evaluate

    data = _frame(rsi=[20.0, 29.0, 31.0, 35.0, 28.0], close=[1.0, 2, 3, 4, 5])
    assert evaluate(data, _cond("rsi", "less_than", "30")).tolist() == [
        True,
        True,
        False,
        False,
        True,
    ]
    assert evaluate(data, _cond("rsi", "greater_than", "30")).tolist() == [
        False,
        False,
        True,
        True,
        False,
    ]
    assert evaluate(data, _cond("rsi", "crosses_above", "30")).tolist() == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert evaluate(data, _cond("rsi", "crosses_below", "30")).tolist() == [
        False,
        False,
        False,
        False,
        True,
    ]
    assert evaluate(data, _cond("price.close", "greater_than", "rsi")).tolist() == [False] * 5


def test_band_operators_include_the_boundaries_inside():
    from products.aegis.backtest import evaluate

    data = _frame(
        close=[9.0, 10.0, 15.0, 20.0, 21.0, float("nan")],
        **{"dc.upper": [20.0] * 6, "dc.lower": [10.0] * 6},
    )
    inside = evaluate(data, _cond("price.close", "inside_band", "dc")).tolist()
    outside = evaluate(data, _cond("price.close", "outside_band", "dc")).tolist()
    assert inside == [False, True, True, True, False, False]
    assert outside == [True, False, False, False, True, False]


def test_groups_combine_with_and_or():
    from products.aegis.backtest import evaluate
    from products.aegis.strategy import RuleGroup

    data = _frame(a=[1.0, 1, 0, 0], b=[1.0, 0, 1, 0])
    first, second = _cond("a", "greater_than", "0.5"), _cond("b", "greater_than", "0.5")
    assert evaluate(data, RuleGroup(all_of=[first, second])).tolist() == [True, False, False, False]
    assert evaluate(data, RuleGroup(any_of=[first, second])).tolist() == [True, True, True, False]


def _breakout(rows_fixture):
    from products.aegis.strategy import StrategySide

    strategy = _long_only()
    data = strategy.long_side.model_dump(mode="json")
    data["indicators"] = [
        {"id": "donchian", "kind": "DONCHIAN", "length": 20},
        {"id": "rsi", "kind": "RSI", "length": 14},
    ]
    data["entry"] = {
        "all_of": [
            {"left": "price.close", "operator": "crosses_above", "right": "donchian.upper"},
            {"left": "rsi", "operator": "less_than", "right": "70"},
        ]
    }
    data["exit"] = {"left": "price.close", "operator": "crosses_below", "right": "donchian.middle"}
    data["optimization"] = []
    return strategy.model_copy(update={"long_side": StrategySide.model_validate(data)})


def test_breakout_strategy_trades_and_hashes_stably():
    from products.aegis.results import canonical_payload, result_hash
    from test_aegis_walkforward import wave_bars

    strategy = _breakout(wave_bars)
    rows = wave_bars(n=300, period=60.0, amplitude=8.0)
    identity = {"source": "supplied_bars", "bar_count": len(rows)}
    first = run_backtest(BacktestRequest(strategy=strategy, bars=rows))
    second = run_backtest(BacktestRequest(strategy=strategy, bars=rows))
    assert first["long"]["metrics"]["trade_count"] >= 1
    assert set(first["long"]["series"]) == {
        "donchian.upper",
        "donchian.lower",
        "donchian.middle",
        "rsi",
    }
    assert result_hash(canonical_payload(first, strategy, identity)) == result_hash(
        canonical_payload(second, strategy, identity)
    )


def test_side_without_indicators_runs():
    from products.aegis.strategy import StrategySide

    strategy = _long_only()
    data = strategy.long_side.model_dump(mode="json")
    data.update(
        indicators=[],
        optimization=[],
        entry={"left": "price.close", "operator": "greater_than", "right": "110"},
        exit={"left": "price.close", "operator": "less_than", "right": "105"},
    )
    strategy = strategy.model_copy(update={"long_side": StrategySide.model_validate(data)})
    result = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))
    assert result["long"]["metrics"]["trade_count"] >= 1
