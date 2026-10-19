"""Plateau walk-forward rules (Mission 8 spec §5): the per-window choice, the per-side capital
chains, flat windows, stitching and the per-rule hashes; then the report and its Markdown."""

import math
from datetime import datetime

import pytest
from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest
from products.aegis.strategy import default_strategy
from products.aegis.study_rules import (
    best_cell,
    centre_inside,
    move_distance,
    resample,
    run_window,
    start_chains,
    stitch_rule,
)
from products.aegis.surface import Parameter, Surface, build_grid
from products.aegis.walkforward import cut_windows
from test_aegis_walkforward import wave_bars

pytestmark = pytest.mark.aegis

ROWS = [
    {**row, "timestamp": row["timestamp"].isoformat()}
    for row in wave_bars(n=600, period=37.0, amplitude=10.0)
]
WINDOWS, _ = cut_windows(len(ROWS), 200, 100)
SETTINGS = BacktestSettings(initial_capital=100_000, allocation_fraction=1)
SPEC = default_strategy()  # EMA 9 / SMA 30 on both sides


def walk(spec=SPEC, flat_at=()):
    """Run every window in order on one chain set, as one rule does."""
    chains = start_chains(spec, SETTINGS.initial_capital)
    results = []
    for window in WINDOWS:
        result = run_window(
            spec,
            ROWS,
            window,
            chains,
            SETTINGS,
            last=window is WINDOWS[-1],
            flat=window.index in flat_at,
        )
        results.append(result)
        chains = result["chains"]
    return results


def core(trade):
    return (trade["side"], trade["entry_time"], trade["exit_time"], round(trade["net_pnl"], 9))


def test_frozen_chain_equals_one_continuous_run():
    stitched = stitch_rule(walk(), SETTINGS.initial_capital)
    continuous = run_backtest(
        BacktestRequest(
            strategy=SPEC,
            bars=ROWS,
            settings=SETTINGS.model_copy(
                update={
                    "evaluate_from": datetime.fromisoformat(ROWS[WINDOWS[0].oos_start]["timestamp"])
                }
            ),
        )
    )["combined"]
    assert len(continuous["trades"]) >= 6
    assert [core(t) for t in stitched["trades"]] == [core(t) for t in continuous["trades"]]
    for key, value in continuous["metrics"].items():
        assert stitched["metrics"][key] == pytest.approx(value), key
    assert [p["equity"] for p in stitched["equity"]] == pytest.approx(
        [p["equity"] for p in continuous["equity"]]
    )


def test_each_side_keeps_its_own_chain_and_carries_across_joins():
    results = walk()
    carried = [
        (k, side)
        for k, result in enumerate(results[:-1])
        for side, record in result["sides"].items()
        if record["open_position"] is not None
    ]
    assert carried, "the wave must leave a position open at some join"
    for k, side in carried:
        assert results[k + 1]["sides"][side]["carried_in"] is True
    assert results[-1]["sides"]["long"]["open_position"] is None  # only the last closes its edge
    for k in range(1, len(results)):
        for side in ("long", "short"):
            assert results[k]["chains"][side].cash == results[k]["sides"][side]["ending_cash"]


def flat_after_an_open_position():
    results = walk()
    k = next(
        k
        for k, result in enumerate(results[:-1])
        if any(record["open_position"] for record in result["sides"].values())
    )
    return k, results[k]


def test_flat_window_closes_a_carried_position_at_its_first_bar_and_opens_nothing():
    k, before = flat_after_an_open_position()
    window = WINDOWS[k + 1]
    flat = run_window(SPEC, ROWS, window, before["chains"], SETTINGS, last=False, flat=True)
    assert flat["flat"] is True
    for side, record in before["sides"].items():
        after = flat["sides"][side]
        assert after["flat"] is True and after["open_position"] is None
        if record["open_position"] is None:
            assert after["trades"] == [] and after["ending_cash"] == before["chains"][side].cash
            continue
        [exit_] = after["trades"]
        assert exit_["exit_time"] == ROWS[window.oos_start]["timestamp"]
        assert exit_["window_flat_exit"] is True
        assert exit_["entry_time"] == record["open_position"]["entry_time"]
    assert flat["combined"]["exposure"] == 0.0


