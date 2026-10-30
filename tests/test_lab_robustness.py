"""Optimization Lab v2, Phase 3 Task 7: neighbourhoods by hashed positions, the four robustness
categories, the candidate card and the two rankings (spec §7.6, §20's robustness list; decision
12; Rulings P15 and P16)."""

from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pyarrow as pa
import pytest
from lab_stat_fixtures import (
    CROWDED_BEST_INTERIOR,
    CROWDED_SPIKES,
    D_WIDE,
    PLATEAU_BEST_INTERIOR,
    PLATEAU_EDGE,
    SPIKE_AT,
    SPIKE_SIZES,
    VALUES,
    crowded_plateau,
    first_order,
    frame_of,
    lattice_frame,
    paths_of,
    spike_and_plateau,
    stat_frame,
    trial_at,
    zero,
)
from products.aegis import analysis
from products.aegis import experiments as exp
from products.aegis.lab import neighbours as neighbours_module
from products.aegis.lab import policy, sources
from products.aegis.lab import robustness as robustness_module
from products.aegis.lab import store as lab_store
from products.aegis.lab.cache import LabCache
from products.aegis.lab.index import build_index
from products.aegis.lab.neighbours import (
    Neighbourhood,
    neighbourhood,
    position_codes,
    position_table,
)
from products.aegis.lab.query import ALL_BLOCKS, METRIC_NAMES, LabFilter
from products.aegis.lab.robustness import (
    BlockEvidence,
    Category,
    FoldEvidence,
    ReplayEvidence,
    _stable_of,
    candidate_card,
    category_a,
    category_b,
    category_c,
    category_d,
    constants,
    rankings,
    rankings_basis,
    robust_key,
    tau,
    top_axes,
)
from test_aegis_experiments import world  # noqa: F401 - the shared experiments fixture
from test_lab_store import PATHS, hand_document, rows_of

pytestmark = pytest.mark.aegis

METRIC = "net_pnl"
SCOPE = "combined"
TOLERANCE = 0.15
SELECTION_ONLY = "unresolved · selection-period only"
NO_REPLAY = "no replay yet (stage 2)"
NO_IMPORTANCE = "importance not computed for this snapshot"
NO_SPREAD = "no spread in the metric (τ = 0)"
SUMMED = {"score", "total", "overall", "weighted", "sum", "rating"}


def hood(values: list[float], *, valid: int | None = None, tested: int | None = None):
    """A neighbourhood as `neighbourhood` reports it, its quartiles over `values`."""
    tested = len(values) if tested is None else tested
    valid = tested if valid is None else valid
    p25, p75 = (None, None) if not values else [float(v) for v in np.percentile(values, [25, 75])]
    return Neighbourhood(
        trial_no=0,
        probes=valid,
        valid=valid,
        tested=tested,
        coverage=tested / valid if valid else 0.0,
        trials=list(range(1, len(values) + 1)),
        values=list(values),
        p25=p25,
        p75=p75,
        iqr=None if p25 is None else p75 - p25,
        r=1,
        m=1,
        undefined=0,
        orientation=1,
    )


def card_of(frame, position_or_trial, axes=(), **kw) -> dict:
    trial = (
        trial_at(frame, position_or_trial)
        if isinstance(position_or_trial, tuple)
        else position_or_trial
    )
    return candidate_card(
        frame, trial, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, axes=list(axes), **kw
    )


def strict(payload) -> str:
    """Strict JSON: a NaN, a numpy scalar or a MappingProxyType is an error here."""
    return json.dumps(payload, allow_nan=False)


# --- §20: category A ---------------------------------------------------------------------------


def test_unresolved_when_untested():
    """2 of 10 tested on an exhaustive grid still running: the reason prints the coverage, and a
    trial far above the two it has is neither a peak nor stable."""
    centre = (1, 1, 1, 1, 1)
    first, second = (0, 1, 1, 1, 1), (2, 1, 1, 1, 1)
    frame = lattice_frame(
        lambda p: 100.0 if p == centre else 1.0,
        [3] * 5,
        only={centre, first, second, (0, 0, 0, 0, 0)},
    )
    a = Category(**card_of(frame, centre)["categories"]["A"])
    assert a.resolved is False and a.classification is None
    assert a.reason == "untested surroundings (coverage 0.2 of 0.5)"
    assert a.inputs["coverage"] == pytest.approx(0.2)
    assert a.inputs["valid"] == 10 and a.inputs["n"] == 2
    assert a.inputs["min_coverage"] == 0.5 and a.inputs["required_n"] == 10


def test_fully_tested_corner_resolves():
    """§7.6's `min(2d + 1, |valid|)`: a grid corner has d neighbours, every one tested."""
    for d in (2, 3):
        corner = (0,) * d
        frame = lattice_frame(lambda p: 50.0, [3] * d)
        found = neighbourhood(frame, trial_at(frame, corner))
        assert found.m == policy.NEIGHBOUR_M_GRID
        assert (found.valid, found.tested, found.coverage) == (d, d, 1.0)
        a = category_a(found, 50.0, 1.0, d)
        assert a.resolved and a.classification == "stable local"
        assert a.inputs["required_n"] == d


def test_a_corner_with_a_neighbour_untested_stays_unresolved():
    """Coverage is enough, but the n rule asks for every neighbour of a grid corner."""
    corner, right = (0, 0), (1, 0)
    frame = lattice_frame(lambda p: 50.0, [3, 3], only={corner, right, (2, 2)})
    a = Category(**card_of(frame, corner)["categories"]["A"])
    assert a.resolved is False
    assert a.reason == "untested surroundings (n 1 of 2)"
    assert a.inputs["n"] == 1 and a.inputs["required_n"] == 2


def test_a_names_what_falls_short():
    """Ruling P17: coverage passes and n falls short, so the reason says n, with the data's
    numbers; a coverage shortfall keeps its own form, also when n is short too."""
    short_n = category_a(hood([1.0] * 7, valid=8), 1.0, 1.0, 20)
    assert short_n.inputs["coverage"] == 0.875 and short_n.inputs["required_n"] == 8
    assert short_n.reason == "untested surroundings (n 7 of 8)"
    short_both = category_a(hood([1.0] * 3, valid=8), 1.0, 1.0, 20)
    assert short_both.reason == "untested surroundings (coverage 0.37 of 0.5)"


def test_isolated_peak_vs_stable_local():
    frame = spike_and_plateau()
    states = {
        position: card_of(frame, position)["categories"]["A"]
        for position in (SPIKE_AT, PLATEAU_BEST_INTERIOR, PLATEAU_EDGE)
    }
    assert states[SPIKE_AT]["classification"] == "isolated peak"
    assert states[PLATEAU_BEST_INTERIOR]["classification"] == "stable local"
    assert states[PLATEAU_EDGE]["classification"] == "mixed"
    for state in states.values():
        assert state["resolved"] is True and state["reason"] is None
        assert state["inputs"]["coverage"] == 1.0 and state["inputs"]["n"] == 4


def test_stable_local_wins_over_a_sliver_above_flat_neighbours():
    """The table's first match: within τ of P25 is stable, however thin the IQR is."""
    a = category_a(hood([10.0, 10.0, 10.0, 10.0]), 10.5, 1.0, 2)
    assert a.classification == "stable local"


def test_within_tau_is_two_sided_and_inclusive():
    """§7.6 says within τ of t's value: a trial far below its neighbours is not stable."""
    assert category_a(hood([10.0] * 4), 9.0, 1.0, 2).classification == "stable local"
    assert category_a(hood([10.0] * 4), 11.0, 1.0, 2).classification == "stable local"
    assert category_a(hood([10.0] * 4), 8.9, 1.0, 2).classification == "mixed"


def test_peak_line_is_strict():
    """t > P75 + 3 x IQR, strictly: on the line it is `mixed`."""
    values = [0.0, 1.0, 2.0, 3.0, 4.0]  # P25 1, P75 3, IQR 2: the line is 9
    assert category_a(hood(values), 9.0, 0.5, 2).classification == "mixed"
    peak = category_a(hood(values), 9.5, 0.5, 2)
    assert peak.classification == "isolated peak"
    assert peak.inputs["peak_line"] == 9.0 and peak.inputs["peak_factor"] == policy.PEAK_IQR_FACTOR


@pytest.mark.parametrize(
    ("tested", "resolved", "reason"),
    [
        (3, False, "untested surroundings (coverage 0.37 of 0.5)"),
        (4, False, "untested surroundings (n 4 of 5)"),  # coverage 0.5 passes, min(5, 8) not
        (5, True, None),
    ],
)
def test_isolated_peak_needs_coverage(tested, resolved, reason):
    """A spike on a sampled surface (m = 2, 8 positions around the centre) is a peak only at
    coverage ≥ 0.5 and n ≥ min(2d + 1, 8) = 5; below either it is unresolved, never a peak."""
    centre = (2, 2)
    around = [(1, 2), (3, 2), (2, 1), (2, 3), (1, 1), (1, 3), (3, 1), (3, 3)]
    frame = lattice_frame(
        lambda p: 100.0 if p == centre else 1.0,
        [5, 5],
        only={centre, *around[:tested]},
        pass_of=lambda p: "sample",
        scheduled=tested + 1,
    )
    a = card_of(frame, centre)["categories"]["A"]
    assert a["inputs"]["valid"] == 8 and a["inputs"]["m"] == policy.NEIGHBOUR_M_SAMPLED
    assert a["resolved"] is resolved and a["reason"] == reason
    assert a["classification"] == ("isolated peak" if resolved else None)


