"""Surfaces and the planner (Mission 6 spec §5).

A surface is 1 to 10 parameter paths across both sides of a pinned strategy, each with a value
list. The grid is their cartesian product, addressed by a mixed-radix index and never
enumerated to plan (plan ruling P1): counts are products, and validity is decided per indicator
from the small table of that indicator's own parameter combinations. The planner prices a grid
against a budget, decides exhaustive or sampled, and lists the ways back into scope.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import product
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from products.aegis.backtest import MIN_BARS
from products.aegis.kinds import kind_info, warmup
from products.aegis.optimize import step_decimals
from products.aegis.strategy import (
    LEVEL_FIELDS,
    IndicatorSpec,
    StrategySpec,
    _resolve_path,
    apply_parameters,
)

KERNEL_MS_PER_BAR = 0.01  # the starting price per cell-bar before any experiment has run
SIDE_KEYS = ("long_side", "short_side")
MAX_PARAMETERS = 10
TIMEFRAMES = ("1m", "15m", "30m", "1h", "1D")
MINUTES = {"1m": 1, "15m": 15, "30m": 30, "1h": 60, "1D": 390}
_NUMBER = re.compile(r"\s*-?\d+(?:\.\d+)?")


def effective_workers(max_workers: int) -> float:
    return max_workers * 0.8


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
        decimals = step_decimals(self.step)
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
    """`(side_key, indicator_id, field)` for `<side>.indicators.<id>.length|params.<name>`, or
    `(side_key, "", level)` for `<side>.stop_loss_pct|take_profit_pct` (Mission 13)."""
    parts = path.split(".")
    if len(parts) == 2 and parts[0] in SIDE_KEYS and parts[1] in LEVEL_FIELDS:
        side = getattr(spec, parts[0])
        if getattr(side, parts[1]) is None:
            raise ValueError(
                f"{path}: the {side.direction.value} side has no {LEVEL_FIELDS[parts[1]]} to range"
            )
        if not side.enabled:
            raise ValueError(f"{path} is on the disabled {parts[0].split('_')[0]} side")
        return parts[0], "", parts[1]
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
    if field in LEVEL_FIELDS:
        return False
    indicator = getattr(spec, side_key).indicator(identifier)
    return field.split(".", 1)[1] in kind_info(indicator.kind).integer_params


def current_value(spec: StrategySpec, path: str) -> float:
    side_key, identifier, field = resolve_path(spec, path)
    if field in LEVEL_FIELDS:
        return float(getattr(getattr(spec, side_key), field))
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

    @property
    def strides(self) -> tuple[int, ...]:
        """Mixed-radix strides: the first path varies slowest."""
        strides = []
        stride = 1
        for n in reversed(self.shape):
            strides.append(stride)
            stride *= n
        return tuple(reversed(strides))

    def positions(self, index: int) -> tuple[int, ...]:
        """The value-list position of each parameter for a cell."""
        if not 0 <= index < self.size:
            raise IndexError(index)
        out = []
        remainder = index
        for n in reversed(self.shape):
            out.append(remainder % n)
            remainder //= n
        return tuple(reversed(out))

    def index_at(self, positions: tuple[int, ...]) -> int:
        index = 0
        for position, n in zip(positions, self.shape, strict=True):
            index = index * n + position
        return index

    def neighbours(self, index: int) -> list[int]:
        """Cells one step away in exactly one parameter (the exhaustive neighbour rule)."""
        positions = self.positions(index)
        out = []
        for k, stride in enumerate(self.strides):
            if positions[k] > 0:
                out.append(index - stride)
            if positions[k] < self.shape[k] - 1:
                out.append(index + stride)
        return out

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
        return apply_params(spec, params)


def apply_params(spec: StrategySpec, params: dict[str, float]) -> StrategySpec:
    """The spec with side-prefixed parameter paths applied; `ValueError` for an unknown path and
    Pydantic's `ValidationError` for an invalid combination."""
    per_side: dict[str, dict[str, float]] = {}
    for path, value in params.items():
        parts = path.split(".", 1)
        if len(parts) != 2 or parts[0] not in SIDE_KEYS:
            raise ValueError(f"unknown parameter path {path!r}")
        per_side.setdefault(parts[0], {})[parts[1]] = value
    update = {
        side_key: apply_parameters(getattr(spec, side_key), values)
        for side_key, values in per_side.items()
    }
    return spec.model_copy(update=update)


def skip_reason_of(exc: ValidationError) -> str:
    """The validator's message without its numbers, as the grid's skip tables spell it."""
    return _reason(exc)


