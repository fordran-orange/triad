"""The Lab's empirical deprioritization rule (Optimization Lab v2 spec §7.3, §7.4a and §8.4;
Phase 3 Task 5): availability, the residual veto, the assembled result, the recommended statuses
and the evidence scope, over `analytics`' statistics.

- **Availability** is decided by provenance (§7.3), the first failing reason winning
  (decision 15): no uniform rows, aliased inputs, not a product design, missing configurations,
  an inconsistent decomposition.
- **The veto** (§7.4): R's lower bound above RESIDUAL_VETO; the panel shows its text and its
  warning (decision 16).
- **The statuses** (decision 21): per parameter the first rule that holds, with `failing` naming
  why every non-proposable parameter is not proposed: the availability reason, else the veto,
  else its first failed §7.4a condition. A non-candidate has no coarse bounds (§7.4), so when its
  failing condition is named, its coarse terms are read at their point estimates; a missing bound
  never names a condition the parameter would pass.
- **The evidence scope** (§7.4a, §8.5): what a result's evidence holds for, and `stale: <field>
  changed` when the current scope differs.

Phase 3 recommends: nothing here persists or changes a status (condition 6, the operator's
confirmation, is Phase 4). Dependencies run rule → analytics → coarse and shares.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np

from products.aegis.lab.analytics import (
    MEASURED,
    MISSING_REASONS,
    BlockMains,
    Checkpoint,
    CoarseBounds,
    Cohort,
    FineStage,
    Floors,
    aliased,
    block_mains,
    coarse_floors,
    coarse_intervals,
    coverage_label,
    cramers_v,
    fine_stage,
    pair_quality,
)
from products.aegis.lab.coarse import (
    Coarse,
    coarse,
    coarse_bins,
    coarse_parts,
    coarse_terms,
    triple_index,
    triples_top,
)
from products.aegis.lab.policy import (
    ALIAS_V,
    BOOTSTRAP_B,
    COARSE_BINS,
    COARSE_BOOTSTRAP_B,
    COARSE_PERMUTATION_P,
    FLOOR_QUANTILE,
    IMPORTANCE_MIN_N_FACTOR,
    IMPORTANCE_MIN_PER_VALUE,
    IMPORTANCE_ROWS,
    INTERVAL,
    PAIR_BALANCE_TVD,
    PAIR_MIN_COVERAGE,
    PAIR_MIN_N,
    PERMUTATION_P,
    RESIDUAL_INCONSISTENT,
    RESIDUAL_VETO,
    THETA_MIN,
    TRIPLE_TOP,
)
from products.aegis.lab.shares import fine_parts

# --- availability and the veto (§7.3, §7.4; decisions 15 and 16) --------------------------------

NO_UNIFORM = "no uniform rows of the current space"
ALIASED = "aliased inputs"
INCONSISTENT = "decomposition inconsistent"
PRODUCT_HINT = "freeze or narrow the constrained ranges"
METRIC_HINT = (
    "choose a metric defined everywhere (net_pnl, max_drawdown, trade_count, exposure) "
    "or retry the failed trials"
)
UNAVAILABLE = "empirical deprioritization unavailable"
VETO = "structure not captured by mains, pairs and triples: deprioritization unsafe"
VETO_WARNING = "unexplained share high: noise or higher-order structure"


@dataclass(frozen=True)
class Availability:
    """Whether the rule may propose (§7.4a): `reasons` every failing reason in order, `reason`
    the first, `hint` the first's hint (reasons 3 and 4 carry one)."""

    available: bool
    reason: str | None
    reasons: list[str]
    hint: str | None

    @property
    def message(self) -> str | None:
        """The panel's line: `empirical deprioritization unavailable: <reason>`."""
        return None if self.available else f"{UNAVAILABLE}: {self.reason}"


def _percent(share: float) -> str:
    """A share as the reasons print it: an integer percent at 1 % and above, one decimal below
    (`0.4`), and `< 0.1` for a positive share that would round to 0.0."""
    percent = 100.0 * share
    if percent >= 1.0:
        return f"{percent:.0f}"
    return f"{percent:.1f}" if percent >= 0.05 else "< 0.1"


