"""The four robustness categories, the candidate card and the two rankings (Optimization Lab v2
spec §7.6, Phase 3 Task 7; decision 12; Rulings P16 to P19).

Robustness is not one number. A candidate (a tested trial) carries four categories, each resolved
with a classification or unresolved with its reason, and each with the inputs that decided it. The
card lists them side by side and says which were tested and which remain unknown: no score, no
weighted total and no overall label exists anywhere here.

- **A** reads the trial's neighbourhood (`neighbours.py`), **B** the sampled trials in a region
  around it. B is never reported as A: the labels differ, B names its radius and n, and a card
  whose A is unresolved says so on B (`a_unresolved`).
- **C and D are pure over evidence**, on fixtures now, and fed real folds (Phase 6) and replays
  (Phase 5) later. In Phase 3 C has no folds and D no replays. They compare per-unit-time
  statistics, never `cagr` or `mar`, which can be undefined on a short range. Blocks are selection-
  period diagnostics: they make the separate `selection-period consistency` finding, and no block
  result ever reaches C's predicate.
- **The rankings.** `peak` is the metric alone, `robust` lexicographic over the resolved categories
  (A, or B where A is unresolved, labelled `ranked_by`; then C; then D), with unresolved below
  every resolved state and the metric breaking a tie. Each lists k rows. `robust` chooses its own
  from the top RANK_POOL by `peak` of the filter, a bounded compute, so more than k spikes cannot
  hide a plateau: the whole pool reads A, a neighbourhood per candidate and never per trial, and B,
  the costly part, runs on the top k alone; a row with no B computed sorts as unresolved. The
  filter selects candidates only: neighbours and regions read every completed block-0 trial of the
  snapshot, because a brush would otherwise make a tested neighbour read as untested.
- **`stable`** names the first candidate of that order that is stable, untied and, on a metric
  whose sign is profit or loss, above 0; `stable_reason` says why when none is. A surface with no
  spread (τ ≤ 0) classifies nothing, as `analysis.analyse` names no plateau on one.

Every value of A and B is oriented so higher is better (`neighbours.py`). Pure: numpy over a
block-0 frame and plain arguments; every payload is strict JSON. The category names are the bare
letters, so a card whose A is unresolved never says `local` (§15 row 26).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import cached_property

import numpy as np

from products.aegis.lab.index import FrameIndex
from products.aegis.lab.neighbours import Neighbourhood, PositionLookup
from products.aegis.lab.policy import (
    DEFAULT_TOLERANCE,
    FOLD_DRAWDOWN_FACTOR,
    FOLD_MIN_TRADES,
    FOLD_RATIO_BAND,
    FOLDS_MIN,
    NEIGHBOUR_M_GRID,
    NEIGHBOUR_M_SAMPLED,
    NEIGHBOUR_R,
    PEAK_IQR_FACTOR,
    PER_BARS,
    PLATEAU_MIN_COVERAGE,
    PNL_SIGNED_METRICS,
    RANK_POOL,
    RANKING_K,
    REGION_AXES,
    REGION_MIN_N,
    REGION_RADIUS,
    STRESS_DRAWDOWN_FACTOR,
    STRESS_KEEP,
)
from products.aegis.lab.query import (
    LabFilter,
    TrialFrame,
    _axis,
    _labelled,
    filter_mask,
    metric_column,
)

# §7.6's classifications.
STABLE_LOCAL = "stable local"
ISOLATED_PEAK = "isolated peak"
MIXED = "mixed"
STABLE_REGION = "stable region"
UNSTABLE_REGION = "unstable region"
CONSISTENT = "consistent"
INCONSISTENT = "inconsistent"
NOT_PROFITABLE_FULL = "not profitable on the full range"
HOLDS = "holds"
DEGRADES = "degrades"
FAILS = "fails"
NOT_PROFITABLE_BASE = "not profitable at base"
# §7.6's unresolved reasons, and the brief's two beside them.
NO_BLOCKS_OR_FOLDS = "no blocks or folds"
TOO_FEW_TRADES = "too few trades per fold"
SELECTION_ONLY = "unresolved · selection-period only"
NO_REPLAY = "no replay yet (stage 2)"
NO_IMPORTANCE = "importance not computed for this snapshot"
UNDEFINED_VALUE = "undefined metric value"
NO_SPREAD = "no spread in the metric (τ = 0)"
NO_FULL_RANGE = "no full-range figures"

SELECTION_FINDING = "selection-period consistency"
BASE_REPLAY = "base"
STRESSED_REPLAY = "slippage×1.5"
DEFAULT_TOLERANCE_LABEL = f"default tolerance {DEFAULT_TOLERANCE}"  # an `opt:` source's τ reads it
# What a view's basis line adds: which rows its evidence reads.
EVERY_TRIAL = (
    "neighbours and regions read every completed block-0 trial of the snapshot, "
    "the filter selects candidates only"
)
# A value exactly on the radius is inside it: float rounding scales with the values, so the slack
# does too, far below any lattice's step.
_REGION_SLACK = 1e-12
# The robust order per category: a lower rank first, and unresolved below every resolved state.
_SLOT_RANK = {
    STABLE_LOCAL: 0,
    STABLE_REGION: 1,
    MIXED: 2,
    UNSTABLE_REGION: 3,
    ISOLATED_PEAK: 4,
}
_C_RANK = {CONSISTENT: 0, INCONSISTENT: 1, NOT_PROFITABLE_FULL: 2}
_D_RANK = {HOLDS: 0, DEGRADES: 1, FAILS: 2, NOT_PROFITABLE_BASE: 3}
_STABLE = (STABLE_LOCAL, STABLE_REGION)


def constants() -> dict:
    """The §7.6 constants a panel prints, read from the response and never from a UI literal."""
    return {
        "PLATEAU_MIN_COVERAGE": PLATEAU_MIN_COVERAGE,
        "NEIGHBOUR_R": NEIGHBOUR_R,
        "NEIGHBOUR_M_GRID": NEIGHBOUR_M_GRID,
        "NEIGHBOUR_M_SAMPLED": NEIGHBOUR_M_SAMPLED,
        "PEAK_IQR_FACTOR": PEAK_IQR_FACTOR,
        "REGION_RADIUS": REGION_RADIUS,
        "REGION_AXES": REGION_AXES,
        "REGION_MIN_N": REGION_MIN_N,
        "FOLDS_MIN": FOLDS_MIN,
        "FOLD_MIN_TRADES": FOLD_MIN_TRADES,
        "FOLD_RATIO_BAND": list(FOLD_RATIO_BAND),
        "FOLD_DRAWDOWN_FACTOR": FOLD_DRAWDOWN_FACTOR,
        "STRESS_KEEP": STRESS_KEEP,
        "STRESS_DRAWDOWN_FACTOR": STRESS_DRAWDOWN_FACTOR,
        "PER_BARS": PER_BARS,
        "RANKING_K": RANKING_K,
        "RANK_POOL": RANK_POOL,
    }


# --- the shapes ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Category:
    """One category's state: resolved with a classification, or unresolved with its reason, and
    the inputs either way. `name` is its letter, A to D."""

    name: str
    resolved: bool
    classification: str | None
    reason: str | None
    inputs: dict

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    """An informational result shown beside a category, which it never changes. `classification`
    is None when the evidence cannot give a verdict, and `reason` says why."""

    name: str
    classification: str | None
    inputs: dict
    reason: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def _defined(value: float | None) -> float | None:
    """A float, None where undefined: an undefined figure is never a number here."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


