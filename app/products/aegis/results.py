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
EQUITY_POINTS = 2_000  # a stored side curve's resolution (Mission 10 decision 2)
STORED_FORMAT = 2  # 2: no per-bar series, side equity resampled, markers once
_CHUNK = 1_000  # list items per C-encoded slice of the streamed hash


def _clean(value: Any) -> Any:
    """Make a structure strict-JSON: NaN/inf become None, tuples become lists, keys are str.
    Copy on write: a structure with nothing to change comes back as the same object, so a
    ten-year run's per-bar lists are not duplicated (Mission 10)."""
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, dict):
        out, changed = {}, False
        for k, v in value.items():
            key = k if isinstance(k, str) else str(k)
            cleaned = _clean(v)
            changed = changed or key is not k or cleaned is not v
            out[key] = cleaned
        return out if changed else value
    if isinstance(value, (list, tuple)):
        items, changed = [], isinstance(value, tuple)
        for v in value:
            cleaned = _clean(v)
            changed = changed or cleaned is not v
            items.append(cleaned)
        return items if changed else value
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


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stream(value: Any, update) -> None:
    """Feed the bytes of `canonical_json(value)` to `update` piece by piece: dicts key by key,
    long lists in C-encoded slices, so a ten-year run is never one string (Mission 10)."""
    if isinstance(value, dict):
        update("{")
        for i, key in enumerate(sorted(value)):
            update(("," if i else "") + _dumps(key) + ":")
            _stream(value[key], update)
        update("}")
    elif isinstance(value, list) and len(value) > _CHUNK:
        update("[")
        for start in range(0, len(value), _CHUNK):
            update(("," if start else "") + _dumps(value[start : start + _CHUNK])[1:-1])
        update("]")
    else:
        update(_dumps(value))


def stream_hash(payload: dict) -> str:
    """`result_hash(payload)`, computed without building the canonical JSON as one string."""
    digest = hashlib.sha256()
    _stream(payload, lambda text: digest.update(text.encode("utf-8")))
    return digest.hexdigest()


def slim_equity(points: list[dict], limit: int = EQUITY_POINTS) -> list[dict]:
    """A side curve resampled by index to at most `limit` points, the first and last kept."""
    if len(points) <= limit:
        return points
    last = len(points) - 1
    return [points[(k * last) // (limit - 1)] for k in range(limit)]


def envelope(
    result: dict,
    strategy: StrategySpec,
    settings,
    identity: dict,
    elapsed_ms: int,
    cache_hits: int = 0,
) -> dict:
    """The persisted run envelope around a backtest result: the hash-bearing payload plus the
    fields a reload needs (identity, strategy, settings, series, markers, engine)."""
    import uuid
    from datetime import UTC, datetime

    payload = canonical_payload(result, strategy, identity)
    digest = stream_hash(payload)  # over the full result, before anything is slimmed (decision 1)
    stored = {  # Mission 10: no per-bar series, side equity resampled, markers once
        **{key: value for key, value in payload.items() if key not in ("long", "short", "markers")},
        **{
            side: {
                **{k: v for k, v in payload[side].items() if k != "series"},
                "equity": slim_equity(payload[side]["equity"]),
            }
            for side in ("long", "short")
        },
    }
    return {
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": elapsed_ms,
        "result_hash": digest,
        "data": identity,
        "strategy_id": strategy.id,
        "strategy_hash": strategy_hash(strategy),
        "strategy": strategy.model_dump(mode="json"),
        "settings": settings.model_dump(mode="json"),
        "result": stored,
        "markers": payload["markers"],
        "stored": {
            "format": STORED_FORMAT,
            "equity_points": {side: len(payload[side]["equity"]) for side in ("long", "short")},
        },
        "cache_hits": cache_hits,
        "engine": result["engine"],
        "state": "ok",
    }


def strategy_hash(spec: StrategySpec) -> str:
    """Identity of a strategy spec (Mission 5 spec §8): SHA-256 of its canonical JSON. It sits on
    envelopes beside the result and never enters a result hash."""
    return result_hash(_clean(spec.model_dump(mode="json")))
