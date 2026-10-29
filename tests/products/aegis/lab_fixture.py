"""The DEMO · synthetic experiment (Optimization Lab v2 spec §9.8, scenario 11): a layout-2
experiment written straight into a data root, never through the engine (a million real trials
take hours), for `lab_benchmark.py explore` and the tests.

Its surface is the benchmark's (`BENCH_SURFACE`, ten ranged paths, 2.87 × 10¹¹ cells); each
trial's positions are drawn uniformly per path, its `cell` is their mixed-radix grid index and
its metrics come from a known function of the first seven positions (`known_metrics`), so the
Lab's views have answers to find: an XOR pair, a conditional triple, a plateau and a spike, plus
noise. The trials are written as compacted parts (`write_part`) with a manifest; the document
is named and marked synthetic (engine, sampler, data pin). No curves.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
from lab_benchmark import BENCH_CASES, BENCH_SURFACE, bench_strategy, bench_surface
from products.aegis.backtest import BacktestSettings, DataReference
from products.aegis.experiments import (
    CHUNK_CELLS,
    ExperimentDocument,
    ExperimentStore,
    _cells_table_v2,
)
from products.aegis.lab import identity
from products.aegis.lab import store as lab_store
from products.aegis.pool import METRICS, SCOPES
from products.aegis.results import strategy_hash
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import StrategySpec
from products.aegis.surface import Budget, Grid, Plan, Surface, build_grid

# The known function. Positions are compared with the midpoint of each path's position range
# (BENCH_SURFACE's value counts), so a trial's structure never depends on the other trials.
STRUCTURE_PATHS = 7  # p0..p6: ten parameters suffice
XOR_GAIN = 4.0  # 4 · [XOR(p0 > m0, p1 > m1)]
TRIPLE_GAIN = 2.0  # 2 · [(p2 > m2) and (p3 > m3) and (p4 > m4)]
PLATEAU_GAIN = 3.0  # over the broad square 0.1 ≤ u5, u6 ≤ 0.5 (u: the position over its range)
PLATEAU = (0.1, 0.5)
SPIKE_LOSS = 6.0  # − 6 · spike: the one position pair nearest u5 = u6 = 0.8
SPIKE_AT = 0.8
NOISE_SD = 0.5
CAGR_UNDEFINED = 0.03  # the seeded share of rows whose cagr (and so mar) is null
SCOPE_OFFSET_SD = 0.1  # long = combined · (1 + δ), short = combined · (1 − δ), δ seeded per row
NOMINAL_CAPITAL = 100.0
NOMINAL_YEARS = 1.5
ENGINE = "synthetic"
PASS = "sample"


def known_metrics(positions: np.ndarray, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Every `<scope>.<metric>` (the ten metrics and `sharpe_trade`) of each row of `positions`
    ((n, d) uint16, d ≥ 7; only p0..p6 are read), NaN where undefined.

    combined.net_pnl = 4·[XOR(p0 > m0, p1 > m1)] + 2·[(p2 > m2) and (p3 > m3) and (p4 > m4)]
    + plateau(p5, p6) − 6·spike(p5, p6) + noise, m_k the midpoint of path k's positions. The other
    metrics are derived from it and from seeded draws: cagr null for a seeded 3 % of rows (mar
    with it), profit_factor null where a trial has no losing trade, sharpe_trade null below two
    trades. The long and short scopes are the combined values ± a seeded relative offset. Every
    draw is independent of the positions, so the same seed gives the same noise whatever they
    are."""
    positions = np.asarray(positions)
    if positions.ndim != 2 or positions.shape[1] < STRUCTURE_PATHS:
        raise ValueError(
            f"known_metrics reads p0..p6: positions need at least {STRUCTURE_PATHS} columns"
        )
    n = len(positions)
    p = positions[:, :STRUCTURE_PATHS].astype(np.float64)
    top = np.array([BENCH_SURFACE[k].n_values - 1 for k in range(STRUCTURE_PATHS)], np.float64)
    high = p > top / 2
    u = p / top
    xor = np.logical_xor(high[:, 0], high[:, 1])
    triple = high[:, 2] & high[:, 3] & high[:, 4]
    lo, hi = PLATEAU
    plateau = (u[:, 5] >= lo) & (u[:, 5] <= hi) & (u[:, 6] >= lo) & (u[:, 6] <= hi)
    spike = (p[:, 5] == round(SPIKE_AT * top[5])) & (p[:, 6] == round(SPIKE_AT * top[6]))
    noise = rng.normal(0.0, NOISE_SD, n)
    net_pnl = XOR_GAIN * xor + TRIPLE_GAIN * triple + PLATEAU_GAIN * plateau - SPIKE_LOSS * spike
    net_pnl = net_pnl + noise

    trade_count = rng.integers(1, 80, n).astype(np.float64)
    win_rate = rng.uniform(0.3, 0.7, n)
    exposure = rng.uniform(0.05, 0.6, n)
    max_drawdown = 0.5 + rng.gamma(2.0, 1.0, n)
    undefined_cagr = rng.random(n) < CAGR_UNDEFINED
    trade_sd = 0.5 + rng.gamma(2.0, 0.5, n)
    offset = rng.normal(0.0, SCOPE_OFFSET_SD, n)

    net_return = net_pnl / NOMINAL_CAPITAL
    cagr = np.where(undefined_cagr, np.nan, net_return / NOMINAL_YEARS)
    losses = np.round(trade_count * (1.0 - win_rate))
    gross_loss = losses * 1.0
    gross_win = np.maximum(net_pnl + gross_loss, 0.0)
    expectancy = net_pnl / trade_count
    combined = {
        "net_pnl": net_pnl,
        "net_return": net_return,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "mar": cagr / max_drawdown,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "profit_factor": np.where(
            losses > 0, gross_win / np.where(losses > 0, gross_loss, 1.0), np.nan
        ),
        "trade_count": trade_count,
        "exposure": exposure,
        "sharpe_trade": np.where(trade_count >= 2, expectancy / trade_sd, np.nan),
    }
    out: dict[str, np.ndarray] = {}
    for scope, sign in (("combined", 0.0), ("long", 1.0), ("short", -1.0)):
        for metric, values in combined.items():
            scoped = values * (1.0 + sign * offset)
            if metric == "trade_count":
                scoped = np.round(scoped)
            out[f"{scope}.{metric}"] = scoped
    return out


