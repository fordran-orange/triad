"""Walk-forward pure functions (Mission 4 spec §5): windows, selection, chaining, stitching,
stability, payload identity. DB-free, synthetic inputs."""

import json

import pytest
from products.aegis.backtest import DataReference
from products.aegis.results import result_hash, walkforward_payload
from products.aegis.strategy import OptimizationParameter, default_strategy
from products.aegis.walkforward import (
    MAX_WINDOWS,
    MIN_OOS_BARS,
    WalkForwardRequest,
    Window,
    cut_windows,
    efficiency,
    lead_bars,
    longest_length,
    pending_record,
    plan,
    select_best,
    stability,
    stitch,
)

DATA = DataReference(symbol="QQQ", timeframe="1h", start="2023-01-01", end="2024-12-31")
PINNED = {"source": "raw_archive", "symbol": "QQQ", "vintage": "test", "research_eligible": False}


def make_request(in_sample_bars=200, out_of_sample_bars=50, ranges=None, **overrides):
    strategy = default_strategy()
    if ranges is not None:
        side = strategy.long_side.model_copy(update={"optimization": ranges})
        strategy = strategy.model_copy(update={"long_side": side})
    return WalkForwardRequest(
        strategy=strategy,
        side="long",
        data=DATA,
        in_sample_bars=in_sample_bars,
        out_of_sample_bars=out_of_sample_bars,
        **overrides,
    )


def small_ranges(fast=(5, 7, 1), slow=(8, 10, 1)):
    return [
        OptimizationParameter(
            path="indicators.ema.length", start=fast[0], stop=fast[1], step=fast[2]
        ),
        OptimizationParameter(
            path="indicators.sma.length", start=slow[0], stop=slow[1], step=slow[2]
        ),
    ]


def test_cut_windows_rolls_by_out_of_sample_and_reports_the_tail():
    windows, tail = cut_windows(502, 200, 50)
    assert len(windows) == 6 and tail == 2
    first, last = windows[0], windows[5]
    assert (first.is_start, first.is_end, first.oos_start, first.oos_end) == (0, 200, 200, 250)
    assert (last.is_start, last.oos_end) == (250, 500)
    assert [w.oos_start for w in windows] == [w.is_end for w in windows]
    assert [w.index for w in windows] == list(range(6))
    with pytest.raises(ValueError, match="range too short: 100 bars"):
        cut_windows(100, 80, 30)


def test_longest_length_covers_the_ranges_the_grid_will_visit():
    side = default_strategy().long_side  # EMA 9 / SMA 30 now; ranges reach SMA 100
    assert longest_length(side) == 100
    assert longest_length(side.model_copy(update={"optimization": small_ranges()})) == 30


def test_plan_rejects_in_sample_shorter_than_warmup():
    with pytest.raises(ValueError, match="in_sample_bars 120 below 135"):
        plan(make_request(in_sample_bars=120, out_of_sample_bars=20), 500)


def test_plan_caps_windows_and_grid_and_counts_units():
    assert (MAX_WINDOWS, MIN_OOS_BARS) == (50, 20)
    with pytest.raises(ValueError, match="windows 60 over cap 50"):
        plan(make_request(in_sample_bars=135, out_of_sample_bars=20), 135 + 60 * 20)
    too_big = small_ranges(fast=(1, 25, 1), slow=(30, 200, 10))  # 25 x 18 = 450
    with pytest.raises(ValueError, match="grid too large"):
        plan(make_request(in_sample_bars=240, out_of_sample_bars=20, ranges=too_big), 500)
    with pytest.raises(ValueError, match="out_of_sample_bars 10 below 20"):
        WalkForwardRequest(
            strategy=default_strategy(),
            side="long",
            data=DATA,
            in_sample_bars=200,
            out_of_sample_bars=10,
        )
    result = plan(make_request(in_sample_bars=135, out_of_sample_bars=20), 335)
    assert len(result.windows) == 10 and result.unused_tail_bars == 0
    assert result.cells_per_window == 271 and result.total_units == 10 * 272


def test_select_best_direction_nulls_and_ties():
    cells = [
        {"index": 0, "params": {"a": 1}, "metrics": {"net_pnl": 5.0, "max_drawdown": 0.2}},
        {"index": 1, "params": {"a": 2}, "metrics": {"net_pnl": 9.0, "max_drawdown": 0.1}},
        {"index": 2, "params": {"a": 3}, "metrics": {"net_pnl": 9.0, "max_drawdown": None}},
    ]
    assert select_best(cells, "net_pnl")["index"] == 1  # tie with 2 → lowest index
    assert select_best(cells, "max_drawdown")["index"] == 1  # minimized; None ignored
    assert select_best([cells[2]], "max_drawdown") is None
    assert select_best([], "net_pnl") is None


def test_efficiency_is_per_bar_ratio_or_null():
    assert efficiency({"net_return": 0.20}, 200, {"net_return": 0.10}, 50) == pytest.approx(2.0)
    assert efficiency({"net_return": 0.0}, 200, {"net_return": 0.10}, 50) is None
    assert efficiency({"net_return": -0.1}, 200, {"net_return": 0.10}, 50) is None
    assert efficiency(None, 200, {"net_return": 0.10}, 50) is None