def availability(cohort: Cohort, V: np.ndarray, R_hi: float, R_lo: float) -> Availability:
    """The rule's availability by provenance (§7.3), the first failing reason winning:
    1. `no uniform rows of the current space`;
    2. `aliased inputs` (any pair of V above ALIAS_V; before the product design, decision 15);
    3. `inputs are not a product design (p % of the grid is invalid)`;
    4. `m of N configurations have no finite <metric> (k invalid, f failed, u undefined)`, N the
       uniform configurations attempted (`Cohort.n_uniform_total`), m counted over block 0 and
       every block;
    5. `decomposition inconsistent` when R's upper bound is below RESIDUAL_INCONSISTENT.
    `R_lo` rides along with R's interval; it is the veto's input (`veto`), not availability's."""
    failing: list[tuple[str, str | None]] = []
    if cohort.n_uniform_total == 0:
        failing.append((NO_UNIFORM, None))
    if aliased(V):
        failing.append((ALIASED, None))
    if cohort.invalid_share > 0:
        grid = _percent(cohort.invalid_share)
        failing.append(
            (f"inputs are not a product design ({grid} % of the grid is invalid)", PRODUCT_HINT)
        )
    k, f, u = (int(cohort.missing.get(reason, 0)) for reason in MISSING_REASONS)
    if k + f + u:
        lost = (
            f"{k + f + u:,} of {cohort.n_uniform_total:,} configurations have no finite "
            f"{cohort.metric} ({k:,} invalid, {f:,} failed, {u:,} undefined)"
        )
        failing.append((lost, METRIC_HINT))
    if R_hi < RESIDUAL_INCONSISTENT:
        failing.append((INCONSISTENT, None))
    if not failing:
        return Availability(True, None, [], None)
    (reason, hint), *_ = failing
    return Availability(False, reason, [text for text, _ in failing], hint)


def veto(R_lo: float) -> str | None:
    """The residual veto (§7.4): raised when R's lower bound exceeds RESIDUAL_VETO; the panel then
    also shows VETO_WARNING (decision 16)."""
    return VETO if R_lo > RESIDUAL_VETO else None


def missingness_note(cohort: Cohort) -> str | None:
    """The descriptive estimates' note when configurations are missing (§7.3)."""
    lost, total = sum(int(v) for v in cohort.missing.values()), cohort.n_uniform_total
    if not lost or not total:
        return None
    return f"on {total - lost:,} of {total:,} configurations; missingness may bias"


# --- the assembled result (Task 5; Task 6 stages it) --------------------------------------------


# The constants the rule and its panel read (global constraints: printed from the response).
CONSTANTS = MappingProxyType(
    {
        "THETA_MIN": THETA_MIN,
        "RESIDUAL_VETO": RESIDUAL_VETO,
        "RESIDUAL_INCONSISTENT": RESIDUAL_INCONSISTENT,
        "BOOTSTRAP_B": BOOTSTRAP_B,
        "PERMUTATION_P": PERMUTATION_P,
        "COARSE_BOOTSTRAP_B": COARSE_BOOTSTRAP_B,
        "COARSE_PERMUTATION_P": COARSE_PERMUTATION_P,
        "COARSE_BINS": COARSE_BINS,
        "INTERVAL": INTERVAL,
        "FLOOR_QUANTILE": FLOOR_QUANTILE,
        "ALIAS_V": ALIAS_V,
        "PAIR_MIN_N": PAIR_MIN_N,
        "PAIR_MIN_COVERAGE": PAIR_MIN_COVERAGE,
        "PAIR_BALANCE_TVD": PAIR_BALANCE_TVD,
        "IMPORTANCE_MIN_N_FACTOR": IMPORTANCE_MIN_N_FACTOR,
        "IMPORTANCE_MIN_PER_VALUE": IMPORTANCE_MIN_PER_VALUE,
        "IMPORTANCE_ROWS": IMPORTANCE_ROWS,
        "TRIPLE_TOP": TRIPLE_TOP,
    }
)


def _plain(value: Any) -> Any:
    """`value` in plain JSON types: arrays as lists, NaN and infinities as None."""
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain({f.name: getattr(value, f.name) for f in dataclasses.fields(value)})
    return value