@dataclass(frozen=True)
class _Evidence:
    """One evaluation's figures: its bars, its trades, its net P&L and its max drawdown (a fraction
    of equity). Either figure may be undefined."""

    bars: int
    trades: int
    net_pnl: float | None
    max_drawdown: float | None

    def per_unit(self) -> float | None:
        """Net P&L per 1,000 bars, None where undefined (no bars, or no defined net P&L)."""
        net = _defined(self.net_pnl)
        if net is None or self.bars <= 0:
            return None
        return net * PER_BARS / self.bars

    def figures(self) -> dict:
        """§7.6's per-unit-time statistics beside the figures they come from."""
        net = _defined(self.net_pnl)
        return {
            "bars": self.bars,
            "trades": self.trades,
            "net_pnl": net,
            "max_drawdown": _defined(self.max_drawdown),
            "net_pnl_per_1000_bars": self.per_unit(),
            "trades_per_1000_bars": self.trades * PER_BARS / self.bars if self.bars > 0 else None,
            "expectancy_per_trade": net / self.trades if net is not None and self.trades else None,
        }


@dataclass(frozen=True)
class FoldEvidence(_Evidence):
    """A validation fold, or the full range's figures a fold is compared with."""


@dataclass(frozen=True)
class BlockEvidence(_Evidence):
    """A screening block: a selection-period diagnostic only (§7.3a)."""