def _level_reason(fields: list[str], combination: tuple[float, ...]) -> str | None:
    """Why a combination of stop / target percentages is invalid, or None."""
    for field, value in zip(fields, combination, strict=True):
        if not math.isfinite(value) or value <= 0 or (field == "stop_loss_pct" and value >= 100):
            return f"{LEVEL_FIELDS[field]} out of range"
    return None


def build_grid(spec: StrategySpec, surface: Surface, bars: int | None = None) -> Grid:
    """The grid over a pinned spec. With `bars`, a combination whose warm-up the engine would
    refuse on that many bars (backtest._check_warmup) is skipped as "insufficient bars"."""
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
        if not identifier:  # Mission 13: the side's stop loss / take profit percentages
            tables.append(
                {
                    combination: _level_reason([fields[k][2] for k in members], combination)
                    for combination in product(*(values[k] for k in members))
                }
            )
            continue
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
                validated = IndicatorSpec.model_validate(candidate)
            except ValidationError as exc:
                table[combination] = _reason(exc)
                continue
            needed = warmup(validated.kind, validated.length, validated.effective_params())
            table[combination] = (
                "insufficient bars" if bars is not None and bars <= needed else None
            )
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


def lhs_stratum(position: int, n: int, count: int) -> int:
    """Which of `count` strata over `n` value positions a position falls in: stratum j spans
    positions [j*n//count, (j+1)*n//count); strata may be empty when n < count."""
    stratum = position * count // n
    while stratum > 0 and stratum * n // count > position:
        stratum -= 1
    while stratum + 1 < count and (stratum + 1) * n // count <= position:
        stratum += 1
    return stratum


