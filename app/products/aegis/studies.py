"""Plateau walk-forward studies (Mission 8 spec §4–6): does peaks to plateaus hold out of sample?

A study belongs to one finished experiment and inherits its pinned spec, surface, objective,
tolerance, budget, seed and timeframe. On each chosen symbol it cuts rolling windows; each
window maps the surface in-sample, chooses by the experiment's analysis, and trades three rules
on the bars that follow: the plateau rule (under test), the peak rule and the frozen centre.
This module holds the request, the plan, the document and the job kind; the per-window rules,
chains and the report are pure functions in `study_rules.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis.analysis import analyse
from products.aegis.backtest import MIN_BARS, BacktestSettings
from products.aegis.experiments import ExperimentDocument, ExperimentStore, _cells_table
from products.aegis.indicators import IndicatorCache
from products.aegis.optimize import provenance
from products.aegis.pool import Pool, default_workers, fitted_workers
from products.aegis.results import _clean
from products.aegis.runs import RunRepository
from products.aegis.strategies import slug
from products.aegis.strategy import StrategySpec
from products.aegis.study_rules import (
    RULES,
    SideChain,
    best_cell,
    centre_inside,
    move_distance,
    run_window,
    start_chains,
    stitch_rule,
    study_report,
)
from products.aegis.surface import (
    KERNEL_MS_PER_BAR,
    Budget,
    Grid,
    Lever,
    Surface,
    apply_params,
    build_grid,
    effective_workers,
    latin_hypercube,
    refinement_cells,
)
from products.aegis.surface import plan as plan_surface
from products.aegis.walkforward import MIN_OOS_BARS, cut_windows

log = logging.getLogger("aegis")
NO_RECOMMENDATION = "the parent report has no recommendation"

DEFAULT_SYMBOLS = ("QQQ", "SPY", "ITOT")
RULE_RUNS_PER_WINDOW = 6  # three rules, two sides
YEAR_OBJECTIVES = ("mar", "cagr")  # the engine reports both only from 365 days
Status = Literal["queued", "running", "paused", "done", "cancelled", "failed"]
UNFINISHED = ("queued", "running", "paused")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StudyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str
    name: str | None = Field(default=None, max_length=120)
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    start: date | None = None
    end: date | None = None
    in_sample_bars: int | None = Field(default=None, gt=0)
    out_of_sample_bars: int | None = Field(default=None, gt=0)

    @field_validator("symbols")
    @classmethod
    def distinct_symbols(cls, value: list[str]) -> list[str]:
        cleaned = [symbol.strip().upper() for symbol in value]
        if not cleaned:
            raise ValueError("choose at least one symbol")
        repeated = sorted({s for s in cleaned if cleaned.count(s) > 1})
        if repeated:
            raise ValueError(f"symbol {repeated[0]!r} chosen more than once")
        return cleaned


class SymbolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    bars: int
    windows: int
    unused_tail_bars: int
    first_window: dict
    mode: Literal["exhaustive", "sampled"]
    cells_per_window: int
    first_pass: int
    refinement: int
    runs: int


class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: str
    timeframe: str
    in_sample_bars: int
    out_of_sample_bars: int
    symbols: list[SymbolPlan]
    total_runs: int
    valid_cells: int
    skipped: int
    skip_reasons: dict[str, int]
    estimate_seconds: float
    ms_per_cell_bar: float
    price_source: Literal["measured", "starting_guess"]
    workers: int
    levers: list[Lever] = Field(default_factory=list)


class StudyDocument(BaseModel):
    """The persisted study: the inherited definition, the plan, status, progress, the compact
    window records, the report and the decision. Runner fields ride along on the same file."""

    id: str
    name: str
    experiment_id: str
    strategy_id: str
    spec: StrategySpec
    surface: Surface
    objective: str
    tolerance: float
    budget: Budget
    seed: int
    timeframe: str
    settings: BacktestSettings
    symbols: list[str]
    start: date
    end: date
    in_sample_bars: int
    out_of_sample_bars: int
    frozen_centre: dict | None = None
    frozen_absent: str | None = None
    data: dict = Field(default_factory=dict)
    plan: dict
    status: Status
    progress: dict
    windows: dict[str, list[dict]] = Field(default_factory=dict)
    report: dict | None = None
    decision: dict | None = None
    ms_per_cell_bar: float | None = None
    job_id: str | None = None
    error: str | None = None
    created_at: str
    updated_at: str


def _span_days(first: str, last: str) -> int:
    return (datetime.fromisoformat(last) - datetime.fromisoformat(first)).days


def window_lengths(request: StudyRequest, experiment: ExperimentDocument) -> tuple[int, int]:
    """In-sample defaults to the experiment's own bar count; out-of-sample to a quarter of it."""
    in_sample = request.in_sample_bars or int(experiment.plan["bars"])
    return in_sample, request.out_of_sample_bars or in_sample // 4


