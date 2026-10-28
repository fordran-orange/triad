"""Trade Sharpe and the deflated Sharpe ratio (Optimization Lab v2 spec §7.12, Phase 2b).

`sharpe_trade` is per trade and not annualized: mean / std (ddof = 1) of a scope's trade returns
`ret = net / capital_at_entry`. It is computed beside the hash-bearing metrics (a row's
`lab_metrics`), never inside `backtest._metrics`, so no `result_hash` moves. The deflated Sharpe
ratio (Bailey and López de Prado, 2014) is a number with its inputs, never a pass / fail.
numpy and math only: Φ from `math.erfc`, Φ⁻¹ by Acklam's approximation refined by one Newton
step on `math.erfc`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from products.aegis.lab import policy

EULER_GAMMA = 0.5772156649015329
_AUTOCORRELATED = 0.2  # |ρ1| above this: "trades autocorrelated: evidence overstated"

# Acklam's rational approximation of Φ⁻¹ (relative error below 1.15e-9 before refinement).
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_P_LOW = 0.02425


def _varies(values: np.ndarray) -> bool:
    """Finite and not all equal (an exact test: the mean of equal values need not equal them)."""
    return bool(np.isfinite(values).all()) and float(values.min()) != float(values.max())


def sharpe_trade(ret: np.ndarray) -> float | None:
    """mean(ret) / std(ret, ddof = 1), per trade and not annualized; None below 2 trades, for
    zero variance (every return equal) or for a non-finite input or result."""
    values = np.asarray(ret, dtype=np.float64)
    if values.size < 2 or not _varies(values):
        return None
    with np.errstate(over="ignore", invalid="ignore"):  # an overflow is a non-finite result
        std = float(values.std(ddof=1))
        mean = float(values.mean())
    if not (std > 0.0 and math.isfinite(std)):
        return None
    sr = mean / std
    return sr if math.isfinite(sr) else None


def _scope(values: np.ndarray) -> dict:
    count = int(values.size)
    return {
        "sharpe_trade": sharpe_trade(values),
        "trade_count": count,
        "low_n": count < policy.SHARPE_MIN_TRADES,
    }


def sharpe_scopes(long_ret: np.ndarray, short_ret: np.ndarray) -> dict[str, dict]:
    """The trade Sharpe of each scope; `combined` is the Sharpe of both sides' trades together
    (mean and std are order-free, so their concatenation stands for the merged trade list)."""
    long_values = np.asarray(long_ret, dtype=np.float64)
    short_values = np.asarray(short_ret, dtype=np.float64)
    return {
        "long": _scope(long_values),
        "short": _scope(short_values),
        "combined": _scope(np.concatenate([long_values, short_values])),
    }


def moments(ret: np.ndarray) -> tuple[float, float]:
    """(γ3, γ4): the skewness m3 / m2^1.5 and the kurtosis m4 / m2^2 (non-excess, 3 for a normal)
    as plain ratios of the central sample moments m_k = mean((ret − mean)^k); (nan, nan) when
    there is no variance to divide by (fewer than 2 trades, all equal, or a non-finite input)."""
    values = np.asarray(ret, dtype=np.float64)
    if values.size < 2 or not _varies(values):
        return math.nan, math.nan
    d = values - values.mean()
    m2 = float(np.mean(d**2))
    if not m2 > 0.0:
        return math.nan, math.nan
    return float(np.mean(d**3)) / m2**1.5, float(np.mean(d**4)) / m2**2


def lag1_autocorrelation(ret: np.ndarray) -> float | None:
    """ρ1 = Σ (r_t − r̄)(r_t+1 − r̄) / Σ (r_t − r̄)², the sample lag-1 autocorrelation of the trade
    returns in trade order; None below 3 trades, for zero variance or a non-finite input."""
    values = np.asarray(ret, dtype=np.float64)
    if values.size < 3 or not _varies(values):
        return None
    d = values - values.mean()
    denominator = float(np.dot(d, d))
    if not denominator > 0.0:
        return None
    rho = float(np.dot(d[:-1], d[1:])) / denominator
    return rho if math.isfinite(rho) else None


def normal_cdf(x: float) -> float:
    """Φ(x), from `math.erfc`."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def normal_ppf(p: float) -> float:
    """Φ⁻¹(p) for 0 < p < 1: Acklam's rational approximation refined by one Newton step on
    `math.erfc`. The upper half is solved as −Φ⁻¹(1 − p) (1 − p is exact for p ≥ 0.5), so a tail
    probability keeps its relative precision. ValueError outside (0, 1)."""
    if not 0.0 < p < 1.0:  # NaN fails this too
        raise ValueError(f"normal_ppf needs 0 < p < 1, got {p!r}")
    if p > 0.5:
        return -_lower_ppf(1.0 - p)
    return _lower_ppf(p)


def _lower_ppf(p: float) -> float:
    """Φ⁻¹(p) for 0 < p ≤ 0.5."""
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    else:
        q = p - 0.5
        r = q * q
        x = (
            (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5])
            * q
            / (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
        )
    density = math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    if density > 0.0:  # one Newton step on Φ(x) − p
        x -= (normal_cdf(x) - p) / density
    return x