def test_a_coverage_below_half_never_rounds_up_to_half():
    a = category_a(hood([1.0] * 496, valid=1000), 1.0, 1.0, 20)
    assert a.reason == "untested surroundings (coverage 0.49 of 0.5)"


def test_a_coverage_of_exactly_half_resolves():
    """10 of 20 at d = 2: coverage ≥ 0.5, and n ≥ min(5, 20)."""
    a = category_a(hood([1.0] * 10, valid=20), 1.0, 1.0, 2)
    assert a.inputs["coverage"] == 0.5 and a.resolved and a.classification == "stable local"


def test_no_neighbour_at_all_is_unresolved():
    """A single configuration has no surroundings: nothing to call stable."""
    frame = lattice_frame(lambda p: 5.0, [1, 1])
    a = card_of(frame, (0, 0))["categories"]["A"]
    assert a["resolved"] is False and a["inputs"]["valid"] == 0
    assert a["reason"] == "untested surroundings (coverage 0.0 of 0.5)"


def test_t_is_outside_its_own_neighbourhood():
    frame = lattice_frame(lambda p: float(p[0] + p[1]), [3, 3])
    t = trial_at(frame, (1, 1))
    found = neighbourhood(frame, t)
    assert t not in found.trials and found.probes == 4 == found.valid == found.tested
    assert sorted(found.values) == [1.0, 1.0, 3.0, 3.0]  # never t's own 2.0


def test_undefined_neighbours_are_not_tested_and_are_counted():
    """A completed neighbour without a value of the metric cannot support a claim."""
    centre = (1, 1)
    frame = lattice_frame(lambda p: None if p == (0, 1) else 5.0, [3, 3])
    found = neighbourhood(frame, trial_at(frame, centre))
    assert (found.valid, found.tested, found.undefined) == (4, 3, 1)
    assert len(found.values) == len(found.trials) == 3
    a = category_a(found, 5.0, 0.0, 2)
    assert a.resolved is False and a.inputs["undefined"] == 1


def test_an_undefined_value_on_t_is_unresolved_with_its_reason():
    frame = lattice_frame(lambda p: None if p == (1, 1) else 5.0, [3, 3])
    card = card_of(frame, (1, 1), axes=[paths_of(2)[0]])
    for name in ("A", "B"):
        assert card["categories"][name]["resolved"] is False
        assert card["categories"][name]["reason"] == "undefined metric value"
    assert card["value"] is None


def test_a_prints_what_its_denominator_is():
    """Ruling on assumption 7: `valid` comes from the frame, and the category says so."""
    frame = spike_and_plateau()
    assert card_of(frame, SPIKE_AT)["categories"]["A"]["inputs"]["valid_basis"] == "frame"
    untested = lattice_frame(lambda p: 1.0, [3, 3], only={(1, 1), (2, 2)})
    assert card_of(untested, (1, 1))["categories"]["A"]["inputs"]["valid_basis"] == "frame"


# --- `valid` from the frame --------------------------------------------------------------------


def test_a_skipped_cell_of_a_fully_attempted_grid_is_not_valid():
    """The schedule is the valid cells, so a position with no row after every scheduled cell was
    attempted is one the grid skipped: it never lowers coverage."""
    skipped = (1, 2)
    kept = {
        (i, j) for i in range(3) for j in range(3) if (i, j) != skipped
    }  # 8 of 9 cells, all attempted
    frame = lattice_frame(lambda p: 5.0, [3, 3], only=kept, valid=8)
    found = neighbourhood(frame, trial_at(frame, (1, 1)))
    assert (found.probes, found.valid, found.tested) == (4, 3, 3)
    assert category_a(found, 5.0, 1.0, 2).classification == "stable local"


def test_a_pending_cell_of_a_running_grid_stays_valid():
    """Before every scheduled cell was attempted, an absent position may be pending: it counts
    as untested, which errs toward unresolved and never toward a false `stable`."""
    kept = {(1, 1), (0, 1), (2, 1), (1, 0)}
    frame = lattice_frame(lambda p: 5.0, [3, 3], only=kept, valid=8)
    found = neighbourhood(frame, trial_at(frame, (1, 1)))
    assert (found.probes, found.valid, found.tested) == (4, 4, 3)


def test_a_row_the_pool_refused_is_not_valid_and_a_failed_one_is():
    def status(position):
        return {(0, 1): "invalid", (2, 1): "failed"}.get(position, "ok")

    frame = lattice_frame(lambda p: 5.0, [3, 3], status=status)
    found = neighbourhood(frame, trial_at(frame, (1, 1)))
    assert (found.probes, found.valid, found.tested) == (4, 3, 2)
    assert found.coverage == pytest.approx(2 / 3)


def test_an_unknown_or_uncompleted_trial_is_refused():
    frame = lattice_frame(lambda p: 5.0, [3, 3], status=lambda p: "failed" if p == (1, 1) else "ok")
    with pytest.raises(KeyError, match="no trial 99"):
        neighbourhood(frame, 99)
    with pytest.raises(ValueError, match="not a completed trial"):
        neighbourhood(frame, trial_at(frame, (1, 1)))


def test_a_screening_block_frame_is_refused():
    """Neighbourhoods read block 0 (§7.3a): an every-block frame has several rows per trial."""
    frame = stat_frame(d=2, values=4, n=20, seed=1, y=zero, blocks={1: zero, 2: zero})
    assert frame.selection == ALL_BLOCKS
    with pytest.raises(ValueError, match="block-0"):
        neighbourhood(frame, 0)


def test_default_m_follows_the_surface():
    grid = lattice_frame(lambda p: 1.0, [3, 3])
    sampled = lattice_frame(lambda p: 1.0, [3, 3], pass_of=lambda p: "sample", scheduled=8, valid=9)
    centre = (1, 1)
    assert neighbourhood(grid, trial_at(grid, centre)).m == policy.NEIGHBOUR_M_GRID
    assert neighbourhood(grid, trial_at(grid, centre)).probes == 4
    assert neighbourhood(sampled, trial_at(sampled, centre)).m == policy.NEIGHBOUR_M_SAMPLED
    assert neighbourhood(sampled, trial_at(sampled, centre)).probes == 8
    assert neighbourhood(sampled, trial_at(sampled, centre), m=1).probes == 4


def test_r_widens_the_steps():
    frame = lattice_frame(lambda p: 1.0, [7, 7])
    found = neighbourhood(frame, trial_at(frame, (3, 3)), r=2)
    assert found.probes == 8 and found.tested == 8 and found.r == 2


# --- hashed positions ----------------------------------------------------------------------------


def test_position_codes_hash_positions_per_row():
    frame = stat_frame(d=20, values=9, n=500, seed=7, y=zero)
    index = build_index(frame)
    codes = position_codes(frame, index)
    assert codes.dtype == np.int64 and len(codes) == frame.table.num_rows
    twin = frame.table.take(pa.array([3, 3, 4]))  # a repeated configuration hashes alike
    copy = replace(frame, table=twin)
    twins = position_codes(copy, build_index(copy))
    assert twins[0] == twins[1] == codes[3] and twins[2] == codes[4]
    positions = np.stack([frame.table.column(f"pos.{k}").to_numpy() for k in range(20)], axis=1)
    assert len(np.unique(codes)) == len(np.unique(positions, axis=0))


def _centred(rng, n, sizes):
    rows = rng.integers(0, sizes, size=(n, len(sizes)))
    rows[0] = np.asarray(sizes) // 2
    return rows


class _ReadCounter(np.ndarray):
    """A code column that counts the elements read from it, by an index or by a ufunc, which is
    what a `code == x` scan is."""

    read = 0

    def __getitem__(self, key):
        out = super().__getitem__(key)
        _ReadCounter.read += int(np.size(out))
        return out

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        counted = [x for x in inputs if isinstance(x, _ReadCounter)]
        _ReadCounter.read += sum(x.size for x in counted)
        plain = [x.view(np.ndarray) if isinstance(x, _ReadCounter) else x for x in inputs]
        return getattr(ufunc, method)(*plain, **kwargs)


def test_the_read_counter_sees_a_scan():
    """So `test_neighbourhood_probes_by_hash` can rely on it: a whole-column comparison counts."""
    code = np.arange(100, dtype=np.uint16).view(_ReadCounter)
    _ReadCounter.read = 0
    assert int((code == 3).sum()) == 1
    assert _ReadCounter.read >= 100
    _ReadCounter.read = 0
    assert int(code[3]) == 3 and _ReadCounter.read == 1


@pytest.mark.parametrize("n", [2_000, 20_000])
def test_neighbourhood_probes_by_hash(monkeypatch, n):
    """d = 20, m = 2: every position's lookup is one needle of one `np.searchsorted` (800 ≤ 840),
    whatever the rows, and only the rows hit are read from the codes: no pairwise scan."""
    frame = stat_frame(d=D_WIDE, values=VALUES, n=n, seed=5, y=zero, draw=_centred)
    index = build_index(frame)
    position_table(frame, index)  # built once for the snapshot, before anything is counted
    needles: list[int] = []
    real = np.searchsorted

    def counting(a, v, *args, **kwargs):
        needles.append(int(np.size(v)))
        return real(a, v, *args, **kwargs)

    for path, code in list(index.codes.items()):
        index.codes[path] = code.view(_ReadCounter)
    _ReadCounter.read = 0
    monkeypatch.setattr(np, "searchsorted", counting)
    found = neighbourhood(frame, 0, m=2, index=index)
    assert found.probes == 800  # 4 x C(20, 2) + 2 x 20, within §7.6's 840
    assert needles == [found.probes]
    assert _ReadCounter.read <= (found.probes + 1) * D_WIDE


