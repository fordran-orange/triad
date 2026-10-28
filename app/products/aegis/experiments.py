"""Experiments (Mission 6 spec §5–6): a saved map of a strategy's control surface.

An experiment pins a strategy document's spec, data, settings, objective and surface; its plan
decides exhaustive or sampled; its cells run as the runner's third job kind in chunks on the
process pool, each chunk landing as one Parquet file under `experiments/<id>.cells/` before the
next starts, so an interrupted experiment pauses and resumes from the cells it already has.
Rows hold parameters and metrics, never envelopes; any cell can be materialized on demand into
an ordinary run whose hash proves it is the same computation.

Optimization Lab v2 (Phase 2): every new experiment is layout 2, whose chunks carry each trial's
number, grid positions, `param_key`, design, status and attempt beside the layout-1 columns, and
whose document records its search space, sampler, versions, pinned data and counts. A document
saved before stays layout 1 and is read and run as it always was; every layout-1 reader of a
layout-2 folder sees the layout-1 columns only (`_legacy_projection`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis import kernel
from products.aegis.backtest import (
    BacktestSettings,
    DataReference,
    _data_key,
    prepare_bars,
    prepared_request,
    run_prepared,
)
from products.aegis.lab import identity
from products.aegis.lab import store as lab_store
from products.aegis.optimize import provenance
from products.aegis.pool import (
    CURVE_POINTS,
    METRICS,
    SCOPES,
    Pool,
    default_workers,
    fitted_workers,
)
from products.aegis.results import envelope as run_envelope
from products.aegis.runs import RunRepository, _retry
from products.aegis.strategies import StrategyLibrary, slug
from products.aegis.strategy import StrategySpec
from products.aegis.surface import (
    KERNEL_MS_PER_BAR,
    Budget,
    Grid,
    Parameter,
    Plan,
    Surface,
    apply_params,
    build_grid,
    effective_workers,
)
from products.aegis.surface import plan as plan_surface

log = logging.getLogger("aegis")
CHUNK_CELLS = 200
CURVES_LIMIT = 20_000
PRICE_MIN_CELLS = 50  # a smaller experiment's cost is mostly its workers' cold first cells
Objective = Literal[
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
]
Status = Literal["queued", "running", "paused", "done", "cancelled", "failed"]
UNFINISHED = ("queued", "running", "paused")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    strategy_id: str
    data: DataReference
    settings: BacktestSettings = Field(default_factory=BacktestSettings)
    objective: Objective = "net_pnl"
    surface: Surface
    budget: Budget
    tolerance: float = Field(default=0.15, gt=0, le=1)
    seed: int = 1

    @field_validator("settings")
    @classmethod
    def plain_settings(cls, value: BacktestSettings) -> BacktestSettings:
        for name, clean in (
            ("evaluate_from", value.evaluate_from is None),
            ("initial_position", value.initial_position is None),
            ("close_at_end", value.close_at_end),
        ):
            if not clean:
                raise ValueError(f"settings.{name} is set by the experiment itself; leave it unset")
        return value


class ExperimentDocument(BaseModel):
    """The persisted experiment: definition, plan, status, progress, reports and the decision.
    Runner fields (job_id, units, elapsed) ride along on the same file."""

    id: str
    name: str
    strategy_id: str
    strategy_hash: str
    spec: StrategySpec
    data: DataReference
    settings: BacktestSettings
    objective: Objective
    surface: Surface
    budget: Budget
    tolerance: float
    seed: int
    plan: dict
    status: Status
    progress: dict
    ms_per_cell_bar: float | None = None
    engine: str = "kernel"
    created_at: str
    updated_at: str
    parent: str | None = None
    decision: dict | None = None
    reports: list[dict] = Field(default_factory=list)
    latest_report: int | None = None
    job_id: str | None = None
    error: str | None = None
    first_pass_cells: list[int] | None = None
    refinement_cells: list[int] | None = None
    workers: int = 1
    chunk_cells: int = CHUNK_CELLS
    # Optimization Lab v2 (Phase 2), written for every new experiment; a document saved before
    # has none of them and validates as layout 1 with the rest None.
    cells_layout: int = 1
    search_space: dict | None = None
    sampler: dict | None = None
    versions: dict | None = None
    data_pinned: dict | None = None
    execution: dict | None = None
    counts: dict | None = None
    lineage: dict | None = None


# --- storage ---------------------------------------------------------------------------------


def _cells_schema(paths: list[str]) -> pa.Schema:
    fields = [
        pa.field("cell", pa.int64()),
        pa.field("pass", pa.string()),
        pa.field("valid", pa.bool_()),
        pa.field("skip_reason", pa.string()),
    ]
    fields += [pa.field(path, pa.float64()) for path in paths]
    fields += [
        pa.field(f"{scope}.{metric}", pa.float64()) for scope in SCOPES for metric in METRICS
    ]
    fields += [pa.field("elapsed_ms", pa.float64()), pa.field("engine", pa.string())]
    return pa.schema(fields)


def _cells_table(rows: list[dict], paths: list[str]) -> pa.Table:
    columns: dict[str, list] = {
        "cell": [r["cell"] for r in rows],
        "pass": [r.get("pass", "grid") for r in rows],
        "valid": [bool(r["valid"]) for r in rows],
        "skip_reason": [r["skip_reason"] for r in rows],
    }
    for path in paths:
        columns[path] = [float(r["params"][path]) for r in rows]
    for scope in SCOPES:
        for metric in METRICS:
            columns[f"{scope}.{metric}"] = [
                None
                if r["metrics"] is None or r["metrics"][scope][metric] is None
                else float(r["metrics"][scope][metric])
                for r in rows
            ]
    columns["elapsed_ms"] = [float(r["elapsed_ms"]) for r in rows]
    columns["engine"] = [r.get("engine") for r in rows]
    return pa.table(columns, schema=_cells_schema(paths))


# Layout 2 (Optimization Lab v2 spec §9.2). The few distinct strings of a column are stored once
# per chunk; `elapsed_ms` stays float64 as layout 1 stores it, so a promoted legacy value never
# casts (decision 13).
TRIAL_NO = "trial_no"
WRITE_MS = "aegis.write_ms"  # a layout-2 chunk's write time, in its Parquet key-value metadata
_WORDS = pa.dictionary(pa.int32(), pa.string())
_REUSED_FROM = pa.struct([pa.field("experiment", pa.string()), pa.field("trial_no", pa.int64())])


def _cells_schema_v2(paths: list[str]) -> pa.Schema:
    """The trial's number, grid positions and identity first, then the layout-1 columns with the
    status and attempt, the trade Sharpe after the metrics, the chunk and commit time last."""
    fields = [pa.field(TRIAL_NO, pa.int64()), pa.field("cell", pa.int64())]
    fields += [pa.field(f"pos.{k}", pa.uint16()) for k in range(len(paths))]
    fields += [pa.field(path, pa.float64()) for path in paths]
    fields += [
        pa.field("param_key", pa.binary(16)),
        pa.field("pass", _WORDS),
        pa.field("design", _WORDS),
        pa.field("block", pa.uint8()),
        pa.field("reused_from", _REUSED_FROM),
        pa.field("status", _WORDS),
        pa.field("valid", pa.bool_()),
        pa.field("skip_reason", pa.string()),
        pa.field("error", pa.string()),
        pa.field("attempt", pa.uint8()),
    ]
    fields += [
        pa.field(f"{scope}.{metric}", pa.float64()) for scope in SCOPES for metric in METRICS
    ]
    fields += [pa.field(f"{scope}.sharpe_trade", pa.float64()) for scope in SCOPES]
    fields += [
        pa.field("elapsed_ms", pa.float64()),
        pa.field("engine", _WORDS),
        pa.field("chunk", pa.int32()),
        pa.field("finished_at", pa.timestamp("ms", tz="UTC")),
    ]
    return pa.schema(fields)


def _status_of(row: dict) -> str:
    """`failed` when the evaluation raised (a row carrying `error`), `invalid` when the cell was
    skipped, else `ok`."""
    if row.get("error") is not None:
        return "failed"
    if row.get("skip_reason") is not None or not row.get("valid", True):
        return "invalid"
    return "ok"


def _sharpe_trade(row: dict, scope: str) -> float | None:
    value = ((row.get("lab_metrics") or {}).get(scope) or {}).get("sharpe_trade")
    return None if value is None else float(value)


def _cells_table_v2(
    rows: list[dict],
    grid: Grid,
    spec: StrategySpec,
    steps: Mapping[str, float],
    schedule: Schedule | None,
    chunk: int,
    finished_at: datetime,
) -> pa.Table:
    """One layout-2 chunk. Trial numbers come from `schedule`, or, with None (fixtures and
    synthetic documents, which have no schedule to number from), from each row's `trial_no`.
    `attempt` and `error` are read from the row when it carries them (the job's rows carry
    neither in Phase 2)."""
    paths = grid.paths
    statuses = [_status_of(r) for r in rows]
    passes = [r.get("pass", "grid") for r in rows]
    positions = [grid.positions(r["cell"]) for r in rows]
    columns: dict[str, list] = {
        TRIAL_NO: [
            int(r[TRIAL_NO]) if schedule is None else schedule.trial_no_of(r["cell"]) for r in rows
        ],
        "cell": [r["cell"] for r in rows],
    }
    for k in range(len(paths)):
        columns[f"pos.{k}"] = [p[k] for p in positions]
    for path in paths:
        columns[path] = [float(r["params"][path]) for r in rows]
    columns["param_key"] = [identity.param_key(spec, r["params"], steps) for r in rows]
    columns["pass"] = passes
    columns["design"] = [identity.design_of(label) for label in passes]
    columns["block"] = [0] * len(rows)  # no screening blocks in Phase 2
    columns["reused_from"] = [None] * len(rows)  # no reuse by value in Phase 2
    columns["status"] = statuses
    columns["valid"] = [status == "ok" for status in statuses]
    columns["skip_reason"] = [r.get("skip_reason") for r in rows]
    columns["error"] = [r.get("error") for r in rows]
    columns["attempt"] = [r.get("attempt", 0) for r in rows]
    for scope in SCOPES:
        for metric in METRICS:
            columns[f"{scope}.{metric}"] = [
                None
                if r.get("metrics") is None or r["metrics"][scope][metric] is None
                else float(r["metrics"][scope][metric])
                for r in rows
            ]
    for scope in SCOPES:
        columns[f"{scope}.sharpe_trade"] = [_sharpe_trade(r, scope) for r in rows]
    columns["elapsed_ms"] = [float(r["elapsed_ms"]) for r in rows]
    columns["engine"] = [r.get("engine") for r in rows]
    columns["chunk"] = [chunk] * len(rows)
    columns["finished_at"] = [finished_at] * len(rows)
    return pa.table(columns, schema=_cells_schema_v2(paths))


def _legacy_projection(table: pa.Table, paths: list[str]) -> pa.Table:
    """A layout-2 table as layout-1 code reads it: the `_cells_schema` columns only, with plain
    strings for `pass` and `engine`. `analysis._paths_of` takes every column outside its
    reserved set for a parameter, and GET /experiments/{id}/cells would hand a `param_key`'s
    bytes to the JSON encoder, so neither ever sees a layout-2 column."""
    schema = _cells_schema(paths)
    return table.select(schema.names).cast(schema)


def _curves_table(rows: list[dict]) -> pa.Table:
    return pa.table(
        {
            "cell": pa.array([r["cell"] for r in rows], pa.int64()),
            "first_time": pa.array([r["first_time"] for r in rows], pa.string()),
            "last_time": pa.array([r["last_time"] for r in rows], pa.string()),
            "equity": pa.array([r["curve"] for r in rows], pa.list_(pa.float32())),
        }
    )


def _write_atomic(path: Path, table: pa.Table, *, stamp_write_ms: bool = False) -> None:
    """Written beside its name as `.tmp`, then swapped in. With `stamp_write_ms` (a layout-2
    chunk) the file's key-value metadata carries `aegis.write_ms`, the write up to the footer
    that holds it; the swap is not in it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if stamp_write_ms:
        started = time.perf_counter()
        with pq.ParquetWriter(tmp, table.schema) as writer:
            writer.write_table(table)
            elapsed = (time.perf_counter() - started) * 1000
            writer.add_key_value_metadata({WRITE_MS: f"{elapsed:.3f}"})
    else:
        pq.write_table(table, tmp)
    _retry(lambda: tmp.replace(path))  # Windows refuses the swap while a reader holds the file


