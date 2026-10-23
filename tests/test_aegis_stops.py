"""Mission 13: stop loss and take profit, checked on each bar's close and filled at the next
bar's open, in both engines (spec §4.2–4.3). Bars are 5-minute bars from 09:30 New York; each
expected fill is worked out beside its bars. Every run goes through both engines, which must
agree exactly."""

from datetime import UTC, datetime, timedelta

import pytest
from products.aegis.backtest import (
    BacktestRequest,
    BacktestSettings,
    OpenPosition,
    run_backtest,
)
from products.aegis.results import canonical_payload, result_hash
from products.aegis.strategy import StrategySide, default_strategy
from pydantic import ValidationError

pytestmark = pytest.mark.aegis

START = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
LONG_ENTRY = {"left": "price.close", "operator": "crosses_above", "right": "100.5"}
SHORT_ENTRY = {"left": "price.close", "operator": "crosses_below", "right": "99.5"}


def rows(closes, opens=None):
    """Bars whose open is the previous close unless `opens` names it."""
    opens = opens or {}
    out, previous = [], closes[0]
    for i, close in enumerate(closes):
        opened = opens.get(i, previous)
        out.append(
            {
                "timestamp": START + timedelta(minutes=5 * i),
                "open": opened,
                "high": max(opened, close) + 0.1,
                "low": min(opened, close) - 0.1,
                "close": close,
                "volume": 1000,
            }
        )
        previous = close
    return out


def price_strategy(entry, exit=None, stop=None, target=None, side="long"):
    """One side trading on price and constants only (always warm); the other side off."""
    strategy = default_strategy()
    key, other = ("long_side", "short_side") if side == "long" else ("short_side", "long_side")
    data = getattr(strategy, key).model_dump(mode="json")
    data.update(indicators=[], entry=entry, optimization=[])
    data.pop("exit", None)
    if exit is not None:
        data["exit"] = exit
    if stop is not None:
        data["stop_loss_pct"] = stop
    if target is not None:
        data["take_profit_pct"] = target
    off = getattr(strategy, other).model_copy(update={"enabled": False})
    return strategy.model_copy(update={key: StrategySide.model_validate(data), other: off})


def run(strategy, bars, **settings):
    """Both engines; they must agree on the payload and on what they carry. Returns the kernel's."""
    results = [
        run_backtest(
            BacktestRequest(
                strategy=strategy, bars=bars, settings=BacktestSettings(**settings), engine=engine
            )
        )
        for engine in ("reference", "kernel")
    ]
    identity = {"source": "supplied_bars", "bar_count": len(bars)}
    hashes = [result_hash(canonical_payload(r, strategy, identity)) for r in results]
    assert hashes[0] == hashes[1]
    for side in ("long", "short"):
        for key in ("open_position", "pending_entry", "ending_cash"):
            assert results[0][side][key] == results[1][side][key], (side, key)
    return results[1]


def at(i: int) -> str:
    return (START + timedelta(minutes=5 * i)).isoformat()


# Long: the entry signals on bar 40 (101 crosses above 100.5) and fills at bar 41's open, 100.0.
# A 2% stop sits at 98.0 and a 5% target at 105.0.
FLAT = [100.0] * 40


# --- the model --------------------------------------------------------------------------------


def test_a_side_needs_an_exit():
    with pytest.raises(
        ValidationError, match="long side has no exit: add a rule, a stop or a target"
    ):
        price_strategy(LONG_ENTRY)


def test_a_stop_alone_is_an_exit():
    side = price_strategy(LONG_ENTRY, stop=2).long_side
    assert side.exit is None and side.stop_loss_pct == 2


def test_stops_are_left_out_of_dumps_when_unset():
    dumped = price_strategy(LONG_ENTRY, stop=2).long_side.model_dump(mode="json")
    assert "exit" not in dumped and "take_profit_pct" not in dumped and dumped["stop_loss_pct"] == 2
    reference = default_strategy().long_side.model_dump(mode="json")
    assert "stop_loss_pct" not in reference and "take_profit_pct" not in reference


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stop", 0),
        ("stop", 100),
        ("stop", -1),
        ("stop", float("inf")),
        ("target", 0),
        ("target", -5),
        ("target", float("inf")),
    ],
)
def test_stop_bounds_are_refused_by_name(field, value):
    name = "stop_loss_pct" if field == "stop" else "take_profit_pct"
    with pytest.raises(ValidationError, match=name + r"\n\s+Input should be"):
        price_strategy(LONG_ENTRY, **{field: value})


