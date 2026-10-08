from products.aegis.strategy import Direction, WindowMode, default_strategy


def test_reference_strategy_is_9_ema_30_sma_cross():
    strategy = default_strategy()
    indicators = {item.id: item for item in strategy.indicators}

    assert indicators["ema_9"].kind == "EMA"
    assert indicators["ema_9"].length == 9
    assert indicators["sma_30"].kind == "SMA"
    assert indicators["sma_30"].length == 30


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

    crossover_ids = {window.id for window in strategy.temporal.market_crossovers}
    assert {"london_new_york", "cash_open"} <= crossover_ids


def test_reference_strategy_uses_next_bar_open_execution():
    strategy = default_strategy()
    assert strategy.execution.signal_timing == "bar_close"
    assert strategy.execution.fill_timing == "next_bar_open"
