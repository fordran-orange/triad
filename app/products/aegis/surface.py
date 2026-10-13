"""Surfaces and the planner (Mission 6 spec §5).

A surface is 1 to 10 parameter paths across both sides of a pinned strategy, each with a value
list. The grid is their cartesian product, addressed by a mixed-radix index and never
enumerated to plan (plan ruling P1): counts are products, and validity is decided per indicator
from the small table of that indicator's own parameter combinations. The planner prices a grid
against a budget, decides exhaustive or sampled, and lists the ways back into scope.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import product
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from products.aegis.kinds import kind_info
from products.aegis.strategy import IndicatorSpec, StrategySpec, _resolve_path, apply_parameters

KERNEL_MS_PER_BAR = 0.01  # the starting price per cell-bar before any experiment has run
SIDE_KEYS = ("long_side", "short_side")
MAX_PARAMETERS = 10
TIMEFRAMES = ("1m", "15m", "30m", "1h", "1D")
MINUTES = {"1m": 1, "15m": 15, "30m": 30, "1h": 60, "1D": 390}
_NUMBER = re.compile(r"\s*-?\d+(?:\.\d+)?")


def effective_workers(max_workers: int) -> float:
    return max_workers * 0.8


def _decimals(step: float) -> int:
    text = repr(float(step))
    return len(text.split(".")[1]) if "." in text and "e" not in text else 0


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    start: float
    stop: float
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.stop:
            raise ValueError(f"{self.path}: start {self.start:g} above stop {self.stop:g}")
        return self

    def values(self) -> list[float]:
        count = math.floor((self.stop - self.start) / self.step + 1e-9) + 1
        decimals = _decimals(self.step)
        return [round(self.start + i * self.step, decimals) for i in range(max(count, 0))]


class Surface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameters: list[Parameter]

    @model_validator(mode="after")
    def one_to_ten_distinct(self):
        if not self.parameters:
            raise ValueError("a surface needs at least one parameter")
        if len(self.parameters) > MAX_PARAMETERS:
            raise ValueError(f"at most {MAX_PARAMETERS} parameters")
        seen: set[str] = set()
        for parameter in self.parameters:
            if parameter.path in seen:
                raise ValueError(f"duplicate parameter path '{parameter.path}'")
            seen.add(parameter.path)
        return self

    def paths(self) -> list[str]:
        return [p.path for p in self.parameters]


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: int | None = None
    seconds: float | None = None

    @model_validator(mode="after")
    def at_least_one_positive(self):
        if self.runs is None and self.seconds is None:
            raise ValueError("a budget needs runs or seconds")
        if self.runs is not None and self.runs <= 0:
            raise ValueError("runs must be positive")
        if self.seconds is not None and self.seconds <= 0:
            raise ValueError("seconds must be positive")
        return self


def resolve_path(spec: StrategySpec, path: str) -> tuple[str, str, str]:
    """`(side_key, indicator_id, field)` for `<side>.indicators.<id>.length|params.<name>`."""
    parts = path.split(".")
    if len(parts) < 4 or parts[0] not in SIDE_KEYS or parts[1] != "indicators":
        raise ValueError(f"unknown parameter path {path!r}")
    side = getattr(spec, parts[0])
    try:
        identifier, field = _resolve_path(side, ".".join(parts[1:]))
    except ValueError:
        raise ValueError(f"unknown parameter path {path!r}") from None
    if not side.enabled:
        raise ValueError(f"{path} is on the disabled {parts[0].split('_')[0]} side")
    return parts[0], identifier, field


def _whole_number(spec: StrategySpec, side_key: str, identifier: str, field: str) -> bool:
    if field == "length":
        return True
    indicator = getattr(spec, side_key).indicator(identifier)
    return field.split(".", 1)[1] in kind_info(indicator.kind).integer_params


def current_value(spec: StrategySpec, path: str) -> float:
    side_key, identifier, field = resolve_path(spec, path)
    indicator = getattr(spec, side_key).indicator(identifier)
    if field == "length":
        return float(indicator.length)
    return float(indicator.effective_params()[field.split(".", 1)[1]])


def _check_parameter(spec: StrategySpec, parameter: Parameter) -> tuple[str, str, str]:
    side_key, identifier, field = resolve_path(spec, parameter.path)
    if _whole_number(spec, side_key, identifier, field) and not all(
        float(v).is_integer() for v in (parameter.start, parameter.stop, parameter.step)
    ):
        raise ValueError(
            f"{parameter.path}: ranges of whole-number parameters need integer start, stop and step"
        )
    return side_key, identifier, field


def _reason(exc: ValidationError) -> str:
    message = exc.errors()[0].get("msg", "invalid")
    message = message.removeprefix("Value error, ")
    return _NUMBER.sub("", message).strip()


@dataclass
class Grid:
    """A surface over a pinned spec: mixed-radix cells, per-indicator validity tables."""

    paths: list[str]
    values: list[list[float]]
    shape: tuple[int, ...]
    size: int
    fields: list[tuple[str, str, str]]  # (side_key, indicator_id, field) per path
    groups: list[tuple[str, str, list[int]]]  # (side_key, indicator_id, parameter positions)
    tables: list[dict[tuple[float, ...], str | None]]  # per group: combination -> skip reason
    valid_count: int
    skipped_count: int
    skip_reasons: dict[str, int]

    def cell_values(self, index: int) -> dict[str, float]:
        if not 0 <= index < self.size:
            raise IndexError(index)
        out: dict[str, float] = {}
        remainder = index
        for k in range(len(self.paths) - 1, -1, -1):
            n = self.shape[k]
            out[self.paths[k]] = self.values[k][remainder % n]
            remainder //= n
        return {path: out[path] for path in self.paths}

    def index_of(self, params: dict[str, float]) -> int:
        index = 0
        for k, path in enumerate(self.paths):
            value = params[path]
            position = next(i for i, v in enumerate(self.values[k]) if abs(v - float(value)) < 1e-9)
            index = index * self.shape[k] + position
        return index

    def _combination(self, index: int, positions: list[int]) -> tuple[float, ...]:
        values = self.cell_values(index)
        return tuple(values[self.paths[k]] for k in positions)

    def skip_reason(self, index: int) -> str | None:
        for (_, _, positions), table in zip(self.groups, self.tables, strict=True):
            reason = table[self._combination(index, positions)]
            if reason is not None:
                return reason
        return None

    def is_valid(self, index: int) -> bool:
        return self.skip_reason(index) is None

    def valid_indices_iter(self) -> Iterator[int]:
        for index in range(self.size):
            if self.is_valid(index):
                yield index

    def apply_cell(self, spec: StrategySpec, params: dict[str, float]) -> StrategySpec:
        """The pinned spec with one cell's values applied to both sides."""
        per_side: dict[str, dict[str, float]] = {}
        for k, path in enumerate(self.paths):
            side_key = self.fields[k][0]
            relative = path.split(".", 1)[1]
            per_side.setdefault(side_key, {})[relative] = params[path]
        update = {
            side_key: apply_parameters(getattr(spec, side_key), values)
            for side_key, values in per_side.items()
        }
        return spec.model_copy(update=update)


