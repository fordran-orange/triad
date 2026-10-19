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


# --- Task 5: the study job kind, its window files and resume ---------------------------------

NINE = Surface(
    parameters=[
        Parameter(path="long_side.indicators.donchian.length", start=10, stop=20, step=5),
        Parameter(path="long_side.indicators.rsi.length", start=7, stop=21, step=7),
    ]
)
PINNED_DATA = {"source": "raw_archive", "vintage": "test", "research_eligible": False}
LENGTHS = {"QQQ": 400, "SPY": 340}  # 4 and 3 windows of 120 + 60 bars


def symbol_rows(symbol: str, n: int) -> list[dict]:
    from test_aegis_walkforward import wave_bars

    amplitude = 10.0 if symbol == "QQQ" else 7.0
    return [
        {**row, "timestamp": row["timestamp"].isoformat(), "symbol": symbol}
        for row in wave_bars(n=n, period=37.0, amplitude=amplitude)
    ]


ROWS_BY_SYMBOL = {symbol: symbol_rows(symbol, n) for symbol, n in LENGTHS.items()}


def make_parent(repository, recommendation=True):
    from products.aegis.experiments import ExperimentStore

    store = ExperimentStore(repository)
    parent = experiment(bars=120, objective="net_pnl", surface=NINE, budget=Budget(runs=100))
    parent = parent.model_copy(update={"id": "nine-cells"})
    store.save(parent)
    grid_values = {
        "long_side.indicators.donchian.length": 15.0,
        "long_side.indicators.rsi.length": 14.0,
    }
    report = (
        {"recommendation": {"centre": {"cell": 4, "params": grid_values}}}
        if recommendation
        else {"recommendation": None}
    )
    store.write_report(parent.id, 1, report, "# report")
    return store, parent


def new_study(repository, name="walk nine", recommendation=True):
    from datetime import date

    from products.aegis.studies import StudyStore, create_study

    experiments, parent = make_parent(repository, recommendation)
    request = StudyRequest(
        experiment_id=parent.id,
        name=name,
        symbols=list(LENGTHS),
        in_sample_bars=120,
        out_of_sample_bars=60,
    )
    bars = {s: [r["timestamp"] for r in rows] for s, rows in ROWS_BY_SYMBOL.items()}
    document = create_study(
        StudyStore(repository), experiments, request, bars, 2, date(2026, 1, 5), date(2026, 1, 31)
    )
    return document


def job_for(repository, document):
    from products.aegis.studies import StudyJob

    return StudyJob(
        document,
        ROWS_BY_SYMBOL,
        {s: {**PINNED_DATA, "symbol": s} for s in LENGTHS},
        repository,
        max_workers=2,
    )


def stored(repository, study_id):
    from products.aegis.studies import StudyStore

    return StudyStore(repository).get(study_id)


def run_to(repository, document, statuses=("done", "failed"), after_unit=None):
    from products.aegis.jobs import JobRunner
    from test_aegis_experiments import wait_for

    runner = JobRunner(repository, after_unit=after_unit)
    job = job_for(repository, document)
    job_id = runner.start(job)
    assert wait_for(lambda: stored(repository, document.id).status in statuses, timeout=240)
    assert wait_for(lambda: runner.status(job_id)["status"] not in ("queued", "running"))
    return runner, job, job_id, stored(repository, document.id)


def hashes(document):
    return {
        symbol: {
            rule: entry["rules"][rule].get("result_hash") for rule in ("plateau", "peak", "frozen")
        }
        for symbol, entry in document.report["symbols"].items()
    }


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    from products.aegis.runs import JsonRunRepository

    repository = JsonRunRepository(tmp_path_factory.mktemp("reference") / "aegis")
    document = new_study(repository)
    _, job, _, done = run_to(repository, document)
    assert done.status == "done", done.error
    return repository, done, job


