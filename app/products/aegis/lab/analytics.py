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
- **A share** is the count-weighted η² of a grid (a parameter's values, a pair's cells), adjusted
  for its cells: `max(0, S - (k - 1) / (N - k) · (1 - S))`. N is the rows and k the cells holding
  rows: B_i observed values for a main, B_i·B_j for a pair whose cells are all tested. Group sums
  are `np.bincount`s: one pass scatters the rows once per block of parameters and once per pair
  of blocks, and every main and pair table is a marginal of those (`_Design`).
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
from dataclasses import dataclass, replace
from typing import NamedTuple

import numpy as np

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

# The columns `cohort` reads beside the parameters' values and the metric column.
COHORT_FIELDS = ("trial_no", "block", "design", "status")
MEASURED = "Measured"
INSUFFICIENT = "Insufficient coverage"
# The fine stage's families (decision 18): the mains, and the increments over all ordered pairs.
MAINS = "mains"
INCREMENTS = "increments"

# Why a configuration is not in the cohort, in `missing`'s order; `_USABLE` when it is.
_REASONS = ("invalid", "failed", "undefined")
_INVALID, _FAILED, _UNDEFINED, _USABLE = 0, 1, 2, 3
# One stream of the caller's seed per use, so a subsample never shares bits with a resample.
_SUBSAMPLE, _DESIGN, _BOOTSTRAP, _PERMUTATION = 0, 1, 2, 3
_INT16_MAX = np.iinfo(np.int16).max
_CONSTANT = 1e-12  # Y is constant when its spread is below this relative to its magnitude
# A block of parameters holds at most this many joint cells, so a block pair's table (at most
# 4,096 cells, 32 KB) stays in cache while the rows are scattered into it.
BLOCK_CELLS = 64

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
    `(space - valid) / space`.

    Beyond the brief: `metric` and `scope` name the column read (Task 5's reasons print them),
    and `X_uniform` holds every uniform configuration's value indices whatever its outcome (at
    most IMPORTANCE_ROWS, a seeded subsample beyond): the rows `cramers_v` reads, so
    outcome-dependent missingness never shows as aliasing (case 16)."""

    paths: tuple[str, ...]
    X: np.ndarray
    B: np.ndarray
    Y: np.ndarray
    blocks: dict[int, np.ndarray]
    n: int
    n_uniform_total: int
    sampled_from: int | None
    missing: dict[str, int]
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
    return np.where(codes == 0, usable, np.where(codes == 1, _INVALID, _FAILED))


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
    positions = np.empty((table.num_rows, len(paths)), dtype=np.int64)
    for k, (path, axis) in enumerate(zip(paths, axes, strict=True)):
        positions[:, k] = _positions(_numbers(table, path), axis)
    values = _numbers(table, metric_column(scope, metric))
    if metric in LOWER_IS_BETTER:
        values = -values
    reason = _reasons(_status_codes(table), values)
    block = _numbers(table, "block")
    trial = _trial_numbers(table)
    uniform = _labelled(table, "design", ["uniform"])
    configurations = np.flatnonzero((block == 0) & uniform & (positions >= 0).all(axis=1))
    configurations = configurations[np.argsort(trial[configurations], kind="stable")]
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
    design = positions[configurations]
    if total > IMPORTANCE_ROWS:
        design = design[_subsample(total, seed, _DESIGN)]
    rows = configurations[kept]
    space = int(frame.space)
    return Cohort(
        paths=paths,
        X=_frozen(positions[rows].astype(np.int16)),
        B=_frozen(B),
        Y=_frozen(values[rows]),
        blocks={b: _frozen(y[kept]) for b, y in per_block.items()},
        n=len(rows),
        n_uniform_total=total,
        sampled_from=sampled_from,
        missing=missing,
        invalid_share=(space - int(frame.valid)) / space if space else 0.0,
        seed=seed,
        metric=metric,
        scope=scope,
        X_uniform=_frozen(design.astype(np.int16)),
    )


# --- the shares (§7.3, §7.4) -------------------------------------------------------------------


def _blocks(B: Sequence[int]) -> list[list[int]]:
    """Consecutive parameters grouped while their joint cells stay within BLOCK_CELLS (a
    parameter larger than that alone)."""
    blocks: list[list[int]] = []
    current: list[int] = []
    cells = 1
    for i, size in enumerate(B):
        if current and cells * size > BLOCK_CELLS:
            blocks.append(current)
            current, cells = [], 1
        current.append(i)
        cells *= size
    if current:
        blocks.append(current)
    return blocks


@dataclass(frozen=True, eq=False)
class _Design:
    """X's grids, scattered once per pass: one `np.bincount` of the rows per block of parameters
    (its joint cells) and, with pairs, one per pair of blocks. Every main and pair table is a
    marginal of one of those tables: a block's mains and inner pairs are its table times
    `margins[p]` (one-hot columns), a block pair's cross pairs are `sides[p]ᵀ · T · sides[q]`.
    A block pair's table holds all its cross pairs, so at 8 values and d = 20 a pass scatters the
    rows 55 times, not 210.

    `keys` hold each row's joint cell per block. The flat grid cells are the mains, then the pairs
    i < j in `np.triu_indices` order (a pair's cell `X_i · B_j + X_j`): `starts` is each grid's
    first cell, `dest` the flat cell of each concatenated marginal entry, `counts` the rows per
    cell, each row once."""

    keys: tuple[np.ndarray, ...]
    cells: tuple[int, ...]
    margins: tuple[np.ndarray, ...]
    sides: tuple[np.ndarray, ...]
    pairs: tuple[tuple[int, int], ...]
    dest: np.ndarray
    starts: np.ndarray
    size: int
    counts: np.ndarray
    buffer: np.ndarray  # one block pair's keys, rewritten in every pass


def _one_hot(cell: np.ndarray, width: int) -> np.ndarray:
    """(len(cell) × width): 1 where a joint cell's value is the column."""
    out = np.zeros((len(cell), width))
    out[np.arange(len(cell)), cell] = 1.0
    return out


def _design(X: np.ndarray, B: Sequence[int], with_pairs: bool) -> _Design:
    """X's `_Design`: the blocks' keys, their marginal matrices, where each marginal entry lands
    among the flat grid cells, and the rows counted once."""
    n, d = X.shape
    B = [int(b) for b in B]
    blocks = _blocks(B)
    grid = {(i, i): i for i in range(d)}  # a grid's number: the mains, then the pairs i < j
    upper = list(zip(*np.triu_indices(d, 1), strict=True)) if with_pairs else []
    sizes = [B[i] for i in range(d)] + [B[i] * B[j] for i, j in upper]
    grid.update({(int(i), int(j)): g for g, (i, j) in enumerate(upper, start=d)})
    starts = np.cumsum([0, *sizes])
    keys, cells, margins, sides, dest = [], [], [], [], []
    for members in blocks:
        key = np.zeros(n, dtype=np.intp)
        for i in members:
            key *= B[i]
            key += np.asarray(X[:, i], dtype=np.intp)
        keys.append(key)
        shape = tuple(B[i] for i in members)
        cells.append(math.prod(shape))
        at = dict(zip(members, np.indices(shape).reshape(len(shape), -1), strict=True))
        side = np.hstack([_one_hot(at[i], B[i]) for i in members])
        sides.append(side.T.copy())
        columns = [side]
        dest += [starts[grid[(i, i)]] + np.arange(B[i]) for i in members]
        inner = [(i, j) for k, i in enumerate(members) for j in members[k + 1 :]]
        for i, j in inner if with_pairs else ():
            columns.append(_one_hot(at[i] * B[j] + at[j], B[i] * B[j]))
            dest.append(starts[grid[(i, j)]] + np.arange(B[i] * B[j]))
        margins.append(np.hstack(columns))
    pairs = []
    if with_pairs:
        for p in range(len(blocks)):
            for q in range(p + 1, len(blocks)):
                pairs.append((p, q))
                for i in blocks[p]:  # the rows of sides[p]ᵀ · T · sides[q], member by member
                    row = np.concatenate(
                        [
                            starts[grid[(i, j)]]
                            + B[j] * np.arange(B[i])[:, None]
                            + np.arange(B[j])[None, :]
                            for j in blocks[q]
                        ],
                        axis=1,
                    )
                    dest.append(row.ravel())
    dest_all = np.concatenate(dest) if dest else np.zeros(0, dtype=np.intp)
    size = int(starts[-1])
    if not np.array_equal(np.sort(dest_all), np.arange(size)):
        raise AssertionError("the marginals must fill every grid cell once")
    design = _Design(
        keys=tuple(keys),
        cells=tuple(cells),
        margins=tuple(margins),
        sides=tuple(sides),
        pairs=tuple(pairs),
        dest=dest_all,
        starts=starts[:-1],
        size=size,
        counts=np.zeros(0),
        buffer=np.empty(n, dtype=np.intp),
    )
    return replace(design, counts=_tables(design, None)[0])


def _tables(design: _Design, *weights: np.ndarray | None) -> list[np.ndarray]:
    """Every grid's cell sums of each weight vector (None: the rows counted), flat."""
    parts: list[list[np.ndarray]] = [[] for _ in weights]
    for key, cells, margin in zip(design.keys, design.cells, design.margins, strict=True):
        for k, w in enumerate(weights):
            parts[k].append(np.bincount(key, weights=w, minlength=cells) @ margin)
    buffer = design.buffer
    for p, q in design.pairs:
        np.multiply(design.keys[p], design.cells[q], out=buffer)
        np.add(buffer, design.keys[q], out=buffer)
        shape = (design.cells[p], design.cells[q])
        for k, w in enumerate(weights):
            table = np.bincount(buffer, weights=w, minlength=shape[0] * shape[1]).reshape(shape)
            parts[k].append((design.sides[p] @ table @ design.sides[q].T).ravel())
    out = []
    for marginals in parts:
        flat = np.empty(design.size)
        flat[design.dest] = np.concatenate(marginals) if marginals else flat[:0]
        out.append(flat)
    return out


def _adjusted(design: _Design, Y: np.ndarray, w: np.ndarray | None) -> np.ndarray:
    """Each grid's adjusted share of Y over the rows weighted by `w` (None: each row once). NaN
    where it is undefined: Y constant, or no fewer cells holding rows than rows."""
    m = len(design.starts)
    if len(Y) < 2:
        return np.full(m, np.nan)
    if w is None:
        total = float(len(Y))
        centred = Y - Y.mean()
        weighted = centred
    else:
        total = float(w.sum())
        centred = Y - (w @ Y) / total
        weighted = w * centred
    sst = float(weighted @ centred)
    scale = float(np.abs(Y).max())
    if not sst > (_CONSTANT * scale) ** 2 * total:
        return np.full(m, np.nan)
    if w is None:
        counts, sums = design.counts, _tables(design, weighted)[0]
    else:
        counts, sums = _tables(design, w, weighted)
    tested = counts > 0
    between = np.zeros(design.size)
    np.divide(sums * sums, counts, out=between, where=tested)
    share = np.add.reduceat(between, design.starts) / sst
    cells = np.add.reduceat(tested, design.starts, dtype=np.float64)
    room = total - cells
    adjusted = np.full(m, np.nan)
    fits = room > 0
    adjusted[fits] = share[fits] - (cells[fits] - 1.0) / room[fits] * (1.0 - share[fits])
    return np.maximum(adjusted, 0.0)  # NaN stays NaN


def _square(S: np.ndarray, pairs: np.ndarray) -> np.ndarray:
    """The pair shares (i < j, `np.triu_indices` order) as a symmetric d × d matrix whose
    diagonal is the mains."""
    d = len(S)
    J = np.empty((d, d))
    upper = np.triu_indices(d, 1)
    J[upper] = pairs
    J[upper[1], upper[0]] = pairs
    J[np.diag_indices(d)] = S
    return J


def incremental(S: np.ndarray, J: np.ndarray) -> np.ndarray:
    """`Δ[i, j] = J[i, j] - S[j]`: what adding i explains beyond j (§7.4); 0 on the diagonal."""
    delta = J - S[np.newaxis, :]
    np.fill_diagonal(delta, 0.0)
    return delta


def interaction(S: np.ndarray, J: np.ndarray) -> np.ndarray:
    """`I[i, j] = J[i, j] - S[i] - S[j]`, for display only (no rule reads it); 0 on the diagonal,
    which holds no pair."""
    out = J - S[:, np.newaxis] - S[np.newaxis, :]
    np.fill_diagonal(out, 0.0)
    return out


class FineTerms:
    """The fine grid's statistic for `intervals` and `floors`: one pass of `np.bincount`s over
    every main and, with `pairs`, every pair. Called as `fn(X, Y, w)`, it returns the mains `S`
    (d) without pairs, else one (2d + 1) × d array: the mains, then the pairs `J` (d × d), then
    the increments `Δ` (d × d); `fine_parts` splits it.

    The design of the last X seen (its keys, counts and marginal maps) is kept: `intervals` and
    `floors` pass the same X on every resample, so a resample costs one scatter of the rows per
    block and per block pair (two for a bootstrap's counts and sums). X is never written to
    between calls (a cohort's arrays are read-only), and one instance serves one thread."""

    def __init__(self, B: Sequence[int], *, pairs: bool = True) -> None:
        self.B = tuple(int(b) for b in B)
        self.pairs = pairs
        self._held: tuple[np.ndarray, _Design] | None = None

    def _design(self, X: np.ndarray) -> _Design:
        held = self._held
        if held is None or held[0] is not X:
            held = self._held = (X, _design(X, self.B, self.pairs))
        return held[1]

    def __call__(self, X: np.ndarray, Y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
        shares = _adjusted(self._design(X), np.asarray(Y, dtype=np.float64), w)
        d = len(self.B)
        S = shares[:d]
        if not self.pairs:
            return S
        J = _square(S, shares[d:])
        return np.vstack([S[np.newaxis, :], J, incremental(S, J)])


def fine_parts(terms: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A `FineTerms` array (or its bounds or floors) as `(S, J, Δ)`."""
    d = terms.shape[1]
    return terms[0], terms[1 : d + 1], terms[d + 1 :]


def fine_families(d: int) -> dict[str, np.ndarray]:
    """The fine stage's families over a `FineTerms` array: the mains, and the increments
    `Δ_{i|j}` over all ordered pairs (the diagonal holds none). The pairs `J` are in no family:
    no rule reads them."""
    mains = np.zeros((2 * d + 1, d), dtype=bool)
    mains[0] = True
    increments = np.zeros_like(mains)
    increments[d + 1 :] = ~np.eye(d, dtype=bool)
    return {MAINS: mains, INCREMENTS: increments}


def fine_shares(X: np.ndarray, Y: np.ndarray, B: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """`(S_adj[d], J_adj[d, d])`: every main and every pair's adjusted share of Y (module
    docstring), J symmetric with the mains on its diagonal."""
    S, J, _ = fine_parts(FineTerms(B)(X, Y))
    return S, J


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
    tail = (1.0 - INTERVAL) / 2.0
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
