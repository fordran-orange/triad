"""Aegis strategy-control contracts.

Direction and time are first-class. Each side (long, short) owns its indicators, entry and
exit rules, enabled state and optimization ranges, so the optimizer can settle on different
parameters per side; symmetry is a UI convenience, never a model requirement. Temporal windows
and market crossovers are data carried by the strategy, not UI-only filters.
"""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

from products.aegis.kinds import kind_info, warmup

TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
ID_PATTERN = r"^[a-z][a-z0-9_]*$"  # never ambiguous with a numeric constant operand


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class WindowMode(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ANALYZE = "analyze"
    MODIFY_RISK = "modify_risk"


class IndicatorSpec(BaseModel):
    """One indicator a side computes. `kind` names an entry of `kinds.KINDS`; `params` holds
    that kind's extra parameters (missing ones take the defaults) and is left out of dumps when
    empty, so every strategy written before Mission 5 serializes byte-identically. `overlay` is
    kept so older documents parse; the chart places series by the kind's pane."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=ID_PATTERN)
    kind: str
    length: int = Field(gt=0)
    source: str = "close"
    overlay: bool = True
    params: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_kind_and_parameters(self):
        info = kind_info(self.kind)
        name = self.kind.upper()
        for key, value in self.params.items():
            if key not in info.params:
                raise ValueError(f"{name} has no parameter {key!r}")
            if not math.isfinite(value):
                raise ValueError(f"{name} parameter {key} must be finite, got {value}")
            if value <= 0:
                raise ValueError(f"{name} parameter {key} must be positive, got {value}")
            if key in info.integer_params and not float(value).is_integer():
                raise ValueError(f"{name} parameter {key} must be a whole number, got {value}")
        if name == "MACD":
            slow = self.effective_params()["slow"]
            if self.length >= slow:
                raise ValueError(f"MACD fast length {self.length} must be below slow {slow:g}")
        return self

    @model_serializer(mode="wrap")
    def _omit_empty_params(self, handler):
        data = handler(self)
        if isinstance(data, dict) and not data.get("params"):
            data.pop("params", None)
        return data

    def effective_params(self) -> dict[str, float]:
        """The kind's defaults overlaid with this spec's own parameters."""
        return {**kind_info(self.kind).params, **self.params}


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    operator: str
    right: str
    timing: str = "bar_close"


class OptimizationParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    enabled: bool = True
    start: float
    stop: float
    step: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered_and_integral(self):
        if self.start > self.stop:
            raise ValueError(f"{self.path}: start {self.start} above stop {self.stop}")
        if self.path.endswith(".length") and not all(
            float(v).is_integer() for v in (self.start, self.stop, self.step)
        ):
            raise ValueError(f"{self.path}: length ranges need integer start, stop and step")
        return self


class StrategySide(BaseModel):
    """One direction's complete logic: its own indicators, rules, switch and ranges."""

    model_config = ConfigDict(extra="forbid")
    direction: Direction
    enabled: bool = True
    indicators: list[IndicatorSpec] = Field(default_factory=list)
    entry: RuleSpec
    exit: RuleSpec
    optimization: list[OptimizationParameter] = Field(default_factory=list)

    @model_validator(mode="after")
    def rules_reference_owned_indicators(self):
        ids = [i.id for i in self.indicators]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate indicator id")
        for rule_name, rule in (("entry", self.entry), ("exit", self.exit)):
            for operand in (rule.left, rule.right):
                if operand not in ids:
                    raise ValueError(f"{rule_name} rule references unknown indicator {operand!r}")
        for parameter in self.optimization:
            identifier, field = _resolve_path(self, parameter.path)
            whole = field == "length" or (
                field.split(".", 1)[1] in kind_info(self.indicator(identifier).kind).integer_params
            )
            if whole and not all(
                float(v).is_integer() for v in (parameter.start, parameter.stop, parameter.step)
            ):
                raise ValueError(
                    f"{parameter.path}: ranges of whole-number parameters need integer start, "
                    "stop and step"
                )
        return self

    def indicator(self, identifier: str) -> IndicatorSpec:
        for spec in self.indicators:
            if spec.id == identifier:
                return spec
        raise KeyError(identifier)


def _resolve_path(side: StrategySide, path: str) -> tuple[str, str]:
    """Validate a side-relative path, `indicators.<id>.length` or
    `indicators.<id>.params.<name>`; return (id, "length") or (id, "params.<name>")."""
    parts = path.split(".")
    if len(parts) == 3 and parts[0] == "indicators" and parts[2] == "length":
        field = "length"
    elif len(parts) == 4 and parts[0] == "indicators" and parts[2] == "params":
        field = f"params.{parts[3]}"
    else:
        raise ValueError(f"unknown parameter path {path!r}")
    spec = next((i for i in side.indicators if i.id == parts[1]), None)
    if spec is None or (field != "length" and parts[3] not in kind_info(spec.kind).params):
        raise ValueError(f"unknown parameter path {path!r}")
    return parts[1], field


def apply_parameters(side: StrategySide, values: dict[str, float]) -> StrategySide:
    """Return a new side with the given side-relative parameter paths set. Never mutates.
    Lengths and whole-number parameters are rounded; other parameters are kept as given."""
    data = side.model_dump(mode="json")
    for path, value in values.items():
        identifier, field = _resolve_path(side, path)
        for spec in data["indicators"]:
            if spec["id"] != identifier:
                continue
            if field == "length":
                spec["length"] = round(float(value))
            else:
                name = field.split(".", 1)[1]
                whole = name in kind_info(spec["kind"]).integer_params
                spec.setdefault("params", {})[name] = (
                    float(round(float(value))) if whole else float(value)
                )
    return StrategySide.model_validate(data)


def side_warmup(side: StrategySide, ranges: bool = True) -> int:
    """Bars after which every indicator of the side has a value; with `ranges`, at the far end
    of every enabled optimization range (warm-up never shrinks as a length or parameter grows)."""
    longest = 0
    for spec in side.indicators:
        length, params = spec.length, spec.effective_params()
        for parameter in side.optimization if ranges else ():
            if not parameter.enabled:
                continue
            identifier, field = _resolve_path(side, parameter.path)
            if identifier != spec.id:
                continue
            if field == "length":
                length = max(length, math.ceil(parameter.stop))
            else:
                name = field.split(".", 1)[1]
                params[name] = max(params[name], float(parameter.stop))
        longest = max(longest, warmup(spec.kind, length, params))
    return longest


class ClockWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)
    mode: WindowMode = WindowMode.ANALYZE


class EventWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    enabled: bool = False
    minutes_before: int = Field(default=0, ge=0)
    minutes_after: int = Field(default=0, ge=0)
    mode: WindowMode = WindowMode.ANALYZE


class MarketCrossover(BaseModel):
    """A market-transition window defined on the strategy clock (ANALYZE-only in this slice)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    enabled: bool = True
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)
    mode: WindowMode = WindowMode.ANALYZE


class TemporalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "America/New_York"
    regular_session_only: bool = True
    clock_windows: list[ClockWindow]
    event_windows: list[EventWindow]
    market_crossovers: list[MarketCrossover]


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_timing: str = "bar_close"
    fill_timing: str = "next_bar_open"
    commission_per_side: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    version: int = 1
    description: str
    long_side: StrategySide
    short_side: StrategySide
    temporal: TemporalContext
    execution: ExecutionSpec


def _reference_side(direction: Direction) -> StrategySide:
    above, below = "crosses_above", "crosses_below"
    entry_operator = above if direction is Direction.LONG else below
    exit_operator = below if direction is Direction.LONG else above
    return StrategySide(
        direction=direction,
        indicators=[
            IndicatorSpec(id="ema", kind="EMA", length=9),
            IndicatorSpec(id="sma", kind="SMA", length=30),
        ],
        entry=RuleSpec(left="ema", operator=entry_operator, right="sma"),
        exit=RuleSpec(left="ema", operator=exit_operator, right="sma"),
        optimization=[
            OptimizationParameter(path="indicators.ema.length", start=5, stop=20, step=1),
            OptimizationParameter(path="indicators.sma.length", start=20, stop=100, step=5),
        ],
    )


def default_strategy() -> StrategySpec:
    """Reference strategy used to validate the Aegis product and backtester: 9 EMA / 30 SMA
    cross on both sides, with each side carrying its own parameters and ranges."""
    return StrategySpec(
        id="ema9-sma30-cross-v1",
        name="9 EMA / 30 SMA Cross",
        description="Simple asymmetric-capable crossover used as Aegis' reference strategy.",
        long_side=_reference_side(Direction.LONG),
        short_side=_reference_side(Direction.SHORT),
        temporal=TemporalContext(
            clock_windows=[
                ClockWindow(id="open", label="Opening Window", start="09:30", end="10:00"),
                ClockWindow(id="close", label="Closing Window", start="15:30", end="16:00"),
            ],
            event_windows=[
                EventWindow(event_type="FOMC", minutes_before=120, minutes_after=240),
                EventWindow(event_type="EARNINGS", minutes_before=1440, minutes_after=2880),
                EventWindow(event_type="MACRO_RELEASE", minutes_before=60, minutes_after=120),
                EventWindow(event_type="RUMOR_NEWS", minutes_before=60, minutes_after=240),
            ],
            market_crossovers=[
                MarketCrossover(
                    id="cash_open",
                    label="US futures / cash open",
                    start="09:25",
                    end="09:45",
                ),
                MarketCrossover(
                    id="london_new_york",
                    label="London / New York overlap",
                    start="09:30",
                    end="11:30",
                ),
            ],
        ),
        execution=ExecutionSpec(),
    )
