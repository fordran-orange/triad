"""Optimization Lab v2, Phase 3, Tasks 4 and 5: importance (spec §7.3, §7.4 and §7.4a, decisions
17 to 21).

Task 4: the analysis cohort, the adjusted shares, their re-centred bootstrap intervals, the
per-share and family-wise (max-T) detection floors, coverage and aliasing.
Task 5: the coarse decomposition and its residual, availability, the veto, the recommended
statuses and the evidence scope: the sixteen §20 cases at seeds 1, 2 and 3.

Every case runs on the seeded experiments of `lab_stat_fixtures.stat_frame` at its fixed
generator constants; a (case, seed) that does not hold is a strict xfail carrying its numbers,
an R3.5 finding, never tuned away."""

import functools
import itertools
import json
import math
import re
import time
from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pyarrow as pa
import pytest
from lab_stat_fixtures import (
    BINARY,
    CHILD_VALUES,
    D_WIDE,
    PROPOSAL_ROWS,
    SIGMA,
    SINE_VALUES,
    SPARSE_PRESENT,
    SPARSE_VALUES,
    VALUES,
    D,
    aliased_rows,
    child_hinge,
    faint_second,
    first_order,
    high,
    hinge,
    one_cell_skipped,
    parity,
    parity_bit,
    parity_table,
    quadrant,
    scope_document,
    sine,
    stack_frames,
    stat_frame,
    two_apart,
    uneven_effect,
    uneven_rows,
    value_index,
    xor_pair,
    zero,
)
from products.aegis.lab import importance as importance_module
from products.aegis.lab import store as lab_store
from products.aegis.lab.analytics import (
    INCREMENTS,
    INSUFFICIENT,
    MAINS,
    MEASURED,
    CoarseTerms,
    FineTerms,
    aliased,
    block_mains,
    coarse,
    coarse_bins,
    coarse_floors,
    coarse_intervals,
    coarse_parts,
    cohort,
    coverage_label,
    cramers_v,
    fine_families,
    fine_parts,
    fine_shares,
    floors,
    incremental,
    interaction,
    intervals,
    pair_quality,
    triples_top,
)
from products.aegis.lab.importance import (
    importance_basis,
    importance_stages,
    interactions_payload,
    triples_payload,
)
from products.aegis.lab.policy import (
    BOOTSTRAP_B,
    COARSE_BOOTSTRAP_B,
    COARSE_PERMUTATION_P,
    IMPORTANCE_ROWS,
    PAIR_MIN_COVERAGE,
    PERMUTATION_P,
    RESIDUAL_VETO,
    THETA_MIN,
    TRIPLE_TOP,
)
from products.aegis.lab.query import BLOCK0, LabFilter, matrix_view
from products.aegis.lab.rule import (
    assess,
    availability,
    candidates,
    compare_scope,
    conditions,
    evidence_scope,
    statuses,
    veto,
)
from products.aegis.lab.shares import design_of, parameter_blocks
from products.aegis.lab.tasks import Cancelled

pytestmark = pytest.mark.aegis

SEED = 1
METRIC, SCOPE = "net_pnl", "combined"


def no_checkpoint() -> None:
    """A task's checkpoint outside a task: never cancelled."""


def cohort_of(frame, *, metric=METRIC, seed=SEED):
    return cohort(frame, metric=metric, scope=SCOPE, seed=seed)


class Fine:
    """The fine stage of one cohort: the point estimates, their 90 % intervals (unless
    `bounds=False`) and floors, each split into mains `S`, pairs `J` and increments `D`
    (`Δ[i, j]`, what i adds beyond j)."""

    def __init__(self, c, *, seed=SEED, bounds=True):
        fn = FineTerms(c.B)
        d = len(c.B)
        terms = fn(c.X, c.Y)
        lo = hi = np.full(terms.shape, np.nan)
        if bounds:
            lo, hi = intervals(fn, c.X, c.Y, b=BOOTSTRAP_B, seed=seed, checkpoint=no_checkpoint)
        found = floors(
            fn,
            c.X,
            c.Y,
            p=PERMUTATION_P,
            seed=seed,
            checkpoint=no_checkpoint,
            families=fine_families(d),
        )
        self.terms, self.lo, self.hi, self.found = terms, lo, hi, found
        self.S, self.J, self.D = fine_parts(terms)
        self.lo_S, self.lo_J, self.lo_D = fine_parts(lo)
        self.hi_S, self.hi_J, self.hi_D = fine_parts(hi)
        self.floor_S, _, self.floor_D = fine_parts(found.family)
        self.tick_S, _, self.tick_D = fine_parts(found.share)
        self.pairs = ~np.eye(d, dtype=bool)

    def detected_mains(self) -> np.ndarray:
        return self.S > self.floor_S

    def detected_increments(self) -> np.ndarray:
        return (self.D > self.floor_D) & self.pairs


def xor(u: np.ndarray) -> np.ndarray:
    return 2.0 * (high(u[:, 0]) ^ high(u[:, 1]))


# --- the fine-grid halves of the §20 cases ----------------------------------------------------


def test_strong_first_order_is_detected():
    """Case 1: Y = 3·x₁ + ε. x₁'s lower bound clears its family floor; every noise parameter's
    upper bound is below θ_min."""
    c = cohort_of(stat_frame(d=D, values=VALUES, seed=SEED, y=lambda u: 3.0 * u[:, 0]))
    fine = Fine(c)
    assert fine.lo_S[0] > fine.floor_S[0]
    assert (fine.hi_S[1:] < THETA_MIN).all(), fine.hi_S


def test_xor_has_mains_below_the_floor_and_a_large_increment():
    """Case 2: Y = 2·[(x₁ > m) XOR (x₂ > m)] + ε. Neither main clears its floor; what x₁ adds
    beyond x₂ is large."""
    fine = Fine(cohort_of(stat_frame(d=D, values=VALUES, seed=SEED, y=xor)))
    assert not fine.detected_mains()[:2].any(), (fine.S[:2], fine.floor_S[:2])
    assert fine.hi_D[0, 1] > 0.2


def test_aliased_inputs_share_credit():
    """Case 4: x₂ = x₁ + a small jitter by construction, Y = 3·x₁ + ε: only (x₁, x₂) is
    aliased."""
    frame = stat_frame(d=D, values=VALUES, seed=SEED, y=lambda u: 3.0 * u[:, 0], draw=aliased_rows)
    c = cohort_of(frame)
    assert aliased(cramers_v(c.X_uniform, c.B)) == [(0, 1)]


def test_uneven_sampling_flags_confounded_squares():
    """Case 5 (§20's generator, Ruling P7): P(x₁ = v) ∝ v and x₃ follows x₁;
    Y = 3·x₂ + x₁·x₂ + ε. The (x₁, x₂) aggregate matrix flags its squares `confounded` (by x₃),
    and what x₁ adds beyond x₂ has an upper bound above θ_min."""
    frame = stat_frame(
        d=D,
        values=VALUES,
        seed=SEED,
        y=lambda u: 3.0 * u[:, 1] + u[:, 0] * u[:, 1],
        draw=uneven_rows,
    )
    paths = [p.path for p in frame.parameters]
    matrix = matrix_view(
        frame, LabFilter(), rows=paths[0], cols=paths[1], metric=METRIC, mode="aggregate"
    )
    flagged = [s["confounded"] for row in matrix["stats"] for s in row if s and s["confounded"]]
    assert flagged and all(paths[2] in names for names in flagged)
    fine = Fine(cohort_of(frame))
    assert fine.hi_D[0, 1] > THETA_MIN


def test_sparse_values_are_insufficient_coverage():
    """Case 6: x₁ has 40 values, 8 of them present (the others invalid): `Insufficient
    coverage`, while every fully sampled parameter is `Measured`."""
    stride = SPARSE_VALUES // SPARSE_PRESENT
    frame = stat_frame(
        d=D,
        values=[SPARSE_VALUES] + [VALUES] * (D - 1),
        seed=SEED,
        y=lambda u: 3.0 * u[:, 0],
        valid=lambda u: np.rint(u[:, 0] * (SPARSE_VALUES - 1)) % stride == 0,
    )
    c = cohort_of(frame)
    assert len(np.unique(c.X[:, 0])) == SPARSE_PRESENT
    assert coverage_label(c.X, c.B, c.n) == [INSUFFICIENT] + [MEASURED] * (D - 1)


def test_one_block_regime_shows_a_block_range():
    """Case 8: Y = 3·x₁ in block 2 only and 0 (plus ε) elsewhere, blocks = 4; the full range
    carries block 2's effect. Block 2's S₁ lower bound is above 0.5; blocks 1, 3 and 4 have
    upper bounds below θ_min."""
    effect = {1: zero, 2: lambda u: 3.0 * u[:, 0], 3: zero, 4: zero}
    frame = stat_frame(d=D, values=VALUES, seed=SEED, y=lambda u: 3.0 * u[:, 0], blocks=effect)
    c = cohort_of(frame)
    assert sorted(c.blocks) == [1, 2, 3, 4]
    mains = block_mains(c, seed=SEED, checkpoint=no_checkpoint)
    assert sorted(mains) == [1, 2, 3, 4]
    assert mains[2].lo[0] > 0.5
    for b in (1, 3, 4):
        assert mains[b].hi[0] < THETA_MIN, (b, mains[b].hi[0])
    S, lo, hi, floor = mains[2]  # the tuple the brief names
    assert lo[0] <= S[0] <= hi[0] and S[0] > floor[0]


def test_coarse_cancellation_keeps_the_fine_share_detected():
    """Case 11, the fine half: Y = sin(8π·x₁) + ε on 17 values of x₁ cancels inside the coarse
    q = 4 bins (Task 5), while the fine S₁ clears its family floor."""
    frame = stat_frame(
        d=D,
        values=[SINE_VALUES] + [VALUES] * (D - 1),
        seed=SEED,
        y=lambda u: np.sin(8.0 * math.pi * u[:, 0]),
    )
    fine = Fine(cohort_of(frame))
    assert fine.detected_mains()[0]
    assert fine.lo_S[0] > fine.floor_S[0]


