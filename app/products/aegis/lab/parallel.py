"""Parallel coordinates' exact mode (Optimization Lab v2 spec §7.9, Phase 3 Task 8; decision 8): a
stratified sample of actual trials. The aggregated mode, the default, is `query.parallel_view`.

Pure: numpy over a `TrialFrame`'s columns, seeded through `np.random.default_rng(seed)` with the seed
in the answer. The strata are the metric's deciles by rank, ties by trial number, so they hold equal
counts whatever the metric's ties: a value most trials share cannot empty one decile and swell
another. A trial with an undefined metric has no decile: it is counted in `excluded`, never drawn.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from products.aegis.lab.policy import PARALLEL_MAX_LINES, PARALLEL_STRATA
from products.aegis.lab.query import (
    LabFilter,
    TrialFrame,
    _numbers,
    _optional,
    checked_axes,
    defined_rows,
    metric_column,
)


def _quotas(sizes: np.ndarray, k: int, total: int) -> np.ndarray:
    """`k` lines shared over the strata in proportion to their sizes, the remainder to the largest
    fractions: never more than a stratum holds, and two strata of equal size differ by at most one."""
    quotas = sizes * k // total
    fractions = sizes * k % total
    lucky = np.argsort(-fractions, kind="stable")[: k - int(quotas.sum())]
    quotas[lucky] += 1
    return quotas


def _chosen(ranked: np.ndarray, k: int, seed: int) -> np.ndarray:
    """The increasing places of `k` of `ranked` (each place's rank), `k` below its length: per
    stratum, the first of a seeded shuffle."""
    total = len(ranked)
    strata = (ranked * PARALLEL_STRATA // total).astype(np.uint8)
    sizes = np.bincount(strata, minlength=PARALLEL_STRATA)
    shuffled = np.random.default_rng(seed).permutation(total)
    grouped = shuffled[np.argsort(strata[shuffled], kind="stable")]  # numpy's radix sort on uint8
    within = np.arange(total) - np.repeat(np.cumsum(sizes) - sizes, sizes)
    return np.sort(grouped[within < np.repeat(_quotas(sizes, k, total), sizes)])


def sample_view(
    frame: TrialFrame,
    flt: LabFilter,
    *,
    axes: Sequence[str],
    metric: str,
    k: int = PARALLEL_MAX_LINES,
    seed: int,
) -> dict:
    """At most `k` of the filter's completed trials with a defined metric, stratified by its decile
    (module docstring), by trial number: every one of them when they fit. Each line carries its
    trial's id, its values on `axes` and its metric. `sampled_from` is N, the trials it drew from.

    The bundle fields stay in the answer, empty: the client's `LabParallel` reads one shape."""
    axes = checked_axes(frame, axes)
    if not 1 <= k <= PARALLEL_MAX_LINES:
        raise ValueError(f"k must be between 1 and {PARALLEL_MAX_LINES}, not {k}")
    column = metric_column(flt.scope, metric)
    table = frame.table
    rows, values, numbers, excluded = defined_rows(frame, flt, column)
    total = len(rows)
    if total > k:
        ranked = np.empty(total, dtype=np.int64)
        ranked[np.argsort(values, kind="stable")] = np.arange(total)
        places = _chosen(ranked, k, seed)
        rows, values, numbers = rows[places], values[places], numbers[places]
    held = np.stack([_numbers(table, path)[rows] for path in axes], axis=1)
    lines = [
        {"trial_id": f"{frame.source}#{number}", "values": _optional(on_axes), "metric": value}
        for number, on_axes, value in zip(numbers.tolist(), held, values.tolist(), strict=True)
    ]
    return {
        "axes": axes,
        "metric": column,
        "lines": lines,
        "sampled_from": total,
        "strata": PARALLEL_STRATA,
        "seed": seed,
        "excluded": excluded,
        "bins": [],
        "bundles": [],
        "total_bundles": 0,
        "shown_bundles": 0,
        "basis": f"Sampled {len(lines)} of {total} (stratified by decile of {metric})",
        "constants": {"PARALLEL_MAX_LINES": PARALLEL_MAX_LINES, "PARALLEL_STRATA": PARALLEL_STRATA},
    }


__all__ = ["sample_view"]
