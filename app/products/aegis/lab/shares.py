"""The Lab's fine-grid shares (Optimization Lab v2 spec §7.3 and §7.4; Phase 3 Task 4): the
adjusted count-weighted η² of every main and every pair of a value-index matrix, one pass of
`np.bincount`s per resample.

A share is the count-weighted η² of a grid (a parameter's values, a pair's cells), adjusted for
its cells: `max(0, S - (k - 1) / (N - k) · (1 - S))`. N is the rows (the total weight of a
resample) and k the cells holding rows: B_i observed values for a main, B_i·B_j for a pair whose
cells are all tested. It is NaN where it is undefined (Y constant, or no fewer cells holding rows
than rows), which no comparison downstream passes.

**One pass.**
- Consecutive parameters are grouped into blocks of at most BLOCK_CELLS joint cells.
- A pass scatters the rows once per block and once per pair of blocks into a joint table:
  - a block's mains and inner pairs are its table times a one-hot `margin`;
  - a block pair's cross pairs are `left · T · right`;
  - a one-parameter side's one-hot is the identity, so it is skipped, and a table of two
    one-parameter blocks is the pair's table itself;
  - a block pair whose joint table would exceed JOINT_CELLS (a large parameter beside a block) is
    scattered pair by pair instead, each into its own B_i·B_j cells.
- At 8 values and d = 20 a pass scatters the rows 55 times, not 210.
- With `triples` (the coarse decomposition, Task 5) every triple i < j < k follows the pairs, one
  scatter each, keyed by the pair key of (i, j) (stored once per pair, as small as it fits) and
  X_k: 1,140 scatters at d = 20 on the coarse grid's 64-cell triples.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

# A block of parameters holds at most this many joint cells, so a block pair's table (at most
# 4,096 cells, 32 KB) stays in cache while the rows are scattered into it.
BLOCK_CELLS = 64
# A block pair's joint table above this many cells (128 KB) is scattered pair by pair. A scatter's
# cost per row rises once its table leaves the core's cache, while the pairs' own tables stay
# small. Measured at 50,000 rows on this laptop: equal within noise from 19,200 to 64,000 cells,
# while splitting is 1.2× to 2.5× faster from 128,000 to 1,280,000 cells.
JOINT_CELLS = 1 << 14
_CONSTANT = 1e-12  # Y is constant when its spread is below this relative to its magnitude
_TINY = np.finfo(np.float64).tiny
_INT16_MAX = int(np.iinfo(np.int16).max)
# The fine stage's families (decision 18): the mains, and the increments over all ordered pairs.
MAINS = "mains"
INCREMENTS = "increments"


def parameter_blocks(B: Sequence[int]) -> list[list[int]]:
    """Consecutive parameters grouped while their joint cells stay within BLOCK_CELLS; a
    parameter larger than that is a block alone."""
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
class Scatter:
    """One scatter of the rows per pass into `bins` cells, keyed `first` or
    `first · factor + second`. Its table becomes grid cells times `margin` (a block's mains and
    inner pairs), or as `left · T · right` with T reshaped to `shape` (a block pair's cross pairs,
    a side None when it is one parameter), or as it is (one parameter, or one pair)."""

    first: np.ndarray
    second: np.ndarray | None
    factor: int
    bins: int
    margin: np.ndarray | None = None
    shape: tuple[int, int] | None = None
    left: np.ndarray | None = None
    right: np.ndarray | None = None


@dataclass(frozen=True, eq=False)
class Design:
    """X's grids for one pass: its `scatters`, in order. The flat grid cells are the mains, then
    the pairs i < j in `np.triu_indices` order (a pair's cell `X_i · B_j + X_j`): `starts` is each
    grid's first cell, `dest` the flat cell of each concatenated scatter output (None when they
    arrive in grid order). With each row once: `counts` the rows per cell, `divisor` the counts
    with every empty cell's 0 raised to the smallest float (its sum is exactly 0, so it divides
    to 0), `tested` each grid's cells holding rows."""

    scatters: tuple[Scatter, ...]
    dest: np.ndarray | None
    starts: np.ndarray
    size: int
    counts: np.ndarray
    divisor: np.ndarray
    tested: np.ndarray
    buffer: np.ndarray  # one scatter's keys, rewritten in every pass


def _one_hot(cell: np.ndarray, width: int) -> np.ndarray:
    """(len(cell) × width): 1 where a joint cell's value is the column."""
    out = np.zeros((len(cell), width))
    out[np.arange(len(cell)), cell] = 1.0
    return out


