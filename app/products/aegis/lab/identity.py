"""Trial and engine identity for the Lab (Optimization Lab v2 spec §6.1-§6.2).

`param_key` names one configuration over the pinned spec's full effective parameter set, so the
same configuration keeps its key across surfaces, parents and children; `inputs_key` names the
computation an experiment's evaluations share; `engine_build` hashes the engine's sources once
per worker. `search_space`, `sampler` and `design_of` describe how an experiment samples. Pure
functions over the spec and plain mappings: this module never imports `experiments.py`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib import metadata
from pathlib import Path

from products.aegis import kernel
from products.aegis.optimize import step_decimals
from products.aegis.results import canonical_json
from products.aegis.strategy import LEVEL_FIELDS, StrategySpec
from products.aegis.surface import SIDE_KEYS, Surface, _whole_number, resolve_path

ENGINE_SOURCES = (
    "kernel.py",
    "backtest.py",
    "indicators.py",
    "kinds.py",
    "strategy.py",
    "temporal.py",
)
_ENGINE_ROOT = Path(__file__).resolve().parents[1]  # beside products/aegis/__init__.py
_DATA_IDENTITY = ("sha256", "data_hash", "timeframe", "start", "end")
_DESIGNS = {
    "grid": "uniform",
    "sample": "uniform",
    "rescreen": "uniform",
    "refine": "adaptive",
    "focused": "adaptive",
    "manual": "adaptive",
}


@lru_cache(maxsize=1)
def engine_build() -> str:
    """SHA-256 over the engine's sources, each framed as `name \\0 bytes \\0` in
    `ENGINE_SOURCES` order. Computed once at worker start (server.py's lifespan) and cached for
    the worker's life, so a source edited under a running worker does not move it."""
    digest = hashlib.sha256()
    for name in ENGINE_SOURCES:
        digest.update(name.encode() + b"\0" + (_ENGINE_ROOT / name).read_bytes() + b"\0")
    return digest.hexdigest()


def _installed(package: str) -> str | None:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return None


def versions(strategy_hash: str) -> dict:
    """The `versions` stamp of a document (§6.2)."""
    return {
        "strategy_hash": strategy_hash,
        "spec_version": StrategySpec.model_fields["version"].default,
        "engine": "kernel" if kernel.AVAILABLE else "reference",
        "engine_build": engine_build(),
        "numba": _installed("numba"),
        "numpy": _installed("numpy"),
        "pyarrow": _installed("pyarrow"),
    }


def full_effective_params(spec: StrategySpec) -> dict[str, float]:
    """Every tunable path of the spec with its value: each indicator's length and parameters
    (the kind's defaults included) and each set stop loss / take profit, on both sides whether
    enabled or not."""
    values: dict[str, float] = {}
    for side_key in SIDE_KEYS:
        side = getattr(spec, side_key)
        for indicator in side.indicators:
            prefix = f"{side_key}.indicators.{indicator.id}"
            values[f"{prefix}.length"] = float(indicator.length)
            for name, value in indicator.effective_params().items():
                values[f"{prefix}.params.{name}"] = float(value)
        for level in LEVEL_FIELDS:
            value = getattr(side, level)
            if value is not None:
                values[f"{side_key}.{level}"] = float(value)
    return values


def param_key(
    spec: StrategySpec, params: Mapping[str, float], steps: Mapping[str, float] | None = None
) -> bytes:
    """16-byte BLAKE2b of the canonical `{path: value}` JSON of the full effective set updated
    with `params`. Values are floats, so 15 and 15.0 are one configuration; a path with a step is
    rounded as `Parameter.values()` rounds its lattice, so `1.0 + 3 * 0.1` and 1.3 agree."""
    values = full_effective_params(spec)
    values.update({path: float(value) for path, value in params.items()})
    for path, step in (steps or {}).items():
        if path in values:
            values[path] = round(values[path], step_decimals(step))
    return hashlib.blake2b(canonical_json(values).encode(), digest_size=16).digest()


def param_key_hex(
    spec: StrategySpec, params: Mapping[str, float], steps: Mapping[str, float] | None = None
) -> str:
    return param_key(spec, params, steps).hex()


def inputs_key(strategy_hash: str, data: Mapping, settings: Mapping, engine_build: str) -> str:
    """32 hex characters naming the computation: two evaluations are the same iff `inputs_key`,
    `param_key` and `block` agree. `data` is the pinned source (or the `DataReference` when none
    was pinned) and `settings` the settings' JSON dump, never the model."""
    payload = {
        "strategy_hash": strategy_hash,
        "data": {name: data.get(name) for name in _DATA_IDENTITY},
        "settings": dict(settings),
        "engine_build": engine_build,
        "partition": None,
        "blocks": 0,
    }
    return hashlib.blake2b(canonical_json(payload).encode(), digest_size=16).hexdigest()


def search_space_hash(parameters: Sequence[dict]) -> str:
    """SHA-256 over the canonical JSON of the parameter entries, statuses and frozen values
    included, so a status flip moves the hash."""
    entries = [dict(entry) for entry in parameters]
    return hashlib.sha256(canonical_json(entries).encode()).hexdigest()


def search_space(spec: StrategySpec, surface: Surface) -> dict:
    """The `search_space` of a new experiment (§6.2): every surface parameter active."""
    parameters = []
    for parameter in surface.parameters:
        side_key, identifier, field = resolve_path(spec, parameter.path)
        side = side_key.split("_")[0]
        parameters.append(
            {
                "path": parameter.path,
                "type": "int" if _whole_number(spec, side_key, identifier, field) else "float",
                "start": parameter.start,
                "stop": parameter.stop,
                "step": parameter.step,
                "n_values": len(parameter.values()),
                "family": f"{side}:{identifier or 'levels'}",
                "status": "active",
                "frozen_value": None,
            }
        )
    return {
        "version": 1,
        "hash": search_space_hash(parameters),
        "parameters": parameters,
        "effective_dims": len(surface.parameters),
        "defined_dims": len(full_effective_params(spec)),
    }


def sampler(plan: dict, seed: int) -> dict:
    """The `sampler` of a new experiment from its plan's dump: the whole grid, or a Latin
    hypercube first pass then refinement. No budget shares and no blocks in Phase 2."""
    return {
        "method": "grid" if plan["mode"] == "exhaustive" else "lhs+refine",
        "seed": seed,
        "budget": {"total": plan["planned_runs"], "shares": None},
        "first_pass": plan["first_pass"],
        "refinement": plan["refinement"],
        "blocks": 0,
        "revision": 1,
    }


def design_of(pass_label: str) -> str:
    """A row's sampling design from its pass: `uniform` rows may feed importance (§7.3)."""
    try:
        return _DESIGNS[pass_label]
    except KeyError:
        raise ValueError(f"unknown pass {pass_label!r}") from None
