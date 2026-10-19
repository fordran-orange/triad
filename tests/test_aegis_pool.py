"""The process pool (Mission 6 spec §4.3): cells run on worker processes that hold the bars,
their own indicator cache and the compiled kernel, and return rows, never envelopes."""

import pytest
from products.aegis.backtest import BacktestRequest, run_backtest
from products.aegis.pool import METRICS, SCOPES, Pool, resample_curve
from products.aegis.surface import apply_params
from test_aegis_surface import pinned
from test_aegis_walkforward import wave_bars

pytestmark = pytest.mark.aegis

ROWS = wave_bars(n=260, period=37.0, amplitude=10.0)


@pytest.fixture(scope="module")
def pool():
    spec = pinned()
    p = Pool(max_workers=2)
    p.start(
        ROWS,
        "QQQ",
        spec.model_dump(mode="json"),
        {"initial_capital": 100_000, "allocation_fraction": 1},
    )
    yield p
    p.shutdown()


def cells(n):
    return [
        (
            i,
            {
                "long_side.indicators.donchian.length": 10 + 5 * (i % 3),
                "long_side.indicators.rsi.length": 7 + 7 * (i % 4),
            },
        )
        for i in range(n)
    ]


def test_pool_runs_a_chunk_and_measures_cost(pool):
    rows = pool.run_chunk(cells(6), want_curve=False)
    assert [r["cell"] for r in rows] == list(range(6))
    for row in rows:
        assert row["valid"] is True and row["skip_reason"] is None
        for scope in SCOPES:
            assert set(row["metrics"][scope]) == set(METRICS)
        assert row["elapsed_ms"] > 0 and row["curve"] is None
    assert pool.mean_ms_per_cell_bar is not None and pool.mean_ms_per_cell_bar > 0


def test_pool_metrics_equal_the_full_engine(pool):
    spec = pinned()
    for index, params in cells(4):
        row = pool.run_chunk([(index, params)], want_curve=False)[0]
        full = run_backtest(BacktestRequest(strategy=apply_params(spec, params), bars=ROWS))
        for scope in SCOPES:
            for metric in METRICS:
                assert row["metrics"][scope][metric] == full[scope]["metrics"][metric], (
                    scope,
                    metric,
                )


def test_pool_returns_curves_of_128_points_when_asked(pool):
    rows = pool.run_chunk(cells(2), want_curve=True)
    for row in rows:
        assert len(row["curve"]) == 128 and row["first_time"] and row["last_time"]
        assert row["curve"][-1] == pytest.approx(100_000 + row["metrics"]["combined"]["net_pnl"])


def test_pool_reports_an_invalid_cell_without_running_it(pool):
    spec = pinned()
    data = spec.long_side.model_dump(mode="json")
    data["indicators"].append({"id": "macd", "kind": "MACD", "length": 12})
    from products.aegis.strategy import StrategySide

    other = Pool(max_workers=1)
    other.start(
        ROWS,
        "QQQ",
        spec.model_copy(update={"long_side": StrategySide.model_validate(data)}).model_dump(
            mode="json"
        ),
        {"initial_capital": 100_000, "allocation_fraction": 1},
    )
    try:
        [row] = other.run_chunk(
            [
                (
                    0,
                    {
                        "long_side.indicators.macd.length": 30,
                        "long_side.indicators.macd.params.slow": 20,
                    },
                )
            ],
            want_curve=False,
        )
    finally:
        other.shutdown()
    assert (
        row["valid"] is False
        and "MACD fast length" in row["skip_reason"]
        and row["metrics"] is None
    )


def test_resample_curve_pads_short_series_and_keeps_the_ends():
    assert resample_curve([1.0, 2.0, 3.0], 5) == [1.0, 1.0, 2.0, 2.0, 3.0]
    assert resample_curve([], 4) == [0.0, 0.0, 0.0, 0.0]
    long = resample_curve([float(i) for i in range(1000)], 128)
    assert len(long) == 128 and long[0] == 0.0 and long[-1] == 999.0


def test_a_cell_whose_warm_up_exceeds_the_bars_is_an_invalid_row_not_a_failure():
    """Review finding 2: the engine's "insufficient bars" refusal is a skipped cell with the
    reason, never an exception that fails the whole experiment."""
    from products.aegis import pool as worker

    worker._init_worker(
        [dict(r) for r in ROWS],
        "QQQ",
        pinned().model_dump(mode="json"),
        {"initial_capital": 100_000, "allocation_fraction": 1},
    )
    params = {
        "long_side.indicators.donchian.length": 1000.0,
        "long_side.indicators.rsi.length": 14.0,
    }
    row = worker._run_cell(7, params, False)
    assert row["valid"] is False and row["skip_reason"] == "insufficient bars", row
    assert row["metrics"] is None and row["cell"] == 7 and row["params"] == params


def test_pool_window_slice_equals_a_backtest_on_those_bars(pool):
    """Mission 8 Task 3: a window's cells run on the window's bars only, as a plain backtest of
    that slice would."""
    spec = pinned()
    for index, params in cells(4):
        [row] = pool.run_chunk([(index, params)], want_curve=False, window=(40, 230))
        sliced = run_backtest(
            BacktestRequest(strategy=apply_params(spec, params), bars=ROWS[40:230])
        )
        for scope in SCOPES:
            for metric in METRICS:
                assert row["metrics"][scope][metric] == sliced[scope]["metrics"][metric], (
                    scope,
                    metric,
                )
    whole = pool.run_chunk(cells(1), want_curve=False)[0]
    full = run_backtest(BacktestRequest(strategy=apply_params(spec, cells(1)[0][1]), bars=ROWS))
    assert whole["metrics"]["combined"] == full["combined"]["metrics"]  # no window: as before
    assert pool.mean_ms_per_cell_bar > 0
