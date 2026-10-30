"""Optimization Lab v2, Phase 3 Task 8: the Pareto front, the exact parallel sample and convergence
(spec §7.7, §7.9, §7.10, §9.3; decisions 7 and 8). The fronts are checked against the definition
by brute force, the views against hand-written frames and recounts, and every payload is plain
strict JSON."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import pairwise

import numpy as np
import pyarrow as pa
import pytest
from lab_stat_fixtures import first_order, lattice_frame, paths_of, stat_frame, trial_at, zero
from products.aegis import api
from products.aegis.lab import convergence as convergence_module
from products.aegis.lab import neighbours as neighbours_module
from products.aegis.lab import policy, sources
from products.aegis.lab.convergence import convergence_view
from products.aegis.lab.index import build_index
from products.aegis.lab.neighbours import PositionLookup, neighbourhood
from products.aegis.lab.parallel import sample_view
from products.aegis.lab.pareto import front_2d, front_3d, pareto_view
from products.aegis.lab.query import (
    LabFilter,
    TrialFrame,
    _numbers,
    _trial_numbers,
    even_positions,
    filter_mask,
)
from products.aegis.pool import SCOPES
from test_lab_query import synthetic_frame

pytestmark = pytest.mark.aegis

COMBINED = "combined"
PNL_DD = ["net_pnl", "max_drawdown"]
NEIGHBOURS = (
    "neighbours read every completed block-0 trial of the snapshot, "
    "the filter selects each batch's top trials"
)


# --- helpers ----------------------------------------------------------------------------------


def trials(**columns) -> TrialFrame:
    """`stat_frame`'s rows (two parameters of 8 values, every evaluation ok, numbered from 0), with
    these metric columns written in every scope."""
    n = len(next(iter(columns.values())))
    frame = stat_frame(d=2, values=8, n=n, seed=1, y=zero)
    table = frame.table
    for name, values in columns.items():
        array = pa.array(np.asarray(values, dtype=np.float64), pa.float64())
        for scope in SCOPES:
            column = f"{scope}.{name}"
            table = table.set_column(table.schema.get_field_index(column), column, array)
    return replace(frame, table=table)


def ids(frame: TrialFrame, numbers) -> list[str]:
    return [f"{frame.source}#{int(n)}" for n in numbers]


def strict(value) -> None:
    """Plain strict JSON all the way down: no numpy scalar, no NaN, no mapping proxy."""
    if isinstance(value, dict):
        assert type(value) is dict
        for key, held in value.items():
            assert type(key) is str
            strict(held)
    elif isinstance(value, list):
        for held in value:
            strict(held)
    else:
        assert value is None or type(value) in (str, int, float, bool), (type(value), value)
    json.dumps(value, allow_nan=False)


def answer(frame: TrialFrame, flt: dict | None = None, *, index=None, **body) -> dict:
    """One view through `run_query`, as the route calls it."""
    request = api.QueryRequest.model_validate({"filter": flt or {}, **body})
    return sources.run_query(frame, request, index=index)


def brute_front(*objectives) -> np.ndarray:
    """The rows nothing dominates, by the definition: at least as good everywhere, better
    somewhere. An equal point dominates nothing."""
    points = np.stack(objectives, axis=1)
    kept = []
    for i, point in enumerate(points):
        at_least = (points >= point).all(axis=1)
        better = (points > point).any(axis=1)
        if not (at_least & better).any():
            kept.append(i)
    return np.array(kept, dtype=np.int64)


def tied_points(seed: int, k: int) -> list[np.ndarray]:
    """2,000 points of `k` objectives, in four shapes that tie differently: a coarse integer grid,
    rounded normals, an anti-correlated pair (a large front, many values shared) and exact
    duplicates of continuous points."""
    rng = np.random.default_rng(seed)
    n = 2_000
    shape = seed % 4
    if shape == 0:
        points = rng.integers(0, 25, size=(n, k)).astype(np.float64)
    elif shape == 1:
        points = np.round(rng.normal(0.0, 10.0, size=(n, k)))
    elif shape == 2:
        x = rng.integers(0, 400, size=n).astype(np.float64)
        points = np.stack([x, 400.0 - x + rng.integers(0, 3, size=n)], axis=1)
        if k == 3:
            points = np.c_[points, rng.integers(0, 5, size=n).astype(np.float64)]
    else:
        points = rng.normal(0.0, 1.0, size=(200, k))[rng.integers(0, 200, size=n)]
    return [points[:, j] for j in range(k)]


# --- the fronts --------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(50))
def test_front_2d_matches_brute_force(seed):
    a, b = tied_points(seed, 2)
    found = front_2d(a, b)
    assert found.tolist() == brute_front(a, b).tolist()
    assert np.issubdtype(found.dtype, np.integer)


@pytest.mark.parametrize("seed", range(50))
def test_front_3d_matches_brute_force(seed):
    a, b, c = tied_points(seed, 3)
    found = front_3d(a, b, c)
    assert found.tolist() == brute_front(a, b, c).tolist()
    assert np.issubdtype(found.dtype, np.integer)


@pytest.mark.parametrize(
    ("points", "front"),
    [
        ([(1, 1), (1, 1), (0, 0)], [0, 1]),  # an equal point is not dominated
        ([(1, 1), (1, 0), (0, 1)], [0]),  # a tie on one objective and worse on the other is
        ([(2, 0), (0, 2), (1, 1)], [0, 1, 2]),
        ([(0, 0)], [0]),
        ([(3, 3), (3, 3), (3, 3)], [0, 1, 2]),
    ],
)
def test_front_2d_ties(points, front):
    a, b = np.array(points, dtype=np.float64).T
    assert front_2d(a, b).tolist() == front


@pytest.mark.parametrize(
    ("points", "front"),
    [
        ([(1, 1, 1), (1, 1, 1), (0, 0, 0)], [0, 1]),
        ([(1, 1, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)], [0]),
        ([(2, 0, 0), (0, 2, 0), (0, 0, 2), (1, 1, 1)], [0, 1, 2, 3]),
        ([(1, 0, 5), (1, 5, 0), (0, 5, 5)], [0, 1, 2]),
        ([(0, 0, 0)], [0]),
    ],
)
def test_front_3d_ties(points, front):
    a, b, c = np.array(points, dtype=np.float64).T
    assert front_3d(a, b, c).tolist() == front


def test_fronts_of_nothing_and_of_undefined_values():
    assert front_2d([], []).tolist() == [] and front_3d([], [], []).tolist() == []
    for bad in (np.nan, np.inf, -np.inf):  # the view excludes these first: never ranked
        with pytest.raises(ValueError, match="finite"):
            front_2d([1.0, bad], [1.0, 2.0])
        with pytest.raises(ValueError, match="finite"):
            front_3d([1.0, 2.0], [1.0, 2.0], [1.0, bad])
    with pytest.raises(ValueError, match="length"):
        front_2d([1.0], [1.0, 2.0])


def test_front_3d_holds_a_wide_front_past_its_pairwise_blocks():
    """Far more points than one pairwise block, every one of them on the front, then a stream
    where only the last block's points survive: the nested blocks answer as the definition does."""
    rng = np.random.default_rng(3)
    x = rng.permutation(3_000).astype(np.float64)
    wide = [rng.permutation(3_000).astype(np.float64), x, -x]
    assert front_3d(*wide).tolist() == list(range(3_000))
    a = np.arange(3_000, dtype=np.float64)
    assert front_3d(a, a, a).tolist() == [2_999]
    assert front_3d(-a, a, a).tolist() == brute_front(-a, a, a).tolist()


