"""Peaks to plateaus (Mission 6 spec §7): the analysis of an experiment's cells.

Everything here is numpy over the cells table. A peak is a cell at or above every neighbour; a
plateau is the connected region within the tolerance of a peak; a peak whose plateau is too
small to count is fragile, one inside a counting plateau is supported. The recommendation is
the top plateau's centre, never the single best cell on its own. Main effects, interactions,
sensitivity, outcome clusters and the uncertainty statement complete the report.
"""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np
import pyarrow as pa

from products.aegis.surface import Grid

RESERVED = {"cell", "pass", "valid", "skip_reason", "elapsed_ms", "engine"}
SCOPE_PREFIXES = ("combined.", "long.", "short.")
CLUSTER_METRICS = ("net_return", "max_drawdown", "trade_count", "exposure")
NEIGHBOUR_SUBSAMPLE = 50_000
SILHOUETTE_FLOOR = 0.5
MIN_CLUSTER_CELLS = 20
NEIGHBOUR_RULES = {
    "exhaustive": "cells one step away in exactly one parameter",
    "sampled": "the 2d nearest run cells by distance in parameter space normalized by each range",
}


# --- rows ------------------------------------------------------------------------------------


def _columns(rows: pa.Table | list[dict]) -> dict[str, list]:
    if isinstance(rows, pa.Table):
        return {name: rows.column(name).to_pylist() for name in rows.column_names}
    if not rows:
        return {"cell": [], "valid": []}
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return {key: [row.get(key) for row in rows] for key in keys}


def _finite(value) -> bool:
    return value is not None and isinstance(value, int | float) and math.isfinite(float(value))


def _paths_of(columns: dict[str, list]) -> list[str]:
    return [
        key
        for key in columns
        if key not in RESERVED and not any(key.startswith(p) for p in SCOPE_PREFIXES)
    ]


def objective_values(
    columns: dict[str, list], objective: str
) -> tuple[dict[int, float], int, int, float]:
    """`({cell: oriented value}, skipped rows, valid rows with a null objective, sign)`; higher
    is always better after orientation (max drawdown is negated)."""
    sign = -1.0 if objective == "max_drawdown" else 1.0
    column = columns.get(f"combined.{objective}", [])
    values: dict[int, float] = {}
    skipped = 0
    nulls = 0
    for cell, valid, value in zip(columns["cell"], columns["valid"], column, strict=True):
        if not valid:
            skipped += 1
            continue
        if not _finite(value):
            nulls += 1
            continue
        values[int(cell)] = sign * float(value)
    return values, skipped, nulls, sign


# --- neighbours, peaks, plateaus ---------------------------------------------------------------


def neighbours_exhaustive(grid: Grid, run: list[int]) -> dict[int, list[int]]:
    present = set(run)
    return {cell: [n for n in grid.neighbours(cell) if n in present] for cell in run}


# A block of rows' difference cube (rows x n x D float64) holds at most this many bytes.
DISTANCE_BLOCK_BYTES = 32 * 1024 * 1024


