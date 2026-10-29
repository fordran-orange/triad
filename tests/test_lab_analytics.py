"""Optimization Lab v2, Phase 3, Task 4: importance on the fine grid (spec §7.3 and §7.4,
decisions 17 to 19). The analysis cohort, the adjusted shares, their re-centred bootstrap
intervals, the per-share and family-wise (max-T) detection floors, coverage and aliasing, on the
seeded experiments of `lab_stat_fixtures.stat_frame` at its fixed generator constants. These are
the fine-grid halves of the sixteen §20 cases; their statuses are Task 5's."""

import math
from dataclasses import replace

import numpy as np
import pyarrow as pa
import pytest
from lab_stat_fixtures import (
    D_WIDE,
    SIGMA,
    SINE_VALUES,
    SPARSE_PRESENT,
    SPARSE_VALUES,
    VALUES,
    D,
    aliased_rows,
    high,
    stack_frames,
    stat_frame,
    uneven_rows,
    zero,
)
from products.aegis.lab.analytics import (
    INCREMENTS,
    INSUFFICIENT,
    MAINS,
    MEASURED,
    FineTerms,
    aliased,
    block_mains,
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
)
from products.aegis.lab.policy import (
    BOOTSTRAP_B,
    IMPORTANCE_ROWS,
    PERMUTATION_P,
    THETA_MIN,
)
from products.aegis.lab.query import BLOCK0, LabFilter, matrix_view
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
    largest standardized share in the family; the families never overlap."""
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
        members = families[name]
        mean, sd = null[:, members].mean(axis=0), null[:, members].std(axis=0, ddof=1)
        t = np.quantile(((null[:, members] - mean) / sd).max(axis=1), 0.95)
        assert found.t[name] == pytest.approx(t)
        assert np.allclose(found.family[members], mean + t * sd)
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