def _metric(value: float) -> float | None:
    return None if math.isnan(value) else value


def _tables(
    grid: Grid,
    spec: StrategySpec,
    steps: dict[str, float],
    trial_nos: np.ndarray,
    rng: np.random.Generator,
    *,
    first_chunk: int,
    finished_at: datetime,
) -> list[pa.Table]:
    """The trials `trial_nos` as layout-2 chunk tables of CHUNK_CELLS rows (`_cells_table_v2`
    with no schedule: each row carries its `trial_no`), chunk indices from `first_chunk`."""
    n = len(trial_nos)
    positions = np.column_stack([rng.integers(0, size, n) for size in grid.shape])
    positions = positions.astype(np.uint16)
    metrics = known_metrics(positions, rng)
    elapsed = 40.0 + rng.gamma(2.0, 4.0, n)
    cells = positions.astype(np.int64) @ np.asarray(grid.strides, dtype=np.int64)
    values = [np.asarray(lattice, dtype=np.float64) for lattice in grid.values]
    params = [values[k][positions[:, k]] for k in range(len(grid.paths))]
    tables = []
    for index, lo in enumerate(range(0, n, CHUNK_CELLS), start=first_chunk):
        hi = min(lo + CHUNK_CELLS, n)
        block = {
            name: [_metric(v) for v in column[lo:hi].tolist()] for name, column in metrics.items()
        }
        block_params = [column[lo:hi].tolist() for column in params]
        rows = []
        for i in range(hi - lo):
            rows.append(
                {
                    "trial_no": int(trial_nos[lo + i]),
                    "cell": int(cells[lo + i]),
                    "params": {path: block_params[k][i] for k, path in enumerate(grid.paths)},
                    "pass": PASS,
                    "valid": True,
                    "skip_reason": None,
                    "metrics": {
                        scope: {metric: block[f"{scope}.{metric}"][i] for metric in METRICS}
                        for scope in SCOPES
                    },
                    "lab_metrics": {
                        scope: {"sharpe_trade": block[f"{scope}.sharpe_trade"][i]}
                        for scope in SCOPES
                    },
                    "elapsed_ms": float(elapsed[lo + i]),
                    "engine": ENGINE,
                }
            )
        tables.append(_cells_table_v2(rows, grid, spec, steps, None, index, finished_at))
    return tables


