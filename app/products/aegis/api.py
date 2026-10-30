"""Aegis worker routes (spec §7): pinned raw data, indicators, backtests and persisted runs.

Loopback-only like every route on this product host; nothing here touches money, credentials
or Core state. Exceptions map to: BarsTooLarge → 422 with the range hint, a pinned archive that
drifted → `state: source_unavailable` on the reloaded run (200), JobBusy → 409, unknown
symbol/run/job → 404.
"""

from __future__ import annotations

import logging
import math
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from products.aegis import display, phrases
from products.aegis import experiments as experiments_module
from products.aegis import optimize as optimize_module
from products.aegis import studies as studies_module
from products.aegis.ai_reading import AIUnread, available_providers, read_with_ai
from products.aegis.backtest import (
    MIN_BARS,
    BacktestRequest,
    DataReference,
    _data_key,
    prepare_archive_frame,
    run_backtest,
    run_prepared,
)
from products.aegis.compare import compare as compare_runs
from products.aegis.core_client import CoreReasoning
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
from products.aegis.lab import identity
from products.aegis.lab import sources as lab_sources
from products.aegis.lab import store as lab_store
from products.aegis.lab.cache import LabCache, cache_bytes_from_env
from products.aegis.lab.importance import METHOD, RUNNING_OPTIMIZATION, STAGES, importance_key
from products.aegis.lab.index import FrameIndex
from products.aegis.lab.policy import DEFAULT_TOLERANCE, LOW_DISK_GB, PAGE_LIMIT, TOP_LIMIT
from products.aegis.lab.query import LabFilter, TrialFrame
from products.aegis.lab.robustness import DEFAULT_TOLERANCE_LABEL, top_axes
from products.aegis.lab.tasks import LabTasks, TaskStatus, task_of
from products.aegis.learned import LearnedPhrases
from products.aegis.library import FOLDERS as LIBRARY_FOLDERS
from products.aegis.library import KINDS as LIBRARY_KINDS
from products.aegis.library import Library, LibraryQuery, Refused
from products.aegis.optimize import (
    SERIAL_MAX_CELLS,
    OptimizeRequest,
    OptimizerJob,
    engine_rows,
    expand_grid,
    plan_seconds,
)
from products.aegis.pool import fitted_workers
from products.aegis.preferences import Preferences
from products.aegis.results import envelope
from products.aegis.runs import (
    ExperimentReferenced,
    JsonRunRepository,
    RunRepository,
    aegis_data_root,
)
from products.aegis.strategies import (
    BuiltinRefused,
    StrategyLibrary,
    StrategyReferenced,
    check_canvas,
)
from products.aegis.strategy import IndicatorSpec, StrategySpec
from products.aegis.study_rules import render_study_markdown
from products.aegis.surface import held_bars
from products.aegis.unsaved import UnsavedRuns
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


@lru_cache(maxsize=1)
def get_unsaved() -> UnsavedRuns:
    """Backtests not saved in "kept" mode; a worker restart forgets them (Mission 10 §8)."""
    return UnsavedRuns()


STORE = Depends(get_store)
REPOSITORY = Depends(get_repository)
RUNNER = Depends(get_runner)
CACHE = Depends(get_cache)
UNSAVED = Depends(get_unsaved)


def get_preferences(repository: RunRepository = REPOSITORY) -> Preferences:
    """The worker's preferences live beside its saved runs."""
    return Preferences(getattr(repository, "root", None))


PREFERENCES = Depends(get_preferences)


def get_learned(repository: RunRepository = REPOSITORY) -> LearnedPhrases:
    """Mission 14: learned phrases and accepted examples, beside the saved runs."""
    root = getattr(repository, "root", None)
    return LearnedPhrases(Path(root) if root is not None else aegis_data_root())


def get_core_reasoning() -> CoreReasoning:
    """Mission 14: Core's read-only reasoning route, with this product's own key."""
    from trading_core.settings import Settings

    return CoreReasoning(key=Settings().aegis_product_key.get_secret_value())


LEARNED = Depends(get_learned)
CORE = Depends(get_core_reasoning)


def get_experiment_store(
    repository: RunRepository = REPOSITORY,
) -> experiments_module.ExperimentStore:
    return experiments_module.ExperimentStore(repository)


EXPERIMENTS = Depends(get_experiment_store)


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


def _shown(store, symbol, timeframe, start, end, frame, max_bars, from_ms, to_ms, at_least=None):
    """What a window of the selection is drawn as (Mission 10 §7)."""
    if at_least is not None:
        _timeframe(at_least)
    return display.choose(
        frame,
        timeframe,
        max_bars,
        from_ms,
        to_ms,
        lambda coarser: _select(store, symbol, coarser, start, end)[0],
        at_least,
    )


@router.get("/data/bars")
def bars(
    symbol: str,
    timeframe: str,
    start: str = Query(..., description="inclusive YYYY-MM-DD, America/New_York"),
    end: str = Query(..., description="inclusive YYYY-MM-DD, America/New_York"),
    max_bars: int | None = Query(None, ge=1, description="draw at most this many candles"),
    from_ms: int | None = Query(None, description="the window drawn; default the selection"),
    to_ms: int | None = Query(None),
    at_least: str | None = Query(None, description="candles at least this coarse"),
    store: ArchiveStore = STORE,
):
    frame, pinned = _select(store, symbol, timeframe, start, end)
    shown = _shown(store, symbol, timeframe, start, end, frame, max_bars, from_ms, to_ms, at_least)
    candles = to_records(shown.frame.iloc[shown.first : shown.last])
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timezone": "America/New_York",
        "bars": candles,
        "count": len(frame),  # the native bars of the whole selection
        "shown": len(candles),
        "display_timeframe": shown.timeframe,
        "window": shown.window,
        "data": _provenance(pinned),
    }


class IndicatorsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    timeframe: str
    start: str
    end: str
    indicators: list[IndicatorSpec] = Field(max_length=32)
    # Mission 10: the same window and bound as GET /data/bars, so the series follow its candles
    max_bars: int | None = Field(default=None, ge=1)
    from_ms: int | None = None
    to_ms: int | None = None
    at_least: str | None = None


@router.post("/indicators")
def indicators(request: IndicatorsRequest, store: ArchiveStore = STORE):
    frame, pinned = _select(store, request.symbol, request.timeframe, request.start, request.end)
    shown = _shown(
        store,
        request.symbol,
        request.timeframe,
        request.start,
        request.end,
        frame,
        request.max_bars,
        request.from_ms,
        request.to_ms,
        request.at_least,
    )
    native_ms = display.times_ms(frame)
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
            # computed on the native bars of the whole selection: the warm-up is unchanged
            values = produced[column].to_numpy(dtype="float64")
            if shown.starts_ms is not None:
                sampled = display.sample_at_buckets(
                    native_ms, values, shown.starts_ms, int(native_ms[-1])
                )
                series[column] = sampled[shown.first : shown.last]
            else:
                series[column] = [
                    None if math.isnan(v) else v for v in values[shown.first : shown.last].tolist()
                ]
    return {
        "times": display.times_ms(shown.frame.iloc[shown.first : shown.last]).tolist(),
        "series": series,
        "outputs": outputs,
        "pane": panes,
        "display_timeframe": shown.timeframe,
        "window": shown.window,
        "data": _provenance(pinned),
    }


def _envelope(request: BacktestRequest, store: ArchiveStore, cache: IndicatorCache) -> dict:
    started = time.perf_counter()
    hits_before = cache.hits
    if request.data is not None:
        frame, pinned = _select(
            store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
        )
        identity = _provenance(pinned)
    else:
        identity = {"source": "supplied_bars", "bar_count": len(request.bars)}
    try:
        if request.data is not None:  # Mission 10: the archive frame, never a dict per bar
            prepared = prepare_archive_frame(frame, request.data.symbol)
            result = run_prepared(request, prepared, _data_key(prepared), cache)
        else:
            result = run_backtest(request, cache=cache)
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


class BacktestBody(BacktestRequest):
    """POST /backtest: the engine's request and, for this request only, whether to save the
    run whatever the save preference says (Mission 10 §8)."""

    save: bool | None = None


class PreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    save_runs: Literal["every", "kept"] | None = None
    reader_provider: Literal["CLAUDE", "CODEX", "GROK"] | None = None  # Mission 14


@router.get("/preferences")
def preferences(prefs: Preferences = PREFERENCES):
    return prefs.get()


@router.put("/preferences")
def set_preferences(body: PreferencesBody, prefs: Preferences = PREFERENCES):
    return prefs.set(body.save_runs, body.reader_provider)


@router.post("/backtest")
def backtest(
    request: BacktestBody,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
    cache: IndicatorCache = CACHE,
    unsaved: UnsavedRuns = UNSAVED,
    prefs: Preferences = PREFERENCES,
):
    envelope = _envelope(request, store, cache)
    save = request.save if request.save is not None else prefs.get()["save_runs"] == "every"
    if save:
        repository.save_run(envelope)
    else:
        unsaved.add(envelope)  # "kept" mode: held until kept, or forgotten on restart
    return {**envelope, "saved": save}


@router.get("/runs")
def runs(repository: RunRepository = REPOSITORY, unsaved: UnsavedRuns = UNSAVED):
    listed = unsaved.list() + repository.list_runs()
    return sorted(listed, key=lambda item: item.get("created_at", ""), reverse=True)


@router.post("/runs/{run_id}/keep")
def keep_run(
    run_id: str,
    repository: RunRepository = REPOSITORY,
    unsaved: UnsavedRuns = UNSAVED,
):
    """Save a run held unsaved; a run already saved is fine; a forgotten one is 404."""
    try:
        envelope = unsaved.pop(run_id)
    except KeyError:
        try:
            repository.get_run(run_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                404,
                f"run {run_id!r} is not held: unsaved runs are forgotten after newer ones and on "
                "restart",
            ) from exc
        return {"saved": run_id}
    try:
        repository.save_run(envelope)
    except Exception:
        unsaved.add(envelope)  # a failed write never loses the run
        raise
    return {"saved": run_id}


@router.get("/runs/{run_id}")
def run(
    run_id: str,
    store: ArchiveStore = STORE,
    repository: RunRepository = REPOSITORY,
    unsaved: UnsavedRuns = UNSAVED,
):
    try:
        envelope, saved = repository.get_run(run_id), True
    except (KeyError, ValueError) as exc:
        try:
            envelope, saved = unsaved.get(run_id), False
        except KeyError:
            raise HTTPException(404, f"unknown run {run_id!r}") from exc
    envelope["saved"] = saved
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


def _grid_seconds(cells: int, bars: int, runner: JobRunner, experiments) -> tuple[float, int]:
    """A grid's estimate and the workers it runs on: serial up to SERIAL_MAX_CELLS cells, else
    the pool at the cost per cell-bar the last experiment measured (the limits change)."""
    if cells <= SERIAL_MAX_CELLS:
        return plan_seconds(cells, bars, runner.ms_per_bar, None, 1), 1
    workers = fitted_workers(bars)  # Mission 10: what free memory holds, as the job will run
    rate = _pool_rate(runner, experiments)
    return plan_seconds(cells, bars, runner.ms_per_bar, rate, workers), workers