def test_neighbourhood_equals_a_pairwise_scan():
    """The hashed answer against the definition, row by row, on a small sampled surface."""
    frame = stat_frame(d=4, values=5, n=300, seed=3, y=first_order)
    positions = np.stack([frame.table.column(f"pos.{k}").to_numpy() for k in range(4)], axis=1)
    values = frame.table.column("combined.net_pnl").to_numpy()
    index = build_index(frame)
    for t in range(0, 300, 25):
        steps = np.abs(positions.astype(int) - positions[t].astype(int))
        near = (
            (steps.max(axis=1) <= 1)
            & (1 <= (steps > 0).sum(axis=1))
            & ((steps > 0).sum(axis=1) <= 2)
        )
        seen: dict[tuple, int] = {}
        for row in np.flatnonzero(near).tolist():
            seen.setdefault(tuple(positions[row].tolist()), row)
        found = neighbourhood(frame, t, m=2, index=index)
        assert found.trials == sorted(seen.values())
        assert found.values == [float(values[row]) for row in sorted(seen.values())]


def test_a_hash_collision_never_counts_a_wrong_neighbour(monkeypatch):
    """Every hash equal: each probe walks the whole table, and the answer is still the
    definition's, because a hit is checked against the positions themselves."""
    frame = stat_frame(d=3, values=5, n=120, seed=9, y=first_order)
    honest = neighbourhood(frame, 7, m=2)
    monkeypatch.setattr(neighbours_module, "_multipliers", lambda d: np.zeros(d, dtype=np.int64))
    collided = neighbourhood(frame, 7, m=2)
    assert collided == honest


def test_a_position_prefers_its_completed_trial():
    """Two rows at one position, the failed one first: the completed one is the tested one."""
    centre, side = (1, 1), (0, 1)
    frame = lattice_frame(lambda p: 5.0, [3, 3])
    table = frame.table
    row = trial_at(frame, side)
    failed = table.take(pa.array([row]))
    failed = failed.set_column(
        failed.schema.get_field_index("status"),
        "status",
        pa.array(["failed"], failed.schema.field("status").type),
    )
    failed = failed.set_column(0, "trial_no", pa.array([-1], pa.int64()))
    both = replace(frame, table=pa.concat_tables([failed, table]))
    found = neighbourhood(both, trial_at(frame, centre))
    assert found.tested == 4 and -1 not in found.trials


def test_a_value_off_the_lattice_takes_no_step_along_its_axis():
    """A surface edited after the trials ran: t's first value left the lattice, so it has no
    neighbour along that axis, and its steps along the other stay on the same off-lattice code."""
    frame = lattice_frame(lambda p: 5.0, [3, 3])
    path = paths_of(2)[0]
    edited = [
        replace(p, values=[1.0, 2.0], stop=2.0) if p.path == path else p for p in frame.parameters
    ]
    moved = replace(frame, parameters=edited)
    t = trial_at(frame, (2, 1))  # its first value, 3, is off the shorter lattice
    found = neighbourhood(moved, t)
    assert found.probes == 2 and found.trials == [
        trial_at(frame, (2, 0)),
        trial_at(frame, (2, 2)),
    ]


def test_legacy_experiment_neighbourhood_from_values():
    """Review Focus 5: no `pos.<k>` columns, so the lattice positions come from the values."""
    frame = stat_frame(d=3, values=6, n=150, seed=3, y=first_order)
    legacy = replace(
        frame, table=frame.table.drop_columns([f"pos.{k}" for k in range(3)]), layout=1
    )
    for t in (0, 40, 90):
        assert neighbourhood(legacy, t, m=2) == neighbourhood(frame, t, m=2)


def test_legacy_store_neighbourhood_through_its_promotion(world):  # noqa: F811
    """A real layout-1 folder read through `open_experiment`: the promoted frame's neighbours
    are its grid's."""
    repository, _library, strategy = world
    store = exp.ExperimentStore(repository)
    legacy = hand_document(repository, strategy, experiment_id="legacy-hood", status="done")
    store.write_chunk(legacy.id, 0, rows_of(range(12)), PATHS)
    assert store.layout(legacy.id) == 1
    meta = sources.experiment_meta(legacy)
    columns = (
        *sources.BASE,
        "design",
        "pass",
        *PATHS,
        *(f"pos.{k}" for k in range(len(PATHS))),
        "combined.net_pnl",
    )
    frame, handle = sources.open_experiment(legacy, store, LabCache(), columns)
    try:
        assert frame.layout == 1 and frame.parameters == meta.parameters
        found = neighbourhood(frame, 5)
        grid = exp.build_grid(legacy.spec, legacy.surface, legacy.plan.get("bars"))
        assert found.trials == sorted(grid.neighbours(5))
        assert found.valid == len(grid.neighbours(5))
    finally:
        lab_store.REGISTRY.release(handle)


# --- τ ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("metric", ["net_pnl", "max_drawdown"])
def test_tau_is_the_analysis_band(metric):
    """`analysis.analyse`'s band: its oriented values, `tolerance × (P90 − P10)`, over the
    completed rows only; a row the pool refused or that failed has none."""
    frame = lattice_frame(
        lambda p: float(p[0] * p[0] + p[1]),
        [6, 6],
        status=lambda p: "invalid" if p == (5, 5) else "failed" if p == (5, 4) else "ok",
    )
    table = frame.table
    columns = {
        "cell": table.column("cell").to_pylist(),
        "valid": table.column("valid").to_pylist(),
        f"combined.{metric}": table.column(f"combined.{metric}").to_pylist(),
    }
    columns["valid"] = [s == "ok" for s in table.column("status").to_pylist()]
    values, _, _, _ = analysis.objective_values(columns, metric)
    p10, p90 = np.percentile(np.array(list(values.values())), [10, 90])
    assert tau(frame, metric, SCOPE, 0.2) == float(0.2 * (p90 - p10))


def test_tau_on_nothing_is_zero():
    assert tau(lattice_frame(lambda p: None, [2, 2]), METRIC, SCOPE, TOLERANCE) == 0.0


# --- category B --------------------------------------------------------------------------------


def _region_frame(value=lambda p: 50.0, **kw):
    """21 x 5 cells: L∞ 0.15 of the first axis's range is ±3 steps, 7 of its 21 values."""
    return lattice_frame(value, [21, 5], **kw)


def test_b_reads_the_radius_of_the_axis_range():
    frame = _region_frame()
    paths = paths_of(2)
    t = trial_at(frame, (10, 2))
    b = category_b(frame, t, [paths[0]], 1.0)
    assert b.name == "B" and b.resolved and b.classification == "stable region"
    inputs = b.inputs
    assert inputs["n"] == 7 * 5 - 1  # t is outside its region
    assert inputs["radius"] == policy.REGION_RADIUS and inputs["min_n"] == policy.REGION_MIN_N
    assert inputs["axes"] == [paths[0]] and inputs["tau"] == 1.0
    assert inputs["region_share"] == pytest.approx(7 / 21)
    assert inputs["population"] == 104
    assert inputs["density"] == pytest.approx(34 / (104 * 7 / 21))


def test_b_classifies_by_the_region_p25_against_tau():
    paths = paths_of(2)
    frame = _region_frame()
    t = trial_at(frame, (10, 2))
    assert category_b(frame, t, [paths[0]], 1.0).classification == "stable region"
    spiked = _region_frame(lambda p: 100.0 if p == (10, 2) else 50.0)
    b = category_b(spiked, t, [paths[0]], 1.0)
    assert b.resolved and b.classification == "unstable region"
    assert b.inputs["p25"] == 50.0 and b.inputs["distance"] == 50.0


def test_b_reads_the_p25_and_never_the_p75():
    """A region whose upper half is far above t: its P25 is t's, so it is stable."""
    paths = paths_of(2)

    def value(position):
        return 90.0 if position[0] > 10 else 50.0

    frame = _region_frame(value)
    b = category_b(frame, trial_at(frame, (10, 2)), [paths[0]], 1.0)
    assert b.inputs["p25"] == 50.0 and b.inputs["p75"] == 90.0 and b.inputs["iqr"] == 40.0
    assert b.classification == "stable region"


def test_b_too_few_names_the_count():
    paths = paths_of(2)
    frame = _region_frame()
    # the second axis's ±0.6 holds t's value alone: 7 x 1 cells, less t
    b = category_b(frame, trial_at(frame, (10, 2)), paths, 1.0)
    assert b.resolved is False and b.classification is None
    assert b.reason == "too few sampled trials in the region (6 of 30)"
    assert b.inputs["n"] == 6
    assert b.inputs["region_share"] == pytest.approx(7 / 21 * 1 / 5)  # every axis's share