def test_study_runs_to_done_with_every_window_once(reference):
    from products.aegis.studies import StudyStore

    repository, done, job = reference
    assert job.name == "study" and job.resumable and job.bars_per_unit == 0
    assert StudyStore(repository).done_windows(done.id) == {"QQQ": {0, 1, 2, 3}, "SPY": {0, 1, 2}}
    assert [w["index"] for w in done.windows["QQQ"]] == [0, 1, 2, 3]
    assert [w["index"] for w in done.windows["SPY"]] == [0, 1, 2]
    assert done.progress["windows_done"] == done.progress["windows_total"] == 7
    for symbol in LENGTHS:
        for rule, value in hashes(done)[symbol].items():
            assert value is not None and len(value) == 64, (symbol, rule)
    compact = done.windows["QQQ"][1]["rules"]["plateau"]
    assert "trades" not in compact["combined"]
    full = StudyStore(repository).read_window(done.id, "QQQ", 1)
    assert "trades" in full["rules"]["plateau"]["combined"] and full["chains_out"]["plateau"]
    assert full["mode"] == "exhaustive" and full["cells_run"] == 9
    # spec §5.5: each rule's carried in and out stay on the document's record
    assert compact["sides"] and done.windows["QQQ"][1]["chains_in"] == full["chains_in"]
    assert done.windows["QQQ"][1]["chains_out"] == full["chains_out"]
    cells = StudyStore(repository).cells(done.id, "QQQ", 1)
    assert sorted(cells.column("cell").to_pylist()) == list(range(9))
    assert done.report["raw_archive"] is True and done.report["summary"].startswith("plateau rule")


def test_window_records_name_the_choice_and_the_previous_plateau(reference):
    _, done, _ = reference
    for symbol, windows in done.windows.items():
        first = windows[0]
        assert first["centre_inside"] is None and first["moved"] is None
        for window in windows:
            assert (window["plateau"] is None) == (window["no_plateau"] is not None), symbol
            assert window["rules"]["frozen"]["params"] == {
                "long_side.indicators.donchian.length": 15.0,
                "long_side.indicators.rsi.length": 14.0,
            }
            if window["plateau"] is None:
                assert window["rules"]["plateau"]["flat"] is True


def test_identical_study_reproduces_every_hash(reference, tmp_path):
    from products.aegis.runs import JsonRunRepository

    _, done, _ = reference
    repository = JsonRunRepository(tmp_path / "aegis")
    _, _, _, again = run_to(repository, new_study(repository))
    assert again.status == "done", again.error
    assert hashes(again) == hashes(done)


def pause_after(units: int):
    state: dict = {}

    def hook(done):
        if done == units:
            job = state["runner"].job_kind(state["job_id"])
            job.pause_requested = True
            state["runner"].cancel(state["job_id"])

    return state, hook


def test_pause_lands_at_a_window_boundary_then_resumes(reference, tmp_path):
    from products.aegis.jobs import JobRunner
    from products.aegis.runs import JsonRunRepository
    from test_aegis_experiments import wait_for

    _, done, _ = reference
    repository = JsonRunRepository(tmp_path / "aegis")
    document = new_study(repository)
    state, hook = pause_after(2)
    runner = JobRunner(repository, after_unit=hook)
    state["runner"] = runner
    state["job_id"] = runner.start(job_for(repository, document))
    assert wait_for(lambda: stored(repository, document.id).status == "paused", timeout=240)
    paused = stored(repository, document.id)
    assert [w["index"] for w in paused.windows["QQQ"]] == [0, 1] and "SPY" not in paused.windows
    resumed = job_for(repository, paused)
    assert resumed.units == [("QQQ", 2), ("QQQ", 3), ("SPY", 0), ("SPY", 1), ("SPY", 2)]
    _, _, _, finished = run_to(repository, paused)
    assert finished.status == "done", finished.error
    assert [w["index"] for w in finished.windows["QQQ"]] == [0, 1, 2, 3]
    assert hashes(finished) == hashes(done)