def expected_max_sharpe(n: int, variance: float) -> float | None:
    """SR₀ = √V · ((1 − γ) · Φ⁻¹(1 − 1/N) + γ · Φ⁻¹(1 − 1/(N·e))), the expected maximum Sharpe of
    N independent trials whose Sharpe estimates have variance V (γ the Euler–Mascheroni constant);
    Φ⁻¹(1 − q) is taken as −Φ⁻¹(q), which needs no rounding of 1 − q. None when N < 2, V ≤ 0 or
    V is not finite."""
    if n < 2 or variance is None or not math.isfinite(variance) or variance <= 0.0:
        return None
    return math.sqrt(variance) * (
        (1.0 - EULER_GAMMA) * -normal_ppf(1.0 / n) + EULER_GAMMA * -normal_ppf(1.0 / (n * math.e))
    )


def _finite(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def psr(sr: float, sr0: float, t: int, skew: float, kurt: float) -> tuple[float | None, str | None]:
    """PSR(SR₀) = Φ((SR − SR₀) · √(T − 1) / √(1 − γ3·SR + (γ4 − 1)/4 · SR²)) as (value, reason).
    Undefined, in order of precedence: "non-finite input" (SR, SR₀, γ3 or γ4), "too few trades"
    (T < 2), "moment denominator" (the radicand ≤ 0)."""
    if not all(_finite(v) for v in (sr, sr0, skew, kurt)):
        return None, "non-finite input"
    if t < 2:
        return None, "too few trades"
    radicand = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    if not radicand > 0.0:
        return None, "moment denominator"
    value = normal_cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(radicand))
    if not math.isfinite(value):
        return None, "non-finite input"
    return value, None


def _cohort_variance(sharpes: np.ndarray) -> float:
    """V: the sample variance (ddof = 1) of the cohort's Sharpe values; exactly 0 when they are
    all equal."""
    if float(sharpes.min()) == float(sharpes.max()):
        return 0.0
    return float(np.var(sharpes, ddof=1))


@dataclass(frozen=True)
class Dsr:
    """The deflated Sharpe ratio with every input it was computed from (§7.12), never a verdict.

    `value` = PSR(SR₀) or None with `reason`; `sr` the candidate's `sharpe_trade`, `t` its trade
    count, `skew` / `kurt` its γ3 / γ4 (`moments`), `rho1` its lag-1 autocorrelation and
    `autocorrelated` when |ρ1| > 0.2; `n` the cohort's member count and `variance` V, the sample
    variance (ddof = 1, as `sharpe_trade`'s own std) of the cohort's Sharpe values; `sr0` the
    expected maximum Sharpe of those N trials; `cohort` names the cohort ("research history")."""

    value: float | None
    reason: str | None
    sr: float | None
    sr0: float | None
    t: int
    n: int
    variance: float | None
    skew: float | None
    kurt: float | None
    rho1: float | None
    autocorrelated: bool
    cohort: str


def deflated_sharpe(
    ret: np.ndarray, cohort_sharpes: Sequence[float], cohort: str = "research history"
) -> Dsr:
    """DSR = PSR(SR₀) of the candidate's trade returns `ret` against the cohort's Sharpe values.
    Undefined, in order of precedence: "non-finite input" (in `ret` or the cohort), "too few
    trades" (T < 2), "zero variance" (every return equal), "cohort below 2", then "zero variance"
    again when every cohort Sharpe is equal (V = 0 leaves SR₀ undefined), "moment denominator"."""
    values = np.asarray(ret, dtype=np.float64)
    sharpes = np.array(
        [math.nan if s is None else float(s) for s in cohort_sharpes], dtype=np.float64
    )
    t, n = int(values.size), int(sharpes.size)
    known: dict = {}

    def undefined(reason: str, **inputs) -> Dsr:
        fields = {
            "sr": None,
            "sr0": None,
            "variance": None,
            "skew": None,
            "kurt": None,
            "rho1": None,
            "autocorrelated": False,
            **known,
            **inputs,
        }
        return Dsr(value=None, reason=reason, t=t, n=n, cohort=cohort, **fields)

    if not (np.isfinite(values).all() and np.isfinite(sharpes).all()):
        return undefined("non-finite input")
    if t < 2:
        return undefined("too few trades")
    sr = sharpe_trade(values)
    if sr is None:  # finite and T ≥ 2: every return equal, or the arithmetic overflowed
        with np.errstate(over="ignore", invalid="ignore"):
            flat = not _varies(values) or float(values.std(ddof=1)) == 0.0
        return undefined("zero variance" if flat else "non-finite input")
    skew, kurt = moments(values)
    rho1 = lag1_autocorrelation(values)
    known.update(
        sr=sr,
        skew=skew,
        kurt=kurt,
        rho1=rho1,
        autocorrelated=rho1 is not None and abs(rho1) > _AUTOCORRELATED,
    )
    if n < 2:
        return undefined("cohort below 2")
    variance = _cohort_variance(sharpes)
    sr0 = expected_max_sharpe(n, variance)
    if sr0 is None:
        return undefined(
            "zero variance" if variance == 0.0 else "non-finite input", variance=variance
        )
    value, reason = psr(sr, sr0, t, skew, kurt)
    return Dsr(
        value=value, reason=reason, t=t, n=n, cohort=cohort, sr0=sr0, variance=variance, **known
    )


