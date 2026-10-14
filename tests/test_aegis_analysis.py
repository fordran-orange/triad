"""The analysis (Mission 6 spec §7, peaks to plateaus) on synthetic surfaces with known answers."""

import math

import numpy as np
import pytest
from products.aegis.analysis import (
    analyse,
    clusters,
    interactions,
    main_effects,
    neighbours_sampled,
    peaks,
    plateaus,
    render_markdown,
    sensitivity,
)
from products.aegis.surface import Parameter, Surface, build_grid
from test_aegis_surface import pinned

pytestmark = pytest.mark.aegis

A = "long_side.indicators.donchian.length"
B = "long_side.indicators.rsi.length"
METRICS = (
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
)


def grid2(a=(1, 9, 1), b=(1, 9, 1)):
    return build_grid(
        pinned(),
        Surface(
            parameters=[
                Parameter(path=A, start=a[0], stop=a[1], step=a[2]),
                Parameter(path=B, start=b[0], stop=b[1], step=b[2]),
            ]
        ),
    )


def grid1(b=(1, 9, 1)):
    return build_grid(
        pinned(), Surface(parameters=[Parameter(path=B, start=b[0], stop=b[1], step=b[2])])
    )


def rows_for(grid, objective, cells=None, extra=None):
    """Cells rows (the Parquet shape) with `combined.net_pnl = objective(values)` and plain
    numbers elsewhere; `extra(values) -> dict` overrides any metric."""
    out = []
    for index in cells if cells is not None else range(grid.size):
        values = grid.cell_values(index)
        row = {"cell": index, "pass": "grid", "valid": True, "skip_reason": None, **values}
        for scope in ("combined", "long", "short"):
            for metric in METRICS:
                row[f"{scope}.{metric}"] = 1.0
        value = objective(values)
        row["combined.net_pnl"] = value
        if extra is not None:
            for key, v in extra(values).items():
                row[f"combined.{key}"] = v
        out.append(row)
    return out


def plateau_surface(values):
    a, b = values[A], values[B]
    if 3 <= a <= 6 and 3 <= b <= 6:
        return 10.0
    if a == 8 and b == 8:
        return 12.0
    return 0.0


def cell(grid, a, b):
    return grid.index_of({A: a, B: b})


def test_flat_surface_has_no_recommendation():
    grid = grid2()
    report = analyse(
        rows_for(grid, lambda v: 7.0), grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ 1h"
    )
    assert report["recommendation"] is None and report["tau"] == 0
    assert "flat" in report["statement"].lower()
    assert report["valid_cells"] == 81 and report["null_objective_cells"] == 0


def test_plateau_counts_and_the_spike_is_fragile():
    grid = grid2()
    report = analyse(
        rows_for(grid, plateau_surface), grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ 1h"
    )
    assert report["tau"] == pytest.approx(1.5)
    spike = cell(grid, 8, 8)
    assert report["recommendation"] is not None
    plateau = report["plateaus"][0]
    assert plateau["counts"] is True and plateau["size"] == 16
    assert sorted(plateau["cells"]) == sorted(
        cell(grid, a, b) for a in range(3, 7) for b in range(3, 7)
    )
    assert plateau["median"] == 10.0 and plateau["iqr"] == 0.0 and plateau["cliff"] == 10.0
    assert plateau["centre"]["cell"] == cell(grid, 4, 4)
    assert plateau["centre"]["params"] == {A: 4, B: 4}
    rec = report["recommendation"]
    assert rec["plateau"] == plateau["id"] and rec["centre"]["cell"] == cell(grid, 4, 4)
    assert (
        rec["supported_peak"]["cell"] in plateau["cells"]
        and rec["supported_peak"]["objective"] == 10.0
    )
    assert [p["cell"] for p in rec["fragile_peaks"]] == [spike]
    fragile = next(p for p in report["peaks"] if p["cell"] == spike)
    assert (
        fragile["fragile"] is True and fragile["objective"] == 12.0 and fragile["plateau"] is None
    )
    assert report["uncertainty"]["cells"] == 16 and report["uncertainty"]["iqr"] == 0.0
    assert "QQQ 1h" in report["uncertainty"]["statement"]
    assert spike in report["cells_named"] and cell(grid, 4, 4) in report["cells_named"]