@dataclass(frozen=True, eq=False)
class ImportanceResult:
    """Everything the rule reads, assembled from the cohort and whichever stages have run (later
    ones None): the cohort's counts; per parameter its coverage `labels` and the values holding
    IMPORTANCE_MIN_PER_VALUE rows; the pairs' `coverage` and `balance`; Cramér's V over every
    uniform configuration and its `aliased_pairs`; the `fine` stage; the per-block mains
    (`blocks`, None until computed, `K` the experiment's blocks); the `coarse` point estimates
    (R's interval in `lo` / `hi` once bounded), the `coarse_bounds` and the `coarse_null`
    floors; `availability`, `veto`, its `warnings` and the missingness `note`."""

    paths: tuple[str, ...]
    B: np.ndarray
    n: int
    n_uniform_total: int
    sampled_from: int | None
    missing: dict[str, int]
    invalid_share: float
    metric: str
    scope: str
    seed: int
    snapshot: dict | None
    labels: list[str]
    values_held: list[int]
    coverage: np.ndarray
    balance: np.ndarray
    V: np.ndarray
    aliased_pairs: list[tuple[int, int]]
    fine: FineStage
    blocks: dict[int, BlockMains] | None
    K: int
    coarse: Coarse | None
    coarse_bounds: CoarseBounds | None
    coarse_null: Floors | None
    availability: Availability
    veto: str | None
    warnings: list[str]
    note: str | None

    def to_json(self) -> dict:
        """The result in plain JSON types (lists, NaN as null), its statuses included."""
        d = len(self.paths)
        fine = self.fine
        names = ("S", "J", "D")
        floor_S, _, floor_D = fine_parts(fine.floors.family)
        tick_S, _, tick_D = fine_parts(fine.floors.share)
        coarse_json = None
        if self.coarse is not None:
            found = self.coarse
            coarse_json = {
                "S": found.S,
                "J": found.J,
                "D": found.D,
                "triples": found.triples,
                "T": found.T,
                "increments": found.increments,
                "R": found.R,
                "lo": found.lo,
                "hi": found.hi,
            }
        null_json = None
        if self.coarse_null is not None:
            null_json = {
                "increments": coarse_parts(self.coarse_null.family, d).increments,
                "tick": coarse_parts(self.coarse_null.share, d).increments,
                "t": self.coarse_null.t,
            }
        blocks_json = None
        if self.blocks is not None:
            blocks_json = {b: mains._asdict() for b, mains in sorted(self.blocks.items())}
        return _plain(
            {
                "paths": self.paths,
                "B": self.B,
                "n": self.n,
                "N": self.n_uniform_total,
                "sampled_from": self.sampled_from,
                "missing": self.missing,
                "invalid_share": self.invalid_share,
                "metric": self.metric,
                "scope": self.scope,
                "seed": self.seed,
                "snapshot": self.snapshot,
                "labels": self.labels,
                "values_held": self.values_held,
                "pair_coverage": self.coverage,
                "pair_balance": self.balance,
                "cramers_v": self.V,
                "aliased": self.aliased_pairs,
                "fine": {
                    **dict(zip(names, fine_parts(fine.terms), strict=True)),
                    "lo": dict(zip(names, fine_parts(fine.lo), strict=True)),
                    "hi": dict(zip(names, fine_parts(fine.hi), strict=True)),
                    "floor": {"S": floor_S, "D": floor_D},
                    "tick": {"S": tick_S, "D": tick_D},
                    "t": fine.floors.t,
                },
                "K": self.K,
                "blocks": blocks_json,
                "coarse": coarse_json,
                "coarse_bounds": self.coarse_bounds,
                "coarse_null": null_json,
                "triples_top": [] if self.coarse is None else triples_top(self.coarse),
                "availability": {
                    **dataclasses.asdict(self.availability),
                    "message": self.availability.message,
                },
                "veto": self.veto,
                "warnings": self.warnings,
                "note": self.note,
                "statuses": statuses(self),
                "constants": CONSTANTS,
            }
        )