def _steps(surface: Surface) -> dict[str, float]:
    return {parameter.path: parameter.step for parameter in surface.parameters}


def chunk_tables(
    document: ExperimentDocument,
    trial_nos: np.ndarray,
    rng: np.random.Generator,
    *,
    first_chunk: int,
    finished_at: datetime | None = None,
) -> list[pa.Table]:
    """More synthetic trials of a fixture's document, as the chunk tables a job would commit
    (`lab_benchmark.py explore`'s compaction measurements)."""
    grid = build_grid(document.spec, document.surface, None)
    return _tables(
        grid,
        document.spec,
        _steps(document.surface),
        trial_nos,
        rng,
        first_chunk=first_chunk,
        finished_at=finished_at or datetime.now(UTC),
    )


def _pin(case_label: str = "A") -> dict:
    """The synthetic data pin: named so, with no archive bytes behind it (a resume or a
    materialize of a DEMO trial is refused on its provenance)."""
    case = BENCH_CASES[case_label]
    return {
        "source": "synthetic",
        "symbol": "QQQ",
        "vintage": "DEMO synthetic",
        "timeframe": case.timeframe,
        "start": case.start.isoformat(),
        "end": case.end.isoformat(),
        "sha256": None,
        "data_hash": None,
        "bar_count": case.bars_nominal,
        "research_eligible": False,
    }


def write_fixture(
    data_root: Path,
    *,
    experiment_id: str = "demo-synthetic-1m",
    trials: int = 1_000_000,
    parameters: int = 10,
    seed: int = 1,
    part_rows: int = 100_000,
) -> ExperimentDocument:
    """`experiments/<id>.json.gz` (status done, layout 2) over the first `parameters` paths of
    BENCH_SURFACE, and `<id>.cells/` holding `part-<g>.parquet` for g in 1..trials / part_rows
    (written through `write_part`) and their manifest. Deterministic in `seed`. Refuses more
    parameters than the bench paths before anything is written, and a fixture already there."""
    if parameters > len(BENCH_SURFACE):
        raise ValueError(f"parameters {parameters} exceeds the {len(BENCH_SURFACE)} bench paths")
    if trials <= 0 or part_rows <= 0 or trials % part_rows or part_rows % CHUNK_CELLS:
        raise ValueError(
            f"trials {trials} must be a positive multiple of part_rows {part_rows}, itself a "
            f"multiple of {CHUNK_CELLS}"
        )
    spec = bench_strategy()
    surface = Surface(parameters=bench_surface().parameters[:parameters])
    store = ExperimentStore(JsonRunRepository(Path(data_root)))
    cells_dir = store.cells_dir(experiment_id)
    documents = [cells_dir.parent / f"{experiment_id}{suffix}" for suffix in (".json.gz", ".json")]
    if cells_dir.exists() or any(path.exists() for path in documents):
        raise FileExistsError(f"fixture {experiment_id} already exists under {data_root}")
    grid = build_grid(spec, surface, None)
    steps = _steps(surface)
    created = datetime.now(UTC)
    parts = trials // part_rows
    entries, cells = [], []
    for generation in range(1, parts + 1):
        rng = np.random.default_rng([seed, generation])
        first = (generation - 1) * part_rows
        trial_nos = np.arange(first, first + part_rows, dtype=np.int64)
        tables = _tables(
            grid,
            spec,
            steps,
            trial_nos,
            rng,
            first_chunk=first // CHUNK_CELLS,
            finished_at=created,
        )
        table = pa.concat_tables(tables)
        entries.append(lab_store.write_part(cells_dir, table, generation))
        cells.append(table.column("cell").to_numpy())
    unique = len(np.unique(np.concatenate(cells)))  # a configuration is its cell here
    lab_store.write_manifest(
        cells_dir,
        lab_store.Manifest(
            layout=2,
            generation=parts,
            parts=entries,
            merged_chunks=[],
            generations=[
                {
                    "generation": entry["generation"],
                    "at": created.timestamp(),
                    "rows": entry["rows"],
                    "compaction_ms": None,
                    "reclaim_ms": None,
                }
                for entry in entries
            ],
            chunk_watermark=trials // CHUNK_CELLS - 1,
            unique=unique,
            unique_generation=parts,
            updated_at=created.isoformat(),
        ),
    )
    document = _document(experiment_id, spec, surface, grid, trials, seed, unique, parts, created)
    store.save(document)
    return document


