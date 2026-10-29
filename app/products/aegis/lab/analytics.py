"""The Lab's importance (Optimization Lab v2 spec §7.3, §7.4 and §7.4a; Phase 3 Tasks 4 and 5): the
analysis cohort, the shares, their intervals and detection floors, coverage and aliasing (Task 4);
the coarse decomposition's resamples, availability, the veto, the recommended statuses and the
evidence scope (Task 5).

Pure numpy over arrays: `cohort` alone reads a frame, through `query`'s column helpers; every
other function takes arrays and returns arrays. Randomness is seeded through
`np.random.default_rng((seed, stream))`, one stream per use of the caller's seed, which every
response carries. Nothing fits a model or interpolates.

- **The cohort** (§7.3 "Rows used"): the configurations of `design == "uniform"` on the current
  space's lattice, unfiltered. Block 0 decides inclusion: a configuration is in when its block-0
  evaluation and every screening block's are `ok` with a finite metric. An excluded one counts
  once in `missing`, by block 0's reason, else by its first failing block's. Beyond
  IMPORTANCE_ROWS a seeded subsample, stated. The metric is oriented so larger is better.
- **The shares** are `shares.py`'s: the adjusted count-weighted η² of every main and pair in
  one pass of `np.bincount`s per resample; `fine_shares`, `FineTerms` and their helpers are
  re-exported here.
- **Intervals** (decision 19): BOOTSTRAP_B row resamples, as row multiplicities. The 90 % bounds
  are re-centred on the point estimate, `[θ̂ + q₀.₀₅* - mean*, θ̂ + q₀.₉₅* - mean*]`, since an
  adjusted share's bootstrap distribution centres on the raw estimate.
- **Floors** (decision 18): PERMUTATION_P permutations of Y.
  - Each share's 95th percentile is a display tick.
  - The family floor is max-T. Each share is standardized by its null mean and SD; `t` is the 95th
    percentile of the permutations' largest standardized share in the family; the floor is
    `mean + t · sd`.
  - "Detected" means the point estimate exceeds its family floor.
- **The coarse decomposition** is `coarse.py`'s (re-exported here); its bootstrap
  (COARSE_BOOTSTRAP_B) bounds R and the candidates' terms, its null (COARSE_PERMUTATION_P) floors
  the triple increments, each on its own stream.
- **The rule** (§7.4a, decisions 15, 16 and 21): `availability` by provenance, first failing
  reason first; the residual `veto`; `statuses`, the first rule that holds per parameter, with
  `failing` naming why every non-proposable parameter is not proposed. Phase 3 recommends: it
  never persists or changes a status (condition 6, the operator's confirmation, is Phase 4).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NamedTuple

import numpy as np
import pyarrow as pa

from products.aegis.lab.coarse import (
    TRIPLE_INCREMENTS,
    Coarse,
    CoarseParts,
    CoarseTerms,
    coarse,
    coarse_bins,
    coarse_families,
    coarse_parts,
    coarse_sizes,
    triple_index,
    triples_top,
)
from products.aegis.lab.policy import (
    ALIAS_V,
    BOOTSTRAP_B,
    COARSE_BINS,
    COARSE_BOOTSTRAP_B,
    COARSE_PERMUTATION_P,
    FLOOR_QUANTILE,
    IMPORTANCE_MIN_N_FACTOR,
    IMPORTANCE_MIN_PER_VALUE,
    IMPORTANCE_ROWS,
    INTERVAL,
    PAIR_BALANCE_TVD,
    PAIR_MIN_COVERAGE,
    PAIR_MIN_N,
    PERMUTATION_P,
    RESIDUAL_INCONSISTENT,
    RESIDUAL_VETO,
    THETA_MIN,
    TRIPLE_TOP,
)
from products.aegis.lab.query import (
    ALL_BLOCKS,
    LOWER_IS_BETTER,
    TrialFrame,
    _axis,
    _labelled,
    _numbers,
    _positions,
    _status_codes,
    _trial_numbers,
    metric_column,
)
from products.aegis.lab.shares import (
    INCREMENTS,
    MAINS,
    FineTerms,
    fine_families,
    fine_parts,
    fine_shares,
    incremental,
    interaction,
)
from products.aegis.lab.store import snapshot_json

# The columns `cohort` reads beside the parameters' values and the metric column.
COHORT_FIELDS = ("trial_no", "block", "design", "status")
MEASURED = "Measured"
INSUFFICIENT = "Insufficient coverage"

# Why a configuration is not in the cohort, in `missing`'s order; `_USABLE` when it is.
_REASONS = ("invalid", "failed", "undefined")
_INVALID, _FAILED, _UNDEFINED, _USABLE = 0, 1, 2, 3
# One stream of the caller's seed per use, so a subsample never shares bits with a resample, nor
# the coarse decomposition's resamples (Task 5) with the fine grid's.
_SUBSAMPLE, _DESIGN, _BOOTSTRAP, _PERMUTATION = 0, 1, 2, 3
_COARSE_BOOTSTRAP, _COARSE_PERMUTATION = 4, 5
_INT16_MAX = np.iinfo(np.int16).max

Checkpoint = Callable[[], None]
# A statistic for `intervals` and `floors`: `fn(X, Y, w)` over X's rows weighted by `w`, the
# row multiplicities of a resample (None: each row once), returning an array of fixed shape.
Statistic = Callable[[np.ndarray, np.ndarray, np.ndarray | None], np.ndarray]


def _frozen(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


def _stream(seed: int, stream: int) -> np.random.Generator:
    return np.random.default_rng((seed, stream))


# --- the cohort (§7.3 "Rows used") -------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Cohort:
    """The rows importance reads: `X` (int16, n × d) the configurations' value indices on each
    parameter's lattice of `B` values, `Y` (float64) the oriented metric in block 0, `blocks` each
    screening block's oriented metric for the same configurations (empty when K = 0). `n` rows
    are used, of `sampled_from` when they were subsampled to IMPORTANCE_ROWS (seeded by `seed`),
    out of the `n_uniform_total` uniform configurations attempted. `missing` counts the excluded
    ones by reason over block 0 and every block; `invalid_share` is the grid's invalid share,
    `(space - valid) / space`. Its arrays are read-only and its mappings `MappingProxyType`s.

    Beyond the brief: `metric` and `scope` name the column read (Task 5's reasons print them),
    and `X_uniform` holds every uniform configuration's value indices whatever its outcome (at
    most IMPORTANCE_ROWS, a seeded subsample beyond): the rows `cramers_v` reads, so
    outcome-dependent missingness never shows as aliasing (case 16). `snapshot` is the frame's
    (`snapshot_json`), part of the evidence's scope (Task 5's `evidence_scope`)."""

    paths: tuple[str, ...]
    X: np.ndarray
    B: np.ndarray
    Y: np.ndarray
    blocks: Mapping[int, np.ndarray]
    n: int
    n_uniform_total: int
    sampled_from: int | None
    missing: Mapping[str, int]
    invalid_share: float
    seed: int
    metric: str
    scope: str
    X_uniform: np.ndarray
    snapshot: dict | None = None


def _subsample(count: int, seed: int, stream: int) -> np.ndarray:
    """IMPORTANCE_ROWS of `count` rows, seeded, in their original order."""
    rng = _stream(seed, stream)
    return np.sort(rng.choice(count, size=IMPORTANCE_ROWS, replace=False))


def _reasons(codes: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Per row `_USABLE` (ok with a finite metric), else invalid, failed (an unknown status
    included) or undefined (ok without a finite metric)."""
    usable = np.where(np.isfinite(values), _USABLE, _UNDEFINED)
    return np.where(codes == 0, usable, np.where(codes == 1, _INVALID, _FAILED)).astype(np.int8)