@dataclass(frozen=True)
class ReplayEvidence(_Evidence):
    """A stage-2 replay under one cost scenario."""


# --- τ ---------------------------------------------------------------------------------------


def _band(values: np.ndarray, tolerance: float) -> float:
    """`analysis.analyse`'s τ over its oriented values, on the frame's completed rows."""
    held = values[np.isfinite(values)]
    if not len(held):
        return 0.0
    p10, p90 = np.percentile(held, [10, 90])
    return float(tolerance * (p90 - p10))


def tau(
    frame: TrialFrame,
    metric: str,
    scope: str,
    tolerance: float,
    *,
    index: FrameIndex | None = None,
) -> float:
    """The experiment's tolerance band, `tolerance × (P90 − P10)` of the metric over every
    completed trial, whatever the filter (`analysis.analyse`'s τ); 0 with no defined value."""
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    return _band(lookup.values[lookup.index.completed], tolerance)


# --- A: local parameter robustness ---------------------------------------------------------------


def _floor_2(value: float) -> float:
    """Two decimals, never rounded up: 0.496 prints 0.49, so it never reads as the 0.5 it missed."""
    return math.floor(value * 100 + 1e-9) / 100


def category_a(nb: Neighbourhood, value: float | None, tau: float, d: int) -> Category:
    """§7.6's A. Resolved at coverage ≥ PLATEAU_MIN_COVERAGE and n ≥ min(2d + 1, |valid|), so a
    fully tested grid corner resolves: `stable local` when P25 is within τ of the value (either
    side), else `isolated peak` above P75 + 3 × IQR, else `mixed`. Below either condition it is
    `untested surroundings` naming the one that fell short (Ruling P17), never a peak and never
    stable; with enough evidence at τ ≤ 0 it reads `no spread in the metric`, since nothing can be
    told from anything (Ruling P19). `value` is oriented like `nb`."""
    required = min(2 * d + 1, nb.valid)
    held = _defined(value)
    peak_line = None if nb.p75 is None else nb.p75 + PEAK_IQR_FACTOR * nb.iqr
    distance = None if held is None or nb.p25 is None else abs(held - nb.p25)
    inputs = {
        "n": nb.tested,
        "valid": nb.valid,
        "tested": nb.tested,
        "undefined": nb.undefined,
        "coverage": nb.coverage,
        "min_coverage": PLATEAU_MIN_COVERAGE,
        "required_n": required,
        "r": nb.r,
        "m": nb.m,
        "probes": nb.probes,
        "valid_basis": nb.valid_basis,
        "p25": nb.p25,
        "p75": nb.p75,
        "iqr": nb.iqr,
        "tau": tau,
        "value": held,
        "distance": distance,
        "peak_factor": PEAK_IQR_FACTOR,
        "peak_line": peak_line,
        "orientation": nb.orientation,
    }

    def unresolved(reason: str) -> Category:
        return Category("A", False, None, reason, inputs)

    if held is None:
        return unresolved(UNDEFINED_VALUE)
    if nb.coverage < PLATEAU_MIN_COVERAGE or not nb.tested:
        return unresolved(
            f"untested surroundings (coverage {_floor_2(nb.coverage)} of {PLATEAU_MIN_COVERAGE})"
        )
    if nb.tested < required:
        return unresolved(f"untested surroundings (n {nb.tested} of {required})")
    if tau <= 0:
        return unresolved(NO_SPREAD)
    if distance <= tau:
        classification = STABLE_LOCAL
    elif held > peak_line:
        classification = ISOLATED_PEAK
    else:
        classification = MIXED
    return Category("A", True, classification, None, inputs)