def test_lead_bars_warm_the_chosen_configuration_and_satisfy_the_engine_floor():
    assert lead_bars(30) == 35  # engine floor of 35 bars wins over 31
    assert lead_bars(60) == 61


def point(ts, equity):
    return {"timestamp": ts, "equity": equity, "drawdown": 0.0}


def trade(net):
    return {"side": "LONG", "net_pnl": net, "exit_time": "x", "signal_time": "x"}


def done_record(index, trades, equity, exposure):
    return {
        "index": index,
        "status": "done",
        "oos_bars": len(equity),
        "best": {
            "params": {"indicators.ema.length": 9 + index, "indicators.sma.length": 30},
            "metrics": {},
        },
        "oos": {
            "trades": trades,
            "equity": equity,
            "metrics": {"exposure": exposure, "net_pnl": sum(t["net_pnl"] for t in trades)},
        },
        "efficiency": 2.0 if index == 0 else None,
    }


def test_stitch_chains_only_done_windows_in_order():
    records = [
        done_record(
            0,
            [trade(500.0)],
            [
                point("2023-01-03T15:30:00+00:00", 100_000.0),
                point("2023-01-03T16:30:00+00:00", 100_500.0),
            ],
            0.5,
        ),
        {
            "index": 1,
            "status": "pending",
            "oos_bars": 2,
            "best": None,
            "oos": None,
            "efficiency": None,
        },
        done_record(
            2,
            [trade(-200.0)],
            [
                point("2023-01-05T15:30:00+00:00", 100_500.0),
                point("2023-01-05T16:30:00+00:00", 100_300.0),
            ],
            1.0,
        ),
    ]
    stitched = stitch(records, 100_000.0)
    assert [t["net_pnl"] for t in stitched["trades"]] == [500.0, -200.0]
    assert [p["equity"] for p in stitched["equity"]] == [100_000.0, 100_500.0, 100_500.0, 100_300.0]
    assert stitched["metrics"]["trade_count"] == 2
    assert stitched["metrics"]["net_pnl"] == pytest.approx(300.0)
    assert stitched["metrics"]["exposure"] == pytest.approx(
        0.75
    )  # bar-weighted mean of 0.5 and 1.0
    assert stitch([records[1]], 100_000.0)["metrics"]["trade_count"] == 0


def test_stability_spread_positive_windows_and_mean_efficiency():
    records = [
        done_record(0, [trade(5.0)], [point("a", 1.0)], 0.0),
        {
            "index": 1,
            "status": "pending",
            "oos_bars": 1,
            "best": None,
            "oos": None,
            "efficiency": None,
        },
        done_record(2, [trade(-3.0)], [point("b", 1.0)], 0.0),
    ]
    result = stability(records, ["indicators.ema.length", "indicators.sma.length"])
    ema = result["parameters"]["indicators.ema.length"]
    assert (ema["min"], ema["max"], ema["mean"], ema["std"]) == (9.0, 11.0, 10.0, 1.0)
    assert result["parameters"]["indicators.sma.length"]["std"] == 0.0
    assert result["positive_oos_windows"] == 1 and result["windows_evaluated"] == 2
    assert result["mean_efficiency"] == pytest.approx(2.0)
    assert stability([records[1]], ["indicators.ema.length"])["mean_efficiency"] is None


def test_pending_record_names_the_window_bars_by_timestamp():
    timestamps = [f"t{i}" for i in range(10)]
    record = pending_record(
        Window(index=1, is_start=2, is_end=6, oos_start=6, oos_end=9), timestamps
    )
    assert record["index"] == 1 and record["status"] == "pending"
    assert (record["is_start"], record["is_end"], record["oos_start"], record["oos_end"]) == (
        "t2",
        "t5",
        "t6",
        "t8",
    )
    assert (record["is_bars"], record["oos_bars"], record["cells_evaluated"]) == (4, 3, 0)
    assert record["best"] is None and record["oos"] is None and record["efficiency"] is None


def test_walkforward_payload_hash_identity_and_sensitivity():
    records = [done_record(0, [trade(1.0)], [point("2023-01-03T15:30:00+00:00", 100_001.0)], 0.0)]
    stitched = stitch(records, 100_000.0)
    stable = stability(records, ["indicators.ema.length"])
    request = make_request()
    first = walkforward_payload(records, stitched, stable, request, PINNED, unused_tail_bars=2)
    second = walkforward_payload(
        records, stitched, stable, make_request(), PINNED, unused_tail_bars=2
    )
    assert result_hash(first) == result_hash(second)
    assert first["kind"] == "walkforward" and first["in_sample_bars"] == 200
    changed = walkforward_payload(
        records, stitched, stable, make_request(out_of_sample_bars=63), PINNED, unused_tail_bars=2
    )
    assert result_hash(changed) != result_hash(first)
    text = json.dumps(first)
    assert all(key not in text for key in ("job_id", "created_at", "elapsed_ms", "evaluate_from"))
