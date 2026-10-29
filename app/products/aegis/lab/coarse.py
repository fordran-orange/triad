"""The Lab's coarse decomposition (Optimization Lab v2 spec §7.4; Phase 3 Task 5): every main,
pair and triple on one grid of q = COARSE_BINS bins per parameter, their own-direction triple
increments, and the residual the rule's veto reads.

- **The grid.** `coarse_bins` puts each parameter's value index v of B values in the lattice's
  quantile bin `⌊v · min(q, B) / B⌋`: consecutive values, ⌊B / q⌋ or ⌈B / q⌉ to a bin, the equal-
  count bins of the product design the rule requires. A parameter of fewer than q values keeps
  one bin per value. The bins depend on the lattice alone, never on the rows drawn.
- **One pass.** `CoarseTerms` is `shares.py`'s kernel with its triples (`design_of(...,
  triples=True)`) and the same share formula, **adjusted and unclamped** (decision 19): the
  terms are summed into R, which clamping biases (review B2: 1.00 to 0.76 on pure noise at
  d = 20). Clamping at 0 is for display only.
- **The terms.** `S_i`, `J_ij`, `J_ijk` the adjusted shares; `Δ_{i|j} = J_ij - S_j`; the three
  own-direction increments of a triple `Δ_{i|jk} = J_ijk - J_jk` (each parameter's proposal reads
  its own direction only, §7.4a condition 3); the interactions `I_ij = J_ij - S_i - S_j` and
  `I_ijk = J_ijk - J_ij - J_ik - J_jk + S_i + S_j + S_k`; and `R = 1 - ΣS - ΣI_pair - ΣI_triple`,
  all on the same grid. R is meaningful only for mutually independent inputs, which availability
  decides by provenance (`analytics.availability`).

Pure numpy; the resamples (`coarse_intervals`, `coarse_floors`) live in `analytics`, beside
`intervals` and `floors`.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from products.aegis.lab.policy import COARSE_BINS, TRIPLE_TOP
from products.aegis.lab.shares import (
    Design,
    adjusted_shares,
    design_of,
    incremental,
    pair_matrix,
)

# The coarse null's one family (decision 18): every own-direction triple increment.
TRIPLE_INCREMENTS = "triple increments"


def coarse_bins(X: np.ndarray, B: Sequence[int], q: int = COARSE_BINS) -> np.ndarray:
    """Each parameter's value indices (X, n × d, of B_i values) in the lattice's `q` quantile
    bins, `⌊v · min(q, B_i) / B_i⌋` (module docstring), as a read-only int16 array."""
    sizes = np.asarray(B, dtype=np.int64)
    bins = np.minimum(sizes, q)
    binned = (np.asarray(X, dtype=np.int64) * bins) // np.maximum(sizes, 1)
    out = binned.astype(np.int16)
    out.setflags(write=False)
    return out


def coarse_sizes(Xq: np.ndarray) -> np.ndarray:
    """The bins each parameter's coarse indices span (at least one), the grid `CoarseTerms`
    keys on."""
    if not len(Xq):
        return np.ones(Xq.shape[1], dtype=np.int64)
    return np.asarray(Xq, dtype=np.int64).max(axis=0) + 1


def triple_index(d: int) -> np.ndarray:
    """Every triple i < j < k of d parameters, in `itertools.combinations` order (t × 3)."""
    trios = list(itertools.combinations(range(d), 3))
    return np.array(trios, dtype=np.intp).reshape(len(trios), 3)


class CoarseParts(NamedTuple):
    """A `CoarseTerms` vector (or its bounds or floors) split: the residual `R`, the mains `S`
    (d), the pairs `J` (d × d, the mains on its diagonal), the pair increments `D` (d × d,
    `D[i, j] = Δ_{i|j}`), the triple shares `T` (t) and the increments (t × 3: `Δ_{i|jk}`,
    `Δ_{j|ik}`, `Δ_{k|ij}` of triple (i, j, k))."""

    R: float
    S: np.ndarray
    J: np.ndarray
    D: np.ndarray
    T: np.ndarray
    increments: np.ndarray


def _length(d: int) -> int:
    t = math.comb(d, 3)
    return 1 + d + 2 * d * d + 4 * t


def coarse_parts(vector: np.ndarray, d: int) -> CoarseParts:
    """`CoarseTerms`' flat vector as its `CoarseParts`."""
    vector = np.asarray(vector)
    if vector.shape != (_length(d),):
        raise ValueError(f"a coarse vector of d = {d} has {_length(d)} entries, not {vector.shape}")
    t = math.comb(d, 3)
    at = np.cumsum([1, d, d * d, d * d, t])
    return CoarseParts(
        R=float(vector[0]),
        S=vector[at[0] : at[1]],
        J=vector[at[1] : at[2]].reshape(d, d),
        D=vector[at[2] : at[3]].reshape(d, d),
        T=vector[at[3] : at[4]],
        increments=vector[at[4] :].reshape(t, 3),
    )