def _pool_rate(runner: JobRunner, experiments) -> float | None:
    """The pool's measured cost per cell-bar: the latest pooled optimization's, else the last
    experiment's (the limits review: the estimate learns from pooled optimizations too)."""
    return optimize_module.pool_rate(
        runner.list_jobs("optimization"), experiments.last_ms_per_cell_bar()
    )


@router.post("/optimize/plan")
def optimize_plan(
    request: OptimizeRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    """What a start would do: valid cells, skipped cells, bars and the runtime estimate, priced
    at the per-bar cost the runner last observed on this host (on the pool's measured cost,
    across its workers, for a grid of more than SERIAL_MAX_CELLS cells)."""
    frame, _ = _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )
    try:
        plan = expand_grid(_side_spec(request))
        seconds, workers = _grid_seconds(len(plan.cells), len(frame), runner, experiments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "total_cells": len(plan.cells),
        "skipped_cells": len(plan.skipped),
        "skip_reason": plan.skip_reason,
        "estimated_seconds": round(seconds, 3),
        "ms_per_bar": runner.ms_per_bar,
        "bars": len(frame),
        "pooled": len(plan.cells) > SERIAL_MAX_CELLS,
        "workers": workers,
    }


@router.post("/optimize", status_code=202)
def optimize(
    request: OptimizeRequest,
    store: ArchiveStore = STORE,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    frame, pinned = _select(
        store, request.data.symbol, request.data.timeframe, request.data.start, request.data.end
    )
    try:
        kind = OptimizerJob(
            request,
            frame,
            pinned,
            ms_per_bar=runner.ms_per_bar,
            pool_rate=_pool_rate(runner, experiments),
        )
        job_id = runner.start(kind)
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


def _optimization(runner: JobRunner, job_id: str) -> dict:
    try:
        return runner.status(job_id, kind="optimization")
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown optimization {job_id!r}") from exc


@router.get("/optimize/{job_id}")
def optimization(job_id: str, runner: JobRunner = RUNNER):
    """The job as it stands. A job of more than CELLS_SENT cells sends its best by the objective
    (the page polls this every second); every cell pages through /cells, and the saved document
    keeps them all."""
    return optimize_module.page_view(_optimization(runner, job_id))


@router.get("/optimize/{job_id}/cells")
def optimization_cells(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=5000),
    runner: JobRunner = RUNNER,
):
    """Every evaluated cell, best first by the job's objective, a page at a time."""
    status = _optimization(runner, job_id)
    cells = status.get("cells") or []
    ordered = optimize_module.best_cells(cells, status.get("objective", "net_pnl"), len(cells))
    return {"total": len(ordered), "rows": ordered[offset : offset + limit]}


def _grid_values(status: dict) -> dict:
    spec = StrategySpec.model_validate(status["strategy"])
    side = getattr(spec, "long_side" if status.get("side") == "long" else "short_side")
    return optimize_module.grid_values(side)


@router.get("/optimize/{job_id}/matrix")
def optimization_matrix(
    job_id: str, rows: str, cols: str, metric: str | None = None, runner: JobRunner = RUNNER
):
    """Any two of the job's parameters as a matrix; each square is the best of the rest. With
    `metric`, that metric only (the page asks for the one it shows)."""
    status = _optimization(runner, job_id)
    if metric is not None and metric not in optimize_module.OBJECTIVES:
        raise HTTPException(422, f"unknown metric {metric!r}")
    metrics = (metric,) if metric else optimize_module.OBJECTIVES
    try:
        values = _grid_values(status)
        squares = len(values.get(rows, [])) * len(values.get(cols, []))
        if squares > optimize_module.MAX_SQUARES:
            raise ValueError(
                f"{squares} squares is more than a matrix draws ({optimize_module.MAX_SQUARES}); "
                "choose other parameters or a coarser step"
            )
        return optimize_module.axis_matrix(
            status.get("cells") or [], rows, cols, values, metrics=metrics
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/optimize/{job_id}/square")
def optimization_square(
    job_id: str,
    rows: str,
    cols: str,
    row: float,
    col: float,
    metric: str | None = None,
    runner: JobRunner = RUNNER,
):
    """One square's best cell, for a click on a cell the page was not sent."""
    status = _optimization(runner, job_id)
    metric = metric or status.get("objective", "net_pnl")
    if metric not in optimize_module.OBJECTIVES:
        raise HTTPException(422, f"unknown metric {metric!r}")
    cell = optimize_module.square_cell(status.get("cells") or [], rows, cols, row, col, metric)
    if cell is None:
        raise HTTPException(404, "no cell with a value in that square")
    return cell


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
    canvas: dict | None = None  # Mission 13: the builder's blocks and wires

    @field_validator("canvas")
    @classmethod
    def bounded_canvas(cls, value):
        return check_canvas(value)

    @field_validator("name")
    @classmethod
    def named(cls, value):
        return _name(value)


class StrategyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=120)
    spec: StrategySpec | None = None
    canvas: dict | None = None  # Mission 13: kept as saved when absent

    @field_validator("canvas")
    @classmethod
    def bounded_canvas(cls, value):
        return check_canvas(value)

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
    return library.create(request.name, request.spec, canvas=request.canvas).model_dump(mode="json")