def importance_result(
    cohort: Cohort,
    *,
    fine: FineStage,
    blocks: Mapping[int, BlockMains] | None = None,
    coarse: Coarse | None = None,
    coarse_bounds: CoarseBounds | None = None,
    coarse_null: Floors | None = None,
    previous: ImportanceResult | None = None,
) -> ImportanceResult:
    """The `ImportanceResult` of `cohort` with the stages that have run: coverage, pair quality and
    aliasing are computed here, and availability and the veto from R's interval once the coarse
    bootstrap has bounded it (NaN before: neither inconsistent nor vetoed, while condition 3 still
    has no interval, so nothing is proposable). `previous`, an earlier stage's result of the same
    cohort, lends its cohort-level facts (Cramér's V, pair quality, coverage), which a later stage
    then does not recompute."""
    X, B = cohort.X, cohort.B
    if previous is not None:
        V, coverage, balance = previous.V, previous.coverage, previous.balance
        labels, held = previous.labels, previous.values_held
    else:
        V = cramers_v(cohort.X_uniform, B)
        coverage, balance = pair_quality(X, B)
        labels = coverage_label(X, B, cohort.n)
        held = []
        for i, size in enumerate(int(b) for b in B):
            per_value = np.bincount(np.asarray(X[:, i], dtype=np.intp), minlength=size)
            held.append(int((per_value >= IMPORTANCE_MIN_PER_VALUE).sum()))
    R_lo = R_hi = math.nan
    if coarse_bounds is not None:
        R_lo, R_hi = coarse_bounds.R_lo, coarse_bounds.R_hi
        if coarse is not None:
            coarse = dataclasses.replace(coarse, lo=R_lo, hi=R_hi)
    vetoed = veto(R_lo)
    return ImportanceResult(
        paths=cohort.paths,
        B=B,
        n=cohort.n,
        n_uniform_total=cohort.n_uniform_total,
        sampled_from=cohort.sampled_from,
        missing=dict(cohort.missing),
        invalid_share=cohort.invalid_share,
        metric=cohort.metric,
        scope=cohort.scope,
        seed=cohort.seed,
        snapshot=cohort.snapshot,
        labels=labels,
        values_held=held,
        coverage=coverage,
        balance=balance,
        V=V,
        aliased_pairs=aliased(V),
        fine=fine,
        blocks=None if blocks is None else dict(blocks),
        K=len(cohort.blocks),
        coarse=coarse,
        coarse_bounds=coarse_bounds,
        coarse_null=coarse_null,
        availability=availability(cohort, V, R_hi, R_lo),
        veto=vetoed,
        warnings=[VETO_WARNING] if vetoed else [],
        note=missingness_note(cohort),
    )


def assess(cohort: Cohort, *, seed: int, checkpoint: Checkpoint) -> ImportanceResult:
    """Every stage of the rule on `cohort`, in Task 6's order: the fine grid, the per-block mains
    and the coarse point estimates, then the coarse bootstrap for R and the candidates (§7.4,
    `candidates`) and the coarse null. The three coarse steps share one triple design, and the
    final result the staged one's cohort-level facts."""
    fine = fine_stage(cohort, seed=seed, checkpoint=checkpoint)
    blocks = block_mains(cohort, seed=seed, checkpoint=checkpoint)
    Xq = coarse_bins(cohort.X, cohort.B)
    terms = coarse_terms(Xq)
    points = coarse(Xq, cohort.Y, terms=terms)
    staged = importance_result(cohort, fine=fine, blocks=blocks, coarse=points)
    chosen = candidates(staged)
    bounds = coarse_intervals(Xq, cohort.Y, chosen, seed=seed, checkpoint=checkpoint, terms=terms)
    null = coarse_floors(Xq, cohort.Y, seed=seed, checkpoint=checkpoint, terms=terms)
    return importance_result(
        cohort,
        fine=fine,
        blocks=blocks,
        coarse=points,
        coarse_bounds=bounds,
        coarse_null=null,
        previous=staged,
    )


# --- the recommended statuses (§7.4a, §8.4; decision 21) ----------------------------------------

