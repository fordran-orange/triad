"""The staged importance task and its views' payloads (Optimization Lab v2 spec §7.3, §7.4 and
§9.4; Phase 3 Task 6).

- **The stages.** `importance_stages` runs `rule.assess_stages` on the frame's cohort and yields
  each stage's result as plain JSON, as it exists: 1, the fine mains and pairs (bootstrap and
  null), delivered first; 2, adding the coarse point estimates (every triple) and the per-block
  mains; 3, adding the coarse bootstrap for R and the candidates' triples, and the coarse null.
  Each is whole for the stages run so far, `partial` until the last, with what its panel prints:
  the result's own fields (`ImportanceResult.to_json`: unclamped terms, display clamps them), the
  block range per parameter, the three uncertainties, the caveat and `elapsed_s`.
- **N and the attempted.** `N` is the uniform configurations scheduled, which a frame cannot tell
  for an experiment (`sources.scheduled_uniform` reads its document); `attempted` is
  `Cohort.n_uniform_total`, the ones attempted so far, which availability's reason 4 counts. They
  differ while a run is in progress, and the basis line then shows both.
- **The payloads** of the `importance`, `interactions` and `triples` views are pure over a stage's
  dict and build new dicts: a stored result is shared, so none of its parts is ever changed.

Importance ignores the filter (§7.3), so no filter is in a task's key (`importance_key`) or in a
payload. Dependencies run importance → rule → analytics; `sources.py` dispatches the views.
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Iterator

from products.aegis.lab.analytics import Checkpoint, cohort
from products.aegis.lab.policy import (
    INTERACTIONS_MAX_PAIRS,
    PAIR_BALANCE_TVD,
    PAIR_MIN_COVERAGE,
)
from products.aegis.lab.query import TrialFrame
from products.aegis.lab.rule import ImportanceResult, assess_stages
from products.aegis.lab.tasks import task_key

METHOD = "importance"  # a task's method in its key, and its label
STAGES = 3
# §7.3's three uncertainties, always shown together, and its caveat, always.
DESIGN_UNCERTAINTY = "interval: sampling of trials, this data"
NO_BLOCKS = "not measured: no screening blocks"
DETECTION_UNCERTAINTY = (
    "detection floor: a detection threshold, not a practical-significance threshold"
)
CAVEAT = (
    "conditional on these ranges, this data, this sampler and this partition; a share is "
    "evidence about where exploration pays, not proof that a parameter is irrelevant"
)
# Why a running optimization requests no task: its identity carries its cells done, so every poll
# would key a new one and coalescing could not bound them.
RUNNING_OPTIMIZATION = "importance is available when the optimization finishes"
NOT_COMPUTED = "importance not computed yet; ignores the active filter"
# What a view reads of a stage, beside its own payload: which stage, on what.
_COMPUTED = (
    "stage",
    "stages",
    "partial",
    "seed",
    "snapshot",
    "metric",
    "scope",
    "n",
    "N",
    "attempted",
    "sampled_from",
    "elapsed_s",
)
# The triple-level arrays of a stage (`math.comb(d, 3)` rows each), left to the triples view.
_COARSE_TRIPLES = ("triples", "T", "increments")
_BOUNDS_TRIPLES = ("inc_lo", "inc_hi")


def importance_key(source: tuple, metric: str, scope: str, seed: int) -> tuple:
    """The importance task's coalescing key on `source` (`sources.experiment_source` or
    `optimization_source`); Task 7 reads the result under the same key."""
    return task_key(source, METHOD, metric, scope, seed)


# --- the stages ---------------------------------------------------------------------------------


def _block_range(result: ImportanceResult) -> list[list[float] | None] | None:
    """Per parameter `[min, max]` of its per-block share estimates (§7.3's period uncertainty),
    over the blocks that measured it (None when none did); None without per-block mains."""
    if not result.K or result.blocks is None:
        return None
    out: list[list[float] | None] = []
    for i in range(len(result.paths)):
        shares = [float(mains.S[i]) for mains in result.blocks.values()]
        measured = [share for share in shares if math.isfinite(share)]
        out.append([min(measured), max(measured)] if measured else None)
    return out


def _period_uncertainty(result: ImportanceResult) -> str:
    if not result.K:
        return NO_BLOCKS
    if result.blocks is None:
        return f"pending: {result.K} screening blocks, measured in stage 2"
    return f"block range over {result.K} screening blocks"


def _stage_json(result: ImportanceResult, stage: int, scheduled: int) -> dict:
    """One stage in plain JSON: the result's fields, `N` re-read as the scheduled configurations
    (module docstring), and what the panel prints beside them."""
    return {
        **result.to_json(),
        "stage": stage,
        "stages": STAGES,
        "partial": stage < STAGES,
        "N": scheduled,
        "attempted": result.n_uniform_total,
        "block_range": _block_range(result),
        "uncertainty": {
            "design": DESIGN_UNCERTAINTY,
            "period": _period_uncertainty(result),
            "detection": DETECTION_UNCERTAINTY,
        },
        "caveat": CAVEAT,
    }


def importance_stages(
    frame: TrialFrame,
    *,
    metric: str,
    scope: str,
    seed: int,
    checkpoint: Checkpoint,
    scheduled: int | None = None,
) -> Iterator[dict]:
    """The three stages of importance on `frame`, each a plain-JSON dict as it finishes (module
    docstring). `checkpoint` runs between resamples and between stages, where a cancelled task
    stops. `elapsed_s` is the seconds since this body began, the cohort included: stage 1's is the
    fine stage's time, stage 3's the whole task's (the budgets `lab_benchmark.py analytics`
    measures). `scheduled` is N: an experiment's body passes its document's first pass, which
    its frame's `scheduled` (refinement included) is not; the default is the frame's, which is
    right for an optimization's grid and for a frame of uniform rows alone."""
    started = time.perf_counter()
    found = cohort(frame, metric=metric, scope=scope, seed=seed)
    checkpoint()
    total = frame.scheduled if scheduled is None else scheduled
    for stage, result in enumerate(assess_stages(found, seed=seed, checkpoint=checkpoint), 1):
        payload = _stage_json(result, stage, total)
        yield {**payload, "elapsed_s": round(time.perf_counter() - started, 3)}