def _readable(folder: Path) -> list[Path]:
    """The chunk files that parse; a torn write is a leftover `.tmp` and is never listed, and a
    file not named by a chunk index (a compacted part) is never a chunk."""
    files = []
    for path in sorted(folder.glob("[0-9]*.parquet")):
        try:
            pq.read_metadata(path)
        except Exception as exc:  # noqa: BLE001 - an unreadable chunk is rerun, never trusted
            log.warning("experiment chunk %s unreadable, its cells will rerun: %s", path.name, exc)
            continue
        files.append(path)
    return files


class ExperimentStore:
    """Documents on the repository; cells, curves and reports as files beside them."""

    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    # -- documents ----------------------------------------------------------------------------
    def save(self, document: ExperimentDocument) -> None:
        self.repository.save_experiment(document.model_dump(mode="json"))

    def get(self, experiment_id: str) -> ExperimentDocument:
        try:
            return ExperimentDocument.model_validate(self.repository.get_experiment(experiment_id))
        except ValueError as exc:  # an identifier the repository refuses is simply unknown
            raise KeyError(experiment_id) from exc

    def list(self) -> list[dict]:
        return self.repository.list_experiments()

    def free_id(self, name: str) -> str:
        base = slug(name)
        taken = {item.get("id") for item in self.list()}
        # Ids in Recently deleted stay reserved until Empty (Mission 9 plan ruling P4).
        trashed = getattr(self.repository, "trashed_ids", None)
        taken |= trashed("experiments") if trashed is not None else set()
        if base not in taken:
            return base
        digest = hashlib.sha256(f"{name}|{_now()}".encode()).hexdigest()
        candidate = f"{base}-{digest[:6]}"
        while candidate in taken:
            digest = hashlib.sha256(digest.encode()).hexdigest()
            candidate = f"{base}-{digest[:6]}"
        return candidate

    def last_ms_per_cell_bar(self) -> float | None:
        """The newest finished experiment's measured cost per cell-bar on this host, preferring
        experiments of at least PRICE_MIN_CELLS cells: a tiny one is priced by its workers' cold
        first cells and would inflate the next plan tenfold (QA observation 1)."""
        finished = [
            s for s in self.list() if s.get("status") == "done" and s.get("ms_per_cell_bar")
        ]
        finished.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        sized = [
            s for s in finished if (s.get("progress") or {}).get("cells_done", 0) >= PRICE_MIN_CELLS
        ]
        chosen = sized or finished
        return float(chosen[0]["ms_per_cell_bar"]) if chosen else None

    def delete(self, experiment_id: str) -> None:
        self.repository.delete_experiment(experiment_id)

    # -- cells and curves ---------------------------------------------------------------------
    def cells_dir(self, experiment_id: str) -> Path:
        return self.repository.experiment_dir(experiment_id, "cells")

    def curves_dir(self, experiment_id: str) -> Path:
        return self.repository.experiment_dir(experiment_id, "curves")

    def chunk_count(self, experiment_id: str) -> int:
        return len(_readable(self.cells_dir(experiment_id)))

    def layout(self, experiment_id: str) -> int:
        """2 when the cells folder holds a manifest or a chunk with the layout-2 columns, else 1.
        Decided by the files, never by the manifest alone, so a folder restored to chunks keeps
        its layout; a legacy folder's chunks have no `trial_no`."""
        folder = self.cells_dir(experiment_id)
        if (folder / lab_store.MANIFEST).is_file():
            return 2
        if any(TRIAL_NO in pq.read_schema(path).names for path in _readable(folder)):
            return 2
        return 1

    def init_layout2(self, experiment_id: str) -> None:
        """The generation-0 manifest of a new layout-2 experiment, written before its document."""
        lab_store.write_manifest(
            self.cells_dir(experiment_id),
            lab_store.Manifest(
                layout=2,
                generation=0,
                parts=[],
                merged_chunks=[],
                generations=[],
                chunk_watermark=-1,
                unique=None,
                unique_generation=None,
                updated_at=_now(),
            ),
        )

    def next_chunk_index(self, experiment_id: str) -> int:
        """F16: one past the highest chunk index the folder (or its manifest) has used."""
        folder = self.cells_dir(experiment_id)
        return lab_store.next_chunk_index(folder, lab_store.read_manifest(folder))

    def done_cells(self, experiment_id: str) -> set[int]:
        done: set[int] = set()
        for path in _readable(self.cells_dir(experiment_id)):
            done.update(pq.read_table(path, columns=["cell"]).column("cell").to_pylist())
        return done

    def write_chunk(
        self,
        experiment_id: str,
        chunk_index: int,
        rows: list[dict],
        paths: list[str],
        table: pa.Table | None = None,
    ) -> None:
        """One chunk: `table` as given (layout 2, its write time stamped in the file), else the
        layout-1 table of `rows`; the rows' curves beside it under the same name."""
        name = f"{chunk_index:06d}.parquet"
        if table is None:
            _write_atomic(self.cells_dir(experiment_id) / name, _cells_table(rows, paths))
        else:
            _write_atomic(self.cells_dir(experiment_id) / name, table, stamp_write_ms=True)
        curved = [r for r in rows if r.get("curve") is not None]
        if curved:
            _write_atomic(self.curves_dir(experiment_id) / name, _curves_table(curved))

    def cells(self, experiment_id: str) -> pa.Table | None:
        """Every readable chunk in layout-1 columns, by cell; a layout-2 folder's chunks are
        projected (`_legacy_projection`) over its document's surface paths."""
        files = _readable(self.cells_dir(experiment_id))
        if not files:
            return None
        table = pa.concat_tables([pq.read_table(path) for path in files])
        if TRIAL_NO in table.column_names:
            table = _legacy_projection(table, self.get(experiment_id).surface.paths())
        return table.sort_by("cell")

    def trials(
        self,
        experiment_id: str,
        columns: Sequence[str] | None = None,
        *,
        snapshot: lab_store.Snapshot | None = None,
    ) -> lab_store.TrialTable | None:
        """The full layout-2 column set for the Lab routes; a given `snapshot` is read as is, so
        a route reads the manifest once per request. The reader arrives in Task 5."""
        raise NotImplementedError("ExperimentStore.trials needs the layout-2 reader (Task 5)")

    def row(self, experiment_id: str, cell: int) -> dict:
        table = self.cells(experiment_id)
        if table is not None:
            mask = pa.compute.equal(table.column("cell"), pa.scalar(cell, pa.int64()))
            found = table.filter(mask)
            if len(found):
                return found.to_pylist()[0]
        raise KeyError(cell)

    def write_curves(self, experiment_id: str, chunk_index: int, rows: list[dict]) -> None:
        curved = [r for r in rows if r.get("curve") is not None]
        if curved:
            name = f"{chunk_index:06d}.parquet"
            _write_atomic(self.curves_dir(experiment_id) / name, _curves_table(curved))

    # -- reports ------------------------------------------------------------------------------
    def report_path(self, experiment_id: str, n: int, suffix: str = "json") -> Path:
        # A folder of its own: the repository lists `experiments/*.json` as documents, so a
        # report must never sit beside them as a loose JSON file.
        return self.repository.experiment_dir(experiment_id, "reports") / f"{n}.{suffix}"

    def write_report(self, experiment_id: str, n: int, report: dict, markdown: str) -> None:
        path = self.report_path(experiment_id, n)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(report, allow_nan=False), encoding="utf-8")
        tmp.replace(path)
        md = self.report_path(experiment_id, n, "md")
        md_tmp = md.with_name(md.name + ".tmp")
        md_tmp.write_text(markdown, encoding="utf-8")
        md_tmp.replace(md)

    def read_report(self, experiment_id: str, n: int) -> dict:
        path = self.report_path(experiment_id, n)
        if not path.is_file():
            raise KeyError(n)
        return json.loads(path.read_text(encoding="utf-8"))

    def read_markdown(self, experiment_id: str, n: int) -> str:
        path = self.report_path(experiment_id, n, "md")
        if not path.is_file():
            raise KeyError(n)
        return path.read_text(encoding="utf-8")

    def curves(self, experiment_id: str, cells: Iterable[int]) -> dict[int, list[float]]:
        wanted = set(cells)
        out: dict[int, list[float]] = {}
        for path in _readable(self.curves_dir(experiment_id)):
            table = pq.read_table(path)
            for record in table.to_pylist():
                if record["cell"] in wanted:
                    out[record["cell"]] = [float(v) for v in record["equity"]]
        return out