UNRESOLVED = "Insufficient coverage · unresolved"
PROPOSABLE = "Deprioritized · proposable"
PERIOD_DEPENDENT = "Investigate · period-dependent"
DETECTED = "Active · detected"
INTERACTION = "Investigate · interaction not ruled out"
THREE_WAY = "Investigate · three-way effect not ruled out"
NOT_DETECTED = "Active · not detected"


@dataclass(frozen=True)
class ParameterStatus:
    """A parameter's recommended status, the first of decision 21's rules that holds, with its
    `reason`; its `flags`; its coverage `label`; `proposable` (rule 2 alone); and `failing`, why a
    non-proposable parameter is not proposed (None when it is)."""

    path: str
    status: str
    reason: str
    flags: list[str]
    label: str
    proposable: bool
    failing: str | None


class _Evidence:
    """A result's arrays, split once for the rule: NaN where a stage has not run yet.

    `named=True` reads the coarse terms as `failing` names a condition: the coarse bootstrap
    bounded the candidates' terms only (§7.4), so a non-candidate's missing coarse bound is read
    at its point estimate. Proposals never read it so: they need every bound (`named=False`)."""

    def __init__(self, result: ImportanceResult, *, named: bool = False) -> None:
        d = len(result.paths)
        self.result, self.d = result, d
        self.S, _, self.D = fine_parts(result.fine.terms)
        self.S_hi, _, self.D_hi = fine_parts(result.fine.hi)
        self.S_floor, _, self.D_floor = fine_parts(result.fine.floors.family)
        self.trios = triple_index(d)
        unknown = np.full((len(self.trios), 3), np.nan)
        found, bounds, null = result.coarse, result.coarse_bounds, result.coarse_null
        self.cS = found.S if found is not None else np.full(d, np.nan)
        self.cD = found.D if found is not None else np.full((d, d), np.nan)
        self.inc = found.increments if found is not None else unknown
        self.cS_hi = bounds.S_hi if bounds is not None else np.full(d, np.nan)
        self.cD_hi = bounds.D_hi if bounds is not None else np.full((d, d), np.nan)
        self.inc_hi = bounds.inc_hi if bounds is not None else unknown
        self.inc_floor = coarse_parts(null.family, d).increments if null is not None else unknown
        self.blocks = dict(sorted((result.blocks if result.blocks is not None else {}).items()))
        # Each parameter's triples, as (triple, the parameter's position in it).
        self.own = [np.argwhere(self.trios == i) for i in range(d)]
        self.at_point = np.zeros(d, dtype=bool)
        if named and bounds is not None:
            self.at_point[:] = True
            self.at_point[list(bounds.candidates)] = False

    def triple(self, t: int) -> str:
        return ", ".join(self.result.paths[k] for k in self.trios[t])

    def coarse(self, i: int, point: float, upper: float, *, at_point: bool) -> tuple[float, bool]:
        """Parameter i's coarse term as a check reads it, and whether that is a point estimate:
        the point when the check reads points, or when i is a non-candidate being named and the
        term has no bound; else the upper bound."""
        if at_point or (self.at_point[i] and math.isnan(upper)):
            return float(point), True
        return float(upper), False


def _below(name: str, value: float, *, point: bool) -> str | None:
    """Why `value < THETA_MIN` fails for `name` (an upper bound, or a point estimate), or None."""
    if math.isnan(value):
        return f"{name} {'undefined' if point else 'has no interval'}"
    if value < THETA_MIN:
        return None
    return f"{name}{'' if point else ' upper'} {value:.4f} ≥ θ_min {THETA_MIN:g}"


def _condition1(ev: _Evidence, i: int, point: bool) -> str | None:
    """§7.4a condition 1: the fine and the coarse S_i, on block 0 and in every block (block 0
    only without blocks, decision 4), coverage first."""
    r = ev.result
    if r.labels[i] != MEASURED:
        return "insufficient coverage"
    unmeasured = [0] if math.isnan(ev.S[i]) else []
    unmeasured += [b for b, mains in ev.blocks.items() if math.isnan(mains.S[i])]
    if unmeasured:
        return f"not measured in block {unmeasured[0]}"
    if r.K and r.blocks is None:
        return "block mains not computed yet"
    checks = [
        ("fine S", float(ev.S[i] if point else ev.S_hi[i]), point),
        ("coarse S", *ev.coarse(i, ev.cS[i], ev.cS_hi[i], at_point=point)),
    ]
    checks += [
        (f"fine S in block {b}", float(mains.S[i] if point else mains.hi[i]), point)
        for b, mains in ev.blocks.items()
    ]
    for name, value, at_point in checks:
        failure = _below(name, value, point=at_point)
        if failure:
            return failure
    return None