# --- B: sampled-region robustness ----------------------------------------------------------------


class _Regions:
    """What every region of one lookup reads: the sampled (uniform-design) completed rows with a
    defined value, derived once for a ranking's k candidates, and never without an axis to read."""

    def __init__(self, lookup: PositionLookup) -> None:
        self.lookup = lookup

    @cached_property
    def uniform(self) -> np.ndarray:
        return _labelled(self.lookup.frame.table, "design", ["uniform"])

    @cached_property
    def defined(self) -> np.ndarray:
        return np.isfinite(self.lookup.values)

    @cached_property
    def population(self) -> int:
        return int((self.lookup.index.completed & self.uniform & self.defined).sum())

    def _inside(self, row: int, path: str) -> np.ndarray:
        """The lattice positions of `path` within the radius of the trial's value on it."""
        lookup = self.lookup
        axis = _axis(lookup.frame, path)
        centre = float(lookup.frame.table.column(path)[row].as_py())
        reach = REGION_RADIUS * (axis[-1] - axis[0]) + _REGION_SLACK * np.abs(axis).max()
        return np.flatnonzero(np.abs(axis - centre) <= reach)

    def category(self, row: int, axes: Sequence[str], tau: float) -> Category:
        """§7.6's B at `row` (module docstring). Resolved at n ≥ REGION_MIN_N: `stable region`
        when the region's P25 is within τ of the value (either side), else `unstable region`; at
        τ ≤ 0 it reads `no spread in the metric` (Ruling P19). The density is the region's trials
        over what a uniform draw would put in it."""
        lookup = self.lookup
        axes = list(axes)[:REGION_AXES]
        value = lookup.value_at(row)
        inputs: dict = {
            "axes": axes,
            "radius": REGION_RADIUS,
            "n": 0,
            "min_n": REGION_MIN_N,
            "population": None,
            "region_share": None,
            "density": None,
            "adaptive_excluded": 0,
            "undefined": 0,
            "p25": None,
            "p75": None,
            "iqr": None,
            "tau": tau,
            "value": value,
            "distance": None,
            "orientation": lookup.orientation,
        }

        def unresolved(reason: str) -> Category:
            return Category("B", False, None, reason, inputs)

        if not axes:
            return unresolved(NO_IMPORTANCE)
        if value is None:
            return unresolved(UNDEFINED_VALUE)
        mask = lookup.index.completed.copy()
        mask[row] = False
        rows = None
        share = 1.0
        for path in axes:  # a loop over at most REGION_AXES axes, narrowing the rows
            inside = self._inside(row, path)
            width = len(_axis(lookup.frame, path))
            share *= len(inside) / width
            if not len(inside):
                rows = np.empty(0, dtype=np.int64)
                break
            code = lookup.index.codes_for(lookup.frame, path)
            if rows is None:
                rows = np.flatnonzero(mask & (code >= inside[0]) & (code <= inside[-1]))
            else:
                held = code[rows]
                rows = rows[(held >= inside[0]) & (held <= inside[-1])]
        uniform = self.uniform[rows]
        sampled = rows[uniform]
        defined = self.defined[sampled]
        values = lookup.values[sampled[defined]]
        n = len(values)
        population = self.population - int(bool(self.uniform[row]))
        expected = population * share
        inputs.update(
            n=n,
            population=population,
            region_share=share,
            density=n / expected if expected > 0 else None,
            adaptive_excluded=int((~uniform).sum()),
            undefined=int((~defined).sum()),
        )
        if n:
            low, high = np.percentile(values, [25, 75])
            inputs.update(
                p25=float(low),
                p75=float(high),
                iqr=float(high - low),
                distance=abs(value - float(low)),
            )
        if n < REGION_MIN_N:
            return unresolved(f"too few sampled trials in the region ({n} of {REGION_MIN_N})")
        if tau <= 0:
            return unresolved(NO_SPREAD)
        classification = STABLE_REGION if inputs["distance"] <= tau else UNSTABLE_REGION
        return Category("B", True, classification, None, inputs)


