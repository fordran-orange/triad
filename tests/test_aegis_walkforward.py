"""Walk-forward pure functions (Mission 4 spec §5): windows, selection, chaining, stitching,
stability, payload identity. DB-free, synthetic inputs."""

import itertools
import json
import threading
import time

import pandas as pd
import pytest
from products.aegis.backtest import DataReference
from products.aegis.jobs import JobRunner
from products.aegis.results import result_hash, walkforward_payload
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import OptimizationParameter, apply_parameters, default_strategy
from products.aegis.walkforward import (
    MAX_WINDOWS,
    MIN_OOS_BARS,
    WalkForwardJob,
    WalkForwardRequest,
    Window,
    cut_windows,
    efficiency,
    flag_edge_exits,
    pending_record,
    plan,
    select_best,
    side_warmup,
    stability,
    stitch,
)
from test_aegis_backtest import bars

pytestmark = pytest.mark.aegis

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


def test_side_warmup_covers_the_ranges_the_grid_will_visit():
    side = default_strategy().long_side  # EMA 9 / SMA 30 now; ranges reach SMA 100
    assert side_warmup(side) == 100
    assert side_warmup(side.model_copy(update={"optimization": small_ranges()})) == 30


def test_plan_rejects_in_sample_shorter_than_warmup():
    with pytest.raises(ValueError, match="in_sample_bars 120 below 135"):
        plan(make_request(in_sample_bars=120, out_of_sample_bars=20), 500)


def test_plan_caps_windows_and_grid_and_counts_units():
    assert (MAX_WINDOWS, MIN_OOS_BARS) == (50, 20)
    with pytest.raises(ValueError, match="windows 60 over cap 50"):
        plan(make_request(in_sample_bars=135, out_of_sample_bars=20), 135 + 60 * 20)
    too_big = small_ranges(fast=(1, 400, 1), slow=(401, 700, 1))  # 120,000 over the 100,000 bound
    with pytest.raises(ValueError, match="grid too large"):
        plan(make_request(in_sample_bars=800, out_of_sample_bars=20, ranges=too_big), 900)
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


# --- the job kind (spec §6.1–6.2) -------------------------------------------------------------


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def job_request(objective="net_pnl"):
    """90 synthetic bars; the long side shortened to EMA 5 / SMA 8 with a 2x2 grid (longest 9 →
    floor 44): in-sample 44, out-of-sample 20 → windows [0,44)+[44,64) and [20,64)+[64,84),
    tail 6, 5 units per window, 10 in all."""
    strategy = default_strategy()
    short_side = apply_parameters(
        strategy.long_side, {"indicators.ema.length": 5, "indicators.sma.length": 8}
    ).model_copy(update={"optimization": small_ranges(fast=(5, 6, 1), slow=(8, 9, 1))})
    return WalkForwardRequest(
        strategy=strategy.model_copy(update={"long_side": short_side}),
        side="long",
        data=DATA,
        in_sample_bars=44,
        out_of_sample_bars=20,
        objective=objective,
    )


def start_job(runner, request=None):
    return runner.start(WalkForwardJob(request or job_request(), pd.DataFrame(bars()), PINNED))


def test_walkforward_job_completes_with_chained_capital_and_hash(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = JobRunner(repository)
    job_id = start_job(runner)
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "failed"))
    status = runner.status(job_id)
    assert status["status"] == "done", status["error"]
    assert status["kind"] == "walkforward" and status["side"] == "long"
    assert status["windows"] == {"done": 2, "total": 2} and status["progress"] == {
        "done": 10,
        "total": 10,
    }
    assert status["unused_tail_bars"] == 6 and status["cells_per_window"] == 4
    first, second = status["window_records"]
    assert first["status"] == "done" and first["cells_evaluated"] == 4 and first["best"]["params"]
    assert first["oos"]["equity"][0]["timestamp"] == first["oos_start"]
    assert second["oos"]["equity"][0]["equity"] == pytest.approx(
        first["oos"]["equity"][-1]["equity"]
    )
    assert len(status["result_hash"]) == 64
    assert status["stitched"]["metrics"]["trade_count"] == len(status["stitched"]["trades"])
    assert set(status["stability"]["parameters"]) == {
        "indicators.ema.length",
        "indicators.sma.length",
    }
    assert status["stability"]["windows_evaluated"] == 2
    assert repository.get_walkforward(job_id)["result_hash"] == status["result_hash"]