def _document(
    experiment_id: str,
    spec: StrategySpec,
    surface: Surface,
    grid: Grid,
    trials: int,
    seed: int,
    unique: int,
    parts: int,
    created: datetime,
) -> ExperimentDocument:
    case = BENCH_CASES["A"]
    planned = Plan(
        mode="sampled",
        grid_cells=grid.size,
        valid_cells=grid.size,  # every cell of the bench surface is valid
        skipped=0,
        skip_reasons={},
        planned_runs=trials,
        first_pass=trials,
        refinement=0,
        sampled_fraction=trials / grid.size,
        estimate_seconds=0.0,
        ms_per_cell_bar=0.0,
        workers=1,
        bars=case.bars_nominal,
        evaluations=trials,  # no screening blocks
    )
    # The trial numbers live in the parts: no first-pass or refinement cells are listed, and
    # counts.scheduled = trials is what the Lab reads.
    plan = {**planned.model_dump(mode="json"), "first_pass_cells": [], "refinement_cells": []}
    hashed = strategy_hash(spec)
    versions = {**identity.versions(hashed), "engine": ENGINE}
    sampler = {**identity.sampler(plan, seed), "method": "uniform per path (DEMO synthetic)"}
    counts = lab_store.Counters(
        attempted=trials,
        completed=trials,
        scheduled=trials,
        budget_total=trials,
        unique=unique,
        unique_generation=parts,
    )
    name = "DEMO · synthetic 1M" if trials == 1_000_000 else f"DEMO · synthetic {trials:,}"
    now = created.isoformat()
    return ExperimentDocument(
        id=experiment_id,
        name=name,
        strategy_id=spec.id,
        strategy_hash=hashed,
        spec=spec,
        data=DataReference(symbol="QQQ", timeframe=case.timeframe, start=case.start, end=case.end),
        settings=BacktestSettings(),
        objective="net_pnl",
        surface=surface,
        budget=Budget(runs=trials),
        tolerance=0.15,
        seed=seed,
        plan=plan,
        status="done",
        progress={
            "cells_done": trials,
            "cells_planned": trials,
            "chunks_done": trials // CHUNK_CELLS,
            "chunks_total": trials // CHUNK_CELLS,
        },
        engine=ENGINE,
        created_at=now,
        updated_at=now,
        first_pass_cells=[],
        refinement_cells=[],
        workers=1,
        chunk_cells=CHUNK_CELLS,
        cells_layout=2,
        search_space=identity.search_space(spec, surface),
        sampler=sampler,
        versions=versions,
        data_pinned=_pin("A"),
        execution={
            "commission_per_side": spec.execution.commission_per_side,
            "slippage_bps": spec.execution.slippage_bps,
        },
        counts=counts.as_dict(),
        lineage={"parent": None, "root": experiment_id},
    )


__all__ = ["chunk_tables", "known_metrics", "write_fixture"]