def category_b(
    frame: TrialFrame,
    trial_no: int,
    axes: list[str],
    tau: float,
    *,
    metric: str | None = None,
    scope: str = "combined",
    index: FrameIndex | None = None,
) -> Category:
    """§7.6's B: the sampled trials (uniform design; the adaptive ones excluded and counted) within
    a normalized L∞ radius of REGION_RADIUS of each axis's range on `axes`, the other parameters
    marginalized, t outside its own region. No `axes` (no importance result) is its own reason."""
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    return _Regions(lookup).category(lookup.row_of(trial_no), axes, tau)


def top_axes(result: Mapping | None) -> list[str]:
    """The top REGION_AXES parameters of a finished importance result by their share, ties by
    their order; none without a result or with no share measured."""
    if not result:
        return []
    shares = (result.get("fine") or {}).get("S") or []
    measured = [
        (-share, k, path)
        for k, (path, share) in enumerate(zip(result.get("paths") or [], shares, strict=False))
        if share is not None
    ]
    return [path for _, _, path in sorted(measured)[:REGION_AXES]]


# --- C: temporal robustness ----------------------------------------------------------------------


def _compared(periods: Sequence[_Evidence], base: float | None) -> list[dict]:
    """Each period's figures, with its ratio to a positive baseline (none is formed otherwise)."""
    rows = []
    for period in periods:
        unit = period.per_unit()
        ratio = None if unit is None or base is None or base <= 0 else unit / base
        rows.append({**period.figures(), "ratio": ratio})
    return rows


def _within(period: _Evidence, full: _Evidence) -> bool:
    """§7.6's fold rule, one period against a positive baseline: a positive net P&L per 1,000 bars
    within the band of it and a drawdown within its factor. A drawdown it cannot read never
    passes."""
    unit, base = period.per_unit(), full.per_unit()
    if unit is None or unit <= 0:
        return False
    low, high = FOLD_RATIO_BAND
    if not low * base <= unit <= high * base:
        return False
    drawdown, limit = _defined(period.max_drawdown), _defined(full.max_drawdown)
    return drawdown is not None and limit is not None and drawdown <= FOLD_DRAWDOWN_FACTOR * limit


def _consistency(periods: Sequence[_Evidence], full: _Evidence) -> str:
    """The one arithmetic of the folds' verdict and the blocks' finding."""
    if full.per_unit() <= 0:
        return NOT_PROFITABLE_FULL
    return CONSISTENT if all(_within(period, full) for period in periods) else INCONSISTENT


def _without_figures(blocks: Sequence[BlockEvidence]) -> str | None:
    """Why these blocks cannot be compared: the ones whose evaluation produced no figures (failed,
    or absent); None when each has them."""
    missing = [
        str(b)
        for b, block in enumerate(blocks, 1)
        if block.per_unit() is None or _defined(block.max_drawdown) is None
    ]
    if not missing:
        return None
    if len(missing) == 1:
        return f"block {missing[0]} has no defined figures"
    return f"blocks {', '.join(missing)} have no defined figures"


def _selection_finding(blocks: Sequence[BlockEvidence], full: _Evidence | None) -> Finding:
    """The blocks' diagnostic, with the folds' arithmetic: never read by C's predicate. An
    evaluation that produced nothing is no evidence of inconsistency, so without a baseline, or
    with a positive one and a block without figures, it gives no verdict and says why; a baseline
    ≤ 0 needs no block to read `not profitable`."""
    base = None if full is None else full.per_unit()
    reason = NO_FULL_RANGE if base is None else None
    if base is not None and base > 0:
        reason = _without_figures(blocks)
    return Finding(
        SELECTION_FINDING,
        None if reason else _consistency(blocks, full),
        {
            "full": None if full is None else full.figures(),
            "block_figures": [
                {"block": b, **row} for b, row in enumerate(_compared(blocks, base), 1)
            ],
            "ratio_band": list(FOLD_RATIO_BAND),
            "drawdown_factor": FOLD_DRAWDOWN_FACTOR,
        },
        reason,
    )


