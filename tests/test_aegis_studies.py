"""Plateau walk-forward studies (Mission 8 spec §4–6): the request, the plan per symbol, the
refusals, the resumable job kind, its window files and its routes."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from products.aegis.experiments import ExperimentDocument
from products.aegis.studies import StudyRequest, plan_study
from products.aegis.surface import Budget, Parameter, Surface
from products.aegis.surface import plan as plan_surface
from test_aegis_surface import item2_surface, pinned

pytestmark = pytest.mark.aegis


def ts(n: int, start: datetime = datetime(2016, 9, 19, 13, 30, tzinfo=UTC)) -> list[str]:
    """`n` hourly timestamps, seven a weekday, as the 1h archive lays out a session."""
    out: list[str] = []
    day = start
    while len(out) < n:
        if day.weekday() < 5:
            out.extend((day + timedelta(hours=h)).isoformat() for h in range(7))
        day += timedelta(days=1)
    return out[:n]


def three_symbols(n: int) -> dict[str, list[str]]:
    return {symbol: ts(n) for symbol in ("QQQ", "SPY", "ITOT")}


def experiment(
    bars: int = 3493,
    status: str = "done",
    objective: str = "mar",
    surface: Surface | None = None,
    budget: Budget | None = None,
    latest_report: int | None = 1,
) -> ExperimentDocument:
    surface = surface or item2_surface()  # 7 × 4 × 3 × 3 = 252 cells
    budget = budget or Budget(runs=1000)
    planned = plan_surface(pinned(), surface, budget, bars, 0.01, 10, "1h")
    return ExperimentDocument(
        id="fresh-surface",
        name="fresh surface",
        strategy_id="breakout",
        strategy_hash="0" * 64,
        spec=pinned(),
        data={"symbol": "QQQ", "timeframe": "1h", "start": "2023-01-01", "end": "2024-12-31"},
        settings={"initial_capital": 100_000, "allocation_fraction": 1},
        objective=objective,
        surface=surface,
        budget=budget,
        tolerance=0.15,
        seed=1,
        plan=planned.model_dump(mode="json"),
        status=status,
        progress={"cells_done": 252, "cells_planned": 252, "chunks_done": 2, "chunks_total": 2},
        created_at="2026-10-15T00:00:00+00:00",
        updated_at="2026-10-15T00:00:00+00:00",
        latest_report=latest_report,
    )


def refused(message: str, request: StudyRequest, exp: ExperimentDocument, bars: dict) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        plan_study(request, exp, bars, None, 10)


# --- Task 1: request, plan and refusals ----------------------------------------------------------


def test_defaults_come_from_the_experiment():
    exp = experiment()
    plan = plan_study(StudyRequest(experiment_id=exp.id), exp, three_symbols(17_500), None, 10)
    assert (plan.in_sample_bars, plan.out_of_sample_bars) == (3493, 873)
    assert [s.symbol for s in plan.symbols] == ["QQQ", "SPY", "ITOT"]
    first = plan.symbols[0]
    assert first.windows == (17_500 - 3493) // 873 == 16
    assert first.unused_tail_bars == 17_500 - 3493 - 16 * 873
    assert first.cells_per_window == 252 and first.mode == "exhaustive"
    assert first.runs == 16 * 252 and plan.total_runs == 3 * 16 * 252
    assert first.first_window["is_start"] == ts(1)[0]
    assert plan.price_source == "starting_guess" and plan.estimate_seconds > 0
    assert plan.timeframe == "1h" and plan.levers == []


def test_a_measured_price_is_used_and_named():
    exp = experiment()
    plan = plan_study(StudyRequest(experiment_id=exp.id), exp, three_symbols(17_500), 0.028, 10)
    assert plan.price_source == "measured" and plan.ms_per_cell_bar == 0.028


def test_symbols_are_upper_cased_distinct_and_never_empty():
    assert StudyRequest(experiment_id="x", symbols=[" qqq", "Spy"]).symbols == ["QQQ", "SPY"]
    with pytest.raises(ValueError, match="at least one symbol"):
        StudyRequest(experiment_id="x", symbols=[])
    with pytest.raises(ValueError, match="more than once"):
        StudyRequest(experiment_id="x", symbols=["QQQ", "qqq"])


def test_plan_counts_windows_per_symbol():  # Review Focus 1
    exp = experiment()
    bars = {"QQQ": ts(17_500), "SPY": ts(9_000), "ITOT": ts(4_400)}
    plan = plan_study(StudyRequest(experiment_id=exp.id), exp, bars, 0.028, 10)
    assert [s.windows for s in plan.symbols] == [16, 6, 1]
    assert [s.bars for s in plan.symbols] == [17_500, 9_000, 4_400]
    assert plan.total_runs == sum(s.runs for s in plan.symbols)


def test_a_sampled_map_carries_the_levers():  # plan ruling P15
    exp = experiment(budget=Budget(runs=100))
    plan = plan_study(StudyRequest(experiment_id=exp.id), exp, three_symbols(17_500), None, 10)
    assert plan.symbols[0].mode == "sampled" and plan.symbols[0].cells_per_window == 100
    assert plan.levers and all(lever.kind for lever in plan.levers)


def test_refused_unless_the_experiment_is_finished_with_a_report():
    message = (
        "experiment fresh-surface is running; a study needs a finished experiment with a report"
    )
    refused(
        message,
        StudyRequest(experiment_id="fresh-surface"),
        experiment(status="running"),
        three_symbols(17_500),
    )
    message = (
        "experiment fresh-surface has no report; a study needs a finished experiment with a report"
    )
    refused(
        message,
        StudyRequest(experiment_id="fresh-surface"),
        experiment(latest_report=None),
        three_symbols(17_500),
    )


def test_refused_for_an_unknown_symbol_or_one_without_bars():
    bars = three_symbols(17_500)
    refused(
        "unknown symbol 'NOPE'",
        StudyRequest(experiment_id="x", symbols=["NOPE"]),
        experiment(),
        bars,
    )
    bars["SPY"] = []
    refused(
        "symbol 'SPY' has no 1h bars in the range",
        StudyRequest(experiment_id="x"),
        experiment(),
        bars,
    )


def test_refused_for_a_range_too_short_for_one_window():
    bars = {"QQQ": ts(4000)}
    message = "QQQ: range too short: 4000 bars; one window needs 3493 + 873 bars"
    refused(message, StudyRequest(experiment_id="x", symbols=["QQQ"]), experiment(), bars)


def test_refused_below_the_window_floors():  # plan ruling P14
    bars = three_symbols(17_500)
    refused(
        "in_sample_bars 30 below 35",
        StudyRequest(experiment_id="x", in_sample_bars=30),
        experiment(),
        bars,
    )
    refused(
        "out_of_sample_bars 10 below 20",
        StudyRequest(experiment_id="x", out_of_sample_bars=10),
        experiment(),
        bars,
    )
    long_lengths = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=50, stop=60, step=5)
        ]
    )
    refused(
        "in_sample_bars 40: every cell's warm-up needs more bars",
        StudyRequest(experiment_id="x", in_sample_bars=40, out_of_sample_bars=20),
        experiment(objective="net_pnl", surface=long_lengths),
        bars,
    )


def test_refused_when_the_budget_cannot_sample_the_map():
    two = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=7),
        ]
    )
    with pytest.raises(ValueError, match="budget too small"):
        experiment(objective="net_pnl", surface=two, budget=Budget(runs=3))  # its own plan refuses
    exp = experiment(objective="net_pnl", surface=two).model_copy(update={"budget": Budget(runs=3)})
    refused(
        "budget too small for a 2-parameter surface",
        StudyRequest(experiment_id="x"),
        exp,
        three_symbols(17_500),
    )


def test_refused_when_mar_has_less_than_a_year_in_sample():  # plan ruling P6
    message = "objective mar needs an in-sample span of at least 365 days"
    request = StudyRequest(experiment_id="x", in_sample_bars=700, out_of_sample_bars=200)
    refused(message, request, experiment(), three_symbols(17_500))
    plan = plan_study(request, experiment(objective="net_pnl"), three_symbols(17_500), None, 10)
    assert plan.symbols[0].windows == (17_500 - 700) // 200


# --- Task 3: in-sample maps on a window slice ------------------------------------------------


@pytest.fixture(scope="module")
def window_pool():
    from products.aegis.pool import Pool

    p = Pool(max_workers=2)
    p.start([dict(r) for r in POOL_ROWS], "QQQ", pinned().model_dump(mode="json"), POOL_SETTINGS)
    yield p
    p.shutdown()


def _wave(n):
    from test_aegis_walkforward import wave_bars

    return [{**r, "timestamp": r["timestamp"].isoformat()} for r in wave_bars(n=n)]


POOL_ROWS = _wave(400)
POOL_SETTINGS = {"initial_capital": 100_000, "allocation_fraction": 1}


def wide_surface():
    return Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=30, step=2),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=3),
        ]
    )


def test_map_window_exhaustive_matches_analyse(window_pool):
    from products.aegis.analysis import analyse
    from products.aegis.backtest import BacktestRequest, run_backtest
    from products.aegis.studies import map_window
    from products.aegis.surface import apply_params, build_grid

    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=28, step=7),
        ]
    )
    grid = build_grid(pinned(), surface, 200)
    table, report = map_window(
        window_pool, grid, "exhaustive", 12, 0, "net_pnl", 0.15, 1, (100, 300), "QQQ w0"
    )
    assert sorted(table.column("cell").to_pylist()) == list(range(12))
    assert set(table.column("pass").to_pylist()) == {"grid"}
    assert report == analyse(table, grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ w0")
    row = table.to_pylist()[5]
    params = {path: row[path] for path in surface.paths()}
    sliced = run_backtest(
        BacktestRequest(strategy=apply_params(pinned(), params), bars=POOL_ROWS[100:300])
    )
    assert row["combined.net_pnl"] == sliced["combined"]["metrics"]["net_pnl"]


def test_map_window_sampled_stays_within_budget(window_pool):
    from products.aegis.studies import map_window
    from products.aegis.surface import build_grid

    grid = build_grid(pinned(), wide_surface(), 200)
    assert grid.valid_count == 88
    table, report = map_window(
        window_pool, grid, "sampled", 20, 10, "net_pnl", 0.15, 7, (100, 300), "QQQ w0"
    )
    cells = table.column("cell").to_pylist()
    assert 20 <= len(cells) <= 30 and len(set(cells)) == len(cells)
    assert set(table.column("pass").to_pylist()) <= {"sample", "refine"}
    assert report["mode"] == "sampled"
    again, _ = map_window(
        window_pool, grid, "sampled", 20, 10, "net_pnl", 0.15, 7, (100, 300), "QQQ w0"
    )
    assert again.column("cell").to_pylist() == cells
