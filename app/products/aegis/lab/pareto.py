"""Pareto selection (Optimization Lab v2 spec §7.7, Phase 3 Task 8; decision 7).

Pure: numpy over a `TrialFrame`'s columns. The rows are the observed completed trials of the
filter; a trial with an undefined objective is compared with nothing and counted in `excluded`, so
`front_size + dominated + excluded` is the scope's `filtered`.

**Dominance.** A point dominates another when it is at least as good on every objective and better
on one, so an equal point never dominates: every copy of a front point is on the front. The two
fronts work on oriented values, larger better; the view orients `query.LOWER_IS_BETTER` and sends
each value in its metric's own units, with `orientation` beside them.

**Drawing.** At most PARETO_FRONT_MAX exact front points, evenly along the first objective with both
ends kept, labelled `Sampled subset (n of N)` beyond that; `front_size` stays the true size. A
PARETO_DENSITY_BINS square bitmap holds the dominated cloud over the first two objectives, on the
range of every defined trial, so the front points share its frame.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from products.aegis.lab.policy import PARETO_DENSITY_BINS, PARETO_FRONT_MAX
from products.aegis.lab.query import (
    BASIS_EXACT,
    LOWER_IS_BETTER,
    LabFilter,
    TrialFrame,
    _grid,
    _numbers,
    _trial_numbers,
    aggregated_basis,
    even_positions,
    filter_mask,
    metric_column,
)

if TYPE_CHECKING:
    from products.aegis.lab.index import FrameIndex

OBJECTIVES_MIN = 2
OBJECTIVES_MAX = 3
_PAIRWISE = 256  # a block of the 3-D stream this small is compared point by point


def _checked(*objectives: Sequence[float]) -> list[np.ndarray]:
    """The objectives as float64, of one length and finite: an undefined value is the caller's to
    exclude, since no comparison with it means anything."""
    arrays = [np.asarray(values, dtype=np.float64) for values in objectives]
    if len({len(values) for values in arrays}) != 1:
        raise ValueError("objectives of different lengths")
    if not all(np.isfinite(values).all() for values in arrays):
        raise ValueError("an objective holds a value that is not finite")
    return arrays


def front_2d(a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    """The rank-1 front of two oriented objectives, as increasing indices (a sort plus a sweep,
    O(n log n)): down the values of `a`, a value's best `b` is on the front when it beats every `b`
    of a larger `a`, with each point that holds it."""
    a, b = _checked(a, b)
    if not len(a):
        return np.empty(0, dtype=np.int64)
    order = np.argsort(a)[::-1]
    by_a, by_b = a[order], b[order]
    starts = np.flatnonzero(np.r_[True, by_a[1:] != by_a[:-1]])
    best = np.maximum.reduceat(by_b, starts)
    beaten = np.r_[-np.inf, np.maximum.accumulate(best)[:-1]]
    group = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(by_a)]))
    return np.sort(order[(best > beaten)[group] & (by_b == best[group])])


def _covered(b: np.ndarray, c: np.ndarray, by_b: np.ndarray, by_c: np.ndarray) -> np.ndarray:
    """Per point of (b, c), whether some point of (by_b, by_c) is at least as large on both: one
    `np.searchsorted` into the block's values of b, each reading the best c from there up."""
    order = np.argsort(by_b)
    held = by_b[order]
    best = np.maximum.accumulate(by_c[order][::-1])[::-1]
    at = np.searchsorted(held, b)
    out = np.zeros(len(b), dtype=bool)
    inside = at < len(held)
    out[inside] = best[at[inside]] >= c[inside]
    return out