def test_b_is_clipped_at_the_range_edge():
    paths = paths_of(2)
    frame = _region_frame()
    b = category_b(frame, trial_at(frame, (0, 2)), [paths[0]], 1.0)
    assert b.inputs["region_share"] == pytest.approx(4 / 21)
    assert b.inputs["n"] == 4 * 5 - 1


def test_b_excludes_adaptive_rows_and_counts_them():
    paths = paths_of(2)

    def pass_of(position):
        return "refine" if 7 <= position[0] <= 8 else "grid"

    frame = _region_frame(pass_of=pass_of)
    b = category_b(frame, trial_at(frame, (10, 2)), [paths[0]], 1.0)
    assert b.inputs["adaptive_excluded"] == 10
    assert b.inputs["n"] == 24 and b.resolved is False
    assert b.reason == "too few sampled trials in the region (24 of 30)"


@pytest.mark.parametrize(("kept", "resolved"), [(30, True), (29, False)])
def test_b_resolves_at_exactly_its_minimum(kept, resolved):
    """n ≥ 30: the region's 34 other cells cut down to `kept`, the others out of its reach."""
    paths = paths_of(2)
    centre = (10, 2)
    inside = [(i, j) for i in range(7, 14) for j in range(5) if (i, j) != centre]
    frame = _region_frame(only={centre, *inside[:kept], (0, 0)})
    b = category_b(frame, trial_at(frame, centre), [paths[0]], 1.0)
    assert b.inputs["n"] == kept and b.resolved is resolved
    assert (b.reason is None) is resolved


@pytest.mark.parametrize("offset", [1.0, 100_000.0])
def test_b_keeps_a_value_exactly_on_the_radius(offset):
    """41 values 0.1 apart: 0.15 of the range is 6 steps, which float rounding would lose, and more
    so far from zero, where the rounding scales with the values and not with the reach."""
    path = paths_of(1)[0]
    lattice = [offset + k * 0.1 for k in range(41)]
    rows = [{"params": {path: value}, "metrics": {"combined.net_pnl": 1.0}} for value in lattice]
    frame = frame_of(rows, [path])
    b = category_b(frame, 20, [path], 1.0)
    assert b.inputs["region_share"] == pytest.approx(13 / 41)
    assert b.inputs["n"] == 12


def test_b_slack_never_reaches_the_next_value():
    """The slack is for rounding: a value one step past the radius stays out, far from zero too."""
    path = paths_of(1)[0]
    lattice = [100_000.0 + k * 0.1 for k in range(21)]  # 0.3 of reach: 3 steps either side
    rows = [{"params": {path: value}, "metrics": {"combined.net_pnl": 1.0}} for value in lattice]
    frame = frame_of(rows, [path])
    assert category_b(frame, 10, [path], 1.0).inputs["n"] == 6


def test_b_without_axes_says_importance_is_not_computed():
    frame = _region_frame()
    b = category_b(frame, trial_at(frame, (10, 2)), [], 1.0)
    assert b.resolved is False and b.reason == NO_IMPORTANCE


def test_b_ignores_undefined_values_and_refused_rows():
    paths = paths_of(2)
    frame = _region_frame(
        lambda p: None if p == (9, 0) else 50.0,
        status=lambda p: "invalid" if p == (9, 1) else "ok",
    )
    b = category_b(frame, trial_at(frame, (10, 2)), [paths[0]], 1.0)
    assert b.inputs["n"] == 7 * 5 - 3 and b.inputs["undefined"] == 1


def test_sparse_region_never_reported_as_local():
    """§15 row 26: a surface sampled alone: B resolved, A unresolved, and nothing on the card
    says `local`, while B's result says A is unresolved and names its radius and n."""
    frame = stat_frame(d=3, values=20, n=2_000, seed=11, y=zero)
    axes = paths_of(3)[:2]
    card = card_of(frame, 0, axes=axes)
    a, b = card["categories"]["A"], card["categories"]["B"]
    assert a["resolved"] is False and a["reason"].startswith("untested surroundings (coverage ")
    assert b["resolved"] is True and b["classification"] in ("stable region", "unstable region")
    assert b["inputs"]["n"] >= policy.REGION_MIN_N
    assert b["inputs"]["radius"] == policy.REGION_RADIUS
    assert b["inputs"]["a_unresolved"] == a["reason"]
    assert "local" not in strict(card).lower()
    assert card["tested"] == ["B"] and card["unknown"] == ["A", "C", "D"]


def test_a_resolved_card_carries_no_note_of_a_on_b():
    frame = spike_and_plateau()
    b = card_of(frame, PLATEAU_BEST_INTERIOR, axes=paths_of(2)[:1])["categories"]["B"]
    assert "a_unresolved" not in b["inputs"]


def test_top_axes_read_the_importance_shares():
    paths = [f"p{k}" for k in range(8)]
    shares = [0.1, 0.5, None, 0.3, 0.2, 0.05, 0.4, 0.01]
    result = {"paths": paths, "fine": {"S": shares}}
    assert top_axes(result) == ["p1", "p6", "p3", "p4", "p0", "p5"]
    assert len(top_axes(result)) == policy.REGION_AXES
    assert top_axes(None) == []
    assert top_axes({"paths": paths, "fine": {"S": [None] * 8}}) == []
    assert top_axes({"paths": [], "fine": None}) == []
    tied = {"paths": ["a", "b"], "fine": {"S": [0.2, 0.2]}}
    assert top_axes(tied) == ["a", "b"]


# --- category C --------------------------------------------------------------------------------

FULL = FoldEvidence(bars=1_300, trades=300, net_pnl=130.0, max_drawdown=0.10)


def _folds(*overrides):
    base = [
        FoldEvidence(bars=100, trades=40, net_pnl=10.0, max_drawdown=0.10),
        FoldEvidence(bars=300, trades=60, net_pnl=30.0, max_drawdown=0.10),
        FoldEvidence(bars=900, trades=200, net_pnl=90.0, max_drawdown=0.10),
    ]
    return [*overrides, *base[len(overrides) :]]


def test_constant_per_unit_time_across_folds_is_consistent():
    """Folds of 100, 300 and 900 bars with the same net P&L per 1,000 bars."""
    c, finding = category_c(_folds(), [], full=FULL)
    assert c.name == "C" and c.resolved and c.classification == "consistent"
    assert c.reason is None and finding is None
    rows = c.inputs["fold_figures"]
    assert [row["net_pnl_per_1000_bars"] for row in rows] == [100.0, 100.0, 100.0]
    assert [row["ratio"] for row in rows] == [1.0, 1.0, 1.0]
    assert c.inputs["full"]["net_pnl_per_1000_bars"] == 100.0
    assert rows[0]["trades_per_1000_bars"] == 400.0 and rows[0]["expectancy_per_trade"] == 0.25


@pytest.mark.parametrize(
    ("net_pnl", "drawdown", "classification"),
    [
        (5.0, 0.10, "consistent"),  # 0.5 x, inclusive
        (4.9, 0.10, "inconsistent"),
        (20.0, 0.10, "consistent"),  # 2 x, inclusive
        (20.1, 0.10, "inconsistent"),
        (10.0, 0.15, "consistent"),  # 1.5 x the full range's drawdown, inclusive
        (10.0, 0.16, "inconsistent"),
        (0.0, 0.10, "inconsistent"),
        (-10.0, 0.10, "inconsistent"),
        (10.0, None, "inconsistent"),  # a drawdown it cannot check never passes
    ],
)
def test_fold_rule_boundaries(net_pnl, drawdown, classification):
    fold = FoldEvidence(bars=100, trades=40, net_pnl=net_pnl, max_drawdown=drawdown)
    c, _ = category_c(_folds(fold), [], full=FULL)
    assert c.resolved and c.classification == classification


def test_a_fold_of_exactly_the_minimum_trades_counts():
    fold = FoldEvidence(bars=100, trades=30, net_pnl=10.0, max_drawdown=0.1)
    assert category_c(_folds(fold), [], full=FULL)[0].classification == "consistent"


def test_a_folds_drawdown_of_exactly_the_factor_passes():
    """Figures that land exactly on 1.5 x in binary: 0.5 x 1.5 is 0.75 with no rounding, unlike
    the 0.1 x 1.5 of the table above, whose product rounds up past 0.15."""
    full = FoldEvidence(bars=1_300, trades=300, net_pnl=130.0, max_drawdown=0.5)
    at_limit = [FoldEvidence(bars=100, trades=40, net_pnl=10.0, max_drawdown=0.75)] * 3
    assert category_c(at_limit, [], full=full)[0].classification == "consistent"
    above = [FoldEvidence(bars=100, trades=40, net_pnl=10.0, max_drawdown=0.76)] * 3
    assert category_c(above, [], full=full)[0].classification == "inconsistent"


@pytest.mark.parametrize(
    "folds",
    [
        _folds(FoldEvidence(bars=100, trades=29, net_pnl=10.0, max_drawdown=0.1)),
        _folds(FoldEvidence(bars=100, trades=40, net_pnl=None, max_drawdown=0.1)),
        _folds(FoldEvidence(bars=100, trades=40, net_pnl=float("nan"), max_drawdown=0.1)),
        _folds(FoldEvidence(bars=0, trades=40, net_pnl=10.0, max_drawdown=0.1)),
        _folds()[:2],  # fewer than FOLDS_MIN, the fold count in `inputs`
    ],
)
def test_too_few_trades_per_fold(folds):
    c, _ = category_c(folds, [], full=FULL)
    assert c.resolved is False and c.classification is None
    assert c.reason == "too few trades per fold"
    assert c.inputs["folds"] == len(folds)
    assert c.inputs["folds_min"] == policy.FOLDS_MIN
    assert c.inputs["fold_min_trades"] == policy.FOLD_MIN_TRADES
    strict(c.inputs)