def _condition2(ev: _Evidence, i: int, point: bool) -> str | None:
    """§7.4a condition 2: for every other j, the pair measured (coverage, balance) and both the
    fine and the coarse Δ_{i|j} below θ_min."""
    r = ev.result
    for j in range(ev.d):
        if j == i:
            continue
        other = r.paths[j]
        if not r.coverage[i, j] >= PAIR_MIN_COVERAGE:
            covered = r.coverage[i, j]
            return f"pair with {other} unresolved: coverage {covered:.2f} < {PAIR_MIN_COVERAGE:g}"
        if r.balance[i, j] > PAIR_BALANCE_TVD:
            tvd = r.balance[i, j]
            return f"pair with {other} unbalanced: TVD {tvd:.2f} > {PAIR_BALANCE_TVD:g}"
        checks = (
            (f"Δ beyond {other}", float(ev.D[i, j] if point else ev.D_hi[i, j]), point),
            (
                f"coarse Δ beyond {other}",
                *ev.coarse(i, ev.cD[i, j], ev.cD_hi[i, j], at_point=point),
            ),
        )
        for name, value, at_point in checks:
            failure = _below(name, value, point=at_point)
            if failure:
                return failure
    return None


def _condition3(ev: _Evidence, i: int) -> str | None:
    """§7.4a condition 3: i's own coarse increment in every triple containing it has an interval
    below θ_min; an unresolved triple blocks, naming it."""
    for t, position in ev.own[i]:
        point, upper = ev.inc[t, position], ev.inc_hi[t, position]
        value, at_point = ev.coarse(i, point, upper, at_point=False)
        if math.isnan(value):
            return f"triple ({ev.triple(t)}) unresolved: no interval"
        if not value < THETA_MIN:
            what = "" if at_point else " upper"
            return (
                f"own coarse increment in ({ev.triple(t)}){what} {value:.4f} ≥ θ_min {THETA_MIN:g}"
            )
    return None


def _failures(ev: _Evidence, i: int, *, point: bool = False, upto: int = 5) -> list[str]:
    """The §7.4a conditions 1 to `upto` that fail for parameter i, each with its first failure:
    on the upper bounds, or (`point`, conditions 1 and 2 only) on the point estimates."""
    r = ev.result
    found = [
        _condition1(ev, i, point),
        _condition2(ev, i, point),
        None if point else _condition3(ev, i),
        None,
        None,
    ]
    if not point and r.aliased_pairs:
        a, b = r.aliased_pairs[0]
        found[3] = f"aliased inputs: {r.paths[a]} and {r.paths[b]}"
    if not point and r.veto is not None:
        found[4] = "residual veto raised"
    return [f"condition {n} ({what})" for n, what in enumerate(found[:upto], 1) if what]


def conditions(result: ImportanceResult, i: int) -> list[str]:
    """The §7.4a conditions 1-5 that parameter i fails, each as `condition <n> (<what>)` with its
    first failure, read as `failing` names them (a non-candidate's coarse terms at their point
    estimates, `_Evidence`); empty when all five hold."""
    return _failures(_Evidence(result, named=True), i)


def candidates(result: ImportanceResult) -> list[int]:
    """The coarse bootstrap's candidates (§7.4): the parameters passing §7.4a conditions 1 and 2
    on their point estimates; `[]` before the coarse point estimates exist."""
    ev = _Evidence(result)
    return [i for i in range(ev.d) if not _failures(ev, i, point=True, upto=2)]