@router.put("/strategies/{strategy_id}")
def update_strategy(strategy_id: str, request: StrategyUpdate, library: StrategyLibrary = LIBRARY):
    try:
        return library.update(strategy_id, request.name, request.spec, request.canvas).model_dump(
            mode="json"
        )
    except BuiltinRefused as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, f"unknown strategy {strategy_id!r}") from exc
    except ValidationError as exc:
        raise _no_longer_parses(strategy_id, exc) from exc


@router.post("/strategies/read")
def read_strategy_text(
    request: phrases.ReadRequest,
    prefs: Preferences = PREFERENCES,
    learned: LearnedPhrases = LEARNED,
    core: CoreReasoning = CORE,
):
    """Mission 13: the sides a sentence describes, read deterministically, learned phrases first
    (Mission 14). Text it cannot read goes to the AI through Core (the chosen provider); when that
    cannot read it either, 422 with the reader's message and unread spans and, under "ai", why the
    AI could not. Nothing is saved."""
    try:
        return phrases.read(request.text, request.strategy, learned=learned.pairs()).model_dump(
            mode="json"
        )
    except phrases.Unread as refusal:
        if not request.ai:
            none = {
                "reason": "none_available",
                "message": "No AI provider is available now, so only the phrase reader read this",
                "provider": None,
            }
            raise HTTPException(
                422, {"message": str(refusal), "unread": refusal.spans, "ai": none}
            ) from refusal
        provider = request.provider or prefs.get()["reader_provider"]
        try:
            reading = read_with_ai(
                request.text, request.strategy, provider, core, learned.examples()
            )
        except AIUnread as exc:
            raise HTTPException(
                422, {"message": str(refusal), "unread": refusal.spans, "ai": exc.detail()}
            ) from exc
        return reading.model_dump(mode="json")


class LearnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2_000)
    rewrite: str = Field(min_length=1, max_length=4_000)
    substitutions: list[dict] = Field(default_factory=list, max_length=100)
    provider: str | None = None
    model: str | None = None
    run_id: str | None = None
    strategy: StrategySpec


@router.post("/phrases/learn")
def learn_phrases(body: LearnBody, learned: LearnedPhrases = LEARNED):
    """Mission 14: an applied AI reading; keeps the example and the substitutions that pass."""
    provenance = {"provider": body.provider, "model": body.model, "run_id": body.run_id}
    kept = learned.learn(body.text, body.rewrite, body.substitutions, provenance, body.strategy)
    return {"kept": kept}


@router.get("/phrases/providers")
def reader_providers(core: CoreReasoning = CORE):
    """Mission 14: the providers the builder may offer, each only while Core can route a reading
    to it (operator, 2026-10-27)."""
    return available_providers(core)


@router.get("/phrases/learned")
def learned_phrases(learned: LearnedPhrases = LEARNED):
    return learned.list()


@router.delete("/phrases/learned/{identifier}")
def remove_learned_phrase(identifier: str, learned: LearnedPhrases = LEARNED):
    try:
        learned.remove(identifier)
    except KeyError as exc:
        raise HTTPException(404, f"unknown learned phrase {identifier!r}") from exc
    return {"removed": identifier}


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
            fitted_workers(held_bars(len(frame), request.blocks)),  # as the job will fit them
            request.data.timeframe,
            price_source="measured" if measured else "starting_guess",
            blocks=request.blocks,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return planned.model_dump(mode="json")


def _pinned_bars(
    document: experiments_module.ExperimentDocument, store: ArchiveStore, *, verb: str
) -> tuple[pd.DataFrame, PinnedSource]:
    """The bars a document's trials run on. A layout-2 document reloads exactly the archive it
    was pinned to, so a resumed or materialized trial runs on the bytes its rows were computed
    from; provenance it never recorded, or an archive whose bytes moved, is a 409 naming why,
    never a silent fall forward. A legacy document re-selects its data reference as before."""
    if document.cells_layout == 2:
        try:
            pinned = PinnedSource.model_validate(document.data_pinned)
        except ValidationError as exc:
            raise HTTPException(409, f"{verb} refused: data provenance not recorded") from exc
        try:
            return store.load_pinned(pinned), pinned
        except SourceUnavailable as exc:
            raise HTTPException(409, f"{verb} refused: data drift: {exc}") from exc
    return _experiment_bars(document.data, store)