def test_no_blocks_or_folds_reads_the_table_reason():
    """Ruling P16: §7.6 binds on a K = 0 experiment."""
    for folds in (None, []):
        c, finding = category_c(folds, [])
        assert c.resolved is False and c.classification is None
        assert c.reason == "no blocks or folds"
        assert finding is None


BLOCKS = [
    BlockEvidence(bars=650, trades=150, net_pnl=65.0, max_drawdown=0.08),
    BlockEvidence(bars=650, trades=150, net_pnl=65.0, max_drawdown=0.09),
]
OTHER_BLOCKS = [
    BlockEvidence(bars=650, trades=150, net_pnl=-40.0, max_drawdown=0.30),
    BlockEvidence(bars=650, trades=150, net_pnl=170.0, max_drawdown=0.09),
]


def test_blocks_alone_leave_c_unresolved_and_cannot_change_it():
    """Blocks alone: `unresolved · selection-period only` with the separate finding, whatever the
    blocks hold. Beside folds, C is the same to the last input with or without them."""
    alone, finding = category_c(None, BLOCKS, full=FULL)
    assert alone.resolved is False and alone.classification is None
    assert alone.reason == SELECTION_ONLY
    assert finding is not None and finding.name == "selection-period consistency"
    assert finding.classification == "consistent"
    assert [row["net_pnl_per_1000_bars"] for row in finding.inputs["block_figures"]] == [
        100.0,
        100.0,
    ]
    other, other_finding = category_c(None, OTHER_BLOCKS, full=FULL)
    assert other == alone
    assert other_finding.classification == "inconsistent"
    plain, none = category_c(_folds(), [], full=FULL)
    with_blocks, one = category_c(_folds(), BLOCKS, full=FULL)
    with_others, other_one = category_c(_folds(), OTHER_BLOCKS, full=FULL)
    assert none is None and one.classification == "consistent"
    assert other_one.classification == "inconsistent"
    assert plain == with_blocks == with_others
    assert plain.classification == "consistent"


@pytest.mark.parametrize("full_pnl", [-13.0, 0.0])
def test_negative_and_zero_baselines_resolve_not_profitable(full_pnl):
    """No ratio is formed on a baseline ≤ 0: every fold's and block's `ratio` is None."""
    full = FoldEvidence(bars=1_300, trades=300, net_pnl=full_pnl, max_drawdown=0.10)
    c, finding = category_c(_folds(), BLOCKS, full=full)
    assert c.resolved and c.classification == "not profitable on the full range"
    assert all(row["ratio"] is None for row in c.inputs["fold_figures"])
    assert finding.classification == "not profitable on the full range"
    assert all(row["ratio"] is None for row in finding.inputs["block_figures"])
    strict(c.inputs)


def test_a_failed_or_absent_block_gives_no_verdict():
    """An evaluation that produced nothing is no evidence of inconsistency: the finding gives no
    verdict and says why, every block's figures still printed. C is exactly what it was."""
    missing = BlockEvidence(bars=650, trades=0, net_pnl=None, max_drawdown=None)
    alone, whole = category_c(None, BLOCKS, full=FULL)
    assert whole.classification == "consistent" and whole.reason is None
    c, finding = category_c(None, [BLOCKS[0], missing], full=FULL)
    assert c == alone
    assert finding.name == "selection-period consistency"
    assert finding.classification is None
    assert finding.reason == "block 2 has no defined figures"
    assert [row["net_pnl"] for row in finding.inputs["block_figures"]] == [65.0, None]
    _, both = category_c(None, [missing, missing], full=FULL)
    assert both.classification is None
    assert both.reason == "blocks 1, 2 have no defined figures"
    with_folds, one = category_c(_folds(), [BLOCKS[0], missing], full=FULL)
    assert with_folds == category_c(_folds(), [], full=FULL)[0]
    assert one.classification is None
    no_drawdown = BlockEvidence(bars=650, trades=150, net_pnl=65.0, max_drawdown=None)
    assert category_c(None, [no_drawdown], full=FULL)[1].classification is None
    negative = FoldEvidence(bars=1_300, trades=300, net_pnl=-1.0, max_drawdown=0.1)
    assert category_c(None, [missing], full=negative)[1].classification == (
        "not profitable on the full range"
    )
    strict(finding.to_json())


def test_a_fold_verdict_needs_the_full_range():
    """Nothing in Phase 3 passes folds; a caller of Phase 6 that forgets `full` is a bug, never a
    lenient `consistent`."""
    with pytest.raises(ValueError, match="full range"):
        category_c(_folds(), [])


def test_blocks_without_a_baseline_read_no_verdict():
    _, finding = category_c(None, BLOCKS)
    assert finding is not None and finding.classification is None
    assert finding.reason == "no full-range figures"


# --- category D --------------------------------------------------------------------------------

BASE = ReplayEvidence(bars=1_000, trades=50, net_pnl=100.0, max_drawdown=0.10)


def _stressed(net_pnl, drawdown=0.10):
    return {
        "base": BASE,
        "slippage×1.5": ReplayEvidence(
            bars=1_000, trades=50, net_pnl=net_pnl, max_drawdown=drawdown
        ),
    }


@pytest.mark.parametrize(
    ("net_pnl", "drawdown", "classification"),
    [
        (100.0, 0.10, "holds"),
        (70.0, 0.10, "holds"),  # 70 %, inclusive
        (69.9, 0.10, "degrades"),
        (90.0, 0.13, "holds"),  # 1.3 x, inclusive
        (90.0, 0.14, "degrades"),
        (90.0, None, "degrades"),  # a drawdown it cannot check never holds
        (0.0, 0.10, "fails"),
        (-5.0, 0.10, "fails"),
    ],
)
def test_replay_rule_boundaries(net_pnl, drawdown, classification):
    d = category_d(_stressed(net_pnl, drawdown))
    assert d.name == "D" and d.resolved and d.classification == classification
    assert d.reason is None
    assert d.inputs["base"]["net_pnl"] == 100.0 and d.inputs["stressed"]["net_pnl"] == net_pnl
    assert d.inputs["stress_keep"] == policy.STRESS_KEEP


def test_sub_year_replays_resolve_d_without_mar():
    """§7.6: per-unit-time statistics, no `cagr` or `mar`: 2,000 bars resolve and neither exists
    in the evidence or the inputs."""
    d = category_d(
        {
            "base": ReplayEvidence(bars=2_000, trades=30, net_pnl=50.0, max_drawdown=0.05),
            "slippage×1.5": ReplayEvidence(bars=2_000, trades=30, net_pnl=45.0, max_drawdown=0.05),
        }
    )
    assert d.resolved and d.classification == "holds"
    text = strict(d.inputs)
    assert "mar" not in text and "cagr" not in text
    assert d.inputs["base"]["net_pnl_per_1000_bars"] == 25.0
    assert d.inputs["ratio"] == pytest.approx(0.9)


@pytest.mark.parametrize("base_pnl", [-20.0, 0.0])
def test_negative_base_replay_is_not_profitable_at_base(base_pnl):
    """No ratio is formed on a base ≤ 0, whatever the stressed replay holds."""
    d = category_d(
        {
            "base": ReplayEvidence(bars=1_000, trades=50, net_pnl=base_pnl, max_drawdown=0.1),
            "slippage×1.5": ReplayEvidence(bars=1_000, trades=50, net_pnl=5.0, max_drawdown=0.1),
        }
    )
    assert d.resolved and d.classification == "not profitable at base"
    assert d.inputs["ratio"] is None


@pytest.mark.parametrize(
    "replays",
    [
        None,
        {},
        {"base": BASE},
        {"slippage×1.5": BASE},
        {"base": BASE, "slippage×1.5": replace(BASE, net_pnl=None)},
        {"base": replace(BASE, net_pnl=float("nan")), "slippage×1.5": BASE},
    ],
)
def test_no_replay_yet(replays):
    d = category_d(replays)
    assert d.resolved is False and d.classification is None and d.reason == NO_REPLAY
    strict(d.inputs)


# --- the card ------------------------------------------------------------------------------------


def _forbid_summed(node) -> None:
    if isinstance(node, dict):
        assert not (set(node) & SUMMED), set(node) & SUMMED
        for value in node.values():
            _forbid_summed(value)
    elif isinstance(node, list):
        for value in node:
            _forbid_summed(value)


