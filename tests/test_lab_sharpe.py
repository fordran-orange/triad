"""Optimization Lab v2, Phase 2b: the per-trade Sharpe (`sharpe_trade`) and the deflated Sharpe
ratio (spec §7.12). Every expected value is computed here by the test's own formulas (its own
`erfc`-based Φ, its own bisection for Φ⁻¹, its own sums), never by calling the implementation."""

import itertools
import math

import numpy as np
import pytest
from products.aegis.lab import policy
from products.aegis.lab.sharpe import (
    deflated_sharpe,
    expected_max_sharpe,
    heuristic_scenarios,
    lag1_autocorrelation,
    lineage_ids,
    moments,
    normal_ppf,
    psr,
    research_cohort,
    sharpe_scopes,
    sharpe_trade,
)

pytestmark = pytest.mark.aegis

EULER_GAMMA = 0.5772156649015329


def phi(x: float) -> float:
    """The standard normal CDF, from `math.erfc`."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def bisect_ppf(p: float) -> float:
    """Φ⁻¹(p) by bisection on `phi`, solved on the lower tail (Φ⁻¹(p) = −Φ⁻¹(1 − p), and 1 − p
    is exact for p ≥ 0.5), so a tail probability keeps its relative precision."""
    q = min(p, 1.0 - p)
    lo, hi = -40.0, 0.0
    for _ in range(400):
        mid = 0.5 * (lo + hi)
        if mid in (lo, hi):
            break
        if phi(mid) < q:
            lo = mid
        else:
            hi = mid
    x = 0.5 * (lo + hi)
    return x if p <= 0.5 else -x


def hand_sharpe(ret) -> float:
    values = [float(v) for v in ret]
    n = len(values)
    mean = math.fsum(values) / n
    return mean / math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (n - 1))


def hand_moments(ret) -> tuple[float, float]:
    values = [float(v) for v in ret]
    n = len(values)
    mean = math.fsum(values) / n
    m2 = math.fsum((v - mean) ** 2 for v in values) / n
    m3 = math.fsum((v - mean) ** 3 for v in values) / n
    m4 = math.fsum((v - mean) ** 4 for v in values) / n
    return m3 / m2**1.5, m4 / m2**2


def hand_variance(values) -> float:
    """The sample variance (ddof = 1)."""
    values = [float(v) for v in values]
    mean = math.fsum(values) / len(values)
    return math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1)


def hand_rho1(ret) -> float:
    values = [float(v) for v in ret]
    mean = math.fsum(values) / len(values)
    d = [v - mean for v in values]
    return math.fsum(a * b for a, b in itertools.pairwise(d)) / math.fsum(x * x for x in d)


def hand_sr0(n: int, variance: float) -> float:
    return math.sqrt(variance) * (
        (1 - EULER_GAMMA) * bisect_ppf(1 - 1 / n) + EULER_GAMMA * bisect_ppf(1 - 1 / (n * math.e))
    )


def hand_psr(sr: float, sr0: float, t: int, skew: float, kurt: float) -> float:
    return phi((sr - sr0) * math.sqrt(t - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2))


def test_sharpe_normal_returns_t500():
    """Normal returns, T = 500. The seed is pinned: this vector's sample moments are
    γ3 ≈ −0.013 and γ4 ≈ 2.90 (SE(γ4) ≈ 0.22, so another seed could miss the bound)."""
    ret = np.random.default_rng(7).normal(0.001, 0.02, 500)
    sr = hand_sharpe(ret)
    assert abs(sharpe_trade(ret) - sr) < 1e-12
    skew, kurt = moments(ret)
    assert abs(skew) < 0.3
    assert abs(kurt - 3.0) < 0.3
    hand_skew, hand_kurt = hand_moments(ret)
    assert abs(skew - hand_skew) < 1e-12 and abs(kurt - hand_kurt) < 1e-12
    # PSR(0) with the exact normal moments (γ3 = 0, γ4 = 3), whose denominator is √(1 + SR²/2)
    value, reason = psr(sr, 0.0, 500, 0.0, 3.0)
    assert reason is None
    assert abs(value - phi(sr * math.sqrt(499) / math.sqrt(1 + sr**2 / 2))) < 1e-9


def test_normal_ppf_published_quantiles_and_bisection():
    published = {
        0.975: 1.959963984540054,
        0.99: 2.3263478740408408,
        0.999: 3.090232306167813,
        0.5: 0.0,
    }
    for p, x in published.items():
        assert abs(normal_ppf(p) - x) < 1e-12, p
    for p in np.linspace(1e-9, 1 - 1e-9, 200):
        p = float(p)
        assert abs(normal_ppf(p) - bisect_ppf(p)) < 1e-12, p
    for p in (0.0, 1.0, -0.25, 1.5, math.nan):
        with pytest.raises(ValueError):
            normal_ppf(p)


def test_dsr_paper_worked_example():
    """formula check with pinned inputs, not the paper's printed example"""
    # Bailey & López de Prado (2014, SSRN 2460551) is not in the repository, so its Appendix
    # numbers are not transcribed here; that transcription is an open question for R2.5 / R3.
    sr, t, skew, kurt, n, variance = 0.05, 500, -0.5, 4.0, 100, 0.0004
    sr0 = math.sqrt(variance) * (
        (1 - EULER_GAMMA) * bisect_ppf(1 - 1 / 100)
        + EULER_GAMMA * bisect_ppf(1 - 1 / (100 * math.e))
    )
    assert abs(expected_max_sharpe(n, variance) - sr0) < 1e-9
    dsr = phi((sr - sr0) * math.sqrt(499) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2))
    value, reason = psr(sr, sr0, t, skew, kurt)
    assert reason is None
    assert abs(value - dsr) < 1e-9

    # End to end: a seeded `ret` and a seeded 100-Sharpe cohort, against the test's own sample
    # Sharpe, moments and cohort variance (ddof = 1) of those same vectors.
    ret = np.random.default_rng(7).normal(0.001, 0.02, 500)
    cohort = np.random.default_rng(11).normal(0.0, 0.03, 100)
    sr = hand_sharpe(ret)
    skew, kurt = hand_moments(ret)
    variance = hand_variance(cohort)
    sr0 = hand_sr0(100, variance)
    result = deflated_sharpe(ret, cohort.tolist())
    assert result.reason is None
    assert abs(result.value - hand_psr(sr, sr0, 500, skew, kurt)) < 1e-9
    assert abs(result.sr - sr) < 1e-12 and abs(result.sr0 - sr0) < 1e-9
    assert result.variance == pytest.approx(variance, rel=1e-12)
    assert abs(result.skew - skew) < 1e-12 and abs(result.kurt - kurt) < 1e-12
    assert abs(result.rho1 - hand_rho1(ret)) < 1e-12
    assert (result.t, result.n, result.cohort) == (500, 100, "research history")