def build_grid(spec: StrategySpec, surface: Surface) -> Grid:
    fields = [_check_parameter(spec, p) for p in surface.parameters]
    values = [p.values() for p in surface.parameters]
    shape = tuple(len(v) for v in values)
    size = math.prod(shape)
    order: list[tuple[str, str]] = []
    positions: dict[tuple[str, str], list[int]] = {}
    for k, (side_key, identifier, _) in enumerate(fields):
        key = (side_key, identifier)
        if key not in positions:
            order.append(key)
            positions[key] = []
        positions[key].append(k)
    groups = [
        (side_key, identifier, positions[(side_key, identifier)]) for side_key, identifier in order
    ]
    tables: list[dict[tuple[float, ...], str | None]] = []
    for side_key, identifier, members in groups:
        base = getattr(spec, side_key).indicator(identifier).model_dump(mode="json")
        table: dict[tuple[float, ...], str | None] = {}
        for combination in product(*(values[k] for k in members)):
            candidate = {**base, "params": dict(base.get("params", {}))}
            for k, value in zip(members, combination, strict=True):
                field = fields[k][2]
                if field == "length":
                    candidate["length"] = round(float(value))
                else:
                    name = field.split(".", 1)[1]
                    whole = name in kind_info(candidate["kind"]).integer_params
                    candidate["params"][name] = float(round(value)) if whole else float(value)
            try:
                IndicatorSpec.model_validate(candidate)
                table[combination] = None
            except ValidationError as exc:
                table[combination] = _reason(exc)
        tables.append(table)
    group_sizes = [len(t) for t in tables]
    group_valid = [sum(1 for r in t.values() if r is None) for t in tables]
    valid_count = math.prod(group_valid)
    skip_reasons: dict[str, int] = {}
    for g, table in enumerate(tables):
        before = math.prod(group_valid[:g])
        after = math.prod(group_sizes[g + 1 :])
        for reason in table.values():
            if reason is not None:
                skip_reasons[reason] = skip_reasons.get(reason, 0) + before * after
    return Grid(
        paths=surface.paths(),
        values=values,
        shape=shape,
        size=size,
        fields=fields,
        groups=groups,
        tables=tables,
        valid_count=valid_count,
        skipped_count=size - valid_count,
        skip_reasons=skip_reasons,
    )


