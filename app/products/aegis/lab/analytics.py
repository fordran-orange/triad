"""The Lab's importance on the fine grid (Optimization Lab v2 spec §7.3 and §7.4; Phase 3 Task 4):
the analysis cohort, the shares, their intervals and detection floors, coverage and aliasing.

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
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

import numpy as np
import pyarrow as pa

from products.aegis.lab.policy import (
    ALIAS_V,
    BOOTSTRAP_B,
    FLOOR_QUANTILE,
    IMPORTANCE_MIN_N_FACTOR,
    IMPORTANCE_MIN_PER_VALUE,
    IMPORTANCE_ROWS,
    INTERVAL,
    PAIR_MIN_N,
    PERMUTATION_P,
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

# The columns `cohort` reads beside the parameters' values and the metric column.
COHORT_FIELDS = ("trial_no", "block", "design", "status")
MEASURED = "Measured"
INSUFFICIENT = "Insufficient coverage"

# Why a configuration is not in the cohort, in `missing`'s order; `_USABLE` when it is.
_REASONS = ("invalid", "failed", "undefined")
_INVALID, _FAILED, _UNDEFINED, _USABLE = 0, 1, 2, 3
# One stream of the caller's seed per use, so a subsample never shares bits with a resample.
_SUBSAMPLE, _DESIGN, _BOOTSTRAP, _PERMUTATION = 0, 1, 2, 3
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
    outcome-dependent missingness never shows as aliasing (case 16)."""

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
    )


# --- the three uncertainties' resamples (§7.3; decisions 18 and 19) ---------------------------


def intervals(
    fn: Statistic, X: np.ndarray, Y: np.ndarray, *, b: int, seed: int, checkpoint: Checkpoint
) -> tuple[np.ndarray, np.ndarray]:
    """The INTERVAL bounds of `fn` over `b` seeded row resamples, re-centred on the point
    estimate: `[θ̂ + q₀.₀₅* - mean*, θ̂ + q₀.₉₅* - mean*]` (decision 19). A resample is a row
    multiplicity vector, equal to drawing the n rows with replacement. `checkpoint()` runs before
    each resample. An output undefined in any resample has NaN bounds."""
    if b < 1:
        raise ValueError(f"an interval needs at least one resample, not {b}")
    Y = np.asarray(Y, dtype=np.float64)
    theta = np.asarray(fn(X, Y, None), dtype=np.float64)
    n = len(Y)
    if n < 2:
        return np.full(theta.shape, np.nan), np.full(theta.shape, np.nan)
    rng = _stream(seed, _BOOTSTRAP)
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
) -> Floors:
    """The detection floors of `fn` from `p` seeded permutations of Y over the same rows (module
    docstring). `families` maps a name to a boolean mask over `fn`'s output, members of no other
    family; a member whose null never varies has its constant null as its floor, and one undefined
    under the null has NaN. `checkpoint()` runs before each permutation."""
    if p < 2:
        raise ValueError(f"a floor needs at least two permutations, not {p}")
    Y = np.asarray(Y, dtype=np.float64)
    rng = _stream(seed, _PERMUTATION)
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


__all__ = [
    "COHORT_FIELDS",
    "INCREMENTS",
    "INSUFFICIENT",
    "MAINS",
    "MEASURED",
    "BlockMains",
    "Cohort",
    "FineTerms",
    "Floors",
    "Statistic",
    "aliased",
    "block_mains",
    "cohort",
    "coverage_label",
    "cramers_v",
    "fine_families",
    "fine_parts",
    "fine_shares",
    "floors",
    "incremental",
    "interaction",
    "intervals",
    "pair_quality",
]