def test_oos_trades_never_signal_before_window_start(tmp_path):
    runner = JobRunner(JsonRunRepository(tmp_path))
    job_id = start_job(runner, job_request(objective="trade_count"))  # the busiest cell
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "failed"))
    status = runner.status(job_id)
    assert status["status"] == "done", status["error"]
    trades = [t for r in status["window_records"] for t in r["oos"]["trades"]]
    assert trades, "the synthetic series should trade out-of-sample"
    for record in status["window_records"]:
        for trade in record["oos"]["trades"]:
            assert trade["signal_time"] >= record["oos_start"], (
                trade["signal_time"],
                record["oos_start"],
            )
        assert record["oos"]["equity"][0]["timestamp"] == record["oos_start"]
        assert len(record["oos"]["equity"]) == record["oos_bars"]


def test_cancel_between_units_keeps_completed_windows_only(tmp_path):
    gate = threading.Event()

    def after_unit(done):
        if done == 5:  # window 0 complete: 4 cells + its out-of-sample run
            gate.wait(10)

    runner = JobRunner(JsonRunRepository(tmp_path), after_unit=after_unit)
    job_id = start_job(runner)
    assert wait_for(lambda: runner.status(job_id)["progress"]["done"] == 5)
    assert runner.cancel(job_id) is True
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "cancelled")
    status = runner.status(job_id)
    assert status["windows"] == {"done": 1, "total": 2}
    assert [r["status"] for r in status["window_records"]] == ["done", "pending"]
    assert status["stitched"]["equity"] == status["window_records"][0]["oos"]["equity"]
    assert status["result_hash"] is None