def test_refinement_rows_excluded():
    """Adding 2,000 `design == "adaptive"` rows (a different surface) changes no share."""
    base = stat_frame(d=D, values=VALUES, seed=SEED, y=lambda u: 3.0 * u[:, 0])
    refine = stat_frame(
        d=D, values=VALUES, n=2_000, seed=SEED + 1, y=lambda u: 5.0 * u[:, 1], design="adaptive"
    )
    alone, both = cohort_of(base), cohort_of(stack_frames(base, refine))
    assert both.n == alone.n == both.n_uniform_total == 5_000
    for ours, theirs in zip(
        fine_shares(both.X, both.Y, both.B), fine_shares(alone.X, alone.Y, alone.B), strict=True
    ):
        assert np.array_equal(ours, theirs)


def test_interval_coverage_known_variance():
    """For Y = a·x₁ + ε the true share is a²·Var(x₁) / (a²·Var(x₁) + σ²), Var(x₁) the variance
    of the uniform lattice in [0, 1]; the 90 % interval covers it in at least 85 of 100 seeds.
    a = 1 puts the true share at 0.30, away from both 0 (clamping) and 1."""
    a = 1.0
    var_x = (VALUES + 1) / (12.0 * (VALUES - 1))
    true = a * a * var_x / (a * a * var_x + SIGMA**2)
    covered = 0
    for seed in range(1, 101):
        c = cohort_of(stat_frame(d=2, values=VALUES, seed=seed, y=lambda u: a * u[:, 0]), seed=seed)
        fn = FineTerms(c.B, pairs=False)
        lo, hi = intervals(fn, c.X, c.Y, b=BOOTSTRAP_B, seed=seed, checkpoint=no_checkpoint)
        covered += bool(lo[0] <= true <= hi[0])
    assert covered >= 85, covered


def test_permutation_floor_scales_with_bins():
    """Pure noise on the same n: the per-share and the family floors of every main and every
    increment are higher at 20 values per parameter than at 4."""

    def floors_at(values: int):
        c = cohort_of(stat_frame(d=D, values=values, seed=SEED, y=zero))
        found = floors(
            FineTerms(c.B),
            c.X,
            c.Y,
            p=PERMUTATION_P,
            seed=SEED,
            checkpoint=no_checkpoint,
            families=fine_families(D),
        )
        S_share, _, D_share = fine_parts(found.share)
        S_family, _, D_family = fine_parts(found.family)
        off = ~np.eye(D, dtype=bool)
        return S_share, S_family, D_share[off], D_family[off]

    for wide, narrow in zip(floors_at(20), floors_at(4), strict=True):
        assert (wide > narrow).all()


def test_family_floors_control_false_detections(capsys):
    """Pure noise, d = 20, 5,000 rows, seeds 1-20: at most 4 seeds show any detection in the
    mains or the Δ family (≈ 2 expected: two families at 5 % each). The per-share floors flag many
    more parameters (review B1), printed beside the rate."""
    seeds = range(1, 21)
    detecting, per_share = 0, []
    for seed in seeds:
        frame = stat_frame(d=D_WIDE, values=VALUES, seed=seed, y=zero)
        fine = Fine(cohort_of(frame, seed=seed), seed=seed, bounds=False)
        detecting += bool(fine.detected_mains().any() or fine.detected_increments().any())
        ticked = (fine.S > fine.tick_S) | ((fine.D > fine.tick_D) & fine.pairs).any(axis=1)
        per_share.append(int(ticked.sum()))
    with capsys.disabled():
        print(
            f"\nfamily-wise false detections: {detecting} of {len(seeds)} seeds "
            f"({detecting / len(seeds):.0%}); per-share floors flag {np.mean(per_share):.1f} of "
            f"{D_WIDE} parameters per seed (min {min(per_share)}, max {max(per_share)})"
        )
    assert detecting <= 4


def test_recentred_intervals_cover_the_point_estimate():
    """Every share's interval contains its point estimate (re-centred, decision 19), and on pure
    noise every main's interval contains 0."""
    signal = stat_frame(d=D, values=VALUES, seed=SEED, y=lambda u: 3.0 * u[:, 0] + xor(u[:, 1:3]))
    noise = Fine(cohort_of(stat_frame(d=D, values=VALUES, seed=SEED, y=zero)))
    for fine in (Fine(cohort_of(signal)), noise):
        assert (fine.lo <= fine.terms).all() and (fine.terms <= fine.hi).all()
    assert (noise.lo_S <= 0.0).all() and (noise.hi_S >= 0.0).all(), (noise.lo_S, noise.hi_S)


def test_cohort_subsamples_to_the_cap():
    """60,000 cohort rows: a seeded subsample of IMPORTANCE_ROWS, stated, the same for the same
    seed and another for another."""
    frame = stat_frame(d=2, values=VALUES, n=60_000, seed=SEED, y=lambda u: 3.0 * u[:, 0])
    c = cohort_of(frame)
    assert c.n == IMPORTANCE_ROWS == 50_000 == len(c.Y) == len(c.X)
    assert c.sampled_from == 60_000 and c.n_uniform_total == 60_000 and c.seed == SEED
    again, other = cohort_of(frame), cohort_of(frame, seed=SEED + 1)
    assert np.array_equal(again.X, c.X) and np.array_equal(again.Y, c.Y)
    assert not np.array_equal(other.Y, c.Y)
    whole = cohort_of(stat_frame(d=2, values=VALUES, seed=SEED, y=zero))
    assert whole.sampled_from is None and whole.n == 5_000


# --- the definitions behind them --------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "blocks", "scatters"),
    [
        # [x₁ x₂ x₃], [x₄], [x₅]: inner pairs, and a 70-value parameter alone and sparse.
        ([3, 4, 5, 7, 70], [[0, 1, 2], [3], [4]], 6),
        # Two blocks of three: cross pairs between multi-member blocks (the 8-value shape).
        ([4] * 6, [[0, 1, 2], [3, 4, 5]], 3),
        # A 64-cell block beside 300 values exceeds JOINT_CELLS: its cross pairs one by one.
        ([4, 4, 4, 300], [[0, 1, 2], [3]], 5),
    ],
)
def test_fine_shares_match_the_definition(values, blocks, scatters):
    """The adjusted count-weighted η² by brute force: a main over its observed values, a pair over
    its cells holding rows (B_i·B_j when all are tested); and a weighted call equals the same rows
    repeated (a bootstrap resample). Each value list makes another block shape."""
    d = len(values)
    frame = stat_frame(
        d=d,
        values=values,
        n=1_000,
        seed=SEED,
        y=lambda u: u[:, 0] * u[:, 1] + np.sin(6.0 * u[:, -1]) + u[:, -2] * u[:, 2],
    )
    c = cohort_of(frame)
    assert parameter_blocks(c.B) == blocks
    assert len(design_of(c.X, c.B).scatters) == scatters
    X, Y = c.X.astype(int), c.Y

    def adjusted(groups) -> float:
        n, mean = len(Y), Y.mean()
        cells = {}
        for g, y in zip(groups, Y, strict=True):
            cells.setdefault(g, []).append(y)
        between = sum(len(v) * (np.mean(v) - mean) ** 2 for v in cells.values())
        s = between / ((Y - mean) ** 2).sum()
        k = len(cells)
        return max(0.0, s - (k - 1) / (n - k) * (1 - s))

    S, J = fine_shares(c.X, c.Y, c.B)
    for i in range(d):
        assert S[i] == pytest.approx(adjusted(X[:, i].tolist()), abs=1e-12)
        for j in range(d):
            expected = S[i] if i == j else adjusted(list(zip(X[:, i], X[:, j], strict=True)))
            assert J[i, j] == pytest.approx(expected, abs=1e-12)
    delta, inter = incremental(S, J), interaction(S, J)
    assert delta[0, 1] == pytest.approx(J[0, 1] - S[1]) and delta[1, 1] == 0.0
    assert inter[0, 1] == pytest.approx(J[0, 1] - S[0] - S[1]) and inter[2, 2] == 0.0
    rng = np.random.default_rng(7)
    w = np.bincount(rng.integers(0, len(Y), len(Y)), minlength=len(Y)).astype(float)
    rows = np.repeat(np.arange(len(Y)), w.astype(int))
    fn = FineTerms(c.B)
    assert np.allclose(fn(c.X, c.Y, w), fn(c.X[rows], c.Y[rows]), atol=1e-12)


def test_cohort_counts_missing_over_every_block():
    """Block 0 decides inclusion and every block must be `ok` with a finite metric; each excluded
    configuration counts once, by block 0's reason, else its first failing block's. Design rows
    (for aliasing) keep every uniform configuration; `max_drawdown` is negated; a blocked
    experiment's block-0 frame is refused."""
    frame = stat_frame(
        d=3, values=4, n=40, seed=SEED, y=lambda u: u[:, 0], blocks={1: zero, 2: zero}
    )
    table = frame.table
    trial = table.column("trial_no").to_numpy()
    block = table.column("block").to_numpy()
    status = np.array(["ok"] * table.num_rows, dtype=object)
    value = np.asarray(table.column("combined.net_pnl").to_numpy(), dtype=float).copy()
    status[(trial == 0) & (block == 0)] = "invalid"
    status[(trial == 1) & (block == 2)] = "failed"
    status[(trial == 2) & (block == 1)] = "invalid"  # first failing block wins over block 2's
    value[(trial == 2) & (block == 2)] = np.nan
    value[(trial == 3) & (block == 0)] = np.inf
    status[(trial == 3) & (block == 1)] = "failed"  # block 0's reason first
    words = pa.array(status.tolist(), pa.string()).dictionary_encode()
    table = table.set_column(table.schema.get_field_index("status"), "status", words)
    table = table.set_column(
        table.schema.get_field_index("combined.net_pnl"), "combined.net_pnl", pa.array(value)
    )
    keep = ~((trial == 4) & (block == 1))  # trial 4 lost its block-1 row: a failed evaluation
    edited = replace(frame, table=table.filter(pa.array(keep)))
    c = cohort_of(edited)
    assert c.missing == {"invalid": 2, "failed": 2, "undefined": 1}
    with pytest.raises(TypeError):
        c.missing["invalid"] = 0
    with pytest.raises(TypeError):
        c.blocks[1] = c.Y
    assert c.n == 35 and c.n_uniform_total == 40 and len(c.X_uniform) == 40
    assert sorted(c.blocks) == [1, 2] and all(len(y) == 35 for y in c.blocks.values())
    assert c.invalid_share == 0.0 and c.metric == METRIC and c.scope == SCOPE
    assert c.X.dtype == np.int16 and list(c.B) == [4, 4, 4]
    drawdown = cohort(frame, metric="max_drawdown", scope=SCOPE, seed=SEED)
    net = cohort_of(frame)
    assert np.array_equal(drawdown.Y, -net.Y)
    with pytest.raises(ValueError, match="ALL_BLOCKS"):
        cohort_of(replace(frame, selection=BLOCK0))