# --- the Pareto view ----------------------------------------------------------------------------


def test_pareto_respects_orientation():
    """max_drawdown is minimized: trial 1 beats trial 0 on it at the same P&L, and trial 2 beats
    trial 3 on both. Taken as larger-is-better the front would be trials 0 alone."""
    frame = trials(net_pnl=[10, 10, 5, 4], max_drawdown=[5, 3, 1, 2])
    out = pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert out["front"] == ids(frame, [1, 2])
    assert (out["front_size"], out["dominated"], out["excluded"]) == (2, 2, 0)
    assert out["objectives"] == PNL_DD and out["orientation"] == [1, -1]
    assert out["points"] == [  # in the metrics' own units, never negated
        {"trial_id": f"{frame.source}#1", "values": [10.0, 3.0]},
        {"trial_id": f"{frame.source}#2", "values": [5.0, 1.0]},
    ]
    maximized = pareto_view(frame, LabFilter(), objectives=["net_pnl", "exposure"], scope=COMBINED)
    assert maximized["orientation"] == [1, 1]
    swapped = pareto_view(frame, LabFilter(), objectives=PNL_DD[::-1], scope=COMBINED)
    assert set(swapped["front"]) == set(out["front"]) and swapped["orientation"] == [-1, 1]
    three = trials(net_pnl=[1, 1, 0], max_drawdown=[1, 2, 1], win_rate=[1, 1, 2])
    held = pareto_view(three, LabFilter(), objectives=[*PNL_DD, "win_rate"], scope=COMBINED)
    assert held["front"] == ids(three, [0, 2]) and held["orientation"] == [1, -1, 1]


def test_the_front_lies_along_the_first_objective():
    """Best first along the first objective, so a capped front still has both its ends."""
    frame = trials(net_pnl=[1, 3, 2], max_drawdown=[1, 3, 2])
    out = pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert out["front"] == ids(frame, [1, 2, 0])


