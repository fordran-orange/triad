"""The compiled simulation kernel (Mission 6 spec §4.1–4.2): byte-identical to the reference
engine on every fixture, honest when numba is absent, and never silently wrong when full."""

import pytest
from products.aegis import kernel
from products.aegis.backtest import (
    BacktestRequest,
    BacktestSettings,
    OpenPosition,
    PendingEntry,
    run_backtest,
)
from products.aegis.results import canonical_payload, result_hash
from products.aegis.strategy import StrategySide, default_strategy
from test_aegis_backtest import _breakout, _long_only, bars
from test_aegis_walkforward import rsi_walkforward_request, run_sync, wave_bars

pytestmark = pytest.mark.aegis

IDENTITY = {"source": "supplied_bars"}


def _both(strategy, rows, **settings):
    """Run the reference and the kernel on the same request; return (reference, kernel)."""
    results = []
    for engine in ("reference", "kernel"):
        request = BacktestRequest(
            strategy=strategy, bars=rows, settings=BacktestSettings(**settings), engine=engine
        )
        results.append(run_backtest(request))
    return results


def _hash(result, strategy, rows):
    return result_hash(canonical_payload(result, strategy, {**IDENTITY, "bar_count": len(rows)}))


def _assert_identical(strategy, rows, **settings):
    reference, compiled = _both(strategy, rows, **settings)
    assert reference["engine"] == "reference" and compiled["engine"] == "kernel"
    assert _hash(reference, strategy, rows) == _hash(compiled, strategy, rows)
    for side in ("long", "short"):
        for key in ("open_position", "pending_entry", "ending_cash", "ending_equity"):
            assert reference[side][key] == compiled[side][key], (side, key)
    return reference, compiled


def _constant_strategy():
    strategy = _long_only()
    data = strategy.long_side.model_dump(mode="json")
    data.update(
        indicators=[],
        optimization=[],
        entry={"left": "price.close", "operator": "greater_than", "right": "110"},
        exit={"left": "price.close", "operator": "less_than", "right": "105"},
    )
    return strategy.model_copy(update={"long_side": StrategySide.model_validate(data)})


def _costly_strategy():
    strategy = default_strategy()
    return strategy.model_copy(
        update={
            "execution": strategy.execution.model_copy(
                update={"commission_per_side": 1.0, "slippage_bps": 5.0}
            )
        }
    )


def test_kernel_available_on_this_host():
    assert kernel.AVAILABLE is True and kernel.IMPORT_ERROR is None


def test_kernel_matches_reference_on_every_fixture():
    _assert_identical(default_strategy(), bars())
    _assert_identical(_breakout(None), wave_bars(n=300, period=60.0, amplitude=8.0))
    _assert_identical(_constant_strategy(), bars())
    _assert_identical(_costly_strategy(), bars())
    reference, compiled = _assert_identical(default_strategy(), bars())
    assert compiled["long"]["metrics"]["trade_count"] >= 1
    assert reference["long"]["trades"] == compiled["long"]["trades"]


def test_kernel_matches_reference_on_the_cut_and_carry_pair():
    rows = bars()
    strategy = _long_only()
    _reference, first_kernel = _assert_identical(strategy, rows[:50], close_at_end=False)
    assert first_kernel["long"]["open_position"]["side"] == "LONG"
    position = OpenPosition(**{**first_kernel["long"]["open_position"], "origin_window": 0})
    _assert_identical(
        strategy,
        rows[50 - 35 :],
        initial_capital=first_kernel["long"]["ending_cash"],
        initial_position=position,
        evaluate_from=rows[50]["timestamp"],
    )


def test_kernel_matches_reference_on_a_travelling_exit():
    rows = bars()
    strategy = _long_only()
    continuous = run_backtest(BacktestRequest(strategy=strategy, bars=rows))["long"]["trades"][0]
    cut = next(
        i
        for i, r in enumerate(rows)
        if r["timestamp"].isoformat() == continuous["exit_signal_time"]
    )
    _, first = _assert_identical(strategy, rows[: cut + 1], close_at_end=False)
    assert first["long"]["open_position"]["exit_signal_time"] == continuous["exit_signal_time"]
    position = OpenPosition(**{**first["long"]["open_position"], "origin_window": 0})
    _, second = _assert_identical(
        strategy,
        rows[cut + 1 - 35 :],
        initial_capital=first["long"]["ending_cash"],
        initial_position=position,
        evaluate_from=rows[cut + 1]["timestamp"],
    )
    assert second["long"]["trades"][0]["exit_time"] == rows[cut + 1]["timestamp"].isoformat()