# --- both engines -----------------------------------------------------------------------------


def test_a_long_stop_fires_on_the_close_and_fills_next_open():
    # bar 43 closes at 97.9 <= 98.0: the exit fills at bar 44's open, 97.7.
    bars = rows([*FLAT, 101.0, 100.2, 99.0, 97.9, 97.6, *[97.5] * 6], opens={41: 100.0, 44: 97.7})
    (trade,) = run(price_strategy(LONG_ENTRY, stop=2), bars)["long"]["trades"]
    assert trade["entry_price"] == 100.0 and trade["exit_signal_time"] == at(43)
    assert trade["exit_time"] == at(44) and trade["exit_price"] == 97.7
    assert trade["exit_reason"] == "stop_loss"


def test_a_long_target_fires_on_the_close():
    # bar 43 closes at 105.5 >= 105.0: the exit fills at bar 44's open, 105.5.
    bars = rows([*FLAT, 101.0, 102.0, 104.0, 105.5, *[106.0] * 6], opens={41: 100.0})
    (trade,) = run(price_strategy(LONG_ENTRY, target=5), bars)["long"]["trades"]
    assert trade["exit_signal_time"] == at(43) and trade["exit_time"] == at(44)
    assert trade["exit_price"] == 105.5 and trade["exit_reason"] == "take_profit"


def test_a_gap_past_the_stop_fills_at_the_next_open():
    # bar 43 closes at 97.0; bar 44 opens at 93.0, below the 98.0 level: that open is the fill.
    bars = rows([*FLAT, 101.0, 100.2, 99.0, 97.0, *[93.5] * 6], opens={41: 100.0, 44: 93.0})
    (trade,) = run(price_strategy(LONG_ENTRY, stop=2), bars)["long"]["trades"]
    assert trade["exit_price"] == 93.0 and trade["exit_reason"] == "stop_loss"


def test_a_stop_and_a_rule_on_one_bar_report_stop_loss():
    rule = {"left": "price.close", "operator": "less_than", "right": "98.5"}
    bars = rows([*FLAT, 101.0, 100.2, 99.0, 97.9, *[97.5] * 6], opens={41: 100.0})
    (trade,) = run(price_strategy(LONG_ENTRY, exit=rule, stop=2), bars)["long"]["trades"]
    assert trade["exit_signal_time"] == at(43) and trade["exit_reason"] == "stop_loss"


def test_short_levels_mirror_the_long():
    # Short: signals on bar 40 (99.0 crosses below 99.5), fills at bar 41's open, 100.0.
    stopped = rows([*FLAT, 99.0, 99.8, 101.0, 102.1, *[102.5] * 6], opens={41: 100.0})
    (trade,) = run(price_strategy(SHORT_ENTRY, stop=2, side="short"), stopped)["short"]["trades"]
    assert trade["exit_signal_time"] == at(43) and trade["exit_reason"] == "stop_loss"
    # Bar 42 closes at 101.0, below the 102.0 stop: nothing fires there.
    target = rows([*FLAT, 99.0, 99.0, 97.0, 94.9, *[94.5] * 6], opens={41: 100.0})
    (trade,) = run(price_strategy(SHORT_ENTRY, target=5, side="short"), target)["short"]["trades"]
    assert trade["exit_signal_time"] == at(43) and trade["exit_reason"] == "take_profit"


def test_rule_exits_add_no_field():
    rule = {"left": "price.close", "operator": "less_than", "right": "99.5"}
    bars = rows([*FLAT, 101.0, 100.2, 99.0, *[99.0] * 7], opens={41: 100.0})
    (trade,) = run(price_strategy(LONG_ENTRY, exit=rule, stop=5), bars)["long"]["trades"]
    assert trade["exit_signal_time"] == at(42) and "exit_reason" not in trade


STOPPED = [*FLAT, 101.0, 100.2, 99.0, 97.9, 97.6, *[97.5] * 6]


