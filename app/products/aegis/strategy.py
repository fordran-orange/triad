"""Aegis strategy-control contracts.

The first product treats direction and time as first-class dimensions. Long and short
logic are independently configurable; temporal windows are data carried by the strategy,
not UI-only filters.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"


class WindowMode(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ANALYZE = "analyze"
    MODIFY_RISK = "modify_risk"


class IndicatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str
    length: int = Field(gt=0)
    source: str = "close"
    overlay: bool = True


class RuleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: str
    operator: str
    right: str
    timing: str = "bar_close"


class StrategySide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Direction
    enabled: bool = True
    entry: RuleSpec
    exit: RuleSpec


class ClockWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    start: str
    end: str
    mode: WindowMode = WindowMode.ANALYZE


class EventWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    enabled: bool = False
    minutes_before: int = Field(default=0, ge=0)
    minutes_after: int = Field(default=0, ge=0)
    mode: WindowMode = WindowMode.ANALYZE


class MarketCrossover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    enabled: bool = False
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


class OptimizationParameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    enabled: bool = True
    start: float
    stop: float
    step: float = Field(gt=0)


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    version: int = 1
    description: str
    indicators: list[IndicatorSpec]
    long_side: StrategySide
    short_side: StrategySide
    temporal: TemporalContext
    execution: ExecutionSpec
    optimization: list[OptimizationParameter]


def default_strategy() -> StrategySpec:
    """Reference strategy used to validate the Aegis product and future backtester."""
    return StrategySpec(
        id="ema9-sma30-cross-v1",
        name="9 EMA / 30 SMA Cross",
        description="Simple asymmetric-capable crossover used as Aegis' reference strategy.",
        indicators=[
            IndicatorSpec(id="ema_9", kind="EMA", length=9),
            IndicatorSpec(id="sma_30", kind="SMA", length=30),
        ],
        long_side=StrategySide(
            direction=Direction.LONG,
            entry=RuleSpec(left="ema_9", operator="crosses_above", right="sma_30"),
            exit=RuleSpec(left="ema_9", operator="crosses_below", right="sma_30"),
        ),
        short_side=StrategySide(
            direction=Direction.SHORT,
            entry=RuleSpec(left="ema_9", operator="crosses_below", right="sma_30"),
            exit=RuleSpec(left="ema_9", operator="crosses_above", right="sma_30"),
        ),
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
                MarketCrossover(id="london_new_york", label="London / New York overlap"),
                MarketCrossover(id="cash_open", label="US futures / cash open"),
            ],
        ),
        execution=ExecutionSpec(),
        optimization=[
            OptimizationParameter(path="indicators.ema_9.length", start=5, stop=20, step=1),
            OptimizationParameter(path="indicators.sma_30.length", start=20, stop=100, step=5),
        ],
    )