def test_resamples_call_the_checkpoint():
    """Every bootstrap and permutation calls the checkpoint first, so a cancelled task stops
    between resamples."""
    c = cohort_of(stat_frame(d=2, values=VALUES, n=200, seed=SEED, y=zero))
    fn = FineTerms(c.B, pairs=False)
    calls = []
    intervals(fn, c.X, c.Y, b=7, seed=SEED, checkpoint=lambda: calls.append("b"))
    floors(
        fn,
        c.X,
        c.Y,
        p=5,
        seed=SEED,
        checkpoint=lambda: calls.append("p"),
        families={MAINS: np.ones(2, dtype=bool)},
    )
    assert calls == ["b"] * 7 + ["p"] * 5

    def cancelled_at_the_third() -> None:
        calls.append("c")
        if calls.count("c") == 3:
            raise Cancelled

    with pytest.raises(Cancelled):
        intervals(fn, c.X, c.Y, b=BOOTSTRAP_B, seed=SEED, checkpoint=cancelled_at_the_third)
    assert calls.count("c") == 3


def test_intervals_are_recentred_on_the_point_estimate_exactly():
    """`lo = θ̂ + q₀.₀₅* - mean*` and `hi = θ̂ + q₀.₉₅* - mean*` over the very draws `intervals`
    made: its first call is the point estimate (no weights), each later one a resample of the n
    rows as multiplicities."""
    c = cohort_of(stat_frame(d=3, values=VALUES, n=500, seed=SEED, y=lambda u: u[:, 0]))
    fn = FineTerms(c.B)
    seen = []

    def recorded(X, Y, w=None):
        seen.append((w, fn(X, Y, w)))
        return seen[-1][1]

    lo, hi = intervals(recorded, c.X, c.Y, b=50, seed=SEED, checkpoint=no_checkpoint)
    (first, theta), *rest = seen
    assert first is None and len(rest) == 50
    assert all(w.sum() == len(c.Y) and (w == np.round(w)).all() for w, _ in rest)
    draws = np.stack([value for _, value in rest])
    q05, q95 = np.quantile(draws, [0.05, 0.95], axis=0)
    mean = draws.mean(axis=0)
    assert np.array_equal(lo, q05 + (theta - mean)) and np.array_equal(hi, q95 + (theta - mean))
    assert np.allclose(lo, theta + q05 - mean, rtol=0, atol=1e-15)
    assert np.allclose(hi, theta + q95 - mean, rtol=0, atol=1e-15)


def test_family_floor_is_max_t_over_its_members():
    """`family` = mean + t·sd over the permutations, t the 95th percentile of each permutation's
    largest share in the family, each standardized leave-one-out by the null mean and SD of the
    other permutations (Ruling P10); the families never overlap."""
    c = cohort_of(stat_frame(d=4, values=VALUES, n=1_000, seed=SEED, y=zero))
    fn = FineTerms(c.B)
    families = fine_families(4)
    seen = []

    def recorded(X, Y, w=None):
        seen.append(fn(X, Y, w))
        return seen[-1]

    found = floors(recorded, c.X, c.Y, p=60, seed=SEED, checkpoint=no_checkpoint, families=families)
    null = np.stack(seen)
    assert null.shape == (60, 9, 4)
    assert np.allclose(found.share, np.quantile(null, 0.95, axis=0))
    for name in (MAINS, INCREMENTS):
        members = null[:, families[name]]
        mean, sd = members.mean(axis=0), members.std(axis=0, ddof=1)
        others = [np.delete(members, r, axis=0) for r in range(len(members))]
        loo = [
            (members[r] - rest.mean(axis=0)) / rest.std(axis=0, ddof=1)
            for r, rest in enumerate(others)
        ]
        t = np.quantile(np.max(loo, axis=1), 0.95)
        assert found.t[name] == pytest.approx(t)
        assert np.allclose(found.family[families[name]], mean + t * sd)
        in_sample = np.quantile(((members - mean) / sd).max(axis=1), 0.95)
        assert t > in_sample  # in-sample standardization shrinks the maxima that set t
    assert np.isnan(fine_parts(found.family)[1]).all()  # J is in no family
    with pytest.raises(ValueError, match="family"):
        floors(
            fn,
            c.X,
            c.Y,
            p=4,
            seed=SEED,
            checkpoint=no_checkpoint,
            families={"a": families[MAINS], "b": families[MAINS]},
        )


def test_aliasing_reads_every_uniform_configuration():
    """Cramér's V reads every uniform configuration, never the cohort, so outcome-dependent
    missingness never shows as aliasing (case 16).

    - Case 16's pattern, `profit_factor` undefined exactly when x₁ is high and x₂ low, drops a
      quarter of the cohort; with `net_pnl` nothing is missing.
    - A band pattern, undefined unless x₁ and x₂ are within one value, leaves a cohort whose x₁ and
      x₂ are aliased (V ≈ 0.53), while the uniform configurations show no aliasing."""
    quadrant = stat_frame(
        d=D,
        values=VALUES,
        seed=SEED,
        y=lambda u: 3.0 * u[:, 0],
        undefined=lambda u: high(u[:, 0]) & ~high(u[:, 1]),
    )
    c = cohort_of(quadrant, metric="profit_factor")
    assert c.missing["invalid"] == c.missing["failed"] == 0
    assert c.n + c.missing["undefined"] == c.n_uniform_total == 5_000
    assert aliased(cramers_v(c.X_uniform, c.B)) == []
    assert cohort_of(quadrant).missing == {"invalid": 0, "failed": 0, "undefined": 0}
    band = stat_frame(
        d=D,
        values=VALUES,
        seed=SEED,
        y=lambda u: 3.0 * u[:, 0],
        undefined=lambda u: np.abs(u[:, 0] - u[:, 1]) > 0.2,
    )
    c = cohort_of(band, metric="profit_factor")
    assert (0, 1) in aliased(cramers_v(c.X, c.B))
    assert aliased(cramers_v(c.X_uniform, c.B)) == []


def test_pair_quality_reads_cells_and_balance():
    """Coverage is the share of a pair's B_i·B_j cells with at least PAIR_MIN_N rows; balance is
    the TVD of its cells from uniform."""
    X = np.array([[0, 0]] * 4 + [[0, 1]] * 4 + [[1, 0]] * 3 + [[1, 1]] * 1, dtype=np.int16)
    coverage, balance = pair_quality(X, np.array([2, 2]))
    assert coverage[0, 1] == coverage[1, 0] == 0.5
    expected = 0.5 * (abs(4 / 12 - 0.25) * 2 + abs(3 / 12 - 0.25) + abs(1 / 12 - 0.25))
    assert balance[0, 1] == pytest.approx(expected)


def test_stat_frame_writes_valid_cells_blocks_and_undefined_rows():
    """The fixture itself: the valid cells counted over the grid, block rows beside block 0 in
    canonical order, `undefined` nulling the undefinable metrics only."""
    frame = stat_frame(
        d=3,
        values=4,
        n=300,
        seed=SEED,
        y=zero,
        blocks={1: zero},
        valid=lambda u: u[:, 1] >= u[:, 0],
        undefined=lambda u: u[:, 2] > 0.5,
    )
    assert frame.space == 64 and frame.valid == 40 and frame.blocks == 1
    table = frame.table
    assert table.column("block").to_pylist()[:4] == [0, 1, 0, 1]
    assert table.column("trial_no").to_pylist()[:4] == [0, 0, 1, 1]
    x0, x1 = (table.column(p.path).to_numpy() for p in frame.parameters[:2])
    assert (x1 >= x0).all()
    pf = table.column("combined.profit_factor")
    assert 0 < pf.null_count < table.num_rows and table.column("combined.net_pnl").null_count == 0


# --- Task 5: the coarse decomposition, availability, the veto and the recommended statuses -----

SEEDS = (1, 2, 3)
VETO_TEXT = "structure not captured by mains, pairs and triples: deprioritization unsafe"
VETO_WARNING = "unexplained share high: noise or higher-order structure"
PRODUCT_HINT = "freeze or narrow the constrained ranges"
METRIC_HINT = (
    "choose a metric defined everywhere (net_pnl, max_drawdown, trade_count, exposure) "
    "or retry the failed trials"
)


def at_seeds(flips=None):
    """Seeds 1, 2 and 3 (Ruling P9). A (case, seed) in `flips` is a strict xfail whose reason
    carries its numbers: visible in every run, never deleted, loosened or re-seeded."""
    flips = flips or {}
    params = []
    for seed in SEEDS:
        marks = ()
        if seed in flips:
            marks = pytest.mark.xfail(strict=True, reason=f"R3.5 finding: {flips[seed]}")
        params.append(pytest.param(seed, id=f"seed{seed}", marks=marks))
    return params