def test_a_level_on_the_last_bar_travels_with_the_open_position():
    strategy = price_strategy(LONG_ENTRY, stop=2)
    full = rows(STOPPED, opens={41: 100.0, 44: 97.7})
    first = run(strategy, full[:44], close_at_end=False)["long"]
    assert first["trades"] == []
    assert first["open_position"]["exit_signal_time"] == at(43)
    assert first["open_position"]["exit_reason"] == "stop_loss"
    position = OpenPosition(**{**first["open_position"], "origin_window": 0})
    second = run(
        strategy,
        full[9:],
        initial_capital=first["ending_cash"],
        initial_position=position,
        evaluate_from=full[44]["timestamp"],
    )["long"]
    (trade,) = second["trades"]
    assert trade["exit_time"] == at(44) and trade["exit_price"] == 97.7
    assert trade["exit_reason"] == "stop_loss" and trade["carried_from_window"] == 0


def test_a_stop_carried_across_a_window_join():
    strategy = price_strategy(LONG_ENTRY, stop=2)
    full = rows(STOPPED, opens={41: 100.0, 44: 97.7})
    first = run(strategy, full[:42], close_at_end=False)["long"]
    assert first["open_position"]["entry_price"] == 100.0
    assert "exit_reason" not in first["open_position"]
    position = OpenPosition(**{**first["open_position"], "origin_window": 0})
    second = run(
        strategy,
        full[7:],
        initial_capital=first["ending_cash"],
        initial_position=position,
        evaluate_from=full[42]["timestamp"],
    )["long"]
    (trade,) = second["trades"]
    assert trade["exit_signal_time"] == at(43) and trade["exit_reason"] == "stop_loss"


def test_a_stop_only_side_runs_every_job_kind(tmp_path):
    """Review Focus 1: an exit that is only a stop, through a backtest, an experiment cell, a
    walk-forward and a study."""
    from products.aegis.backtest import _data_key, _prepare_frame, prepared_request, run_metrics
    from products.aegis.indicators import IndicatorCache
    from products.aegis.runs import JsonRunRepository
    from products.aegis.studies import StudyRequest, StudyStore, create_study
    from products.aegis.walkforward import WalkForwardRequest
    from test_aegis_studies import LENGTHS, ROWS_BY_SYMBOL, make_parent, run_to
    from test_aegis_walkforward import job_request, run_sync, wave_bars

    strategy = price_strategy(LONG_ENTRY, stop=2)
    bars = rows(STOPPED, opens={41: 100.0, 44: 97.7})
    full = run(strategy, bars)
    assert [t["exit_reason"] for t in full["long"]["trades"]] == ["stop_loss"]

    frame = _prepare_frame(bars)
    metrics = run_metrics(
        prepared_request(strategy, BacktestSettings()), frame, _data_key(frame), IndicatorCache()
    )
    assert metrics["long"] == full["long"]["metrics"]

    def stop_only(side: StrategySide) -> StrategySide:
        data = side.model_dump(mode="json")
        data.pop("exit")
        data["stop_loss_pct"] = 2.0
        return StrategySide.model_validate(data)

    base = job_request()
    walk = WalkForwardRequest.model_validate(
        {
            **base.model_dump(mode="json"),
            "strategy": base.strategy.model_copy(
                update={"long_side": stop_only(base.strategy.long_side)}
            ).model_dump(mode="json"),
        }
    )
    snapshot = run_sync(walk, wave_bars())
    assert snapshot["windows"]["done"] == snapshot["windows"]["total"] > 0, snapshot["windows"]

    repository = JsonRunRepository(tmp_path / "aegis")
    experiments, parent = make_parent(repository)
    spec = parent.spec.model_copy(update={"long_side": stop_only(parent.spec.long_side)})
    experiments.save(parent.model_copy(update={"spec": spec}))
    request = StudyRequest(
        experiment_id=parent.id,
        name="stop only",
        symbols=list(LENGTHS),
        in_sample_bars=120,
        out_of_sample_bars=60,
    )
    times = {s: [r["timestamp"] for r in rows_] for s, rows_ in ROWS_BY_SYMBOL.items()}
    from datetime import date

    document = create_study(
        StudyStore(repository), experiments, request, times, 2, date(2026, 1, 5), date(2026, 1, 31)
    )
    *_, done = run_to(repository, document)
    assert done.status == "done", done.error