# --- creation --------------------------------------------------------------------------------


POSITION_MAX = 65_535  # a layout-2 `pos.<k>` is a uint16 grid position


def _check_positions(surface: Surface) -> None:
    """Refuse a surface whose value positions a layout-2 chunk cannot hold, before anything is
    planned or saved (a ValueError, as every other refusal of `create`)."""
    for parameter in surface.parameters:
        count = len(parameter.values())
        if count > POSITION_MAX:
            raise ValueError(
                f"parameter {parameter.path} has {count} values; "
                f"a layout-2 position holds at most {POSITION_MAX}"
            )


def _layout2_fields(
    spec: StrategySpec,
    surface: Surface,
    planned: Plan,
    seed: int,
    strategy_hash: str,
    pinned: Any | None,
    engine_build: str | None,
) -> dict:
    """The layout-2 fields of a new experiment, from its own surface and plan. `create` holds no
    grid and no sample yet, so the schedule is the plan's: every valid cell when exhaustive (where
    `first_pass == valid_cells`), else the planned first pass, which the job replaces with the
    count it draws."""
    versions = identity.versions(strategy_hash)
    if engine_build is not None:  # the worker's, computed at its start
        versions["engine_build"] = engine_build
    scheduled = planned.valid_cells if planned.mode == "exhaustive" else planned.first_pass
    counts = lab_store.Counters(scheduled=scheduled, budget_total=planned.planned_runs)
    return {
        "cells_layout": 2,
        "search_space": identity.search_space(spec, surface),
        "sampler": identity.sampler(planned.model_dump(mode="json"), seed),
        "versions": versions,
        "data_pinned": None if pinned is None else provenance(pinned),
        "execution": {
            "commission_per_side": spec.execution.commission_per_side,
            "slippage_bps": spec.execution.slippage_bps,
        },
        "counts": counts.as_dict(),
    }


