"""Plateau walk-forward studies (Mission 8 spec §4–6): does peaks to plateaus hold out of sample?

A study belongs to one finished experiment and inherits its pinned spec, surface, objective,
tolerance, budget, seed and timeframe. On each chosen symbol it cuts rolling windows; each
window maps the surface in-sample, chooses by the experiment's analysis, and trades three rules
on the bars that follow: the plateau rule (under test), the peak rule and the frozen centre.
This module holds the request, the plan, the document and the job kind; the per-window rules,
chains and the report are pure functions in `study_rules.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from products.aegis.backtest import MIN_BARS, BacktestSettings
from products.aegis.experiments import ExperimentDocument
from products.aegis.strategy import StrategySpec
from products.aegis.surface import (
    KERNEL_MS_PER_BAR,
    Budget,
    Lever,
    Surface,
    build_grid,
    effective_workers,
)
from products.aegis.surface import plan as plan_surface
from products.aegis.walkforward import MIN_OOS_BARS, cut_windows

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


__all__ = [
    "DEFAULT_SYMBOLS",
    "UNFINISHED",
    "StudyDocument",
    "StudyPlan",
    "StudyRequest",
    "SymbolPlan",
    "plan_study",
    "window_lengths",
]
