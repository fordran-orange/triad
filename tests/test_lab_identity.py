"""Optimization Lab v2, Phase 2, Task 3: trial and engine-build identity. `param_key` is taken
over the pinned spec's full effective parameter set, so one configuration keeps its key across
surfaces; `inputs_key` and `engine_build` identify the computation; `search_space`, `sampler`
and `design_of` describe the sampling; the policy constants keep the spec's values."""

import hashlib
from pathlib import Path

import products.aegis
import pytest
from products.aegis import kernel
from products.aegis.lab import policy
from products.aegis.lab.identity import (
    ENGINE_SOURCES,
    design_of,
    engine_build,
    full_effective_params,
    inputs_key,
    param_key,
    param_key_hex,
    sampler,
    search_space,
    search_space_hash,
    versions,
)
from products.aegis.strategy import IndicatorSpec, apply_parameters
from products.aegis.surface import KERNEL_MS_PER_BAR, Budget, Parameter, Surface, plan
from test_aegis_surface import pinned

pytestmark = pytest.mark.aegis

DONCHIAN = "long_side.indicators.donchian.length"
RSI = "long_side.indicators.rsi.length"
EMA = "short_side.indicators.ema.length"
SMA = "short_side.indicators.sma.length"
STOP = "long_side.stop_loss_pct"
DATA = {
    "symbol": "QQQ",
    "sha256": "a" * 64,
    "data_hash": "d" * 64,
    "timeframe": "1D",
    "start": "2020-01-02",
    "end": "2024-12-31",
}
SETTINGS = {"initial_capital": 100_000.0, "allocation_fraction": 1.0}


def two_surface() -> Surface:
    return Surface(
        parameters=[
            Parameter(path=DONCHIAN, start=10, stop=40, step=5),
            Parameter(path=RSI, start=7, stop=28, step=7),
        ]
    )


def steps_of(surface: Surface) -> dict[str, float]:
    return {p.path: p.step for p in surface.parameters}


def with_stop(spec, value: float = 2.0):
    return spec.model_copy(
        update={"long_side": spec.long_side.model_copy(update={"stop_loss_pct": value})}
    )


def test_param_key_over_full_effective_set():
    spec = pinned()
    two = two_surface()
    three = Surface(parameters=[*two.parameters, Parameter(path=SMA, start=20, stop=40, step=10)])
    params = {DONCHIAN: 15, RSI: 14}
    own = full_effective_params(spec)[SMA]
    assert own == 30.0
    key = param_key(spec, params, steps_of(two))
    assert len(key) == 16
    assert key == param_key(spec, {**params, SMA: own}, steps_of(three))  # stable across surfaces
    # Every tunable path of both sides, enabled or not; kind defaults and set levels included.
    assert set(full_effective_params(spec)) == {DONCHIAN, RSI, EMA, SMA}
    disabled = spec.model_copy(
        update={"short_side": spec.short_side.model_copy(update={"enabled": False})}
    )
    assert full_effective_params(disabled) == full_effective_params(spec)
    stopped = with_stop(spec)
    bands = IndicatorSpec(id="bb", kind="BB", length=20)
    indicators = [*stopped.long_side.indicators, bands]
    widened = stopped.model_copy(
        update={"long_side": stopped.long_side.model_copy(update={"indicators": indicators})}
    )
    full = full_effective_params(widened)
    multiplier = "long_side.indicators.bb.params.multiplier"
    assert set(full) - set(full_effective_params(spec)) == {
        "long_side.indicators.bb.length",
        multiplier,
        STOP,
    }
    assert full[multiplier] == 2.0 and full[STOP] == 2.0


def test_param_key_changes_with_a_non_surface_spec_value():
    spec = pinned()
    changed = spec.model_copy(
        update={"short_side": apply_parameters(spec.short_side, {"indicators.sma.length": 40})}
    )
    params = {DONCHIAN: 15, RSI: 14}
    steps = steps_of(two_surface())
    assert param_key(changed, params, steps) != param_key(spec, params, steps)


def test_param_key_rounds_as_parameter_values():
    spec = with_stop(pinned())
    steps = {STOP: 0.1}
    assert param_key(spec, {STOP: 1.0 + 3 * 0.1}, steps) == param_key(spec, {STOP: 1.3}, steps)
    # 1.0 + 3 * 0.1 is exactly 1.3 as a double; 1.0 + 7 * 0.1 drifts, and the step rounds it to
    # the lattice value Parameter.values() lists.
    drifted = 1.0 + 7 * 0.1
    assert drifted != 1.7
    assert Parameter(path=STOP, start=1.0, stop=2.0, step=0.1).values()[7] == 1.7
    assert param_key(spec, {STOP: drifted}, steps) == param_key(spec, {STOP: 1.7}, steps)
    assert param_key(spec, {STOP: drifted}) != param_key(spec, {STOP: 1.7})  # no step, no rounding