@dataclass(frozen=True)
class Cohort:
    """The research-history cohort (§7.12): one Sharpe per distinct configuration (`param_key`)
    with a defined `sharpe_trade`. `per_experiment` counts the members each experiment brought
    (the printed "N = 48,210 across 3 sweeps"); an experiment that brought none is absent.
    `n == len(sharpes) == sum(per_experiment.values())`."""

    sharpes: list[float]
    n: int
    per_experiment: dict[str, int]


def research_cohort(members: Iterable[tuple[str, bytes, float | None]]) -> Cohort:
    """The cohort of `(experiment_id, param_key, sharpe_trade)` members, in their order: an
    undefined Sharpe (None or non-finite) is dropped first, then the first experiment to bring a
    key keeps it, so repeating a configuration, in one experiment or across them, never grows N."""
    seen: set[bytes] = set()
    sharpes: list[float] = []
    per_experiment: dict[str, int] = {}
    for experiment_id, param_key, sharpe in members:
        key = bytes(param_key)
        if not _finite(sharpe) or key in seen:
            continue
        seen.add(key)
        sharpes.append(float(sharpe))
        per_experiment[experiment_id] = per_experiment.get(experiment_id, 0) + 1
    return Cohort(sharpes=sharpes, n=len(sharpes), per_experiment=per_experiment)


def _lineage_identity(document: Mapping) -> tuple:
    """The strategy hash and the data identity: the pinned archive (sha256 + data_hash) when the
    experiment recorded one, else its DataReference."""
    pinned = document.get("data_pinned")
    if pinned:
        data = ("pinned", pinned.get("sha256"), pinned.get("data_hash"))
    else:
        data = ("reference", document.get("data"))
    return document.get("strategy_hash"), data


def lineage_ids(documents: Sequence[dict], experiment_id: str) -> list[str]:
    """The research history of one experiment: itself first, then its ancestors (nearest first)
    and its descendants (breadth first, in the documents' order) by `parent`, kept when they share
    its strategy hash and data identity. Siblings and cousins are not ancestors or descendants."""
    by_id = {document["id"]: document for document in documents}
    identity = _lineage_identity(by_id[experiment_id])
    seen = {experiment_id}
    related: list[str] = []
    parent = by_id[experiment_id].get("parent")
    while parent is not None and parent in by_id and parent not in seen:
        seen.add(parent)
        related.append(parent)
        parent = by_id[parent].get("parent")
    children: dict[str, list[str]] = {}
    for document in documents:
        if document.get("parent") is not None:
            children.setdefault(document["parent"], []).append(document["id"])
    queue = [experiment_id]
    while queue:
        current = queue.pop(0)
        for child in children.get(current, []):
            if child not in seen:
                seen.add(child)
                related.append(child)
                queue.append(child)
    return [experiment_id] + [i for i in related if _lineage_identity(by_id[i]) == identity]


def _scenario(label: str, cells: list[int], sharpe_by_cell: Mapping[int, float | None]) -> dict:
    sharpes = [float(s) for s in (sharpe_by_cell.get(cell) for cell in cells) if _finite(s)]
    n = len(sharpes)
    if n < 2:
        return {"label": label, "n": n, "variance": None, "value": None, "reason": "cohort below 2"}
    variance = _cohort_variance(np.array(sharpes, dtype=np.float64))
    value = expected_max_sharpe(n, variance)
    reason = None
    if value is None:
        reason = "zero variance" if variance == 0.0 else "non-finite input"
    return {"label": label, "n": n, "variance": variance, "value": value, "reason": reason}


def heuristic_scenarios(report: dict, sharpe_by_cell: Mapping[int, float | None]) -> list[dict]:
    """The two sensitivity scenarios of §7.12, labelled heuristic: N and V taken over (a) the
    exemplar (medoid) trials of the report's outcome clusters and (b) the centre trials of its
    plateaus. Each carries its N, V and `value` = SR₀, the expected maximum Sharpe of that cohort
    (the candidate's DSR under the scenario is `psr(sr, value, t, skew, kurt)`); fewer than 2
    defined members leave it undefined, "cohort below 2". They are not bounds and never sorted:
    the list is always the clusters scenario, then the regions scenario."""
    clusters = report.get("clusters")
    groups = (clusters.get("groups") or []) if isinstance(clusters, dict) else []
    plateaus = report.get("plateaus") or []
    return [
        _scenario(
            f"heuristic scenario: if only the {len(groups)} clusters counted as distinct strategies",
            [group["exemplar"] for group in groups],
            sharpe_by_cell,
        ),
        _scenario(
            f"heuristic scenario: if only the {len(plateaus)} regions counted as distinct "
            "strategies",
            [plateau["centre"]["cell"] for plateau in plateaus],
            sharpe_by_cell,
        ),
    ]