def test_sharpe_scopes_low_n_boundary():
    rng = np.random.default_rng(3)
    no_trades = np.empty(0)
    nineteen = sharpe_scopes(rng.normal(0.001, 0.02, 19), no_trades)
    assert nineteen["long"]["low_n"] is True and nineteen["long"]["trade_count"] == 19
    twenty = sharpe_scopes(rng.normal(0.001, 0.02, 20), no_trades)
    assert twenty["long"]["low_n"] is False and twenty["long"]["trade_count"] == 20
    mixed = sharpe_scopes(rng.normal(0.001, 0.02, 12), rng.normal(0.001, 0.02, 9))
    for scopes in (nineteen, twenty, mixed):
        assert set(scopes) == {"long", "short", "combined"}
        assert (
            scopes["combined"]["trade_count"]
            == scopes["long"]["trade_count"] + scopes["short"]["trade_count"]
        )
    assert nineteen["short"] == {"sharpe_trade": None, "trade_count": 0, "low_n": True}
    assert mixed["long"]["low_n"] is True and mixed["short"]["low_n"] is True
    assert mixed["combined"]["trade_count"] == 21 and mixed["combined"]["low_n"] is False
    assert policy.SHARPE_MIN_TRADES == 20


def test_sharpe_too_few_trades():
    cohort = [0.01, 0.02, 0.04]
    for t in (0, 1):
        ret = np.full(t, 0.01)
        assert sharpe_trade(ret) is None
        result = deflated_sharpe(ret, cohort)
        assert result.value is None and result.reason == "too few trades" and result.t == t
        assert psr(0.1, 0.0, t, 0.0, 3.0) == (None, "too few trades")
        scopes = sharpe_scopes(ret, np.empty(0))
        assert scopes["long"]["sharpe_trade"] is None and scopes["combined"]["sharpe_trade"] is None