def test_param_key_literal_golden():
    params = {DONCHIAN: 15, RSI: 14}
    golden = "2a111d945faa85c7e00cf7a91d5f8b36"
    assert param_key_hex(pinned(), params) == golden
    assert param_key(pinned(), params).hex() == golden


def test_engine_build_is_sha256_over_the_six_sources():
    names = ("kernel.py", "backtest.py", "indicators.py", "kinds.py", "strategy.py", "temporal.py")
    assert ENGINE_SOURCES == names
    folder = Path(products.aegis.__file__).parent
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode() + b"\0" + (folder / name).read_bytes() + b"\0")
    build = engine_build()
    assert build == digest.hexdigest() and len(build) == 64
    hits = engine_build.cache_info().hits
    assert engine_build() == build
    assert engine_build.cache_info().hits == hits + 1
    assert engine_build.cache_info().currsize == 1
    stamped = versions("h" * 64)
    assert set(stamped) == {
        "strategy_hash",
        "spec_version",
        "engine",
        "engine_build",
        "numba",
        "numpy",
        "pyarrow",
    }
    assert stamped["strategy_hash"] == "h" * 64 and stamped["engine_build"] == build
    assert stamped["engine"] == ("kernel" if kernel.AVAILABLE else "reference")
    assert stamped["spec_version"] == pinned().version == 1


def test_inputs_key_differs_by_engine_build_and_data():
    base = inputs_key("s" * 64, DATA, SETTINGS, "b" * 64)
    assert inputs_key("s" * 64, dict(DATA), dict(SETTINGS), "b" * 64) == base
    assert inputs_key("s" * 64, DATA, SETTINGS, "c" * 64) != base
    assert inputs_key("s" * 64, {**DATA, "data_hash": "e" * 64}, SETTINGS, "b" * 64) != base
    assert inputs_key("s" * 64, {**DATA, "symbol": "SPY"}, SETTINGS, "b" * 64) != base
    # An unpinned document's identity is its DataReference: two symbols on one timeframe and
    # range never share a key.
    reference = {"symbol": "QQQ", "timeframe": "1D", "start": "2020-01-02", "end": "2024-12-31"}
    legacy = inputs_key("s" * 64, reference, SETTINGS, "b" * 64)
    assert inputs_key("s" * 64, {**reference, "symbol": "SPY"}, SETTINGS, "b" * 64) != legacy


def test_inputs_key_is_32_hex():
    key = inputs_key("a" * 64, DATA, {}, "b" * 64)
    assert len(key) == 32
    int(key, 16)


def test_search_space_hash_covers_parameters_and_statuses():
    spec = with_stop(pinned())
    surface = Surface(
        parameters=[*two_surface().parameters, Parameter(path=STOP, start=1.0, stop=2.0, step=0.5)]
    )
    space = search_space(spec, surface)
    assert space["version"] == 1
    assert space["hash"] == search_space_hash(space["parameters"])
    flipped = [dict(entry) for entry in space["parameters"]]
    flipped[0]["status"] = "frozen"
    assert search_space_hash(flipped) != space["hash"]
    for entry, parameter in zip(space["parameters"], surface.parameters, strict=True):
        assert entry["path"] == parameter.path
        assert entry["n_values"] == len(parameter.values())
        assert entry["status"] == "active" and entry["frozen_value"] is None
    assert [entry["type"] for entry in space["parameters"]] == ["int", "int", "float"]
    families = [entry["family"] for entry in space["parameters"]]
    assert families == ["long:donchian", "long:rsi", "long:levels"]
    assert space["effective_dims"] == 3 and space["defined_dims"] == 5