def coarse_families(d: int) -> dict[str, np.ndarray]:
    """The coarse null's family over a `CoarseTerms` vector: the own-direction triple increments.
    No rule reads a coarse main or pair against a floor."""
    mask = np.zeros(_length(d), dtype=bool)
    mask[_length(d) - 3 * math.comb(d, 3) :] = True
    return {TRIPLE_INCREMENTS: mask}


class CoarseTerms:
    """The coarse grid's statistic for `analytics.intervals` and `analytics.floors`: one pass
    over every main, pair and triple of a coarse index matrix whose parameters span `sizes` bins.
    Called as `fn(Xq, Y, w)` (`w` a resample's row multiplicities, None for each row once), it
    returns one flat vector: `[R, S, J, D, T, increments]` (`coarse_parts`).

    The design of the last Xq seen is kept, as `FineTerms` keeps its own: the resamples pass the
    same read-only Xq every time. One instance serves one thread."""

    def __init__(self, sizes: Sequence[int]) -> None:
        self.sizes = tuple(int(s) for s in sizes)
        d = len(self.sizes)
        self.trios = triple_index(d)
        self.upper = np.triu_indices(d, 1)
        self._held: tuple[np.ndarray, Design] | None = None

    def design(self, Xq: np.ndarray) -> Design:
        held = self._held
        if held is None or held[0] is not Xq:
            held = self._held = (Xq, design_of(Xq, self.sizes, pairs=True, triples=True))
        return held[1]

    def __call__(self, Xq: np.ndarray, Y: np.ndarray, w: np.ndarray | None = None) -> np.ndarray:
        shares = adjusted_shares(self.design(Xq), np.asarray(Y, dtype=np.float64), w, clamp=False)
        d = len(self.sizes)
        pairs = d * (d - 1) // 2
        S = shares[:d]
        J = pair_matrix(S, shares[d : d + pairs])
        T = shares[d + pairs :]
        a, b, c = self.trios.T
        increments = np.stack([T - J[b, c], T - J[a, c], T - J[a, b]], axis=1)
        i, j = self.upper
        I2 = J[i, j] - S[i] - S[j]
        I3 = T - J[a, b] - J[a, c] - J[b, c] + S[a] + S[b] + S[c]
        R = 1.0 - S.sum() - I2.sum() - I3.sum()
        return np.concatenate([[R], S, J.ravel(), incremental(S, J).ravel(), T, increments.ravel()])


def own_cube(increments: np.ndarray, trios: np.ndarray, d: int) -> np.ndarray:
    """The triples' increments as a (d, d, d) array: `[i, j, k] = Δ_{i|jk}` for every three
    distinct parameters (symmetric in j and k), NaN elsewhere."""
    cube = np.full((d, d, d), np.nan)
    a, b, c = trios.T
    for p, (own, x, y) in enumerate(((a, b, c), (b, a, c), (c, a, b))):
        cube[own, x, y] = increments[:, p]
        cube[own, y, x] = increments[:, p]
    return cube


@dataclass(frozen=True, eq=False)
class Coarse:
    """The coarse decomposition's point estimates (module docstring), every term adjusted and
    unclamped: `S` (d), `J` (d × d, the mains on its diagonal), `D` (d × d, `Δ_{i|j}`), `Delta3`
    (d, d, d) the own-direction increments `Δ_{i|jk}` (NaN unless i, j, k are distinct), `R` the
    residual, and `lo` / `hi` R's re-centred interval once the coarse bootstrap has run (NaN
    before). `triples` (t × 3), `T` (t) and `increments` (t × 3) are the same triples compactly,
    in `triple_index` order."""

    S: np.ndarray
    J: np.ndarray
    D: np.ndarray
    Delta3: np.ndarray
    R: float
    triples: np.ndarray
    T: np.ndarray
    increments: np.ndarray
    lo: float = math.nan
    hi: float = math.nan


def coarse(Xq: np.ndarray, Y: np.ndarray) -> Coarse:
    """The coarse decomposition of Y over the coarse index matrix Xq (`coarse_bins`): one pass."""
    d = Xq.shape[1]
    fn = CoarseTerms(coarse_sizes(Xq))
    parts = coarse_parts(fn(Xq, Y), d)
    return Coarse(
        S=parts.S,
        J=parts.J,
        D=parts.D,
        Delta3=own_cube(parts.increments, fn.trios, d),
        R=parts.R,
        triples=fn.trios,
        T=parts.T,
        increments=parts.increments,
    )


def triples_top(found: Coarse, k: int = TRIPLE_TOP) -> list[tuple[int, int, int]]:
    """The `k` triples with the largest own-direction increment `Δ^c` (an undefined one last), for
    display (§7.4); ties keep `triple_index` order."""
    increments = np.where(np.isnan(found.increments), -np.inf, found.increments)
    score = increments.max(axis=1) if len(increments) else np.zeros(0)
    order = np.argsort(-score, kind="stable")[:k]
    return [tuple(int(v) for v in found.triples[t]) for t in order]


__all__ = [
    "TRIPLE_INCREMENTS",
    "Coarse",
    "CoarseParts",
    "CoarseTerms",
    "coarse",
    "coarse_bins",
    "coarse_families",
    "coarse_parts",
    "coarse_sizes",
    "own_cube",
    "triple_index",
    "triples_top",
]