LeverKind = Literal["coarsen", "narrow", "freeze", "shorten", "coarser_timeframe", "raise_budget"]


class Lever(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: LeverKind
    parameter: str | None
    label: str
    valid_cells: int
    estimate_seconds: float
    fits: bool
    surface: Surface | None = None
    budget: Budget | None = None
    data_hint: str | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["exhaustive", "sampled"]
    grid_cells: int
    valid_cells: int
    skipped: int
    skip_reasons: dict[str, int]
    planned_runs: int
    first_pass: int
    refinement: int
    sampled_fraction: float
    estimate_seconds: float
    ms_per_cell_bar: float
    workers: int
    bars: int
    levers: list[Lever] = Field(default_factory=list)


def _core(grid: Grid, budget: Budget, bars: int, ms_per_cell_bar: float, max_workers: int) -> dict:
    workers = effective_workers(max_workers)
    per_run = bars * ms_per_cell_bar / 1000.0 / workers
    caps = []
    if budget.runs is not None:
        caps.append(budget.runs)
    if budget.seconds is not None:
        caps.append(int(budget.seconds * workers * 1000.0 / (bars * ms_per_cell_bar)))
    cap = min(caps)
    d = len(grid.paths)
    if grid.valid_count <= cap:
        planned, first, refinement, mode = grid.valid_count, grid.valid_count, 0, "exhaustive"
    else:
        planned = cap
        if planned < 2 * d + 1:
            raise ValueError(f"budget too small for a {d}-parameter surface")
        first = math.ceil(2 * planned / 3)
        refinement = planned - first
        mode = "sampled"
    return {
        "mode": mode,
        "grid_cells": grid.size,
        "valid_cells": grid.valid_count,
        "skipped": grid.skipped_count,
        "skip_reasons": grid.skip_reasons,
        "planned_runs": planned,
        "first_pass": first,
        "refinement": refinement,
        "sampled_fraction": planned / grid.valid_count if grid.valid_count else 0.0,
        "estimate_seconds": planned * per_run,
        "ms_per_cell_bar": ms_per_cell_bar,
        "workers": max_workers,
        "bars": bars,
    }


def _with_parameter(surface: Surface, k: int, parameter: Parameter) -> Surface:
    parameters = list(surface.parameters)
    parameters[k] = parameter
    return Surface(parameters=parameters)


def _levers(
    spec: StrategySpec,
    surface: Surface,
    grid: Grid,
    budget: Budget,
    bars: int,
    ms_per_cell_bar: float,
    max_workers: int,
    timeframe: str | None,
) -> list[Lever]:
    levers: list[Lever] = []

    def priced(
        kind, parameter, label, *, new_surface=None, new_budget=None, new_bars=None, hint=None
    ):
        g = build_grid(spec, new_surface) if new_surface is not None else grid
        try:
            core = _core(g, new_budget or budget, new_bars or bars, ms_per_cell_bar, max_workers)
            fits = core["mode"] == "exhaustive"
            estimate = core["estimate_seconds"]
        except ValueError:  # the lever leaves the grid over a budget too small to sample
            fits, estimate = (
                False,
                g.valid_count * bars * ms_per_cell_bar / 1000.0 / effective_workers(max_workers),
            )
        levers.append(
            Lever(
                kind=kind,
                parameter=parameter,
                label=label,
                valid_cells=g.valid_count,
                estimate_seconds=estimate,
                fits=fits,
                surface=new_surface,
                budget=new_budget,
                data_hint=hint,
            )
        )

    for k, parameter in enumerate(surface.parameters):
        values = parameter.values()
        path = parameter.path
        if len(values) > 1:
            coarse = Parameter(
                path=path, start=parameter.start, stop=parameter.stop, step=parameter.step * 2
            )
            priced(
                "coarsen",
                path,
                f"coarsen {path}: step {parameter.step:g} → {parameter.step * 2:g}",
                new_surface=_with_parameter(surface, k, coarse),
            )
        current = current_value(spec, path)
        span = parameter.stop - parameter.start
        lo, hi = current - span / 4, current + span / 4
        inside = [v for v in values if lo - 1e-9 <= v <= hi + 1e-9] or [
            min(values, key=lambda v: abs(v - current))
        ]
        narrow = Parameter(path=path, start=min(inside), stop=max(inside), step=parameter.step)
        priced(
            "narrow",
            path,
            f"narrow {path} to {min(inside):g}–{max(inside):g}",
            new_surface=_with_parameter(surface, k, narrow),
        )
        freeze = Parameter(path=path, start=current, stop=current, step=parameter.step)
        priced(
            "freeze",
            path,
            f"freeze {path} at {current:g}",
            new_surface=_with_parameter(surface, k, freeze),
        )
    priced(
        "shorten",
        None,
        "shorten the date range to its last half",
        new_bars=math.ceil(bars / 2),
        hint="shorten",
    )
    if timeframe in TIMEFRAMES and TIMEFRAMES.index(timeframe) < len(TIMEFRAMES) - 1:
        coarser = TIMEFRAMES[TIMEFRAMES.index(timeframe) + 1]
        ratio = MINUTES[timeframe] / MINUTES[coarser]
        priced(
            "coarser_timeframe",
            None,
            f"coarsen the timeframe to {coarser}",
            new_bars=max(1, math.ceil(bars * ratio)),
            hint=coarser,
        )
    priced(
        "raise_budget",
        None,
        f"raise the budget to {grid.valid_count} runs",
        new_budget=Budget(runs=grid.valid_count),
    )
    return levers


def plan(
    spec: StrategySpec,
    surface: Surface,
    budget: Budget,
    bars: int,
    ms_per_cell_bar: float,
    max_workers: int,
    timeframe: str | None = None,
) -> Plan:
    """Exhaustive when every valid cell fits the budget, sampled otherwise, with the levers that
    bring an over-budget grid back into scope (spec §5.3–5.5)."""
    grid = build_grid(spec, surface)
    core = _core(grid, budget, bars, ms_per_cell_bar, max_workers)
    levers = (
        []
        if core["mode"] == "exhaustive"
        else _levers(spec, surface, grid, budget, bars, ms_per_cell_bar, max_workers, timeframe)
    )
    return Plan(**core, levers=levers)


__all__ = [
    "KERNEL_MS_PER_BAR",
    "MAX_PARAMETERS",
    "Budget",
    "Grid",
    "Lever",
    "Parameter",
    "Plan",
    "Surface",
    "build_grid",
    "current_value",
    "effective_workers",
    "plan",
    "resolve_path",
]