def test_the_window_after_a_flat_window_starts_flat():
    results = walk(flat_at=(2,))
    for record in results[2]["sides"].values():
        assert record["open_position"] is None
    for record in results[3]["sides"].values():
        assert record["carried_in"] is False


def test_window_net_is_its_ending_equity_minus_the_previous():
    results = walk()
    previous = SETTINGS.initial_capital
    for result in results:
        combined = result["combined"]
        assert combined["net_pnl"] == pytest.approx(combined["ending_equity"] - previous)
        previous = combined["ending_equity"]
    stitched = stitch_rule(results, SETTINGS.initial_capital)
    assert sum(r["combined"]["net_pnl"] for r in results) == pytest.approx(
        stitched["metrics"]["net_pnl"]
    )


def test_flat_windows_are_counted_in_the_stitch():
    results = walk(flat_at=(1, 2))
    assert stitch_rule(results, SETTINGS.initial_capital)["flat_windows"] == 2


def rows_of(values: dict[int, float | None], valid: dict[int, bool] | None = None):
    return [
        {"cell": cell, "valid": (valid or {}).get(cell, True), "combined.mar": value}
        for cell, value in values.items()
    ]


def test_best_cell_ties_to_the_lower_index_and_skips_nulls():
    assert best_cell(rows_of({4: 1.0, 2: 1.0, 7: None, 9: 0.5}), "mar") == 2
    assert best_cell(rows_of({4: 3.0, 2: 1.0}, valid={4: False}), "mar") == 2
    drawdown = [
        {"cell": 0, "valid": True, "combined.max_drawdown": 0.3},
        {"cell": 1, "valid": True, "combined.max_drawdown": 0.1},
    ]
    assert best_cell(drawdown, "max_drawdown") == 1


def test_null_objective_window_is_flat_for_both_choosing_rules():  # Review Focus 2
    assert best_cell(rows_of({0: None, 1: None}), "mar") is None
    assert best_cell([], "mar") is None


def grid2():
    return build_grid(
        default_strategy(),
        Surface(
            parameters=[
                Parameter(path="long_side.indicators.ema.length", start=1, stop=9, step=1),
                Parameter(path="long_side.indicators.sma.length", start=21, stop=29, step=1),
            ]
        ),
    )


def test_centre_inside_and_move_distance():
    assert centre_inside([3, 4, 5], 4) is True
    assert centre_inside([3, 4, 5], 8) is False
    assert centre_inside(None, 4) is None and centre_inside([3], None) is None
    grid = grid2()
    corner, opposite = grid.index_at((0, 0)), grid.index_at((8, 8))
    assert move_distance(grid, corner, opposite) == pytest.approx(math.sqrt(2))
    assert move_distance(grid, corner, corner) == 0.0


def test_stitched_hash_reproduces_and_changes_with_a_trade():
    first = stitch_rule(walk(), SETTINGS.initial_capital)
    again = stitch_rule(walk(), SETTINGS.initial_capital)
    assert first["result_hash"] == again["result_hash"] and len(first["result_hash"]) == 64
    results = walk()
    results[0]["combined"]["trades"] = results[0]["combined"]["trades"][1:]
    assert stitch_rule(results, SETTINGS.initial_capital)["result_hash"] != first["result_hash"]


def test_each_side_run_carries_a_hash_of_its_own_trades_and_metrics():  # plan ruling P16
    result = walk()[1]
    hashes = {record["run_hash"] for record in result["sides"].values()}
    assert len(hashes) == 2 and all(len(h) == 64 for h in hashes)


def test_resample_keeps_ends_and_bounds_the_count():
    points = [{"t": i} for i in range(1000)]
    out = resample(points, 256)
    assert len(out) == 256 and out[0] == points[0] and out[-1] == points[-1]
    assert resample(points[:10], 256) == points[:10]