def plan_study(
    request: StudyRequest,
    experiment: ExperimentDocument,
    bars_by_symbol: dict[str, list[str]],
    ms_per_cell_bar: float | None,
    workers: int,
) -> StudyPlan:
    """What a start would do on each symbol (spec §3 item 1, §5.4): windows, cells per window,
    runs and an estimate. `bars_by_symbol` maps each known symbol to its ISO timestamps in the
    range; every refusal is a `ValueError` naming the problem."""
    if experiment.status != "done":
        raise ValueError(
            f"experiment {experiment.id} is {experiment.status}; "
            "a study needs a finished experiment with a report"
        )
    if experiment.latest_report is None:
        raise ValueError(
            f"experiment {experiment.id} has no report; "
            "a study needs a finished experiment with a report"
        )
    in_sample, out_of_sample = window_lengths(request, experiment)
    if in_sample < MIN_BARS:
        raise ValueError(f"in_sample_bars {in_sample} below {MIN_BARS}")
    if out_of_sample < MIN_OOS_BARS:
        raise ValueError(f"out_of_sample_bars {out_of_sample} below {MIN_OOS_BARS}")
    grid = build_grid(experiment.spec, experiment.surface, in_sample)
    if grid.valid_count == 0:
        raise ValueError(f"in_sample_bars {in_sample}: every cell's warm-up needs more bars")
    timeframe = experiment.data.timeframe
    price = ms_per_cell_bar or KERNEL_MS_PER_BAR
    planned = plan_surface(
        experiment.spec,
        experiment.surface,
        experiment.budget,
        in_sample,
        price,
        workers,
        timeframe,
        price_source="measured" if ms_per_cell_bar else "starting_guess",
    )
    symbols: list[SymbolPlan] = []
    map_seconds = 0.0
    rule_seconds = 0.0
    for symbol in request.symbols:
        if symbol not in bars_by_symbol:
            raise ValueError(f"unknown symbol {symbol!r}")
        timestamps = bars_by_symbol[symbol]
        if not timestamps:
            raise ValueError(f"symbol {symbol!r} has no {timeframe} bars in the range")
        try:
            windows, tail = cut_windows(len(timestamps), in_sample, out_of_sample)
        except ValueError as exc:
            raise ValueError(f"{symbol}: {exc}") from exc
        if experiment.objective in YEAR_OBJECTIVES:
            spans = [
                (_span_days(timestamps[w.is_start], timestamps[w.is_end - 1]), w.index)
                for w in windows
            ]
            span, index = min(spans)
            if span < 365:
                raise ValueError(
                    f"objective {experiment.objective} needs an in-sample span of at least 365 "
                    f"days; {symbol} window {index} spans {span} days; lengthen in_sample_bars "
                    "or choose another objective"
                )
        first = windows[0]
        symbols.append(
            SymbolPlan(
                symbol=symbol,
                bars=len(timestamps),
                windows=len(windows),
                unused_tail_bars=tail,
                first_window={
                    "is_start": timestamps[first.is_start],
                    "is_end": timestamps[first.is_end - 1],
                    "oos_start": timestamps[first.oos_start],
                    "oos_end": timestamps[first.oos_end - 1],
                },
                mode=planned.mode,
                cells_per_window=planned.planned_runs,
                first_pass=planned.first_pass,
                refinement=planned.refinement,
                runs=len(windows) * planned.planned_runs,
            )
        )
        map_seconds += len(windows) * planned.planned_runs * in_sample * price / 1000.0
        rule_seconds += sum(RULE_RUNS_PER_WINDOW * w.oos_end * price / 1000.0 for w in windows)
    return StudyPlan(
        experiment_id=experiment.id,
        timeframe=timeframe,
        in_sample_bars=in_sample,
        out_of_sample_bars=out_of_sample,
        symbols=symbols,
        total_runs=sum(s.runs for s in symbols),
        valid_cells=planned.valid_cells,
        skipped=planned.skipped,
        skip_reasons=planned.skip_reasons,
        estimate_seconds=round(map_seconds / effective_workers(workers) + rule_seconds, 3),
        ms_per_cell_bar=price,
        price_source=planned.price_source,
        workers=workers,
        levers=planned.levers,
    )


