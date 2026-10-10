import pytest
from products.aegis.strategy import (
    Direction,
    RuleSpec,
    StrategySide,
    WindowMode,
    apply_parameters,
    default_strategy,
)
from pydantic import ValidationError


def test_reference_strategy_is_9_ema_30_sma_cross_on_both_sides():
    strategy = default_strategy()
    for side in (strategy.long_side, strategy.short_side):
        assert side.indicator("ema").kind == "EMA" and side.indicator("ema").length == 9
        assert side.indicator("sma").kind == "SMA" and side.indicator("sma").length == 30


def test_each_side_owns_its_indicators_and_ranges():
    s = default_strategy()
    assert [i.length for i in s.long_side.indicators] == [9, 30]
    assert [i.length for i in s.short_side.indicators] == [9, 30]
    assert s.long_side.optimization[0].path == "indicators.ema.length"
    assert s.long_side.optimization[1].path == "indicators.sma.length"
    assert s.short_side.optimization is not s.long_side.optimization
    assert not hasattr(s, "indicators") and not hasattr(s, "optimization")


def test_sides_can_diverge_without_shared_state():
    s = default_strategy()
    short = apply_parameters(
        s.short_side, {"indicators.ema.length": 6, "indicators.sma.length": 52}
    )
    assert short.indicator("ema").length == 6 and short.indicator("sma").length == 52
    assert s.long_side.indicator("ema").length == 9
    assert s.short_side.indicator("ema").length == 9  # apply_parameters does not mutate


def test_apply_parameters_rejects_unknown_paths():
    with pytest.raises(ValueError, match="unknown parameter path"):
        apply_parameters(default_strategy().long_side, {"indicators.rsi.length": 14})


def test_rule_referencing_unknown_indicator_is_rejected():
    with pytest.raises(ValidationError, match="unknown indicator"):
        StrategySide(
            direction=Direction.LONG,
            indicators=[],
            entry=RuleSpec(left="ema", operator="crosses_above", right="sma"),
            exit=RuleSpec(left="ema", operator="crosses_below", right="sma"),
        )


def test_long_and_short_sides_are_explicit_and_independent():
    strategy = default_strategy()
    assert strategy.long_side.direction == Direction.LONG
    assert strategy.short_side.direction == Direction.SHORT
    assert strategy.long_side.entry.operator == "crosses_above"
    assert strategy.short_side.entry.operator == "crosses_below"
    changed = strategy.model_copy(
        update={"short_side": strategy.short_side.model_copy(update={"enabled": False})}
    )
    assert changed.long_side.enabled is True
    assert changed.short_side.enabled is False


def test_temporal_context_is_first_class():
    strategy = default_strategy()
    windows = {window.id: window for window in strategy.temporal.clock_windows}
    assert windows["open"].start == "09:30"
    assert windows["close"].end == "16:00"
    assert all(window.mode == WindowMode.ANALYZE for window in windows.values())
    event_types = {window.event_type for window in strategy.temporal.event_windows}
    assert {"FOMC", "EARNINGS", "MACRO_RELEASE", "RUMOR_NEWS"} <= event_types


def test_market_crossovers_are_clock_defined_and_enabled():
    cx = {c.id: c for c in default_strategy().temporal.market_crossovers}
    assert cx["cash_open"].start == "09:25" and cx["cash_open"].end == "09:45"
    assert cx["cash_open"].enabled and cx["cash_open"].mode == WindowMode.ANALYZE
    assert cx["london_new_york"].start == "09:30" and cx["london_new_york"].end == "11:30"
    assert cx["london_new_york"].enabled


def test_reference_strategy_uses_next_bar_open_execution():
    strategy = default_strategy()
    assert strategy.execution.signal_timing == "bar_close"
    assert strategy.execution.fill_timing == "next_bar_open"