def create(
    store: ExperimentStore,
    library: StrategyLibrary,
    request: ExperimentRequest,
    bars: int,
    max_workers: int,
    timeframe: str | None = None,
    *,
    pinned: Any | None = None,
    engine_build: str | None = None,
) -> ExperimentDocument:
    """Plan and save a queued experiment pinned to the strategy document's current spec: a
    layout-2 experiment recording its search space, sampler, versions (with `engine_build` when
    given, the worker's) and, when given, the data it was pinned to."""
    document = library.get(request.strategy_id)  # KeyError when unknown
    _check_positions(request.surface)
    spec = document.spec
    measured = store.last_ms_per_cell_bar()
    planned = plan_surface(
        spec,
        request.surface,
        request.budget,
        bars,
        measured or KERNEL_MS_PER_BAR,
        max_workers,
        timeframe,
        price_source="measured" if measured else "starting_guess",
    )
    now = _now()
    chunk = CHUNK_CELLS
    experiment_id = store.free_id(request.name)
    experiment = ExperimentDocument(
        id=experiment_id,
        name=request.name,
        strategy_id=document.id,
        strategy_hash=document.strategy_hash,
        spec=spec,
        data=request.data,
        settings=request.settings,
        objective=request.objective,
        surface=request.surface,
        budget=request.budget,
        tolerance=request.tolerance,
        seed=request.seed,
        plan=planned.model_dump(mode="json"),
        status="queued",
        progress={
            "cells_done": 0,
            "cells_planned": planned.planned_runs,
            "chunks_done": 0,
            "chunks_total": math.ceil(planned.first_pass / chunk)
            + math.ceil(planned.refinement / chunk),
        },
        engine="kernel" if kernel.AVAILABLE else "reference",
        created_at=now,
        updated_at=now,
        workers=max_workers,
        chunk_cells=chunk,
        **_layout2_fields(
            spec,
            request.surface,
            planned,
            request.seed,
            document.strategy_hash,
            pinned,
            engine_build,
        ),
        lineage={"parent": None, "root": experiment_id},
    )
    store.init_layout2(experiment.id)
    store.save(experiment)
    return experiment