def test_kernel_matches_reference_on_a_travelling_entry():
    """Mission 8 QA D1: an entry signalled on a run's last bar travels to the next run and fills
    at its first evaluated bar's open, as a continuous run fills it (it used to be dropped)."""
    rows = bars()
    strategy = _long_only()
    continuous = run_backtest(BacktestRequest(strategy=strategy, bars=rows))["long"]["trades"]
    stamps = [r["timestamp"].isoformat() for r in rows]
    trade = next(t for t in continuous if stamps.index(t["signal_time"]) > 40)
    cut = stamps.index(trade["signal_time"])
    _, first = _assert_identical(strategy, rows[: cut + 1], close_at_end=False)
    assert first["long"]["open_position"] is None
    pending = first["long"]["pending_entry"]
    assert pending["side"] == "LONG" and pending["signal_time"] == trade["signal_time"]
    _, second = _assert_identical(
        strategy,
        rows[cut + 1 - 35 :],
        initial_capital=first["long"]["ending_cash"],
        initial_entry=PendingEntry(**pending),
        evaluate_from=rows[cut + 1]["timestamp"],
    )
    filled = second["long"]["trades"][0]
    for key in ("signal_time", "entry_time", "entry_price", "quantity", "exit_time", "net_pnl"):
        assert filled[key] == trade[key], key


def test_a_carried_entry_needs_its_side_enabled_and_no_position_on_it():
    rows = bars()
    strategy = _long_only()
    stamp = rows[60]["timestamp"].isoformat()
    with pytest.raises(ValueError, match="initial_entry side SHORT"):
        run_backtest(
            BacktestRequest(
                strategy=strategy,
                bars=rows,
                settings=BacktestSettings(
                    initial_entry=PendingEntry(side="SHORT", signal_time=stamp)
                ),
            )
        )
    position = OpenPosition(
        side="LONG",
        entry_time=stamp,
        signal_time=stamp,
        entry_price=100.0,
        quantity=10,
        entry_fee=0.0,
        capital_at_entry=100_000.0,
        entry_tags=[],
    )
    with pytest.raises(ValueError, match="both a carried position and a carried entry"):
        run_backtest(
            BacktestRequest(
                strategy=strategy,
                bars=rows,
                settings=BacktestSettings(
                    initial_position=position,
                    initial_entry=PendingEntry(side="LONG", signal_time=stamp),
                ),
            )
        )


def test_kernel_matches_reference_on_carried_windows(monkeypatch):
    rows = wave_bars(n=400, period=29.0, amplitude=6.0)
    compiled = run_sync(rsi_walkforward_request(), rows)
    assert compiled["engine"] == "kernel"
    monkeypatch.setattr(kernel, "AVAILABLE", False)
    monkeypatch.setattr(kernel, "IMPORT_ERROR", "ModuleNotFoundError")
    reference = run_sync(rsi_walkforward_request(), rows)
    assert reference["engine"] == "reference"
    assert reference["result_hash"] == compiled["result_hash"]
    assert reference["window_records"] == compiled["window_records"]


def test_reference_fallback_when_numba_is_absent(monkeypatch):
    monkeypatch.setattr(kernel, "AVAILABLE", False)
    monkeypatch.setattr(kernel, "IMPORT_ERROR", "ModuleNotFoundError")
    result = run_backtest(
        BacktestRequest(strategy=default_strategy(), bars=bars(), engine="kernel")
    )
    assert result["engine"] == "reference"


def test_trades_buffer_overflow_is_an_error_not_a_crash(monkeypatch):
    strategy = _long_only()
    data = strategy.long_side.model_dump(mode="json")
    data.update(
        indicators=[],
        optimization=[],
        entry={"left": "price.close", "operator": "greater_than", "right": "price.low"},
        exit={"left": "price.close", "operator": "less_than", "right": "price.high"},
    )
    strategy = strategy.model_copy(update={"long_side": StrategySide.model_validate(data)})
    rows = bars()[:60]
    _reference, compiled = _assert_identical(strategy, rows)
    assert compiled["long"]["metrics"]["trade_count"] >= 10
    monkeypatch.setattr(kernel, "trade_capacity", lambda n_bars: 1)
    with pytest.raises(RuntimeError, match=r"trades buffer full \(capacity 1\)"):
        run_backtest(BacktestRequest(strategy=strategy, bars=rows, engine="kernel"))


def test_kernel_matches_reference_with_stops():
    """Mission 13: stop loss and take profit give the same trades on both engines."""

    def levels(strategy):
        update = {
            key: getattr(strategy, key).model_copy(
                update={"stop_loss_pct": 1.5, "take_profit_pct": 3.0}
            )
            for key in ("long_side", "short_side")
        }
        return strategy.model_copy(update=update)

    for strategy in (default_strategy(), _breakout(None)):
        for rows in (bars(), wave_bars(n=300, period=60.0, amplitude=8.0)):
            reference, _ = _assert_identical(levels(strategy), rows)
            reasons = {
                t.get("exit_reason") for s in ("long", "short") for t in reference[s]["trades"]
            }
            assert reasons & {"stop_loss", "take_profit"}, reasons