def test_walkforward_hash_is_identical_across_two_jobs_and_persisted(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = JobRunner(repository)
    ids = []
    for _ in range(2):
        job_id = start_job(runner)
        assert wait_for(lambda j=job_id: runner.status(j)["status"] == "done")
        ids.append(job_id)
    first, second = (runner.status(i) for i in ids)
    assert first["result_hash"] == second["result_hash"] and first["job_id"] != second["job_id"]
    assert sorted(w["job_id"] for w in repository.list_walkforwards()) == sorted(ids)
    assert repository.list_walkforwards()[0]["kind"] == "walkforward"
    assert repository.get_walkforward(ids[0])["status"] == "done"


def test_mark_lost_covers_walkforward_jobs(tmp_path):
    gate = threading.Event()

    def after_unit(done):
        if done == 1:
            gate.wait(10)

    runner = JobRunner(JsonRunRepository(tmp_path), after_unit=after_unit)
    job_id = start_job(runner)
    assert wait_for(lambda: runner.status(job_id)["progress"]["done"] == 1)
    assert JobRunner(JsonRunRepository(tmp_path)).mark_lost_on_startup() == [job_id]
    gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")


# --- fix pass after the whole-branch review and QA ---------------------------------------------


def test_stitch_measures_drawdown_across_window_joins():
    first = done_record(
        0,
        [trade(20_000.0)],
        [
            point("2023-01-03T15:30:00+00:00", 100_000.0),
            point("2023-01-04T15:30:00+00:00", 120_000.0),
        ],
        1.0,
    )
    second = done_record(
        1,
        [trade(-10_000.0)],
        [
            point("2023-01-05T15:30:00+00:00", 110_000.0),
            point("2023-01-06T15:30:00+00:00", 100_000.0),
        ],
        1.0,
    )
    second["oos"]["equity"][1]["drawdown"] = (
        -1 / 11
    )  # the window's own peak (110,000), not the curve's
    stitched = stitch([first, second], 100_000.0)
    assert stitched["metrics"]["max_drawdown"] == pytest.approx(1 - 100_000 / 120_000)
    assert [round(p["drawdown"], 4) for p in stitched["equity"]] == [
        0.0,
        0.0,
        round(-1 / 12, 4),
        round(-1 / 6, 4),
    ]
    assert second["oos"]["equity"][1]["drawdown"] == -1 / 11  # the window record is untouched


def test_flag_edge_exits_marks_forced_closes_only():
    trades = [
        {"exit_signal_time": "2023-01-03T15:30:00+00:00", "exit_time": "2023-01-03T16:30:00+00:00"},
        {"exit_signal_time": "2023-01-04T15:30:00+00:00", "exit_time": "2023-01-04T15:30:00+00:00"},
    ]
    assert [t["window_edge_exit"] for t in flag_edge_exits(trades)] == [False, True]


def daily(n, start="2023-01-02"):
    from datetime import UTC, datetime, timedelta

    first = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return [(first + timedelta(days=i)).isoformat() for i in range(n)]


def test_plan_refuses_mar_under_a_year_and_grids_without_a_valid_cell():
    short = make_request(in_sample_bars=200, out_of_sample_bars=50, objective="mar")
    with pytest.raises(
        ValueError,
        match="objective mar needs an in-sample span of at least 365 days; window 0 spans 199 days",
    ):
        plan(short, 500, timestamps=daily(500))
    long_enough = make_request(in_sample_bars=400, out_of_sample_bars=50, objective="mar")
    assert len(plan(long_enough, 500, timestamps=daily(500)).windows) == 2  # 399 days: fine
    assert len(plan(short, 500).windows) == 6  # without timestamps the span cannot be checked
    empty = make_request(
        in_sample_bars=200,
        out_of_sample_bars=50,
        ranges=small_ranges(fast=(30, 32, 1), slow=(8, 9, 1)),
    )
    with pytest.raises(ValueError, match="grid has no valid cell: fast ≥ slow"):
        plan(empty, 500)


def test_walkforward_request_rejects_a_warmup_boundary_of_its_own():
    from datetime import UTC, datetime

    from products.aegis.backtest import BacktestSettings, OpenPosition
    from pydantic import ValidationError

    def request(**settings):
        return WalkForwardRequest(
            strategy=default_strategy(),
            side="long",
            data=DATA,
            in_sample_bars=200,
            out_of_sample_bars=50,
            settings=BacktestSettings(**settings),
        )

    carried = OpenPosition(
        side="LONG",
        entry_time="2024-01-02T14:30:00+00:00",
        signal_time="2024-01-02T14:00:00+00:00",
        entry_price=100.0,
        quantity=1,
        entry_fee=0.0,
        capital_at_entry=100_000.0,
        entry_tags=[],
    )
    for field, value in (
        ("evaluate_from", datetime(2024, 1, 2, 14, 30, tzinfo=UTC)),
        ("initial_position", carried),
        ("close_at_end", False),
    ):
        with pytest.raises(
            ValidationError, match=f"settings.{field} is set by the job itself; leave it unset"
        ):
            request(**{field: value})


def test_oos_trades_at_window_edges_are_flagged_in_records_and_stitched(tmp_path):
    runner = JobRunner(JsonRunRepository(tmp_path))
    job_id = start_job(runner, job_request(objective="trade_count"))
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    status = runner.status(job_id)
    trades = [t for r in status["window_records"] for t in r["oos"]["trades"]]
    assert trades and all("window_edge_exit" in t for t in trades)
    for t in trades:
        assert t["window_edge_exit"] is (t["exit_signal_time"] == t["exit_time"])
    assert [t["window_edge_exit"] for t in status["stitched"]["trades"]] == [
        t["window_edge_exit"] for t in trades
    ]
    assert (
        status["stitched"]["metrics"]["max_drawdown"]
        >= max(r["oos"]["metrics"]["max_drawdown"] for r in status["window_records"]) - 1e-12
    )


# --- Mission 5: positions carried across windows --------------------------------------------


def wave_bars(n=200, period=37.0, amplitude=10.0):
    """A drifting sine series whose EMA 5 / SMA 8 trades straddle several window joins."""
    import math
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    rows, previous = [], 100.0
    for i in range(n):
        close = 100 + amplitude * math.sin(2 * math.pi * i / period) + 0.05 * i
        rows.append(
            {
                "timestamp": start + timedelta(minutes=30 * i),
                "symbol": "QQQ",
                "open": previous,
                "high": max(previous, close) + 0.5,
                "low": min(previous, close) - 0.5,
                "close": close,
                "volume": 1000 + i,
            }
        )
        previous = close
    return rows


def run_sync(request=None, rows=None):
    """Drive every unit in order on this thread, as the runner would, and return the snapshot."""
    job = WalkForwardJob(
        request or job_request(objective="net_pnl"), pd.DataFrame(rows or wave_bars()), PINNED
    )
    for unit in range(job.total_units):
        job.commit(unit, job.run_unit(unit))
    job.finalize("done")
    return job.snapshot()


def test_only_the_final_window_can_close_at_its_edge():
    records = run_sync()["window_records"]
    assert len(records) == 7
    for record in records[:-1]:
        assert not any(t["window_edge_exit"] for t in record["oos"]["trades"]), record["index"]


def test_open_at_end_and_carried_in_agree_across_every_join():
    records = run_sync()["window_records"]
    assert records[0]["carried_in"] is False
    for before, after in itertools.pairwise(records):
        assert before["open_at_end"] == after["carried_in"], before["index"]
    holding = {r["index"] for r in records if r["open_at_end"]}
    carried = [t for r in records for t in r["oos"]["trades"] if "carried_from_window" in t]
    assert holding and carried, "the fixture must carry at least one position"
    assert all(t["carried_from_window"] in holding for t in carried)
    for k in holding:  # the position window k left open closes as a trade of a later window
        later = [
            t
            for r in records
            if r["index"] > k
            for t in r["oos"]["trades"]
            if t.get("carried_from_window") == k
        ]
        assert later, f"window {k} ended open but no later window records its carried trade"
    assert records[-1]["open_at_end"] is False


def test_window_net_pnl_is_rebased_on_the_previous_ending_equity():
    status = run_sync()
    records = status["window_records"]
    baseline = status["settings"]["initial_capital"]
    for record in records:
        metrics = record["oos"]["metrics"]
        assert metrics["net_pnl"] == pytest.approx(record["ending_equity"] - baseline, abs=1e-6)
        baseline = record["ending_equity"]


def test_stitched_net_pnl_equals_the_final_ending_equity_minus_capital():
    status = run_sync()
    final = status["window_records"][-1]["ending_equity"]
    assert status["stitched"]["metrics"]["net_pnl"] == pytest.approx(
        final - status["settings"]["initial_capital"], abs=1e-6
    )


def test_no_valid_cell_after_a_carry_inherits_the_previous_configuration(monkeypatch):
    from products.aegis import walkforward

    plain = run_sync()["window_records"]
    k = next(r["index"] for r in plain if r["open_at_end"])
    real, calls = walkforward.select_best, []

    def select_best(cells, objective):
        calls.append(1)
        return None if len(calls) == k + 2 else real(cells, objective)

    monkeypatch.setattr(walkforward, "select_best", select_best)
    records = run_sync()["window_records"]
    inherited = records[k + 1]
    assert inherited["status"] == "done"
    assert inherited["inherited_from"] == k
    assert inherited["best"] is None and inherited["efficiency"] is None
    assert inherited["carried_in"] is True
    assert records[-1]["open_at_end"] is False


def test_side_warmup_counts_parameter_ranges():
    from products.aegis.strategy import IndicatorSpec

    side = default_strategy().long_side.model_copy(
        update={
            "indicators": [
                *default_strategy().long_side.indicators,
                IndicatorSpec(id="macd", kind="MACD", length=12),
            ],
            "optimization": [
                OptimizationParameter(path="indicators.macd.params.slow", start=20, stop=40, step=5)
            ],
        }
    )
    assert side_warmup(side) == 40 + 9 - 1
    assert side_warmup(side, ranges=False) == 26 + 9 - 1


def rsi_walkforward_request():
    """RSI 21/28 crossing 55: a recursive indicator whose cold start would move the signals."""
    from products.aegis.strategy import StrategySide

    strategy = default_strategy()
    data = strategy.long_side.model_dump(mode="json")
    data["indicators"] = [{"id": "rsi", "kind": "RSI", "length": 21}]
    data["entry"] = {"left": "rsi", "operator": "crosses_above", "right": "55"}
    data["exit"] = {"left": "rsi", "operator": "crosses_below", "right": "55"}
    data["optimization"] = [{"path": "indicators.rsi.length", "start": 21, "stop": 28, "step": 7}]
    strategy = strategy.model_copy(update={"long_side": StrategySide.model_validate(data)})
    return WalkForwardRequest(
        strategy=strategy, side="long", data=DATA, in_sample_bars=80, out_of_sample_bars=60
    )


def test_out_of_sample_runs_on_the_full_history():
    """Review finding #2: an out-of-sample window's indicators must equal a continuous run's, so
    its trades equal a continuous backtest of the chosen configuration counted from the window."""
    from datetime import datetime

    from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest

    rows = wave_bars(n=400, period=29.0, amplitude=6.0)
    job = WalkForwardJob(rsi_walkforward_request(), pd.DataFrame(rows), PINNED)
    for unit in range(job.total_units):
        job.commit(unit, job.run_unit(unit))
    last = len(job.plan.windows) - 1
    compared = 0
    for record, window in zip(job.records, job.plan.windows, strict=True):
        if record["carried_in"] or record["best"] is None:
            continue
        side = apply_parameters(job._base_side, record["best"]["params"])
        continuous = run_backtest(
            BacktestRequest(
                strategy=job._strategy_with(side),
                bars=job.rows[: window.oos_end],
                settings=BacktestSettings(
                    evaluate_from=datetime.fromisoformat(job.timestamps[window.oos_start]),
                    close_at_end=window.index == last,
                ),
            )
        )["long"]
        assert [(t["entry_time"], t["exit_time"]) for t in record["oos"]["trades"]] == [
            (t["entry_time"], t["exit_time"]) for t in continuous["trades"]
        ], window.index
        compared += 1
    assert compared >= 3
