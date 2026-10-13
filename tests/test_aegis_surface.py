"""Surfaces, grids and the planner (Mission 6 spec §5): counts without enumeration, validity per
indicator, the budget rule, sampling arithmetic and the ways back into scope."""

import math
import random

import pytest
from products.aegis.strategy import StrategySide, default_strategy
from products.aegis.surface import (
    KERNEL_MS_PER_BAR,
    Budget,
    Grid,
    Parameter,
    Surface,
    build_grid,
    effective_workers,
    plan,
    resolve_path,
)
from test_aegis_backtest import _breakout

BARS = 3493
WORKERS = 10


def pinned():
    """The Mission 5 breakout on the long side, the reference crossover on the short side."""
    return default_strategy().model_copy(update={"long_side": _breakout(None).long_side})


def P(path, start, stop, step):
    return Parameter(path=path, start=start, stop=stop, step=step)


def item2_surface(step_scale=1):
    s = step_scale
    return Surface(
        parameters=[
            P("long_side.indicators.donchian.length", 10, 40, 5 * s),
            P("long_side.indicators.rsi.length", 7, 28, 7 * s),
            P("short_side.indicators.ema.length", 5, 15, 5 * s),
            P("short_side.indicators.sma.length", 20, 40, 10 * s),
        ]
    )


def step_one_surface():
    return Surface(
        parameters=[
            P("long_side.indicators.donchian.length", 10, 40, 1),
            P("long_side.indicators.rsi.length", 7, 28, 1),
            P("short_side.indicators.ema.length", 5, 15, 1),
            P("short_side.indicators.sma.length", 20, 40, 1),
        ]
    )


def test_parameter_values_land_on_the_lattice_and_round_to_the_step():
    assert P("x", 10, 40, 5).values() == [10, 15, 20, 25, 30, 35, 40]
    assert P("x", 7, 28, 7).values() == [7, 14, 21, 28]
    assert P("x", 1.0, 1.5, 0.1).values() == [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]
    assert P("x", 2, 2, 1).values() == [2]


def test_item2_surface_is_exhaustive_under_budget():
    result = plan(pinned(), item2_surface(), Budget(runs=2000), BARS, KERNEL_MS_PER_BAR, WORKERS)
    assert (result.grid_cells, result.valid_cells, result.skipped) == (252, 252, 0)
    assert result.mode == "exhaustive" and result.planned_runs == 252
    assert result.first_pass == 252 and result.refinement == 0
    assert result.sampled_fraction == 1.0
    assert effective_workers(WORKERS) == 8.0
    assert result.estimate_seconds == pytest.approx(252 * BARS * 0.01 / 1000 / 8, rel=1e-9)
    assert result.levers == []


def test_step_one_surface_is_sampled_with_the_budget():
    result = plan(pinned(), step_one_surface(), Budget(runs=2000), BARS, 0.01, WORKERS)
    assert result.grid_cells == result.valid_cells == 157_542
    assert result.mode == "sampled" and result.planned_runs == 2000
    assert (result.first_pass, result.refinement) == (1334, 666)
    assert result.sampled_fraction == pytest.approx(2000 / 157_542)
    assert result.estimate_seconds == pytest.approx(2000 * BARS * 0.01 / 1000 / 8, rel=1e-9)


def test_levers_offer_every_way_back_into_scope():
    result = plan(
        pinned(), step_one_surface(), Budget(runs=2000), BARS, 0.01, WORKERS, timeframe="1h"
    )
    kinds = {(lever.kind, lever.parameter) for lever in result.levers}
    for path in [p.path for p in step_one_surface().parameters]:
        assert {("coarsen", path), ("narrow", path), ("freeze", path)} <= kinds
    assert {("shorten", None), ("coarser_timeframe", None), ("raise_budget", None)} <= kinds
    for lever in result.levers:
        assert lever.valid_cells > 0 and lever.estimate_seconds > 0
        assert lever.label and isinstance(lever.fits, bool)

    def lever(kind, parameter=None):
        return next(x for x in result.levers if x.kind == kind and x.parameter == parameter)

    coarsen = lever("coarsen", "long_side.indicators.donchian.length")
    assert coarsen.surface.parameters[0].values() == list(range(10, 41, 2))
    assert coarsen.valid_cells == 16 * 22 * 11 * 21
    narrow = lever("narrow", "long_side.indicators.rsi.length")  # pinned value 14, span 21
    assert narrow.surface.parameters[1].values() == list(range(9, 20))
    raise_budget = lever("raise_budget")
    assert raise_budget.budget == Budget(runs=157_542) and raise_budget.fits is True
    shorten = lever("shorten")
    assert shorten.estimate_seconds == pytest.approx(2000 * math.ceil(BARS / 2) * 0.01 / 1000 / 8)
    coarser = lever("coarser_timeframe")
    assert coarser.data_hint == "1D" and coarser.estimate_seconds < shorten.estimate_seconds

    # Freezing the two short-side parameters brings the grid under budget (spec §2 item 10).
    frozen = lever("freeze", "short_side.indicators.ema.length").surface
    again = plan(pinned(), frozen, Budget(runs=2000), BARS, 0.01, WORKERS)
    frozen = next(
        x
        for x in again.levers
        if x.kind == "freeze" and x.parameter == "short_side.indicators.sma.length"
    )
    assert frozen.valid_cells == 682 and frozen.fits is True
    final = plan(pinned(), frozen.surface, Budget(runs=2000), BARS, 0.01, WORKERS)
    assert final.mode == "exhaustive" and final.valid_cells == 682