def _period_dependent(ev: _Evidence, i: int) -> str | None:
    """Rule 3: a block whose S_i exceeds that block's family floor with its upper bound above
    θ_min, while another block's upper bound is below θ_min."""
    for b, mains in ev.blocks.items():
        if not (mains.S[i] > mains.floor[i] and mains.hi[i] > THETA_MIN):
            continue
        for c, other in ev.blocks.items():
            if c != b and other.hi[i] < THETA_MIN:
                return (
                    f"S {mains.S[i]:.4f} exceeds its floor in block {b} (upper "
                    f"{mains.hi[i]:.4f}); upper {other.hi[i]:.4f} < θ_min {THETA_MIN:g} in "
                    f"block {c}"
                )
    return None


def _interaction(ev: _Evidence, i: int) -> str | None:
    """Rule 5: some Δ_{i|j} exceeds its family floor and its upper bound θ_min (the largest)."""
    found = [
        (float(ev.D[i, j]), j)
        for j in range(ev.d)
        if j != i and ev.D[i, j] > ev.D_floor[i, j] and ev.D_hi[i, j] > THETA_MIN
    ]
    if not found:
        return None
    value, j = max(found)
    return (
        f"Δ beyond {ev.result.paths[j]} {value:.4f} exceeds its family floor "
        f"{ev.D_floor[i, j]:.4f}; upper {ev.D_hi[i, j]:.4f} > θ_min {THETA_MIN:g}"
    )


def _three_way(ev: _Evidence, i: int) -> str | None:
    """Rule 6: some own-direction Δ_{i|jk}^c exceeds its family floor and its upper bound θ_min
    (the largest). Only a candidate's triples have bounds (§7.4)."""
    found = [
        (float(ev.inc[t, p]), int(t), int(p))
        for t, p in ev.own[i]
        if ev.inc[t, p] > ev.inc_floor[t, p] and ev.inc_hi[t, p] > THETA_MIN
    ]
    if not found:
        return None
    value, t, p = max(found)
    return (
        f"own coarse increment in ({ev.triple(t)}) {value:.4f} exceeds its family floor "
        f"{ev.inc_floor[t, p]:.4f}; upper {ev.inc_hi[t, p]:.4f} > θ_min {THETA_MIN:g}"
    )


def _status(ev: _Evidence, i: int, proposable: bool) -> tuple[str, str]:
    """Decision 21's first rule that holds for parameter i, with its reason."""
    r = ev.result
    if r.labels[i] != MEASURED:
        size = int(r.B[i])
        return UNRESOLVED, (
            f"coverage: {r.values_held[i]} of {size} values hold ≥ {IMPORTANCE_MIN_PER_VALUE} "
            f"rows; n = {r.n:,} (needs {IMPORTANCE_MIN_N_FACTOR * size:,})"
        )
    if proposable:
        return PROPOSABLE, (
            f"§7.4a conditions 1-5 hold (every upper bound below θ_min {THETA_MIN:g}); awaits "
            "the operator's confirmation"
        )
    period = _period_dependent(ev, i)
    if period:
        return PERIOD_DEPENDENT, period
    if ev.S[i] > ev.S_floor[i]:
        return DETECTED, f"S {ev.S[i]:.4f} exceeds its family floor {ev.S_floor[i]:.4f}"
    for status, rule in ((INTERACTION, _interaction), (THREE_WAY, _three_way)):
        reason = rule(ev, i)
        if reason:
            return status, reason
    if math.isnan(ev.S[i]):
        return NOT_DETECTED, "not measured in block 0"
    return NOT_DETECTED, (
        f"S {ev.S[i]:.4f} within its family floor {ev.S_floor[i]:.4f}; no increment both "
        f"detected and above θ_min {THETA_MIN:g}"
    )


def _flags(ev: _Evidence, i: int) -> list[str]:
    r = ev.result
    flags = [
        f"aliased · credit shared with {r.paths[b if i == a else a]}"
        for a, b in r.aliased_pairs
        if i in (a, b)
    ]
    if math.isnan(ev.S[i]):
        flags.append("not measured in block 0")
    flags += [f"not measured in block {b}" for b, m in ev.blocks.items() if math.isnan(m.S[i])]
    return flags