def _block_rows(n: int, d: int) -> int:
    """How many rows' distances to all `n` points one block computes, within the byte bound."""
    return max(1, DISTANCE_BLOCK_BYTES // max(1, n * d * 8))


def _distances(block: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Each block row's Euclidean distance to every point: the differences squared in place,
    summed over the parameters, then the root (the arithmetic of `((a - b) ** 2).sum(axis=2)`,
    with one cube alive instead of two)."""
    cube = block[:, None, :] - points[None, :, :]
    np.square(cube, out=cube)
    return np.sqrt(cube.sum(axis=2))


def neighbours_sampled(grid: Grid, run: list[int], k: int) -> dict[int, list[int]]:
    """The `k` nearest run cells of each run cell by normalized Euclidean distance over parameter
    positions, ties by lower cell index; brute force in blocks of rows bounded by bytes (plan
    ruling P6, Phase 3 Task 0)."""
    cells = np.asarray(sorted(run), dtype=np.int64)
    n = len(cells)
    if n == 0:
        return {}
    scale = np.array([max(s - 1, 1) for s in grid.shape], dtype=np.float64)
    points = np.array([grid.positions(int(c)) for c in cells], dtype=np.float64) / scale
    k = min(k, n - 1)
    relation: dict[int, list[int]] = {}
    if k <= 0:
        return {int(c): [] for c in cells}
    rows = _block_rows(n, points.shape[1])
    for start in range(0, n, rows):
        block = points[start : start + rows]
        distances = _distances(block, points)
        for i in range(len(block)):
            row = distances[i].copy()
            row[start + i] = np.inf
            order = np.lexsort((cells, row))[:k]
            relation[int(cells[start + i])] = [int(cells[j]) for j in order]
    return relation


def peaks(values: dict[int, float], relation: dict[int, list[int]]) -> list[int]:
    """Local maxima, best first (ties by lower index): a cell at or above every neighbour that
    beats at least one of them, or that sits at the surface's maximum. Without the second clause
    every cell of a flat basin would be a peak and its basin would swallow the surface."""
    if not values:
        return []
    top = max(values.values())
    found = []
    for cell, value in values.items():
        around = [values[n] for n in relation.get(cell, []) if n in values]
        if all(value >= v for v in around) and (value >= top or any(value > v for v in around)):
            found.append(cell)
    return sorted(found, key=lambda cell: (-values[cell], cell))


def _plateau_of(
    peak: int, values: dict[int, float], relation: dict[int, list[int]], tau: float
) -> set[int]:
    floor = values[peak] - tau
    members = {peak}
    queue = deque([peak])
    while queue:
        cell = queue.popleft()
        for n in relation.get(cell, []):
            if n in values and n not in members and values[n] >= floor:
                members.add(n)
                queue.append(n)
    return members


def plateaus(
    values: dict[int, float],
    relation: dict[int, list[int]],
    found_peaks: list[int],
    tau: float,
    min_cells: int,
) -> list[dict]:
    """One plateau per group of peaks: breadth-first within the tolerance of the best peak;
    sets reached from several peaks are merged. Each carries its cells, size, median, iqr, its
    peaks and whether it counts (size ≥ min_cells)."""
    found: list[dict] = []
    for peak in found_peaks:
        if any(peak in p["cells"] for p in found):
            for plateau in found:
                if peak in plateau["cells"]:
                    plateau["peaks"].append(peak)
            continue
        members = _plateau_of(peak, values, relation, tau)
        touching = [plateau for plateau in found if members & plateau["cells"]]
        if touching:  # one plateau for every set the new one bridges (review finding 3)
            merged = touching[0]
            for other in touching[1:]:
                merged["cells"] |= other["cells"]
                merged["peaks"] += other["peaks"]
                found.remove(other)
            merged["cells"] |= members
            merged["peaks"].append(peak)
        else:
            found.append({"cells": members, "peaks": [peak]})
    out = []
    for plateau in found:
        cells = sorted(plateau["cells"])
        vals = np.array([values[c] for c in cells])
        p25, p75 = np.percentile(vals, [25, 75])
        out.append(
            {
                "cells": cells,
                "size": len(cells),
                "median": float(np.median(vals)),
                "iqr": float(p75 - p25),
                "peaks": sorted(set(plateau["peaks"]), key=lambda c: (-values[c], c)),
                "counts": len(cells) >= min_cells,
            }
        )
    return out


def _centre(grid: Grid, cells: list[int]) -> int:
    positions = np.array([grid.positions(c) for c in cells], dtype=np.float64)
    scale = np.array([max(s - 1, 1) for s in grid.shape], dtype=np.float64)
    target = np.median(positions, axis=0)
    distances = np.sqrt((((positions - target) / scale) ** 2).sum(axis=1))
    order = np.lexsort((np.array(cells), distances))
    return int(cells[order[0]])


def _cliff(
    values: dict[int, float], relation: dict[int, list[int]], cells: list[int], median: float
):
    members = set(cells)
    outside = [
        values[n] for c in cells for n in relation.get(c, []) if n in values and n not in members
    ]
    return float(median - min(outside)) if outside else None


# --- effects, interactions, sensitivity ---------------------------------------------------------


def _valid_rows(columns: dict[str, list], column: str) -> dict[str, np.ndarray]:
    keep = [
        i
        for i, (valid, value) in enumerate(zip(columns["valid"], columns[column], strict=True))
        if valid and _finite(value)
    ]
    return {key: np.asarray([series[i] for i in keep]) for key, series in columns.items()}


def main_effects(rows: pa.Table | list[dict], grid: Grid, column: str) -> dict[str, list[dict]]:
    """Per parameter and value: median, quartiles and count of `column` over the cells with that
    value (over all other parameters)."""
    columns = _columns(rows)
    kept = _valid_rows(columns, column)
    y = kept[column].astype(float)
    out: dict[str, list[dict]] = {}
    for k, path in enumerate(grid.paths):
        x = kept[path].astype(float)
        entries = []
        for value in grid.values[k]:
            mask = np.isclose(x, value)
            sample = y[mask]
            if len(sample):
                p25, p75 = np.percentile(sample, [25, 75])
                entries.append(
                    {
                        "value": value,
                        "median": float(np.median(sample)),
                        "p25": float(p25),
                        "p75": float(p75),
                        "count": len(sample),
                    }
                )
            else:
                entries.append(
                    {"value": value, "median": None, "p25": None, "p75": None, "count": 0}
                )
        out[path] = entries
    return out


def interactions(rows: pa.Table | list[dict], grid: Grid, column: str) -> list[dict]:
    """Per pair of parameters: the matrix of median `column` by their values and the strength,
    the variance of that matrix not explained by the additive fit of its row and column means."""
    columns = _columns(rows)
    kept = _valid_rows(columns, column)
    y = kept[column].astype(float)
    out = []
    d = len(grid.paths)
    for a in range(d):
        for b in range(a + 1, d):
            xa, xb = kept[grid.paths[a]].astype(float), kept[grid.paths[b]].astype(float)
            matrix = np.full((len(grid.values[a]), len(grid.values[b])), np.nan)
            for i, va in enumerate(grid.values[a]):
                mask_a = np.isclose(xa, va)
                for j, vb in enumerate(grid.values[b]):
                    sample = y[mask_a & np.isclose(xb, vb)]
                    if len(sample):
                        matrix[i, j] = np.median(sample)
            if np.isnan(matrix).all():
                strength = 0.0
            else:
                row_means = np.nanmean(matrix, axis=1, keepdims=True)
                col_means = np.nanmean(matrix, axis=0, keepdims=True)
                grand = np.nanmean(matrix)
                residual = matrix - (row_means + col_means - grand)
                strength = float(np.nanvar(residual)) if np.isfinite(residual).any() else 0.0
            out.append(
                {
                    "paths": [grid.paths[a], grid.paths[b]],
                    "values_a": list(grid.values[a]),
                    "values_b": list(grid.values[b]),
                    "matrix": [[None if np.isnan(v) else float(v) for v in row] for row in matrix],
                    "strength": strength,
                }
            )
    return sorted(out, key=lambda item: -item["strength"])


def sensitivity(rows: pa.Table | list[dict], grid: Grid, column: str) -> dict:
    """Each parameter's first-order share: the count-weighted variance of its main-effect medians
    over the variance of `column` across valid cells; the remainder is interactions and noise."""
    columns = _columns(rows)
    kept = _valid_rows(columns, column)
    y = kept[column].astype(float)
    total = float(np.var(y)) if len(y) else 0.0
    shares: dict[str, float] = {}
    for path, entries in main_effects(rows, grid, column).items():
        medians = np.array([e["median"] for e in entries if e["count"]], dtype=float)
        weights = np.array([e["count"] for e in entries if e["count"]], dtype=float)
        if total <= 0 or not len(medians):
            shares[path] = 0.0
            continue
        mean = float(np.average(medians, weights=weights))
        variance = float(np.average((medians - mean) ** 2, weights=weights))
        shares[path] = variance / total
    return {
        "shares": shares,
        "remainder": max(0.0, 1.0 - sum(shares.values())) if total > 0 else None,
    }


# --- outcome clusters ------------------------------------------------------------------------------


def _kmeans(
    points: np.ndarray, k: int, rng: random.Random, restarts: int = 20, iterations: int = 50
):
    best_labels, best_inertia, best_centres = None, math.inf, None
    n = len(points)
    for _ in range(restarts):
        centres = [points[rng.randrange(n)]]
        while len(centres) < k:  # k-means++ seeding
            d2 = np.min(
                ((points[:, None, :] - np.array(centres)[None, :, :]) ** 2).sum(axis=2), axis=1
            )
            total = float(d2.sum())
            if total <= 0:
                centres.append(points[rng.randrange(n)])
                continue
            r = rng.random() * total
            centres.append(points[int(np.searchsorted(np.cumsum(d2), r))])
        centres = np.array(centres)
        labels = np.zeros(n, dtype=int)
        for _ in range(iterations):
            d2 = ((points[:, None, :] - centres[None, :, :]) ** 2).sum(axis=2)
            new_labels = d2.argmin(axis=1)
            if np.array_equal(new_labels, labels) and _ > 0:
                break
            labels = new_labels
            for j in range(k):
                members = points[labels == j]
                if len(members):
                    centres[j] = members.mean(axis=0)
        inertia = float(((points - centres[labels]) ** 2).sum())
        if inertia < best_inertia:
            best_labels, best_inertia, best_centres = labels.copy(), inertia, centres.copy()
    return best_labels, best_centres


def _silhouette(points: np.ndarray, labels: np.ndarray) -> float:
    n = len(points)
    if n < 2 or len(set(labels.tolist())) < 2:
        return float("nan")
    scores = []
    rows = _block_rows(n, points.shape[1])  # a block of rows' distances at a time, never n x n
    for start in range(0, n, rows):
        distances = _distances(points[start : start + rows], points)
        for i in range(start, start + len(distances)):
            row = distances[i - start]
            own = labels == labels[i]
            own[i] = False
            if not own.any():
                scores.append(0.0)
                continue
            a = row[own].mean()
            b = min(
                row[labels == other].mean() for other in set(labels.tolist()) if other != labels[i]
            )
            scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.mean(scores))


def clusters(rows: pa.Table | list[dict], seed: int, max_cells: int = 2000) -> dict:
    """Outcome groups by k-means on standardized return, drawdown, trade count and exposure;
    reported only with at least 20 valid cells and a silhouette of 0.5 or better."""
    columns = _columns(rows)
    paths = _paths_of(columns)
    keep = [
        i
        for i, valid in enumerate(columns["valid"])
        if valid and all(_finite(columns[f"combined.{m}"][i]) for m in CLUSTER_METRICS)
    ]
    if len(keep) < MIN_CLUSTER_CELLS:
        return {"refused": f"fewer than {MIN_CLUSTER_CELLS} valid cells"}
    raw = np.array([[float(columns[f"combined.{m}"][i]) for m in CLUSTER_METRICS] for i in keep])
    informative = []
    for j in range(raw.shape[1]):
        column = raw[:, j]
        spread = float(np.ptp(column))
        if spread > 1e-6 and spread > 0.01 * abs(float(column.mean())):
            informative.append(j)
    if not informative:
        return {"refused": "no clear structure (the outcome metrics do not vary across cells)"}
    points = raw[:, informative]
    points = (points - points.mean(axis=0)) / np.where(
        points.std(axis=0) > 0, points.std(axis=0), 1.0
    )
    rng = random.Random(seed)
    sample = list(range(len(points)))
    if len(sample) > max_cells:
        sample = sorted(rng.sample(sample, max_cells))
    best = None
    for k in range(2, min(6, len(points) - 1) + 1):
        labels, centres = _kmeans(points, k, random.Random(seed + k))
        score = _silhouette(points[sample], labels[sample])
        if best is None or (not math.isnan(score) and score > best[0]):
            best = (score, k, labels, centres)
    score, k, labels, centres = best
    if math.isnan(score) or score < SILHOUETTE_FLOOR:
        shown = "undefined" if math.isnan(score) else f"{score:.2f}"
        return {
            "refused": f"no clear structure (best silhouette {shown}, below {SILHOUETTE_FLOOR})"
        }
    groups = []
    for j in range(k):
        members = [keep[i] for i in range(len(keep)) if labels[i] == j]
        if not members:
            continue
        member_points = points[labels == j]
        nearest = members[int(np.argmin(((member_points - centres[j]) ** 2).sum(axis=1)))]
        groups.append(
            {
                "size": len(members),
                "medians": {
                    m: float(np.median([columns[f"combined.{m}"][i] for i in members]))
                    for m in CLUSTER_METRICS
                },
                "parameter_ranges": {
                    path: [
                        float(min(columns[path][i] for i in members)),
                        float(max(columns[path][i] for i in members)),
                    ]
                    for path in paths
                },
                "exemplar": int(columns["cell"][nearest]),
                "cells": [int(columns["cell"][i]) for i in members][:200],
            }
        )
    return {"k": k, "silhouette": score, "groups": groups, "metrics": list(CLUSTER_METRICS)}


# --- the report ------------------------------------------------------------------------------------


def _params(grid: Grid, cell: int) -> dict[str, float]:
    return grid.cell_values(cell)


def _metrics_of(columns: dict[str, list], index_by_cell: dict[int, int], cell: int) -> dict:
    i = index_by_cell[cell]
    return {
        key[len("combined.") :]: columns[key][i] for key in columns if key.startswith("combined.")
    }


def analyse(
    rows: pa.Table | list[dict],
    grid: Grid,
    objective: str,
    tolerance: float,
    mode: str,
    seed: int,
    data_label: str,
) -> dict:
    columns = _columns(rows)
    index_by_cell = {int(c): i for i, c in enumerate(columns["cell"])}
    values, skipped, nulls, sign = objective_values(columns, objective)
    column = f"combined.{objective}"
    d = len(grid.paths)
    sampled_fraction = (
        (len(values) / grid.valid_count) if mode == "sampled" and grid.valid_count else 1.0
    )
    base = {
        "objective": objective,
        "tolerance": tolerance,
        "tau": 0.0,
        "mode": mode,
        "sampled_fraction": sampled_fraction,
        "valid_cells": len(values),
        "skipped": skipped,
        "null_objective_cells": nulls,
        "neighbour_rule": NEIGHBOUR_RULES["sampled" if mode == "sampled" else "exhaustive"],
        "recommendation": None,
        "plateaus": [],
        "peaks": [],
        "main_effects": {},
        "interactions": None,
        "sensitivity": {"shares": {}, "remainder": None},
        "clusters": {"refused": "no valid cells"},
        "uncertainty": None,
        "cells_named": [],
        "statement": "",
    }
    if not values:
        base["statement"] = f"no valid objective values for {objective}: nothing to rank"
        return base

    # The maps hold whatever the surface shows, recommendation or not.
    base["main_effects"] = main_effects(rows, grid, column)
    if d > 1:
        pairs = interactions(rows, grid, column)
        base["interactions"] = pairs if len(pairs) <= 3 else pairs[:3]
    base["sensitivity"] = sensitivity(rows, grid, column)
    base["clusters"] = clusters(rows, seed)

    vals = np.array(list(values.values()))
    p10, p90 = np.percentile(vals, [10, 90])
    tau = float(tolerance * (p90 - p10))
    base["tau"] = tau
    if tau <= 0:
        best = max(values, key=lambda c: (values[c], -c))
        if len({float(v) for v in vals}) == 1:
            base["statement"] = (
                f"the surface is flat: every valid cell has the same {objective} "
                f"({sign * float(vals[0]):g}); no peak or plateau to name"
            )
            return base
        # P10 == P90 but the values differ: the tolerance band is empty, so no plateau can be
        # named; the best cell stands alone as a fragile peak (review finding 6).
        base["peaks"] = [
            {
                "cell": best,
                "params": _params(grid, best),
                "objective": sign * values[best],
                "fragile": True,
                "plateau": None,
            }
        ]
        base["cells_named"] = [best]
        base["statement"] = (
            f"the surface is flat between the 10th and 90th percentiles of {objective} "
            f"(both {sign * float(p10):g}), so the tolerance band is empty and no plateau can be "
            f"named; the best cell {_params(grid, best)} with {objective} "
            f"{sign * values[best]:g} is a fragile peak"
        )
        return base

    run = sorted(values)
    subsampled = False
    if mode == "sampled":
        if len(run) > NEIGHBOUR_SUBSAMPLE:
            run = sorted(random.Random(seed).sample(run, NEIGHBOUR_SUBSAMPLE))
            subsampled = True
        relation = neighbours_sampled(grid, run, 2 * d)
        if subsampled:
            base["neighbour_rule"] += (
                f", over a seeded subsample of {NEIGHBOUR_SUBSAMPLE} run cells"
            )
    else:
        relation = neighbours_exhaustive(grid, run)
    considered = {cell: values[cell] for cell in run}
    found_peaks = peaks(considered, relation)
    found = plateaus(considered, relation, found_peaks, tau, 2 * d + 1)
    counting = sorted((p for p in found if p["counts"]), key=lambda p: (-p["median"], -p["size"]))
    for rank, plateau in enumerate(counting, start=1):
        plateau["id"] = rank
    plateau_of_peak: dict[int, int | None] = {}
    for plateau in found:
        for peak in plateau["peaks"]:
            plateau_of_peak[peak] = plateau.get("id") if plateau["counts"] else None
    reported_plateaus = []
    for plateau in counting:
        centre = _centre(grid, plateau["cells"])
        cliff = _cliff(considered, relation, plateau["cells"], plateau["median"])
        reported_plateaus.append(
            {
                "id": plateau["id"],
                "cells": plateau["cells"],
                "size": plateau["size"],
                "median": sign * plateau["median"],
                "iqr": plateau["iqr"],
                "cliff": cliff,
                "counts": True,
                "peaks": plateau["peaks"],
                "centre": {
                    "cell": centre,
                    "params": _params(grid, centre),
                    "metrics": _metrics_of(columns, index_by_cell, centre),
                    "objective": sign * considered[centre],
                },
            }
        )
    base["plateaus"] = reported_plateaus
    base["peaks"] = [
        {
            "cell": peak,
            "params": _params(grid, peak),
            "objective": sign * considered[peak],
            "fragile": plateau_of_peak.get(peak) is None,
            "plateau": plateau_of_peak.get(peak),
        }
        for peak in found_peaks
    ]
    fragile = [p for p in base["peaks"] if p["fragile"]]
    named: list[int] = [p["cell"] for p in base["peaks"]]
    for plateau in reported_plateaus[:3]:
        named.extend(plateau["cells"])
    if isinstance(base["clusters"], dict) and "groups" in base["clusters"]:
        named.extend(g["exemplar"] for g in base["clusters"]["groups"])
    base["cells_named"] = sorted(set(named))[:2000]

    if not reported_plateaus:
        best = found_peaks[0]
        others = max(len(fragile) - 1, 0)
        tail = (
            ""
            if others == 0
            else (
                ", as is 1 other fragile peak"
                if others == 1
                else f", as are {others} other fragile peaks"
            )
        )
        base["statement"] = (
            f"no plateau at tolerance {tolerance:g} (τ = {tau:g}); the best cell "
            f"{_params(grid, best)} with {objective} {sign * considered[best]:g} is a fragile peak{tail}"
        )
        return base

    top = reported_plateaus[0]
    supported = next(
        (
            {"cell": peak, "params": _params(grid, peak), "objective": sign * considered[peak]}
            for peak in top["peaks"]
            if plateau_of_peak.get(peak) == top["id"]
        ),
        None,
    )
    base["recommendation"] = {
        "plateau": top["id"],
        "centre": top["centre"],
        "supported_peak": supported,
        "fragile_peaks": [
            {"cell": p["cell"], "params": p["params"], "objective": p["objective"]} for p in fragile
        ],
        "statement": (
            f"plateau {top['id']} of {top['size']} cells, median {objective} {top['median']:g}; "
            f"use its centre {top['centre']['params']}; "
            + (f"supported peak at {supported['params']}; " if supported else "no supported peak; ")
            + f"{len(fragile)} fragile peak{'s' if len(fragile) != 1 else ''} marked"
        ),
    }
    base["uncertainty"] = {
        "iqr": top["iqr"],
        "cells": top["size"],
        "sampled_fraction": sampled_fraction,
        "statement": (
            f"In-sample on one symbol and range ({data_label}); no out-of-sample evidence until "
            "walked forward."
        ),
    }
    base["statement"] = base["recommendation"]["statement"]
    return base


# --- markdown ----------------------------------------------------------------------------------------


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def render_markdown(report: dict) -> str:
    lines: list[str] = []
    rec = report.get("recommendation")
    lines.append(f"# Recommendation — {report.get('statement', '')}")
    lines.append("")
    lines.append(
        f"Report {report.get('report_id', '?')} generated {report.get('generated_at', '?')} · "
        f"objective {report['objective']} · tolerance {_fmt(report['tolerance'])} (τ = {_fmt(report['tau'])}) · "
        f"{report['mode']}, fraction {_fmt(report['sampled_fraction'])} · valid cells {report['valid_cells']} · "
        f"skipped {report['skipped']} · null objective {report['null_objective_cells']}"
    )
    lines.append("")
    if rec:
        lines.append(
            f"- Centre: cell {rec['centre']['cell']} {rec['centre']['params']} · {report['objective']} {_fmt(rec['centre']['objective'])}"
        )
        if rec["supported_peak"]:
            sp = rec["supported_peak"]
            lines.append(
                f"- Supported peak: cell {sp['cell']} {sp['params']} · {_fmt(sp['objective'])}"
            )
        else:
            lines.append("- Supported peak: none")
        for peak in rec["fragile_peaks"]:
            lines.append(
                f"- Fragile peak (not recommended): cell {peak['cell']} {peak['params']} · {_fmt(peak['objective'])}"
            )
    lines.append("")
    lines.append("## Plateaus")
    lines.append("")
    if report["plateaus"]:
        lines.append("| # | cells | median | iqr | cliff | centre |")
        lines.append("|---|---|---|---|---|---|")
        for p in report["plateaus"]:
            lines.append(
                f"| {p['id']} | {p['size']} | {_fmt(p['median'])} | {_fmt(p['iqr'])} | {_fmt(p['cliff'])} | {p['centre']['params']} |"
            )
    else:
        lines.append("No plateau counted at this tolerance.")
    lines.append("")
    lines.append("## Peaks")
    lines.append("")
    if report["peaks"]:
        lines.append("| cell | params | objective | standing |")
        lines.append("|---|---|---|---|")
        for p in report["peaks"]:
            standing = "fragile" if p["fragile"] else f"supported by plateau {p['plateau']}"
            lines.append(f"| {p['cell']} | {p['params']} | {_fmt(p['objective'])} | {standing} |")
    else:
        lines.append("No peaks.")
    lines.append("")
    lines.append("## Main effects")
    lines.append("")
    for path, entries in report["main_effects"].items():
        lines.append(f"### {path}")
        lines.append("")
        lines.append("| value | median | p25 | p75 | cells |")
        lines.append("|---|---|---|---|---|")
        for e in entries:
            lines.append(
                f"| {_fmt(e['value'])} | {_fmt(e['median'])} | {_fmt(e['p25'])} | {_fmt(e['p75'])} | {e['count']} |"
            )
        lines.append("")
    lines.append("## Interactions")
    lines.append("")
    if report["interactions"]:
        for pair in report["interactions"]:
            lines.append(
                f"- {pair['paths'][0]} × {pair['paths'][1]}: strength {_fmt(pair['strength'])}"
            )
    else:
        lines.append(
            "Not applicable: one parameter." if report["interactions"] is None else "None."
        )
    lines.append("")
    lines.append("## Sensitivity")
    lines.append("")
    for path, share in report["sensitivity"]["shares"].items():
        lines.append(f"- {path}: {_fmt(share)}")
    lines.append(
        f"- remainder (interactions and noise): {_fmt(report['sensitivity']['remainder'])}"
    )
    lines.append("")
    lines.append("## Clusters")
    lines.append("")
    found = report["clusters"]
    if "refused" in found:
        lines.append(f"Not reported: {found['refused']}.")
    else:
        lines.append(f"{found['k']} groups, silhouette {_fmt(found['silhouette'])}:")
        for i, g in enumerate(found["groups"], start=1):
            lines.append(
                f"- group {i}: {g['size']} cells, medians {g['medians']}, parameter ranges {g['parameter_ranges']}"
            )
    lines.append("")
    lines.append("## Uncertainty")
    lines.append("")
    u = report["uncertainty"]
    if u:
        lines.append(
            f"Plateau spread (iqr) {_fmt(u['iqr'])} over {u['cells']} cells; sampled fraction {_fmt(u['sampled_fraction'])}."
        )
        lines.append(u["statement"])
    else:
        lines.append("No recommendation, so no uncertainty to state.")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "analyse",
    "clusters",
    "interactions",
    "main_effects",
    "neighbours_exhaustive",
    "neighbours_sampled",
    "objective_values",
    "peaks",
    "plateaus",
    "render_markdown",
    "sensitivity",
]