def test_macd_grid_skips_invalid_combinations_without_enumerating():
    spec = pinned()
    data = spec.long_side.model_dump(mode="json")
    data["indicators"].append({"id": "macd", "kind": "MACD", "length": 12})
    spec = spec.model_copy(update={"long_side": StrategySide.model_validate(data)})
    surface = Surface(
        parameters=[
            P("long_side.indicators.macd.length", 10, 30, 10),
            P("long_side.indicators.macd.params.slow", 20, 30, 10),
        ]
    )
    grid = build_grid(spec, surface)
    assert (grid.size, grid.valid_count, grid.skipped_count) == (6, 3, 3)
    assert grid.skip_reasons == {"MACD fast length must be below slow": 3}
    valid = [i for i in range(grid.size) if grid.is_valid(i)]
    assert valid == [0, 1, 3]  # (10,20) (10,30) (20,30)
    assert (
        grid.skip_reason(2) == "MACD fast length must be below slow" and grid.skip_reason(0) is None
    )
    assert list(grid.valid_indices_iter()) == valid


def test_cell_values_and_index_round_trip():
    grid = build_grid(pinned(), item2_surface())
    assert isinstance(grid, Grid) and grid.shape == (7, 4, 3, 3)
    assert grid.cell_values(0) == {
        "long_side.indicators.donchian.length": 10,
        "long_side.indicators.rsi.length": 7,
        "short_side.indicators.ema.length": 5,
        "short_side.indicators.sma.length": 20,
    }
    assert grid.cell_values(grid.size - 1) == {
        "long_side.indicators.donchian.length": 40,
        "long_side.indicators.rsi.length": 28,
        "short_side.indicators.ema.length": 15,
        "short_side.indicators.sma.length": 40,
    }
    rng = random.Random(1)
    for index in (rng.randrange(grid.size) for _ in range(20)):
        assert grid.index_of(grid.cell_values(index)) == index
    applied = grid.apply_cell(pinned(), grid.cell_values(grid.size - 1))
    assert applied.long_side.indicator("donchian").length == 40
    assert applied.short_side.indicator("sma").length == 40
    assert applied.long_side.indicator("rsi").length == 28


def test_resolve_path_names_side_indicator_and_field():
    assert resolve_path(pinned(), "long_side.indicators.rsi.length") == (
        "long_side",
        "rsi",
        "length",
    )
    assert resolve_path(pinned(), "short_side.indicators.ema.length") == (
        "short_side",
        "ema",
        "length",
    )


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("long_side.indicators.nope.length", "unknown parameter path"),
        ("long_side.indicators.rsi.params.slow", "unknown parameter path"),
        ("indicators.rsi.length", "unknown parameter path"),
        ("long_side.indicators.rsi", "unknown parameter path"),
    ],
)
def test_bad_paths_are_refused_naming_the_path(path, message):
    with pytest.raises(ValueError, match=message):
        plan(pinned(), Surface(parameters=[P(path, 1, 2, 1)]), Budget(runs=10), BARS, 0.01, WORKERS)


def test_a_path_on_a_disabled_side_is_refused():
    spec = pinned()
    spec = spec.model_copy(
        update={"short_side": spec.short_side.model_copy(update={"enabled": False})}
    )
    with pytest.raises(ValueError, match="is on the disabled short side"):
        plan(
            spec,
            Surface(parameters=[P("short_side.indicators.ema.length", 5, 9, 1)]),
            Budget(runs=10),
            BARS,
            0.01,
            WORKERS,
        )


def test_whole_number_parameters_need_integer_ranges():
    with pytest.raises(ValueError, match="integer start, stop and step"):
        plan(
            pinned(),
            Surface(parameters=[P("long_side.indicators.rsi.length", 7, 21, 0.5)]),
            Budget(runs=10),
            BARS,
            0.01,
            WORKERS,
        )


def test_surface_shape_refusals():
    with pytest.raises(ValueError, match="a surface needs at least one parameter"):
        Surface(parameters=[])
    with pytest.raises(ValueError, match="at most 10 parameters"):
        Surface(parameters=[P(f"long_side.indicators.rsi.length{i}", 1, 2, 1) for i in range(11)])
    with pytest.raises(ValueError, match="duplicate parameter path"):
        Surface(parameters=[P("long_side.indicators.rsi.length", 1, 2, 1)] * 2)
    with pytest.raises(ValueError, match="start .* above stop"):
        P("long_side.indicators.rsi.length", 9, 2, 1)
    with pytest.raises(ValueError, match="step"):
        P("long_side.indicators.rsi.length", 2, 9, 0)