def map_window(
    pool: Pool,
    grid: Grid,
    mode: str,
    first_pass: int,
    refinement: int,
    objective: str,
    tolerance: float,
    seed: int,
    window: tuple[int, int],
    data_label: str,
) -> tuple[pa.Table, dict]:
    """One window's in-sample map (spec §5.1–5.2): every planned cell on the window's bars only,
    exhaustive or a Latin-hypercube first pass plus plateau refinement as an experiment samples,
    then the experiment's analysis. Returns the cells (the experiment's cell schema) and the
    report; nothing is persisted here."""
    paths = grid.paths

    def run(cells: list[int], label: str) -> list[dict]:
        if not cells:
            return []
        rows = pool.run_chunk(
            [(i, grid.cell_values(i)) for i in cells], want_curve=False, window=window
        )
        for row in rows:
            row["pass"] = label
        return rows

    if mode == "exhaustive":
        cells = range(grid.size) if grid.skipped_count == 0 else grid.valid_indices_iter()
        rows = run(list(cells), "grid")
    else:
        rows = run(latin_hypercube(grid, first_pass, seed), "sample")
        first = _cells_table(rows, paths)
        report = analyse(first, grid, objective, tolerance, "sampled", seed, data_label)
        sign = -1.0 if objective == "max_drawdown" else 1.0
        run_cells = {
            cell: (None if value is None else sign * float(value))
            for cell, value in zip(
                first.column("cell").to_pylist(),
                first.column(f"combined.{objective}").to_pylist(),
                strict=True,
            )
        }
        rows += run(refinement_cells(grid, run_cells, report["plateaus"], refinement), "refine")
    table = _cells_table(rows, paths)
    return table, analyse(table, grid, objective, tolerance, mode, seed, data_label)


# --- storage ---------------------------------------------------------------------------------


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class StudyStore:
    """Documents on the repository; each window's full record (JSON) and in-sample cells
    (Parquet) under `studies/<id>.windows/<symbol>/` (plan ruling P4)."""

    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    def save(self, document: StudyDocument) -> None:
        self.repository.save_study(document.model_dump(mode="json"))

    def get(self, study_id: str) -> StudyDocument:
        try:
            return StudyDocument.model_validate(self.repository.get_study(study_id))
        except ValueError as exc:  # an identifier the repository refuses is simply unknown
            raise KeyError(study_id) from exc

    def list(self) -> list[dict]:
        return self.repository.list_studies()

    def delete(self, study_id: str) -> None:
        self.repository.delete_study(study_id)

    def free_id(self, name: str) -> str:
        base = slug(name)
        taken = {item.get("id") for item in self.list()}
        # Ids in Recently deleted stay reserved until Empty (Mission 9 plan ruling P4).
        trashed = getattr(self.repository, "trashed_ids", None)
        taken |= trashed("studies") if trashed is not None else set()
        if base not in taken:
            return base
        digest = hashlib.sha256(f"{name}|{_now()}".encode()).hexdigest()
        candidate = f"{base}-{digest[:6]}"
        while candidate in taken:
            digest = hashlib.sha256(digest.encode()).hexdigest()
            candidate = f"{base}-{digest[:6]}"
        return candidate

    def window_paths(self, study_id: str, symbol: str, w: int) -> tuple[Path, Path]:
        folder = self.repository.study_dir(study_id) / slug(symbol).upper()
        return folder / f"{int(w)}.json", folder / f"{int(w)}.parquet"

    def write_window(
        self, study_id: str, symbol: str, w: int, record: dict, table: pa.Table
    ) -> None:
        """Cells first, the record last: a window counts as done only when both parse."""
        json_path, parquet_path = self.window_paths(study_id, symbol, w)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = parquet_path.with_name(parquet_path.name + ".tmp")
        pq.write_table(table, tmp)
        tmp.replace(parquet_path)
        _write_text_atomic(json_path, json.dumps(_clean(record), allow_nan=False))

    def read_window(self, study_id: str, symbol: str, w: int) -> dict | None:
        json_path, parquet_path = self.window_paths(study_id, symbol, w)
        if not json_path.is_file() or not parquet_path.is_file():
            return None
        try:
            pq.read_metadata(parquet_path)
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a torn window is rerun, never trusted
            log.warning(
                "study %s window %s/%s unreadable, it will rerun: %s", study_id, symbol, w, exc
            )
            return None

    def done_windows(self, study_id: str) -> dict[str, set[int]]:
        root = self.repository.study_dir(study_id)
        done: dict[str, set[int]] = {}
        if not root.is_dir():
            return done
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            indices = {int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()}
            kept = {w for w in indices if self.read_window(study_id, folder.name, w) is not None}
            if kept:
                done[folder.name] = kept
        return done

    def cells(self, study_id: str, symbol: str, w: int) -> pa.Table | None:
        _, parquet_path = self.window_paths(study_id, symbol, w)
        if not parquet_path.is_file():
            return None
        return pq.read_table(parquet_path).sort_by("cell")