def test_zero_variance():
    ret = np.full(50, 0.01)  # 0.01 is no binary fraction: the computed mean need not equal it
    assert sharpe_trade(ret) is None
    result = deflated_sharpe(ret, [0.01, 0.02, 0.04])
    assert result.value is None and result.reason == "zero variance"
    assert result.sr is None
    assert lag1_autocorrelation(ret) is None
    # a cohort whose Sharpes are all equal has V = 0, which leaves SR₀ undefined
    varied = np.random.default_rng(5).normal(0.001, 0.02, 40)
    flat_cohort = deflated_sharpe(varied, [0.07] * 5)
    assert flat_cohort.value is None and flat_cohort.reason == "cohort variance zero"
    assert flat_cohort.variance == 0.0 and flat_cohort.sr0 is None
    assert abs(flat_cohort.sr - hand_sharpe(varied)) < 1e-12


def test_skew_direction_three_cases():
    """Positive skew lowers the denominator (SR > 0): PSR rises when SR − SR₀ > 0, falls when
    SR − SR₀ < 0 and stays 0.5 when SR = SR₀."""
    t, kurt, skew = 50, 4.0, 0.8
    for sr, sr0 in ((0.3, 0.1), (0.1, 0.3), (0.2, 0.2)):
        flat, flat_reason = psr(sr, sr0, t, 0.0, kurt)
        skewed, skewed_reason = psr(sr, sr0, t, skew, kurt)
        assert flat_reason is None and skewed_reason is None
        assert abs(flat - hand_psr(sr, sr0, t, 0.0, kurt)) < 1e-12
        assert abs(skewed - hand_psr(sr, sr0, t, skew, kurt)) < 1e-12
        if sr > sr0:
            assert skewed > flat
        elif sr < sr0:
            assert skewed < flat
        else:
            assert flat == 0.5 and skewed == 0.5


def test_moment_denominator_undefined():
    # 1 − γ3·SR + (γ4 − 1)/4·SR²: 1 − 3 + 0.5 = −1.5, and 1 − 2 + 1 = 0 exactly
    assert psr(1.0, 0.0, 100, 3.0, 3.0) == (None, "moment denominator")
    assert psr(1.0, 0.0, 100, 2.0, 5.0) == (None, "moment denominator")
    value, reason = psr(1.0, 0.0, 100, 1.0, 3.0)  # 1 − 1 + 0.5 = 0.5: defined
    assert reason is None and abs(value - hand_psr(1.0, 0.0, 100, 1.0, 3.0)) < 1e-12


def test_repeated_strategies_do_not_grow_cohort():
    members = [
        ("exp-a", b"\x01key-1", 0.10),
        ("exp-a", b"\x01key-2", 0.20),
        ("exp-a", b"\x01key-1", 0.10),  # the same configuration twice in one experiment
        ("exp-b", b"\x01key-2", 0.20),  # exp-a's configuration again, in exp-b
        ("exp-b", b"\x01key-3", 0.30),
        ("exp-b", b"\x01key-4", None),  # undefined: never a member
        ("exp-a", b"\x01key-5", math.nan),  # non-finite: never a member
    ]
    cohort = research_cohort(members)
    assert cohort.n == 3 == len(cohort.sharpes)
    assert cohort.sharpes == [0.10, 0.20, 0.30]
    assert cohort.per_experiment == {"exp-a": 2, "exp-b": 1}
    assert sum(cohort.per_experiment.values()) == cohort.n
    again = research_cohort([*members, *[("exp-c", key, s) for _, key, s in members]])
    assert again.n == cohort.n and again.per_experiment == cohort.per_experiment