def test_four_category_states():
    """All four, side by side: which were tested and which remain unknown, never summed."""
    frame = spike_and_plateau()
    card = card_of(frame, PLATEAU_BEST_INTERIOR, axes=paths_of(2)[:1])
    assert sorted(card["categories"]) == ["A", "B", "C", "D"]
    categories = card["categories"]
    assert all(categories[name]["name"] == name for name in categories)
    assert categories["A"]["classification"] == "stable local"
    assert categories["C"]["reason"] == "no blocks or folds"
    assert categories["D"]["reason"] == NO_REPLAY
    assert categories["B"]["inputs"]["n"] == 3 * 11 - 1  # ±1 step of the first axis, less t
    assert card["tested"] == ["A", "B"] and card["unknown"] == ["C", "D"]
    for name, category in categories.items():
        assert category["resolved"] is (name in card["tested"])
        assert (category["classification"] is None) is (not category["resolved"])
        assert (category["reason"] is None) is category["resolved"]
    assert card["findings"] == []
    assert card["trial_id"] == f"{frame.source}#{trial_at(frame, PLATEAU_BEST_INTERIOR)}"
    assert card["tolerance"] == TOLERANCE and card["tau"] > 0
    _forbid_summed(card)
    strict(card)


def test_the_card_with_blocks_reads_selection_period_only():
    """Decision 12: no folds and no replays in Phase 3; blocks only ever add the finding."""
    frame = spike_and_plateau()
    full = FoldEvidence(bars=1_300, trades=300, net_pnl=130.0, max_drawdown=0.10)
    card = card_of(frame, SPIKE_AT, blocks=BLOCKS, full=full)
    c, d = card["categories"]["C"], card["categories"]["D"]
    assert c["resolved"] is False and c["reason"] == SELECTION_ONLY
    assert d["resolved"] is False and d["reason"] == NO_REPLAY
    assert [finding["name"] for finding in card["findings"]] == ["selection-period consistency"]
    assert card["findings"][0]["classification"] == "consistent"
    assert "C" in card["unknown"]
    _forbid_summed(card)
    strict(card)


def test_the_card_echoes_a_default_tolerance_label():
    frame = spike_and_plateau()
    label = "default tolerance 0.15"
    card = card_of(frame, SPIKE_AT, tolerance_label=label)
    assert card["tolerance_label"] == label
    assert card_of(frame, SPIKE_AT)["tolerance_label"] is None


def _classifications():
    """Every classification of §7.6, each built from its own evidence."""
    frame = _region_frame()
    spiked = _region_frame(lambda p: 100.0 if p == (10, 2) else 50.0)
    axis = [paths_of(2)[0]]
    t = trial_at(frame, (10, 2))
    fold_good = _folds()
    fold_bad = _folds(FoldEvidence(bars=100, trades=40, net_pnl=50.0, max_drawdown=0.1))
    negative = FoldEvidence(bars=1_300, trades=300, net_pnl=-1.0, max_drawdown=0.1)
    return [
        ("stable local", category_a(hood([10.0] * 4), 10.0, 1.0, 2)),
        ("isolated peak", category_a(hood([10.0] * 4), 90.0, 1.0, 2)),
        ("mixed", category_a(hood([1.0, 10.0, 20.0, 30.0]), 40.0, 1.0, 2)),
        ("stable region", category_b(frame, t, axis, 1.0)),
        ("unstable region", category_b(spiked, t, axis, 1.0)),
        ("consistent", category_c(fold_good, [], full=FULL)[0]),
        ("inconsistent", category_c(fold_bad, [], full=FULL)[0]),
        ("not profitable on the full range", category_c(fold_good, [], full=negative)[0]),
        ("holds", category_d(_stressed(90.0))),
        ("degrades", category_d(_stressed(50.0))),
        ("fails", category_d(_stressed(-1.0))),
        (
            "not profitable at base",
            category_d(
                {
                    "base": replace(BASE, net_pnl=-1.0),
                    "slippage×1.5": BASE,
                }
            ),
        ),
    ]


REQUIRED_INPUTS = {
    "A": {"n", "coverage", "valid", "required_n", "p25", "p75", "iqr", "tau", "value"},
    "B": {"n", "radius", "density", "axes", "p25", "p75", "iqr", "tau", "value"},
    "C": {"full", "fold_figures", "ratio_band", "drawdown_factor"},
    "D": {"base", "stressed", "scenarios", "stress_keep", "drawdown_factor"},
}


def test_every_classification_carries_its_inputs():
    seen = set()
    for classification, category in _classifications():
        seen.add(classification)
        assert category.classification == classification and category.resolved
        assert REQUIRED_INPUTS[category.name] <= set(category.inputs), classification
        strict(category.to_json())
    assert len(seen) == 12


def test_no_spread_classifies_nothing():
    """Ruling P19, `analysis.analyse`'s `tau <= 0`: with no spread nothing can be told from
    anything. A and B read unresolved; a shortfall of evidence still reads as itself."""
    for band in (0.0, -1.0):
        a = category_a(hood([10.0] * 4), 10.0, band, 2)
        assert a.resolved is False and a.classification is None and a.reason == NO_SPREAD
    flat = _region_frame()
    card = card_of(flat, (10, 2), axes=paths_of(2)[:1])
    assert card["tau"] == 0.0 and card["tested"] == []
    for name in ("A", "B"):
        assert card["categories"][name]["resolved"] is False
        assert card["categories"][name]["reason"] == NO_SPREAD
    assert card["categories"]["B"]["inputs"]["n"] == 34
    short = category_a(hood([10.0] * 3, valid=6), 10.0, 0.0, 2)
    assert short.reason == "untested surroundings (n 3 of 5)"
    too_few = category_b(flat, trial_at(flat, (10, 2)), paths_of(2), 0.0)
    assert too_few.reason == "too few sampled trials in the region (6 of 30)"


def test_a_spike_on_a_flat_surface_is_not_a_peak_without_a_spread():
    """P10 = P90 with a value that differs: the band is empty, and no peak is named from it."""
    frame = lattice_frame(lambda p: 100.0 if p == (2, 2) else 5.0, [5, 5])
    a = card_of(frame, (2, 2))["categories"]["A"]
    assert a["inputs"]["tau"] == 0.0 and a["resolved"] is False and a["reason"] == NO_SPREAD


def test_a_mixed_trial_is_within_neither_rule():
    a = category_a(hood([1.0, 10.0, 20.0, 30.0]), 40.0, 1.0, 2)
    assert a.inputs["distance"] > 1.0 and 40.0 <= a.inputs["peak_line"]


def test_max_drawdown_is_oriented():
    """Lower is better: the trial far below its neighbours' drawdown is the peak."""
    frame = lattice_frame(lambda p: 0.01 if p == (2, 2) else 0.9 if p[0] == 4 else 0.5, [5, 5])
    card = candidate_card(
        frame,
        trial_at(frame, (2, 2)),
        metric="max_drawdown",
        scope=SCOPE,
        tolerance=TOLERANCE,
        axes=[],
    )
    a = card["categories"]["A"]
    assert a["classification"] == "isolated peak"
    assert card["value"] == -0.01 and card["orientation"] == -1
    assert a["inputs"]["orientation"] == -1 and a["inputs"]["p25"] == -0.5
    assert a["inputs"]["value"] == -0.01
    ranks = rankings(frame, metric="max_drawdown", scope=SCOPE, tolerance=TOLERANCE)
    assert ranks["peak"][0] == f"{frame.source}#{trial_at(frame, (2, 2))}"


# --- the rankings --------------------------------------------------------------------------------


def _id(frame, position) -> str:
    return f"{frame.source}#{trial_at(frame, position)}"


def test_rankings_shown_side_by_side():
    """Scenario 5: on a spike and a plateau the two rankings disagree, and `stable` names the
    plateau's interior trial."""
    frame = spike_and_plateau()
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20)
    assert len(ranks["peak"]) == len(ranks["robust"]) == 20
    assert ranks["peak"][0] == _id(frame, SPIKE_AT)
    assert ranks["robust"][0] == _id(frame, PLATEAU_BEST_INTERIOR)
    assert ranks["disagree"] is True
    assert ranks["stable"] == _id(frame, PLATEAU_BEST_INTERIOR)
    assert ranks["stable_reason"] is None
    assert ranks["k"] == 20 and ranks["pool"] == SPIKE_SIZES[0] * SPIKE_SIZES[1]
    assert _id(frame, SPIKE_AT) not in ranks["robust"]  # every resolved state above it fills them
    assert [row["trial_id"] for row in ranks["ranked"]] == ranks["robust"]
    assert [row["trial_id"] for row in ranks["peak_ranked"]] == ranks["peak"]
    best = ranks["ranked"][0]
    assert best["ranked_by"] == "A" and best["classification"] == "stable local"
    assert ranks["peak_ranked"][0]["classification"] == "isolated peak"
    strict(ranks)
    _forbid_summed(ranks)


def test_a_crowd_of_spikes_cannot_hide_a_plateau():
    """Ruling P18's probe: 25 spikes above a 15 x 15 plateau at k = 20. Every one of the top 20 by
    peak is a spike; the plateau is found from the pool, `disagree` says so and `stable` names it,
    as its own card has it."""
    frame = crowded_plateau()
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20)
    spikes = {_id(frame, position) for position in CROWDED_SPIKES}
    best = _id(frame, CROWDED_BEST_INTERIOR)
    assert ranks["k"] == 20 and ranks["pool"] == policy.RANK_POOL == 300
    assert len(ranks["peak"]) == len(ranks["robust"]) == 20
    assert set(ranks["peak"]) <= spikes
    assert ranks["robust"][0] == best and ranks["stable"] == best
    assert ranks["disagree"] is True and ranks["stable_reason"] is None
    assert card_of(frame, CROWDED_BEST_INTERIOR)["categories"]["A"]["classification"] == (
        "stable local"
    )