def sparse_present(u):
    """Case 6's validity: every fifth of x₁'s 40 values, so 8 are present."""
    return value_index(u[:, 0], SPARSE_VALUES) % (SPARSE_VALUES // SPARSE_PRESENT) == 0


def _case(**kwargs):
    defaults = {"d": D, "values": VALUES}
    return lambda seed: stat_frame(seed=seed, **{**defaults, **kwargs})


# The §20 experiments, each a function of the seed. Case 13's experiment is case 1's (independent
# inputs, Y = 3·x₁ + ε, 20,000 rows), so case 13 reads "01".
CASES = {
    "01": _case(n=PROPOSAL_ROWS, y=first_order),
    "01@5000": _case(y=first_order),
    "02": _case(y=xor_pair),
    "03": _case(y=parity(3)),
    "04": _case(y=first_order, draw=aliased_rows),
    "05": _case(y=uneven_effect, draw=uneven_rows),
    "06": _case(values=[SPARSE_VALUES] + [VALUES] * (D - 1), y=first_order, valid=sparse_present),
    "07": _case(d=D_WIDE, y=zero),
    "08": _case(y=first_order, blocks={1: zero, 2: first_order, 3: zero, 4: zero}),
    "09": _case(y=hinge),
    "09-child": _case(values=[CHILD_VALUES] + [VALUES] * (D - 1), y=child_hinge),
    "10": _case(y=first_order, valid=two_apart),
    "11": _case(values=[SINE_VALUES] + [VALUES] * (D - 1), y=sine),
    "12": _case(y=parity(4)),
    "14": _case(values=[BINARY] * 4 + [VALUES] * (D - 4), y=parity_bit, valid=parity_table),
    "15": _case(y=first_order, valid=one_cell_skipped),
    "16": _case(y=first_order, undefined=quadrant),
    "faint": _case(n=PROPOSAL_ROWS, y=faint_second),
}


@functools.cache
def assessed(case, seed, metric=METRIC):
    """`(frame, cohort, result)` of a case at a seed, the data's and the analysis', computed once
    per session."""
    frame = CASES[case](seed)
    c = cohort_of(frame, metric=metric, seed=seed)
    return frame, c, assess(c, seed=seed, checkpoint=no_checkpoint)


def by_path(result):
    return {s.path: s for s in statuses(result)}


@pytest.mark.parametrize("seed", at_seeds())
def test_case01_strong_first_order(seed):
    """Case 1 on 20,000 rows (decision 20): Y = 3·x₁ + ε. x₁ is `Active · detected`, its S₁
    upper bound far above θ_min; every noise parameter is `Deprioritized · proposable`."""
    _, _, result = assessed("01", seed)
    found = by_path(result)
    first, *noise = result.paths
    assert result.availability.available and result.veto is None
    assert found[first].status == "Active · detected" and not found[first].proposable
    assert fine_parts(result.fine.hi)[0][0] > 10 * THETA_MIN
    for path in noise:
        assert found[path].status == "Deprioritized · proposable", found[path]
        assert found[path].proposable and found[path].failing is None


@pytest.mark.parametrize("seed", at_seeds())
def test_case01_at_5000_rows_proposes_nothing_honestly(seed, capsys):
    """Case 1 on §20's 5,000 rows, the brief's companion with Ruling P11's (amended) assertion.
    A noise own-direction increment's upper bound sits ≈ 0.004 above its point at 5,000 rows, so
    the rule proposes a seed-dependent subset of the noise parameters, each with every bound below
    θ_min; it never detects one. x₁ is `Active · detected` and not proposable; every noise
    parameter not proposed is blocked by a practical bound on a pair or a triple: its `failing`
    names condition 2 or 3. The proposable counts are printed."""
    _, _, result = assessed("01@5000", seed)
    found = by_path(result)
    first, *noise = result.paths
    assert found[first].status == "Active · detected" and not found[first].proposable
    for path in noise:
        s = found[path]
        assert s.status in {"Active · not detected", "Deprioritized · proposable"}, s
        assert s.proposable or re.match(r"not proposable: condition [23] \(", s.failing), s
    proposed = sum(found[path].proposable for path in noise)
    with capsys.disabled():
        print(f"\ncase 1 at 5,000 rows, seed {seed}: {proposed} of {len(noise)} noise proposable")


@pytest.mark.parametrize("seed", at_seeds())
def test_case02_xor(seed):
    """Case 2: Y = 2·[(x₁ > m) XOR (x₂ > m)] + ε. Both mains stay within their family floor and
    both parameters are `Investigate · interaction not ruled out`, never proposable; `failing`
    names the real cause, condition 2's increment beyond the other (a non-candidate's missing
    coarse bound never stands in for it)."""
    _, _, result = assessed("02", seed)
    found = by_path(result)
    S = fine_parts(result.fine.terms)[0]
    floor = fine_parts(result.fine.floors.family)[0]
    assert (S[:2] <= floor[:2]).all(), (S[:2], floor[:2])
    for path, other in zip(result.paths[:2], result.paths[1::-1], strict=True):
        assert found[path].status == "Investigate · interaction not ruled out", found[path]
        assert not found[path].proposable
        assert found[path].failing.startswith(
            f"not proposable: condition 2 (Δ beyond {other} upper"
        ), found[path]


@pytest.mark.parametrize("seed", at_seeds())
def test_case03_three_way_only(seed):
    """Case 3: Y = 2·parity(x₁ > m, x₂ > m, x₃ > m) + ε. No main or pair is detected; the coarse
    triple's own increments are, so all three are `Investigate · three-way effect not ruled
    out`."""
    _, _, result = assessed("03", seed)
    found = by_path(result)
    for path in result.paths[:3]:
        assert found[path].status == "Investigate · three-way effect not ruled out", found[path]
        assert not found[path].proposable


@pytest.mark.parametrize("seed", at_seeds())
def test_case04_aliased(seed):
    """Case 4: x₂ = x₁ + a small jitter, Y = 3·x₁ + ε. Both carry `aliased · credit shared with`
    the other; neither is proposable; the rule is unavailable: `aliased inputs`."""
    _, _, result = assessed("04", seed)
    found = by_path(result)
    a, b = result.paths[:2]
    assert result.availability.reason == "aliased inputs"
    assert f"aliased · credit shared with {b}" in found[a].flags
    assert f"aliased · credit shared with {a}" in found[b].flags
    assert not found[a].proposable and not found[b].proposable
    assert found[a].failing == found[b].failing == "aliased inputs"


@pytest.mark.parametrize("seed", at_seeds())
def test_case05_uneven_sampling(seed):
    """Case 5 (§20's generator, Ruling P7): P(x₁ = v) ∝ v with x₃ following x₁;
    Y = 3·x₂ + x₁·x₂ + ε. The (x₁, x₂) squares are flagged `confounded` (by x₃), x₁ is not
    proposable, and condition 2 fails on the pair (x₁, x₂): Δ_{1|2} upper > θ_min."""
    frame, _, result = assessed("05", seed)
    paths = result.paths
    matrix = matrix_view(
        frame, LabFilter(), rows=paths[0], cols=paths[1], metric=METRIC, mode="aggregate"
    )
    flagged = [s["confounded"] for row in matrix["stats"] for s in row if s and s["confounded"]]
    assert flagged and all(paths[2] in names for names in flagged)
    assert not by_path(result)[paths[0]].proposable
    assert fine_parts(result.fine.hi)[2][0, 1] > THETA_MIN
    assert any(c.startswith(f"condition 2 (Δ beyond {paths[1]}") for c in conditions(result, 0))


@pytest.mark.parametrize("seed", at_seeds())
def test_case06_sparse_coverage(seed):
    """Case 6: x₁ has 40 values, 8 of them present: `Insufficient coverage · unresolved`, listed
    last with its coverage, never proposable."""
    _, _, result = assessed("06", seed)
    listed = statuses(result)
    last = listed[-1]
    assert last.path == result.paths[0]
    assert last.status == "Insufficient coverage · unresolved"
    assert last.label == "Insufficient coverage" and not last.proposable
    assert last.reason == "coverage: 8 of 40 values hold ≥ 20 rows; n = 5,000 (needs 1,200)"
    assert all(s.label == "Measured" for s in listed[:-1])


@pytest.mark.parametrize("seed", at_seeds())
def test_case07_pure_noise(seed):
    """Case 7: Y = ε over 20 parameters. Every status is `Active · not detected`; the residual
    veto is raised with its text and its warning, and names every parameter's `failing`; nothing
    is proposed. (Its coarse triple family holds 3,420 increments: the leave-one-out max-T floor,
    Ruling P10, keeps them undetected at COARSE_PERMUTATION_P = 50.)"""
    _, _, result = assessed("07", seed)
    listed = statuses(result)
    assert len(listed) == D_WIDE
    assert [s.status for s in listed] == ["Active · not detected"] * D_WIDE, [
        (s.path, s.status, s.reason) for s in listed if s.status != "Active · not detected"
    ]
    assert result.veto == VETO_TEXT and VETO_WARNING in result.warnings
    assert result.coarse.lo > RESIDUAL_VETO
    assert not any(s.proposable for s in listed)
    assert all(s.failing == VETO_TEXT for s in listed)


@pytest.mark.parametrize("seed", at_seeds())
def test_case08_one_block_regime(seed):
    """Case 8: Y = 3·x₁ in block 2 only and 0 (plus ε) in the other blocks, blocks = 4. x₁ is
    `Investigate · period-dependent`, never proposable."""
    _, _, result = assessed("08", seed)
    found = by_path(result)[result.paths[0]]
    assert found.status == "Investigate · period-dependent", found
    assert not found.proposable


@pytest.mark.parametrize("seed", at_seeds())
def test_case09_range_change(seed):
    """Case 9: Y = 3·max(0, x₁ - 0.8·range) + ε. On the wide range x₁ is detected; the re-screen
    on x₁ ∈ [0, 0.7·range] makes the wide-range evidence `stale: ranges changed`, and the
    child's fresh S₁ is within its floor."""
    parent_frame, parent_c, parent = assessed("09", seed)
    child_frame, child_c, child = assessed("09-child", seed)
    assert by_path(parent)[parent.paths[0]].status == "Active · detected"
    evidence = evidence_scope(scope_document(parent_frame), parent_c)
    current = evidence_scope(scope_document(child_frame), child_c)
    assert compare_scope(evidence, current) == "stale: ranges changed"
    S = fine_parts(child.fine.terms)[0]
    floor = fine_parts(child.fine.floors.family)[0]
    assert S[0] <= floor[0], (S[0], floor[0])


@pytest.mark.parametrize("seed", at_seeds())
def test_case10_correlated_inputs(seed):
    """Case 10: a validity constraint x₂ ≥ x₁ + 2 correlates the design; Y = 3·x₁ + ε. Both carry
    `aliased · credit shared`, the rule is unavailable (`aliased inputs`, before the product
    design's reason) and no parameter is proposable."""
    _, _, result = assessed("10", seed)
    found = by_path(result)
    a, b = result.paths[:2]
    assert result.availability.reason == "aliased inputs"
    assert f"aliased · credit shared with {b}" in found[a].flags
    assert f"aliased · credit shared with {a}" in found[b].flags
    assert not any(s.proposable for s in found.values())


@pytest.mark.parametrize("seed", at_seeds())
def test_case11_coarse_bin_cancellation(seed):
    """Case 11: Y = sin(8π·x₁ / range) + ε on 17 values. The coarse S₁^c is ≈ 0 (it cancels in
    every q = 4 bin) while the fine S₁ is large, so condition 1 fails on the fine grid and x₁
    stays `Active · detected`."""
    _, _, result = assessed("11", seed)
    assert abs(result.coarse.S[0]) < THETA_MIN, result.coarse.S[0]
    assert fine_parts(result.fine.terms)[0][0] > 0.5
    assert by_path(result)[result.paths[0]].status == "Active · detected"
    assert conditions(result, 0)[0].startswith("condition 1 (fine S upper")


@pytest.mark.parametrize("seed", at_seeds())
def test_case12_higher_order(seed):
    """Case 12: Y = 2·parity(x₁ > m, …, x₄ > m) + ε, which no main, pair or triple captures. The
    residual's lower bound exceeds RESIDUAL_VETO: the veto is raised and nothing is proposed."""
    _, _, result = assessed("12", seed)
    assert result.coarse.lo > RESIDUAL_VETO
    assert result.veto == VETO_TEXT and VETO_WARNING in result.warnings
    assert not any(s.proposable for s in statuses(result))


@pytest.mark.parametrize("seed", at_seeds())
def test_case13_own_direction_triple(seed):
    """Case 13 on 20,000 rows: independent inputs, Y = 3·x₁ + ε. In the triple (x₁, x₂, x₃)
    Δ_{1|23}^c > 0.5 while Δ_{2|13}^c ≈ 0: x₂ reads its own direction only and is
    `Deprioritized · proposable`."""
    _, _, result = assessed("01", seed)
    assert result.coarse.Delta3[0, 1, 2] > 0.5
    assert abs(result.coarse.Delta3[1, 0, 2]) < THETA_MIN
    found = by_path(result)[result.paths[1]]
    assert found.status == "Deprioritized · proposable" and found.proposable


@pytest.mark.parametrize("seed", at_seeds())
def test_case14_pairwise_independent_jointly_dependent(seed):
    """Case 14: three independent binary inputs and x₄ = x₁ XOR x₂ XOR x₃, defined by a validity
    table: pairwise independent (no aliasing), jointly dependent. The rule is unavailable because
    the inputs are not a product design, while the fine lists still have their entries."""
    _, _, result = assessed("14", seed)
    assert result.aliased_pairs == []
    reason = result.availability.reason
    assert reason.startswith("inputs are not a product design")
    assert reason == "inputs are not a product design (50 % of the grid is invalid)"
    assert result.availability.hint == PRODUCT_HINT
    S = fine_parts(result.fine.terms)[0]
    assert np.isfinite(S).all() and len(statuses(result)) == D
    assert by_path(result)[result.paths[3]].status == "Active · detected"


@pytest.mark.parametrize("seed", at_seeds())
def test_case15_weak_constraint(seed):
    """Case 15: a validity constraint skipping one (x₁, x₂) cell of 64 is not aliased, yet the
    inputs are not a product design: `2 %` with the hint to freeze or narrow."""
    _, _, result = assessed("15", seed)
    assert result.aliased_pairs == []
    assert (
        result.availability.reason == "inputs are not a product design (2 % of the grid is invalid)"
    )
    assert result.availability.hint == PRODUCT_HINT


@pytest.mark.parametrize("seed", at_seeds())
def test_case16_outcome_dependent_missingness(seed):
    """Case 16: `profit_factor` undefined exactly when x₁ is high and x₂ low. The reason prints
    the fixture's own count at every seed (Ruling P8: 1,189 at seed 1), and the descriptive
    estimates carry their note; with `net_pnl` the rule is available."""
    frame, _, result = assessed("16", seed, "profit_factor")
    positions = [frame.table.column(f"pos.{k}").to_numpy().astype(int) for k in (0, 1)]
    m = int(((positions[0] >= VALUES // 2) & (positions[1] < VALUES // 2)).sum())
    n = frame.table.num_rows
    expected = (
        f"{m:,} of {n:,} configurations have no finite profit_factor "
        f"(0 invalid, 0 failed, {m:,} undefined)"
    )
    assert result.availability.reason == expected
    assert result.availability.hint == METRIC_HINT
    assert result.note == f"on {n - m:,} of {n:,} configurations; missingness may bias"
    if seed == 1:
        assert expected == (
            "1,189 of 5,000 configurations have no finite profit_factor "
            "(0 invalid, 0 failed, 1,189 undefined)"
        )
        assert result.note == "on 3,811 of 5,000 configurations; missingness may bias"
    _, _, defined = assessed("16", seed, "net_pnl")
    assert defined.availability.available and defined.note is None


@pytest.mark.parametrize("seed", at_seeds())
def test_a_detected_but_negligible_share_stays_proposable(seed):
    """Decision 21 puts `Deprioritized · proposable` before `Active · detected` (review B1):
    Y = 3·x₁ + 0.15·x₂ + ε on 20,000 rows makes x₂'s share exceed its family floor while its
    upper bound stays below θ_min, so x₂ is proposable, not `Active · detected`."""
    _, _, result = assessed("faint", seed)
    S = fine_parts(result.fine.terms)[0]
    floor = fine_parts(result.fine.floors.family)[0]
    upper = fine_parts(result.fine.hi)[0]
    assert S[1] > floor[1] and upper[1] < THETA_MIN, (S[1], floor[1], upper[1])
    found = by_path(result)[result.paths[1]]
    assert found.status == "Deprioritized · proposable" and found.proposable


def test_rule_unavailable_when_aliased_or_adaptive():
    """Adaptive rows alone leave no uniform rows of the current space, the first reason; aliased
    inputs make the rule unavailable even on a fully valid grid."""
    adaptive = stat_frame(d=D, values=VALUES, n=500, seed=SEED, y=first_order, design="adaptive")
    c = cohort_of(adaptive)
    assert c.n_uniform_total == 0
    found = availability(c, cramers_v(c.X_uniform, c.B), math.nan, math.nan)
    assert not found.available and found.reason == "no uniform rows of the current space"
    assert found.hint is None
    result = assess(c, seed=SEED, checkpoint=no_checkpoint)
    listed = statuses(result)
    assert all(s.failing == "no uniform rows of the current space" for s in listed)
    _, aliased_c, aliased_result = assessed("04", SEED)
    assert aliased_c.invalid_share == 0.0
    assert aliased_result.availability.reason == "aliased inputs"


def test_stale_then_rescreen_refreshes_evidence():
    """Evidence from the wide range is stale on the narrow child; a re-screen's fresh uniform
    cohort on the child is `current`. A later snapshot, a new sampler revision or other data
    makes it stale again, naming the field."""
    parent_frame, parent_c, _ = assessed("09", SEED)
    child_frame, child_c, _ = assessed("09-child", SEED)
    document = scope_document(child_frame)
    current = evidence_scope(document, child_c)
    old = evidence_scope(scope_document(parent_frame), parent_c)
    assert compare_scope(old, current) == "stale: ranges changed"
    rescreen = CASES["09-child"](SEED + 10)  # a fresh uniform sample over the child's space
    fresh = evidence_scope(document, cohort_of(rescreen, seed=SEED + 10))
    assert compare_scope(fresh, current) == "current"
    later = replace(child_frame, snapshot=lab_store.Snapshot(1, 7))
    assert compare_scope(current, evidence_scope(document, cohort_of(later))) == (
        "stale: snapshot changed"
    )
    revised = evidence_scope(scope_document(child_frame, revision=2), child_c)
    assert compare_scope(current, revised) == "stale: sampler changed"
    moved = evidence_scope(scope_document(child_frame, sha256="sha-2"), child_c)
    assert compare_scope(current, moved) == "stale: data identity changed"


def test_compare_scope_reads_the_snapshot_by_its_watermark():
    """The rule the task cache and the label read: snapshots of one chunk watermark are one
    evidence (compaction leaves its canonical rows as they were), so a bare compaction reads
    `current`, either way round, though the scope still records its whole snapshot. A new chunk
    reads `stale: snapshot changed`, with or without a compaction, and so does a source without
    snapshots against one with them. Other fields are read as ever."""
    frame, c, _ = assessed("09-child", SEED)
    document = scope_document(frame)
    computed = evidence_scope(document, c)
    assert computed["snapshot"] == {"generation": 0, "chunk_watermark": 0}
    compacted = evidence_scope(
        document, cohort_of(replace(frame, snapshot=lab_store.Snapshot(1, 0)))
    )
    assert compacted["snapshot"] == {"generation": 1, "chunk_watermark": 0}
    assert compare_scope(computed, compacted) == "current"
    assert compare_scope(compacted, computed) == "current"
    for later in (lab_store.Snapshot(0, 1), lab_store.Snapshot(1, 1)):
        chunk = evidence_scope(document, cohort_of(replace(frame, snapshot=later)))
        assert compare_scope(computed, chunk) == "stale: snapshot changed"
        assert compare_scope(compacted, chunk) == "stale: snapshot changed"
    none = {**computed, "snapshot": None}
    assert compare_scope(none, dict(none)) == "current"
    assert compare_scope(none, computed) == "stale: snapshot changed"
    assert compare_scope(computed, none) == "stale: snapshot changed"
    revised = evidence_scope(scope_document(frame, revision=2), c)
    assert compare_scope(compacted, revised) == "stale: sampler changed"


def test_recentred_r_interval_contains_one_on_pure_noise():
    """Pure noise at d = 20: the residual's re-centred interval contains 1 (decision 19), and the
    coarse terms are unclamped (some noise shares are negative), so R is not biased down."""
    _, _, result = assessed("07", SEED)
    found = result.coarse
    assert found.lo <= 1.0 <= found.hi, (found.lo, found.R, found.hi)
    assert found.lo <= found.R <= found.hi
    assert (found.S < 0).any() and (found.T < 0).any()


def test_failing_is_set_on_every_non_proposable_parameter():
    """Every parameter that is not proposable names why: the availability reason when the rule
    is unavailable, else the veto, else its first failed §7.4a condition; a proposable one has
    none."""
    kinds = set()
    for case in ("01", "02", "04", "06", "07", "12"):
        _, _, result = assessed(case, SEED)
        for s in statuses(result):
            if s.proposable:
                assert s.failing is None and s.status == "Deprioritized · proposable"
                kinds.add("proposable")
            elif not result.availability.available:
                assert s.failing == result.availability.reason
                kinds.add("unavailable")
            elif result.veto is not None:
                assert s.failing == VETO_TEXT
                kinds.add("veto")
            else:
                named = conditions(result, result.paths.index(s.path))
                assert s.failing == f"not proposable: {named[0]}", s
                assert re.fullmatch(r"not proposable: condition [1-5] \(.+\)", s.failing), s
                assert "no interval" not in s.failing, s  # every candidate's bounds were drawn
                kinds.add("condition")
    assert kinds == {"proposable", "unavailable", "veto", "condition"}


# --- Task 5's definitions ---------------------------------------------------------------------


def test_coarse_bins_and_terms_match_the_definition():
    """The coarse bins are the lattice's q = 4 quantile bins (fewer values keep one bin each), and
    the coarse terms are the adjusted, unclamped η² of every main, pair and triple on them, the
    own-direction triple increments `Δ_{i|jk} = J_ijk - J_jk`, and
    `R = 1 - ΣS - ΣI_pair - ΣI_triple`; a weighted call equals the rows repeated."""
    values = [3, 8, 17, 2, 40]
    frame = stat_frame(
        d=5,
        values=values,
        n=1_000,
        seed=SEED,
        y=lambda u: u[:, 0] * u[:, 1] + np.sin(6.0 * u[:, 2]) + u[:, 3] * u[:, 4] * u[:, 1],
    )
    c = cohort_of(frame)
    X = c.X.astype(int)
    Xq = coarse_bins(c.X, c.B)
    bins = [X[:, 0], X[:, 1] // 2, X[:, 2] * 4 // 17, X[:, 3], X[:, 4] // 10]
    assert np.array_equal(Xq, np.stack(bins, axis=1)) and not Xq.flags.writeable
    q, Y = Xq.astype(int), c.Y

    def adjusted(*columns) -> float:
        n, mean = len(Y), Y.mean()
        cells = {}
        for key, y in zip(zip(*columns, strict=True), Y, strict=True):
            cells.setdefault(key, []).append(y)
        between = sum(len(v) * (np.mean(v) - mean) ** 2 for v in cells.values())
        s = between / ((Y - mean) ** 2).sum()
        k = len(cells)
        return s - (k - 1) / (n - k) * (1 - s)  # unclamped

    found = coarse(Xq, Y)
    d = len(values)
    S = np.array([adjusted(q[:, i]) for i in range(d)])
    J = np.array(
        [[adjusted(q[:, i], q[:, j]) if i != j else S[i] for j in range(d)] for i in range(d)]
    )
    T = {t: adjusted(*(q[:, i] for i in t)) for t in itertools.combinations(range(d), 3)}
    assert found.S == pytest.approx(S, abs=1e-12)
    assert np.allclose(found.J, J, atol=1e-12)
    assert np.allclose(found.D, incremental(S, J), atol=1e-12)
    assert [tuple(t) for t in found.triples] == list(T)
    assert np.allclose(found.T, list(T.values()), atol=1e-12)
    for (a, b, k), share in T.items():
        for i, (j, m) in ((a, (b, k)), (b, (a, k)), (k, (a, b))):
            assert found.Delta3[i, j, m] == pytest.approx(share - J[j, m], abs=1e-12)
            assert found.Delta3[i, m, j] == found.Delta3[i, j, m]
    assert np.isnan(found.Delta3[0, 0, 1]) and np.isnan(found.Delta3[0, 1, 1])
    assert (found.increments < 0).any()  # unclamped: below 0 where the brute force is
    I2 = sum(J[i, j] - S[i] - S[j] for i, j in itertools.combinations(range(d), 2))
    I3 = sum(
        share - J[a, b] - J[a, k] - J[b, k] + S[a] + S[b] + S[k] for (a, b, k), share in T.items()
    )
    assert found.R == pytest.approx(1.0 - S.sum() - I2 - I3, abs=1e-10)
    assert math.isnan(found.lo) and math.isnan(found.hi)
    rng = np.random.default_rng(7)
    w = np.bincount(rng.integers(0, len(Y), len(Y)), minlength=len(Y)).astype(float)
    rows = np.repeat(np.arange(len(Y)), w.astype(int))
    fn = CoarseTerms(Xq.max(axis=0) + 1)
    assert np.allclose(fn(Xq, Y, w), fn(Xq[rows], Y[rows]), atol=1e-12, equal_nan=True)


def test_coarse_intervals_bound_r_and_the_candidates_only():
    """The coarse bootstrap (B_c = 50 by default, its own stream) bounds R and, for each
    candidate, its coarse main, its increments beyond every other parameter and every triple
    containing it in all three directions; nothing else. The coarse null (P = 50) floors the
    triple increments, one family. Both call the checkpoint once per resample."""
    c = cohort_of(stat_frame(d=4, values=VALUES, n=800, seed=SEED, y=first_order))
    Xq = coarse_bins(c.X, c.B)
    calls = []
    bounds = coarse_intervals(Xq, c.Y, [2], b=7, seed=SEED, checkpoint=lambda: calls.append("b"))
    assert calls == ["b"] * 7
    point = coarse(Xq, c.Y)
    assert bounds.R_lo <= point.R <= bounds.R_hi
    others = [0, 1, 3]
    assert np.isfinite(bounds.S_hi[2]) and np.isnan(bounds.S_hi[others]).all()
    assert np.isfinite(bounds.D_hi[2, others]).all() and np.isnan(bounds.D_hi[others]).all()
    containing = (point.triples == 2).any(axis=1)
    assert np.isfinite(bounds.inc_hi[containing]).all()
    assert np.isnan(bounds.inc_hi[~containing]).all()
    assert bounds.candidates == (2,)
    found = coarse_floors(Xq, c.Y, p=6, seed=SEED, checkpoint=lambda: calls.append("p"))
    assert calls.count("p") == 6
    family = coarse_parts(found.family, 4)
    assert np.isfinite(family.increments).all() and np.isnan(family.S).all()
    assert math.isnan(family.R) and set(found.t) == {"triple increments"}
    defaults = {"b": coarse_intervals.__kwdefaults__["b"], "p": coarse_floors.__kwdefaults__["p"]}
    assert defaults == {"b": COARSE_BOOTSTRAP_B, "p": COARSE_PERMUTATION_P} == {"b": 50, "p": 50}
    shared_lo, _ = intervals(
        CoarseTerms(Xq.max(axis=0) + 1), Xq, c.Y, b=7, seed=SEED, checkpoint=no_checkpoint
    )
    assert shared_lo[0] != bounds.R_lo  # the coarse bootstrap draws its own resamples


def test_candidates_pass_conditions_1_and_2_on_point_estimates():
    """Candidates (§7.4) pass conditions 1 and 2 on their point estimates: the parity triple's
    members do, a strong main does not."""
    assert {0, 1, 2} <= set(candidates(assessed("03", SEED)[2]))
    assert 0 not in candidates(assessed("01@5000", SEED)[2])


def test_availability_reasons_in_order_and_their_strings():
    """The first failing reason wins, in the brief's order; `{p} %` is an integer at 1 % and
    above and one decimal below; counts carry thousands separators; the panel line reads
    `empirical deprioritization unavailable: <reason>`. The veto rises above RESIDUAL_VETO."""
    _, c, _ = assessed("02", SEED)
    V = cramers_v(c.X_uniform, c.B)
    clean = availability(c, V, 0.5, 0.1)
    assert clean.available and clean.reason is None and clean.reasons == [] and clean.hint is None
    assert clean.message is None

    def reason_of(**changes):
        return availability(replace(c, **changes), V, 0.5, 0.1)

    product = "inputs are not a product design ({} % of the grid is invalid)"
    assert reason_of(invalid_share=0.004).reason == product.format("0.4")
    assert reason_of(invalid_share=0.0156).reason == product.format("2")
    assert reason_of(invalid_share=0.35).hint == PRODUCT_HINT
    lost = MappingProxyType({"invalid": 3, "failed": 1_200, "undefined": 0})
    missing = reason_of(missing=lost, n_uniform_total=12_345, metric="mar")
    expected = (
        "1,203 of 12,345 configurations have no finite mar (3 invalid, 1,200 failed, 0 undefined)"
    )
    assert missing.reason == expected and missing.hint == METRIC_HINT
    assert missing.message == f"empirical deprioritization unavailable: {expected}"
    assert availability(c, V, -0.06, -0.2).reason == "decomposition inconsistent"
    assert availability(c, V, -0.05, -0.2).available
    tied = V.copy()
    tied[0, 1] = tied[1, 0] = 0.31
    broken = replace(c, invalid_share=0.004, missing=lost, n_uniform_total=12_345, metric="mar")
    everything = availability(broken, tied, -0.06, -0.2)
    assert everything.reasons == [
        "aliased inputs",
        product.format("0.4"),
        expected,
        "decomposition inconsistent",
    ]
    assert everything.reason == "aliased inputs" and everything.hint is None
    none = availability(replace(broken, n_uniform_total=0), tied, -0.06, -0.2)
    assert none.reason == "no uniform rows of the current space"
    assert veto(RESIDUAL_VETO + 1e-9) == VETO_TEXT
    assert veto(RESIDUAL_VETO) is None and veto(math.nan) is None


def test_a_constant_block_is_not_measured():
    """A block whose metric never varies has no shares: every parameter carries
    `not measured in block <b>`, and condition 1 fails there."""
    frame = stat_frame(
        d=3, values=4, n=2_000, seed=SEED, y=first_order, blocks={1: first_order, 2: zero}
    )
    table = frame.table
    block = table.column("block").to_numpy()
    column = "combined.net_pnl"
    value = np.asarray(table.column(column).to_numpy(), dtype=float).copy()
    value[block == 2] = 1.0
    table = table.set_column(table.schema.get_field_index(column), column, pa.array(value))
    c = cohort_of(replace(frame, table=table))
    result = assess(c, seed=SEED, checkpoint=no_checkpoint)
    assert result.availability.available and result.veto is None
    for i, s in enumerate(statuses(result)):
        assert "not measured in block 2" in s.flags
        assert "condition 1 (not measured in block 2)" in conditions(result, i)
        assert s.failing == "not proposable: condition 1 (not measured in block 2)"
    flat = stat_frame(d=3, values=4, n=2_000, seed=SEED, y=zero)
    column = flat.table.schema.get_field_index("combined.net_pnl")
    constant = flat.table.set_column(column, "combined.net_pnl", pa.array(np.ones(2_000)))
    result = assess(cohort_of(replace(flat, table=constant)), seed=SEED, checkpoint=no_checkpoint)
    for s in statuses(result):
        assert s.status == "Active · not detected" and s.reason == "not measured in block 0", s
        assert "not measured in block 0" in s.flags
        assert s.failing == "not proposable: condition 1 (not measured in block 0)"


def _with_fine(result, **parts):
    """`result` with some fine-stage arrays replaced: `terms`, `hi` or `floor`, each as a function
    of its (S, J, Δ) views of a copy."""
    fine = result.fine
    arrays = {"terms": fine.terms, "hi": fine.hi, "floor": fine.floors.family}
    copies = {}
    for name, array in arrays.items():
        copies[name] = array.copy()
        if name in parts:
            parts[name](*fine_parts(copies[name]))
    found = replace(fine.floors, family=copies["floor"])
    return replace(result, fine=replace(fine, terms=copies["terms"], hi=copies["hi"], floors=found))


def test_condition_2_reads_the_coarse_increment():
    """Condition 2 reads the coarse Δ_{i|j} as well as the fine one: with case 2's fine Δ of x₁
    below θ_min everywhere, its coarse increment beyond x₂ still fails it. x₁ is no candidate, so
    its coarse increment is read at its point estimate, and the reason says so (no `upper`)."""
    _, _, result = assessed("02", SEED)
    assert 0 not in result.coarse_bounds.candidates

    def quiet_row(S, J, D):
        D[0, :] = 0.0

    quiet = _with_fine(result, hi=quiet_row)
    named = conditions(quiet, 0)
    second = [c for c in named if c.startswith("condition 2 (")]
    path = result.paths[1]
    assert second and second[0].startswith(f"condition 2 (coarse Δ beyond {path} 0."), named
    assert "upper" not in second[0]


def test_rules_5_and_6_need_an_upper_bound_above_theta_min():
    """`Investigate · interaction not ruled out` and `Investigate · three-way effect not ruled out`
    need detection *and* an upper bound above θ_min: a detected increment whose upper bound is
    below θ_min leaves the parameter `Active · not detected`. On case 1 (20,000 rows) with the
    veto forced, so nothing is proposable, x₂ gets a detected fine Δ beyond x₃, then a detected
    own coarse increment, each with its upper bound below and then above θ_min."""
    _, _, base = assessed("01", SEED)
    base = replace(base, veto=VETO_TEXT)
    path = base.paths[1]
    assert by_path(base)[path].status == "Active · not detected"
    floor = fine_parts(base.fine.floors.family)[2][1, 2]
    assert 0 < floor < THETA_MIN / 2

    for upper, expected in ((THETA_MIN / 2, "Active · not detected"), (2 * THETA_MIN, None)):

        def detected(S, J, D):
            D[1, 2] = 2 * floor

        def bounded(S, J, D, upper=upper):
            D[1, 2] = upper

        found = by_path(_with_fine(base, terms=detected, hi=bounded))[path]
        assert found.status == (expected or "Investigate · interaction not ruled out"), found

    trios = base.coarse.triples
    t, position = (int(v) for v in np.argwhere(trios == 1)[0])
    inc_floor = coarse_parts(base.coarse_null.family, len(base.paths)).increments[t, position]
    assert 0 < inc_floor < THETA_MIN / 2
    for upper, expected in ((THETA_MIN / 2, "Active · not detected"), (2 * THETA_MIN, None)):
        increments = base.coarse.increments.copy()
        increments[t, position] = 2 * inc_floor
        inc_hi = base.coarse_bounds.inc_hi.copy()
        inc_hi[t, position] = upper
        tripled = replace(
            base,
            coarse=replace(base.coarse, increments=increments),
            coarse_bounds=replace(base.coarse_bounds, inc_hi=inc_hi),
        )
        found = by_path(tripled)[path]
        assert found.status == (expected or "Investigate · three-way effect not ruled out"), found


def test_importance_result_serialises_to_plain_json():
    """`to_json` holds plain JSON types only: lists for arrays, null for NaN, the statuses and the
    availability included."""
    _, _, result = assessed("08", SEED)
    plain = json.loads(json.dumps(result.to_json(), allow_nan=False))
    assert plain["paths"] == list(result.paths)
    assert [s["status"] for s in plain["statuses"]] == [s.status for s in statuses(result)]
    assert plain["availability"]["available"] is True
    assert sorted(plain["blocks"]) == ["1", "2", "3", "4"]
    assert plain["coarse"]["R"] == pytest.approx(result.coarse.R)
    assert None in plain["coarse_bounds"]["S_hi"]  # x₁ is no candidate: its bound is NaN


def test_triples_top_ranks_by_the_largest_own_increment():
    """The triples are ranked by their largest own-direction increment Δ^c, TRIPLE_TOP of them."""
    _, _, result = assessed("03", SEED)
    top = triples_top(result.coarse)
    assert top[0] == (0, 1, 2) and len(top) == TRIPLE_TOP
    assert triples_top(result.coarse, k=3) == top[:3]


# --- Task 6: the staged importance task and its views' payloads ---------------------------------

# What a stage adds to `ImportanceResult.to_json()` (and `N`, which it re-reads as the scheduled
# uniform configurations).
STAGE_KEYS = {
    "stage",
    "stages",
    "partial",
    "elapsed_s",
    "N",
    "attempted",
    "block_range",
    "uncertainty",
    "caveat",
}


def staged(frame, *, seed=SEED, checkpoint=no_checkpoint, **kwargs):
    """Every stage `importance_stages` yields on `frame`, in order."""
    return list(
        importance_stages(
            frame, metric=METRIC, scope=SCOPE, seed=seed, checkpoint=checkpoint, **kwargs
        )
    )


def test_importance_stages_arrive_in_order():
    """The three stages (§9.4), each whole for the stages run so far and partial until the last:
    1, the fine mains and pairs; 2, adding the per-block mains (with the block range) and the
    coarse point estimates; 3, adding the coarse bootstrap (R's interval, the candidates' bounds)
    and the coarse null. Every stage carries the counts, the seed, the snapshot, the constants and
    the three uncertainties; the last is `assess`'s result."""
    frame = stat_frame(
        d=4, values=4, n=600, seed=SEED, y=first_order, blocks={1: first_order, 2: zero}
    )
    stages = staged(frame)
    assert [s["stage"] for s in stages] == [1, 2, 3]
    assert [s["partial"] for s in stages] == [True, True, False]
    assert all(s["stages"] == 3 and s["seed"] == SEED for s in stages)
    assert all(s["snapshot"] == {"generation": 0, "chunk_watermark": 0} for s in stages)
    assert all(s["n"] == s["N"] == s["attempted"] == 600 and s["K"] == 2 for s in stages)
    assert all(s["constants"]["THETA_MIN"] == THETA_MIN for s in stages)
    assert all(len(s["statuses"]) == 4 and s["availability"] is not None for s in stages)
    json.dumps(stages, allow_nan=False)  # plain JSON throughout
    first, second, third = stages
    assert first["fine"] == second["fine"] == third["fine"]  # computed once, in stage 1
    assert first["blocks"] is None and first["coarse"] is None and first["block_range"] is None
    assert first["uncertainty"]["period"] == "pending: 2 screening blocks, measured in stage 2"
    assert sorted(second["blocks"]) == ["1", "2"] and second["coarse"]["R"] is not None
    assert second["coarse_bounds"] is None and second["coarse_null"] is None
    assert second["coarse"]["lo"] is None  # R has no interval before stage 3
    assert second["uncertainty"]["period"] == "block range over 2 screening blocks"
    for k, found in enumerate(second["block_range"]):
        shares = [second["blocks"][b]["S"][k] for b in ("1", "2")]
        assert found == [min(shares), max(shares)]
    assert third["coarse"]["lo"] is not None and third["coarse"]["hi"] is not None
    assert third["coarse_bounds"]["R_lo"] == third["coarse"]["lo"]
    assert third["coarse_null"] is not None and third["block_range"] == second["block_range"]
    final = assess(cohort_of(frame), seed=SEED, checkpoint=no_checkpoint).to_json()
    assert {k: v for k, v in third.items() if k not in STAGE_KEYS} == {
        k: v for k, v in final.items() if k != "N"
    }
    assert third["uncertainty"]["design"] == "interval: sampling of trials, this data"
    assert third["caveat"].startswith("conditional on these ranges, this data, this sampler")


def test_stage_results_carry_their_timings():
    """Each stage's dict carries `elapsed_s`, the seconds since the task's body began (the cohort
    included), so stage 1's is the fine stage's time and stage 3's the whole task's. The budgets
    (FINE_STAGE_BUDGET_S, TASK_BUDGET_S) are measured by `lab_benchmark.py analytics` (Task 12),
    never asserted here."""
    stages = staged(stat_frame(d=3, values=4, n=400, seed=SEED, y=first_order))
    elapsed = [s["elapsed_s"] for s in stages]
    assert all(isinstance(value, float) and value >= 0.0 for value in elapsed)
    assert elapsed == sorted(elapsed)


def test_importance_stages_stop_at_a_checkpoint():
    """The stages pass the task's checkpoint between resamples: a cancel stops the computation
    inside a stage, after the stages already delivered."""
    calls = []
    cancelled = []

    def checkpoint():
        calls.append(1)
        if cancelled:
            raise Cancelled

    stages = importance_stages(
        stat_frame(d=3, values=4, n=400, seed=SEED, y=first_order),
        metric=METRIC,
        scope=SCOPE,
        seed=SEED,
        checkpoint=checkpoint,
    )
    assert next(stages)["stage"] == 1
    assert len(calls) >= BOOTSTRAP_B + PERMUTATION_P
    cancelled.append(True)
    with pytest.raises(Cancelled):
        next(stages)


def test_basis_line_names_n_and_the_scheduled_n():
    """The basis line: n uniform trials used of N scheduled, with the attempted count beside N
    while they differ (a run in progress), excluded adaptive rows and the ignored filter."""
    frame = stat_frame(d=3, values=4, n=400, seed=SEED, y=first_order)
    *_, last = staged(frame, scheduled=1_000)
    assert (last["n"], last["N"], last["attempted"]) == (400, 1_000, 400)
    assert importance_basis(last) == (
        "computed on 400 uniform trials of 1,000 (400 attempted); adaptive rows excluded; "
        "ignores the active filter"
    )
    *_, whole = staged(frame)
    assert whole["N"] == frame.scheduled == 400
    assert importance_basis(whole) == (
        "computed on 400 uniform trials of 400; adaptive rows excluded; ignores the active filter"
    )
    assert importance_basis(None) == "importance not computed yet; ignores the active filter"


def test_without_blocks_the_period_uncertainty_is_not_measured():
    """K = 0 (an optimization grid, an experiment without screening blocks): every stage says the
    period uncertainty is `not measured: no screening blocks` and has no block range."""
    stages = staged(stat_frame(d=3, values=4, n=400, seed=SEED, y=first_order))
    for stage in stages:
        assert stage["uncertainty"]["period"] == "not measured: no screening blocks"
        assert stage["block_range"] is None and stage["K"] == 0


def test_interactions_view_lists_every_pair():
    """Every pair of d = 10, 45 of them: J and both increments with their intervals, the
    increments' floors, I (display-only, Task 4's interface: no interval), coverage and balance.
    Resolved pairs first, by their larger increment; the unresolved ones (coverage under
    PAIR_MIN_COVERAGE) last, by max(S_i upper, S_j upper), then lowest coverage."""
    values = [12, 12, 12] + [3] * 7
    first, *_ = staged(stat_frame(d=10, values=values, n=400, seed=SEED, y=first_order))
    payload = interactions_payload(first)
    pairs = payload["pairs"]
    assert len(pairs) == payload["total_pairs"] == 45
    assert sorted(tuple(p["index"]) for p in pairs) == list(itertools.combinations(range(10), 2))
    paths = first["paths"]
    fine = first["fine"]
    for pair in pairs:
        i, j = pair["index"]
        assert pair["pair"] == [paths[i], paths[j]]
        assert pair["J"] == {
            "value": fine["J"][i][j],
            "lo": fine["lo"]["J"][i][j],
            "hi": fine["hi"]["J"][i][j],
        }
        for name, (a, b) in (("D_ij", (i, j)), ("D_ji", (j, i))):
            entry = pair[name]
            assert entry["value"] == fine["D"][a][b]
            assert (entry["lo"], entry["hi"]) == (fine["lo"]["D"][a][b], fine["hi"]["D"][a][b])
            assert entry["floor"] == fine["floor"]["D"][a][b]
            assert entry["detected"] == (fine["D"][a][b] > fine["floor"]["D"][a][b])
        assert pair["I"] == fine["I"][i][j]
        assert pair["I"] == pytest.approx(fine["J"][i][j] - fine["S"][i] - fine["S"][j])
        assert pair["coverage"] == first["pair_coverage"][i][j]
        assert pair["balance"] == first["pair_balance"][i][j]
        assert pair["unresolved"] == (pair["coverage"] < PAIR_MIN_COVERAGE)
    unresolved = [p for p in pairs if p["unresolved"]]
    assert payload["unresolved_pairs"] == len(unresolved) == 3  # the three 12-value pairs
    assert pairs[-3:] == unresolved  # last
    upper = fine["hi"]["S"]
    keys = [(-max(upper[p["index"][0]], upper[p["index"][1]]), p["coverage"]) for p in unresolved]
    assert keys == sorted(keys)
    resolved = pairs[:-3]
    larger = [max(p["D_ij"]["value"], p["D_ji"]["value"]) for p in resolved]
    assert larger == sorted(larger, reverse=True)
    assert payload["constants"] == first["constants"]
    assert payload["truncated"] is False  # every pair sent
    assert interactions_payload(None) == {
        "pairs": [],
        "total_pairs": 0,
        "unresolved_pairs": 0,
        "truncated": False,
        "constants": None,
    }


def test_triples_view_tops_twenty_with_their_intervals():
    """The top TRIPLE_TOP triples by Δ^c, each with its three own-direction increments; a bound
    where the coarse bootstrap gave one (a candidate's triple, stage 3), null elsewhere, and the
    coarse null's floor. Before stage 2 there are none."""
    _, _, result = assessed("03", SEED)
    final = result.to_json()
    payload = triples_payload(final)
    triples = payload["triples"]
    assert len(triples) == TRIPLE_TOP and payload["total_triples"] == math.comb(D, 3)
    assert [tuple(t["index"]) for t in triples] == [tuple(t) for t in final["triples_top"]]
    assert triples[0]["index"] == [0, 1, 2] and triples[0]["triple"] == list(result.paths[:3])
    at = {tuple(t): k for k, t in enumerate(final["coarse"]["triples"])}
    candidates_held = set(final["coarse_bounds"]["candidates"])
    bounded = 0
    for triple in triples:
        t = at[tuple(triple["index"])]
        assert triple["T"] == final["coarse"]["T"][t]
        values = [entry["value"] for entry in triple["increments"]]
        assert values == final["coarse"]["increments"][t]
        assert triple["delta"] == max(values)
        for p, entry in enumerate(triple["increments"]):
            assert entry["own"] == result.paths[triple["index"][p]]
            assert entry["hi"] == final["coarse_bounds"]["inc_hi"][t][p]
            assert entry["floor"] == final["coarse_null"]["increments"][t][p]
        held = candidates_held.intersection(triple["index"])
        assert all(e["hi"] is not None for e in triple["increments"]) == bool(held)
        bounded += bool(held)
    assert payload["bounded"] is True and bounded > 0
    points = triples_payload({**final, "coarse_bounds": None, "coarse_null": None})
    assert all(
        e["lo"] is None and e["hi"] is None and e["floor"] is None
        for t in points["triples"]
        for e in t["increments"]
    )
    assert points["bounded"] is False
    assert triples_payload({**final, "coarse": None, "triples_top": []})["triples"] == []
    assert triples_payload(None) == {"triples": [], "total_triples": 0, "bounded": False}


def test_importance_view_leaves_the_triples_to_the_triples_view():
    """The importance view sends the latest stage without its triple-level arrays (1,140 triples
    at d = 20; the triples view sends the top TRIPLE_TOP), building new dicts: the stage it read
    is unchanged."""
    _, _, result = assessed("03", SEED)
    final = result.to_json()
    before = json.dumps(final, sort_keys=True)
    sent = importance_module.importance_payload(final)
    assert set(sent["coarse"]) == {"S", "J", "D", "R", "lo", "hi"}
    assert "inc_lo" not in sent["coarse_bounds"] and "inc_hi" not in sent["coarse_bounds"]
    assert sent["coarse_null"] == {"t": final["coarse_null"]["t"]}
    assert sent["triples_top"] == final["triples_top"] and sent["fine"] == final["fine"]
    assert json.dumps(final, sort_keys=True) == before
    assert importance_module.importance_payload(None) is None


def test_interactions_view_is_truncated_at_its_bound(monkeypatch):
    """The response bound holds whatever d is: the first INTERACTIONS_MAX_PAIRS pairs in the
    view's order, the unresolved going first, `total_pairs` still counting them all and
    `truncated` saying the list was cut; a list that exactly fits the bound is not cut. `truncated`
    is the pair list's own word: `triples` keeps `bounded`, which says stage 3's intervals exist."""
    values = [12, 12, 12] + [3] * 7
    first, *_ = staged(stat_frame(d=10, values=values, n=400, seed=SEED, y=first_order))
    whole = interactions_payload(first)["pairs"]
    monkeypatch.setattr(importance_module, "INTERACTIONS_MAX_PAIRS", 40)
    payload = interactions_payload(first)
    assert payload["pairs"] == whole[:40] and payload["total_pairs"] == 45
    assert not any(pair["unresolved"] for pair in payload["pairs"])
    assert payload["unresolved_pairs"] == 3
    assert payload["truncated"] is True and "bounded" not in payload
    monkeypatch.setattr(importance_module, "INTERACTIONS_MAX_PAIRS", 45)
    exact = interactions_payload(first)
    assert exact["pairs"] == whole and exact["truncated"] is False
    monkeypatch.setattr(importance_module, "INTERACTIONS_MAX_PAIRS", 44)
    cut = interactions_payload(first)
    assert cut["pairs"] == whole[:44] and cut["truncated"] is True
    assert first["constants"]["INTERACTIONS_MAX_PAIRS"] == 190


def test_elapsed_counts_from_the_start_it_is_given():
    """A body passes the clock it started before it opened its frame; without one the stages start
    their own."""
    frame = stat_frame(d=3, values=4, n=400, seed=SEED, y=first_order)
    earlier = time.perf_counter() - 100.0
    assert all(s["elapsed_s"] >= 100.0 for s in staged(frame, started=earlier))
    assert all(s["elapsed_s"] < 100.0 for s in staged(frame))
