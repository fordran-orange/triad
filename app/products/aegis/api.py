"""Aegis worker routes (spec §7): pinned raw data, indicators, backtests and persisted runs.

Loopback-only like every route on this product host; nothing here touches money, credentials
or Core state. Exceptions map to: BarsTooLarge → 422 with the range hint, SourceUnavailable →
409, unknown symbol/run → 404.
"""

from __future__ import annotations

import math
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
from products.aegis.indicators import compute
from products.aegis.optimize import (
    JobBusy,
    OptimizeRequest,
    OptimizerRunner,
    engine_rows,
    estimate_seconds,
    expand_grid,
)
from products.aegis.results import canonical_payload, result_hash
from products.aegis.runs import JsonRunRepository, RunRepository
from products.aegis.strategy import IndicatorSpec

router = APIRouter(prefix="/aegis/api")


@lru_cache(maxsize=1)
def get_store() -> ArchiveStore:
    return ArchiveStore()


@lru_cache(maxsize=1)
def get_repository() -> RunRepository:
    return JsonRunRepository()


@lru_cache(maxsize=1)
def get_runner() -> OptimizerRunner:
    return OptimizerRunner(get_repository())


STORE = Depends(get_store)
REPOSITORY = Depends(get_repository)
RUNNER = Depends(get_runner)


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
    series = {}
    for spec in request.indicators:
        try:
            values = compute(spec, frame)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        series[spec.id] = [None if math.isnan(v) else float(v) for v in values.tolist()]
    return {
        "times": [record["time"] for record in to_records(frame)],
        "series": series,
        "data": _provenance(pinned),
    }


def _envelope(request: BacktestRequest, store: ArchiveStore) -> dict:
    started = time.perf_counter()
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
        result = run_backtest(engine_request)
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
        "result": payload,
        "series": {"long": result["long"]["series"], "short": result["short"]["series"]},
        "markers": markers(result),
        "state": "ok",
    }


@router.post("/backtest")
def backtest(
    request: BacktestRequest,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
):
    envelope = _envelope(request, store)
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
def optimize_plan(request: OptimizeRequest, store: ArchiveStore = STORE):
    """What a start would do: valid cells, skipped cells, bars and the runtime estimate."""
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
        "estimated_seconds": round(estimate_seconds(len(plan.cells), len(frame)), 3),
        "bars": len(frame),
    }


@router.post("/optimize", status_code=202)
def optimize(
    request: OptimizeRequest,
    store: ArchiveStore = STORE,
    runner: OptimizerRunner = RUNNER,
):
    frame, pinned = _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )
    try:
        job_id = runner.start(request, frame, pinned)
    except JobBusy as exc:
        raise HTTPException(409, "an optimization is already running") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    status = runner.status(job_id)
    return {
        key: status[key] for key in ("job_id", "total_cells", "skipped_cells", "estimated_seconds")
    }


@router.get("/optimize")
def optimizations(runner: OptimizerRunner = RUNNER):
    return runner.list_jobs()


@router.get("/optimize/{job_id}")
def optimization(job_id: str, runner: OptimizerRunner = RUNNER):
    try:
        return runner.status(job_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown optimization {job_id!r}") from exc


@router.post("/optimize/{job_id}/cancel")
def cancel_optimization(job_id: str, runner: OptimizerRunner = RUNNER):
    return {"cancelled": runner.cancel(job_id)}


__all__ = ["DataReference", "get_repository", "get_runner", "get_store", "router"]
