"""Deterministic result identity (spec §2b.2).

The canonical payload is the computational result only: strategy spec and version, data
identity, per-side and combined trades, equity, metrics and indicator series, the temporal
breakdown, and chart markers. Envelope fields (run id, job id, timestamps, elapsed time)
never enter it. `result_hash` is the SHA-256 of its canonical JSON serialization.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from products.aegis.backtest import markers
from products.aegis.strategy import StrategySpec

SIDE_KEYS = ("enabled", "series", "trades", "equity", "metrics")


def _clean(value: Any) -> Any:
    """Make a structure strict-JSON: NaN/inf become None, tuples become lists, keys are str."""
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def canonical_payload(result: dict, strategy: StrategySpec, data_identity: dict) -> dict:
    """The hash-bearing part of a backtest: everything a rerun must reproduce, nothing else."""
    sides = {
        side: {key: result[side][key] for key in SIDE_KEYS if key in result[side]}
        for side in ("long", "short")
    }
    combined = {key: result["combined"][key] for key in ("trades", "equity", "metrics")}
    return _clean(
        {
            "strategy": strategy.model_dump(mode="json"),
            "data": data_identity,
            "long": sides["long"],
            "short": sides["short"],
            "combined": combined,
            "temporal": result["temporal"],
            "markers": markers(result),
        }
    )


def walkforward_payload(
    records: list[dict],
    stitched: dict,
    stability: dict,
    request,
    data_identity: dict,
    unused_tail_bars: int,
) -> dict:
    """The hash-bearing part of a walk-forward (spec §5.6): the request's computational inputs,
    the pinned data, every window's choice and out-of-sample results, the stitched series and the
    stability figures. Envelope fields (job id, timestamps, elapsed) never enter it."""
    return _clean(
        {
            "kind": "walkforward",
            "strategy": request.strategy.model_dump(mode="json"),
            "data": data_identity,
            "side": request.side,
            "settings": {
                "initial_capital": request.settings.initial_capital,
                "allocation_fraction": request.settings.allocation_fraction,
            },
            "objective": request.objective,
            "in_sample_bars": request.in_sample_bars,
            "out_of_sample_bars": request.out_of_sample_bars,
            "windows": records,
            "unused_tail_bars": unused_tail_bars,
            "stitched": stitched,
            "stability": stability,
        }
    )


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def result_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
