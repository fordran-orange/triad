"""The Lab's sources (Optimization Lab v2 spec §6.4, §7, §9.2, §9.3): what one `/aegis/api/lab`
request reads, and the answers built from it.

An `exp:<id>` source is an experiment's trial store. A request reads the document and the files
under the experiment's read lock (`LOCKS.read`), takes the latest snapshot once, holds it in the
registry for its own life and loads only the columns its view needs (`COLUMNS_FOR`) through the
Lab cache, keyed by that snapshot. It never takes the runner's lock. An `opt:<job_id>` source is
a grid optimization's cells, from one `runner.status` call (the runner's lock, briefly, and no Lab
lock), laid out in the same columns: one side, block 0, each cell a grid trial numbered by its
place in the job's cells. The views themselves are `query.py`'s.

What a snapshot fixes is cached beside its tables (Phase 3 Task 0): one table per column set and
row selection, whatever order a view asks for its columns in; the snapshot's `FrameIndex`; the
summary's counts per value and headline; and each aggregate matrix with its four stats, keyed by
its source's identity, so a stat change answers from it and one source never meets another's.

The importance task's three views (`TASK_VIEWS`, Phase 3 Task 6) answer from a Lab task instead of
computing in the request: `experiment_importance` and `optimization_importance` are the task's
body, and `task_query` builds their answers from the stage the route chose.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from products.aegis.experiments import (
    UNFINISHED,
    ExperimentDocument,
    ExperimentStore,
    _cells_schema_v2,
    block0_rows,
)
from products.aegis.lab import identity
from products.aegis.lab.cache import LabCache
from products.aegis.lab.importance import (
    computed_of,
    importance_basis,
    importance_payload,
    importance_stages,
    interactions_payload,
    triples_payload,
)
from products.aegis.lab.index import FrameIndex, build_index
from products.aegis.lab.policy import SHARPE_MIN_TRADES
from products.aegis.lab.query import (
    ALL_BLOCKS,
    BASIS_EXACT,
    BLOCK0,
    METRIC_NAMES,
    LabFilter,
    ParameterInfo,
    Selection,
    TrialFrame,
    _status_tallies,
    aggregated_basis,
    counts_view,
    envelope,
    filter_mask,
    marginals_view,
    matrix_view,
    metric_column,
    page_view,
    parallel_view,
    scope_counts,
    square_trials_view,
    tested_per_value,
    top_view,
    undefined_mask,
)
from products.aegis.lab.store import (
    _KEPT,
    LOCKS,
    REGISTRY,
    Counters,
    Snapshot,
    SnapshotExpired,
    TrialTable,
    file_set,
    latest_snapshot,
    snapshot_json,
)
from products.aegis.lab.tasks import Body, TaskStatus, snapshot_label, status_json
from products.aegis.optimize import SIDE_KEY, grid_values
from products.aegis.pool import METRICS, SCOPES
from products.aegis.runs import _check_id
from products.aegis.strategy import StrategySpec
from products.aegis.surface import _whole_number, resolve_path

# Every view reads these: the trial, its block and status (completed = ok in block 0) and its
# configuration (`unique` counts distinct keys).
BASE = ("trial_no", "block", "status", "param_key")
VIEWS = (
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
)
INDEXED_VIEWS = ("counts", "matrix", "page", "marginals")  # the views that read the index
TASK_VIEWS = ("importance", "interactions", "triples")  # answered from the importance task
# A page row's `values` beside the objective (the page's metric columns, §9.3).
PAGE_VALUES = ("net_pnl", "max_drawdown", "trade_count", "exposure", "sharpe_trade")
_REQUIRED = {
    "matrix": ("rows", "cols", "metric"),
    "square_trials": ("rows", "cols", "row_value", "col_value"),
}
OPT_FINAL = ("done", "cancelled", "failed", "lost")  # an optimization no longer changing
META_BYTES = 4096  # the nominal size of an `exp-meta` entry (Task 7's cache rule)
UNIQUE_BYTES = 64  # and of an `exp-unique` count
SUMMARY_BYTES = 65_536  # and of an `exp-summary` part (counts per value and the headline)
# A cached aggregate matrix's size per square, its four stats' values, stats and histogram
# included (1.3 to 1.9 KB measured, from 200 x 200 to 12 x 12 squares, every square tested).
SQUARE_BYTES = 2048
# The row selection (`query.BLOCK0` / `ALL_BLOCKS`, Ruling P1) is in a table's and an index's
# key: ordinary views read block 0, filtered before caching; the importance task reads every
# screening block, under its own key.
_TRIAL_NUMBER = re.compile(r"[0-9]{1,18}")  # below 2**63: a trial_no is an int64


@dataclass(frozen=True)
class SourceRef:
    kind: Literal["exp", "opt"]
    id: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


def parse_source(text: str) -> SourceRef:
    """`exp:<experiment id>` or `opt:<optimization job id>`, the id checked as the repository
    checks it; ValueError otherwise."""
    kind, colon, identifier = text.partition(":")
    if not colon or kind not in ("exp", "opt"):
        raise ValueError(f"unknown source {text!r}: a Lab source is exp:<id> or opt:<job_id>")
    _check_id(identifier)
    return SourceRef(kind, identifier)


def trial_number(source: SourceRef, trial: str) -> int:
    """The trial number of `<source>#<n>`; ValueError for an id of another source or a
    malformed one."""
    prefix = f"{source}#"
    if not trial.startswith(prefix):
        raise ValueError(f"trial {trial!r} is not a trial of {source}")
    number = trial[len(prefix) :]
    if not _TRIAL_NUMBER.fullmatch(number):
        raise ValueError(f"trial {trial!r}: {number!r} is not a trial number")
    return int(number)


# --- parameters and an experiment's metadata --------------------------------------------------


def _parameter(
    spec: StrategySpec, path: str, start: float, stop: float, step: float, values: Sequence
) -> ParameterInfo:
    """A surface (or grid) parameter: its side, its family (`<side>:<indicator id>`, or
    `<side>:levels` for a stop or target percentage) and whether its values are whole numbers,
    as `identity.search_space` names them."""
    side = path.split("_side", 1)[0]
    try:
        side_key, identifier, field = resolve_path(spec, path)
        whole = _whole_number(spec, side_key, identifier, field)
    except (KeyError, ValueError):  # a path the spec no longer resolves still names its family
        parts = path.split(".")
        identifier = parts[2] if len(parts) > 3 and parts[1] == "indicators" else ""
        whole = path.endswith(".length")
    return ParameterInfo(
        path=path,
        side=side,
        family=f"{side}:{identifier or 'levels'}",
        type="int" if whole else "float",
        start=float(start),
        stop=float(stop),
        step=float(step),
        values=[float(value) for value in values],
    )


@dataclass(frozen=True)
class ExperimentMeta:
    """What every frame of an experiment shares while its document is unchanged (the `exp-meta`
    cache entry): its parameters, its objective, the pinned spec's values on those parameters
    (§7.1's default slice) and the plan's counts. Known before any column list is."""

    parameters: list[ParameterInfo]
    objective: str
    spec_values: dict[str, float]
    space: int
    valid: int
    budget_total: int


def experiment_meta(document: ExperimentDocument) -> ExperimentMeta:
    spec = document.spec
    parameters = [
        _parameter(spec, p.path, p.start, p.stop, p.step, p.values())
        for p in document.surface.parameters
    ]
    effective = identity.full_effective_params(spec)
    plan = document.plan
    return ExperimentMeta(
        parameters=parameters,
        objective=document.objective,
        spec_values={p.path: effective[p.path] for p in parameters if p.path in effective},
        space=int(plan["grid_cells"]),
        valid=int(plan["valid_cells"]),
        budget_total=int(plan["planned_runs"]),
    )


def cached_meta(document: ExperimentDocument, cache: LabCache) -> ExperimentMeta:
    return cache.get(
        (("exp-meta", document.id), document.updated_at),
        lambda: experiment_meta(document),
        size=lambda _: META_BYTES,
    )


# --- the columns a request loads ---------------------------------------------------------------


def _require(view: str, request: Any) -> None:
    missing = [name for name in _REQUIRED.get(view, ()) if getattr(request, name) is None]
    if missing:
        raise ValueError(f"the {view} view needs {', '.join(missing)}")


def _sort_column(sort: str, paths: set[str]) -> str:
    scope, _, metric = sort.partition(".")
    if sort == "trial_no" or sort in paths or (scope in SCOPES and metric in METRIC_NAMES):
        return sort
    raise KeyError(f"unknown sort column {sort!r}")


def COLUMNS_FOR(
    view: str,
    request: Any,
    parameters: Sequence[ParameterInfo],
    objective: str,
    side: str | None = None,
) -> tuple[str, ...]:
    """The columns one request loads (§9.2: projected, never the whole row set): `BASE`, every
    path the filter names (and `pass` / `design` when it names a pass), then the view's own.
    `request` is a `QueryRequest` for the query views and None for `summary` and `trial`
    (the trial route's one row: every metric of every scope). `side` is an optimizer source's
    side, whose metric columns its summary reads. A path that is not a parameter, a metric that
    does not exist or a missing view argument is a ValueError; an unknown sort a KeyError."""
    paths = [p.path for p in parameters]
    known = set(paths)

    def parameter(path: str | None) -> str:
        if path not in known:
            raise ValueError(f"unknown path {path!r}: not a parameter of this source")
        return path

    columns = list(BASE)
    if view == "summary":  # tested_per_value, and the headline over the objective
        columns += [*paths, metric_column(side or "combined", objective)]
        return tuple(dict.fromkeys(columns))
    if view == "trial":
        columns += ["cell", "attempt", "pass", "design"]
        columns += [f"pos.{k}" for k in range(len(paths))] + paths
        columns += [f"{scope}.{name}" for scope in SCOPES for name in METRIC_NAMES]
        columns += ["elapsed_ms", "engine", "chunk", "finished_at"]
        return tuple(dict.fromkeys(columns))
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}")
    flt = request.filter
    scope = flt.scope
    columns += [parameter(path) for path in (*flt.ranges, *flt.values)]
    if flt.pass_:
        columns += ["pass", "design"]
    _require(view, request)
    metric = request.metric if view == "counts" else (request.metric or objective)
    if view == "counts":
        if metric is not None:  # so `undefined` agrees with the other views
            columns.append(metric_column(scope, metric))
    elif view == "matrix":
        columns += [parameter(request.rows), parameter(request.cols)]
        columns.append(metric_column(scope, metric))
        columns += [parameter(path) for path in request.fixed or {}]
        if request.mode == "aggregate":  # the TVD over the other parameters
            columns += paths
    elif view in ("page", "square_trials"):
        if view == "square_trials":
            parameter(request.rows)
            parameter(request.cols)
        # `cell` stays beside trial_no, so materialize by cell is reachable from a row
        columns += ["cell", "pass", "design", "valid", *paths, metric_column(scope, metric)]
        if view == "page" and request.sort is not None:
            columns.append(_sort_column(request.sort, known))
        columns += [metric_column(scope, name) for name in (objective, *PAGE_VALUES)]
    elif view == "top":
        columns += [metric_column(scope, metric), *paths]
    elif view == "marginals":
        chosen = paths if request.paths is None else request.paths
        columns += [parameter(path) for path in chosen]
        columns.append(metric_column(scope, metric))
    elif view in TASK_VIEWS:  # the cohort's rows (a legacy source's design comes from its pass)
        columns += ["design", "pass", *paths, metric_column(scope, metric)]
    else:  # parallel
        chosen = paths if request.axes is None else request.axes
        columns += [parameter(path) for path in chosen]
        columns.append(metric_column(scope, metric))
    return tuple(dict.fromkeys(columns))


def project(frame: TrialFrame, columns: Sequence[str]) -> TrialFrame:
    """The frame with only `columns` (an optimizer's frame is built whole from its cells)."""
    return replace(frame, table=frame.table.select(list(columns)))


# --- exp: an experiment's trial store ---------------------------------------------------------


@dataclass(frozen=True)
class _Selected:
    """A snapshot's trials in one row selection, and the snapshot's `evaluations_done` when the
    selection dropped rows it counts (None: the table holds every row)."""

    trials: TrialTable
    evaluations_done: int | None


def _select_rows(trials: TrialTable, selection: Selection) -> _Selected:
    """Block 0 for `BLOCK0`, its `evaluations_done` counted over every block first (§6.4,
    Ruling P5); every row for `ALL_BLOCKS`. A table without a screening block's row is kept as
    read, never copied."""
    if selection == ALL_BLOCKS:
        return _Selected(trials, None)
    if selection != BLOCK0:
        raise ValueError(f"unknown row selection {selection!r}")
    kept = block0_rows(trials.table)
    if kept is trials.table:
        return _Selected(trials, None)
    done = _status_tallies(trials.table)[1]["evaluations_done"]
    return _Selected(replace(trials, table=kept), done)


def open_experiment(
    document: ExperimentDocument,
    store: ExperimentStore,
    cache: LabCache,
    columns: Sequence[str],
    *,
    trial_no: int | None = None,
    selection: Selection = BLOCK0,
    snapshot: Snapshot | None = None,
) -> tuple[TrialFrame, int]:
    """The frame of one request and its registry handle, which the caller releases when its
    answer is built. Under the experiment's read lock: the latest snapshot, read once; its file
    set registered; its trials in `columns` from the cache or read at that same snapshot, so the
    key, the handle and the rows name one file set even while the job writes its next chunk
    (`write_chunk` takes no write lock). The key carries the document's `created_at`, so an
    experiment deleted and created again under the same id never meets its predecessor's
    tables. With `trial_no`, that trial's rows only, read through the store's predicate and
    never cached (one row is not worth an entry; its counts are that trial's, never the
    snapshot's). A legacy (layout 1) folder is promoted by `store.trials` and keyed by its
    synthesized snapshot. `selection` picks the rows (Ruling P1): block 0 for every ordinary
    view, filtered before caching, so a screened experiment costs the cache no more than an
    unscreened one; `ALL_BLOCKS` for the importance task, cached under its own key, never the
    block-0 table's. With `snapshot`, that snapshot instead of the latest (a Lab task reads the
    one its route pinned, `pin_experiment`, whatever the job wrote since), under the same lock,
    registry hold and cache key, so it is cached under its own generation and watermark; one
    whose files were reclaimed, or one ahead of the latest, is `SnapshotExpired`, never the
    latest read in its place."""
    experiment_id = document.id
    columns = tuple(columns)
    meta = cached_meta(document, cache)
    cells_dir = store.cells_dir(experiment_id)
    with LOCKS.read(experiment_id):
        manifest, latest = latest_snapshot(cells_dir)
        if snapshot is None:
            snapshot = latest
        elif snapshot.generation > latest.generation or (
            snapshot.chunk_watermark > latest.chunk_watermark
        ):
            raise SnapshotExpired(
                f"{cells_dir.name}: snapshot {snapshot} is ahead of the latest, {latest}"
            )
        handle = REGISTRY.open(experiment_id, snapshot, file_set(cells_dir, manifest, snapshot))
        try:
            if trial_no is not None:
                selected = _select_rows(
                    store.trials(
                        experiment_id, list(columns), snapshot=snapshot, trial_no=trial_no
                    ),
                    selection,
                )
            else:
                # The column set, never its order: one entry serves every view that loads it.
                key = (
                    snapshot.generation,
                    snapshot.chunk_watermark,
                    selection,
                    column_set(columns),
                )
                selected = cache.get(
                    (("exp", experiment_id), document.created_at, *key),
                    lambda: _select_rows(
                        store.trials(experiment_id, list(columns), snapshot=snapshot), selection
                    ),
                    size=lambda held: held.trials.table.nbytes,
                    release=True,
                )
        except BaseException:
            REGISTRY.release(handle)
            raise
    trials = selected.trials
    # The request's own order, as `read_trials` gives it (a zero-copy select).
    table = trials.table.select(list(dict.fromkeys([*columns, *_KEPT])))
    frame = TrialFrame(
        source=f"exp:{experiment_id}",
        table=table,
        parameters=meta.parameters,
        space=meta.space,
        valid=meta.valid,
        budget_total=meta.budget_total,
        scheduled=Counters.from_document(document).scheduled,
        reserved=0,  # no reservations and no reuse by value in Phase 2 (decision 18)
        reused=0,
        duplicates=trials.duplicates,
        snapshot=trials.snapshot,
        provisional=document.status in UNFINISHED,
        layout=trials.layout,
        objective=meta.objective,
        blocks=document.blocks,
        evaluations_done=selected.evaluations_done,
        selection=selection,
    )
    return frame, handle


def pin_experiment(document: ExperimentDocument, store: ExperimentStore) -> tuple[Snapshot, int]:
    """The experiment's latest snapshot and a registry handle holding its file set, which the
    caller releases (Phase 3 Task 3): a Lab task pins its snapshot at request time and reads it
    later with `open_experiment(..., snapshot=)`, so no reclamation in between takes its files."""
    cells_dir = store.cells_dir(document.id)
    with LOCKS.read(document.id):
        manifest, snapshot = latest_snapshot(cells_dir)
        files = file_set(cells_dir, manifest, snapshot)
        return snapshot, REGISTRY.open(document.id, snapshot, files)


def column_set(columns: Sequence[str]) -> tuple[str, ...]:
    """A table's cache key component: its columns sorted, each once."""
    return tuple(sorted(set(columns)))


def experiment_index(
    cache: LabCache, frame: TrialFrame, document: ExperimentDocument
) -> FrameIndex:
    """The snapshot's index (index.py), built from the first request's frame on that snapshot of
    this instance of the experiment and shared by every later one, whatever columns it loads:
    their rows are the same block-0 rows in the same order. Only a `BLOCK0` frame is indexed: any
    other selection is a ValueError before the cache is touched, so an every-block frame (Task 6's
    importance task) never becomes the index every ordinary view of the snapshot reads."""
    if frame.selection != BLOCK0:
        raise ValueError(
            f"the snapshot index is built from block-0 frames only, not a {frame.selection!r} frame"
        )
    snapshot = frame.snapshot
    return cache.get(
        (
            ("exp-index", document.id),
            document.created_at,
            snapshot.generation,
            snapshot.chunk_watermark,
            BLOCK0,
        ),
        lambda: build_index(frame),
        size=lambda index: index.nbytes(frame.parameters),
        release=True,
    )


def experiment_source(document: ExperimentDocument) -> tuple:
    """The identity a cached answer of an experiment carries: one instance of its id."""
    return ("exp", document.id, document.created_at)


def optimization_source(status: dict, frame: TrialFrame) -> tuple:
    """The identity a cached answer of an optimization carries: the job and the cells done that
    its frame holds (one frozen copy of them, which a running job only appends to)."""
    return ("opt", status["job_id"], frame.table.num_rows)


def scheduled_uniform(document: ExperimentDocument) -> int:
    """The uniform configurations an experiment schedules, the N of the importance basis line
    (§7.3): its first pass, every valid cell when exhaustive; when sampled, the cells its Latin
    hypercube drew, which may be fewer than planned, or before the draw the planned first pass.
    Refinement rows are adaptive and never counted."""
    plan = document.plan
    if plan["mode"] == "exhaustive":
        return int(plan["valid_cells"])
    if document.first_pass_cells is not None:
        return len(document.first_pass_cells)
    return int(plan["first_pass"])


def experiment_importance(
    document: ExperimentDocument,
    store: ExperimentStore,
    cache: LabCache,
    columns: Sequence[str],
    *,
    snapshot: Snapshot,
    metric: str,
    scope: str,
    seed: int,
) -> Body:
    """The importance task's body on an experiment (§9.4): when the task runs, its own frame at
    the `snapshot` its route pinned, every screening block's rows (`ALL_BLOCKS`; a K = 0
    experiment has only block 0, so it shares the route's block-0 table), computed with no lock
    held (`open_experiment` has released its read lock by then) and its handle released in a
    `finally`, whatever ends the task. The pin itself is the executor's (`LabTasks.request`'s
    `hold`). Building the body reads nothing, so it cannot refuse between pin and request."""

    def body(checkpoint) -> Iterator[dict]:
        frame, handle = open_experiment(
            document,
            store,
            cache,
            columns,
            selection=ALL_BLOCKS if document.blocks else BLOCK0,
            snapshot=snapshot,
        )
        try:
            yield from importance_stages(
                frame,
                metric=metric,
                scope=scope,
                seed=seed,
                checkpoint=checkpoint,
                scheduled=scheduled_uniform(document),
            )
        finally:
            REGISTRY.release(handle)

    return body


def optimization_importance(frame: TrialFrame, *, metric: str, scope: str, seed: int) -> Body:
    """The importance task's body on a finished optimization: its one `opt_frame` copy, in memory
    (no lock, no handle), N its grid's scheduled cells (the frame's `scheduled`)."""

    def body(checkpoint) -> Iterator[dict]:
        yield from importance_stages(
            frame, metric=metric, scope=scope, seed=seed, checkpoint=checkpoint
        )

    return body


def canonical_filter(flt: LabFilter) -> str:
    """The filter as a server-side cache key, never echoed: the client's `filter_hash` is."""
    return json.dumps(flt.model_dump(mode="json", by_alias=True), sort_keys=True)


def matrix_payload_key(
    source_identity: tuple,
    snapshot: Snapshot | None,
    canonical_filter: str,
    scope: str,
    rows: str,
    cols: str,
    metric: str,
    fixed: dict[str, float] | None,
    mode: str,
) -> tuple:
    """A matrix payload's cache key: its source's identity first (`experiment_source` or
    `optimization_source`), so one source is never served another's heatmap, then the snapshot,
    the filter and the view's own arguments. The stat is not part of it: the payload holds all
    four."""
    at = None if snapshot is None else (snapshot.generation, snapshot.chunk_watermark)
    held = tuple(sorted((fixed or {}).items()))
    return (
        ("matrix", *source_identity),
        at,
        canonical_filter,
        scope,
        rows,
        cols,
        metric,
        held,
        mode,
    )


def experiment_unique(cache: LabCache, frame: TrialFrame, document: ExperimentDocument) -> int:
    """`unique` (the distinct configurations completed) depends on the snapshot alone, so it is
    counted once per snapshot of this instance of the experiment (its `created_at`) and shared by
    every request and every projection on it."""
    snapshot = frame.snapshot
    return cache.get(
        (
            ("exp-unique", document.id),
            document.created_at,
            snapshot.generation,
            snapshot.chunk_watermark,
        ),
        lambda: scope_counts(frame, LabFilter())["unique"],
        size=lambda _: UNIQUE_BYTES,
    )


def experiment_identity(document: ExperimentDocument) -> dict:
    """A trial's identity block: the computation's `inputs_key` (None when the document never
    recorded its engine build, as a legacy one; over its screening blocks), the pinned spec's
    hash and the data its trials ran on: the pinned source, or the data reference of a document
    that pinned none."""
    build = (document.versions or {}).get("engine_build")
    if document.data_pinned is not None:
        name, data = "data_pinned", dict(document.data_pinned)
    else:
        name, data = "data", document.data.model_dump(mode="json")
    settings = document.settings.model_dump(mode="json")
    key = (
        None
        if build is None
        else identity.inputs_key(
            document.strategy_hash, data, settings, build, blocks=document.blocks
        )
    )
    return {"inputs_key": key, "strategy_hash": document.strategy_hash, name: data}


# --- opt: a grid optimization's cells ---------------------------------------------------------


def _number(value) -> float | None:
    """A float, None where undefined: an undefined metric is never sent as a number."""
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def opt_frame(status: dict) -> TrialFrame:
    """An optimization's evaluated cells as a frame (`status` is one `runner.status` result):
    cell k is trial k of block 0, attempt 0, pass `grid` (design `uniform`); its parameters under
    their side-prefixed paths, its grid positions from `grid_values`, its `param_key` over the
    full effective set, its metrics in `<side>.<metric>` only (the other scopes and the trade
    Sharpe null). A cell the pool refused (one carrying `skip_reason`) is `invalid`, else `ok`.
    The space is the whole grid, skipped cells included; the schedule is its kept cells."""
    cells = list(status.get("cells") or [])  # one frozen copy: a running job appends meanwhile
    side = status["side"]
    side_key = SIDE_KEY[side]
    spec = StrategySpec.model_validate(status["strategy"])
    enabled = [p for p in getattr(spec, side_key).optimization if p.enabled]
    lattices = grid_values(getattr(spec, side_key))
    steps = {f"{side_key}.{p.path}": p.step for p in enabled}
    by_path = {p.path: p for p in enabled}
    parameters = [
        _parameter(
            spec,
            f"{side_key}.{path}",
            by_path[path].start,
            by_path[path].stop,
            by_path[path].step,
            values,
        )
        for path, values in lattices.items()
    ]
    n = len(cells)
    params = [
        {f"{side_key}.{path}": float(value) for path, value in (cell.get("params") or {}).items()}
        for cell in cells
    ]
    statuses = ["invalid" if cell.get("skip_reason") else "ok" for cell in cells]
    data: dict[str, Any] = {
        "trial_no": np.arange(n, dtype=np.int64),
        "cell": np.arange(n, dtype=np.int64),
    }
    for k, (path, values) in enumerate(lattices.items()):
        at = {float(value): i for i, value in enumerate(values)}
        full = f"{side_key}.{path}"
        data[f"pos.{k}"] = [at.get(row.get(full)) for row in params]
        data[full] = [row.get(full) for row in params]
    data["param_key"] = [identity.param_key(spec, row, steps) for row in params]
    data["pass"] = ["grid"] * n
    data["design"] = ["uniform"] * n
    data["block"] = np.zeros(n, dtype=np.uint8)
    data["attempt"] = np.zeros(n, dtype=np.uint8)
    data["status"] = statuses
    data["valid"] = [label == "ok" for label in statuses]
    data["skip_reason"] = [cell.get("skip_reason") for cell in cells]
    for metric in METRICS:
        data[f"{side}.{metric}"] = [
            _number((cell.get("metrics") or {}).get(metric)) for cell in cells
        ]
    data["engine"] = [status.get("engine")] * n
    schema = _cells_schema_v2([f"{side_key}.{path}" for path in lattices])
    table = pa.Table.from_arrays(
        [
            pa.array(data[field.name], field.type)
            if field.name in data
            else pa.nulls(n, field.type)
            for field in schema
        ],
        schema=schema,
    )
    total = int(status["total_cells"])
    return TrialFrame(
        source=f"opt:{status['job_id']}",
        table=table,
        parameters=parameters,
        space=total + int(status["skipped_cells"]),
        valid=total,
        budget_total=total,
        scheduled=total,
        reserved=0,
        reused=0,
        duplicates=0,
        snapshot=None,
        provisional=status.get("status") not in OPT_FINAL,
        layout=0,  # not a cells folder; the summary reports `layout: null`
        objective=status.get("objective") or "net_pnl",
    )


def optimization_identity(status: dict) -> dict:
    """An optimization records no engine build, so its trials carry no `inputs_key`."""
    return {
        "inputs_key": None,
        "strategy_hash": status.get("strategy_hash"),
        "data_pinned": status.get("data"),
    }


# --- the answers ------------------------------------------------------------------------------


def _summary_part(frame: TrialFrame, scope_name: str, mask: np.ndarray, index: FrameIndex) -> dict:
    """What a summary reads of the snapshot alone: each parameter's tested trials per value (or
    bucket), counted from the index's codes over the completed rows, and the headline's best
    trial and undefined count over the objective."""
    column = metric_column(scope_name, frame.objective)
    members = np.flatnonzero(mask)
    return {
        "tested": {
            parameter.path: tested_per_value(frame, parameter, members, index)
            for parameter in frame.parameters
        },
        "best": top_view(frame, LabFilter(scope=scope_name), metric=frame.objective, k=1)["rows"],
        "undefined": int(undefined_mask(frame.table.column(column))[mask].sum()),
    }


def summary(
    frame: TrialFrame,
    document: ExperimentDocument | None,
    status: dict | None,
    spec_values: dict[str, float] | None,
    *,
    unique: int | None = None,
    index: FrameIndex | None = None,
    cache: LabCache | None = None,
) -> dict:
    """GET /lab/{src}/summary: the source's unfiltered scope, its parameters (each value's or
    bucket's tested trials), the headline over the objective (an experiment's combined scope, an
    optimization's own side), the latest snapshot of a layout-2 store and the identity fields.
    `document` for an `exp:` source, `status` for an `opt:` one. Without the snapshot's `index`
    one is built for this frame. With a `cache`, an experiment's snapshot part is kept under
    `("exp-summary", id), created_at, generation, watermark`; the counts and the document's own
    fields are read each time."""
    side = None if document is not None else status["side"]
    scope_name = side or "combined"
    if index is None:
        index = build_index(frame)
    unfiltered = LabFilter()
    mask = filter_mask(frame, unfiltered, index=index)
    counts = scope_counts(frame, unfiltered, unique=unique, mask=mask, index=index)
    column = metric_column(scope_name, frame.objective)
    if cache is not None and document is not None and frame.snapshot is not None:
        part = cache.get(
            (
                ("exp-summary", document.id),
                document.created_at,
                frame.snapshot.generation,
                frame.snapshot.chunk_watermark,
            ),
            lambda: _summary_part(frame, scope_name, mask, index),
            size=lambda _: SUMMARY_BYTES,
        )
    else:
        part = _summary_part(frame, scope_name, mask, index)
    best, undefined = part["best"], part["undefined"]
    parameters = []
    for parameter in frame.parameters:
        entry, tested = part["tested"][parameter.path]
        bucketed = "buckets" in entry
        parameters.append(
            {
                "path": parameter.path,
                "side": parameter.side,
                "family": parameter.family,
                "type": parameter.type,
                "start": parameter.start,
                "stop": parameter.stop,
                "step": parameter.step,
                "n_values": len(parameter.values),
                "values": None if bucketed else entry["values"],
                "tested_per_value": tested,
                "bucketed": bucketed,
            }
        )
    latest = None
    if document is not None and frame.layout == 2 and frame.snapshot is not None:
        latest = snapshot_json(frame.snapshot)
    exp = document is not None
    return {
        "source": frame.source,
        "kind": "exp" if exp else "opt",
        "layout": frame.layout if exp else None,
        "status": document.status if exp else status.get("status"),
        "counts": counts,
        "parameters": parameters,
        "headline": {
            "objective": frame.objective,
            "best": None
            if not best
            else {
                "trial_id": best[0]["trial_id"],
                "value": best[0]["values"][column],
                "params": best[0]["params"],
            },
            "completed": counts["completed"],
            "undefined": undefined,
        },
        "snapshots": {"latest": latest},
        "provisional": frame.provisional,
        "versions": document.versions if exp else None,
        "data_pinned": document.data_pinned if exp else status.get("data"),
        "engine": document.engine if exp else status.get("engine"),
        "spec_values": spec_values,
        "filter_hash": None,
    }


def _matrix(
    frame: TrialFrame,
    request: Any,
    metric: str,
    index: FrameIndex | None,
    cache: LabCache | None,
    source_identity: tuple | None,
) -> dict:
    """The matrix view's payload. An aggregate one, with a cache and the source's identity, is
    computed with its four stats once per `matrix_payload_key` and answered from that entry for
    any stat."""
    flt = request.filter

    def compute(**extra) -> dict:
        return matrix_view(
            frame,
            flt,
            rows=request.rows,
            cols=request.cols,
            metric=metric,
            mode=request.mode,
            stat=request.stat,
            fixed=request.fixed,
            index=index,
            **extra,
        )

    if request.mode != "aggregate" or cache is None or source_identity is None:
        return compute()
    key = matrix_payload_key(
        source_identity,
        frame.snapshot,
        canonical_filter(flt),
        flt.scope,
        request.rows,
        request.cols,
        metric,
        request.fixed,
        request.mode,
    )
    payload = cache.get(
        key,
        lambda: compute(all_stats=True),
        size=lambda held: SQUARE_BYTES * len(held["rows"]) * len(held["cols"]),
    )
    by_stat = payload["values_by_stat"]
    return {
        name: by_stat[request.stat] if name == "values" else value
        for name, value in payload.items()
        if name != "values_by_stat"
    }


def run_query(
    frame: TrialFrame,
    request: Any,
    *,
    unique: int | None = None,
    index: FrameIndex | None = None,
    cache: LabCache | None = None,
    source_identity: tuple | None = None,
) -> dict:
    """POST /lab/{src}/query: one view of one filter in the envelope. The filter's mask is
    computed once for the scope; each view states its basis, and `shown` is what it sends (the
    squares holding trials, the rows, the bundles; 0 for counts and marginals). Without a
    `metric`, a view reads the objective (counts then counts no `undefined`). A view's refusal
    is its ValueError or KeyError. `index` is the snapshot's (None: computed per request); with
    a `cache` and the source's identity, an aggregate matrix is cached with its four stats."""
    flt = request.filter
    view = request.view
    metric = request.metric if view == "counts" else (request.metric or frame.objective)
    mask = filter_mask(frame, flt, index=index)
    aggregated = aggregated_basis(int(mask.sum()))

    def scope(shown: int, basis: str = BASIS_EXACT) -> dict:
        return scope_counts(
            frame, flt, shown, metric=metric, basis=basis, unique=unique, mask=mask, index=index
        )

    if view == "counts":
        payload: dict = {}
        counted = counts_view(frame, flt, metric=metric, unique=unique, mask=mask, index=index)
    elif view == "matrix":
        payload = _matrix(frame, request, metric, index, cache, source_identity)
        squares = sum(1 for row in payload["counts"] for count in row if count)
        counted = scope(squares, payload["basis"])
    elif view == "page":
        payload = page_view(
            frame,
            flt,
            sort=request.sort,
            descending=request.descending,
            offset=request.offset,
            limit=request.limit,
            metric=metric,
            index=index,
        )
        counted = scope(len(payload["rows"]))
    elif view == "top":
        payload = top_view(frame, flt, metric=metric, k=request.k)
        counted = scope(len(payload["rows"]))
    elif view == "marginals":
        payload = marginals_view(frame, flt, metric=metric, paths=request.paths, index=index)
        counted = scope(0, aggregated)
    elif view == "parallel":
        axes = request.axes if request.axes is not None else [p.path for p in frame.parameters]
        payload = parallel_view(frame, flt, axes=axes, metric=metric)
        counted = scope(payload["shown_bundles"], aggregated)
    elif view == "square_trials":
        payload = square_trials_view(
            frame,
            flt,
            rows=request.rows,
            cols=request.cols,
            row_value=request.row_value,
            col_value=request.col_value,
            offset=request.offset,
            limit=request.limit,
        )
        counted = scope(len(payload["rows"]))
    else:
        raise ValueError(f"unknown view {view!r}")
    return envelope(
        view,
        payload,
        counted,
        filter_hash=request.filter_hash,
        snapshot=frame.snapshot,
        provisional=frame.provisional,
    )


def task_query(
    frame: TrialFrame,
    request: Any,
    *,
    task: TaskStatus | None,
    result: dict | None,
    reason: str | None = None,
    unique: int | None = None,
) -> dict:
    """POST /lab/{src}/query for `TASK_VIEWS`: the view of `result`, the importance task's stage
    the route chose, beside `task`, its status (None: no task was requested, and `reason` says
    why) and `snapshot_label` when `result` is of a snapshot the source has moved on from. The
    filter is ignored (§7.3): the scope is the unfiltered one of the request's side, so a filter
    changes nothing in the answer. The basis line is `importance_basis`'s."""
    view = request.view
    if view == "importance":
        payload, shown = {"importance": importance_payload(result)}, 0
    elif view == "interactions":
        payload = {"computed": computed_of(result), **interactions_payload(result)}
        shown = len(payload["pairs"])
    elif view == "triples":
        payload = {"computed": computed_of(result), **triples_payload(result)}
        shown = len(payload["triples"])
    else:
        raise ValueError(f"{view!r} is not a view of the importance task")
    counted = scope_counts(
        frame,
        LabFilter(scope=request.filter.scope),
        shown,
        metric=request.metric or frame.objective,
        basis=importance_basis(result),
        unique=unique,
    )
    return envelope(
        view,
        {
            "task": status_json(task),
            "reason": reason,
            "snapshot_label": snapshot_label(result, frame.snapshot),
            **payload,
        },
        counted,
        filter_hash=request.filter_hash,
        snapshot=frame.snapshot,
        provisional=frame.provisional,
    )


def trial_detail(frame: TrialFrame, trial_no: int, trial_identity: dict) -> dict | None:
    """GET /lab/{src}/trials/{trial}: the canonical block-0 row of one trial number (None when the
    table has none), every scope's metrics with the trade Sharpe and its `low_n` flag (fewer than
    SHARPE_MIN_TRADES trades, or none known)."""
    table = frame.table
    hit = pc.and_(
        pc.equal(table.column("trial_no"), pa.scalar(trial_no, pa.int64())),
        pc.equal(table.column("block"), 0),
    )
    found = table.filter(hit)
    if not len(found):
        return None
    row = found.slice(0, 1).to_pylist()[0]
    paths = [p.path for p in frame.parameters]
    metrics = {}
    for scope in SCOPES:
        values: dict = {name: _number(row.get(f"{scope}.{name}")) for name in METRICS}
        trades = values["trade_count"]
        values["sharpe_trade"] = _number(row.get(f"{scope}.sharpe_trade"))
        values["low_n"] = trades is None or trades < SHARPE_MIN_TRADES
        metrics[scope] = values
    key, finished = row.get("param_key"), row.get("finished_at")
    return {
        "trial_id": f"{frame.source}#{trial_no}",
        "trial_no": trial_no,
        "cell": row.get("cell"),
        "params": {path: row.get(path) for path in paths},
        "pos": [row.get(f"pos.{k}") for k in range(len(paths))],
        "param_key": None if key is None else key.hex(),
        "status": row.get("status"),
        "attempt": row.get("attempt"),
        "block": row.get("block"),
        "pass": row.get("pass"),
        "design": row.get("design"),
        "metrics": metrics,
        "elapsed_ms": _number(row.get("elapsed_ms")),
        "engine": row.get("engine"),
        "chunk": row.get("chunk"),
        "finished_at": None if finished is None else finished.isoformat(),
        "identity": trial_identity,
    }


__all__ = [
    "ALL_BLOCKS",
    "BASE",
    "BLOCK0",
    "COLUMNS_FOR",
    "INDEXED_VIEWS",
    "TASK_VIEWS",
    "ExperimentMeta",
    "SourceRef",
    "cached_meta",
    "canonical_filter",
    "column_set",
    "experiment_identity",
    "experiment_importance",
    "experiment_index",
    "experiment_meta",
    "experiment_source",
    "experiment_unique",
    "matrix_payload_key",
    "open_experiment",
    "opt_frame",
    "optimization_identity",
    "optimization_importance",
    "optimization_source",
    "parse_source",
    "project",
    "run_query",
    "scheduled_uniform",
    "summary",
    "task_query",
    "trial_detail",
    "trial_number",
]