def _start_experiment(
    document,
    store: ArchiveStore,
    runner: JobRunner,
    repository: RunRepository,
    *,
    frame: pd.DataFrame | None = None,
    pinned: PinnedSource | None = None,
) -> str | None:
    """Start (or resume) the runner job for a document; None when another job is running. The
    bars are re-selected from the document's data reference unless the caller loaded them."""
    if frame is None:
        frame, pinned = _experiment_bars(document.data, store)
    try:
        job = experiments_module.ExperimentJob(document, frame, pinned, repository)
    except ValueError as exc:  # not even one pool worker fits in free memory now
        raise HTTPException(422, str(exc)) from exc
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
    frame, pinned = _experiment_bars(request.data, store)
    _document(library, request.strategy_id)
    try:
        document = experiments_module.create(
            experiments,
            library,
            request,
            len(frame),
            fitted_workers(held_bars(len(frame), request.blocks)),  # as the job will fit them
            request.data.timeframe,
            pinned=pinned,
            engine_build=identity.engine_build(),
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
    frame, pinned = _pinned_bars(document, store, verb="resume")
    if document.cells_layout == 2:  # the engine its trials ran on must be this worker's
        recorded = str((document.versions or {}).get("engine_build"))
        worker = identity.engine_build()
        if recorded != worker:
            raise HTTPException(
                409,
                f"resume refused: engine build drift (document {recorded[:12]}, "
                f"worker {worker[:12]})",
            )
    job_id = _start_experiment(document, store, runner, repository, frame=frame, pinned=pinned)
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
    frame, pinned = _pinned_bars(document, store, verb="materialize")
    try:
        return experiments_module.materialize(
            document,
            experiments,
            repository,
            frame,
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
    frame, pinned = _experiment_bars(document.data, store)
    try:
        child = experiments_module.refine(
            experiments,
            document,
            len(frame),
            fitted_workers(len(frame)),
            document.data.timeframe,
            pinned=pinned,
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
    unfinished experiments are cancelled first; a parent with studies or live child experiments
    cannot go."""
    _experiment(experiments, experiment_id)
    try:
        Library(repository, experiments).delete("experiment", experiment_id)
    except (Refused, ExperimentReferenced) as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"deleted": experiment_id}


# --- the Optimization Lab (Lab v2 spec §6.4, §7, §9.2, §9.3) --------------------------------
#
# Every Lab route is a sync `def`: the experiment's read lock is re-entrant per thread, so on the
# event loop's one thread every request would count as re-entrant and a wait would block the
# loop. An `exp:` route reads the document and the files under that lock and never the runner;
# an `opt:` route reads `runner.status` and holds no Lab lock.


@lru_cache(maxsize=1)
def get_lab_cache() -> LabCache:
    """The Lab's column cache, one per worker (§9.2): `AEGIS_LAB_CACHE_MB` megabytes, else
    `LAB_CACHE_BYTES`."""
    return LabCache(cache_bytes_from_env())


LAB_CACHE = Depends(get_lab_cache)


def _sharing_cpu(runner: JobRunner) -> bool:
    """A Lab task's `sharing_cpu`: an experiment job is running on this worker, from one brief
    hold of the runner's lock (`running_kind`, no snapshot built)."""
    return runner.running_kind() == "experiment"


@lru_cache(maxsize=1)
def get_lab_tasks() -> LabTasks:
    """The Lab's tasks, one executor per worker (Phase 3 Task 3): one task at a time on its own
    thread beside the job, shut down by the lifespan on exit."""
    return LabTasks(sharing_cpu=lambda: _sharing_cpu(get_runner()))


LAB_TASKS = Depends(get_lab_tasks)


def _non_finite_named(value):
    """`value` with every NaN or infinite float replaced by its JSON literal's name."""
    if isinstance(value, float) and not math.isfinite(value):
        return "NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {key: _non_finite_named(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_non_finite_named(item) for item in value]
    return value


class QueryRequest(BaseModel):
    """One view of one filter. Only `filter` and `view` are required; a view checks its own
    arguments (a matrix needs rows, cols and metric; a square's trials its two values). `seed`
    and `rerun` are the importance task's: its resamples' seed, in the task's key and every
    answer, and the user's own "run again" after a task failed or was cancelled, which a poll
    never does by itself. `trial` is a trial id, `<src>#<n>`: the `neighbourhood` view's trial and
    the `robustness` view's candidate (without one, that view answers the rankings). `objectives`
    are the `pareto` view's two or three metric names, each in the filter's scope. `parallel_mode`
    is the `parallel` view's: its bundles by default, or `sample`'s exact lines, seeded by `seed`
    (decision 8: `mode` is the matrix's)."""

    model_config = ConfigDict(extra="forbid")
    filter: LabFilter
    view: Literal[
        "counts",
        "matrix",
        "page",
        "top",
        "marginals",
        "parallel",
        "square_trials",
        "importance",
        "interactions",
        "triples",
        "neighbourhood",
        "robustness",
        "pareto",
        "convergence",
    ]
    filter_hash: str | None = None
    rows: str | None = None
    cols: str | None = None
    metric: str | None = None
    mode: Literal["exact", "aggregate"] = "exact"
    stat: Literal["best", "median", "mean", "worst"] = "best"
    fixed: dict[str, float] | None = None
    sort: str | None = None
    descending: bool = False
    offset: int = Field(0, ge=0)
    limit: int = Field(PAGE_LIMIT, ge=1, le=PAGE_LIMIT)
    k: int = Field(200, ge=1, le=TOP_LIMIT)
    paths: list[str] | None = None
    axes: list[str] | None = None
    row_value: float | None = None
    col_value: float | None = None
    seed: int = Field(1, ge=0)  # numpy's seed sequences refuse a negative entropy
    rerun: bool = False
    trial: str | None = None
    objectives: list[str] | None = None
    parallel_mode: Literal["bundles", "sample"] = "bundles"

    @model_validator(mode="before")
    @classmethod
    def non_finite_named(cls, value):
        """Starlette's JSON parser accepts the NaN and Infinity literals, and FastAPI's 422 echoes
        the input, which the response encoder refuses (a 500): each arrives as its literal's
        name, so a filter bound still refuses it (`finite_number`) and the refusal renders."""
        return _non_finite_named(value)


def _lab_source(src: str) -> lab_sources.SourceRef:
    try:
        return lab_sources.parse_source(src)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def _lab_refused(exc: Exception) -> HTTPException:
    """A view's or a column list's refusal as a 422 naming it (a KeyError's message, not its
    repr)."""
    return HTTPException(422, str(exc.args[0]) if exc.args else str(exc))


@dataclass
class _TaskPin:
    """The snapshot `_lab_experiment` pinned for a Lab task and its registry hold, which stays
    `_lab_experiment`'s to release until the caller takes it for `LabTasks.request`."""

    snapshot: lab_store.Snapshot | None = None
    hold: int | None = None

    def take(self) -> int | None:
        hold, self.hold = self.hold, None
        return hold


@contextmanager
def _lab_experiment(
    experiment_id: str,
    experiments: experiments_module.ExperimentStore,
    cache: LabCache,
    columns_of,
    trial_no: int | None = None,
    pin: _TaskPin | None = None,
):
    """One `exp:` request's document, metadata and frame: the document and the files read under
    the experiment's read lock, the latest snapshot registered for the request's life and
    released once its answer is built. With `trial_no`, the frame holds that trial's rows only.
    With `pin`, the frame is read at a snapshot pinned for a Lab task, so the answer's `snapshot`
    is the one its task was requested at. The caller's body runs outside the lock, where a Lab
    task must be requested: a status of a live task reads the runner, whose lock the job holds
    while it takes this write lock (`finalize` compacts). A snapshot whose files are gone is a
    409, never a 500."""
    handle = None
    try:
        try:
            with lab_store.LOCKS.read(experiment_id):
                document = _experiment(experiments, experiment_id)
                meta = lab_sources.cached_meta(document, cache)
                try:
                    columns = columns_of(meta)
                except (KeyError, ValueError) as exc:
                    raise _lab_refused(exc) from exc
                if pin is not None:
                    pin.snapshot, pin.hold = lab_sources.pin_experiment(document, experiments)
                frame, handle = lab_sources.open_experiment(
                    document,
                    experiments,
                    cache,
                    columns,
                    trial_no=trial_no,
                    snapshot=None if pin is None else pin.snapshot,
                )
        except lab_store.SnapshotExpired as exc:
            raise HTTPException(409, "snapshot expired") from exc
        yield document, meta, frame
    finally:
        if handle is not None:
            lab_store.REGISTRY.release(handle)
        if pin is not None and pin.hold is not None:
            lab_store.REGISTRY.release(pin.take())


def _lab_optimization(
    runner: JobRunner, job_id: str, view: str, request
) -> tuple[dict, TrialFrame]:
    """An `opt:` request's job status (one `runner.status` call) and its frame in the view's
    columns. An optimization has one side: a query of another scope is refused."""
    status = _optimization(runner, job_id)
    if request is not None and request.filter.scope != status.get("side"):
        raise HTTPException(422, "an optimizer source has one side")
    frame = lab_sources.opt_frame(status)
    try:
        columns = lab_sources.COLUMNS_FOR(
            view, request, frame.parameters, frame.objective, side=status["side"]
        )
    except (KeyError, ValueError) as exc:
        raise _lab_refused(exc) from exc
    return status, lab_sources.project(frame, columns)


def _lab_answer(
    frame: TrialFrame,
    request: QueryRequest,
    unique: int | None,
    *,
    cache: LabCache,
    source_identity: tuple,
    index: FrameIndex | None = None,
) -> dict:
    """One query's answer over the snapshot's index (an experiment's; None for an optimization),
    an aggregate matrix cached under its source's identity."""
    try:
        return lab_sources.run_query(
            frame,
            request,
            unique=unique,
            index=index,
            cache=cache,
            source_identity=source_identity,
        )
    except (KeyError, ValueError) as exc:
        raise _lab_refused(exc) from exc


def _lab_task_answer(
    frame: TrialFrame,
    request: QueryRequest,
    tasks: LabTasks,
    key: tuple,
    placed: TaskStatus,
    unique: int | None = None,
) -> dict:
    """A task view's answer (Ruling P14): the key's newest `done` result, of whichever snapshot
    (`task_query` labels it `snapshot X · current Y`), else the computing task's delivered stage,
    a cancelled or failed task's included, else null. The line names the computing task, never
    the waiter behind it (`placed`, what the request placed, only if the key's tasks were
    evicted meanwhile)."""
    task = tasks.computing(key) or placed
    done = tasks.result(key)
    result = done if done is not None else task.result
    return lab_sources.task_query(frame, request, task=task, result=result, unique=unique)


def _lab_task_optimization(
    job_id: str, request: QueryRequest, runner: JobRunner, tasks: LabTasks
) -> dict:
    """A task view of an `opt:` source. Its identity carries its cells done, so a running job
    would key a new task at every poll, which coalescing cannot bound: nothing is requested until
    it finishes, and the answer says so."""
    status, frame = _lab_optimization(runner, job_id, request.view, request)
    if status.get("status") not in lab_sources.OPT_FINAL:
        return lab_sources.task_query(
            frame, request, task=None, result=None, reason=RUNNING_OPTIMIZATION
        )
    metric, scope = request.metric or frame.objective, request.filter.scope
    source = lab_sources.optimization_source(status, frame)
    key = importance_key(source, metric, scope, request.seed)
    body = lab_sources.optimization_importance(frame, metric=metric, scope=scope, seed=request.seed)
    task = tasks.request(key, METHOD, STAGES, body, keep_stopped=not request.rerun)
    return _lab_task_answer(frame, request, tasks, key, task)


def _lab_task_experiment(
    experiment_id: str,
    request: QueryRequest,
    experiments: experiments_module.ExperimentStore,
    cache: LabCache,
    tasks: LabTasks,
) -> dict:
    """A task view of an `exp:` source: its frame at the snapshot pinned for its task, which is
    requested and answered outside the read lock (`_lab_experiment`). `request` takes the pin
    over, releasing it whenever the task needs none; without `rerun`, a stopped key stays stopped
    (Ruling P13)."""

    def columns_of(meta) -> tuple[str, ...]:
        return lab_sources.COLUMNS_FOR(request.view, request, meta.parameters, meta.objective)

    pin = _TaskPin()
    with _lab_experiment(experiment_id, experiments, cache, columns_of, pin=pin) as (
        document,
        meta,
        frame,
    ):
        metric, scope = request.metric or meta.objective, request.filter.scope
        source = lab_sources.experiment_source(document)
        key = importance_key(source, metric, scope, request.seed)
        body = lab_sources.experiment_importance(
            document,
            experiments,
            cache,
            columns_of(meta),
            snapshot=pin.snapshot,
            metric=metric,
            scope=scope,
            seed=request.seed,
        )
        task = tasks.request(
            key,
            METHOD,
            STAGES,
            body,
            snapshot=pin.snapshot,
            hold=pin.take(),
            keep_stopped=not request.rerun,
        )
        unique = lab_sources.experiment_unique(cache, frame, document)
        return _lab_task_answer(frame, request, tasks, key, task, unique)


def _lab_robustness_optimization(
    job_id: str, request: QueryRequest, runner: JobRunner, tasks: LabTasks
) -> dict:
    """The `robustness` view of an `opt:` source: no tolerance of its own, so the default, labelled.
    B reads the finished importance of exactly these cells (its key carries their count), and
    nothing here requests a task."""
    status, frame = _lab_optimization(runner, job_id, request.view, request)
    metric, scope = request.metric or frame.objective, request.filter.scope
    key = importance_key(
        lab_sources.optimization_source(status, frame), metric, scope, request.seed
    )
    try:
        return lab_sources.robustness_query(
            frame,
            request,
            tolerance=DEFAULT_TOLERANCE,
            tolerance_label=DEFAULT_TOLERANCE_LABEL,
            axes=top_axes(tasks.result(key)),
        )
    except (KeyError, ValueError) as exc:
        raise _lab_refused(exc) from exc


def _lab_robustness_experiment(
    experiment_id: str,
    request: QueryRequest,
    experiments: experiments_module.ExperimentStore,
    cache: LabCache,
    tasks: LabTasks,
) -> dict:
    """The `robustness` view of an `exp:` source (Ruling P15): B's axes are the finished importance
    result at the frame's snapshot, or none. `LabTasks.result` is the one read of the executor
    here, outside the read lock in any case: a live task's status reads the runner, whose lock the
    job holds while it takes this write lock. A snapshot whose files went while a card read its
    block rows is the same 409 as any other."""

    def columns_of(meta) -> tuple[str, ...]:
        return lab_sources.COLUMNS_FOR(request.view, request, meta.parameters, meta.objective)

    with _lab_experiment(experiment_id, experiments, cache, columns_of) as (document, meta, frame):
        metric, scope = request.metric or meta.objective, request.filter.scope
        key = importance_key(lab_sources.experiment_source(document), metric, scope, request.seed)
        try:
            return lab_sources.experiment_robustness(
                document,
                experiments,
                cache,
                frame,
                request,
                axes=top_axes(tasks.result(key, frame.snapshot)),
            )
        except lab_store.SnapshotExpired as exc:
            raise HTTPException(409, "snapshot expired") from exc
        except (KeyError, ValueError) as exc:
            raise _lab_refused(exc) from exc


@router.get("/lab/build")
def lab_build(cache: LabCache = LAB_CACHE):
    """The worker's engine build and versions, its code and data roots, the Lab cache and the
    free space on the data root's disk (§9.8: a warning below LOW_DISK_GB)."""
    root = aegis_data_root()
    probe = root
    while not probe.exists() and probe.parent != probe:  # a store not yet created: its disk
        probe = probe.parent
    free_gb = round(shutil.disk_usage(probe).free / 1024**3, 3)
    return {
        "engine_build": identity.engine_build(),
        "versions": identity.versions(""),
        "app_root": str(Path(__file__).resolve().parents[2]),
        "data_root": str(root),
        "cache": cache.stats(),
        "disk": {"free_gb": free_gb, "low": free_gb < LOW_DISK_GB, "root": str(root)},
    }


@router.get("/lab/{src}/summary")
def lab_summary(
    src: str,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
    cache: LabCache = LAB_CACHE,
):
    ref = _lab_source(src)
    if ref.kind == "opt":
        status, frame = _lab_optimization(runner, ref.id, "summary", None)
        return lab_sources.summary(frame, None, status, None)
    with _lab_experiment(
        ref.id,
        experiments,
        cache,
        lambda meta: lab_sources.COLUMNS_FOR("summary", None, meta.parameters, meta.objective),
    ) as (document, meta, frame):
        unique = lab_sources.experiment_unique(cache, frame, document)
        index = lab_sources.experiment_index(cache, frame, document)
        return lab_sources.summary(
            frame, document, None, meta.spec_values, unique=unique, index=index, cache=cache
        )


@router.post("/lab/{src}/query")
def lab_query(
    src: str,
    request: QueryRequest,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
    cache: LabCache = LAB_CACHE,
    tasks: LabTasks = LAB_TASKS,
):
    ref = _lab_source(src)
    if request.view in lab_sources.TASK_VIEWS:
        if ref.kind == "opt":
            return _lab_task_optimization(ref.id, request, runner, tasks)
        return _lab_task_experiment(ref.id, request, experiments, cache, tasks)
    if request.view == "robustness":
        if ref.kind == "opt":
            return _lab_robustness_optimization(ref.id, request, runner, tasks)
        return _lab_robustness_experiment(ref.id, request, experiments, cache, tasks)
    if ref.kind == "opt":
        status, frame = _lab_optimization(runner, ref.id, request.view, request)
        identity_of = lab_sources.optimization_source(status, frame)
        return _lab_answer(frame, request, None, cache=cache, source_identity=identity_of)
    with _lab_experiment(
        ref.id,
        experiments,
        cache,
        lambda meta: lab_sources.COLUMNS_FOR(
            request.view, request, meta.parameters, meta.objective
        ),
    ) as (document, _, frame):
        index = None  # built or fetched only for the views that read it
        if request.view in lab_sources.INDEXED_VIEWS:
            index = lab_sources.experiment_index(cache, frame, document)
        return _lab_answer(
            frame,
            request,
            lab_sources.experiment_unique(cache, frame, document),
            cache=cache,
            source_identity=lab_sources.experiment_source(document),
            index=index,
        )


@router.get("/lab/{src}/trials/{trial}")
def lab_trial(
    src: str,
    trial: str,
    runner: JobRunner = RUNNER,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
    cache: LabCache = LAB_CACHE,
):
    """One trial by its id (`<src>#<trial_no>`, the `#` percent-encoded in the path)."""
    ref = _lab_source(src)
    try:
        trial_no = lab_sources.trial_number(ref, trial)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if ref.kind == "opt":
        status, frame = _lab_optimization(runner, ref.id, "trial", None)
        detail = lab_sources.trial_detail(
            frame, trial_no, lab_sources.optimization_identity(status)
        )
    else:
        with _lab_experiment(
            ref.id,
            experiments,
            cache,
            lambda meta: lab_sources.COLUMNS_FOR("trial", None, meta.parameters, meta.objective),
            trial_no=trial_no,  # that trial's rows only, through the store's predicate
        ) as (document, _, frame):
            detail = lab_sources.trial_detail(
                frame, trial_no, lab_sources.experiment_identity(document)
            )
    if detail is None:
        raise HTTPException(404, f"{ref} has no trial {trial_no}")
    return detail


@router.post("/lab/{src}/tasks/{task_id}/cancel")
def lab_cancel_task(
    src: str,
    task_id: str,
    tasks: LabTasks = LAB_TASKS,
    experiments: experiments_module.ExperimentStore = EXPERIMENTS,
):
    """Stops the analysis one of this source's Lab tasks belongs to: `task_id` names its key,
    whichever of its tasks it is. The key's waiting task is dropped at once and its running one
    stops at its next checkpoint, its finished stages kept and labelled partial; a finished task's
    id still stops the key's live tasks, and answers true. `cancelled` is false only when the key
    has nothing live left to stop. A task this source does not own is a 404: an experiment owns
    its tasks by its whole identity (`task_of`), so one deleted and created again under the same
    id never cancels its predecessor's; an optimization by its job id."""
    ref = _lab_source(src)
    if ref.kind == "exp":
        source = lab_sources.experiment_source(_experiment(experiments, ref.id))
    else:
        source = (ref.kind, ref.id)
    try:
        if not task_of(tasks.status(task_id).key, source):
            raise KeyError(task_id)
        return {"cancelled": tasks.cancel(task_id)}
    except KeyError as exc:
        raise HTTPException(404, f"unknown task {task_id!r}") from exc


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
    """A prepared frame and provenance per known symbol (Mission 12: no dict per bar); an unknown
    symbol is left for the plan to name, and so is a range too short to simulate: it holds no
    window, so it stays as its (at most 34) rows (QA D1)."""
    known = {s.symbol for s in store.symbols()}
    rows: dict[str, pd.DataFrame | list[dict]] = {}
    pinned: dict[str, PinnedSource] = {}
    if start is None or end is None:
        return rows, pinned
    for symbol in symbols:
        if symbol not in known:
            continue
        frame, source = _select(store, symbol, timeframe, start, end)  # BAR_CAP guards it
        if len(frame) < MIN_BARS:
            rows[symbol] = engine_rows(frame, symbol)
        else:
            rows[symbol] = prepare_archive_frame(frame, symbol)
        pinned[symbol] = source
    return rows, pinned


def _study_workers(rows: dict[str, list[dict]]) -> int:
    """The workers a study's pool would run on now (Mission 10 review I1)."""
    return fitted_workers(max((len(r) for r in rows.values()), default=0))


def _study_job(document, rows, pinned, repository) -> studies_module.StudyJob:
    try:
        return studies_module.StudyJob(document, rows, pinned, repository)
    except ValueError as exc:  # not even one pool worker fits in free memory now
        raise HTTPException(422, str(exc)) from exc


def _timestamps(
    frames: dict[str, pd.DataFrame | list[dict]],
) -> dict[str, studies_module.IsoTimes | list[str]]:
    """Each symbol's bar times as ISO strings, read one at a time from a frame (Mission 12)."""
    return {
        symbol: studies_module.IsoTimes(bars)
        if isinstance(bars, pd.DataFrame)
        else [r["timestamp"] for r in bars]
        for symbol, bars in frames.items()
    }


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
            _study_workers(rows),
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
            _study_workers(rows),
            start,
            end,
            data={symbol: _provenance(source) for symbol, source in pinned.items()},
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = _study_job(document, rows, pinned, repository)
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
    job = _study_job(document, rows, pinned, repository)
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


@router.get("/library/{kind}/{item_id}")
def library_entry(kind: str, item_id: str, library: Library = LIBRARY_INDEX):
    """One saved result's entry, live or in Recently deleted."""
    _library_kind(kind)
    try:
        return library.entry(kind, item_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown {kind} {item_id!r}") from exc


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
    except (Refused, ExperimentReferenced) as exc:
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
    "get_lab_cache",
    "get_lab_tasks",
    "get_repository",
    "get_runner",
    "get_store",
    "router",
    "warm_in_background",
]
