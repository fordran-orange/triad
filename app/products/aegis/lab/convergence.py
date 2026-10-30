"""Convergence (Optimization Lab v2 spec §7.10, Phase 3 Task 8; decision 7): best-so-far and the
robust-region median, per batch. Labelled provisional while the source runs. Never extrapolated.

Pure: numpy over a block-0 `TrialFrame`. A view of the filter's completed trials with a defined
metric, by trial number; an undefined value is never ranked, so it takes no place in either series
and no batch's top (the scope counts it).

- **`best`** is the best value so far at each trial, at most CONVERGENCE_MAX_POINTS, evenly spaced
  with the last point kept. §7.10 puts no floor on it, so it is there from the first trial.
- **`robust`** has one entry per complete batch of CONVERGENCE_BATCH such trials: the median and
  quartiles of the neighbourhood P25 of the batch's top CONVERGENCE_TOP. A partial batch has no
  entry, its trials counted in `partial`, and fewer than two complete batches leave the series empty
  with `robust_reason` saying so (the spec's `< 2 batches: empty`). A top trial with no tested
  neighbour has no P25: `measured` says how many had one, and a batch with none holds no value.
- **What the filter touches.** It selects each batch's top trials. Their neighbours read every
  completed block-0 trial of the snapshot, as every neighbourhood does (`neighbours.py`), because a
  brush would otherwise make a tested neighbour read as untested. The basis line says so.
- **Units.** Both series are in the metric's own units, with `orientation` beside them; for a
  minimized metric the neighbourhood P25 reads the worse side, and `p25` ≤ `p75` still holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from products.aegis.lab.neighbours import PositionLookup, default_m
from products.aegis.lab.policy import (
    CONVERGENCE_BATCH,
    CONVERGENCE_MAX_POINTS,
    CONVERGENCE_TOP,
    NEIGHBOUR_R,
)
from products.aegis.lab.query import (
    BASIS_EXACT,
    LOWER_IS_BETTER,
    LabFilter,
    TrialFrame,
    _Groups,
    _numbers,
    _optional,
    _trial_numbers,
    even_positions,
    filter_mask,
    metric_column,
)

if TYPE_CHECKING:
    from products.aegis.lab.index import FrameIndex

MIN_BATCHES = 2
NEIGHBOURS = (
    "neighbours read every completed block-0 trial of the snapshot, "
    "the filter selects each batch's top trials"
)


def _robust(
    frame: TrialFrame,
    rows: np.ndarray,
    oriented: np.ndarray,
    *,
    metric: str,
    scope: str,
    orientation: int,
    index: FrameIndex | None,
) -> list[dict]:
    """The robust series over `rows`, the defined trials by trial number: one lookup for all the
    batches' top trials, and one grouping for their quartiles."""
    size = CONVERGENCE_BATCH
    top = max(1, round(CONVERGENCE_TOP * size))
    batches = even_positions(len(rows) // size, CONVERGENCE_MAX_POINTS)
    candidates = np.empty((len(batches), top), dtype=np.int64)
    for place, batch in enumerate(batches.tolist()):  # a loop over the batches sent
        start = batch * size
        best_first = np.argsort(-oriented[start : start + size], kind="stable")
        candidates[place] = rows[start : start + size][best_first[:top]]
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    groups = _Groups(
        np.repeat(np.arange(len(batches)), top),
        lookup.p25_around(candidates.ravel()),
        len(batches),
    )
    median = groups.median()
    lower, upper = groups.quantile(0.25), groups.quantile(0.75)
    if orientation < 0:  # back to the metric's own units, where the quartiles change places
        median, lower, upper = -median, -upper, -lower
    last = lookup.trial_numbers[rows[batches * size + size - 1]].tolist()
    return [
        {
            "batch": batch,
            "trial_no": trial_no,
            "median": value,
            "p25": low,
            "p75": high,
            "top": top,
            "measured": measured,
        }
        for batch, trial_no, value, low, high, measured in zip(
            batches.tolist(),
            last,
            _optional(median),
            _optional(lower),
            _optional(upper),
            groups.m.tolist(),
            strict=True,
        )
    ]


def convergence_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    metric: str,
    scope: str,
    index: FrameIndex | None = None,
) -> dict:
    """`best` as `[trial_no, value]` pairs and `robust` as batches (module docstring), in `scope`'s
    metric column. `best_total` is how many trials `best` thinned from, `batches` the complete
    batches, `r` and `m` the reach their neighbourhoods read."""
    column = metric_column(scope, metric)
    table = frame.table
    members = np.flatnonzero(filter_mask(frame, flt, index=index))
    values = _numbers(table, column)[members]
    defined = np.isfinite(values)
    rows, values = members[defined], values[defined]
    numbers = _trial_numbers(table)[rows]
    by_trial = np.argsort(numbers, kind="stable")
    rows, values, numbers = rows[by_trial], values[by_trial], numbers[by_trial]
    orientation = -1 if metric in LOWER_IS_BETTER else 1
    oriented = orientation * values
    total = len(rows)
    shown = even_positions(total, CONVERGENCE_MAX_POINTS)
    best_so_far = orientation * np.maximum.accumulate(oriented)
    best = [
        [trial_no, value]
        for trial_no, value in zip(
            numbers[shown].tolist(), best_so_far[shown].tolist(), strict=True
        )
    ]
    batches = total // CONVERGENCE_BATCH
    robust: list[dict] = []
    reason = None
    if batches >= MIN_BATCHES:
        robust = _robust(
            frame,
            rows,
            oriented,
            metric=metric,
            scope=scope,
            orientation=orientation,
            index=index,
        )
    else:
        reason = (
            f"fewer than {MIN_BATCHES} complete batches of {CONVERGENCE_BATCH} trials "
            f"with a defined {metric} ({total} so far)"
        )
    basis = f"{BASIS_EXACT}; {NEIGHBOURS}"
    if total > CONVERGENCE_MAX_POINTS:
        basis += f"; best-so-far thinned evenly to {len(shown)} of {total} points"
    return {
        "metric": column,
        "orientation": orientation,
        "best": best,
        "best_total": total,
        "robust": robust,
        "robust_reason": reason,
        "batches": batches,
        "partial": total - batches * CONVERGENCE_BATCH,
        "provisional": frame.provisional,
        "r": NEIGHBOUR_R,
        "m": default_m(frame),
        "basis": basis,
        "empty": f"no trial has a defined {metric}" if not total and len(members) else None,
        "constants": {
            "CONVERGENCE_BATCH": CONVERGENCE_BATCH,
            "CONVERGENCE_TOP": CONVERGENCE_TOP,
            "CONVERGENCE_MAX_POINTS": CONVERGENCE_MAX_POINTS,
            "NEIGHBOUR_R": NEIGHBOUR_R,
        },
    }


__all__ = ["NEIGHBOURS", "convergence_view"]