def test_one_parameter_surface_has_neighbours_plateaus_and_no_interactions():
    grid = grid1()
    series = {1: 0.0, 2: 1.0, 3: 5.0, 4: 5.0, 5: 5.0, 6: 1.0, 7: 0.0, 8: 0.0, 9: 0.0}
    report = analyse(
        rows_for(grid, lambda v: series[v[B]]), grid, "net_pnl", 0.15, "exhaustive", 1, "x"
    )
    assert report["interactions"] is None
    assert report["recommendation"] is not None
    plateau = report["plateaus"][0]
    assert sorted(plateau["cells"]) == [2, 3, 4] and plateau["counts"] is True  # 3 cells, 2d + 1
    assert report["recommendation"]["centre"]["cell"] == 3
    assert set(report["main_effects"]) == {B} and len(report["main_effects"][B]) == 9


def test_null_objective_everywhere_is_refused_honestly():
    grid = grid2()
    rows = rows_for(grid, lambda v: 1.0)
    for row in rows:
        row["combined.mar"] = None
    report = analyse(rows, grid, "mar", 0.15, "exhaustive", 1, "x")
    assert report["recommendation"] is None and report["null_objective_cells"] == 81
    assert "no valid objective values" in report["statement"]
    assert report["plateaus"] == [] and report["peaks"] == []


def test_max_drawdown_is_minimized():
    grid = grid2()
    rows = rows_for(
        grid,
        lambda v: 0.0,
        extra=lambda v: {"max_drawdown": 0.5 - (0.3 if 3 <= v[A] <= 6 and 3 <= v[B] <= 6 else 0.0)},
    )
    report = analyse(rows, grid, "max_drawdown", 0.15, "exhaustive", 1, "x")
    assert report["recommendation"]["centre"]["params"] == {A: 4, B: 4}
    assert report["plateaus"][0]["median"] == pytest.approx(
        0.2
    )  # reported in the metric's own sign


def test_main_effects_interactions_and_sensitivity_on_known_surfaces():
    grid = grid2()
    plateau_rows = rows_for(grid, plateau_surface)
    effects = main_effects(plateau_rows, grid, "combined.net_pnl")
    at_four = next(e for e in effects[A] if e["value"] == 4)
    assert (at_four["median"], at_four["p25"], at_four["p75"], at_four["count"]) == (
        0.0,
        0.0,
        10.0,
        9,
    )

    additive_rows = rows_for(grid, lambda v: v[A] + 2 * v[B])
    pairs = interactions(additive_rows, grid, "combined.net_pnl")
    assert len(pairs) == 1 and pairs[0]["paths"] == [A, B]
    assert pairs[0]["strength"] == pytest.approx(0.0, abs=1e-9)
    assert np.array(pairs[0]["matrix"]).shape == (9, 9)
    product_rows = rows_for(grid, lambda v: v[A] * v[B])
    assert interactions(product_rows, grid, "combined.net_pnl")[0]["strength"] > 1.0

    shares = sensitivity(additive_rows, grid, "combined.net_pnl")
    assert shares["shares"][A] == pytest.approx(0.2, abs=1e-6)
    assert shares["shares"][B] == pytest.approx(0.8, abs=1e-6)
    assert shares["remainder"] == pytest.approx(0.0, abs=1e-6)


def test_clusters_are_reported_only_with_clear_structure_and_enough_cells():
    grid = grid2()

    def two_groups(v):
        first = v[A] <= 4
        return {
            "net_return": 0.5 if first else -0.2,
            "max_drawdown": 0.05 if first else 0.4,
            "trade_count": 10.0 if first else 50.0,
            "exposure": 0.3 if first else 0.9,
        }

    rows = rows_for(grid, lambda v: 1.0, cells=range(60), extra=two_groups)
    found = clusters(rows, seed=1)
    assert found["k"] == 2 and found["silhouette"] >= 0.5 and len(found["groups"]) == 2
    assert sum(g["size"] for g in found["groups"]) == 60
    assert all(set(g["parameter_ranges"]) == {A, B} for g in found["groups"])
    assert clusters(rows[:15], seed=1) == {"refused": "fewer than 20 valid cells"}
    blob = rows_for(
        grid,
        lambda v: 1.0,
        cells=range(40),
        extra=lambda v: {
            "net_return": 0.1 + 1e-6 * v[A],
            "max_drawdown": 0.1,
            "trade_count": 10.0,
            "exposure": 0.5,
        },
    )
    assert clusters(blob, seed=1)["refused"].startswith("no clear structure")


