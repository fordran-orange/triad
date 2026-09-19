from datetime import UTC, datetime
from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator, model_validator

from trading_core.work import Record, now, uid


class LabLimits(Record):
    max_rows: int = Field(default=5000, ge=10, le=20000)
    max_bytes: int = Field(default=2000000, ge=1000, le=10000000)
    memory_mb: int = Field(default=128, ge=32, le=256)
    runtime_seconds: int = Field(default=30, ge=1, le=120)
    max_combinations: int = Field(default=8, ge=1, le=16)
    parallel_backtests: Literal[1] = 1
    worker_count: Literal[1] = 1


class Bar(Record):
    timestamp: datetime
    symbol: str = Field(pattern=r"^[A-Z0-9_-]{1,20}$")
    open: float = Field(gt=0, allow_inf_nan=False)
    high: float = Field(gt=0, allow_inf_nan=False)
    low: float = Field(gt=0, allow_inf_nan=False)
    close: float = Field(gt=0, allow_inf_nan=False)
    volume: float = Field(ge=0, allow_inf_nan=False)
    source: str
    source_symbol: str
    timezone: str
    exchange: str = "XNYS"
    asset_class: Literal["equity"] = "equity"
    ingested_at: datetime
    dataset_version: str
    provenance_id: str
    trade_count: int | None = Field(default=None, ge=0)
    vwap: float | None = Field(default=None, gt=0)
    adjustment_status: Literal["UNADJUSTED"] = "UNADJUSTED"
    session: Literal["REGULAR"] = "REGULAR"
    currency: Literal["USD"] = "USD"

    @field_validator("timestamp", "ingested_at")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def coherent(self):
        if self.timestamp.second or self.timestamp.microsecond:
            raise ValueError("Minute boundary required")
        if self.high < max(self.open, self.low, self.close) or self.low > min(
            self.open, self.close
        ):
            raise ValueError("Invalid OHLC relationship")
        if self.ingested_at < self.timestamp:
            raise ValueError("Ingestion precedes data")
        return self


class DatasetManifest(Record):
    dataset_id: str = Field(default_factory=uid)
    dataset_version: str
    symbols: tuple[str, ...]
    asset_class: str = "equity"
    resolution: Literal["1m", "5m", "15m", "30m", "1h", "1d"] = "1m"
    start_time: datetime
    end_time: datetime
    row_count: int
    source: str
    mode: Literal["REAL", "FIXTURE", "SIMULATED", "UNAVAILABLE"]
    raw_sources: tuple[dict, ...]
    canonical_paths: tuple[str, ...]
    schema_version: str = "triad.ohlcv.v2"
    created_at: datetime = Field(default_factory=now)
    checksum: str
    file_checksums: dict[str, str]
    quality_status: Literal["PASS", "FAIL"]
    known_gaps: tuple[str, ...] = ()
    adjustment_policy: str = (
        "UNADJUSTED; corporate actions unsupported, no retrospective adjustment"
    )
    timezone_policy: str = (
        "UTC interval start; source America/New_York retained; regular session only"
    )
    creator: str = "operator"
    provenance: dict
    transformations: tuple[str, ...] = ()
    calendar_version: str = "XNYS-2026-v1"
    size_bytes: int


class Hypothesis(Record):
    hypothesis_id: str = Field(default_factory=uid)
    statement: str
    created_by: str = "operator"
    created_at: datetime = Field(default_factory=now)
    origin: str = "ENGINE_VALIDATION"
    rationale: str
    expected_behavior: str
    falsification_condition: str
    status: Literal[
        "PROPOSED",
        "TESTABLE",
        "TESTING",
        "SUPPORTED",
        "NOT_SUPPORTED",
        "INCONCLUSIVE",
        "SUPERSEDED",
    ] = "TESTABLE"
    evidence_for: tuple[str, ...] = ()
    evidence_against: tuple[str, ...] = ()


class Costs(Record):
    fixed: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    per_share: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
    bps: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)


class Slippage(Record):
    bps: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    spread_bps: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)


class Sizing(Record):
    kind: Literal["fixed_shares", "fixed_dollars", "portfolio_percentage"] = "fixed_shares"
    value: float = Field(default=10, gt=0, le=100000, allow_inf_nan=False)


class Partition(Record):
    name: Literal["training", "validation", "test"]
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def valid(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("Partition must be aware and nonempty [start,end)")
        return self


class Experiment(Record):
    experiment_id: str = Field(default_factory=uid)
    name: str
    description: str
    hypothesis: str
    created_by: str = "CODEX"
    created_at: datetime = Field(default_factory=now)
    status: str = "DEFINED"
    strategy_version: Literal["periodic-fixture-v1", "hold-fixture-v1"] = "periodic-fixture-v1"
    dataset_id: str
    dataset_version: str
    symbols: tuple[str, ...]
    timeframe: Literal["1m", "5m", "15m", "30m", "1h", "1d"] = "1m"
    start_time: datetime
    end_time: datetime
    parameters: dict[str, int] = Field(default_factory=lambda: {"period": 20, "hold": 5})
    directions: tuple[Literal["LONG", "SHORT"], ...] = ("LONG", "SHORT")
    fees_model: Costs = Field(default_factory=Costs)
    slippage_model: Slippage = Field(default_factory=Slippage)
    position_sizing_model: Sizing = Field(default_factory=Sizing)
    execution_model: Literal["CLOSE_SIGNAL_NEXT_OPEN"] = "CLOSE_SIGNAL_NEXT_OPEN"
    initial_capital: float = Field(default=10000, gt=0, allow_inf_nan=False)
    random_seed: int = 42
    code_commit: str
    environment: dict[str, str]
    acceptance_criteria: tuple[str, ...]
    partitions: tuple[Partition, ...]
    selected_partition: Literal["training", "validation", "test"] = "test"

    @model_validator(mode="after")
    def validate_windows(self):
        if (
            self.start_time.tzinfo is None
            or self.end_time.tzinfo is None
            or self.start_time >= self.end_time
        ):
            raise ValueError("Aware nonempty experiment window required")
        if (
            not self.symbols
            or not self.directions
            or len(set(self.directions)) != len(self.directions)
        ):
            raise ValueError("Distinct directions and symbols required")
        if (
            set(self.parameters) != {"period", "hold"}
            or not 1 <= self.parameters["hold"] < self.parameters["period"] <= 1000
        ):
            raise ValueError("Bounded periodic fixture parameters required")
        windows = sorted(self.partitions, key=lambda p: p.start)
        if len({p.name for p in windows}) != len(windows) or self.selected_partition not in {
            p.name for p in windows
        }:
            raise ValueError("Distinct named partitions required")
        if any(p.start < self.start_time or p.end > self.end_time for p in windows):
            raise ValueError("Partitions exceed experiment window")
        if any(a.end > b.start for a, b in pairwise(windows)):
            raise ValueError("Overlapping partitions")
        if (
            self.position_sizing_model.kind == "portfolio_percentage"
            and self.position_sizing_model.value > 1
        ):
            raise ValueError("Portfolio fraction must be <=1")
        return self


class BacktestRun(Record):
    run_id: str = Field(default_factory=uid)
    experiment_id: str
    parameters: dict
    start_time: datetime
    end_time: datetime
    code_commit: str
    dataset_version: str
    started_at: datetime = Field(default_factory=now)
    completed_at: datetime | None = None
    status: str = "RUNNING"
    runtime: float = 0
    peak_memory_bytes: int = 0
    storage_bytes: int = 0
    result_artifacts: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    logs: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    work_item_id: str
    content_hash: str | None = None