def category_c(
    folds: list[FoldEvidence] | None,
    blocks: list[BlockEvidence],
    *,
    full: _Evidence | None = None,
) -> tuple[Category, Finding | None]:
    """§7.6's C and, separately, the blocks' finding (Ruling P16).

    - No folds: `no blocks or folds`, or with blocks `unresolved · selection-period only`.
    - Folds that fall short (fewer than FOLDS_MIN, one under FOLD_MIN_TRADES or with an undefined
      net P&L): `too few trades per fold`, the count in `inputs`.
    - Otherwise, by `full`, the full range's figures: `not profitable on the full range` at a
      baseline ≤ 0 (no ratio is formed), else `consistent` when every fold is within the rule, or
      `inconsistent`. Usable folds without a defined `full` are a caller's bug: a ValueError.

    With folds, C's inputs hold nothing of the blocks, so no block can change it."""
    folds = list(folds or [])
    blocks = list(blocks or [])
    finding = _selection_finding(blocks, full) if blocks else None
    inputs: dict = {
        "folds": len(folds),
        "folds_min": FOLDS_MIN,
        "fold_min_trades": FOLD_MIN_TRADES,
        "ratio_band": list(FOLD_RATIO_BAND),
        "drawdown_factor": FOLD_DRAWDOWN_FACTOR,
    }
    if not folds:
        inputs["blocks"] = len(blocks)
        reason = SELECTION_ONLY if blocks else NO_BLOCKS_OR_FOLDS
        return Category("C", False, None, reason, inputs), finding
    usable = len(folds) >= FOLDS_MIN and all(
        fold.trades >= FOLD_MIN_TRADES and fold.per_unit() is not None for fold in folds
    )
    base = None if full is None else full.per_unit()
    inputs["full"] = None if full is None else full.figures()
    inputs["fold_figures"] = _compared(folds, base)
    if not usable:
        return Category("C", False, None, TOO_FEW_TRADES, inputs), finding
    if base is None:
        raise ValueError("a verdict on validation folds reads the full range's figures")
    return Category("C", True, _consistency(folds, full), None, inputs), finding


# --- D: execution robustness ---------------------------------------------------------------------


def category_d(replays: Mapping[str, ReplayEvidence] | None) -> Category:
    """§7.6's D, resolved once the `base` and `slippage×1.5` replays exist with a defined net P&L.
    At a base ≤ 0: `not profitable at base` (no ratio is formed). Otherwise, per 1,000 bars:
    `fails` at a stressed figure ≤ 0, `holds` at ≥ STRESS_KEEP of base with a drawdown within
    STRESS_DRAWDOWN_FACTOR of base's (one it cannot read never holds), else `degrades`."""
    replays = dict(replays or {})
    base, stressed = replays.get(BASE_REPLAY), replays.get(STRESSED_REPLAY)
    inputs: dict = {
        "scenarios": sorted(replays),
        "stress_keep": STRESS_KEEP,
        "drawdown_factor": STRESS_DRAWDOWN_FACTOR,
        "base": None if base is None else base.figures(),
        "stressed": None if stressed is None else stressed.figures(),
        "ratio": None,
    }
    if base is None or stressed is None or base.per_unit() is None or stressed.per_unit() is None:
        return Category("D", False, None, NO_REPLAY, inputs)
    unit, stressed_unit = base.per_unit(), stressed.per_unit()
    if unit <= 0:
        return Category("D", True, NOT_PROFITABLE_BASE, None, inputs)
    inputs["ratio"] = stressed_unit / unit
    if stressed_unit <= 0:
        return Category("D", True, FAILS, None, inputs)
    drawdown, limit = _defined(stressed.max_drawdown), _defined(base.max_drawdown)
    holds = (
        stressed_unit >= STRESS_KEEP * unit
        and drawdown is not None
        and limit is not None
        and drawdown <= STRESS_DRAWDOWN_FACTOR * limit
    )
    return Category("D", True, HOLDS if holds else DEGRADES, None, inputs)


