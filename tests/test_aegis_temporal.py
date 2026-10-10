from datetime import UTC, datetime

import pandas as pd
import pytest
from products.aegis.backtest import BacktestRequest, EventPoint, run_backtest
from products.aegis.strategy import (
    ClockWindow,
    EventWindow,
    MarketCrossover,
    TemporalContext,
    WindowMode,
    default_strategy,
)
from products.aegis.temporal import entry_permitted, tags, validate
from test_aegis_backtest import bars


def et(hour, minute=0, day=5):
    # 2026-01-05 is a Monday in EST (UTC-5).
    return pd.Timestamp(datetime(2026, 1, day, hour + 5, minute, tzinfo=UTC))


def context(clock=(), events=(), crossovers=()):
    return TemporalContext(
        clock_windows=list(clock), event_windows=list(events), market_crossovers=list(crossovers)
    )


def window(identifier, start, end, mode):
    return ClockWindow(id=identifier, label=identifier, start=start, end=end, mode=mode)


def test_block_wins_and_allow_requires_inside_allow_and_outside_block():
    temporal = context(
        clock=[
            window("day", "10:00", "15:00", WindowMode.ALLOW),
            window("lunch", "12:00", "12:30", WindowMode.BLOCK),
        ]
    )
    assert entry_permitted(et(11), temporal) is True
    assert entry_permitted(et(12, 15), temporal) is False  # inside BLOCK, BLOCK wins
    assert entry_permitted(et(9, 40), temporal) is False  # outside every ALLOW window
    assert entry_permitted(et(15, 30), temporal) is False


def test_without_allow_windows_everything_outside_block_is_permitted():
    temporal = context(clock=[window("open", "09:30", "10:00", WindowMode.BLOCK)])
    assert entry_permitted(et(9, 45), temporal) is False
    assert entry_permitted(et(13), temporal) is True
    assert entry_permitted(et(9, 30), context()) is True


def test_block_suppresses_entry_but_not_exit():
    strategy = default_strategy()
    baseline = run_backtest(BacktestRequest(strategy=strategy, bars=bars()))
    assert baseline["combined"]["metrics"]["trade_count"] >= 2

    blocked = strategy.model_copy(deep=True)
    blocked.temporal.clock_windows = [window("all", "00:00", "23:59", WindowMode.BLOCK)]
    result = run_backtest(BacktestRequest(strategy=blocked, bars=bars()))
    assert result["combined"]["metrics"]["trade_count"] == 0

    # Block everything after the first long entry's fill: that position must still exit.
    first_entry = datetime.fromisoformat(baseline["long"]["trades"][0]["entry_time"])
    later = strategy.model_copy(deep=True)
    start = first_entry.astimezone(pd.Timestamp(first_entry).tz_convert("America/New_York").tzinfo)
    later.temporal.clock_windows = [
        window("late", start.strftime("%H:%M"), "23:59", WindowMode.BLOCK),
        window("early", "00:00", start.strftime("%H:%M"), WindowMode.ALLOW),
    ]
    partial = run_backtest(BacktestRequest(strategy=later, bars=bars()))
    assert partial["long"]["metrics"]["trade_count"] >= 1
    assert partial["long"]["trades"][0]["exit_time"] == baseline["long"]["trades"][0]["exit_time"]


def test_analyze_never_changes_execution():
    strategy = default_strategy()
    plain = strategy.model_copy(deep=True)
    plain.temporal.clock_windows = []
    plain.temporal.market_crossovers = []
    analyzed = strategy.model_copy(deep=True)
    analyzed.temporal.clock_windows = [window("mid", "10:00", "15:00", WindowMode.ANALYZE)]
    a = run_backtest(BacktestRequest(strategy=plain, bars=bars()))
    b = run_backtest(BacktestRequest(strategy=analyzed, bars=bars()))
    assert a["combined"]["metrics"]["trade_count"] == b["combined"]["metrics"]["trade_count"]
    assert a["combined"]["metrics"]["net_pnl"] == b["combined"]["metrics"]["net_pnl"]
    assert any("CLOCK:mid" in t["temporal_tags"] for t in b["combined"]["trades"])


def test_modify_risk_is_rejected_explicitly():
    with pytest.raises(ValueError, match="unsupported window mode: MODIFY_RISK"):
        validate(context(clock=[window("x", "09:30", "10:00", WindowMode.MODIFY_RISK)]))
    with pytest.raises(ValueError, match="unsupported window mode: MODIFY_RISK"):
        validate(context(events=[EventWindow(event_type="FOMC", mode=WindowMode.MODIFY_RISK)]))
    strategy = default_strategy()
    strategy.temporal.market_crossovers[0].mode = WindowMode.MODIFY_RISK
    with pytest.raises(ValueError, match="unsupported window mode: MODIFY_RISK"):
        run_backtest(BacktestRequest(strategy=strategy, bars=bars()))


def test_crossover_tags_are_clock_derived():
    temporal = default_strategy().temporal
    assert tags(et(9, 30), temporal, [], None) == (
        "CLOCK:open",
        "CROSSOVER:cash_open",
        "CROSSOVER:london_new_york",
    )
    assert tags(et(14), temporal, [], None) == ()
    disabled = temporal.model_copy(deep=True)
    disabled.market_crossovers = [
        MarketCrossover(id="x", label="x", enabled=False, start="09:30", end="11:30")
    ]
    assert tags(et(10), disabled, [], None) == ()


def test_rumor_news_window_without_events_tags_nothing():
    temporal = context(
        events=[
            EventWindow(event_type="RUMOR_NEWS", enabled=True, minutes_before=60, minutes_after=60)
        ]
    )
    assert tags(et(10), temporal, [], "QQQ") == ()
    event = EventPoint(event_type="RUMOR_NEWS", timestamp=datetime(2026, 1, 5, 15, 0, tzinfo=UTC))
    assert tags(et(10), temporal, [event], "QQQ") == ("EVENT:RUMOR_NEWS",)
    assert tags(et(12), temporal, [event], "QQQ") == ()


def test_gating_modes_on_crossovers_and_events_are_rejected():
    from products.aegis.strategy import WindowMode, default_strategy
    from products.aegis.temporal import validate

    temporal = default_strategy().temporal
    validate(temporal)  # ANALYZE everywhere is the supported shape
    for field in ("market_crossovers", "event_windows"):
        for mode in (WindowMode.BLOCK, WindowMode.ALLOW):
            windows = [w.model_copy(update={"mode": mode}) for w in getattr(temporal, field)]
            with pytest.raises(ValueError, match="ANALYZE-only"):
                validate(temporal.model_copy(update={field: windows}))