def _skyline(b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Over distinct points in stream order, the ones no earlier point covers on (b, c). The stream
    is cut into nested blocks: a block's earlier half is settled first, its survivors filter the
    later half in one vector pass, and what is left of that half is settled against itself, down
    to blocks small enough to compare pairwise. Later points can never cover earlier ones here, and
    a covered point is covered by a survivor, so survivors are all a block needs to keep."""
    n = len(b)
    if n <= _PAIRWISE:
        covers = (b[:, None] >= b) & (c[:, None] >= c)  # [i, j]: i is at least j on both
        return ~np.triu(covers, 1).any(axis=0)
    half = n // 2
    keep = np.zeros(n, dtype=bool)
    keep[:half] = earlier = _skyline(b[:half], c[:half])
    rest = half + np.flatnonzero(
        ~_covered(b[half:], c[half:], b[:half][earlier], c[:half][earlier])
    )
    keep[rest] = _skyline(b[rest], c[rest])
    return keep


def front_3d(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> np.ndarray:
    """The rank-1 front of three oriented objectives, as increasing indices: sorted by `a`, then
    `b`, then `c`, all descending, plus a block-nested skyline over that stream (`_skyline`).

    In that order a later point is never better than an earlier one unless it is equal, so equal
    points are folded first, and an earlier distinct point dominates a later one exactly when it is
    at least as large on `b` and `c` (it already is on `a`). Every copy of a front point is on the
    front. O(n log² n) however large the front, with most blocks settled by the first filter."""
    a, b, c = _checked(a, b, c)
    if not len(a):
        return np.empty(0, dtype=np.int64)
    order = np.lexsort((c, b, a))[::-1]
    by_a, by_b, by_c = a[order], b[order], c[order]
    distinct = np.r_[
        True, (by_a[1:] != by_a[:-1]) | (by_b[1:] != by_b[:-1]) | (by_c[1:] != by_c[:-1])
    ]
    keep = _skyline(by_b[distinct], by_c[distinct])
    return np.sort(order[keep[np.cumsum(distinct) - 1]])


def checked_objectives(objectives: Sequence[str]) -> list[str]:
    """§7.7's two or three chosen metrics, none twice; whether each exists is `metric_column`'s."""
    names = list(objectives)
    if not OBJECTIVES_MIN <= len(names) <= OBJECTIVES_MAX:
        raise ValueError(
            f"a Pareto front reads {OBJECTIVES_MIN} or {OBJECTIVES_MAX} objectives, "
            f"not {len(names)}"
        )
    if len(set(names)) != len(names):
        raise ValueError("an objective is named twice")
    return names


def _range_of(values: np.ndarray) -> tuple[float, float]:
    """A bitmap axis's range: its values', widened by 0.5 each way when they are one value (as
    numpy's histogram widens it)."""
    low, high = float(values.min()), float(values.max())
    return (low - 0.5, high + 0.5) if low == high else (low, high)


def _bins(values: np.ndarray, low: float, high: float) -> np.ndarray:
    """Equal-width bins over [low, high], the last one closed: the top edge is in, nothing is out."""
    at = ((values - low) / (high - low) * PARETO_DENSITY_BINS).astype(np.int64)
    return np.minimum(at, PARETO_DENSITY_BINS - 1)


def _density(names: list[str], x: np.ndarray, y: np.ndarray, cloud: np.ndarray) -> dict:
    """The dominated cloud's bitmap, `counts[y][x]` with both axes ascending. It sums to the cloud;
    its range is every defined trial's, the front's included."""
    bins = PARETO_DENSITY_BINS
    size = bins * bins
    density: dict = {"bins": bins, "axes": names[:2], "x": None, "y": None}
    counts = np.zeros(size, dtype=np.int64)
    if len(x):
        low_x, high_x = _range_of(x)
        low_y, high_y = _range_of(y)
        density.update(x=[low_x, high_x], y=[low_y, high_y])
        cell = _bins(y[cloud], low_y, high_y) * bins + _bins(x[cloud], low_x, high_x)
        counts = np.bincount(cell, minlength=size)
    density["counts"] = _grid(counts.tolist(), bins, bins)
    density["basis"] = aggregated_basis(int(cloud.sum()))
    return density


def pareto_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    objectives: Sequence[str],
    scope: str,
    index: FrameIndex | None = None,
) -> dict:
    """The rank-1 front of two or three objectives over the filter's completed trials, in `scope`'s
    metric columns (module docstring). `front` and `points` are aligned and hold at most
    PARETO_FRONT_MAX; `sampled` says when that is not all of `front_size`. `points[i].values` line
    up with `objectives`, `orientation` says which way each is better, and `basis` is the line the
    scope states."""
    names = checked_objectives(objectives)
    columns = [metric_column(scope, name) for name in names]
    table = frame.table
    members = np.flatnonzero(filter_mask(frame, flt, index=index))
    raw = np.stack([_numbers(table, column)[members] for column in columns])
    defined = np.isfinite(raw).all(axis=0)
    excluded = int((~defined).sum())
    rows, raw = members[defined], raw[:, defined]
    orientation = [-1 if name in LOWER_IS_BETTER else 1 for name in names]
    oriented = raw * np.array(orientation, dtype=np.float64)[:, None]
    picked = front_2d(*oriented) if len(names) == OBJECTIVES_MIN else front_3d(*oriented)
    front_size = len(picked)
    cloud = np.ones(len(rows), dtype=bool)
    cloud[picked] = False
    # Along the first objective, best first, so a capped front still has both its ends.
    along = np.lexsort(
        (_trial_numbers(table)[rows[picked]], -oriented[1][picked], -oriented[0][picked])
    )
    drawn = picked[along][even_positions(front_size, PARETO_FRONT_MAX)]
    numbers = _trial_numbers(table)[rows[drawn]].tolist()
    front = [f"{frame.source}#{number}" for number in numbers]
    values = raw[:, drawn].T.tolist()
    sampled = front_size > PARETO_FRONT_MAX
    return {
        "objectives": names,
        "orientation": orientation,
        "front": front,
        "front_size": front_size,
        "dominated": int(cloud.sum()),
        "excluded": excluded,
        "sampled": sampled,
        "points": [
            {"trial_id": trial, "values": held} for trial, held in zip(front, values, strict=True)
        ],
        "density": _density(names, raw[0], raw[1], cloud),
        "basis": f"Sampled subset ({len(front)} of {front_size})" if sampled else BASIS_EXACT,
        "empty": (
            f"no trial has every objective defined ({excluded} excluded)"
            if excluded and not len(rows)
            else None
        ),
        "constants": {
            "PARETO_FRONT_MAX": PARETO_FRONT_MAX,
            "PARETO_DENSITY_BINS": PARETO_DENSITY_BINS,
        },
    }


__all__ = ["checked_objectives", "front_2d", "front_3d", "pareto_view"]