# --- creation, decision, cancel --------------------------------------------------------------


def _own_report(experiment: ExperimentDocument) -> tuple[int | None, str | None]:
    """The latest report on the experiment's own objective and tolerance (the definition the
    study inherits); a report recomputed on another objective never freezes the centre."""
    if not experiment.reports:
        return experiment.latest_report, None
    own = [
        r["report_id"]
        for r in experiment.reports
        if r.get("objective") == experiment.objective
        and float(r.get("tolerance", -1)) == float(experiment.tolerance)
    ]
    if own:
        return max(own), None
    return None, (
        f"the parent has no report on its own objective {experiment.objective} "
        f"at tolerance {experiment.tolerance:g}"
    )


def create_study(
    store: StudyStore,
    experiments: ExperimentStore,
    request: StudyRequest,
    bars_by_symbol: dict[str, list[str]],
    workers: int,
    start: date,
    end: date,
    data: dict | None = None,
) -> StudyDocument:
    """Plan and save a queued study inheriting the experiment's definition; the frozen centre
    is the parent's latest report recommendation, or absent with the reason."""
    experiment = experiments.get(request.experiment_id)  # KeyError when unknown
    planned = plan_study(
        request, experiment, bars_by_symbol, experiments.last_ms_per_cell_bar(), workers
    )
    number, absent = _own_report(experiment)
    centre = None
    if number is not None:
        try:
            report = experiments.read_report(experiment.id, number)
        except KeyError as exc:
            raise ValueError(f"experiment {experiment.id} report {number} is missing") from exc
        recommendation = report.get("recommendation")
        centre = recommendation["centre"] if recommendation else None
        absent = None if centre else NO_RECOMMENDATION
    name = request.name or f"{experiment.name} · walk forward"
    now = _now()
    document = StudyDocument(
        id=store.free_id(name),
        name=name,
        experiment_id=experiment.id,
        strategy_id=experiment.strategy_id,
        spec=experiment.spec,
        surface=experiment.surface,
        objective=experiment.objective,
        tolerance=experiment.tolerance,
        budget=experiment.budget,
        seed=experiment.seed,
        timeframe=experiment.data.timeframe,
        settings=experiment.settings,
        symbols=request.symbols,
        start=start,
        end=end,
        in_sample_bars=planned.in_sample_bars,
        out_of_sample_bars=planned.out_of_sample_bars,
        frozen_centre={"cell": centre["cell"], "params": centre["params"]} if centre else None,
        frozen_absent=absent,
        data=data or {},
        plan=planned.model_dump(mode="json"),
        status="queued",
        progress={
            "windows_done": 0,
            "windows_total": sum(s.windows for s in planned.symbols),
            "symbol": request.symbols[0],
            "window": 0,
            "cells_done": 0,
        },
        created_at=now,
        updated_at=now,
    )
    store.save(document)
    return document


VERDICTS = ("accepted", "rejected", "deferred")


def decide_study(
    store: StudyStore, document: StudyDocument, verdict: str, notes: str
) -> StudyDocument:
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