# --- the card ------------------------------------------------------------------------------------


def candidate_card(
    frame: TrialFrame,
    trial_no: int,
    *,
    metric: str,
    scope: str,
    tolerance: float,
    axes: Sequence[str] | None,
    blocks: Sequence[BlockEvidence] | None = None,
    full: _Evidence | None = None,
    tolerance_label: str | None = None,
    index: FrameIndex | None = None,
) -> dict:
    """One candidate's four categories side by side, which were tested and which remain unknown,
    with the blocks' finding when blocks exist. Never summed. In Phase 3 no folds reach C and no
    replays reach D (decision 12). `blocks` and `full` are the trial's own screening evaluations
    and its full-range figures. KeyError for a trial the frame has no row of, ValueError for one
    that did not complete."""
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    row = lookup.row_of(trial_no)
    band = _band(lookup.values[lookup.index.completed], tolerance)
    value = lookup.value_at(row)
    a = category_a(lookup.around(row), value, band, len(frame.parameters))
    b = _Regions(lookup).category(row, axes or [], band)
    if not a.resolved:  # B is never reported as A: it says so beside its result
        b = Category(
            b.name,
            b.resolved,
            b.classification,
            b.reason,
            {**b.inputs, "a_unresolved": a.reason},
        )
    c, finding = category_c(None, list(blocks or []), full=full)
    categories = (a, b, c, category_d(None))
    return {
        "trial_id": f"{frame.source}#{trial_no}",
        "trial_no": trial_no,
        "metric": metric,
        "scope": scope,
        "value": value,
        "orientation": lookup.orientation,
        "tolerance": tolerance,
        "tolerance_label": tolerance_label,
        "tau": band,
        "categories": {category.name: category.to_json() for category in categories},
        "tested": [category.name for category in categories if category.resolved],
        "unknown": [category.name for category in categories if not category.resolved],
        "findings": [] if finding is None else [finding.to_json()],
    }


# --- the rankings --------------------------------------------------------------------------------


def _rank(category: Category, ranks: Mapping[str, int]) -> int:
    """A resolved state's place, an unresolved one after them all."""
    return ranks[category.classification] if category.resolved else len(ranks)


def robust_key(
    slot: Category, c: Category, d: Category, value: float, trial_no: int
) -> tuple[int, int, int, float, int]:
    """The robust order's key, ascending: the slot (A, or B where A is unresolved), C, D, then the
    oriented metric, best first, and the trial number. Unresolved sorts below every resolved state
    of its category."""
    return (_rank(slot, _SLOT_RANK), _rank(c, _C_RANK), _rank(d, _D_RANK), -value, trial_no)


def _top_rows(lookup: PositionLookup, flt: LabFilter, k: int) -> np.ndarray:
    """The best `k` rows of the filter with a defined value, by (value, trial number): the
    snapshot's order of the whole frame, restricted."""
    frame = lookup.frame
    column = metric_column(lookup.scope, lookup.metric)
    order = lookup.index.order(column, lookup.orientation > 0, frame.table)
    mask = filter_mask(frame, flt, index=lookup.index)
    rows = order[mask[order]][:k].astype(np.int64)
    return rows[np.isfinite(lookup.values[rows])]


def _stable_of(
    ordered: Sequence[Mapping], *, metric: str, pool: int, band: float
) -> tuple[str | None, str | None]:
    """The candidate `stable` names and, when it names none, why (Ruling P19). `ordered` is the
    pool in `robust`'s order: the first that is `stable local`, or `stable region` with A
    unresolved; that no other candidate ties on the whole order but the trial number; and, on a
    P&L-signed metric, that is above 0. The reason is what stopped the most robust of the stable
    ones, or that there were none."""
    if not ordered:
        return None, f"no trial with a defined {metric} in the filter"
    if band <= 0:
        return None, NO_SPREAD
    reason = None
    for place, entry in enumerate(ordered):
        if entry["classification"] not in _STABLE:
            continue
        held = entry["key"][:-1]
        neighbours = ordered[max(place - 1, 0) : place] + ordered[place + 1 : place + 2]
        if metric in PNL_SIGNED_METRICS and entry["value"] <= 0:
            reason = reason or f"the most robust candidate has {metric} ≤ 0"
        elif any(other["key"][:-1] == held for other in neighbours):
            reason = reason or f"the most robust candidates tie on {metric}"
        else:
            return entry["trial_id"], None
    return None, reason or f"none among the top {pool} by peak"