def _document(identifier, parent, strategy_hash, data_hash, sha256="sha-1"):
    return {
        "id": identifier,
        "parent": parent,
        "strategy_hash": strategy_hash,
        "data": {"symbol": "QQQ", "timeframe": "1h", "start": "2016-01-01", "end": "2026-09-18"},
        "data_pinned": {"sha256": sha256, "data_hash": data_hash, "symbol": "QQQ"},
    }


def test_research_history_cohort_parent_child_sibling():
    documents = [
        _document("parent", None, "h-1", "d-1"),
        _document("child", "parent", "h-1", "d-1"),
        _document("sibling", "parent", "h-2", "d-1"),  # another strategy: its own lineage
        _document("nephew", "sibling", "h-2", "d-1"),
        _document("grandchild", "child", "h-1", "d-1"),
        _document("other-data", "child", "h-1", "d-2"),  # a descendant on another data_hash
        _document("unrelated", None, "h-1", "d-1"),
    ]
    ids = lineage_ids(documents, "child")
    assert ids[0] == "child"
    assert sorted(ids) == ["child", "grandchild", "parent"]
    assert sorted(lineage_ids(documents, "parent")) == ["child", "grandchild", "parent"]
    assert lineage_ids(documents, "sibling") == ["sibling", "nephew"]

    trials = {
        "parent": [(b"k-1", 0.1), (b"k-2", 0.2)],
        "child": [(b"k-2", 0.2), (b"k-3", 0.3), (b"k-4", 0.4)],
        "sibling": [(b"k-9", 0.9)],
        "nephew": [(b"k-8", 0.8)],
        "grandchild": [(b"k-5", 0.5)],
        "other-data": [(b"k-6", 0.6)],
        "unrelated": [(b"k-7", 0.7)],
    }
    members = [(e, key, s) for e in ids for key, s in trials[e]]
    cohort = research_cohort(members)
    assert cohort.per_experiment == {"child": 3, "parent": 1, "grandchild": 1}
    assert cohort.n == 5 and sorted(cohort.sharpes) == [0.1, 0.2, 0.3, 0.4, 0.5]

    # Without a pin, the DataReference is the data identity.
    legacy = [
        {"id": "a", "parent": None, "strategy_hash": "h", "data": {"symbol": "QQQ", "end": "x"}},
        {"id": "b", "parent": "a", "strategy_hash": "h", "data": {"symbol": "QQQ", "end": "x"}},
        {"id": "c", "parent": "b", "strategy_hash": "h", "data": {"symbol": "QQQ", "end": "y"}},
    ]
    assert lineage_ids(legacy, "b") == ["b", "a"]

    # A pinned child of a legacy (unpinned) parent compares the DataReference of both.
    reference = {"symbol": "QQQ", "timeframe": "1h", "start": "2016-01-01", "end": "2026-09-18"}
    pin = {"sha256": "sha-1", "data_hash": "d-1"}
    mixed = [
        {"id": "legacy", "parent": None, "strategy_hash": "h", "data": reference},
        {"id": "pinned", "parent": "legacy", "strategy_hash": "h", "data": reference},
        {
            "id": "moved",
            "parent": "legacy",
            "strategy_hash": "h",
            "data": {**reference, "end": "2026-10-01"},
        },
    ]
    for document in mixed[1:]:
        document["data_pinned"] = pin
    assert lineage_ids(mixed, "pinned") == ["pinned", "legacy"]
    assert lineage_ids(mixed, "moved") == ["moved"]


