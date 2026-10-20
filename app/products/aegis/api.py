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
from datetime import date
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from products.aegis import experiments as experiments_module
from products.aegis import studies as studies_module
from products.aegis.backtest import BacktestRequest, DataReference, run_backtest
from products.aegis.compare import compare as compare_runs
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
from products.aegis.library import FOLDERS as LIBRARY_FOLDERS
from products.aegis.library import KINDS as LIBRARY_KINDS
from products.aegis.library import Library, LibraryQuery, Refused
from products.aegis.optimize import OptimizeRequest, OptimizerJob, engine_rows, expand_grid
from products.aegis.pool import default_workers
from products.aegis.results import envelope
from products.aegis.runs import JsonRunRepository, RunRepository
from products.aegis.strategies import BuiltinRefused, StrategyLibrary, StrategyReferenced
from products.aegis.strategy import IndicatorSpec, StrategySpec
from products.aegis.study_rules import render_study_markdown
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
    return envelope(
        result,
        request.strategy,
        request.settings,
        identity,
        int((time.perf_counter() - started) * 1000),
        cache.hits - hits_before,
    )


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


# --- strategy documents (Mission 5 spec §8) ------------------------------------------------


def get_library(repository: RunRepository = REPOSITORY) -> StrategyLibrary:
    return StrategyLibrary(repository)


LIBRARY = Depends(get_library)


def _name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("a strategy needs a name")
    return value


class StrategyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=120)
    spec: StrategySpec

    @field_validator("name")
    @classmethod
    def named(cls, value):
        return _name(value)


class StrategyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    spec: StrategySpec | None = None

    @field_validator("name")
    @classmethod
    def named(cls, value):
        return _name(value)


class StrategyDuplicate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=120)

    @field_validator("name")
    @classmethod
    def named(cls, value):
        return _name(value)


def _no_longer_parses(strategy_id: str, exc: ValidationError) -> HTTPException:
    """A saved document the current StrategySpec refuses (P14 item 2): 422 naming the field."""
    field = ".".join(str(part) for part in exc.errors()[0]["loc"]) or "document"
    return HTTPException(422, f"strategy {strategy_id} no longer parses: {field}")


def _document(library: StrategyLibrary, strategy_id: str):
    try:
        return library.get(strategy_id)
    except KeyError as exc:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}") from exc
    except ValidationError as exc:
        raise _no_longer_parses(strategy_id, exc) from exc


@router.get("/strategies")
def strategies(library: StrategyLibrary = LIBRARY):
    return library.list()


@router.get("/strategies/{strategy_id}")
def strategy_document(strategy_id: str, library: StrategyLibrary = LIBRARY):
    return _document(library, strategy_id).model_dump(mode="json")


@router.post("/strategies", status_code=201)
def create_strategy(request: StrategyCreate, library: StrategyLibrary = LIBRARY):
    return library.create(request.name, request.spec).model_dump(mode="json")


@router.put("/strategies/{strategy_id}")
def update_strategy(strategy_id: str, request: StrategyUpdate, library: StrategyLibrary = LIBRARY):
    try:
        return library.update(strategy_id, request.name, request.spec).model_dump(mode="json")
    except BuiltinRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}") from exc
    except ValidationError as exc:
        raise _no_longer_parses(strategy_id, exc) from exc


@router.post("/strategies/{strategy_id}/duplicate", status_code=201)
def duplicate_strategy(
    strategy_id: str, request: StrategyDuplicate, library: StrategyLibrary = LIBRARY
):
    _document(library, strategy_id)
    return library.duplicate(strategy_id, request.name).model_dump(mode="json")


@router.delete("/strategies/{strategy_id}")
def delete_strategy(strategy_id: str, library: StrategyLibrary = LIBRARY):
    try:
        library.delete(strategy_id)
    except BuiltinRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except StrategyReferenced as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}") from exc
    return {"deleted": strategy_id}


# --- experiments (Mission 6 spec §5.6, §6) --------------------------------------------------


def get_experiment_store(
    repository: RunRepository = REPOSITORY,
) -> experiments_module.ExperimentStore:
    return experiments_module.ExperimentStore(repository)