def test_resume_restores_the_chains_from_the_last_window_file(
    reference, tmp_path
):  # Review Focus 3
    from products.aegis.jobs import JobRunner
    from products.aegis.runs import JsonRunRepository
    from products.aegis.studies import StudyStore
    from test_aegis_experiments import wait_for

    _, done, _ = reference
    repository = JsonRunRepository(tmp_path / "aegis")
    document = new_study(repository)
    state, hook = pause_after(6)  # QQQ 0-3 and SPY 0-1
    runner = JobRunner(repository, after_unit=hook)
    state["runner"] = runner
    state["job_id"] = runner.start(job_for(repository, document))
    assert wait_for(lambda: stored(repository, document.id).status == "paused", timeout=240)
    # A worker that died mid-run leaves the document running; the next worker pauses it.
    dead = repository.get_study(document.id)
    dead["status"] = "running"
    repository.save_study(dead)
    assert JobRunner(repository).mark_lost_on_startup() == [document.id]
    assert stored(repository, document.id).status == "paused"
    store = StudyStore(repository)
    before = {w: store.window_paths(document.id, "SPY", w)[0].stat().st_mtime_ns for w in (0, 1)}
    resumed = job_for(repository, stored(repository, document.id))
    assert resumed.units == [("SPY", 2)]
    last = store.read_window(document.id, "SPY", 1)
    for rule, sides in last["chains_out"].items():
        for side, chain in sides.items():
            assert resumed.chains["SPY"][rule][side].as_dict() == chain, (rule, side)
    _, _, _, finished = run_to(repository, stored(repository, document.id))
    assert finished.status == "done", finished.error
    assert hashes(finished) == hashes(done)
    assert {
        w: store.window_paths(document.id, "SPY", w)[0].stat().st_mtime_ns for w in (0, 1)
    } == before


def test_a_torn_window_file_reruns_that_window_and_every_later_one(reference, tmp_path):
    import shutil

    from products.aegis.runs import JsonRunRepository
    from products.aegis.studies import StudyStore

    source_repository, done, _ = reference
    repository = JsonRunRepository(tmp_path / "aegis")
    repository.save_study(source_repository.get_study(done.id))
    shutil.copytree(source_repository.study_dir(done.id), repository.study_dir(done.id))
    store = StudyStore(repository)
    json_path, _ = store.window_paths(done.id, "QQQ", 2)
    json_path.write_text("{torn", encoding="utf-8")
    assert store.done_windows(done.id)["QQQ"] == {0, 1, 3}
    job = job_for(repository, stored(repository, done.id).model_copy(update={"status": "paused"}))
    assert job.units == [("QQQ", 2), ("QQQ", 3)]


def test_frozen_column_is_absent_when_the_parent_has_no_recommendation(tmp_path):
    from products.aegis.runs import JsonRunRepository

    document = new_study(JsonRunRepository(tmp_path / "aegis"), recommendation=False)
    assert document.frozen_centre is None
    assert document.frozen_absent == "the parent report has no recommendation"
    assert document.status == "queued" and document.progress["windows_total"] == 7


def test_frozen_centre_comes_from_the_parents_report_on_its_own_objective(tmp_path):
    """A recomputed report on another objective or tolerance never becomes the frozen centre."""
    from datetime import date

    from products.aegis.runs import JsonRunRepository
    from products.aegis.studies import StudyStore, create_study

    repository = JsonRunRepository(tmp_path / "aegis")
    experiments, parent = make_parent(repository)  # report 1 recommends cell 4 on net_pnl, 0.15
    other = {"long_side.indicators.donchian.length": 10.0, "long_side.indicators.rsi.length": 7.0}
    experiments.write_report(
        parent.id, 2, {"recommendation": {"centre": {"cell": 0, "params": other}}}, "# r2"
    )
    reports = [
        {"report_id": 1, "objective": "net_pnl", "tolerance": 0.15, "generated_at": "x"},
        {"report_id": 2, "objective": "mar", "tolerance": 0.1, "generated_at": "y"},
    ]
    experiments.save(parent.model_copy(update={"reports": reports, "latest_report": 2}))
    request = StudyRequest(
        experiment_id=parent.id, symbols=list(LENGTHS), in_sample_bars=120, out_of_sample_bars=60
    )
    bars = {s: [r["timestamp"] for r in rows] for s, rows in ROWS_BY_SYMBOL.items()}
    store = StudyStore(repository)
    document = create_study(
        store, experiments, request, bars, 2, date(2026, 1, 5), date(2026, 1, 31)
    )
    assert document.frozen_centre["cell"] == 4
    experiments.save(parent.model_copy(update={"reports": reports[1:], "latest_report": 2}))
    absent = create_study(store, experiments, request, bars, 2, date(2026, 1, 5), date(2026, 1, 31))
    assert absent.frozen_centre is None
    assert (
        absent.frozen_absent
        == "the parent has no report on its own objective net_pnl at tolerance 0.15"
    )