# --- the job kind ----------------------------------------------------------------------------


def _chunks(cells: list[int], size: int) -> list[list[int]]:
    return [cells[i : i + size] for i in range(0, len(cells), size)]


class Schedule:
    """Each scheduled cell's trial number (layout 2). Exhaustive: the cell itself on a grid
    without skipped cells, else its rank among the valid cells. Sampled: its position in
    `first_pass_cells + refinement_cells`. Held as sorted numpy arrays, never as a dict of a
    million ints."""

    def __init__(self, cells: np.ndarray | None, numbers: np.ndarray | None, size: int) -> None:
        self._cells = cells  # sorted; None for the identity over range(size)
        self._numbers = numbers  # the trial number at each sorted position; None for the rank
        self._size = size

    @classmethod
    def exhaustive(cls, grid: Grid) -> Schedule:
        if grid.skipped_count == 0:
            return cls(None, None, grid.size)
        valid = np.fromiter(grid.valid_indices_iter(), dtype=np.int64, count=grid.valid_count)
        return cls(valid, None, grid.valid_count)

    @classmethod
    def of(cls, cells: Sequence[int]) -> Schedule:
        listed = np.asarray(cells, dtype=np.int64)
        order = np.argsort(listed, kind="stable")
        return cls(listed[order], order.astype(np.int64), len(listed))

    @classmethod
    def from_document(cls, document: ExperimentDocument) -> Schedule:
        """A reader's schedule. The grid is built on the bars the plan counted (`Plan.bars`),
        which the writer's grid used too, so the skipped set and the ranks agree with the chunks;
        a grid built without bars has another skipped set and must never number trials."""
        if document.plan["mode"] == "exhaustive":
            grid = build_grid(document.spec, document.surface, document.plan["bars"])
            return cls.exhaustive(grid)
        return cls.of([*(document.first_pass_cells or []), *(document.refinement_cells or [])])

    def trial_no_of(self, cell: int) -> int:
        """The cell's trial number; KeyError for a cell the schedule does not hold."""
        if self._cells is None:
            if 0 <= cell < self._size:
                return int(cell)
            raise KeyError(cell)
        position = int(np.searchsorted(self._cells, cell))
        if position >= len(self._cells) or int(self._cells[position]) != cell:
            raise KeyError(cell)
        return position if self._numbers is None else int(self._numbers[position])