def test_non_finite_input_undefined():
    base = np.random.default_rng(5).normal(0.001, 0.02, 40)
    cohort = [0.01, 0.02, 0.05]
    for bad in (math.nan, math.inf, -math.inf):
        ret = base.copy()
        ret[7] = bad
        assert sharpe_trade(ret) is None
        result = deflated_sharpe(ret, cohort)
        assert result.value is None and result.reason == "non-finite input"
        scopes = sharpe_scopes(ret, base)
        assert scopes["long"]["sharpe_trade"] is None and scopes["combined"]["sharpe_trade"] is None
        assert scopes["long"]["trade_count"] == 40
        assert deflated_sharpe(base, [*cohort, bad]).reason == "non-finite input"
        assert psr(bad, 0.0, 40, 0.0, 3.0) == (None, "non-finite input")
        assert psr(0.1, bad, 40, 0.0, 3.0) == (None, "non-finite input")
        assert expected_max_sharpe(10, bad) is None
    # non-finite input comes first: one NaN trade is not reported as too few trades
    assert deflated_sharpe(np.array([math.nan]), cohort).reason == "non-finite input"


def test_pure_noise_20_seeds():
    """spec:833: the best of 1,000 pure-noise trials (T = 50) has a DSR above 0.95 over its
    research-history cohort in at most 2 of 20 seeds (a Monte Carlo sanity check)."""
    above = 0
    for seed in range(20):
        trials = np.random.default_rng(seed).normal(0.0, 0.02, (1000, 50))
        sharpes = trials.mean(axis=1) / trials.std(axis=1, ddof=1)
        best = int(np.argmax(sharpes))
        result = deflated_sharpe(trials[best], sharpes.tolist())
        assert result.reason is None and result.n == 1000 and result.t == 50
        if result.value > 0.95:
            above += 1
    assert above <= 2


def test_combined_equals_concatenated_order_free():
    rng = np.random.default_rng(13)
    long, short = rng.normal(0.002, 0.02, 37), rng.normal(-0.001, 0.03, 23)
    scopes = sharpe_scopes(long, short)
    joined = np.concatenate([long, short])
    combined = scopes["combined"]["sharpe_trade"]
    assert abs(combined - hand_sharpe(joined)) < 1e-12
    assert abs(combined - hand_sharpe(joined[::-1])) < 1e-12
    assert abs(combined - hand_sharpe(np.concatenate([short, long]))) < 1e-12
    assert abs(scopes["long"]["sharpe_trade"] - hand_sharpe(long)) < 1e-12
    assert abs(scopes["short"]["sharpe_trade"] - hand_sharpe(short)) < 1e-12
    assert scopes["combined"]["trade_count"] == 60


def test_ar1_autocorrelation_flag():
    rng = np.random.default_rng(17)
    noise = rng.normal(0.0, 0.02, 5000)
    ret = np.empty(5000)
    ret[0] = noise[0]
    for i in range(1, 5000):
        ret[i] = 0.5 * ret[i - 1] + noise[i]
    ret += 0.001
    rho1 = lag1_autocorrelation(ret)
    assert abs(rho1 - 0.5) < 0.1
    assert abs(rho1 - hand_rho1(ret)) < 1e-12
    cohort = [0.01, 0.03, 0.02, 0.05]
    result = deflated_sharpe(ret, cohort)
    assert abs(result.rho1 - rho1) < 1e-15 and result.autocorrelated is True
    white = deflated_sharpe(rng.normal(0.001, 0.02, 5000), cohort)
    assert abs(white.rho1) < 0.2 and white.autocorrelated is False
    assert lag1_autocorrelation(ret[:2]) is None