def cohort(frame: TrialFrame, *, metric: str, scope: str, seed: int) -> Cohort:
    """The analysis cohort of `frame` (module docstring), unfiltered.

    A frame of an experiment with screening blocks must hold them all (`ALL_BLOCKS`); a K = 0
    frame may be of either selection. A configuration is a block-0 row; a row off the current
    lattice is not of the current space and is left out uncounted. A configuration whose
    block-b row is absent counts as `failed` there: an evaluation that never produced a row
    cannot be told from one that failed."""
    if frame.blocks and frame.selection != ALL_BLOCKS:
        raise ValueError(
            f"{frame.source} has {frame.blocks} screening blocks: importance reads every block, "
            "from a frame opened with selection=ALL_BLOCKS"
        )
    table = frame.table
    paths = tuple(parameter.path for parameter in frame.parameters)
    axes = [_axis(frame, path) for path in paths]
    B = np.array([len(axis) for axis in axes], dtype=np.int64)
    if len(B) and int(B.max()) > _INT16_MAX:
        raise ValueError(f"a parameter of {int(B.max())} values exceeds int16 value indices")
    values = _numbers(table, metric_column(scope, metric))
    if metric in LOWER_IS_BETTER:
        values = -values
    reason = _reasons(_status_codes(table), values)
    block = _numbers(table, "block")
    trial = _trial_numbers(table)
    # The configurations' value positions only (a block row needs its metric alone), as int16.
    base = np.flatnonzero((block == 0) & _labelled(table, "design", ["uniform"]))
    held = table.select(list(paths)).take(pa.array(base, pa.int64()))
    positions = np.empty((len(base), len(paths)), dtype=np.int16)
    on_lattice = np.ones(len(base), dtype=bool)
    for k, (path, axis) in enumerate(zip(paths, axes, strict=True)):
        position = _positions(_numbers(held, path), axis)  # -1 off the lattice
        on_lattice &= position >= 0
        positions[:, k] = position
    order = np.flatnonzero(on_lattice)
    order = order[np.argsort(trial[base[order]], kind="stable")]
    configurations, positions = base[order], positions[order]
    owner = trial[configurations]
    total = len(configurations)
    why = reason[configurations]
    per_block: dict[int, np.ndarray] = {}
    for b in range(1, frame.blocks + 1):
        rows = np.flatnonzero(block == b)
        at = np.searchsorted(owner, trial[rows])
        found = at < total
        found[found] = owner[at[found]] == trial[rows[found]]
        y = np.full(total, np.nan)
        y[at[found]] = values[rows[found]]
        seen = np.full(total, _FAILED)  # no row for this block: failed (docstring)
        seen[at[found]] = reason[rows[found]]
        why = np.where(why == _USABLE, seen, why)  # block 0's reason, else the first block's
        per_block[b] = y
    missing = {name: int((why == k).sum()) for k, name in enumerate(_REASONS)}
    kept = np.flatnonzero(why == _USABLE)
    sampled_from = None
    if len(kept) > IMPORTANCE_ROWS:
        sampled_from = len(kept)
        kept = kept[_subsample(len(kept), seed, _SUBSAMPLE)]
    design = positions
    if total > IMPORTANCE_ROWS:
        design = design[_subsample(total, seed, _DESIGN)]
    rows = configurations[kept]
    space = int(frame.space)
    return Cohort(
        paths=paths,
        X=_frozen(positions[kept]),
        B=_frozen(B),
        Y=_frozen(values[rows]),
        blocks=MappingProxyType({b: _frozen(y[kept]) for b, y in per_block.items()}),
        n=len(rows),
        n_uniform_total=total,
        sampled_from=sampled_from,
        missing=MappingProxyType(missing),
        invalid_share=(space - int(frame.valid)) / space if space else 0.0,
        seed=seed,
        metric=metric,
        scope=scope,
        X_uniform=_frozen(design),
        snapshot=snapshot_json(frame.snapshot),
    )


# --- the three uncertainties' resamples (§7.3; decisions 18 and 19) ---------------------------


def intervals(
    fn: Statistic,
    X: np.ndarray,
    Y: np.ndarray,
    *,
    b: int,
    seed: int,
    checkpoint: Checkpoint,
    stream: int = _BOOTSTRAP,
) -> tuple[np.ndarray, np.ndarray]:
    """The INTERVAL bounds of `fn` over `b` seeded row resamples, re-centred on the point
    estimate: `[θ̂ + q₀.₀₅* - mean*, θ̂ + q₀.₉₅* - mean*]` (decision 19). A resample is a row
    multiplicity vector, equal to drawing the n rows with replacement, from `stream` of the seed
    (the coarse bootstrap draws its own). `checkpoint()` runs before each resample. An output
    undefined in any resample has NaN bounds."""
    if b < 1:
        raise ValueError(f"an interval needs at least one resample, not {b}")
    Y = np.asarray(Y, dtype=np.float64)
    theta = np.asarray(fn(X, Y, None), dtype=np.float64)
    n = len(Y)
    if n < 2:
        return np.full(theta.shape, np.nan), np.full(theta.shape, np.nan)
    rng = _stream(seed, stream)
    draws = np.empty((b, *theta.shape))
    for r in range(b):
        checkpoint()
        w = np.bincount(rng.integers(0, n, size=n), minlength=n).astype(np.float64)
        draws[r] = fn(X, Y, w)
    tail = round((1.0 - INTERVAL) / 2.0, 12)  # exactly 0.05 (the subtraction leaves 0.0499…)
    low, high = np.quantile(draws, [tail, 1.0 - tail], axis=0)
    shift = theta - draws.mean(axis=0)
    return low + shift, high + shift