def test_the_pool_is_stated_and_bounds_stable(monkeypatch):
    """The same surface with a pool of the spikes alone: nothing stable among them, which is what
    `stable_reason` says, in the pool's own words."""
    monkeypatch.setattr(robustness_module, "RANK_POOL", 25)
    frame = crowded_plateau()
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20)
    assert ranks["pool"] == 25 and ranks["stable"] is None
    assert ranks["stable_reason"] == "none among the top 25 by peak"
    assert ranks["disagree"] is False


def test_the_list_length_is_k_bounded_by_the_pool():
    frame = crowded_plateau()
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=2)
    assert len(ranks["peak"]) == len(ranks["robust"]) == 2 and ranks["k"] == 2
    assert ranks["pool"] == policy.RANK_POOL
    widest = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=500)
    assert widest["k"] == policy.RANK_POOL == len(widest["peak"]) == len(widest["robust"])
    few = rankings(
        lattice_frame(lambda p: float(p[0]), [3, 3]),
        metric=METRIC,
        scope=SCOPE,
        tolerance=TOLERANCE,
    )
    assert few["pool"] == 9 and few["k"] == policy.RANKING_K and len(few["peak"]) == 9


def test_b_runs_only_on_the_top_k_and_the_rest_sort_unresolved(monkeypatch):
    """B is the costly part: of a pool whose A is unresolved, the top k by peak get it. A row
    without a B computed is unresolved, whatever a B would have said."""
    frame = stat_frame(d=3, values=20, n=1_000, seed=11, y=zero)
    axes = paths_of(3)[:2]
    calls: list[int] = []
    real = robustness_module._Regions.category

    def counting(self, row, *args, **kwargs):
        calls.append(row)
        return real(self, row, *args, **kwargs)

    monkeypatch.setattr(robustness_module._Regions, "category", counting)
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=3, axes=axes)
    assert ranks["pool"] == policy.RANK_POOL and len(calls) == 3
    assert [row["ranked_by"] for row in ranks["ranked"]] == ["B", "B", "B"]
    assert {row["trial_id"] for row in ranks["ranked"]} == set(ranks["peak"])
    one = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=1, axes=axes)
    assert len(calls) == 3 + 1 and [row["ranked_by"] for row in one["ranked"]] == ["B"]


def test_b_is_bounded_apart_from_k(monkeypatch):
    """Whatever `k` asks, B runs on at most RANK_B_MAX rows: the lists are as long as `k` says, and
    a row past the bound whose A is unresolved stays unresolved."""
    frame = stat_frame(d=3, values=20, n=1_000, seed=11, y=zero)
    axes = paths_of(3)[:2]
    calls: list[int] = []
    real = robustness_module._Regions.category

    def counting(self, row, *args, **kwargs):
        calls.append(row)
        return real(self, row, *args, **kwargs)

    monkeypatch.setattr(robustness_module._Regions, "category", counting)
    bound = policy.RANK_B_MAX
    for k in (bound + 1, 50, policy.RANK_POOL):
        calls.clear()
        ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=k, axes=axes)
        assert len(calls) == bound
        assert ranks["k"] == k == len(ranks["peak"]) and ranks["b_max"] == bound
        # the first rows by peak read it (a trial number is its row in this frame)
        assert [f"{frame.source}#{row}" for row in calls] == ranks["peak"][:bound]
        assert {row["ranked_by"] for row in ranks["peak_ranked"][bound:]} == {None}
    calls.clear()
    rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=bound, axes=axes)
    assert len(calls) == bound


def _plateau_on_a_ring(plateau: float, ring: float):
    """5 x 5: a centre with its neighbours all equal, inside a ring far from them."""

    def value(position):
        return plateau if 1 <= position[0] <= 3 and 1 <= position[1] <= 3 else ring

    return lattice_frame(value, [5, 5])


@pytest.mark.parametrize("plateau", [-10.0, 0.0])
def test_a_losing_plateau_is_not_named_stable(plateau):
    """Ruling P19: §7.6's order is untouched, so the plateau still leads `robust`, but `stable`
    never names a trial that loses money."""
    frame = _plateau_on_a_ring(plateau, -100.0)
    assert card_of(frame, (2, 2))["categories"]["A"]["classification"] == "stable local"
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["robust"][0] == _id(frame, (2, 2))
    assert ranks["stable"] is None
    assert ranks["stable_reason"] == "the most robust candidate has net_pnl ≤ 0"
    profitable = _plateau_on_a_ring(10.0, 1.0)
    ranks = rankings(profitable, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["stable"] == _id(profitable, (2, 2)) and ranks["stable_reason"] is None


def test_an_unsigned_metric_is_not_asked_to_be_positive():
    """A drawdown's oriented value is negative by construction: `stable` still names its best."""
    frame = _plateau_on_a_ring(0.1, 0.9)
    ranks = rankings(frame, metric="max_drawdown", scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["stable"] == _id(frame, (2, 2)) and ranks["stable_reason"] is None


@pytest.mark.parametrize(("plateau", "named"), [(0.8, False), (1.0, False), (1.2, True)])
def test_stable_requires_a_profit_factor_above_its_break_even(plateau, named):
    """Positive on a loss too: a profit factor breaks even at 1, and the order stays §7.6's."""
    frame = _plateau_on_a_ring(plateau, 0.1)
    ranks = rankings(frame, metric="profit_factor", scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["robust"][0] == _id(frame, (2, 2))
    if named:
        assert ranks["stable"] == _id(frame, (2, 2)) and ranks["stable_reason"] is None
    else:
        assert ranks["stable"] is None
        assert ranks["stable_reason"] == "the most robust candidate has profit_factor ≤ 1"


def test_every_metric_has_a_break_even_or_none():
    """A metric added later has to be put on one side or the other."""
    money = {"net_pnl", "net_return", "cagr", "mar", "expectancy", "sharpe_trade"}
    assert policy.BREAK_EVEN == {**dict.fromkeys(money, 0.0), "profit_factor": 1.0}
    none = {"max_drawdown", "win_rate", "trade_count", "exposure"}
    assert set(policy.BREAK_EVEN) | none == set(METRIC_NAMES)
    assert not set(policy.BREAK_EVEN) & none


def test_stable_scans_the_robust_order_for_the_first_that_qualifies():
    """Ruling P19's three conditions, on hand-written rows in `robust`'s order."""

    def entry(trial, classification, value, tie=0):
        rank = {"stable local": 0, "stable region": 1}.get(classification, 2)
        return {
            "trial_id": trial,
            "classification": classification,
            "value": value,
            "key": (rank, 3, 4, -value + tie, 1),
        }

    def named(*rows, metric="net_pnl"):
        return _stable_of(list(rows), metric=metric, pool=7, band=1.0)

    losing, region = entry("a", "stable local", -5.0), entry("b", "stable region", 3.0)
    assert named(losing, region) == ("b", None)
    tied = entry("a", "stable local", 9.0), entry("b", "stable local", 9.0)
    lower = entry("c", "stable local", 8.0)
    is_tied = (None, "the most robust candidates are tied on net_pnl")
    # the addendum's 100, 100, 99: a tie at the top names nothing, never the 99
    assert named(*tied, lower) == is_tied
    assert named(*tied) == is_tied
    assert named(losing) == (None, "the most robust candidate has net_pnl ≤ 0")
    assert named(losing, entry("c", "stable local", -6.0)) == named(losing)
    # the top is the first that qualifies: below its break-even a candidate is passed over, so the
    # tie is not at the very top and the reason says which candidates it is about
    tied_regions = entry("b", "stable region", 3.0), entry("c", "stable region", 3.0)
    above = (None, "the most robust candidates above break-even are tied on net_pnl")
    assert named(losing, *tied_regions) == above
    assert named(losing, *tied_regions, metric="profit_factor") == (
        None,
        "the most robust candidates above break-even are tied on profit_factor",
    )
    # a candidate that is not stable is not one passed over: the plain wording stays
    assert named(entry("m", "mixed", 50.0), *tied) == is_tied
    # and a metric with no break-even passes nobody over
    assert named(losing, entry("d", "stable local", -5.0), metric="win_rate") == (
        None,
        "the most robust candidates are tied on win_rate",
    )
    # a tie below the one that qualifies changes nothing
    assert named(entry("z", "stable local", 10.0), *tied) == ("z", None)
    assert named(entry("a", "mixed", 9.0)) == (None, "none among the top 7 by peak")
    assert named(losing, metric="win_rate") == ("a", None)
    assert _stable_of([], metric="net_pnl", pool=0, band=0.0) == (
        None,
        "no trial with a defined net_pnl in the filter",
    )
    assert _stable_of([losing], metric="net_pnl", pool=1, band=0.0) == (None, NO_SPREAD)


def test_the_rankings_basis_states_b_only_when_it_runs():
    """B runs only with axes, and on at most min(pool, k, RANK_B_MAX) rows: no line says more."""

    def ranks(pool, k):
        return {"pool": pool, "k": k, "b_max": policy.RANK_B_MAX}

    bare = "robust ranks the top 300 by peak"
    assert rankings_basis(ranks(300, 20), []) == bare
    assert rankings_basis(ranks(300, 20), ["x"]) == f"{bare}, B reads the top 20 (at most 20)"
    assert rankings_basis(ranks(300, 2), ["x"]) == f"{bare}, B reads the top 2 (at most 20)"
    assert rankings_basis(ranks(300, 300), ["x"]) == f"{bare}, B reads the top 20 (at most 20)"
    assert rankings_basis(ranks(4, 20), ["x"]) == (
        "robust ranks the top 4 by peak, B reads the top 4 (at most 20)"
    )
    assert rankings_basis(ranks(0, 20), ["x"]) == "robust ranks the top 0 by peak"


def test_constants_print_what_a_panel_reads():
    held = constants()
    assert held["PER_BARS"] == policy.PER_BARS == 1_000
    assert held["RANK_POOL"] == policy.RANK_POOL
    assert held["RANK_B_MAX"] == policy.RANK_B_MAX == 20
    assert held["BREAK_EVEN"] == policy.BREAK_EVEN
    strict(held)


def test_peak_is_the_metric_alone_best_first():
    frame = spike_and_plateau()
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=3)
    assert ranks["peak"] == [_id(frame, SPIKE_AT), _id(frame, (5, 5)), _id(frame, (5, 4))]


def test_the_robust_order_is_lexicographic():
    """A, or B where A is unresolved; then C; then D; unresolved below every resolved state; the
    metric, then the trial number, last."""

    def slot(name, classification=None):
        return Category(name, classification is not None, classification, "x", {})

    c0, d0 = slot("C"), slot("D")
    ordered = [
        slot("A", "stable local"),
        slot("B", "stable region"),
        slot("A", "mixed"),
        slot("B", "unstable region"),
        slot("A", "isolated peak"),
        slot("A"),
    ]
    keys = [robust_key(s, c0, d0, 1.0, 1) for s in ordered]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    stable = ordered[0]
    by_c = [
        robust_key(stable, slot("C", name), d0, 1.0, 1)
        for name in ("consistent", "inconsistent", "not profitable on the full range")
    ] + [robust_key(stable, slot("C"), d0, 1.0, 1)]
    assert by_c == sorted(by_c) and len(set(by_c)) == 4
    by_d = [
        robust_key(stable, c0, slot("D", name), 1.0, 1)
        for name in ("holds", "degrades", "fails", "not profitable at base")
    ] + [robust_key(stable, c0, slot("D"), 1.0, 1)]
    assert by_d == sorted(by_d) and len(set(by_d)) == 5
    # C outranks D, the slot outranks both, and the metric only breaks a tie
    assert robust_key(stable, slot("C", "consistent"), d0, 1.0, 1) < robust_key(
        stable, slot("C", "inconsistent"), slot("D", "holds"), 1.0, 1
    )
    assert robust_key(stable, c0, d0, 1.0, 1) < robust_key(
        slot("A", "mixed"), slot("C", "consistent"), slot("D", "holds"), 99.0, 1
    )
    assert robust_key(stable, c0, d0, 9.0, 5) < robust_key(stable, c0, d0, 1.0, 1)
    assert robust_key(stable, c0, d0, 1.0, 1) < robust_key(stable, c0, d0, 1.0, 2)


def test_rankings_read_b_where_a_is_unresolved_and_label_it():
    frame = stat_frame(d=3, values=20, n=1_000, seed=11, y=zero)
    axes = paths_of(3)[:2]
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5, axes=axes)
    assert all(row["ranked_by"] == "B" for row in ranks["ranked"])
    assert {row["classification"] for row in ranks["ranked"]} <= {
        "stable region",
        "unstable region",
    }
    assert "stable local" not in strict(ranks)
    without = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert all(row["ranked_by"] is None for row in without["ranked"])
    assert all(row["reason"].startswith("untested surroundings") for row in without["ranked"])
    assert without["robust"] == without["peak"] and without["stable"] is None
    assert without["stable_reason"] == f"none among the top {without['pool']} by peak"


def test_stable_is_null_without_a_stable_candidate():
    """A checkerboard: nothing's neighbours are within τ of it."""
    frame = lattice_frame(lambda p: 100.0 if sum(p) % 2 else 0.0, [5, 5])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["stable"] is None and ranks["stable_reason"] == "none among the top 25 by peak"
    assert all(row["classification"] != "stable local" for row in ranks["ranked"])


def test_stable_is_null_when_ambiguous():
    """A plateau of one value: its interior is `stable local` at the same value, none *the* one."""

    def value(position):
        return 100.0 if 1 <= position[0] <= 5 and 1 <= position[1] <= 5 else 0.0

    frame = lattice_frame(value, [7, 7])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=4)
    assert ranks["ranked"][0]["classification"] == "stable local"
    assert ranks["stable"] is None
    assert ranks["stable_reason"] == "the most robust candidates are tied on net_pnl"