def cancel_idle_study(store: StudyStore, document: StudyDocument) -> StudyDocument:
    """Cancel a queued or paused study that has no live job; its window files stay."""
    cancelled = document.model_copy(update={"status": "cancelled", "updated_at": _now()})
    store.save(cancelled)
    return cancelled


# --- the job kind ----------------------------------------------------------------------------


def compact(record: dict) -> dict:
    """A window record without its trades or plateau cells: what the document keeps. Each rule's
    carried in and out (the chains) stay, as spec §5.5 asks."""
    out = dict(record)
    if record.get("plateau"):
        out["plateau"] = {k: v for k, v in record["plateau"].items() if k != "cells"}
    rules = {}
    for rule, result in record["rules"].items():
        if "absent" in result:
            rules[rule] = result
            continue
        rules[rule] = {
            "flat": result["flat"],
            "params": result.get("params"),
            "combined": {k: v for k, v in result["combined"].items() if k != "trades"},
            "sides": {
                side: {
                    **{
                        k: v
                        for k, v in entry.items()
                        if k not in ("trades", "open_position", "pending_entry")
                    },
                    "trade_count": len(entry["trades"]),
                    "open_at_end": entry["open_position"] is not None,
                    "entry_at_end": entry.get("pending_entry") is not None,
                }
                for side, entry in result["sides"].items()
            },
        }
    out["rules"] = rules
    return out


# Studies still hold every bar as a row (Mission 10 ruling: their frames are a follow-up), so they
# keep the bound per symbol they were built and measured under; GET /data/bars' 2,000,000-bar
# guard is not theirs (review I1).
STUDY_BAR_CAP = 200_000