def latin_hypercube(grid: Grid, count: int, seed: int) -> list[int]:
    """`count` distinct valid cells by a Latin hypercube over the discrete grid (spec §5.4): per
    parameter, `count` strata over its value list and a seeded permutation choosing one stratum
    per draw; a draw landing on a skipped or repeated cell is redrawn inside its strata, then
    anywhere, up to ten times the count in all. May return fewer cells than asked."""
    rng = random.Random(seed)
    d = len(grid.shape)
    permutations = [rng.sample(range(count), count) for _ in range(d)]
    chosen: list[int] = []
    seen: set[int] = set()
    tries = 0
    limit = 10 * count

    def draw(i: int, anywhere: bool) -> int:
        positions = []
        for k, n in enumerate(grid.shape):
            if anywhere:
                positions.append(rng.randrange(n))
                continue
            stratum = permutations[k][i]
            lo = stratum * n // count
            hi = max(lo + 1, (stratum + 1) * n // count)
            positions.append(rng.randrange(lo, min(hi, n)))
        return grid.index_at(tuple(positions))

    for i in range(count):
        attempts = 0
        while tries < limit:
            tries += 1
            index = draw(i, anywhere=attempts >= 10)
            attempts += 1
            if index in seen or not grid.is_valid(index):
                continue
            seen.add(index)
            chosen.append(index)
            break
        if tries >= limit:
            break
    return chosen


def _distance(grid: Grid, a: int, b: int) -> float:
    pa_, pb = grid.positions(a), grid.positions(b)
    return math.sqrt(
        sum(((x - y) / max(n - 1, 1)) ** 2 for x, y, n in zip(pa_, pb, grid.shape, strict=True))
    )


def refinement_cells(
    grid: Grid, run_cells: dict[int, float | None], plateaus: list[dict], budget: int
) -> list[int]:
    """Unexplored valid cells within one step of the top three plateaus' cells, nearest each
    plateau's centre first; with no plateau, the neighbours of the ten best run cells (spec §5.4).
    Never a cell already run; at most `budget`."""
    run = set(run_cells)
    chosen: list[int] = []
    taken: set[int] = set()

    def admit(candidates: list[int]) -> None:
        for index in candidates:
            if len(chosen) >= budget:
                return
            if index in run or index in taken or not grid.is_valid(index):
                continue
            taken.add(index)
            chosen.append(index)

    for plateau in plateaus[:3]:
        members = list(plateau.get("cells", []))
        centre = plateau.get("centre", {}).get("cell", members[0] if members else None)
        if centre is None:
            continue
        ring = sorted(
            {n for member in members for n in grid.neighbours(member)},
            key=lambda index: (_distance(grid, index, centre), index),
        )
        admit(ring)
        if len(chosen) >= budget:
            return chosen
    if not plateaus:
        ranked = sorted(
            (cell for cell, value in run_cells.items() if value is not None),
            key=lambda cell: (-float(run_cells[cell]), cell),
        )
        for best in ranked[:10]:
            admit(
                sorted(
                    grid.neighbours(best), key=lambda index: (_distance(grid, index, best), index)
                )
            )
            if len(chosen) >= budget:
                break
    return chosen


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
    blocks: int = 0  # screening blocks per configuration (Lab Phase 3, §7.3a); 0 without
    evaluations: int  # engine evaluations: planned_runs × (blocks + 1) (§6.4)
    levers: list[Lever] = Field(default_factory=list)
    price_source: Literal["measured", "starting_guess"] = "starting_guess"


def block_bounds(n_bars: int, k: int) -> list[tuple[int, int]]:
    """The `k` screening blocks of `n_bars` bars (Lab Phase 3, spec §7.3a): contiguous
    `[start, end)` ranges of `n_bars // k` bars, the last taking the remainder; none for k = 0.
    Block b is scored from its start on the bars up to its end, the earlier ones its warm-up."""
    if k <= 0:
        return []
    size = n_bars // k
    return [(b * size, n_bars if b == k - 1 else (b + 1) * size) for b in range(k)]


def configuration_bars(bars: int, blocks: int) -> int:
    """The bars one configuration's evaluations run on: the whole range (block 0) plus, for
    each screening block, the bars up to its end (decision 1: ≈ 3.5 × bars at K = 4)."""
    return bars + sum(end for _, end in block_bounds(bars, blocks))


def _check_blocks(bars: int, blocks: int) -> None:
    """A screening block shorter than the engine's minimum could never be scored: refused."""
    if blocks and bars // blocks < MIN_BARS:
        raise ValueError(
            f"blocks: {blocks} blocks of {bars} bars leave {bars // blocks} per block, "
            f"under the {MIN_BARS}-bar minimum"
        )


def _core(
    grid: Grid,
    budget: Budget,
    bars: int,
    ms_per_cell_bar: float,
    max_workers: int,
    blocks: int = 0,
) -> dict:
    """The plan's counts and price. A configuration costs every one of its evaluations' bars
    (`configuration_bars`), so a time budget buys configurations at their whole price."""
    workers = effective_workers(max_workers)
    per_configuration = configuration_bars(bars, blocks)
    per_run = per_configuration * ms_per_cell_bar / 1000.0 / workers
    caps = []
    if budget.runs is not None:
        caps.append(budget.runs)
    if budget.seconds is not None:
        caps.append(int(budget.seconds * workers * 1000.0 / (per_configuration * ms_per_cell_bar)))
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
        "blocks": blocks,
        "evaluations": planned * (blocks + 1),
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
    blocks: int = 0,
) -> list[Lever]:
    levers: list[Lever] = []
    per_configuration = configuration_bars(bars, blocks)

    def priced(
        kind, parameter, label, *, new_surface=None, new_budget=None, new_bars=None, hint=None
    ):
        g = build_grid(spec, new_surface, bars) if new_surface is not None else grid
        try:
            core = _core(
                g, new_budget or budget, new_bars or bars, ms_per_cell_bar, max_workers, blocks
            )
            fits = core["mode"] == "exhaustive"
            estimate = core["estimate_seconds"]
        except ValueError:  # the lever leaves the grid over a budget too small to sample
            fits, estimate = (
                False,
                g.valid_count
                * per_configuration
                * ms_per_cell_bar
                / 1000.0
                / effective_workers(max_workers),
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
    price_source: Literal["measured", "starting_guess"] = "starting_guess",
    blocks: int = 0,
) -> Plan:
    """Exhaustive when every valid cell fits the budget, sampled otherwise, with the levers that
    bring an over-budget grid back into scope (spec §5.3–5.5). `price_source` says whether
    `ms_per_cell_bar` was measured on this host or is the starting guess. With `blocks` = K, each
    configuration is priced on all its K + 1 evaluations (Lab Phase 3), and a block shorter than
    the engine's minimum is refused."""
    _check_blocks(bars, blocks)
    grid = build_grid(spec, surface, bars)
    core = _core(grid, budget, bars, ms_per_cell_bar, max_workers, blocks)
    levers = (
        []
        if core["mode"] == "exhaustive"
        else _levers(
            spec, surface, grid, budget, bars, ms_per_cell_bar, max_workers, timeframe, blocks
        )
    )
    return Plan(**core, levers=levers, price_source=price_source)


__all__ = [
    "KERNEL_MS_PER_BAR",
    "MAX_PARAMETERS",
    "Budget",
    "Grid",
    "Lever",
    "Parameter",
    "Plan",
    "Surface",
    "apply_params",
    "block_bounds",
    "build_grid",
    "configuration_bars",
    "current_value",
    "effective_workers",
    "latin_hypercube",
    "lhs_stratum",
    "plan",
    "refinement_cells",
    "resolve_path",
    "skip_reason_of",
]