def test_budget_refusals():
    with pytest.raises(ValueError, match="a budget needs runs or seconds"):
        Budget()
    with pytest.raises(ValueError, match="runs must be positive"):
        Budget(runs=0)
    with pytest.raises(ValueError, match="seconds must be positive"):
        Budget(seconds=-1)
    with pytest.raises(ValueError, match="budget too small for a 4-parameter surface"):
        plan(pinned(), step_one_surface(), Budget(runs=8), BARS, 0.01, WORKERS)
    seconds_only = plan(pinned(), step_one_surface(), Budget(seconds=60), BARS, 0.01, WORKERS)
    assert seconds_only.mode == "sampled"
    assert seconds_only.planned_runs == int(60 * 8 * 1000 / (BARS * 0.01))


# --- Mission 6 Task 4: sampling and refinement -------------------------------------------------


def _grid(donchian=(10, 59, 1), rsi=(5, 54, 1), spec=None):
    from products.aegis.surface import build_grid, latin_hypercube  # noqa: F401 - exercised below

    surface = Surface(
        parameters=[
            P("long_side.indicators.donchian.length", *donchian),
            P("long_side.indicators.rsi.length", *rsi),
        ]
    )
    return build_grid(spec or pinned(), surface)


def test_grid_positions_strides_and_neighbours():
    grid = _grid((10, 12, 1), (5, 8, 1))  # 3 × 4
    assert grid.strides == (4, 1)
    assert grid.positions(0) == (0, 0) and grid.positions(11) == (2, 3)
    assert grid.positions(6) == (1, 2)
    assert sorted(grid.neighbours(6)) == [2, 5, 7, 10]
    assert sorted(grid.neighbours(0)) == [1, 4]
    assert sorted(grid.neighbours(11)) == [7, 10]


def test_latin_hypercube_covers_every_stratum_once_per_parameter():
    from products.aegis.surface import latin_hypercube

    grid = _grid()  # 50 × 50
    drawn = latin_hypercube(grid, 20, seed=1)
    assert len(drawn) == 20 and len(set(drawn)) == 20
    from products.aegis.surface import lhs_stratum

    for k in range(2):
        strata = {lhs_stratum(grid.positions(index)[k], 50, 20) for index in drawn}
        assert len(strata) == 20, (k, sorted(strata))
    assert [lhs_stratum(p, 50, 20) for p in (0, 1, 2, 4, 5, 49)] == [0, 0, 1, 1, 2, 19]


def test_latin_hypercube_is_seeded_and_skips_invalid_cells():
    from products.aegis.surface import latin_hypercube

    grid = _grid()
    assert latin_hypercube(grid, 20, seed=1) == latin_hypercube(grid, 20, seed=1)
    assert latin_hypercube(grid, 20, seed=2) != latin_hypercube(grid, 20, seed=1)
    spec = pinned()
    data = spec.long_side.model_dump(mode="json")
    data["indicators"].append({"id": "macd", "kind": "MACD", "length": 12})
    spec = spec.model_copy(update={"long_side": StrategySide.model_validate(data)})
    surface = Surface(
        parameters=[
            P("long_side.indicators.macd.length", 10, 30, 1),
            P("long_side.indicators.macd.params.slow", 20, 30, 1),
        ]
    )
    from products.aegis.surface import build_grid

    macd = build_grid(spec, surface)
    assert macd.skipped_count > 0
    drawn = latin_hypercube(macd, 30, seed=1)
    assert len(drawn) == 30 and len(set(drawn)) == 30
    assert all(macd.is_valid(index) for index in drawn)


def test_refinement_targets_plateau_neighbours_first():
    from products.aegis.surface import refinement_cells

    grid = _grid((1, 9, 1), (1, 9, 1))  # 9 × 9, positions == value - 1
    plateau = [
        grid.index_of(
            {"long_side.indicators.donchian.length": a, "long_side.indicators.rsi.length": b}
        )
        for a in (3, 4, 5, 6)
        for b in (3, 4, 5, 6)
    ]
    centre = grid.index_of(
        {"long_side.indicators.donchian.length": 4, "long_side.indicators.rsi.length": 4}
    )
    run = {index: 10.0 for index in plateau}
    run[
        grid.index_of(
            {"long_side.indicators.donchian.length": 9, "long_side.indicators.rsi.length": 9}
        )
    ] = 12.0
    chosen = refinement_cells(grid, run, [{"cells": plateau, "centre": {"cell": centre}}], budget=6)
    assert len(chosen) == 6 and not set(chosen) & set(run)
    for index in chosen:
        assert any(index in grid.neighbours(member) for member in plateau)
    distances = [
        sum(
            (p - c) ** 2 for p, c in zip(grid.positions(index), grid.positions(centre), strict=True)
        )
        for index in chosen
    ]
    assert distances == sorted(distances)
    everything = refinement_cells(
        grid, run, [{"cells": plateau, "centre": {"cell": centre}}], budget=100
    )
    assert len(everything) == 16  # the ring around a 4×4 block minus nothing run outside it
    no_plateau = refinement_cells(grid, run, [], budget=5)
    assert len(no_plateau) == 5 and not set(no_plateau) & set(run)
    best = max(run, key=run.get)
    assert all(index in grid.neighbours(best) for index in no_plateau[:2])