# --- the views' payloads, pure over a stage's dict ------------------------------------------------


def importance_basis(result: dict | None) -> str:
    """The basis line of the three views: n uniform trials used of N scheduled, the attempted
    beside N while they differ (a run in progress)."""
    if result is None:
        return NOT_COMPUTED
    n, scheduled, attempted = result["n"], result["N"], result["attempted"]
    of = f"{scheduled:,}" if attempted == scheduled else f"{scheduled:,} ({attempted:,} attempted)"
    return (
        f"computed on {n:,} uniform trials of {of}; adaptive rows excluded; "
        "ignores the active filter"
    )


def computed_of(result: dict | None) -> dict | None:
    """Which stage an `interactions` or `triples` answer was read from, and on what."""
    return None if result is None else {name: result[name] for name in _COMPUTED}


def importance_payload(result: dict | None) -> dict | None:
    """The `importance` view's stage: the latest one without its triple-level arrays, which the
    `triples` view sends for the top TRIPLE_TOP (`triples_top` stays, naming them)."""
    if result is None:
        return None
    out = dict(result)
    if result.get("coarse") is not None:
        out["coarse"] = {k: v for k, v in result["coarse"].items() if k not in _COARSE_TRIPLES}
    if result.get("coarse_bounds") is not None:
        out["coarse_bounds"] = {
            k: v for k, v in result["coarse_bounds"].items() if k not in _BOUNDS_TRIPLES
        }
    if result.get("coarse_null") is not None:
        out["coarse_null"] = {"t": result["coarse_null"]["t"]}
    return out


def _increment(fine: dict, a: int, b: int) -> dict:
    """`Δ_{a|b}`, what a adds beyond b, with its interval and its family floor."""
    value, floor = fine["D"][a][b], fine["floor"]["D"][a][b]
    return {
        "value": value,
        "lo": fine["lo"]["D"][a][b],
        "hi": fine["hi"]["D"][a][b],
        "floor": floor,
        "detected": value is not None and floor is not None and value > floor,
    }


def _difference(whole: float | None, *parts: float | None) -> float | None:
    if whole is None or None in parts:
        return None
    return whole - sum(parts)


def _largest(*values: float | None) -> float:
    """The largest of `values` that is defined, for a sort; `-inf` when none is."""
    return max((value for value in values if value is not None), default=-math.inf)