def rankings_basis(ranks: Mapping) -> str:
    """What the rankings' basis line adds: how far they looked."""
    return f"robust ranks the top {ranks['pool']} by peak, B reads the top {ranks['k']}"


def rankings(
    frame: TrialFrame,
    *,
    metric: str,
    scope: str,
    tolerance: float,
    k: int = RANKING_K,
    axes: Sequence[str] | None = None,
    flt: LabFilter | None = None,
    index: FrameIndex | None = None,
) -> dict:
    """`peak` and `robust`, side by side, `k` rows each at most and `k` bounded by RANK_POOL
    (module docstring). `pool` is how many candidates `robust` chose from, the top RANK_POOL by
    `peak` of the filter. `disagree` is whether their first trials differ. `stable` and
    `stable_reason` are `_stable_of`'s. `ranked` and `peak_ranked` list each ranking's trials with
    what placed them (`ranked_by` A or B, None when neither resolved)."""
    k = min(k, RANK_POOL)
    lookup = PositionLookup(frame, metric=metric, scope=scope, index=index)
    band = _band(lookup.values[lookup.index.completed], tolerance)
    regions = _Regions(lookup) if axes else None
    d = len(frame.parameters)
    c_state, _ = category_c(None, [])  # decision 12: no folds or replays in Phase 3
    d_state = category_d(None)
    rows = _top_rows(lookup, flt or LabFilter(scope=scope), RANK_POOL).tolist()
    entries = []
    for place, row in enumerate(rows):  # a loop over at most RANK_POOL candidates
        value = float(lookup.values[row])
        trial_no = int(lookup.trial_numbers[row])
        slot = category_a(lookup.around(row), value, band, d)
        ranked_by = "A" if slot.resolved else None
        if not slot.resolved and regions is not None and place < k:
            b = regions.category(row, axes, band)
            if b.resolved:
                slot, ranked_by = b, "B"
        entries.append(
            {
                "trial_id": f"{frame.source}#{trial_no}",
                "key": robust_key(slot, c_state, d_state, value, trial_no),
                "value": value,
                "ranked_by": ranked_by,
                "classification": slot.classification,
                "reason": slot.reason,
            }
        )
    ordered = sorted(entries, key=lambda entry: entry["key"])
    stable, stable_reason = _stable_of(ordered, metric=metric, pool=len(rows), band=band)

    def shown(listed: list[dict]) -> list[dict]:
        return [{name: held for name, held in entry.items() if name != "key"} for entry in listed]

    peak = [entry["trial_id"] for entry in entries[:k]]
    robust = [entry["trial_id"] for entry in ordered[:k]]
    return {
        "peak": peak,
        "robust": robust,
        "disagree": bool(peak) and peak[0] != robust[0],
        "stable": stable,
        "stable_reason": stable_reason,
        "k": k,
        "pool": len(rows),
        "ranked": shown(ordered[:k]),
        "peak_ranked": shown(entries[:k]),
    }


__all__ = [
    "DEFAULT_TOLERANCE_LABEL",
    "EVERY_TRIAL",
    "NO_BLOCKS_OR_FOLDS",
    "NO_IMPORTANCE",
    "NO_REPLAY",
    "NO_SPREAD",
    "SELECTION_FINDING",
    "SELECTION_ONLY",
    "UNDEFINED_VALUE",
    "BlockEvidence",
    "Category",
    "Finding",
    "FoldEvidence",
    "ReplayEvidence",
    "candidate_card",
    "category_a",
    "category_b",
    "category_c",
    "category_d",
    "constants",
    "rankings",
    "rankings_basis",
    "robust_key",
    "tau",
    "top_axes",
]