@dataclass(frozen=True, eq=False)
class Floors:
    """`share`: each output's FLOOR_QUANTILE over the permutations, the panel's tick. `family`:
    the family-wise (max-T) floor of each family member, NaN outside every family. `t`: each
    family's critical value (an addition the panel can print)."""

    share: np.ndarray
    family: np.ndarray
    t: dict[str, float]


def floors(
    fn: Statistic,
    X: np.ndarray,
    Y: np.ndarray,
    *,
    p: int,
    seed: int,
    checkpoint: Checkpoint,
    families: Mapping[str, np.ndarray],
    stream: int = _PERMUTATION,
) -> Floors:
    """The detection floors of `fn` from `p` seeded permutations of Y over the same rows (module
    docstring), drawn from `stream` of the seed (the coarse null draws its own). `families` maps a
    name to a boolean mask over `fn`'s output, members of no other family; a member whose null
    never varies has its constant null as its floor, and one undefined under the null has NaN.
    `checkpoint()` runs before each permutation."""
    if p < 2:
        raise ValueError(f"a floor needs at least two permutations, not {p}")
    Y = np.asarray(Y, dtype=np.float64)
    rng = _stream(seed, stream)
    null: np.ndarray | None = None
    for r in range(p):
        checkpoint()
        value = np.asarray(fn(X, Y[rng.permutation(len(Y))], None), dtype=np.float64)
        if null is None:
            null = np.empty((p, *value.shape))
        null[r] = value
    assert null is not None
    share = np.quantile(null, FLOOR_QUANTILE, axis=0)
    mean, sd = null.mean(axis=0), null.std(axis=0, ddof=1)
    family = np.full(mean.shape, np.nan)
    claimed = np.zeros(mean.shape, dtype=bool)
    critical: dict[str, float] = {}
    for name, mask in families.items():
        members = np.asarray(mask, dtype=bool)
        if members.shape != mean.shape:
            raise ValueError(f"family {name!r} is {members.shape}, the statistic {mean.shape}")
        if (claimed & members).any():
            raise ValueError(f"family {name!r} shares a member with another family")
        claimed |= members
        centre, spread = mean[members], sd[members]
        varies = np.isfinite(spread) & (spread > 0)
        z = (null[:, members][:, varies] - centre[varies]) / spread[varies]
        t = float(np.quantile(z.max(axis=1), FLOOR_QUANTILE)) if z.shape[1] else math.nan
        constant = np.where(spread == 0, centre, np.nan)
        family[members] = np.where(varies, centre + t * np.where(varies, spread, 0.0), constant)
        critical[name] = t
    return Floors(share=share, family=family, t=critical)


class BlockMains(NamedTuple):
    """One screening block's fine mains: the shares, their interval and their family floor."""

    S: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    floor: np.ndarray


def block_mains(cohort: Cohort, *, seed: int, checkpoint: Checkpoint) -> dict[int, BlockMains]:
    """Per screening block (none when K = 0), the fine mains of its metric, one bootstrap of
    BOOTSTRAP_B and one null of PERMUTATION_P each, the block's mains one family. Every block
    resamples the same rows with the same permutations: the blocks differ by their Y alone."""
    fn = FineTerms(cohort.B, pairs=False)
    families = {MAINS: np.ones(len(cohort.B), dtype=bool)}
    out: dict[int, BlockMains] = {}
    for b, Y in sorted(cohort.blocks.items()):
        lo, hi = intervals(fn, cohort.X, Y, b=BOOTSTRAP_B, seed=seed, checkpoint=checkpoint)
        found = floors(
            fn,
            cohort.X,
            Y,
            p=PERMUTATION_P,
            seed=seed,
            checkpoint=checkpoint,
            families=families,
        )
        out[b] = BlockMains(fn(cohort.X, Y), lo, hi, found.family)
    return out


# --- coverage and aliasing (§7.3, §7.4) ---------------------------------------------------------


def coverage_label(X: np.ndarray, B: Sequence[int], n: int) -> list[str]:
    """Per parameter `Measured` when `n ≥ IMPORTANCE_MIN_N_FACTOR × B_i` and every one of its
    B_i values has at least IMPORTANCE_MIN_PER_VALUE of X's rows, else `Insufficient coverage`
    (unresolved: §7.3, scenario 25). `n` is the rows the shares are computed on."""
    labels = []
    for i, size in enumerate(int(b) for b in B):
        per_value = np.bincount(np.asarray(X[:, i], dtype=np.intp), minlength=size)
        measured = (
            n >= IMPORTANCE_MIN_N_FACTOR * size
            and size > 0
            and int(per_value.min()) >= IMPORTANCE_MIN_PER_VALUE
        )
        labels.append(MEASURED if measured else INSUFFICIENT)
    return labels