def test_front_size_capped_with_a_label():
    """A 5,000-point front (more P&L only with more drawdown) above 300 dominated trials: 2,000
    drawn, evenly along the front, both its ends kept, its true size stated. The 800 ms budget is
    measured by `explore` (Task 12)."""
    assert policy.PARETO_FRONT_MAX == 2_000
    front = np.arange(5_000, dtype=np.float64)
    cloud = np.arange(300, dtype=np.float64)
    frame = trials(
        net_pnl=np.r_[front, -1_000.0 - cloud],
        max_drawdown=np.r_[front, 10_000.0 + cloud],
    )
    out = pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert out["sampled"] is True and out["front_size"] == 5_000 and out["dominated"] == 300
    assert len(out["front"]) == len(out["points"]) == 2_000
    assert out["front"] == [point["trial_id"] for point in out["points"]]
    assert out["front"][0] == f"{frame.source}#4999" and out["front"][-1] == f"{frame.source}#0"
    spaced = [int(trial.split("#")[1]) for trial in out["front"]]
    assert {a - b for a, b in pairwise(spaced)} <= {2, 3}
    assert out["basis"] == "Sampled subset (2000 of 5000)"
    assert out == pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    sent = answer(frame, view="pareto", objectives=PNL_DD)
    assert sent["scope"]["shown"] == 2_000
    assert sent["scope"]["basis"] == "Sampled subset (2000 of 5000)"
    strict(sent)
    exact = trials(net_pnl=front[:2_000], max_drawdown=front[:2_000])
    held = pareto_view(exact, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert held["sampled"] is False and held["front_size"] == len(held["front"]) == 2_000
    assert held["basis"] == "Tested (exact)"
    assert answer(exact, view="pareto", objectives=PNL_DD)["scope"]["basis"] == "Tested (exact)"


def test_pareto_reads_the_filter_and_the_completed_rows_only():
    """Decision 7: the filter's completed block-0 trials only, by brute force on a frame with
    invalid and failed rows, whose missing metrics are never counted as undefined here."""
    frame = synthetic_frame(4_000, 4, 11)
    path = frame.parameters[0].path
    values = frame.parameters[0].values
    flt = LabFilter(ranges={path: (values[1], values[3])}, scope="long")
    mask = filter_mask(frame, flt)
    a = _numbers(frame.table, "long.net_pnl")[mask]
    b = _numbers(frame.table, "long.cagr")[mask]
    defined = np.isfinite(a) & np.isfinite(b)
    numbers = _trial_numbers(frame.table)[mask][defined]
    out = pareto_view(frame, flt, objectives=["net_pnl", "cagr"], scope="long")
    expected = numbers[brute_front(a[defined], b[defined])]
    assert sorted(out["front"]) == sorted(ids(frame, expected))
    assert out["front_size"] == len(expected)
    assert out["excluded"] == int((~defined).sum()) > 0
    assert out["front_size"] + out["dominated"] + out["excluded"] == int(mask.sum())
    assert sum(map(sum, out["density"]["counts"])) == out["dominated"]
    strict(out)
    indexed = pareto_view(
        frame, flt, objectives=["net_pnl", "cagr"], scope="long", index=build_index(frame)
    )
    assert indexed == out


def test_an_undefined_objective_is_excluded_and_counted():
    nan = float("nan")
    frame = trials(net_pnl=[9.0, nan, 1.0, 2.0, 5.0], max_drawdown=[1.0, 0.0, nan, 3.0, 2.0])
    out = pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert out["front"] == ids(frame, [0])  # trial 1 would win on drawdown if a NaN were ranked
    assert (out["front_size"], out["dominated"], out["excluded"]) == (1, 2, 2)
    every = trials(net_pnl=[nan, nan], max_drawdown=[1.0, 2.0])
    none = pareto_view(every, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert none["front"] == [] and none["points"] == [] and none["excluded"] == 2
    assert none["empty"] == "no trial has every objective defined (2 excluded)"
    assert none["density"]["x"] is None and none["density"]["y"] is None
    strict(none)


def test_the_density_holds_the_dominated_cloud_over_every_defined_trial():
    """64 x 64, `counts[y][x]`, over the range of every defined trial so the front shares its frame;
    the front is not in it, the range's top edge is (nothing is dropped), and numpy agrees."""
    rng = np.random.default_rng(4)
    x, y = rng.normal(0.0, 5.0, 3_000), rng.normal(0.0, 5.0, 3_000)
    frame = trials(net_pnl=x, win_rate=y)
    out = pareto_view(frame, LabFilter(), objectives=["net_pnl", "win_rate"], scope=COMBINED)
    density = out["density"]
    assert density["bins"] == policy.PARETO_DENSITY_BINS == 64
    assert len(density["counts"]) == 64 and all(len(row) == 64 for row in density["counts"])
    assert density["x"] == [float(x.min()), float(x.max())]
    assert density["y"] == [float(y.min()), float(y.max())]
    assert density["axes"] == ["net_pnl", "win_rate"]
    assert density["basis"] == f"Aggregated from tested (n = {out['dominated']})"
    cloud = np.ones(3_000, dtype=bool)
    cloud[front_2d(x, y)] = False
    numpy_counts, _, _ = np.histogram2d(
        x[cloud], y[cloud], bins=64, range=[density["x"], density["y"]]
    )
    assert np.array_equal(np.array(density["counts"]), numpy_counts.T.astype(np.int64))
    assert sum(map(sum, density["counts"])) == out["dominated"]


def test_the_density_loses_nothing_at_its_edges_or_on_a_flat_axis():
    """The cloud's top edge lands in the last bin, a flat axis is widened as numpy widens it, and
    the third objective of three never shrinks what the two drawn axes count."""
    frame = trials(net_pnl=[0.0, 64.0, 32.0, 64.0], win_rate=[0.0, 0.0, 0.0, 1.0])
    out = pareto_view(frame, LabFilter(), objectives=["net_pnl", "win_rate"], scope=COMBINED)
    assert out["front"] == ids(frame, [3]) and out["dominated"] == 3
    counts = np.array(out["density"]["counts"])
    assert counts[0, 0] == 1 and counts[0, 32] == 1 and counts[0, 63] == 1  # 64.0 is in, at 63
    flat = trials(net_pnl=[5.0, 5.0, 5.0], win_rate=[1.0, 2.0, 3.0])
    held = pareto_view(flat, LabFilter(), objectives=["net_pnl", "win_rate"], scope=COMBINED)
    assert held["density"]["x"] == [4.5, 5.5] and held["dominated"] == 2
    assert sum(map(sum, held["density"]["counts"])) == 2
    alone = trials(net_pnl=[5.0], win_rate=[1.0])
    single = pareto_view(alone, LabFilter(), objectives=["net_pnl", "win_rate"], scope=COMBINED)
    assert single["front_size"] == 1 and sum(map(sum, single["density"]["counts"])) == 0
    rng = np.random.default_rng(5)
    a, b, c = rng.normal(size=(3, 2_000))
    three = trials(net_pnl=a, win_rate=b, expectancy=c)
    wide = pareto_view(
        three, LabFilter(), objectives=["net_pnl", "win_rate", "expectancy"], scope=COMBINED
    )
    assert sorted(wide["front"]) == sorted(ids(three, brute_front(a, b, c)))
    assert sum(map(sum, wide["density"]["counts"])) == wide["dominated"]
    assert all(len(point["values"]) == 3 for point in wide["points"])
    assert wide["density"]["axes"] == ["net_pnl", "win_rate"]


@pytest.mark.parametrize(
    "objectives",
    [
        ["net_pnl"],
        [],
        ["net_pnl", "cagr", "mar", "exposure"],
        ["net_pnl", "net_pnl"],
        ["nope", "mar"],
    ],
)
def test_objectives_must_be_two_or_three_known_metrics(objectives):
    frame = trials(net_pnl=[1.0, 2.0])
    with pytest.raises(ValueError):
        pareto_view(frame, LabFilter(), objectives=objectives, scope=COMBINED)
    request = api.QueryRequest.model_validate(
        {"filter": {}, "view": "pareto", "objectives": objectives}
    )
    with pytest.raises(ValueError):
        sources.COLUMNS_FOR("pareto", request, frame.parameters, frame.objective)


def test_pareto_needs_objectives_and_reads_only_block_zero():
    frame = stat_frame(d=2, values=8, n=300, seed=2, y=first_order, blocks={1: zero})
    request = api.QueryRequest.model_validate({"filter": {}, "view": "pareto"})
    with pytest.raises(ValueError, match="needs objectives"):
        sources.COLUMNS_FOR("pareto", request, frame.parameters, frame.objective)
    out = pareto_view(frame, LabFilter(), objectives=PNL_DD, scope=COMBINED)
    assert out["front_size"] + out["dominated"] + out["excluded"] == 300


# --- the exact parallel sample ------------------------------------------------------------------


def test_sample_view_is_stratified_and_seeded():
    """5,000 of 30,000, 500 from each decile of the metric, the same lines for the same seed and
    others for another; each line carries its axes' values, the metric and the trial id."""
    assert policy.PARALLEL_MAX_LINES == 5_000 and policy.PARALLEL_STRATA == 10
    n = 30_000
    pnl = np.random.default_rng(6).normal(0.0, 10.0, n)
    frame = trials(net_pnl=pnl)
    axes = [p.path for p in frame.parameters]
    out = sample_view(frame, LabFilter(), axes=axes, metric="net_pnl", seed=5)
    assert len(out["lines"]) == 5_000 and out["sampled_from"] == n and out["strata"] == 10
    assert out["basis"] == "Sampled 5000 of 30000 (stratified by decile of net_pnl)"
    assert out["seed"] == 5 and out["axes"] == axes and out["excluded"] == 0
    assert out["metric"] == "combined.net_pnl"
    assert out["bundles"] == [] and out["bins"] == []  # no bundle was computed in this mode
    numbers = [int(line["trial_id"].split("#")[1]) for line in out["lines"]]
    assert numbers == sorted(set(numbers))
    rank = np.empty(n, dtype=np.int64)
    rank[np.argsort(pnl, kind="stable")] = np.arange(n)
    decile = rank * 10 // n
    assert np.bincount(decile[numbers], minlength=10).tolist() == [500] * 10
    columns = {path: _numbers(frame.table, path) for path in axes}
    for line, trial in list(zip(out["lines"], numbers, strict=True))[:50]:
        assert line["trial_id"] == f"{frame.source}#{trial}"
        assert line["metric"] == float(pnl[trial])
        assert line["values"] == [float(columns[path][trial]) for path in axes]
    assert out == sample_view(frame, LabFilter(), axes=axes, metric="net_pnl", seed=5)
    other = sample_view(frame, LabFilter(), axes=axes, metric="net_pnl", seed=6)
    assert other["lines"] != out["lines"]
    assert (
        np.bincount(
            decile[[int(line["trial_id"].split("#")[1]) for line in other["lines"]]], minlength=10
        ).tolist()
        == [500] * 10
    )
    strict(out)


def test_sample_view_reads_the_filter_and_leaves_the_undefined_out():
    """Only the filter's completed trials with a defined metric: the rest are `excluded`, counted,
    never stratified as if they were a value."""
    frame = synthetic_frame(9_000, 4, 12)
    path = frame.parameters[1].path
    values = frame.parameters[1].values
    flt = LabFilter(ranges={path: (values[0], values[2])})
    mask = filter_mask(frame, flt)
    metric = _numbers(frame.table, "combined.cagr")[mask]
    defined = np.isfinite(metric)
    out = sample_view(frame, flt, axes=[path], metric="cagr", seed=1)
    assert out["sampled_from"] == int(defined.sum())
    assert out["excluded"] == int((~defined).sum()) > 0
    allowed = set(ids(frame, _trial_numbers(frame.table)[mask][defined]))
    assert {line["trial_id"] for line in out["lines"]} <= allowed
    held = _numbers(frame.table, path)
    numbers = _trial_numbers(frame.table)
    at = {int(trial): row for row, trial in enumerate(numbers.tolist())}
    for line in out["lines"]:
        value = held[at[int(line["trial_id"].split("#")[1])]]
        assert values[0] <= value <= values[2] and line["values"] == [float(value)]
    assert out["basis"] == (
        f"Sampled {len(out['lines'])} of {out['sampled_from']} (stratified by decile of cagr)"
    )
    strict(out)


def test_sample_view_keeps_every_line_of_a_small_population():
    frame = trials(net_pnl=[3.0, 1.0, 2.0, float("nan")])
    out = sample_view(frame, LabFilter(), axes=[frame.parameters[0].path], metric="net_pnl", seed=1)
    assert [line["trial_id"] for line in out["lines"]] == ids(frame, [0, 1, 2])
    assert out["sampled_from"] == 3 and out["excluded"] == 1
    assert out["basis"] == "Sampled 3 of 3 (stratified by decile of net_pnl)"
    path = frame.parameters[0].path
    nothing = sample_view(
        frame, LabFilter(values={path: -1.0}), axes=[path], metric="net_pnl", seed=1
    )
    assert nothing["lines"] == [] and nothing["sampled_from"] == 0
    assert nothing["basis"] == "Sampled 0 of 0 (stratified by decile of net_pnl)"


@pytest.mark.parametrize(("n", "k"), [(14, 13), (11, 10), (25, 3), (1_000, 7), (101, 100)])
def test_sample_view_strata_stay_even_at_any_k(n, k):
    """Whatever the numbers, `k` lines come back, and two strata differ by at most one line."""
    frame = trials(net_pnl=np.arange(n, dtype=np.float64))
    out = sample_view(
        frame, LabFilter(), axes=[frame.parameters[0].path], metric="net_pnl", k=k, seed=2
    )
    assert len(out["lines"]) == k
    numbers = [int(line["trial_id"].split("#")[1]) for line in out["lines"]]
    per = np.bincount(np.array(numbers) * 10 // n, minlength=10)
    assert per.sum() == k and per.max() - per.min() <= 1


def test_sample_view_strata_are_even_under_ties():
    """A metric of few values: the deciles are by rank, ties by trial number, so a value holding
    most trials cannot leave a stratum empty and swell another."""
    n = 10_000
    pnl = np.zeros(n)
    pnl[:500] = -1.0
    pnl[-500:] = 1.0
    frame = trials(net_pnl=pnl)
    out = sample_view(
        frame, LabFilter(), axes=[frame.parameters[0].path], metric="net_pnl", k=1_000, seed=3
    )
    numbers = np.array([int(line["trial_id"].split("#")[1]) for line in out["lines"]])
    assert np.bincount(numbers * 10 // n, minlength=10).tolist() == [100] * 10


@pytest.mark.parametrize(
    "arguments",
    [
        {"axes": []},
        {"axes": ["nope"]},
        {"axes": [paths_of(2)[0], paths_of(2)[0]]},
        {"k": 0},
        {"k": policy.PARALLEL_MAX_LINES + 1},
        {"metric": "nope"},
    ],
)
def test_sample_view_refuses(arguments):
    frame = trials(net_pnl=[1.0, 2.0])
    held = {"axes": [paths_of(2)[0]], "metric": "net_pnl", "k": 1, **arguments}
    with pytest.raises(ValueError):
        sample_view(frame, LabFilter(), seed=1, **held)


# --- convergence: best-so-far -------------------------------------------------------------------


def test_convergence_is_best_so_far_and_labelled_provisional_while_running():
    """Best-so-far by trial number, an undefined value skipped and never ranked; the same series
    minimizing max_drawdown, in its own units; `provisional` while the source runs."""
    nan = float("nan")
    frame = trials(
        net_pnl=[3.0, 1.0, 5.0, nan, 4.0, 9.0, 2.0],
        max_drawdown=[7.0, 8.0, 6.0, 2.0, nan, 4.0, 5.0],
    )
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert out["best"] == [[0, 3.0], [1, 3.0], [2, 5.0], [4, 5.0], [5, 9.0], [6, 9.0]]
    assert out["provisional"] is False and out["orientation"] == 1
    assert out["metric"] == "combined.net_pnl"
    low = convergence_view(frame, LabFilter(), metric="max_drawdown", scope=COMBINED)
    assert low["best"] == [[0, 7.0], [1, 7.0], [2, 6.0], [3, 2.0], [5, 2.0], [6, 2.0]]
    assert low["orientation"] == -1
    running = replace(frame, provisional=True)
    held = convergence_view(running, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert held["provisional"] is True and held["best"] == out["best"]
    assert answer(running, view="convergence")["provisional"] is True
    assert answer(frame, view="convergence")["provisional"] is False
    strict(out)


def test_convergence_reads_the_filter_in_trial_order():
    """Decision 7: best-so-far of the filtered completed trials, gaps in the numbers included,
    whatever order the rows arrive in."""
    frame = synthetic_frame(3_000, 3, 13)
    path = frame.parameters[0].path
    flt = LabFilter(values={path: frame.parameters[0].values[1]})
    mask = filter_mask(frame, flt)
    pnl = _numbers(frame.table, "combined.net_pnl")[mask]
    numbers = _trial_numbers(frame.table)[mask]
    out = convergence_view(frame, flt, metric="net_pnl", scope=COMBINED)
    assert out["best"] == [
        [int(trial), float(value)]
        for trial, value in zip(numbers, np.maximum.accumulate(pnl), strict=True)
    ]
    shuffled = frame.table.take(pa.array(np.random.default_rng(1).permutation(3_000)))
    again = convergence_view(replace(frame, table=shuffled), flt, metric="net_pnl", scope=COMBINED)
    assert again["best"] == out["best"]


@pytest.mark.parametrize(
    ("n", "points"), [(999, 999), (1_000, 1_000), (1_001, 1_000), (12_345, 1_000)]
)
def test_best_is_thinned_evenly_and_keeps_the_last_point(n, points):
    pnl = np.random.default_rng(n).normal(0.0, 10.0, n)
    frame = trials(net_pnl=pnl)
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    best = out["best"]
    running = np.maximum.accumulate(pnl)
    assert len(best) == points <= policy.CONVERGENCE_MAX_POINTS == 1_000
    assert best[0] == [0, float(pnl[0])]
    assert best[-1] == [n - 1, float(pnl.max())]
    assert all(value == running[trial] for trial, value in best)
    at = [trial for trial, _ in best]
    gaps = np.diff(at)
    assert gaps.min() >= 1 and gaps.max() - gaps.min() <= 1
    assert out["best_total"] == n
    if n > 1_000:
        assert out["basis"] == (
            f"Tested (exact); {NEIGHBOURS}; best-so-far thinned evenly to 1000 of {n} points"
        )
    else:
        assert out["basis"] == f"Tested (exact); {NEIGHBOURS}"


def test_even_positions():
    assert even_positions(0, 5).tolist() == [] and even_positions(3, 5).tolist() == [0, 1, 2]
    assert even_positions(5, 5).tolist() == [0, 1, 2, 3, 4]
    assert even_positions(11, 3).tolist() == [0, 5, 10]
    for total in (6, 7, 1_001, 99_999):
        held = even_positions(total, 5).tolist()
        assert held[0] == 0 and held[-1] == total - 1 and len(set(held)) == 5


# --- convergence: the robust series -------------------------------------------------------------


def _expected_robust(frame, flt, metric, *, batch=5_000, top=50) -> list[dict]:
    """§7.10 by the definition, one `neighbourhood` at a time: per complete batch of defined
    trials, the median and quartiles of the neighbourhood P25 of its top 1 %, in the metric's own
    units."""
    index = build_index(frame)
    sign = -1.0 if metric == "max_drawdown" else 1.0
    column = _numbers(frame.table, f"{flt.scope}.{metric}")
    mask = filter_mask(frame, flt) & np.isfinite(column)
    rows = np.flatnonzero(mask)
    numbers = _trial_numbers(frame.table)
    rows = rows[np.argsort(numbers[rows], kind="stable")]
    out = []
    for b in range(len(rows) // batch):
        members = rows[b * batch : (b + 1) * batch]
        leaders = members[np.argsort(-(sign * column[members]), kind="stable")][:top]
        found = [
            neighbourhood(frame, int(numbers[row]), metric=metric, scope=flt.scope, index=index).p25
            for row in leaders.tolist()
        ]
        held = np.array([p for p in found if p is not None], dtype=np.float64)
        entry = {
            "batch": b,
            "trial_no": int(numbers[members[-1]]),
            "top": top,
            "measured": len(held),
        }
        if len(held):
            median, low, high = np.median(held), *np.percentile(held, [25, 75])
            if sign < 0:
                median, low, high = -median, -high, -low
            entry.update(median=float(median), p25=float(low), p75=float(high))
        else:
            entry.update(median=None, p25=None, p75=None)
        out.append(entry)
    return out


def test_robust_is_the_median_of_the_top_trials_neighbourhood_p25():
    """Two complete batches and 2,000 trials over: the over is in no batch, never extrapolated."""
    assert policy.CONVERGENCE_BATCH == 5_000 and policy.CONVERGENCE_TOP == 0.01
    frame = stat_frame(d=4, values=8, n=12_000, seed=14, y=first_order)
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert out["robust"] == _expected_robust(frame, LabFilter(), "net_pnl")
    assert [entry["batch"] for entry in out["robust"]] == [0, 1]
    assert out["batches"] == 2 and out["partial"] == 2_000 and out["robust_reason"] is None
    assert out["robust"][-1]["trial_no"] == 9_999
    assert all(e["p25"] <= e["median"] <= e["p75"] for e in out["robust"])
    assert out["m"] == policy.NEIGHBOUR_M_GRID and out["r"] == policy.NEIGHBOUR_R  # 8⁴ < n
    sampled = stat_frame(d=12, values=8, n=10_000, seed=14, y=first_order)
    wide = convergence_view(sampled, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert wide["m"] == policy.NEIGHBOUR_M_SAMPLED
    assert wide["robust"] == _expected_robust(sampled, LabFilter(), "net_pnl")
    assert out["constants"] == {
        "CONVERGENCE_BATCH": 5_000,
        "CONVERGENCE_TOP": 0.01,
        "CONVERGENCE_MAX_POINTS": 1_000,
        "NEIGHBOUR_R": policy.NEIGHBOUR_R,
    }
    strict(out)


def test_robust_of_a_minimized_metric_stays_in_its_own_units():
    frame = stat_frame(d=3, values=8, n=10_000, seed=15, y=first_order)
    out = convergence_view(frame, LabFilter(), metric="max_drawdown", scope=COMBINED)
    assert out["robust"] == _expected_robust(frame, LabFilter(), "max_drawdown")
    assert all(e["p25"] <= e["median"] <= e["p75"] for e in out["robust"])
    assert len(out["robust"]) == 2


def test_the_filter_selects_the_top_trials_and_neighbours_read_the_whole_snapshot():
    """A brush must not make real neighbours look untested: the filter picks each batch's top
    trials, and their neighbourhoods read every completed block-0 trial. The basis says so."""
    frame = stat_frame(d=3, values=8, n=100_000, seed=16, y=first_order)
    path = frame.parameters[1].path
    brush = LabFilter(values={path: 4.0})
    held = convergence_view(frame, brush, metric="net_pnl", scope=COMBINED)
    assert held["batches"] == 2 and held["robust"] == _expected_robust(frame, brush, "net_pnl")
    assert held["basis"].startswith(f"Tested (exact); {NEIGHBOURS}")
    # the top trial of the first batch has tested neighbours the brush left out, and they count
    first = np.flatnonzero(filter_mask(frame, brush))[:5_000]
    pnl = _numbers(frame.table, "combined.net_pnl")
    whole = neighbourhood(frame, int(first[np.argmax(pnl[first])]))  # a trial number is its row
    values = _numbers(frame.table, path)
    assert any(values[trial] != 4.0 for trial in whole.trials)
    # the same narrow brush on a tenth of the trials holds under two batches: no robust series
    fewer = stat_frame(d=3, values=8, n=10_000, seed=16, y=first_order)
    assert convergence_view(fewer, brush, metric="net_pnl", scope=COMBINED)["robust"] == []


def test_the_views_read_the_scope_they_are_given():
    """The scope picks the metric column and drops no row, in all three views: only the short
    side's columns differ here, so a view reading any other shows it."""
    n = 10_000
    frame = stat_frame(d=3, values=8, n=n, seed=22, y=first_order)
    rng = np.random.default_rng(22)
    table = frame.table
    for name in ("net_pnl", "win_rate"):
        column = f"short.{name}"
        table = table.set_column(
            table.schema.get_field_index(column), column, pa.array(rng.normal(0.0, 9.0, n))
        )
    frame = replace(frame, table=table)
    short = LabFilter(scope="short")
    pnl = _numbers(table, "short.net_pnl")
    rate = _numbers(table, "short.win_rate")
    path = frame.parameters[0].path
    lines = sample_view(frame, short, axes=[path], metric="net_pnl", k=50, seed=1)
    assert lines["metric"] == "short.net_pnl"
    for line in lines["lines"]:
        assert line["metric"] == float(pnl[int(line["trial_id"].split("#")[1])])
    front = pareto_view(frame, short, objectives=["net_pnl", "win_rate"], scope="short")
    assert sorted(front["front"]) == sorted(ids(frame, brute_front(pnl, rate)))
    trend = convergence_view(frame, short, metric="net_pnl", scope="short")
    assert trend["metric"] == "short.net_pnl"
    assert trend["best"][-1] == [n - 1, float(pnl.max())]
    assert trend["robust"] == _expected_robust(frame, short, "net_pnl")
    combined = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert trend["robust"] != combined["robust"]


@pytest.mark.parametrize(
    ("n", "batches"), [(0, 0), (4_999, 0), (5_000, 1), (9_999, 1), (10_000, 2)]
)
def test_robust_is_empty_below_two_batches_and_best_is_not(n, batches):
    """§7.10 puts no floor on best-so-far; §5's `< 2 batches: empty` is the robust series'. A reason
    says why it is empty, and nothing is built for it."""
    frame = stat_frame(d=2, values=8, n=n, seed=17, y=zero)
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert out["batches"] == batches and len(out["best"]) == min(n, 1_000)
    assert out["partial"] == n - batches * 5_000
    if batches < 2:
        assert out["robust"] == []
        assert out["robust_reason"] == (
            f"fewer than 2 complete batches of 5000 trials with a defined net_pnl ({n} so far)"
        )
    else:
        assert len(out["robust"]) == 2 and out["robust_reason"] is None


def test_a_short_run_builds_no_neighbourhood(monkeypatch):
    frame = stat_frame(d=2, values=8, n=100, seed=17, y=zero)

    def refuse(*args, **kwargs):
        raise AssertionError("a run of under two batches read neighbourhoods")

    monkeypatch.setattr(convergence_module, "PositionLookup", refuse)
    assert convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)["robust"] == []


def test_batches_count_defined_trials_and_a_batch_without_neighbours_holds_no_value(monkeypatch):
    """Undefined trials sit in no batch and take no top place. A batch whose top trials have no
    tested neighbour holds no value, rather than a zero, and says how many it measured."""
    monkeypatch.setattr(convergence_module, "CONVERGENCE_BATCH", 2)
    sizes = [9, 9]
    only = {(0, 0), (4, 4), (8, 8), (0, 8), (8, 0)}
    frame = lattice_frame(lambda p: float(p[0] + p[1]) if p != (4, 4) else None, sizes, only=only)
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert out["batches"] == 2 and out["partial"] == 0
    assert out["robust"] == [
        {"batch": 0, "trial_no": trial_at(frame, (0, 8)), "top": 1, "measured": 0}
        | {"median": None, "p25": None, "p75": None},
        {"batch": 1, "trial_no": trial_at(frame, (8, 8)), "top": 1, "measured": 0}
        | {"median": None, "p25": None, "p75": None},
    ]
    strict(out)


def test_robust_is_thinned_evenly_past_the_bound(monkeypatch):
    """§9.3's ≤ 1,000 points also holds the robust series past 5,000,000 trials: evenly, keeping
    the last complete batch."""
    monkeypatch.setattr(convergence_module, "CONVERGENCE_BATCH", 10)
    monkeypatch.setattr(convergence_module, "CONVERGENCE_MAX_POINTS", 5)
    frame = stat_frame(d=3, values=4, n=205, seed=18, y=first_order)
    out = convergence_view(frame, LabFilter(), metric="net_pnl", scope=COMBINED)
    assert out["batches"] == 20 and out["partial"] == 5
    assert [entry["batch"] for entry in out["robust"]] == [0, 5, 10, 14, 19]
    assert len(out["best"]) == 5 and out["best"][-1][0] == 204
    every = _expected_robust(frame, LabFilter(), "net_pnl", batch=10, top=1)
    assert out["robust"] == [every[b] for b in (0, 5, 10, 14, 19)]


# --- the batched lookup -------------------------------------------------------------------------


def _same_p25s(frame, rows, *, r=1, m=None, index=None, metric="net_pnl") -> None:
    lookup = PositionLookup(frame, metric=metric, index=index)
    batched = lookup.p25_around(np.asarray(rows, dtype=np.int64), r=r, m=m)
    single = [lookup.around(int(row), r=r, m=m).p25 for row in rows]
    assert len(batched) == len(rows)
    for one, held in zip(single, batched.tolist(), strict=True):
        assert (one is None and np.isnan(held)) or one == held


@pytest.mark.parametrize(("r", "m"), [(1, 1), (1, 2), (2, 1), (2, 2), (1, 3)])
def test_the_batched_p25_equals_one_neighbourhood_at_a_time(r, m):
    frame = stat_frame(d=4, values=6, n=1_500, seed=19, y=first_order)
    _same_p25s(frame, range(0, 1_500, 40), r=r, m=m)


def test_the_batched_p25_equals_one_at_a_time_on_a_rough_surface():
    """A corner, an undefined metric, refused and failed rows, a repeated configuration and a
    sparse surface: the same arithmetic reads them all."""
    frame = stat_frame(
        d=3, values=5, n=1_500, seed=20, y=first_order, undefined=lambda u: u[:, 0] > 0.7
    )
    _same_p25s(frame, range(0, 1_500, 25), metric="cagr", m=2)
    statuses = np.array(["ok", "invalid", "failed"])[np.random.default_rng(1).integers(0, 3, 1_500)]
    table = frame.table.set_column(
        frame.table.schema.get_field_index("status"),
        "status",
        pa.array(statuses.tolist(), frame.table.schema.field("status").type),
    )
    rough = replace(frame, table=table)
    rows = np.flatnonzero(statuses == "ok")[:40]
    _same_p25s(rough, rows, m=2)
    sparse = stat_frame(d=9, values=8, n=2_000, seed=21, y=first_order)
    _same_p25s(sparse, range(0, 2_000, 50), m=2)
    grid = lattice_frame(lambda p: float(p[0] * 10 + p[1]), [5, 5])
    _same_p25s(grid, range(25))
    assert np.isnan(PositionLookup(sparse).p25_around(np.array([], dtype=np.int64))).all()


def test_the_batched_p25_survives_a_hash_collision_and_a_value_off_the_lattice(monkeypatch):
    frame = stat_frame(d=3, values=5, n=120, seed=9, y=first_order)
    honest = PositionLookup(frame).p25_around(np.arange(40), m=2)
    monkeypatch.setattr(neighbours_module, "_multipliers", lambda d: np.zeros(d, dtype=np.int64))
    collided = PositionLookup(frame).p25_around(np.arange(40), m=2)
    assert np.array_equal(honest, collided, equal_nan=True)
    monkeypatch.undo()
    grid = lattice_frame(lambda p: float(p[0] * 10 + p[1]), [3, 3])
    path = paths_of(2)[0]
    edited = [
        replace(p, values=[1.0, 2.0], stop=2.0) if p.path == path else p for p in grid.parameters
    ]
    _same_p25s(replace(grid, parameters=edited), range(9))


@pytest.mark.parametrize(("r", "m"), [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_the_batched_p25_equals_a_pairwise_scan(r, m):
    """Against the definition, row by row, and not against `around`, which shares its arithmetic:
    within `r` steps in 1 to `m` parameters, one row per position, its first."""
    frame = stat_frame(d=3, values=5, n=400, seed=23, y=first_order)
    positions = np.stack(
        [frame.table.column(f"pos.{k}").to_numpy().astype(np.int64) for k in range(3)], axis=1
    )
    values = _numbers(frame.table, "combined.net_pnl")
    rows = np.arange(0, 400, 9)
    held = PositionLookup(frame).p25_around(rows, r=r, m=m)
    for row, found in zip(rows.tolist(), held.tolist(), strict=True):
        steps = np.abs(positions - positions[row])
        moved = (steps > 0).sum(axis=1)
        near = (steps.max(axis=1) <= r) & (moved >= 1) & (moved <= m)
        seen: dict[tuple, int] = {}
        for other in np.flatnonzero(near).tolist():
            seen.setdefault(tuple(positions[other].tolist()), other)
        if seen:
            assert found == float(np.percentile(values[sorted(seen.values())], 25))
        else:
            assert np.isnan(found)


def test_the_batched_p25_stays_on_the_lattice():
    """A surface edited after its trials ran: both parameters' third value left the lattice, so
    rows sit just past its top. A candidate never steps onto them, a move with one step past the top
    is closed whatever its other step, and a value off the lattice takes no step along its axis."""
    grid = lattice_frame(lambda p: float(p[0] * 10 + p[1]), [3, 3])
    edited = [replace(p, values=[1.0, 2.0], stop=2.0) for p in grid.parameters]
    moved = replace(grid, parameters=edited)
    top, off = trial_at(grid, (1, 1)), trial_at(grid, (2, 1))
    single = PositionLookup(moved).p25_around(np.array([top, off]), m=1)
    # (1, 1) reads (0, 1) and (1, 0); (2, 1), off the first lattice, reads (2, 0) alone
    assert single.tolist() == [float(np.percentile([1.0, 10.0], 25)), 20.0]
    pairs = PositionLookup(moved).p25_around(np.array([top]), m=2)
    assert pairs.tolist() == [float(np.percentile([0.0, 1.0, 10.0], 25))]  # never (0, 2) or (2, 0)


def test_the_batched_p25_is_one_searchsorted_over_every_candidate(monkeypatch):
    """Convergence's cost: every candidate's needles in one pass, and only the rows hit read."""
    frame = stat_frame(d=20, values=8, n=2_000, seed=5, y=zero)
    index = build_index(frame)
    lookup = PositionLookup(frame, index=index)
    calls: list[int] = []
    real = np.searchsorted

    def counting(a, v, *args, **kwargs):
        calls.append(int(np.size(v)))
        return real(a, v, *args, **kwargs)

    monkeypatch.setattr(np, "searchsorted", counting)
    held = lookup.p25_around(np.arange(50), m=2)
    assert len(calls) == 1 and len(held) == 50
    assert calls[0] <= 50 * 800