def test_heuristic_scenarios_undefined_below_two():
    sharpe_by_cell = {1: 0.10, 2: 0.30, 3: -0.05, 4: 0.20, 5: None, 6: 0.25}
    regions = [{"centre": {"cell": 4}}, {"centre": {"cell": 6}}]
    one_cluster = {"clusters": {"k": 2, "groups": [{"exemplar": 1}]}, "plateaus": regions}
    clusters_scenario, regions_scenario = heuristic_scenarios(one_cluster, sharpe_by_cell)
    assert clusters_scenario["value"] is None and clusters_scenario["reason"] == "cohort below 2"
    assert clusters_scenario["n"] == 1 and clusters_scenario["sr0"] is None
    # without a candidate the cohort's SR₀ is still reported, and the DSR is undefined
    assert regions_scenario["reason"] == "no candidate" and regions_scenario["value"] is None
    assert regions_scenario["n"] == 2
    variance = hand_variance([0.20, 0.25])
    assert regions_scenario["variance"] == pytest.approx(variance, rel=1e-12)
    assert abs(regions_scenario["sr0"] - hand_sr0(2, variance)) < 1e-9
    for scenario in (clusters_scenario, regions_scenario):
        assert set(scenario) == {"label", "n", "variance", "sr0", "value", "reason"}
        assert scenario["label"].startswith("heuristic scenario")
    assert "clusters" in clusters_scenario["label"] and "regions" in regions_scenario["label"]
    equal = heuristic_scenarios(
        {"clusters": {"groups": []}, "plateaus": [{"centre": {"cell": c}} for c in (7, 8)]},
        {7: 0.15, 8: 0.15},
    )[1]
    assert equal["reason"] == "cohort variance zero" and equal["variance"] == 0.0
    assert equal["sr0"] is None and equal["value"] is None

    # an undefined exemplar is no member, and a refused clustering has none
    undefined = {"clusters": {"groups": [{"exemplar": 1}, {"exemplar": 5}]}, "plateaus": []}
    assert [s["reason"] for s in heuristic_scenarios(undefined, sharpe_by_cell)] == [
        "cohort below 2",
        "cohort below 2",
    ]
    refused = {"clusters": {"refused": "fewer than 20 valid cells"}, "plateaus": regions}
    assert heuristic_scenarios(refused, sharpe_by_cell)[0]["reason"] == "cohort below 2"

    # the scenarios keep the input order (clusters, then regions), whichever value is larger
    wide = [{"exemplar": 1}, {"exemplar": 2}, {"exemplar": 3}]
    narrow = [{"exemplar": 4}, {"exemplar": 6}]
    centres_wide = [{"centre": {"cell": c}} for c in (1, 2, 3)]
    first = heuristic_scenarios({"clusters": {"groups": wide}, "plateaus": regions}, sharpe_by_cell)
    second = heuristic_scenarios(
        {"clusters": {"groups": narrow}, "plateaus": centres_wide}, sharpe_by_cell
    )
    assert first[0]["sr0"] > first[1]["sr0"] and second[0]["sr0"] < second[1]["sr0"]
    for scenarios in (first, second):
        assert "clusters" in scenarios[0]["label"] and "regions" in scenarios[1]["label"]
    assert abs(first[0]["sr0"] - hand_sr0(3, hand_variance([0.10, 0.30, -0.05]))) < 1e-9

    # with a candidate, each scenario's value is the candidate's PSR at that scenario's SR₀
    ret = np.random.default_rng(7).normal(0.001, 0.02, 500)
    candidate = deflated_sharpe(ret, np.random.default_rng(11).normal(0.0, 0.03, 100).tolist())
    two_clusters = {"clusters": {"groups": [{"exemplar": 1}, {"exemplar": 2}]}, "plateaus": regions}
    scenarios = heuristic_scenarios(two_clusters, sharpe_by_cell, candidate=candidate)
    sr = hand_sharpe(ret)
    skew, kurt = hand_moments(ret)
    for scenario, members in zip(scenarios, ([0.10, 0.30], [0.20, 0.25]), strict=True):
        sr0 = hand_sr0(2, hand_variance(members))
        assert scenario["reason"] is None and abs(scenario["sr0"] - sr0) < 1e-9
        assert abs(scenario["value"] - hand_psr(sr, sr0, 500, skew, kurt)) < 1e-9
    assert "clusters" in scenarios[0]["label"] and "regions" in scenarios[1]["label"]
    assert scenarios[0]["value"] < scenarios[1]["value"]  # the input order, not sorted by value
    no_sharpe = deflated_sharpe(np.full(50, 0.01), [0.01, 0.02])
    assert [
        s["reason"] for s in heuristic_scenarios(two_clusters, sharpe_by_cell, candidate=no_sharpe)
    ] == ["no candidate", "no candidate"]
