"""Aegis worker routes (spec §7): pinned raw data, indicators, backtests and persisted runs.

Loopback-only like every route on this product host; nothing here touches money, credentials
or Core state. Exceptions map to: BarsTooLarge → 422 with the range hint, a pinned archive that
drifted → `state: source_unavailable` on the reloaded run (200), JobBusy → 409, unknown
symbol/run/job → 404.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from products.aegis.backtest import BacktestRequest, DataReference, markers, run_backtest
from products.aegis.data import (
    TIMEFRAMES,
    ArchiveStore,
    BarsTooLarge,
    PinnedSource,
    SourceUnavailable,
    to_records,
)
from products.aegis.indicators import IndicatorCache, compute
from products.aegis.jobs import JobBusy, JobRunner, estimate_seconds
from products.aegis.kinds import kind_info
from products.aegis.optimize import OptimizeRequest, OptimizerJob, engine_rows, expand_grid
from products.aegis.results import canonical_payload, result_hash
from products.aegis.runs import JsonRunRepository, RunRepository
from products.aegis.strategy import IndicatorSpec
from products.aegis.walkforward import WalkForwardJob, WalkForwardRequest
from products.aegis.walkforward import plan as walkforward_plan

log = logging.getLogger("aegis")
router = APIRouter(prefix="/aegis/api")


@lru_cache(maxsize=1)
def get_store() -> ArchiveStore:
    return ArchiveStore()


@lru_cache(maxsize=1)
def get_repository() -> RunRepository:
    return JsonRunRepository()


@lru_cache(maxsize=1)
def get_runner() -> JobRunner:
    return JobRunner(get_repository())


@lru_cache(maxsize=1)
def get_cache() -> IndicatorCache:
    """Indicator series shared by plain backtests on this worker, keyed by the bars' content
    identity and bounded to the most recent eight selections (spec §6.4)."""
    return IndicatorCache(max_data_keys=8)


STORE = Depends(get_store)
REPOSITORY = Depends(get_repository)
RUNNER = Depends(get_runner)
CACHE = Depends(get_cache)


def warm_in_background(store) -> threading.Thread:
    """Spec §6: resample every discovered symbol once at startup so first touches are warm."""

    def warm():
        try:
            store.warm([source.symbol for source in store.symbols()])
        except Exception as exc:  # noqa: BLE001 - warm-up is a convenience; a failure must not matter
            log.warning("archive warm-up skipped: %s: %s", type(exc).__name__, exc)

    thread = threading.Thread(target=warm, name="aegis-warmup", daemon=True)
    thread.start()
    return thread


def _timeframe(value: str) -> str:
    if value not in TIMEFRAMES:
        raise HTTPException(422, f"unknown timeframe {value!r}; expected one of {list(TIMEFRAMES)}")
    return value


def _select(store: ArchiveStore, symbol: str, timeframe: str, start, end):
    try:
        return store.bars(symbol, _timeframe(timeframe), start, end)
    except KeyError as exc:
        raise HTTPException(404, f"unknown symbol {symbol!r}") from exc
    except BarsTooLarge as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _provenance(pinned: PinnedSource) -> dict:
    return pinned.model_dump(mode="json")


@router.get("/data/symbols")
def symbols(store: ArchiveStore = STORE):
    return {
        "timeframes": list(TIMEFRAMES),
        "symbols": [source.model_dump(mode="json") for source in store.symbols()],
    }


@router.get("/data/bars")
def bars(
    symbol: str,
    timeframe: str,
    start: str = Query(..., description="inclusive YYYY-MM-DD, America/New_York"),
    end: str = Query(..., description="inclusive YYYY-MM-DD, America/New_York"),
    store: ArchiveStore = STORE,
):
    frame, pinned = _select(store, symbol, timeframe, start, end)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": "America/New_York",
        "bars": to_records(frame),
        "count": len(frame),
        "data": _provenance(pinned),
    }


class IndicatorsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    timeframe: str
    start: str
    end: str
    indicators: list[IndicatorSpec] = Field(max_length=32)


@router.post("/indicators")
def indicators(request: IndicatorsRequest, store: ArchiveStore = STORE):
    frame, pinned = _select(store, request.symbol, request.timeframe, request.start, request.end)
    series, outputs, panes = {}, {}, {}
    for spec in request.indicators:
        info = kind_info(spec.kind)
        outputs[spec.id] = list(info.outputs)
        panes[spec.id] = info.pane
        try:
            produced = compute(spec, frame)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        for column in produced.columns:
            series[column] = [
                None if math.isnan(v) else float(v) for v in produced[column].tolist()
            ]
    return {
        "times": [record["time"] for record in to_records(frame)],
        "series": series,
        "outputs": outputs,
        "pane": panes,
        "data": _provenance(pinned),
    }


def _envelope(request: BacktestRequest, store: ArchiveStore, cache: IndicatorCache) -> dict:
    started = time.perf_counter()
    hits_before = cache.hits
    if request.data is not None:
        frame, pinned = _select(
            store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
        )
        engine_request = request.model_copy(
            update={"bars": engine_rows(frame, request.data.symbol)}
        )
        identity = _provenance(pinned)
    else:
        engine_request = request
        identity = {"source": "supplied_bars", "bar_count": len(request.bars)}
    try:
        result = run_backtest(engine_request, cache=cache)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    payload = canonical_payload(result, request.strategy, identity)
    return {
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "result_hash": result_hash(payload),
        "data": identity,
        "strategy": request.strategy.model_dump(mode="json"),
        "settings": request.settings.model_dump(mode="json"),
        "result": payload,
        "series": {"long": result["long"]["series"], "short": result["short"]["series"]},
        "markers": markers(result),
        "cache_hits": cache.hits - hits_before,
        "state": "ok",
    }


@router.post("/backtest")
def backtest(
    request: BacktestRequest,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
    cache: IndicatorCache = CACHE,
):
    envelope = _envelope(request, store, cache)
    repository.save_run(envelope)
    return envelope


@router.get("/runs")
def runs(repository: RunRepository = REPOSITORY):
    return repository.list_runs()


@router.get("/runs/{run_id}")
def run(
    run_id: str,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
):
    try:
        envelope = repository.get_run(run_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown run {run_id!r}") from exc
    data = envelope.get("data") or {}
    if data.get("source") == "raw_archive":
        try:
            store.load_pinned(PinnedSource(**data))
            envelope["state"] = "ok"
        except SourceUnavailable as exc:
            envelope["state"] = "source_unavailable"
            envelope["state_detail"] = str(exc)
    return envelope


def _side_spec(request: OptimizeRequest):
    return request.strategy.long_side if request.side == "long" else request.strategy.short_side


@router.post("/optimize/plan")
def optimize_plan(
    request: OptimizeRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
):
    """What a start would do: valid cells, skipped cells, bars and the runtime estimate, priced
    at the per-bar cost the runner last observed on this host."""
    frame, _ = _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )
    try:
        plan = expand_grid(_side_spec(request))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "total_cells": len(plan.cells),
        "skipped_cells": len(plan.skipped),
        "skip_reason": plan.skip_reason,
        "estimated_seconds": round(
            estimate_seconds(len(plan.cells), len(frame), runner.ms_per_bar), 3
        ),
        "ms_per_bar": runner.ms_per_bar,
        "bars": len(frame),
    }


@router.post("/optimize", status_code=202)
def optimize(
    request: OptimizeRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
):
    frame, pinned = _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )
    try:
        job_id = runner.start(OptimizerJob(request, frame, pinned))
    except JobBusy as exc:
        raise HTTPException(409, "an optimization is already running") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    status = runner.status(job_id)
    return {
        key: status[key] for key in ("job_id", "total_cells", "skipped_cells", "estimated_seconds")
    }


@router.get("/optimize")
def optimizations(runner: JobRunner = RUNNER):
    return runner.list_jobs("optimization")


@router.get("/optimize/{job_id}")
def optimization(job_id: str, runner: JobRunner = RUNNER):
    try:
        return runner.status(job_id, kind="optimization")
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown optimization {job_id!r}") from exc


@router.post("/optimize/{job_id}/cancel")
def cancel_optimization(job_id: str, runner: JobRunner = RUNNER):
    return _cancel(runner, job_id, "optimization")


def _cancel(runner: JobRunner, job_id: str, kind: str) -> dict:
    if not runner.known(job_id, kind):
        raise HTTPException(404, f"unknown job {job_id!r}")
    return {"cancelled": runner.cancel(job_id)}


# --- walk-forward (spec §6.3) ---------------------------------------------------------------


def _walkforward_frame(request: WalkForwardRequest, store: ArchiveStore):
    return _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )


@router.post("/walkforward/plan")
def walkforward_plan_route(
    request: WalkForwardRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
):
    """What a start would do: windows, cells per window, units, unused tail, bars, estimate."""
    frame, _ = _walkforward_frame(request, store)
    try:
        layout = walkforward_plan(
            request, len(frame), [stamp.isoformat() for stamp in frame["timestamp"]]
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "windows": len(layout.windows),
        "cells_per_window": layout.cells_per_window,
        "total_units": layout.total_units,
        "unused_tail_bars": layout.unused_tail_bars,
        "bars": len(frame),
        "estimated_seconds": round(
            estimate_seconds(layout.total_units, request.in_sample_bars, runner.ms_per_bar), 3
        ),
        "ms_per_bar": runner.ms_per_bar,
    }


@router.post("/walkforward", status_code=202)
def walkforward(
    request: WalkForwardRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
):
    frame, pinned = _walkforward_frame(request, store)
    try:
        job = WalkForwardJob(request, frame, pinned)
        job_id = runner.start(job)
    except JobBusy as exc:
        raise HTTPException(409, "an optimization is already running") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    status = runner.status(job_id)
    return {
        "job_id": job_id,
        "windows": status["windows"]["total"],
        "cells_per_window": status["cells_per_window"],
        "total_units": status["progress"]["total"],
        "estimated_seconds": status["estimated_seconds"],
    }


@router.get("/walkforward")
def walkforwards(runner: JobRunner = RUNNER):
    return runner.list_jobs("walkforward")


@router.get("/walkforward/{job_id}")
def walkforward_status(job_id: str, runner: JobRunner = RUNNER):
    try:
        return runner.status(job_id, kind="walkforward")
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown walk-forward {job_id!r}") from exc


@router.post("/walkforward/{job_id}/cancel")
def cancel_walkforward(job_id: str, runner: JobRunner = RUNNER):
    return _cancel(runner, job_id, "walkforward")


__all__ = [
    "DataReference",
    "get_cache",
    "get_repository",
    "get_runner",
    "get_store",
    "router",
    "warm_in_background",
]