def pair_quality(X: np.ndarray, B: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """`(coverage[d, d], balance_tvd[d, d])` (§7.4): a pair's coverage is the share of its B_i·B_j
    cells holding at least PAIR_MIN_N rows; its balance is the total variation distance of its
    cells' row shares from uniform. The diagonal is each parameter's own values."""
    d, n = len(B), len(X)
    coverage, balance = np.zeros((d, d)), np.full((d, d), np.nan)
    columns = [np.asarray(X[:, i], dtype=np.intp) for i in range(d)]
    for i in range(d):
        for j in range(i, d):
            key = columns[i] if i == j else columns[i] * int(B[j]) + columns[j]
            size = int(B[i]) if i == j else int(B[i]) * int(B[j])
            counts = np.bincount(key, minlength=size)
            coverage[i, j] = coverage[j, i] = float((counts >= PAIR_MIN_N).mean())
            if n:
                balance[i, j] = balance[j, i] = 0.5 * float(np.abs(counts / n - 1.0 / size).sum())
    return coverage, balance


def cramers_v(X: np.ndarray, B: Sequence[int]) -> np.ndarray:
    """Cramér's V between every two parameters (d × d, 1 on the diagonal) over X's rows: pass
    every scheduled uniform configuration (`Cohort.X_uniform`), never the cohort, so
    outcome-dependent missingness never shows as aliasing (§7.3, case 16). Over the values each
    pair holds; 0 for a parameter with a single value held."""
    d = len(B)
    V = np.eye(d)
    columns = [np.asarray(X[:, i], dtype=np.intp) for i in range(d)]
    for i, j in zip(*np.triu_indices(d, 1), strict=True):
        cells = np.bincount(columns[i] * int(B[j]) + columns[j], minlength=int(B[i]) * int(B[j]))
        table = cells.reshape(int(B[i]), int(B[j])).astype(np.float64)
        rows, cols = table.sum(axis=1), table.sum(axis=0)
        table = table[rows > 0][:, cols > 0]
        rows, cols = rows[rows > 0], cols[cols > 0]
        q = min(len(rows), len(cols)) - 1
        if q < 1:
            continue
        n = float(rows.sum())
        chi2 = n * (float((table**2 / np.outer(rows, cols)).sum()) - 1.0)
        V[i, j] = V[j, i] = math.sqrt(max(chi2, 0.0) / (n * q))
    return V


def aliased(V: np.ndarray) -> list[tuple[int, int]]:
    """The pairs `(i, j)`, i < j, whose Cramér's V exceeds ALIAS_V: both carry `credit shared`."""
    upper = zip(*np.triu_indices(len(V), 1), strict=True)
    return [(int(i), int(j)) for i, j in upper if V[i, j] > ALIAS_V]


# --- the coarse decomposition's resamples (§7.4; Task 5) ----------------------------------------


@dataclass(frozen=True, eq=False)
class CoarseBounds:
    """The coarse bootstrap's re-centred INTERVAL bounds (decision 19). R's always; for each of
    the `candidates` its coarse main `S_i`, its increments `Δ_{i|j}` beyond every j (row i of
    `D`) and the three increments of every triple containing it (`inc`, t × 3, `triple_index`
    order). Every other entry is NaN: the rule reads no other coarse bound (§7.4)."""

    candidates: tuple[int, ...]
    R_lo: float
    R_hi: float
    S_lo: np.ndarray
    S_hi: np.ndarray
    D_lo: np.ndarray
    D_hi: np.ndarray
    inc_lo: np.ndarray
    inc_hi: np.ndarray


def coarse_intervals(
    Xq: np.ndarray,
    Y: np.ndarray,
    candidates: Sequence[int],
    *,
    b: int = COARSE_BOOTSTRAP_B,
    seed: int,
    checkpoint: Checkpoint,
) -> CoarseBounds:
    """`b` seeded resamples of the whole coarse decomposition, on its own stream, re-centred as
    `intervals` is: every resample needs every triple for R, so only the bounds reported are
    restricted to R and the candidates' terms (`CoarseBounds`)."""
    d = Xq.shape[1]
    fn = CoarseTerms(coarse_sizes(Xq))
    lo, hi = intervals(fn, Xq, Y, b=b, seed=seed, checkpoint=checkpoint, stream=_COARSE_BOOTSTRAP)
    chosen = tuple(sorted({int(i) for i in candidates}))
    keep = np.zeros(d, dtype=bool)
    keep[list(chosen)] = True
    held = np.isin(fn.trios, chosen).any(axis=1)

    def kept(vector: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
        parts = coarse_parts(vector, d)
        S = np.where(keep, parts.S, np.nan)
        D = np.where(keep[:, np.newaxis], parts.D, np.nan)
        inc = np.where(held[:, np.newaxis], parts.increments, np.nan)
        return parts.R, S, D, inc

    R_lo, S_lo, D_lo, inc_lo = kept(lo)
    R_hi, S_hi, D_hi, inc_hi = kept(hi)
    return CoarseBounds(chosen, R_lo, R_hi, S_lo, S_hi, D_lo, D_hi, inc_lo, inc_hi)


def coarse_floors(
    Xq: np.ndarray,
    Y: np.ndarray,
    *,
    p: int = COARSE_PERMUTATION_P,
    seed: int,
    checkpoint: Checkpoint,
) -> Floors:
    """`p` seeded permutations of Y over the coarse grid, on their own stream: each term's tick,
    and the family-wise (max-T) floor of the own-direction triple increments, one family."""
    fn = CoarseTerms(coarse_sizes(Xq))
    families = coarse_families(Xq.shape[1])
    return floors(
        fn,
        Xq,
        Y,
        p=p,
        seed=seed,
        checkpoint=checkpoint,
        families=families,
        stream=_COARSE_PERMUTATION,
    )


# --- availability and the veto (§7.3, §7.4; decisions 15 and 16) --------------------------------

NO_UNIFORM = "no uniform rows of the current space"
ALIASED = "aliased inputs"
INCONSISTENT = "decomposition inconsistent"
PRODUCT_HINT = "freeze or narrow the constrained ranges"
METRIC_HINT = (
    "choose a metric defined everywhere (net_pnl, max_drawdown, trade_count, exposure) "
    "or retry the failed trials"
)
UNAVAILABLE = "empirical deprioritization unavailable"
VETO = "structure not captured by mains, pairs and triples: deprioritization unsafe"
VETO_WARNING = "unexplained share high: noise or higher-order structure"


@dataclass(frozen=True)
class Availability:
    """Whether the rule may propose (§7.4a): `reasons` every failing reason in order, `reason`
    the first, `hint` the first's hint (reasons 3 and 4 carry one)."""

    available: bool
    reason: str | None
    reasons: list[str]
    hint: str | None

    @property
    def message(self) -> str | None:
        """The panel's line: `empirical deprioritization unavailable: <reason>`."""
        return None if self.available else f"{UNAVAILABLE}: {self.reason}"


def _percent(share: float) -> str:
    """A share as the reasons print it: an integer percent at 1 % and above, one decimal below
    (`0.4`), and `< 0.1` for a positive share that would round to 0.0."""
    percent = 100.0 * share
    if percent >= 1.0:
        return f"{percent:.0f}"
    return f"{percent:.1f}" if percent >= 0.05 else "< 0.1"


def availability(cohort: Cohort, V: np.ndarray, R_hi: float, R_lo: float) -> Availability:
    """The rule's availability by provenance (§7.3), the first failing reason winning:
    1. `no uniform rows of the current space`;
    2. `aliased inputs` (any pair of V above ALIAS_V; before the product design, decision 15);
    3. `inputs are not a product design (p % of the grid is invalid)`;
    4. `m of N configurations have no finite <metric> (k invalid, f failed, u undefined)`, N the
       uniform configurations scheduled, counted over block 0 and every block;
    5. `decomposition inconsistent` when R's upper bound is below RESIDUAL_INCONSISTENT.
    `R_lo` rides along with R's interval; it is the veto's input (`veto`), not availability's."""
    failing: list[tuple[str, str | None]] = []
    if cohort.n_uniform_total == 0:
        failing.append((NO_UNIFORM, None))
    if aliased(V):
        failing.append((ALIASED, None))
    if cohort.invalid_share > 0:
        grid = _percent(cohort.invalid_share)
        failing.append(
            (f"inputs are not a product design ({grid} % of the grid is invalid)", PRODUCT_HINT)
        )
    k, f, u = (int(cohort.missing.get(reason, 0)) for reason in _REASONS)
    if k + f + u:
        lost = (
            f"{k + f + u:,} of {cohort.n_uniform_total:,} configurations have no finite "
            f"{cohort.metric} ({k:,} invalid, {f:,} failed, {u:,} undefined)"
        )
        failing.append((lost, METRIC_HINT))
    if R_hi < RESIDUAL_INCONSISTENT:
        failing.append((INCONSISTENT, None))
    if not failing:
        return Availability(True, None, [], None)
    (reason, hint), *_ = failing
    return Availability(False, reason, [text for text, _ in failing], hint)


def veto(R_lo: float) -> str | None:
    """The residual veto (§7.4): raised when R's lower bound exceeds RESIDUAL_VETO; the panel then
    also shows VETO_WARNING (decision 16)."""
    return VETO if R_lo > RESIDUAL_VETO else None


def missingness_note(cohort: Cohort) -> str | None:
    """The descriptive estimates' note when configurations are missing (§7.3)."""
    lost, total = sum(int(v) for v in cohort.missing.values()), cohort.n_uniform_total
    if not lost or not total:
        return None
    return f"on {total - lost:,} of {total:,} configurations; missingness may bias"


# --- the assembled result (Task 5; Task 6 stages it) --------------------------------------------


@dataclass(frozen=True, eq=False)
class FineStage:
    """The fine grid's stage: `FineTerms` point estimates, their re-centred bounds and floors,
    each a (2d + 1) × d array that `fine_parts` splits into S, J and Δ."""

    terms: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    floors: Floors


def fine_stage(cohort: Cohort, *, seed: int, checkpoint: Checkpoint) -> FineStage:
    """The fine mains and pairs with BOOTSTRAP_B resamples and PERMUTATION_P permutations."""
    fn = FineTerms(cohort.B)
    X, Y = cohort.X, cohort.Y
    lo, hi = intervals(fn, X, Y, b=BOOTSTRAP_B, seed=seed, checkpoint=checkpoint)
    found = floors(
        fn,
        X,
        Y,
        p=PERMUTATION_P,
        seed=seed,
        checkpoint=checkpoint,
        families=fine_families(len(cohort.B)),
    )
    return FineStage(fn(X, Y), lo, hi, found)


# The constants the rule and its panel read (global constraints: printed from the response).
CONSTANTS = MappingProxyType(
    {
        "THETA_MIN": THETA_MIN,
        "RESIDUAL_VETO": RESIDUAL_VETO,
        "RESIDUAL_INCONSISTENT": RESIDUAL_INCONSISTENT,
        "BOOTSTRAP_B": BOOTSTRAP_B,
        "PERMUTATION_P": PERMUTATION_P,
        "COARSE_BOOTSTRAP_B": COARSE_BOOTSTRAP_B,
        "COARSE_PERMUTATION_P": COARSE_PERMUTATION_P,
        "COARSE_BINS": COARSE_BINS,
        "INTERVAL": INTERVAL,
        "FLOOR_QUANTILE": FLOOR_QUANTILE,
        "ALIAS_V": ALIAS_V,
        "PAIR_MIN_N": PAIR_MIN_N,
        "PAIR_MIN_COVERAGE": PAIR_MIN_COVERAGE,
        "PAIR_BALANCE_TVD": PAIR_BALANCE_TVD,
        "IMPORTANCE_MIN_N_FACTOR": IMPORTANCE_MIN_N_FACTOR,
        "IMPORTANCE_MIN_PER_VALUE": IMPORTANCE_MIN_PER_VALUE,
        "IMPORTANCE_ROWS": IMPORTANCE_ROWS,
        "TRIPLE_TOP": TRIPLE_TOP,
    }
)


def _plain(value: Any) -> Any:
    """`value` in plain JSON types: arrays as lists, NaN and infinities as None."""
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain({f.name: getattr(value, f.name) for f in dataclasses.fields(value)})
    return value


@dataclass(frozen=True, eq=False)
class ImportanceResult:
    """Everything the rule reads, assembled from the cohort and whichever stages have run (later
    ones None): the cohort's counts; per parameter its coverage `labels` and the values holding
    IMPORTANCE_MIN_PER_VALUE rows; the pairs' `coverage` and `balance`; Cramér's V over every
    uniform configuration and its `aliased_pairs`; the `fine` stage; the per-block mains
    (`blocks`, None until computed, `K` the experiment's blocks); the `coarse` point estimates
    (R's interval in `lo` / `hi` once bounded), the `coarse_bounds` and the `coarse_null`
    floors; `availability`, `veto`, its `warnings` and the missingness `note`."""

    paths: tuple[str, ...]
    B: np.ndarray
    n: int
    n_uniform_total: int
    sampled_from: int | None
    missing: dict[str, int]
    invalid_share: float
    metric: str
    scope: str
    seed: int
    snapshot: dict | None
    labels: list[str]
    values_held: list[int]
    coverage: np.ndarray
    balance: np.ndarray
    V: np.ndarray
    aliased_pairs: list[tuple[int, int]]
    fine: FineStage
    blocks: dict[int, BlockMains] | None
    K: int
    coarse: Coarse | None
    coarse_bounds: CoarseBounds | None
    coarse_null: Floors | None
    availability: Availability
    veto: str | None
    warnings: list[str]
    note: str | None

    def to_json(self) -> dict:
        """The result in plain JSON types (lists, NaN as null), its statuses included."""
        d = len(self.paths)
        fine = self.fine
        names = ("S", "J", "D")
        floor_S, _, floor_D = fine_parts(fine.floors.family)
        tick_S, _, tick_D = fine_parts(fine.floors.share)
        coarse_json = None
        if self.coarse is not None:
            found = self.coarse
            coarse_json = {
                "S": found.S,
                "J": found.J,
                "D": found.D,
                "triples": found.triples,
                "T": found.T,
                "increments": found.increments,
                "R": found.R,
                "lo": found.lo,
                "hi": found.hi,
            }
        null_json = None
        if self.coarse_null is not None:
            null_json = {
                "increments": coarse_parts(self.coarse_null.family, d).increments,
                "tick": coarse_parts(self.coarse_null.share, d).increments,
                "t": self.coarse_null.t,
            }
        blocks_json = None
        if self.blocks is not None:
            blocks_json = {b: mains._asdict() for b, mains in sorted(self.blocks.items())}
        return _plain(
            {
                "paths": self.paths,
                "B": self.B,
                "n": self.n,
                "N": self.n_uniform_total,
                "sampled_from": self.sampled_from,
                "missing": self.missing,
                "invalid_share": self.invalid_share,
                "metric": self.metric,
                "scope": self.scope,
                "seed": self.seed,
                "snapshot": self.snapshot,
                "labels": self.labels,
                "values_held": self.values_held,
                "pair_coverage": self.coverage,
                "pair_balance": self.balance,
                "cramers_v": self.V,
                "aliased": self.aliased_pairs,
                "fine": {
                    **dict(zip(names, fine_parts(fine.terms), strict=True)),
                    "lo": dict(zip(names, fine_parts(fine.lo), strict=True)),
                    "hi": dict(zip(names, fine_parts(fine.hi), strict=True)),
                    "floor": {"S": floor_S, "D": floor_D},
                    "tick": {"S": tick_S, "D": tick_D},
                    "t": fine.floors.t,
                },
                "K": self.K,
                "blocks": blocks_json,
                "coarse": coarse_json,
                "coarse_bounds": self.coarse_bounds,
                "coarse_null": null_json,
                "triples_top": [] if self.coarse is None else triples_top(self.coarse),
                "availability": {
                    **dataclasses.asdict(self.availability),
                    "message": self.availability.message,
                },
                "veto": self.veto,
                "warnings": self.warnings,
                "note": self.note,
                "statuses": statuses(self),
                "constants": CONSTANTS,
            }
        )


def importance_result(
    cohort: Cohort,
    *,
    fine: FineStage,
    blocks: Mapping[int, BlockMains] | None = None,
    coarse: Coarse | None = None,
    coarse_bounds: CoarseBounds | None = None,
    coarse_null: Floors | None = None,
) -> ImportanceResult:
    """The `ImportanceResult` of `cohort` with the stages that have run: coverage, pair quality and
    aliasing are computed here, and availability and the veto from R's interval once the coarse
    bootstrap has bounded it (NaN before: neither inconsistent nor vetoed, while condition 3 still
    has no interval, so nothing is proposable)."""
    X, B = cohort.X, cohort.B
    V = cramers_v(cohort.X_uniform, B)
    coverage, balance = pair_quality(X, B)
    held = []
    for i, size in enumerate(int(b) for b in B):
        per_value = np.bincount(np.asarray(X[:, i], dtype=np.intp), minlength=size)
        held.append(int((per_value >= IMPORTANCE_MIN_PER_VALUE).sum()))
    R_lo = R_hi = math.nan
    if coarse_bounds is not None:
        R_lo, R_hi = coarse_bounds.R_lo, coarse_bounds.R_hi
        if coarse is not None:
            coarse = dataclasses.replace(coarse, lo=R_lo, hi=R_hi)
    vetoed = veto(R_lo)
    return ImportanceResult(
        paths=cohort.paths,
        B=B,
        n=cohort.n,
        n_uniform_total=cohort.n_uniform_total,
        sampled_from=cohort.sampled_from,
        missing=dict(cohort.missing),
        invalid_share=cohort.invalid_share,
        metric=cohort.metric,
        scope=cohort.scope,
        seed=cohort.seed,
        snapshot=cohort.snapshot,
        labels=coverage_label(X, B, cohort.n),
        values_held=held,
        coverage=coverage,
        balance=balance,
        V=V,
        aliased_pairs=aliased(V),
        fine=fine,
        blocks=None if blocks is None else dict(blocks),
        K=len(cohort.blocks),
        coarse=coarse,
        coarse_bounds=coarse_bounds,
        coarse_null=coarse_null,
        availability=availability(cohort, V, R_hi, R_lo),
        veto=vetoed,
        warnings=[VETO_WARNING] if vetoed else [],
        note=missingness_note(cohort),
    )


def assess(cohort: Cohort, *, seed: int, checkpoint: Checkpoint) -> ImportanceResult:
    """Every stage of the rule on `cohort`, in Task 6's order: the fine grid, the per-block mains
    and the coarse point estimates, then the coarse bootstrap for R and the candidates (§7.4,
    `candidates`) and the coarse null."""
    fine = fine_stage(cohort, seed=seed, checkpoint=checkpoint)
    blocks = block_mains(cohort, seed=seed, checkpoint=checkpoint)
    Xq = coarse_bins(cohort.X, cohort.B)
    points = coarse(Xq, cohort.Y)
    staged = importance_result(cohort, fine=fine, blocks=blocks, coarse=points)
    bounds = coarse_intervals(Xq, cohort.Y, candidates(staged), seed=seed, checkpoint=checkpoint)
    null = coarse_floors(Xq, cohort.Y, seed=seed, checkpoint=checkpoint)
    return importance_result(
        cohort,
        fine=fine,
        blocks=blocks,
        coarse=points,
        coarse_bounds=bounds,
        coarse_null=null,
    )


# --- the recommended statuses (§7.4a, §8.4; decision 21) ----------------------------------------

UNRESOLVED = "Insufficient coverage · unresolved"
PROPOSABLE = "Deprioritized · proposable"
PERIOD_DEPENDENT = "Investigate · period-dependent"
DETECTED = "Active · detected"
INTERACTION = "Investigate · interaction not ruled out"
THREE_WAY = "Investigate · three-way effect not ruled out"
NOT_DETECTED = "Active · not detected"


@dataclass(frozen=True)
class ParameterStatus:
    """A parameter's recommended status, the first of decision 21's rules that holds, with its
    `reason`; its `flags`; its coverage `label`; `proposable` (rule 2 alone); and `failing`, why a
    non-proposable parameter is not proposed (None when it is)."""

    path: str
    status: str
    reason: str
    flags: list[str]
    label: str
    proposable: bool
    failing: str | None


class _Evidence:
    """A result's arrays, split once for the rule: NaN where a stage has not run yet."""

    def __init__(self, result: ImportanceResult) -> None:
        d = len(result.paths)
        self.result, self.d = result, d
        self.S, _, self.D = fine_parts(result.fine.terms)
        self.S_hi, _, self.D_hi = fine_parts(result.fine.hi)
        self.S_floor, _, self.D_floor = fine_parts(result.fine.floors.family)
        self.trios = triple_index(d)
        unknown = np.full((len(self.trios), 3), np.nan)
        found, bounds, null = result.coarse, result.coarse_bounds, result.coarse_null
        self.cS = found.S if found else np.full(d, np.nan)
        self.cD = found.D if found else np.full((d, d), np.nan)
        self.inc = found.increments if found else unknown
        self.cS_hi = bounds.S_hi if bounds else np.full(d, np.nan)
        self.cD_hi = bounds.D_hi if bounds else np.full((d, d), np.nan)
        self.inc_hi = bounds.inc_hi if bounds else unknown
        self.inc_floor = coarse_parts(null.family, d).increments if null else unknown
        self.blocks = dict(sorted((result.blocks or {}).items()))
        # Each parameter's triples, as (triple, the parameter's position in it).
        self.own = [np.argwhere(self.trios == i) for i in range(d)]

    def triple(self, t: int) -> str:
        return ", ".join(self.result.paths[k] for k in self.trios[t])


def _below(name: str, value: float, *, point: bool) -> str | None:
    """Why `value < THETA_MIN` fails for `name` (an upper bound, or a point estimate), or None."""
    if math.isnan(value):
        return f"{name} {'undefined' if point else 'has no interval'}"
    if value < THETA_MIN:
        return None
    return f"{name}{'' if point else ' upper'} {value:.4f} ≥ θ_min {THETA_MIN:g}"


def _condition1(ev: _Evidence, i: int, point: bool) -> str | None:
    """§7.4a condition 1: the fine and the coarse S_i, on block 0 and in every block (block 0
    only without blocks, decision 4), coverage first."""
    r = ev.result
    if r.labels[i] != MEASURED:
        return "insufficient coverage"
    unmeasured = [0] if math.isnan(ev.S[i]) else []
    unmeasured += [b for b, mains in ev.blocks.items() if math.isnan(mains.S[i])]
    if unmeasured:
        return f"not measured in block {unmeasured[0]}"
    if r.K and r.blocks is None:
        return "block mains not computed yet"
    checks = [
        ("fine S", ev.S[i] if point else ev.S_hi[i]),
        ("coarse S", ev.cS[i] if point else ev.cS_hi[i]),
    ]
    checks += [
        (f"fine S in block {b}", mains.S[i] if point else mains.hi[i])
        for b, mains in ev.blocks.items()
    ]
    for name, value in checks:
        failure = _below(name, float(value), point=point)
        if failure:
            return failure
    return None


def _condition2(ev: _Evidence, i: int, point: bool) -> str | None:
    """§7.4a condition 2: for every other j, the pair measured (coverage, balance) and both the
    fine and the coarse Δ_{i|j} below θ_min."""
    r = ev.result
    for j in range(ev.d):
        if j == i:
            continue
        other = r.paths[j]
        if not r.coverage[i, j] >= PAIR_MIN_COVERAGE:
            covered = r.coverage[i, j]
            return f"pair with {other} unresolved: coverage {covered:.2f} < {PAIR_MIN_COVERAGE:g}"
        if r.balance[i, j] > PAIR_BALANCE_TVD:
            tvd = r.balance[i, j]
            return f"pair with {other} unbalanced: TVD {tvd:.2f} > {PAIR_BALANCE_TVD:g}"
        checks = (
            (f"Δ beyond {other}", ev.D[i, j] if point else ev.D_hi[i, j]),
            (f"coarse Δ beyond {other}", ev.cD[i, j] if point else ev.cD_hi[i, j]),
        )
        for name, value in checks:
            failure = _below(name, float(value), point=point)
            if failure:
                return failure
    return None


def _condition3(ev: _Evidence, i: int) -> str | None:
    """§7.4a condition 3: i's own coarse increment in every triple containing it has an interval
    below θ_min; an unresolved triple blocks, naming it."""
    for t, position in ev.own[i]:
        value = float(ev.inc_hi[t, position])
        if math.isnan(value):
            return f"triple ({ev.triple(t)}) unresolved: no interval"
        if not value < THETA_MIN:
            return (
                f"own coarse increment in ({ev.triple(t)}) upper {value:.4f} ≥ θ_min {THETA_MIN:g}"
            )
    return None


def _failures(ev: _Evidence, i: int, *, point: bool = False, upto: int = 5) -> list[str]:
    """The §7.4a conditions 1 to `upto` that fail for parameter i, each with its first failure:
    on the upper bounds, or (`point`, conditions 1 and 2 only) on the point estimates."""
    r = ev.result
    found = [
        _condition1(ev, i, point),
        _condition2(ev, i, point),
        None if point else _condition3(ev, i),
        None,
        None,
    ]
    if not point and r.aliased_pairs:
        a, b = r.aliased_pairs[0]
        found[3] = f"aliased inputs: {r.paths[a]} and {r.paths[b]}"
    if not point and r.veto is not None:
        found[4] = "residual veto raised"
    return [f"condition {n} ({what})" for n, what in enumerate(found[:upto], 1) if what]


def conditions(result: ImportanceResult, i: int) -> list[str]:
    """The §7.4a conditions 1-5 that parameter i fails, each as `condition <n> (<what>)` with its
    first failure; empty when all five hold."""
    return _failures(_Evidence(result), i)


def candidates(result: ImportanceResult) -> list[int]:
    """The coarse bootstrap's candidates (§7.4): the parameters passing §7.4a conditions 1 and 2
    on their point estimates. None before the coarse point estimates exist."""
    ev = _Evidence(result)
    return [i for i in range(ev.d) if not _failures(ev, i, point=True, upto=2)]


def _period_dependent(ev: _Evidence, i: int) -> str | None:
    """Rule 3: a block whose S_i exceeds that block's family floor with its upper bound above
    θ_min, while another block's upper bound is below θ_min."""
    for b, mains in ev.blocks.items():
        if not (mains.S[i] > mains.floor[i] and mains.hi[i] > THETA_MIN):
            continue
        for c, other in ev.blocks.items():
            if c != b and other.hi[i] < THETA_MIN:
                return (
                    f"S {mains.S[i]:.4f} exceeds its floor in block {b} (upper "
                    f"{mains.hi[i]:.4f}); upper {other.hi[i]:.4f} < θ_min {THETA_MIN:g} in "
                    f"block {c}"
                )
    return None


def _interaction(ev: _Evidence, i: int) -> str | None:
    """Rule 5: some Δ_{i|j} exceeds its family floor and its upper bound θ_min (the largest)."""
    found = [
        (float(ev.D[i, j]), j)
        for j in range(ev.d)
        if j != i and ev.D[i, j] > ev.D_floor[i, j] and ev.D_hi[i, j] > THETA_MIN
    ]
    if not found:
        return None
    value, j = max(found)
    return (
        f"Δ beyond {ev.result.paths[j]} {value:.4f} exceeds its family floor "
        f"{ev.D_floor[i, j]:.4f}; upper {ev.D_hi[i, j]:.4f} > θ_min {THETA_MIN:g}"
    )


def _three_way(ev: _Evidence, i: int) -> str | None:
    """Rule 6: some own-direction Δ_{i|jk}^c exceeds its family floor and its upper bound θ_min
    (the largest). Only a candidate's triples have bounds (§7.4)."""
    found = [
        (float(ev.inc[t, p]), int(t), int(p))
        for t, p in ev.own[i]
        if ev.inc[t, p] > ev.inc_floor[t, p] and ev.inc_hi[t, p] > THETA_MIN
    ]
    if not found:
        return None
    value, t, p = max(found)
    return (
        f"own coarse increment in ({ev.triple(t)}) {value:.4f} exceeds its family floor "
        f"{ev.inc_floor[t, p]:.4f}; upper {ev.inc_hi[t, p]:.4f} > θ_min {THETA_MIN:g}"
    )


def _status(ev: _Evidence, i: int, proposable: bool) -> tuple[str, str]:
    """Decision 21's first rule that holds for parameter i, with its reason."""
    r = ev.result
    if r.labels[i] != MEASURED:
        size = int(r.B[i])
        return UNRESOLVED, (
            f"coverage: {r.values_held[i]} of {size} values hold ≥ {IMPORTANCE_MIN_PER_VALUE} "
            f"rows; {r.n:,} rows of {IMPORTANCE_MIN_N_FACTOR * size:,} needed"
        )
    if proposable:
        return PROPOSABLE, (
            f"§7.4a conditions 1-5 hold (every upper bound below θ_min {THETA_MIN:g}); awaits "
            "the operator's confirmation"
        )
    period = _period_dependent(ev, i)
    if period:
        return PERIOD_DEPENDENT, period
    if ev.S[i] > ev.S_floor[i]:
        return DETECTED, f"S {ev.S[i]:.4f} exceeds its family floor {ev.S_floor[i]:.4f}"
    for status, rule in ((INTERACTION, _interaction), (THREE_WAY, _three_way)):
        reason = rule(ev, i)
        if reason:
            return status, reason
    return NOT_DETECTED, (
        f"S {ev.S[i]:.4f} within its family floor {ev.S_floor[i]:.4f}; no increment both "
        f"detected and above θ_min {THETA_MIN:g}"
    )


def _flags(ev: _Evidence, i: int) -> list[str]:
    r = ev.result
    flags = [
        f"aliased · credit shared with {r.paths[b if i == a else a]}"
        for a, b in r.aliased_pairs
        if i in (a, b)
    ]
    if math.isnan(ev.S[i]):
        flags.append("not measured in block 0")
    flags += [f"not measured in block {b}" for b, m in ev.blocks.items() if math.isnan(m.S[i])]
    return flags


def statuses(result: ImportanceResult) -> list[ParameterStatus]:
    """Every parameter's recommended status (decision 21), the `Measured` ones in path order and
    then the unresolved ones, last with their coverage. `failing` is set on every non-proposable
    parameter: the availability reason when the rule is unavailable, else the veto, else its first
    failed §7.4a condition as `not proposable: condition <n> (<what>)` (review B4)."""
    ev = _Evidence(result)
    available = result.availability.available
    out = []
    for i, path in enumerate(result.paths):
        failures = _failures(ev, i)
        proposable = available and result.veto is None and not failures
        if proposable:
            failing = None
        elif not available:
            failing = result.availability.reason
        elif result.veto is not None:
            failing = result.veto
        else:
            failing = f"not proposable: {failures[0]}"
        status, reason = _status(ev, i, proposable)
        out.append(
            ParameterStatus(
                path=path,
                status=status,
                reason=reason,
                flags=_flags(ev, i),
                label=result.labels[i],
                proposable=proposable,
                failing=failing,
            )
        )
    return [s for s in out if s.label == MEASURED] + [s for s in out if s.label != MEASURED]


# --- the evidence scope (§7.4a, §8.5; decision 5) -----------------------------------------------

# The fields of an evidence scope, in the order `compare_scope` reads them; a field's name in the
# `stale` text where it differs from its key.
SCOPE_FIELDS = (
    "strategy_hash",
    "data",
    "ranges",
    "sampler",
    "blocks",
    "search_space.hash",
    "snapshot",
)
_SCOPE_NAMES = {"data": "data identity"}


def evidence_scope(document: Any, cohort: Cohort) -> dict:
    """The scope a result's evidence holds for (§7.4a): the strategy hash, the data identity
    (symbol, timeframe, range and pinned sha256), the surface's ranges, the sampler (method, seed,
    revision), the screening blocks, the search space's hash and the cohort's snapshot. `document`
    is an `ExperimentDocument` or a mapping of its fields."""
    fields = document.model_dump(mode="json") if hasattr(document, "model_dump") else document
    data = fields.get("data") or {}
    pinned = fields.get("data_pinned") or {}
    surface = fields.get("surface") or {}
    sampler = fields.get("sampler") or {}
    space = fields.get("search_space") or {}
    return {
        "strategy_hash": fields.get("strategy_hash"),
        "data": {
            "symbol": data.get("symbol"),
            "timeframe": data.get("timeframe"),
            "start": data.get("start"),
            "end": data.get("end"),
            "sha256": pinned.get("sha256"),
        },
        "ranges": {
            p["path"]: [p["start"], p["stop"], p["step"]] for p in surface.get("parameters", [])
        },
        "sampler": {key: sampler.get(key) for key in ("method", "seed", "revision")},
        "blocks": int(fields.get("blocks") or 0),
        "search_space.hash": space.get("hash"),
        "snapshot": cohort.snapshot,
    }


def compare_scope(evidence: Mapping, current: Mapping) -> str:
    """`current` when the evidence's scope is the current one, else `stale: <field> changed`, the
    first differing field in SCOPE_FIELDS' order (case 9: `stale: ranges changed`)."""
    for field in SCOPE_FIELDS:
        if evidence.get(field) != current.get(field):
            return f"stale: {_SCOPE_NAMES.get(field, field)} changed"
    return "current"


__all__ = [
    "ALIASED",
    "COHORT_FIELDS",
    "CONSTANTS",
    "DETECTED",
    "INCONSISTENT",
    "INCREMENTS",
    "INSUFFICIENT",
    "INTERACTION",
    "MAINS",
    "MEASURED",
    "METRIC_HINT",
    "NOT_DETECTED",
    "NO_UNIFORM",
    "PERIOD_DEPENDENT",
    "PRODUCT_HINT",
    "PROPOSABLE",
    "SCOPE_FIELDS",
    "THREE_WAY",
    "TRIPLE_INCREMENTS",
    "UNAVAILABLE",
    "UNRESOLVED",
    "VETO",
    "VETO_WARNING",
    "Availability",
    "BlockMains",
    "Coarse",
    "CoarseBounds",
    "CoarseParts",
    "CoarseTerms",
    "Cohort",
    "FineStage",
    "FineTerms",
    "Floors",
    "ImportanceResult",
    "ParameterStatus",
    "Statistic",
    "aliased",
    "assess",
    "availability",
    "block_mains",
    "candidates",
    "coarse",
    "coarse_bins",
    "coarse_families",
    "coarse_floors",
    "coarse_intervals",
    "coarse_parts",
    "cohort",
    "compare_scope",
    "conditions",
    "coverage_label",
    "cramers_v",
    "evidence_scope",
    "fine_families",
    "fine_parts",
    "fine_shares",
    "fine_stage",
    "floors",
    "importance_result",
    "incremental",
    "interaction",
    "intervals",
    "missingness_note",
    "pair_quality",
    "statuses",
    "triples_top",
    "veto",
]