class StudyJob:
    """The runner's fourth kind (spec §6): a unit is one window of one symbol — its in-sample
    map, the choice, and each rule's out-of-sample window on its chains. Symbols run in order and
    windows in order within a symbol; every committed window is a pair of files, so a pause or a
    restart resumes at the first window without them, its chains read back from the last one."""

    name = "study"
    side = "both"
    resumable = True
    bars_per_unit = 0

    def __init__(
        self,
        document: StudyDocument,
        rows_by_symbol: dict[str, list[dict]],
        pinned_by_symbol: dict[str, Any],
        repository: RunRepository,
        max_workers: int | None = None,
    ) -> None:
        self.document = document.model_copy()
        self.rows = rows_by_symbol
        self.pinned = {symbol: provenance(p) for symbol, p in pinned_by_symbol.items()}
        self.repository = repository
        self.store = StudyStore(repository)
        # Mission 10 review I1: the pool takes only the workers free memory holds for the
        # longest symbol's bars (a ValueError naming the shortfall when none fits).
        longest = max((len(rows) for rows in rows_by_symbol.values()), default=0)
        self.workers = fitted_workers(longest, max_workers or default_workers())
        self.grid = build_grid(document.spec, document.surface, document.in_sample_bars)
        self.rules = [r for r in RULES if r != "frozen" or document.frozen_centre is not None]
        self.windows = {
            symbol: cut_windows(
                len(rows_by_symbol[symbol]), document.in_sample_bars, document.out_of_sample_bars
            )[0]
            for symbol in document.symbols
        }
        done = self.store.done_windows(document.id)
        self.chains: dict[str, dict[str, dict[str, SideChain]]] = {}
        self.previous: dict[str, dict | None] = {}
        self.units: list[tuple[str, int]] = []
        windows: dict[str, list[dict]] = {}
        self.windows_done = 0
        self.cells_done = 0
        for symbol in document.symbols:
            kept = 0  # the done prefix: a later window depends on every earlier chain
            while kept < len(self.windows[symbol]) and kept in done.get(symbol, set()):
                kept += 1
            records = [self.store.read_window(document.id, symbol, w) for w in range(kept)]
            windows[symbol] = [compact(r) for r in records]
            self.windows_done += kept
            self.cells_done += sum(r["cells_run"] for r in records)
            last = records[-1] if records else None
            self.chains[symbol] = {
                rule: (
                    {side: SideChain.of(c) for side, c in last["chains_out"][rule].items()}
                    if last is not None
                    else start_chains(document.spec, document.settings.initial_capital)
                )
                for rule in self.rules
            }
            self.previous[symbol] = self._plateau_of(last)
            self.units += [(symbol, w) for w in range(kept, len(self.windows[symbol]))]
        self.document = self.document.model_copy(
            update={"windows": {s: v for s, v in windows.items() if v}}
        )
        self.total_units = len(self.units)
        self.units_done = 0
        self.pause_requested = False
        self.pool: Pool | None = None
        self.pool_symbol: str | None = None
        self.cache = IndicatorCache(max_data_keys=8)
        self.status: str = "queued"
        self.ms_per_cell_bar = document.ms_per_cell_bar
        self.current: tuple[str, int] | None = self.units[0] if self.units else None

    @staticmethod
    def _plateau_of(record: dict | None) -> dict | None:
        if record is None or not record.get("plateau"):
            return None
        return {"cells": record["plateau"]["cells"], "centre": record["plateau"]["centre_cell"]}

    # -- units ------------------------------------------------------------------------------
    def _switch_pool(self, symbol: str) -> None:
        if self.pool is not None:
            self.pool.shutdown()
        self.pool = Pool(self.workers)
        self.pool.start(
            self.rows[symbol],
            symbol,
            self.document.spec.model_dump(mode="json"),
            self.document.settings.model_dump(mode="json"),
        )
        self.pool_symbol = symbol

    def run_unit(self, index: int) -> dict:
        symbol, w = self.units[index]
        if self.pool_symbol != symbol:
            self._switch_pool(symbol)
        self.status = "running"
        doc = self.document
        plan = next(p for p in doc.plan["symbols"] if p["symbol"] == symbol)
        window = self.windows[symbol][w]
        rows = self.rows[symbol]
        stamp = [rows[i]["timestamp"] for i in (window.is_start, window.is_end - 1)]
        table, report = map_window(
            self.pool,
            self.grid,
            plan["mode"],
            plan["first_pass"],
            plan["refinement"],
            doc.objective,
            doc.tolerance,
            doc.seed + w,  # plan ruling P13
            (window.is_start, window.is_end),
            f"{symbol} {doc.timeframe} window {w} in-sample {stamp[0]} → {stamp[1]}",
        )
        recommendation = report.get("recommendation")
        plateau = None
        if recommendation:
            top = next(p for p in report["plateaus"] if p["id"] == recommendation["plateau"])
            plateau = {
                "id": top["id"],
                "size": top["size"],
                "median": top["median"],
                "cliff": top["cliff"],
                "centre_cell": top["centre"]["cell"],
                "centre_params": top["centre"]["params"],
                "cells": top["cells"],
            }
        best = best_cell(table, doc.objective)
        best_entry = None
        if best is not None:
            cells = table.column("cell").to_pylist()
            values = table.column(f"combined.{doc.objective}").to_pylist()
            best_entry = {
                "cell": best,
                "params": self.grid.cell_values(best),
                "objective": values[cells.index(best)],
            }
        choices: dict[str, dict | None] = {
            "plateau": plateau["centre_params"] if plateau else None,
            "peak": best_entry["params"] if best_entry else None,
        }
        if doc.frozen_centre is not None:
            choices["frozen"] = doc.frozen_centre["params"]
        last = w == len(self.windows[symbol]) - 1
        rules: dict[str, dict] = {}
        chains_out: dict[str, dict] = {}
        chains_in: dict[str, dict] = {}
        for rule, params in choices.items():
            chains = self.chains[symbol][rule]
            chains_in[rule] = {side: chain.as_dict() for side, chain in chains.items()}
            strategy = apply_params(doc.spec, params) if params is not None else doc.spec
            result = run_window(
                strategy,
                rows,
                window,
                chains,
                doc.settings,
                last,
                flat=params is None,
                cache=self.cache,
            )
            chains_out[rule] = {side: c.as_dict() for side, c in result.pop("chains").items()}
            rules[rule] = {**result, "params": params}
        if doc.frozen_centre is None:
            rules["frozen"] = {"absent": doc.frozen_absent or NO_RECOMMENDATION}
        previous = self.previous[symbol]
        centre = plateau["centre_cell"] if plateau else None
        record = {
            "index": w,
            "is_start": rows[window.is_start]["timestamp"],
            "is_end": rows[window.is_end - 1]["timestamp"],
            "oos_start": rows[window.oos_start]["timestamp"],
            "oos_end": rows[window.oos_end - 1]["timestamp"],
            "oos_bars": window.oos_end - window.oos_start,
            "mode": plan["mode"],
            "cells_run": len(table),
            "skipped": sum(1 for valid in table.column("valid").to_pylist() if not valid),
            "plateau": plateau,
            "no_plateau": None if plateau else report["statement"],
            "peaks": len(report["peaks"]),
            "fragile": sum(1 for peak in report["peaks"] if peak["fragile"]),
            "best": best_entry,
            "rules": rules,
            "chains_in": chains_in,
            "chains_out": chains_out,
            "centre_inside": centre_inside(previous["cells"] if previous else None, centre),
            "moved": (
                move_distance(self.grid, previous["centre"], centre)
                if previous is not None and centre is not None
                else None
            ),
        }
        return {"symbol": symbol, "window": w, "record": record, "table": table}

    def commit(self, index: int, result: dict) -> None:
        symbol, w, record = result["symbol"], result["window"], result["record"]
        self.store.write_window(self.document.id, symbol, w, record, result["table"])
        for rule, sides in record["chains_out"].items():
            self.chains[symbol][rule] = {side: SideChain.of(c) for side, c in sides.items()}
        self.previous[symbol] = self._plateau_of(record)
        windows = dict(self.document.windows)
        windows[symbol] = [
            *(r for r in windows.get(symbol, []) if r["index"] != w),
            compact(record),
        ]
        self.units_done += 1
        self.windows_done += 1
        self.cells_done += record["cells_run"]
        self.current = self.units[index + 1] if index + 1 < len(self.units) else None
        if self.pool is not None and self.pool.mean_ms_per_cell_bar:
            self.ms_per_cell_bar = self.pool.mean_ms_per_cell_bar
        self.document = self.document.model_copy(
            update={
                "windows": windows,
                "progress": self._progress(),
                "ms_per_cell_bar": self.ms_per_cell_bar,
                "status": self.status,
                "updated_at": _now(),
            }
        )

    def _progress(self) -> dict:
        symbol, window = self.current or (None, None)
        return {
            "windows_done": self.windows_done,
            "windows_total": self.document.progress["windows_total"],
            "symbol": symbol,
            "window": window,
            "cells_done": self.cells_done,
        }

    def snapshot(self) -> dict:
        remaining = self.total_units - self.units_done
        price = self.ms_per_cell_bar or self.document.plan["ms_per_cell_bar"]
        cells = max((p["cells_per_window"] for p in self.document.plan["symbols"]), default=0)
        estimate = (
            remaining
            * cells
            * self.document.in_sample_bars
            * price
            / 1000.0
            / effective_workers(self.workers)
        )
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

    def _report(self) -> dict:
        doc = self.document
        per_symbol: dict[str, dict] = {}
        for symbol in doc.symbols:
            records = [
                self.store.read_window(doc.id, symbol, w) for w in range(len(self.windows[symbol]))
            ]
            records = [r for r in records if r is not None]
            per_symbol[symbol] = {
                "rules": {
                    rule: (
                        {"absent": doc.frozen_absent or NO_RECOMMENDATION}
                        if rule not in self.rules
                        else stitch_rule(
                            [r["rules"][rule] for r in records], doc.settings.initial_capital
                        )
                    )
                    for rule in RULES
                },
                "windows": [compact(r) for r in records],
            }
        return study_report(doc, per_symbol)

    def finalize(self, status: str) -> dict:
        mapped = "paused" if status == "cancelled" and self.pause_requested else status
        self.status = mapped
        update: dict[str, Any] = {
            "status": mapped,
            "progress": self._progress(),
            "updated_at": _now(),
        }
        if mapped == "done":
            update["report"] = self._report()
        self.document = self.document.model_copy(update=update)
        return {"status": mapped}

    def release(self) -> None:
        if self.pool is not None:
            self.pool.shutdown()
            self.pool = None
            self.pool_symbol = None
        self.rows = {}
        self.cache = IndicatorCache()


__all__ = [
    "DEFAULT_SYMBOLS",
    "NO_RECOMMENDATION",
    "UNFINISHED",
    "VERDICTS",
    "StudyDocument",
    "StudyJob",
    "StudyPlan",
    "StudyRequest",
    "StudyStore",
    "SymbolPlan",
    "cancel_idle_study",
    "compact",
    "create_study",
    "decide_study",
    "map_window",
    "plan_study",
    "window_lengths",
]