class ExperimentJob:
    """The runner's third kind (spec §6.1): a unit is a chunk of cells on the pool; every
    committed chunk is a Parquet file; pause and resume continue from the cells on disk."""

    name = "experiment"
    side = "both"
    resumable = True
    bars_per_unit = 0

    def __init__(
        self,
        document: ExperimentDocument,
        bars: list[dict] | pd.DataFrame,
        pinned: Any,
        repository: RunRepository,
        max_workers: int | None = None,
    ) -> None:
        self.document = document.model_copy()
        # Mission 10: one prepared frame (an archive frame, or supplied rows as given).
        self.frame = prepare_bars(bars, document.data.symbol)
        self.pinned = provenance(pinned)
        self.repository = repository
        self.store = ExperimentStore(repository)
        self.bars = len(self.frame)
        self.grid = build_grid(document.spec, document.surface, self.bars)
        self.workers = fitted_workers(
            self.bars, max_workers or document.workers or default_workers()
        )
        self.chunk = document.chunk_cells or CHUNK_CELLS
        self.keep_curves = document.plan["planned_runs"] <= CURVES_LIMIT
        # Layout 2 numbers its trials and keeps its counts; a legacy experiment runs as before.
        self.layout = self.store.layout(document.id)
        self.steps = {p.path: p.step for p in document.surface.parameters}
        self.counters = lab_store.Counters.from_document(document)
        if self.layout == 2:
            self._recount_counters()
        done = self.store.done_cells(document.id)
        self.cells_done = len(done)
        self.chunks_done = self.store.chunk_count(document.id)
        self.first_pass_units = 0
        self.units: list[list[int] | None] = self._units(done)
        self.schedule = self._schedule() if self.layout == 2 else None
        self.total_units = len(self.units)
        self.units_done = 0
        self.pause_requested = False
        self.pool: Pool | None = None
        self.status: str = "queued"
        self.ms_per_cell_bar = document.ms_per_cell_bar

    def _recount_counters(self) -> None:
        """`attempted`, `completed`, `invalid` and `failed` from the trials on disk, the rows of
        the readable chunks `done_cells` reads: those never rerun, and an unreadable chunk adds
        nothing, so its trials rerun and are counted once. Every start and resume recounts, so a
        lost or torn chunk, or a crash before the document's last save, never skews the counts."""
        statuses: list[str] = []
        for path in _readable(self.store.cells_dir(self.document.id)):
            statuses += pq.read_table(path, columns=["status"]).column("status").to_pylist()
        self.counters.recount(statuses)
        self.document = self.document.model_copy(update={"counts": self.counters.as_dict()})

    # -- planning the units ---------------------------------------------------------------
    def _valid_indices(self) -> Iterable[int]:
        if self.grid.skipped_count == 0:
            return range(self.grid.size)
        return self.grid.valid_indices_iter()

    def _units(self, done: set[int]) -> list[list[int] | None]:
        plan = self.document.plan
        if plan["mode"] == "exhaustive":
            pending = [i for i in self._valid_indices() if i not in done]
            units: list[list[int] | None] = list(_chunks(pending, self.chunk))
            self.first_pass_units = len(units)
            return units
        first = self.document.first_pass_cells
        if first is None:
            first = self._sample_first_pass()
            self._scheduled_first_pass(first)
        pending_first = [i for i in first if i not in done]
        units = list(_chunks(pending_first, self.chunk))
        self.first_pass_units = len(units)
        if self.document.refinement_cells is not None:
            pending_refinement = [i for i in self.document.refinement_cells if i not in done]
            units += list(_chunks(pending_refinement, self.chunk))
        else:
            units += [None] * math.ceil(plan["refinement"] / self.chunk)
        return units

    def _sample_first_pass(self) -> list[int]:
        from products.aegis.surface import latin_hypercube  # Task 4

        return latin_hypercube(self.grid, self.document.plan["first_pass"], self.document.seed)

    def _scheduled_first_pass(self, first: list[int]) -> None:
        """Take a fresh draw as the first pass. `latin_hypercube` may draw fewer cells than the
        plan asked for (its tries are bounded on a sparse grid), so the drawn count is the
        schedule; a layout-2 document is saved at once, before any chunk carries a trial number
        it cannot explain."""
        planned = self.document.plan["first_pass"]
        if len(first) != planned:
            log.warning("experiment %s: LHS drew %d of %d", self.document.id, len(first), planned)
        update: dict[str, Any] = {"first_pass_cells": first}
        if self.layout == 2:
            self.counters.scheduled = len(first)
            update["counts"] = self.counters.as_dict()
        self.document = self.document.model_copy(update=update)
        if self.layout == 2:
            self._save_schedule()

    def _schedule(self) -> Schedule:
        """Numbered over the grid this job runs, the one that decided which cells are valid."""
        if self.document.plan["mode"] == "exhaustive":
            return Schedule.exhaustive(self.grid)
        return Schedule.of(
            [*(self.document.first_pass_cells or []), *(self.document.refinement_cells or [])]
        )

    def _save_schedule(self) -> None:
        """Write the schedule and counts onto the stored document now. The stored copy is
        updated, not replaced, so the runner's fields on it (its job_id, which a pause reads, and
        the status) stay until its own next save."""
        self.document = self.document.model_copy(update={"updated_at": _now()})
        fields = ("first_pass_cells", "refinement_cells", "counts", "updated_at")
        update = {key: getattr(self.document, key) for key in fields}
        try:
            stored = self.repository.get_experiment(self.document.id)
        except KeyError:  # never saved: this document is the whole of it
            stored = self.document.model_dump(mode="json")
        self.repository.save_experiment({**stored, **update})

    def _decide_refinement(self) -> None:
        """Choose the refinement cells from the first pass (spec §5.4); plan ruling P3."""
        from products.aegis.analysis import analyse  # Task 5
        from products.aegis.surface import refinement_cells  # Task 4

        table = self.store.cells(self.document.id)
        report = analyse(
            table,
            self.grid,
            self.document.objective,
            self.document.tolerance,
            "sampled",
            self.document.seed,
            self._data_label(),
        )
        budget = self.document.plan["refinement"]
        column = f"combined.{self.document.objective}"
        sign = -1.0 if self.document.objective == "max_drawdown" else 1.0
        run_cells = {
            cell: (None if value is None else sign * float(value))
            for cell, value in zip(
                table.column("cell").to_pylist(), table.column(column).to_pylist(), strict=True
            )
        }
        chosen = refinement_cells(self.grid, run_cells, report["plateaus"], budget)
        chunks = list(_chunks(chosen, self.chunk))
        for k in range(self.first_pass_units, self.total_units):
            offset = k - self.first_pass_units
            self.units[k] = chunks[offset] if offset < len(chunks) else []
        self.document = self.document.model_copy(update={"refinement_cells": chosen})
        if self.layout == 2:  # on disk before the first refinement chunk is numbered by it
            self.counters.scheduled += len(chosen)
            self.document = self.document.model_copy(update={"counts": self.counters.as_dict()})
            self.schedule = self._schedule()
            self._save_schedule()

    def _data_label(self) -> str:
        d = self.document.data
        return f"{d.symbol} {d.timeframe} {d.start} → {d.end}"

    def pending_cells(self) -> list[int]:
        return [i for unit in self.units if unit for i in unit]

    # -- units ------------------------------------------------------------------------------
    def _start_pool(self) -> None:
        self.pool = Pool(self.workers)
        self.pool.start(
            self.frame,
            self.document.data.symbol,
            self.document.spec.model_dump(mode="json"),
            self.document.settings.model_dump(mode="json"),
        )

    def run_unit(self, index: int) -> dict:
        if self.pool is None:
            self._start_pool()
        self.status = "running"
        cells = self.units[index]
        if cells is None:
            self._decide_refinement()
            cells = self.units[index] or []
        if self.document.plan["mode"] == "exhaustive":
            label = "grid"
        else:
            label = "sample" if index < self.first_pass_units else "refine"
        rows = (
            self.pool.run_chunk(
                [(i, self.grid.cell_values(i)) for i in cells], want_curve=self.keep_curves
            )
            if cells
            else []
        )
        for row in rows:
            row["pass"] = label
        return {"rows": rows}

    def commit(self, index: int, result: dict) -> None:
        rows = result["rows"]
        if rows:
            # F16: named one past the highest index used, so no file on disk is overwritten
            chunk = self.store.next_chunk_index(self.document.id)
            table = None
            if self.layout == 2:
                table = _cells_table_v2(
                    rows,
                    self.grid,
                    self.document.spec,
                    self.steps,
                    self.schedule,
                    chunk,
                    datetime.now(UTC),
                )
            self.store.write_chunk(self.document.id, chunk, rows, self.grid.paths, table=table)
            self.cells_done += len(rows)
            if self.layout == 2:
                self._count(rows)
        self.chunks_done += 1
        self.units_done += 1
        if self.pool is not None and self.pool.mean_ms_per_cell_bar:
            self.ms_per_cell_bar = self.pool.mean_ms_per_cell_bar
        engine = next((r["engine"] for r in rows if r.get("engine")), self.document.engine)
        update: dict[str, Any] = {
            "progress": self._progress(),
            "ms_per_cell_bar": self.ms_per_cell_bar,
            "status": self.status,
            "engine": engine,
            "updated_at": _now(),
        }
        if self.layout == 2:
            update["counts"] = self.counters.as_dict()
        self.document = self.document.model_copy(update=update)

    def _count(self, rows: list[dict]) -> None:
        self.counters.tally(_status_of(row) for row in rows)

    def _progress(self) -> dict:
        return {
            "cells_done": self.cells_done,
            "cells_planned": self.document.plan["planned_runs"],
            "chunks_done": self.chunks_done,
            "chunks_total": self.document.progress["chunks_total"],
        }

    def snapshot(self) -> dict:
        remaining = max(self.document.plan["planned_runs"] - self.cells_done, 0)
        price = self.ms_per_cell_bar or self.document.plan["ms_per_cell_bar"]
        estimate = remaining * self.bars * price / 1000.0 / effective_workers(self.workers)
        document = self.document.model_dump(mode="json")
        document.pop("job_id", None)  # the runner's
        document.pop("error", None)
        return {
            **document,
            "status": self.status,
            "progress": self._progress(),
            "units": {"done": self.units_done, "total": self.total_units},
            "ms_per_cell_bar": self.ms_per_cell_bar,
            "ms_per_bar": None,
            "estimated_seconds": round(estimate, 3),
        }

    def finalize(self, status: str) -> dict:
        mapped = "paused" if status == "cancelled" and self.pause_requested else status
        self.status = mapped
        update: dict[str, Any] = {
            "status": mapped,
            "progress": self._progress(),
            "updated_at": _now(),
        }
        if mapped in ("done", "cancelled") and self.cells_done:
            report = self._write_report(1, self.document.objective, self.document.tolerance, mapped)
            entry = {
                "report_id": 1,
                "objective": report["objective"],
                "tolerance": report["tolerance"],
                "generated_at": report["generated_at"],
            }
            update["reports"] = [entry]
            update["latest_report"] = 1
        self.document = self.document.model_copy(update=update)
        return {"status": mapped}

    def _write_report(self, n: int, objective: str, tolerance: float, status: str) -> dict:
        """Analyse the cells on disk into report `n`; for a large experiment, also fetch the
        curves of the cells the report names through the pool (plan ruling P7)."""
        from products.aegis.analysis import analyse, render_markdown

        table = self.store.cells(self.document.id)
        report = analyse(
            table,
            self.grid,
            objective,
            tolerance,
            self.document.plan["mode"],
            self.document.seed,
            self._data_label(),
        )
        if status == "cancelled":
            report["statement"] = (
                f"cancelled before completion ({self.cells_done} of "
                f"{self.document.plan['planned_runs']} cells); " + report["statement"]
            )
        report["report_id"] = n
        report["generated_at"] = _now()
        if not self.keep_curves and self.pool is not None and report["cells_named"]:
            have = set(self.store.curves(self.document.id, report["cells_named"]))
            missing = [c for c in report["cells_named"] if c not in have]
            if missing:
                rows = self.pool.run_chunk(
                    [(i, self.grid.cell_values(i)) for i in missing], want_curve=True
                )
                self.store.write_curves(self.document.id, 900_000 + n, rows)
        self.store.write_report(self.document.id, n, report, render_markdown(report))
        return report

    def release(self) -> None:
        if self.pool is not None:
            self.pool.shutdown()
            self.pool = None
        self.frame = self.frame.iloc[0:0]