def design_of(
    X: np.ndarray, B: Sequence[int], *, pairs: bool = True, triples: bool = False
) -> Design:
    """X's `Design` over parameters of `B` values: the mains and, with `pairs`, every pair; with
    `triples` (which needs `pairs`), every triple i < j < k after them, in
    `itertools.combinations` order, a triple's cell `(X_i · B_j + X_j) · B_k + X_k`."""
    n, d = X.shape
    B = [int(b) for b in B]
    if triples and not pairs:
        raise ValueError("a design with triples needs its pairs")
    groups = parameter_blocks(B)
    upper = [(int(i), int(j)) for i, j in zip(*np.triu_indices(d, 1), strict=True)] if pairs else []
    trios = list(itertools.combinations(range(d), 3)) if triples else []
    grid = {(i, i): i for i in range(d)} | {pair: g for g, pair in enumerate(upper, start=d)}
    starts = np.cumsum(
        [
            0,
            *(B[i] for i in range(d)),
            *(B[i] * B[j] for i, j in upper),
            *(B[i] * B[j] * B[k] for i, j, k in trios),
        ]
    )
    columns: dict[int, np.ndarray] = {}

    def column(i: int) -> np.ndarray:
        if i not in columns:
            columns[i] = np.asarray(X[:, i], dtype=np.intp)
        return columns[i]

    def cells_of(i: int, j: int) -> np.ndarray:
        return starts[grid[(i, j)]] + np.arange(B[i] * B[j] if i != j else B[i])

    keys, cells, sides, scatters, dest = [], [], [], [], []
    for members in groups:
        shape = tuple(B[i] for i in members)
        cells.append(math.prod(shape))
        if len(members) == 1:
            (i,) = members
            keys.append(column(i))
            sides.append(None)
            scatters.append(Scatter(keys[-1], None, 1, B[i]))
            dest.append(cells_of(i, i))
            continue
        key = np.zeros(n, dtype=np.intp)
        for i in members:
            key *= B[i]
            key += column(i)
        keys.append(key)
        at = dict(zip(members, np.indices(shape).reshape(len(shape), -1), strict=True))
        side = np.hstack([_one_hot(at[i], B[i]) for i in members])
        sides.append(side)
        margin = [side]
        dest += [cells_of(i, i) for i in members]
        for k, i in enumerate(members if pairs else ()):
            for j in members[k + 1 :]:
                margin.append(_one_hot(at[i] * B[j] + at[j], B[i] * B[j]))
                dest.append(cells_of(i, j))
        scatters.append(Scatter(key, None, 1, cells[-1], margin=np.hstack(margin)))
    for p in range(len(groups) if pairs else 0):
        for q in range(p + 1, len(groups)):
            single = len(groups[p]) == len(groups[q]) == 1
            if single or cells[p] * cells[q] <= JOINT_CELLS:
                left = None if sides[p] is None else sides[p].T.copy()
                scatters.append(
                    Scatter(
                        keys[p],
                        keys[q],
                        cells[q],
                        cells[p] * cells[q],
                        shape=(cells[p], cells[q]),
                        left=left,
                        right=sides[q],
                    )
                )
                for i in groups[p]:  # the rows of left · T · right, member by member
                    row = np.concatenate(
                        [cells_of(i, j).reshape(B[i], B[j]) for j in groups[q]], axis=1
                    )
                    dest.append(row.ravel())
                continue
            for i in groups[p]:
                for j in groups[q]:
                    scatters.append(Scatter(column(i), column(j), B[j], B[i] * B[j]))
                    dest.append(cells_of(i, j))
    widest = max(B, default=1)
    pair_keys: dict[tuple[int, int], np.ndarray] = {}
    for g, (i, j, k) in enumerate(trios, start=d + len(upper)):
        if (i, j) not in pair_keys:
            # `cell_sums` multiplies the stored key by B_k in the key's own type: int16 holds every
            # product when B_i·B_j·max(B) does.
            fits = B[i] * B[j] * widest <= _INT16_MAX
            key = column(i) * B[j] + column(j)
            pair_keys[(i, j)] = key.astype(np.int16) if fits else key
        size = B[i] * B[j] * B[k]
        scatters.append(Scatter(pair_keys[(i, j)], column(k), B[k], size))
        dest.append(starts[g] + np.arange(size))
    flat = np.concatenate(dest) if dest else np.zeros(0, dtype=np.intp)
    size = int(starts[-1])
    if not np.array_equal(np.sort(flat), np.arange(size)):
        raise AssertionError("the scatters must fill every grid cell once")
    design = Design(
        scatters=tuple(scatters),
        dest=None if np.array_equal(flat, np.arange(size)) else flat,
        starts=starts[:-1],
        size=size,
        counts=np.zeros(0),
        divisor=np.zeros(0),
        tested=np.zeros(0),
        buffer=np.empty(n, dtype=np.intp),
    )
    counts = cell_sums(design, None)[0]
    return replace(
        design,
        counts=counts,
        divisor=np.maximum(counts, _TINY),
        tested=_tested(counts, design.starts),
    )