EXPERIMENTS = Depends(get_experiment_store)


def _experiment(store: experiments_module.ExperimentStore, experiment_id: str):
    try:
        return store.get(experiment_id)
    except KeyError as exc:
        raise HTTPException(404, f"unknown experiment {experiment_id!r}") from exc


def _experiment_bars(request_data: DataReference, store: ArchiveStore):
    return _select(
        store, request_data.symbol, request_data.timeframe, request_data.start, request_data.end
    )


@router.post("/experiments/plan")
def experiment_plan(
    request: experiments_module.ExperimentRequest,
    store: ArchiveStore = STORE,
    library: StrategyLibrary = LIBRARY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    """What a start would do: mode, counts, estimate and the ways back into scope."""
    frame, _ = _experiment_bars(request.data, store)
    document = _document(library, request.strategy_id)
    try:
        from products.aegis.surface import KERNEL_MS_PER_BAR
        from products.aegis.surface import plan as plan_surface

        measured = experiments.last_ms_per_cell_bar()
        planned = plan_surface(
            document.spec,
            request.surface,
            request.budget,
            len(frame),
            measured or KERNEL_MS_PER_BAR,
            default_workers(),
            request.data.timeframe,
            price_source="measured" if measured else "starting_guess",
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return planned.model_dump(mode="json")


def _start_experiment(
    document, store: ArchiveStore, runner: JobRunner, repository: RunRepository
) -> str | None:
    """Start (or resume) the runner job for a document; None when another job is running."""
    frame, pinned = _experiment_bars(document.data, store)
    job = experiments_module.ExperimentJob(
        document, engine_rows(frame, document.data.symbol), pinned, repository
    )
    try:
        return runner.start(job)
    except JobBusy:
        return None


@router.post("/experiments", status_code=202)
def create_experiment(
    request: experiments_module.ExperimentRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    repository: RunRepository = REPOSITORY,
    library: StrategyLibrary = LIBRARY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    frame, _ = _experiment_bars(request.data, store)
    _document(library, request.strategy_id)
    try:
        document = experiments_module.create(
            experiments, library, request, len(frame), default_workers(), request.data.timeframe
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = _start_experiment(document, store, runner, repository)
    return {
        "experiment_id": document.id,
        "job_id": job_id,
        "status": "queued" if job_id is None else "running",
        "plan": document.plan,
    }


@router.get("/experiments")
def list_experiments(experiments: experiments_module.ExperimentStore = EXPERIMENTS):
    return experiments.list()


@router.get("/experiments/{experiment_id}")
def experiment_document(
    experiment_id: str, experiments: experiments_module.ExperimentStore = EXPERIMENTS
):
    return _experiment(experiments, experiment_id).model_dump(mode="json")


@router.post("/experiments/{experiment_id}/pause")
def pause_experiment(
    experiment_id: str,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    if document.status != "running" or not document.job_id:
        raise HTTPException(409, f"experiment {experiment_id} is {document.status}, not running")
    job = runner.job_kind(document.job_id)
    if job is None:
        raise HTTPException(409, f"experiment {experiment_id} has no running job on this worker")
    job.pause_requested = True
    runner.cancel(document.job_id)
    return {"paused": experiment_id}


@router.post("/experiments/{experiment_id}/resume", status_code=202)
def resume_experiment(
    experiment_id: str,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    repository: RunRepository = REPOSITORY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    if document.status not in ("queued", "paused", "failed"):
        raise HTTPException(
            409,
            f"experiment {experiment_id} is {document.status}; "
            "only queued, paused or failed experiments resume",
        )
    job_id = _start_experiment(document, store, runner, repository)
    if job_id is None:
        raise HTTPException(409, "an optimization is already running")
    return {"experiment_id": experiment_id, "job_id": job_id, "status": "running"}


@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(
    experiment_id: str,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    if document.status not in experiments_module.UNFINISHED:
        raise HTTPException(409, f"experiment {experiment_id} is {document.status}, not running")
    live = runner.job_kind(document.job_id) if document.job_id else None
    if live is not None:  # a job on this worker, started or about to start: it finalizes itself
        return {"cancelled": runner.cancel(document.job_id)}
    if document.status == "running":
        raise HTTPException(409, f"experiment {experiment_id} has no running job on this worker")
    # Queued without a job, or paused (its job has stopped): cancelled here, with report 1 from
    # the cells present (review finding 1: a paused experiment could be neither cancelled nor
    # deleted, since every real pause keeps its job_id).
    experiments_module.cancel_idle(experiments, document)
    return {"cancelled": True}


@router.get("/experiments/{experiment_id}/cells")
def experiment_cells(
    experiment_id: str,
    offset: int = 0,
    limit: int = Query(200, ge=1, le=5000),
    sort: str | None = None,
    descending: bool = False,
    valid_only: bool = False,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    _experiment(experiments, experiment_id)
    table = experiments.cells(experiment_id)
    if table is None:
        return {"total": 0, "rows": [], "columns": []}
    import pyarrow.compute as pc

    if valid_only:
        table = table.filter(pc.equal(table.column("valid"), True))
    if sort:
        if sort not in table.column_names:
            raise HTTPException(422, f"unknown sort column {sort!r}")
        table = table.sort_by([(sort, "descending" if descending else "ascending")])
    total = len(table)
    page = table.slice(offset, limit)
    return {"total": total, "rows": page.to_pylist(), "columns": table.column_names}


@router.get("/experiments/{experiment_id}/curves")
def experiment_curves(
    experiment_id: str,
    cells: str = Query("", description="comma-separated cell indices"),
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    _experiment(experiments, experiment_id)
    try:
        wanted = [int(part) for part in cells.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(422, "cells must be integers") from exc
    found = experiments.curves(experiment_id, wanted[:64])
    return {str(cell): curve for cell, curve in found.items()}


@router.post("/experiments/{experiment_id}/cells/{cell}/materialize")
def materialize_cell(
    experiment_id: str,
    cell: int,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    frame, pinned = _experiment_bars(document.data, store)
    try:
        return experiments_module.materialize(
            document,
            experiments,
            repository,
            engine_rows(frame, document.data.symbol),
            pinned,
            cell,
        )
    except KeyError as exc:
        raise HTTPException(404, f"experiment {experiment_id} has no row for cell {cell}") from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: experiments_module.Objective | None = None
    tolerance: float | None = Field(default=None, gt=0, le=1)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["accepted", "rejected", "deferred"]
    notes: str = Field(default="", max_length=4000)


@router.post("/experiments/{experiment_id}/report")
def recompute_experiment_report(
    experiment_id: str,
    request: ReportRequest,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    if document.status in ("queued", "running"):
        raise HTTPException(
            409, f"experiment {experiment_id} is {document.status}; reports need its cells"
        )
    try:
        _, report = experiments_module.recompute_report(
            experiments, document, request.objective, request.tolerance
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return report


@router.get("/experiments/{experiment_id}/report")
def experiment_report(
    experiment_id: str,
    n: int | None = None,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    number = n if n is not None else document.latest_report
    if number is None:
        raise HTTPException(404, f"experiment {experiment_id} has no report yet")
    try:
        return experiments.read_report(experiment_id, number)
    except KeyError as exc:
        raise HTTPException(404, f"experiment {experiment_id} has no report {number}") from exc


@router.get("/experiments/{experiment_id}/report.md")
def experiment_report_markdown(
    experiment_id: str,
    n: int | None = None,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    number = n if n is not None else document.latest_report
    if number is None:
        raise HTTPException(404, f"experiment {experiment_id} has no report yet")
    try:
        text = experiments.read_markdown(experiment_id, number)
    except KeyError as exc:
        raise HTTPException(404, f"experiment {experiment_id} has no report {number}") from exc
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@router.put("/experiments/{experiment_id}/decision")
def decide_experiment(
    experiment_id: str,
    request: DecisionRequest,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    decided = experiments_module.decide(experiments, document, request.verdict, request.notes)
    return decided.model_dump(mode="json")


@router.post("/experiments/{experiment_id}/refine", status_code=201)
def refine_experiment(
    experiment_id: str,
    store: ArchiveStore = STORE,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    document = _experiment(experiments, experiment_id)
    frame, _ = _experiment_bars(document.data, store)
    try:
        child = experiments_module.refine(
            experiments, document, len(frame), default_workers(), document.data.timeframe
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return child.model_dump(mode="json")


def get_study_store(repository: RunRepository = REPOSITORY) -> studies_module.StudyStore:
    return studies_module.StudyStore(repository)


STUDIES = Depends(get_study_store)


@router.delete("/experiments/{experiment_id}")
def delete_experiment(
    experiment_id: str,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
    repository: RunRepository = REPOSITORY,
):
    """Moves the experiment to Recently deleted (Mission 9 spec §6.2) with its existing rules:
    unfinished experiments are cancelled first; a parent with studies cannot go."""
    _experiment(experiments, experiment_id)
    try:
        Library(repository, experiments).delete("experiment", experiment_id)
    except Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": experiment_id}


# --- studies (Mission 8 spec §6) -------------------------------------------------------------


def _study(store: studies_module.StudyStore, study_id: str):
    try:
        return store.get(study_id)
    except KeyError as exc:
        raise HTTPException(404, f"unknown study {study_id!r}") from exc


def _study_range(store: ArchiveStore, symbols: list[str], start, end) -> tuple:
    """The requested range, or the chosen archives' whole span (spec §4)."""
    known = [s for s in store.symbols() if s.symbol in symbols]
    if not known:
        return start, end
    first = start or min(date.fromisoformat(s.first_bar[:10]) for s in known)
    last = end or max(date.fromisoformat(s.last_bar[:10]) for s in known)
    return first, last


def _study_bars(store: ArchiveStore, symbols: list[str], timeframe: str, start, end):
    """Engine rows and provenance per known symbol; an unknown one is left for the plan to name."""
    known = {s.symbol for s in store.symbols()}
    rows: dict[str, list[dict]] = {}
    pinned: dict[str, PinnedSource] = {}
    if start is None or end is None:
        return rows, pinned
    for symbol in symbols:
        if symbol not in known:
            continue
        frame, source = _select(store, symbol, timeframe, start, end)
        rows[symbol] = engine_rows(frame, symbol)
        pinned[symbol] = source
    return rows, pinned


def _timestamps(rows: dict[str, list[dict]]) -> dict[str, list[str]]:
    return {symbol: [r["timestamp"] for r in values] for symbol, values in rows.items()}


@router.post("/studies/plan")
def study_plan(
    request: studies_module.StudyRequest,
    store: ArchiveStore = STORE,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    """What a start would do on each symbol: windows, cells per window, runs and an estimate."""
    experiment = _experiment(experiments, request.experiment_id)
    start, end = _study_range(store, request.symbols, request.start, request.end)
    rows, _ = _study_bars(store, request.symbols, experiment.data.timeframe, start, end)
    try:
        planned = studies_module.plan_study(
            request,
            experiment,
            _timestamps(rows),
            experiments.last_ms_per_cell_bar(),
            default_workers(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return planned.model_dump(mode="json")


@router.post("/studies", status_code=202)
def create_study(
    request: studies_module.StudyRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    repository: RunRepository = REPOSITORY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
    studies: studies_module.StudyStore = STUDIES,
):
    experiment = _experiment(experiments, request.experiment_id)
    start, end = _study_range(store, request.symbols, request.start, request.end)
    rows, pinned = _study_bars(store, request.symbols, experiment.data.timeframe, start, end)
    try:
        document = studies_module.create_study(
            studies,
            experiments,
            request,
            _timestamps(rows),
            default_workers(),
            start,
            end,
            data={symbol: _provenance(source) for symbol, source in pinned.items()},
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = studies_module.StudyJob(document, rows, pinned, repository)
    try:
        job_id = runner.start(job)
    except JobBusy as exc:
        studies.delete(document.id)  # nothing is left queued behind a refusal
        raise HTTPException(
            409, "another job is running; start the study when the runner is free"
        ) from exc
    return {"study_id": document.id, "job_id": job_id, "status": "running", "plan": document.plan}


@router.get("/studies")
def list_studies(experiment_id: str | None = None, studies: studies_module.StudyStore = STUDIES):
    listed = studies.list()
    if experiment_id is not None:
        listed = [s for s in listed if s.get("experiment_id") == experiment_id]
    return listed


@router.get("/studies/{study_id}")
def study_document(study_id: str, studies: studies_module.StudyStore = STUDIES):
    """The persisted study as the runner last saved it, with its progress and estimate."""
    _study(studies, study_id)
    return studies.repository.get_study(study_id)


@router.post("/studies/{study_id}/pause")
def pause_study(
    study_id: str, runner: JobRunner = RUNNER, studies: studies_module.StudyStore = STUDIES
):
    document = _study(studies, study_id)
    if document.status != "running" or not document.job_id:
        raise HTTPException(409, f"study {study_id} is {document.status}, not running")
    job = runner.job_kind(document.job_id)
    if job is None:
        raise HTTPException(409, f"study {study_id} has no running job on this worker")
    job.pause_requested = True
    runner.cancel(document.job_id)
    return {"paused": study_id}


@router.post("/studies/{study_id}/resume", status_code=202)
def resume_study(
    study_id: str,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    repository: RunRepository = REPOSITORY,
    studies: studies_module.StudyStore = STUDIES,
):
    document = _study(studies, study_id)
    if document.status not in ("queued", "paused", "failed"):
        raise HTTPException(
            409,
            f"study {study_id} is {document.status}; only queued, paused or failed studies resume",
        )
    rows, pinned = _study_bars(
        store, document.symbols, document.timeframe, document.start, document.end
    )
    job = studies_module.StudyJob(document, rows, pinned, repository)
    try:
        job_id = runner.start(job)
    except JobBusy as exc:
        raise HTTPException(409, "another job is running") from exc
    return {"study_id": study_id, "job_id": job_id, "status": "running"}


@router.post("/studies/{study_id}/cancel")
def cancel_study(
    study_id: str, runner: JobRunner = RUNNER, studies: studies_module.StudyStore = STUDIES
):
    document = _study(studies, study_id)
    if document.status not in studies_module.UNFINISHED:
        raise HTTPException(409, f"study {study_id} is {document.status}, not running")
    live = runner.job_kind(document.job_id) if document.job_id else None
    if live is not None:  # a job on this worker: it finalizes itself
        return {"cancelled": runner.cancel(document.job_id)}
    if document.status == "running":
        raise HTTPException(409, f"study {study_id} has no running job on this worker")
    studies_module.cancel_idle_study(studies, document)
    return {"cancelled": True}


@router.delete("/studies/{study_id}")
def delete_study(
    study_id: str,
    studies: studies_module.StudyStore = STUDIES,
    repository: RunRepository = REPOSITORY,
):
    """Moves the study to Recently deleted (Mission 9 spec §6.2); unfinished studies are
    cancelled first."""
    _study(studies, study_id)
    try:
        Library(repository).delete("study", study_id)
    except Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": study_id}


@router.put("/studies/{study_id}/decision")
def decide_study(
    study_id: str, request: DecisionRequest, studies: studies_module.StudyStore = STUDIES
):
    document = _study(studies, study_id)
    if document.status in ("queued", "running"):
        # The running job saves its own copy of the document after every window; a decision
        # written now would be overwritten (review finding). Paused studies resume from disk.
        raise HTTPException(
            409,
            f"study {study_id} is {document.status}; decide when it has finished, been cancelled "
            "or been paused",
        )
    decided = studies_module.decide_study(studies, document, request.verdict, request.notes)
    return decided.model_dump(mode="json")


@router.get("/studies/{study_id}/windows/{symbol}/{w}/cells")
def study_window_cells(
    study_id: str,
    symbol: str,
    w: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=5000),
    studies: studies_module.StudyStore = STUDIES,
):
    document = _study(studies, study_id)
    if symbol not in document.symbols:
        raise HTTPException(404, f"study {study_id} has no symbol {symbol!r}")
    table = studies.cells(study_id, symbol, w)
    if table is None:
        raise HTTPException(404, f"study {study_id} has no window {symbol}/{w}")
    page = table.slice(offset, limit)
    return {"total": len(table), "rows": page.to_pylist(), "columns": table.column_names}


@router.get("/studies/{study_id}/report.md")
def study_report_markdown(study_id: str, studies: studies_module.StudyStore = STUDIES):
    document = _study(studies, study_id)
    if document.report is None:
        raise HTTPException(404, f"study {study_id} has no report yet")
    return PlainTextResponse(
        render_study_markdown(document.report), media_type="text/markdown; charset=utf-8"
    )


# --- the Results library (Mission 9 spec §4) --------------------------------------------------------


def get_library(
    repository: RunRepository = REPOSITORY,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
) -> Library:
    return Library(repository, experiments)


LIBRARY_INDEX = Depends(get_library)
KINDS_QUERY = Query(default=[])


@router.get("/library")
def library_index(
    kind: list[str] = KINDS_QUERY,
    symbol: str | None = None,
    timeframe: str | None = None,
    strategy: str | None = None,
    starred: bool | None = None,
    decision: str | None = None,
    q: str | None = None,
    sort: str = "created",
    offset: int = 0,
    limit: int = 50,
    deleted: bool = False,
    library: Library = LIBRARY_INDEX,
):
    """Every saved result as one entry; headlines are computed once and cached (plan P1, P2)."""
    try:
        query = LibraryQuery(
            kinds=kind,
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy,
            starred=starred,
            decision=decision,
            q=q,
            sort=sort,
            offset=offset,
            limit=limit,
            deleted=deleted,
        )
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"]) from exc
    result = library.query(query)
    return {**result, "entries": [e.model_dump(mode="json") for e in result["entries"]]}


class AnnotationRequest(BaseModel):
    """Only the fields sent change; a field left out keeps its value (a row's star and the view's
    label editor each send their own)."""

    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    starred: bool | None = None


class LibraryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["backtest", "optimization", "walkforward", "experiment", "study"]
    id: str


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[LibraryItem] | None = None


def _library_kind(kind: str) -> str:
    if kind not in LIBRARY_KINDS:
        raise HTTPException(404, f"unknown kind {kind!r}")
    return kind


@router.put("/library/{kind}/{item_id}/annotation")
def annotate_library_item(
    kind: str, item_id: str, request: AnnotationRequest, library: Library = LIBRARY_INDEX
):
    _library_kind(kind)
    try:
        library.repository.read_document(LIBRARY_FOLDERS[kind], item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown {kind} {item_id!r}") from exc
    note = library.annotations.set(kind, item_id, request.label, request.notes, request.starred)
    return {"kind": kind, "id": item_id, **note}


@router.delete("/library/{kind}/{item_id}")
def delete_library_item(kind: str, item_id: str, library: Library = LIBRARY_INDEX):
    _library_kind(kind)
    try:
        library.delete(kind, item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown {kind} {item_id!r}") from exc
    except Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": item_id}


@router.post("/library/{kind}/{item_id}/restore")
def restore_library_item(kind: str, item_id: str, library: Library = LIBRARY_INDEX):
    _library_kind(kind)
    try:
        library.restore(kind, item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"{kind} {item_id!r} is not in Recently deleted") from exc
    except Refused as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"restored": item_id}


@router.get("/library/compare")
def compare_library_backtests(a: str, b: str, library: Library = LIBRARY_INDEX):
    """Two saved backtests side by side (spec §7): computed here, sent back compact; reads only."""
    if a == b:
        raise HTTPException(422, "compare two different runs")
    runs = {}
    for key, run_id in (("a", a), ("b", b)):
        try:
            runs[key] = library.repository.get_run(run_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, f"unknown run {run_id!r}") from exc
    result = compare_runs(runs["a"], runs["b"])
    for key, run_id in (("a", a), ("b", b)):
        result["identity"][key]["label"] = library.annotations.get("backtest", run_id).get(
            "label", ""
        )
    return result


@router.post("/library/trash/empty")
def empty_library_trash(request: EmptyRequest, library: Library = LIBRARY_INDEX):
    """Erase items from Recently deleted for good: the one destructive act, always explicit."""
    items = None if request.items is None else [(i.kind, i.id) for i in request.items]
    return {"erased": library.empty(items)}


__all__ = [
    "DataReference",
    "get_cache",
    "get_repository",
    "get_runner",
    "get_store",
    "router",
    "warm_in_background",
]