def test_design_of_each_pass():
    passes = ("grid", "sample", "rescreen", "refine", "focused", "manual")
    assert [design_of(label) for label in passes] == ["uniform"] * 3 + ["adaptive"] * 3
    with pytest.raises(ValueError, match="unknown pass"):
        design_of("other")
    # The sampler records the method that sets those passes: the grid, or LHS then refinement.
    spec, surface = pinned(), two_surface()
    exhaustive = plan(spec, surface, Budget(runs=1000), 3493, KERNEL_MS_PER_BAR, 10)
    assert sampler(exhaustive.model_dump(), 7) == {
        "method": "grid",
        "seed": 7,
        "budget": {"total": 28, "shares": None},
        "first_pass": 28,
        "refinement": 0,
        "blocks": 0,
        "revision": 1,
    }
    sampled = plan(spec, surface, Budget(runs=10), 3493, KERNEL_MS_PER_BAR, 10).model_dump()
    drawn = sampler(sampled, 7)
    assert drawn["method"] == "lhs+refine" and drawn["budget"]["total"] == 10
    assert (drawn["first_pass"], drawn["refinement"]) == (7, 3)


def test_policy_constants_match_spec():
    assert policy.AGG_MIN_N == 8
    assert policy.CONFOUNDED_TVD == 0.25
    assert policy.PAGE_LIMIT == 500
    assert policy.TOP_LIMIT == 500
    assert policy.MATRIX_MAX_AXIS == 200
    assert policy.MARGINAL_BUCKETS == 200
    assert policy.PARALLEL_MAX_BUNDLES == 2_000
    assert policy.COMPACT_EVERY == 50
    assert policy.RETAIN_MERGED_SECONDS == 600.0
    assert policy.LAB_CACHE_BYTES == 400 * 1024 * 1024
    assert policy.SHARPE_MIN_TRADES == 20
    assert policy.LOW_DISK_GB == 10
    # Phase 3 (Task 1): importance and interval constants (§7.3, §7.4).
    assert policy.IMPORTANCE_ROWS == 50_000
    assert policy.BOOTSTRAP_B == 200
    assert policy.PERMUTATION_P == 200
    assert policy.COARSE_BOOTSTRAP_B == 50
    assert policy.COARSE_PERMUTATION_P == 50
    assert policy.COARSE_BINS == 4
    assert policy.INTERVAL == 0.90
    assert policy.FLOOR_QUANTILE == 0.95
    # Blocks (§7.3a).
    assert policy.SCREEN_BLOCKS == 4
    assert policy.MAX_BLOCKS == 8
    # Coverage and aliasing (§7.3, §7.4).
    assert policy.IMPORTANCE_MIN_N_FACTOR == 30
    assert policy.IMPORTANCE_MIN_PER_VALUE == 20
    assert policy.ALIAS_V == 0.3
    assert policy.PAIR_MIN_N == 4
    assert policy.PAIR_MIN_COVERAGE == 0.5
    assert policy.PAIR_BALANCE_TVD == 0.25
    assert policy.TRIPLE_TOP == 20
    # The rule (§7.4, §7.4a).
    assert policy.RESIDUAL_VETO == 0.3
    assert policy.RESIDUAL_INCONSISTENT == -0.05
    assert policy.THETA_MIN == 0.01
    # Robustness (§7.6).
    assert policy.PLATEAU_MIN_COVERAGE == 0.5
    assert policy.NEIGHBOUR_R == 1
    assert policy.NEIGHBOUR_M_GRID == 1
    assert policy.NEIGHBOUR_M_SAMPLED == 2
    assert policy.PEAK_IQR_FACTOR == 3.0
    assert policy.REGION_RADIUS == 0.15
    assert policy.REGION_AXES == 6
    assert policy.REGION_MIN_N == 30
    assert policy.FOLDS_MIN == 3
    assert policy.FOLD_MIN_TRADES == 30
    assert policy.FOLD_RATIO_BAND == (0.5, 2.0)
    assert policy.FOLD_DRAWDOWN_FACTOR == 1.5
    assert policy.STRESS_KEEP == 0.70
    assert policy.STRESS_DRAWDOWN_FACTOR == 1.3
    # Pareto, parallel and convergence (§7.7, §7.9, §7.10).
    assert policy.PARETO_FRONT_MAX == 2_000
    assert policy.PARETO_DENSITY_BINS == 64
    assert policy.PARALLEL_MAX_LINES == 5_000
    assert policy.PARALLEL_STRATA == 10
    assert policy.CONVERGENCE_BATCH == 5_000
    assert policy.CONVERGENCE_TOP == 0.01
    assert policy.CONVERGENCE_MAX_POINTS == 1_000
    assert policy.MIN_BATCHES == 2
    assert policy.OBJECTIVES_MIN == 2
    assert policy.OBJECTIVES_MAX == 3
    # Task budgets (§9.4, §9.6).
    assert policy.TASK_BUDGET_S == 180
    assert policy.FINE_STAGE_BUDGET_S == 30