def _tested(counts: np.ndarray, starts: np.ndarray) -> np.ndarray:
    """Each grid's cells holding rows (positive weight)."""
    if not len(starts):
        return np.zeros(0)
    return np.add.reduceat(counts > 0, starts, dtype=np.float64)


def cell_sums(design: Design, *weights: np.ndarray | None) -> list[np.ndarray]:
    """Every grid cell's sum of each weight vector (None: the rows counted), flat."""
    parts: list[list[np.ndarray]] = [[] for _ in weights]
    buffer = design.buffer
    for scatter in design.scatters:
        key = scatter.first
        if scatter.second is not None:
            np.multiply(scatter.first, scatter.factor, out=buffer)
            np.add(buffer, scatter.second, out=buffer)
            key = buffer
        for k, w in enumerate(weights):
            table = np.bincount(key, weights=w, minlength=scatter.bins)
            if scatter.margin is not None:
                table = table @ scatter.margin
            elif scatter.left is not None or scatter.right is not None:
                table = table.reshape(scatter.shape)
                if scatter.left is not None:
                    table = scatter.left @ table
                if scatter.right is not None:
                    table = table @ scatter.right
                table = table.ravel()
            parts[k].append(table)
    out = []
    for tables in parts:
        flat = np.concatenate(tables).astype(np.float64, copy=False) if tables else np.zeros(0)
        if design.dest is not None:
            placed = np.empty(design.size)
            placed[design.dest] = flat
            flat = placed
        out.append(flat)
    return out


def adjusted_shares(
    design: Design, Y: np.ndarray, w: np.ndarray | None, *, clamp: bool = True
) -> np.ndarray:
    """Each grid's adjusted share of Y over the rows weighted by `w` (None: each row once), in
    grid order (module docstring). `clamp=False` keeps a negative adjusted share as it is: the
    coarse decomposition sums its terms into the residual, which clamping would bias (decision
    19); clamping at 0 is then for display only."""
    m = len(design.starts)
    if len(Y) < 2 or not m:
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
        (sums,) = cell_sums(design, weighted)
        divisor, cells = design.divisor, design.tested
    else:
        counts, sums = cell_sums(design, w, weighted)
        divisor, cells = np.maximum(counts, _TINY), _tested(counts, design.starts)
    # An empty cell's sum is exactly 0, so dividing by the smallest float gives its 0: the same
    # numbers as dividing the tested cells alone, without a masked division over every cell.
    between = np.multiply(sums, sums, out=sums)
    between /= divisor
    share = np.add.reduceat(between, design.starts) / sst
    room = total - cells
    adjusted = np.full(m, np.nan)
    fits = room > 0
    adjusted[fits] = share[fits] - (cells[fits] - 1.0) / room[fits] * (1.0 - share[fits])
    return np.maximum(adjusted, 0.0) if clamp else adjusted  # NaN stays NaN


def pair_matrix(S: np.ndarray, pairs: np.ndarray) -> np.ndarray:
    """The pair shares (i < j, `np.triu_indices` order) as a symmetric d × d matrix whose diagonal
    is the mains."""
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
    """The fine grid's statistic for `analytics.intervals` and `analytics.floors`: one pass over
    every main and, with `pairs`, every pair. Called as `fn(X, Y, w)` (`w` a resample's row
    multiplicities, None for each row once), it returns the mains `S` (d) without pairs, else one
    (2d + 1) × d array: the mains, then the pairs `J` (d × d), then the increments `Δ` (d × d);
    `fine_parts` splits it.

    The design of the last X seen is kept: `intervals` and `floors` pass the same X on every
    resample, so a resample costs one scatter per block, block pair or split pair (two for a
    bootstrap's counts and sums). X is never written to between calls (a cohort's arrays are
    read-only), and one instance serves one thread."""

    def __init__(self, B: Sequence[int], *, pairs: bool = True) -> None:
        self.B = tuple(int(b) for b in B)
        self.pairs = pairs
        self._held: tuple[np.ndarray, Design] | None = None

    def design(self, X: np.ndarray) -> Design:
        held = self._held
        if held is None or held[0] is not X:
            held = self._held = (X, design_of(X, self.B, pairs=self.pairs))
        return held[1]

    def __call__(self, X: np.ndarray, Y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
        shares = adjusted_shares(self.design(X), np.asarray(Y, dtype=np.float64), w)
        d = len(self.B)
        S = shares[:d]
        if not self.pairs:
            return S
        J = pair_matrix(S, shares[d:])
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


__all__ = [
    "BLOCK_CELLS",
    "INCREMENTS",
    "JOINT_CELLS",
    "MAINS",
    "Design",
    "FineTerms",
    "Scatter",
    "adjusted_shares",
    "cell_sums",
    "design_of",
    "fine_families",
    "fine_parts",
    "fine_shares",
    "incremental",
    "interaction",
    "pair_matrix",
    "parameter_blocks",
]