def test_a_tie_at_the_top_names_nothing():
    """100, 100, 99 on a real surface: two stable trials share the top and one stable trial sits
    under them. It is not the most robust, so `stable` does not name it."""
    top = {(3, 3), (3, 4)}

    def value(position):
        i, j = position
        if not (1 <= i <= 5 and 1 <= j <= 5):
            return 0.0
        return 100.0 if position in top else 99.0

    frame = lattice_frame(value, [7, 7])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert set(ranks["robust"][:2]) == {_id(frame, position) for position in top}
    assert ranks["ranked"][2]["classification"] == "stable local"
    assert ranks["ranked"][2]["value"] == 99.0
    assert ranks["stable"] is None
    assert ranks["stable_reason"] == "the most robust candidates are tied on net_pnl"

    def untied(position):
        return 100.0 if position == (3, 3) else value(position) if position not in top else 99.0

    single = lattice_frame(untied, [7, 7])
    ranks = rankings(single, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=5)
    assert ranks["stable"] == _id(single, (3, 3)) and ranks["stable_reason"] is None


def test_no_spread_names_no_stable_candidate():
    """Ruling P19: the τ = 0 surface, every value the same."""
    frame = lattice_frame(lambda p: 5.0, [3, 3])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=4)
    assert ranks["stable"] is None and ranks["stable_reason"] == NO_SPREAD
    assert {row["reason"] for row in ranks["ranked"]} == {NO_SPREAD}
    assert {row["ranked_by"] for row in ranks["ranked"]} == {None}


def test_rankings_agree_when_the_top_is_stable():
    frame = lattice_frame(lambda p: 50.0 + 0.01 * p[0] + 0.001 * p[1], [5, 5])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=1.0, k=1)
    assert ranks["peak"] == ranks["robust"] and ranks["disagree"] is False
    assert ranks["stable"] == ranks["peak"][0]


def test_disagree_reads_the_first_trial_alone():
    """The plateau's centre tops both rankings: lower down they differ, and nothing is to say."""

    def value(position):
        i, j = position
        if position == (8, 8):
            return 99.0  # a spike under the plateau's top, above the rest of it
        if 1 <= i <= 5 and 1 <= j <= 5:
            return 100.0 - abs(i - 3) - abs(j - 3) - 0.01 * i - 0.001 * j
        return 10.0 + 0.1 * i + 0.01 * j

    frame = lattice_frame(value, [11, 11])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=10)
    assert ranks["peak"][0] == ranks["robust"][0] == _id(frame, (3, 3))
    assert ranks["peak"] != ranks["robust"]
    assert ranks["disagree"] is False and ranks["stable"] == _id(frame, (3, 3))


def test_b_never_stands_in_for_a_resolved_a():
    frame = spike_and_plateau()
    axes = paths_of(2)[:1]
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20, axes=axes)
    assert {row["ranked_by"] for row in ranks["ranked"]} == {"A"}
    assert ranks["robust"][0] == _id(frame, PLATEAU_BEST_INTERIOR)


def test_rankings_of_nothing_are_empty():
    frame = lattice_frame(lambda p: None, [2, 2])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE)
    assert ranks["peak"] == ranks["robust"] == [] and ranks["ranked"] == []
    assert ranks["disagree"] is False and ranks["stable"] is None
    assert ranks["pool"] == 0 and ranks["peak_ranked"] == []
    assert ranks["stable_reason"] == "no trial with a defined net_pnl in the filter"


def test_the_filter_selects_candidates_and_neighbours_read_every_trial():
    """Assumption 5: a brush picks who is ranked, and a candidate on its border keeps the
    neighbours the brush left out: they are tested, whatever the filter shows."""
    frame = spike_and_plateau()
    path = paths_of(2)[0]
    flt = LabFilter(ranges={path: [1.0, 4.0]})  # position 3 is the brush's last value
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20, flt=flt)
    border = (3, 3)  # its neighbour (4, 3) is outside the brush
    assert _id(frame, SPIKE_AT) not in ranks["peak"]
    assert _id(frame, (5, 5)) not in ranks["peak"]
    assert ranks["robust"][0] == _id(frame, (3, 4))
    row = next(r for r in ranks["ranked"] if r["trial_id"] == _id(frame, border))
    assert row["classification"] == "stable local"
    assert card_of(frame, border)["categories"]["A"]["inputs"]["tested"] == 4
    full = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=20)
    assert full["peak"][0] == _id(frame, SPIKE_AT)


def test_ranking_undefined_values_never_rank():
    frame = lattice_frame(lambda p: None if p == (1, 1) else float(p[0]), [3, 3])
    ranks = rankings(frame, metric=METRIC, scope=SCOPE, tolerance=TOLERANCE, k=9)
    assert _id(frame, (1, 1)) not in ranks["peak"] and len(ranks["peak"]) == 8