def statuses(result: ImportanceResult) -> list[ParameterStatus]:
    """Every parameter's recommended status (decision 21), the `Measured` ones in path order and
    then the unresolved ones, last with their coverage. `failing` is set on every non-proposable
    parameter: the availability reason when the rule is unavailable, else the veto, else its first
    failed §7.4a condition as `not proposable: condition <n> (<what>)` (review B4), read as
    `conditions` reads it: a non-candidate's missing coarse bound never names a condition."""
    ev, named = _Evidence(result), _Evidence(result, named=True)
    available = result.availability.available
    out = []
    for i, path in enumerate(result.paths):
        failures = _failures(ev, i)
        proposable = available and result.veto is None and not failures
        if proposable:
            failing = None
        elif not available:
            failing = result.availability.reason
        elif result.veto is not None:
            failing = result.veto
        else:
            failing = f"not proposable: {(_failures(named, i) or failures)[0]}"
        status, reason = _status(ev, i, proposable)
        out.append(
            ParameterStatus(
                path=path,
                status=status,
                reason=reason,
                flags=_flags(ev, i),
                label=result.labels[i],
                proposable=proposable,
                failing=failing,
            )
        )
    return [s for s in out if s.label == MEASURED] + [s for s in out if s.label != MEASURED]


# --- the evidence scope (§7.4a, §8.5; decision 5) -----------------------------------------------

# The fields of an evidence scope, in the order `compare_scope` reads them; a field's name in the
# `stale` text where it differs from its key.
SCOPE_FIELDS = (
    "strategy_hash",
    "data",
    "ranges",
    "sampler",
    "blocks",
    "search_space.hash",
    "snapshot",
)
_SCOPE_NAMES = {"data": "data identity"}


def evidence_scope(document: Any, cohort: Cohort) -> dict:
    """The scope a result's evidence holds for (§7.4a): the strategy hash, the data identity
    (symbol, timeframe, range and pinned sha256), the surface's ranges, the sampler (method, seed,
    revision), the screening blocks, the search space's hash and the cohort's snapshot. `document`
    is an `ExperimentDocument` or a mapping of its fields."""
    fields = document.model_dump(mode="json") if hasattr(document, "model_dump") else document
    data = fields.get("data") or {}
    pinned = fields.get("data_pinned") or {}
    surface = fields.get("surface") or {}
    sampler = fields.get("sampler") or {}
    space = fields.get("search_space") or {}
    return {
        "strategy_hash": fields.get("strategy_hash"),
        "data": {
            "symbol": data.get("symbol"),
            "timeframe": data.get("timeframe"),
            "start": data.get("start"),
            "end": data.get("end"),
            "sha256": pinned.get("sha256"),
        },
        "ranges": {
            p["path"]: [p["start"], p["stop"], p["step"]] for p in surface.get("parameters", [])
        },
        "sampler": {key: sampler.get(key) for key in ("method", "seed", "revision")},
        "blocks": int(fields.get("blocks") or 0),
        "search_space.hash": space.get("hash"),
        "snapshot": cohort.snapshot,
    }


def compare_scope(evidence: Mapping, current: Mapping) -> str:
    """`current` when the evidence's scope is the current one, else `stale: <field> changed`, the
    first differing field in SCOPE_FIELDS' order (case 9: `stale: ranges changed`)."""
    for field in SCOPE_FIELDS:
        if evidence.get(field) != current.get(field):
            return f"stale: {_SCOPE_NAMES.get(field, field)} changed"
    return "current"


__all__ = [
    "ALIASED",
    "CONSTANTS",
    "DETECTED",
    "INCONSISTENT",
    "INTERACTION",
    "METRIC_HINT",
    "NOT_DETECTED",
    "NO_UNIFORM",
    "PERIOD_DEPENDENT",
    "PRODUCT_HINT",
    "PROPOSABLE",
    "SCOPE_FIELDS",
    "THREE_WAY",
    "UNAVAILABLE",
    "UNRESOLVED",
    "VETO",
    "VETO_WARNING",
    "Availability",
    "ImportanceResult",
    "ParameterStatus",
    "assess",
    "availability",
    "candidates",
    "compare_scope",
    "conditions",
    "evidence_scope",
    "importance_result",
    "missingness_note",
    "statuses",
    "veto",
]