def test_sampled_neighbours_are_the_nearest_run_cells():
    grid = grid2((1, 50, 1), (1, 50, 1))
    rng = np.random.default_rng(1)
    run = sorted(int(i) for i in rng.choice(grid.size, size=400, replace=False))
    relation = neighbours_sampled(grid, run, k=4)
    assert set(relation) == set(run) and all(len(v) == 4 for v in relation.values())
    some = run[7]
    px = np.array(grid.positions(some)) / 49
    distances = sorted(
        (float(np.linalg.norm(np.array(grid.positions(other)) / 49 - px)), other)
        for other in run
        if other != some
    )
    assert sorted(relation[some]) == sorted(index for _, index in distances[:4])
    report = analyse(
        rows_for(grid, lambda v: math.sin(v[A] / 7) + math.cos(v[B] / 9), cells=run),
        grid,
        "net_pnl",
        0.15,
        "sampled",
        1,
        "x",
    )
    assert "nearest" in report["neighbour_rule"]


def test_peaks_and_plateaus_helpers_agree_with_the_report():
    grid = grid2()
    values = {index: plateau_surface(grid.cell_values(index)) for index in range(grid.size)}
    relation = {index: grid.neighbours(index) for index in range(grid.size)}
    found_peaks = peaks(values, relation)
    assert cell(grid, 8, 8) in found_peaks and cell(grid, 3, 3) in found_peaks
    assert cell(grid, 4, 4) not in found_peaks and cell(grid, 1, 1) not in found_peaks
    found = plateaus(values, relation, found_peaks, tau=1.5, min_cells=5)
    assert [p["size"] for p in found if p["counts"]] == [16]
    assert [p["size"] for p in found if not p["counts"]] == [1]


def test_markdown_starts_with_the_recommendation_and_has_every_section():
    grid = grid2()
    report = analyse(
        rows_for(grid, plateau_surface), grid, "net_pnl", 0.15, "exhaustive", 1, "QQQ 1h"
    )
    text = render_markdown({**report, "report_id": 1, "generated_at": "2026-10-12T00:00:00+00:00"})
    first = next(line for line in text.splitlines() if line.strip())
    assert "Recommendation" in first
    for heading in (
        "Plateaus",
        "Peaks",
        "Main effects",
        "Interactions",
        "Sensitivity",
        "Clusters",
        "Uncertainty",
    ):
        assert f"## {heading}" in text, heading
    assert "fragile" in text and "4" in text


def test_no_plateau_statement_names_the_best_cell_without_phantom_others():
    grid = grid2((1, 3, 1), (1, 3, 1))
    rows = rows_for(grid, lambda v: 9.0 if (v[A], v[B]) == (2, 2) else 0.0)
    report = analyse(rows, grid, "net_pnl", 0.15, "exhaustive", 1, "x")
    assert report["recommendation"] is None
    assert "is a fragile peak" in report["statement"]
    assert "other 0" not in report["statement"]
    two = rows_for(grid, lambda v: 9.0 if (v[A], v[B]) in ((1, 1), (3, 3)) else 0.0)
    assert (
        "as is 1 other fragile peak"
        in analyse(two, grid, "net_pnl", 0.15, "exhaustive", 1, "x")["statement"]
    )


def test_plateaus_reached_from_several_peaks_merge_into_one():
    """Review finding 3: a lower peak whose band bridges two higher plateaus must union them
    (spec §7: plateaus reached from several peaks are one plateau), never leave a twin."""
    from products.aegis.analysis import neighbours_exhaustive

    grid = grid1((1, 9, 1))
    heights = [10, 10, 10, 7.5, 8, 7.5, 10, 10, 10]
    values = {i: float(h) for i, h in enumerate(heights)}
    relation = neighbours_exhaustive(grid, sorted(values))
    found = plateaus(values, relation, peaks(values, relation), tau=1.0, min_cells=3)
    assert len(found) == 1, [(p["cells"], p["size"]) for p in found]
    assert found[0]["cells"] == list(range(9)) and found[0]["counts"]
    assert {0, 4, 6} <= set(found[0]["peaks"])


def test_flat_between_the_percentiles_is_not_called_identical():
    """Review finding 6: P10 == P90 with differing values is an empty tolerance band, not a
    constant surface; the headline must not claim every cell is the same."""
    grid = grid2((1, 10, 1), (1, 10, 1))
    rows = rows_for(grid, lambda v: 5.0)
    for k, cell in enumerate(range(0, 88, 11)):  # eight cells spread 0 … 84 among 92 at 5.0
        rows[cell]["combined.net_pnl"] = 12.0 * k
    report = analyse(rows, grid, "net_pnl", 0.15, "exhaustive", 1, "x")
    assert report["tau"] == 0 and report["recommendation"] is None
    assert "between the 10th and 90th percentiles" in report["statement"], report["statement"]
    assert "every valid cell has the same" not in report["statement"]
    assert report["peaks"] and report["peaks"][0]["cell"] == 77 and report["peaks"][0]["fragile"]
    assert report["cells_named"] == [77]