# --- reports, decision, refine ---------------------------------------------------------------


def recompute_report(
    store: ExperimentStore,
    document: ExperimentDocument,
    objective: str | None = None,
    tolerance: float | None = None,
) -> tuple[ExperimentDocument, dict]:
    """Another report from the stored cells, kept beside the earlier ones (spec §8.1)."""
    from products.aegis.analysis import analyse, render_markdown
    from products.aegis.surface import build_grid

    table = store.cells(document.id)
    if table is None:
        raise ValueError("no cells to analyse")
    objective = objective or document.objective
    tolerance = document.tolerance if tolerance is None else tolerance
    grid = build_grid(document.spec, document.surface)
    d = document.data
    report = analyse(
        table,
        grid,
        objective,
        tolerance,
        document.plan["mode"],
        document.seed,
        f"{d.symbol} {d.timeframe} {d.start} → {d.end}",
    )
    n = (document.latest_report or 0) + 1
    while n in {r["report_id"] for r in document.reports}:
        n += 1
    report["report_id"] = n
    report["generated_at"] = _now()
    store.write_report(document.id, n, report, render_markdown(report))
    entry = {
        "report_id": n,
        "objective": objective,
        "tolerance": tolerance,
        "generated_at": report["generated_at"],
    }
    updated = document.model_copy(
        update={
            "reports": [*document.reports, entry],
            "latest_report": n,
            "updated_at": _now(),
        }
    )
    store.save(updated)
    return updated, report


def cancel_idle(store: ExperimentStore, document: ExperimentDocument) -> ExperimentDocument:
    """Cancel a queued or paused experiment that has no live job (review finding 1): the status
    is written here and, when cells exist and no report does, report 1 is computed from them,
    as finalize does when a running job is cancelled."""
    cancelled = document.model_copy(update={"status": "cancelled", "updated_at": _now()})
    store.save(cancelled)
    if cancelled.latest_report is None and store.done_cells(document.id):
        try:
            cancelled, _ = recompute_report(store, cancelled)
        except ValueError as exc:  # nothing to rank: the cancellation stands without a report
            log.info("experiment %s cancelled without a report: %s", document.id, exc)
    return cancelled


