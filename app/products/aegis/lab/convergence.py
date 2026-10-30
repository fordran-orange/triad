"""Convergence (Optimization Lab v2 spec §7.10, Phase 3 Task 8; decision 7): best-so-far and the
robust-region median, per batch. Labelled provisional while the source runs. Never extrapolated.

Pure: numpy over a block-0 `TrialFrame`. A view of the filter's completed trials with a defined
metric, by trial number; an undefined value is never ranked, so it takes no place in either series
and no batch's top (the scope counts it).

- **`best`** is the best value so far at each trial, at most CONVERGENCE_MAX_POINTS, evenly spaced
  with the last point kept. §7.10 puts no floor on it, so it is there from the first trial, for the
  compact sparkline, even while the panel reads empty.
- **`robust`** has one entry per complete batch of CONVERGENCE_BATCH such trials: the median and
  quartiles of the neighbourhood P25 of the batch's top CONVERGENCE_TOP. A partial batch has no
  entry, its trials counted in `partial`. A top trial with no tested neighbour has no P25: `measured`
  says how many had one, and a batch with none holds no value. Past CONVERGENCE_MAX_POINTS batches
  the series is thinned evenly too, and the basis line says so.
- **The panel's state.** §5's `P "provisional"; < 2 batches: empty`: below MIN_BATCHES complete
  batches, `empty` is the reason (`robust_reason`); with no defined value at all, it says that.
- **What the filter touches.** It selects each batch's top trials. Their neighbours read every
  completed block-0 trial of the snapshot, as every neighbourhood does (`neighbours.py`), because a
  brush would otherwise make a tested neighbour read as untested. A batch counts filtered trials
  with a defined value, so one that left trials out spans more raw trials. The basis line says both.
- **Units.** Both series are in the metric's own units, with `orientation` beside them; for a
  minimized metric the neighbourhood P25 reads the worse side, and `p25` ≤ `p75` still holds.
- **What a snapshot fixes.** `convergence_payload` is all of that, so `sources` caches it (the cost
  of the robust series, repeated on every poll, is the reason). `provisional` follows the source's
  status, which moves without the snapshot, so it is never in that dict: `convergence_view` adds it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from products.aegis.lab.neighbours import PositionLookup, default_m
from products.aegis.lab.policy import (
    CONVERGENCE_BATCH,
    CONVERGENCE_MAX_POINTS,
    CONVERGENCE_TOP,
    MIN_BATCHES,
    NEIGHBOUR_R,
)
from products.aegis.lab.query import (
    BASIS_EXACT,
    LOWER_IS_BETTER,
    LabFilter,
    TrialFrame,
    _completed,
    _Groups,
    _optional,
    defined_rows,
    even_positions,
    metric_column,
)

if TYPE_CHECKING:
    from products.aegis.lab.index import FrameIndex

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


def _basis(metric: str, *, left_out: int, batches: int, robust: int, best: int, total: int) -> str:
    """The line the scope states: what is exact, which rows the neighbours read, and each way the
    series shown differ from every trial. `left_out` counts the completed trials in no batch's
    count, the filter's and the undefined; a clause about batches needs a batch to describe."""
    parts = [BASIS_EXACT, NEIGHBOURS]
    if robust and left_out:
        parts.append(
            f"each batch counts {CONVERGENCE_BATCH} filtered trials with a defined {metric}, "
            "so it spans more raw trials"
        )
    if best < total:
        parts.append(f"best-so-far thinned evenly to {best} of {total} points")
    if 0 < robust < batches:
        parts.append(f"robust thinned evenly to {robust} of {batches} batches")
    return "; ".join(parts)


def convergence_payload(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    metric: str,
    scope: str,
    index: FrameIndex | None = None,
) -> dict:
    """All of the view that one snapshot, filter, scope and metric fix (module docstring): the view
    without `provisional`, which follows the source's status."""
    column = metric_column(scope, metric)
    rows, values, numbers, _ = defined_rows(frame, flt, column, index=index)
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
    reason = empty = None
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
        empty = reason if total else f"no trial has a defined {metric}"
    return {
        "metric": column,
        "orientation": orientation,
        "best": best,
        "best_total": total,
        "robust": robust,
        "robust_reason": reason,
        "batches": batches,
        "partial": total - batches * CONVERGENCE_BATCH,
        "r": NEIGHBOUR_R,
        "m": default_m(frame),
        "basis": _basis(
            metric,
            left_out=int(_completed(frame, index).sum()) - total,
            batches=batches,
            robust=len(robust),
            best=len(shown),
            total=total,
        ),
        "empty": empty,
        "constants": {
            "CONVERGENCE_BATCH": CONVERGENCE_BATCH,
            "CONVERGENCE_TOP": CONVERGENCE_TOP,
            "CONVERGENCE_MAX_POINTS": CONVERGENCE_MAX_POINTS,
            "MIN_BATCHES": MIN_BATCHES,
            "NEIGHBOUR_R": NEIGHBOUR_R,
        },
    }


def convergence_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    metric: str,
    scope: str,
    index: FrameIndex | None = None,
) -> dict:
    """`best` as `[trial_no, value]` pairs and `robust` as batches (module docstring), in `scope`'s
    metric column, labelled `provisional` while the source runs. `best_total` is how many trials
    `best` thinned from, `batches` the complete batches, `r` and `m` the reach their neighbourhoods
    read."""
    payload = convergence_payload(frame, flt, metric=metric, scope=scope, index=index)
    return {**payload, "provisional": frame.provisional}


__all__ = ["NEIGHBOURS", "convergence_payload", "convergence_view"]