def interactions_payload(result: dict | None) -> dict:
    """Every pair on the fine grid (§7.4): `J`, `Δ_{i|j}` (`D_ij`), `Δ_{j|i}` (`D_ji`), `I`
    (no interval: no rule reads it), coverage, balance and `unresolved` (coverage under
    PAIR_MIN_COVERAGE). Resolved pairs first, by their larger increment, the one the rules read;
    the unresolved last, by `max(S_i upper, S_j upper)` descending, then lowest coverage. At most
    INTERACTIONS_MAX_PAIRS are sent, in that order, `total_pairs` counting them all: a surface
    holds at most MAX_PARAMETERS = 10 parameters, so only an optimization grid with single-value
    axes can reach it (a single value multiplies its cells by one)."""
    if result is None:
        return {"pairs": [], "total_pairs": 0, "unresolved_pairs": 0, "constants": None}
    paths, fine = result["paths"], result["fine"]
    S, upper = fine["S"], fine["hi"]["S"]
    resolved, unresolved = [], []
    for i, j in itertools.combinations(range(len(paths)), 2):
        coverage, balance = result["pair_coverage"][i][j], result["pair_balance"][i][j]
        pair = {
            "pair": [paths[i], paths[j]],
            "index": [i, j],
            "J": {
                "value": fine["J"][i][j],
                "lo": fine["lo"]["J"][i][j],
                "hi": fine["hi"]["J"][i][j],
            },
            "D_ij": _increment(fine, i, j),
            "D_ji": _increment(fine, j, i),
            "I": _difference(fine["J"][i][j], S[i], S[j]),
            "coverage": coverage,
            "balance": balance,
            "unbalanced": balance is not None and balance > PAIR_BALANCE_TVD,
            "unresolved": coverage < PAIR_MIN_COVERAGE,
        }
        (unresolved if pair["unresolved"] else resolved).append(pair)
    resolved.sort(key=lambda p: -_largest(p["D_ij"]["value"], p["D_ji"]["value"]))
    unresolved.sort(
        key=lambda p: (-_largest(upper[p["index"][0]], upper[p["index"][1]]), p["coverage"])
    )
    return {
        "pairs": (resolved + unresolved)[:INTERACTIONS_MAX_PAIRS],
        "total_pairs": len(resolved) + len(unresolved),
        "unresolved_pairs": len(unresolved),
        "constants": result["constants"],
    }


def triples_payload(result: dict | None) -> dict:
    """The top TRIPLE_TOP triples by `Δ^c` (§7.4), each with its three own-direction increments:
    its interval where the coarse bootstrap has one (stage 3, a candidate's triple), its family
    floor once the coarse null has run, null otherwise. None before stage 2."""
    found = None if result is None else result.get("coarse")
    if found is None:
        return {"triples": [], "total_triples": 0, "bounded": False}
    paths = result["paths"]
    bounds, null = result.get("coarse_bounds"), result.get("coarse_null")
    place = {tuple(trio): t for t, trio in enumerate(found["triples"])}
    triples = []
    for trio in result["triples_top"]:
        t = place[tuple(trio)]
        values = found["increments"][t]
        increments = [
            {
                "own": paths[own],
                "value": values[p],
                "lo": None if bounds is None else bounds["inc_lo"][t][p],
                "hi": None if bounds is None else bounds["inc_hi"][t][p],
                "floor": None if null is None else null["increments"][t][p],
            }
            for p, own in enumerate(trio)
        ]
        best = _largest(*values)
        triples.append(
            {
                "triple": [paths[k] for k in trio],
                "index": list(trio),
                "T": found["T"][t],
                "delta": None if best == -math.inf else best,
                "increments": increments,
            }
        )
    return {
        "triples": triples,
        "total_triples": len(found["triples"]),
        "bounded": bounds is not None,
    }


__all__ = [
    "CAVEAT",
    "DESIGN_UNCERTAINTY",
    "DETECTION_UNCERTAINTY",
    "METHOD",
    "NOT_COMPUTED",
    "NO_BLOCKS",
    "RUNNING_OPTIMIZATION",
    "STAGES",
    "computed_of",
    "importance_basis",
    "importance_key",
    "importance_payload",
    "importance_stages",
    "interactions_payload",
    "triples_payload",
]