VERDICTS = ("accepted", "rejected", "deferred")


def decide(
    store: ExperimentStore, document: ExperimentDocument, verdict: str, notes: str
) -> ExperimentDocument:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    updated = document.model_copy(
        update={
            "decision": {"verdict": verdict, "notes": notes, "decided_at": _now()},
            "updated_at": _now(),
        }
    )
    store.save(updated)
    return updated


def refined_surface(surface: Surface, grid, plateau_cells: list[int]) -> Surface:
    """The surface narrowed to each parameter's span over the plateau, extended by one step
    each way and clipped to the original range (spec §8.3)."""
    positions = [grid.positions(cell) for cell in plateau_cells]
    parameters = []
    for k, parameter in enumerate(surface.parameters):
        column = [p[k] for p in positions]
        lo = max(0, min(column) - 1)
        hi = min(grid.shape[k] - 1, max(column) + 1)
        parameters.append(
            Parameter(
                path=parameter.path,
                start=grid.values[k][lo],
                stop=grid.values[k][hi],
                step=parameter.step,
            )
        )
    return Surface(parameters=parameters)


def refine(
    store: ExperimentStore,
    document: ExperimentDocument,
    bars: int,
    max_workers: int,
    timeframe: str | None = None,
    *,
    pinned: Any | None = None,
    engine_build: str | None = None,
) -> ExperimentDocument:
    """A queued child experiment around the latest report's recommended plateau, pinned to the
    parent's spec (not the document's current one), with the same objective, budget and tolerance.
    The child is layout 2 whatever its parent's layout: its search space, sampler and versions
    come from its own narrowed surface and plan, nothing is copied from the parent."""
    from products.aegis.surface import build_grid

    if document.latest_report is None:
        raise ValueError("no report yet: nothing to refine")
    report = store.read_report(document.id, document.latest_report)
    recommendation = report.get("recommendation")
    if not recommendation:
        raise ValueError("the latest report has no recommendation to refine around")
    plateau = next(
        (p for p in report.get("plateaus", []) if p.get("id") == recommendation.get("plateau")),
        None,
    )
    if plateau is None or not plateau.get("cells"):
        raise ValueError("the latest report has no recommendation to refine around")
    grid = build_grid(document.spec, document.surface, bars)
    narrowed = refined_surface(document.surface, grid, plateau["cells"])
    _check_positions(narrowed)
    measured = store.last_ms_per_cell_bar()
    planned = plan_surface(
        document.spec,
        narrowed,
        document.budget,
        bars,
        measured or KERNEL_MS_PER_BAR,
        max_workers,
        timeframe,
        price_source="measured" if measured else "starting_guess",
    )
    now = _now()
    name = f"{document.name} · refined"
    chunk = CHUNK_CELLS
    root = (document.lineage or {}).get("root") or document.id
    child = ExperimentDocument(
        id=store.free_id(name),
        name=name,
        strategy_id=document.strategy_id,
        strategy_hash=document.strategy_hash,
        spec=document.spec,
        data=document.data,
        settings=document.settings,
        objective=document.objective,
        surface=narrowed,
        budget=document.budget,
        tolerance=document.tolerance,
        seed=document.seed,
        plan=planned.model_dump(mode="json"),
        status="queued",
        progress={
            "cells_done": 0,
            "cells_planned": planned.planned_runs,
            "chunks_done": 0,
            "chunks_total": math.ceil(planned.first_pass / chunk)
            + math.ceil(planned.refinement / chunk),
        },
        engine="kernel" if kernel.AVAILABLE else "reference",
        created_at=now,
        updated_at=now,
        parent=document.id,
        workers=max_workers,
        chunk_cells=chunk,
        **_layout2_fields(
            document.spec,
            narrowed,
            planned,
            document.seed,
            document.strategy_hash,
            pinned,
            engine_build,
        ),
        lineage={"parent": document.id, "root": root},
    )
    store.init_layout2(child.id)
    store.save(child)
    return child


# --- materialize -----------------------------------------------------------------------------


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return float(a) == float(b)


def materialize(
    document: ExperimentDocument,
    store: ExperimentStore,
    repository: RunRepository,
    bars: list[dict] | pd.DataFrame,
    pinned: Any,
    cell: int,
) -> dict:
    """Rerun one cell as an ordinary backtest and persist it under runs (spec §6.3). The row's
    metrics must equal the run's; the run's hash is the identity any later rerun reproduces."""
    row = store.row(document.id, cell)  # KeyError when the cell has no row
    params = {path: row[path] for path in document.surface.paths()}
    strategy = apply_params(document.spec, params)
    started = time.perf_counter()
    frame = prepare_bars(bars, document.data.symbol)
    result = run_prepared(prepared_request(strategy, document.settings), frame, _data_key(frame))
    envelope = run_envelope(
        result,
        strategy,
        document.settings,
        provenance(pinned),
        int((time.perf_counter() - started) * 1000),
    )
    envelope["strategy_id"] = document.strategy_id
    envelope["experiment_id"] = document.id
    envelope["cell"] = cell
    for scope in SCOPES:
        for metric in METRICS:
            ran, stored = envelope["result"][scope]["metrics"][metric], row[f"{scope}.{metric}"]
            if not _same(ran, stored):
                raise RuntimeError(
                    f"cell {cell} {scope}.{metric}: the run gave {ran}, the row holds {stored}"
                )
    repository.save_run(envelope)
    return envelope


__all__ = [
    "CHUNK_CELLS",
    "CURVES_LIMIT",
    "CURVE_POINTS",
    "UNFINISHED",
    "VERDICTS",
    "ExperimentDocument",
    "ExperimentJob",
    "ExperimentRequest",
    "ExperimentStore",
    "Schedule",
    "cancel_idle",
    "create",
    "decide",
    "materialize",
    "recompute_report",
    "refine",
    "refined_surface",
]
