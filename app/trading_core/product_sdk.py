"""Pure product-facing research adapter. No host, credentials or private storage.

Explicitly supplied one-minute datasets use the existing Core quality contract
and engine. This SDK cannot fetch records, change authority or place orders.
"""

from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import Field

from trading_core.research.contracts import Bar, Experiment, LabLimits
from trading_core.research.data import digest, encoded, quality
from trading_core.research.engine import run_engine
from trading_core.work import Record

SDK_FILES = (
    "app/trading_core/__init__.py",
    "app/trading_core/work.py",
    "app/trading_core/product_sdk.py",
    "app/trading_core/market.py",
    "app/trading_core/research/__init__.py",
    "app/trading_core/research/contracts.py",
    "app/trading_core/research/calendar.py",
    "app/trading_core/research/data.py",
    "app/trading_core/research/engine.py",
    "app/trading_core/research/planning.py",
)
CONTRACT = "core.product-research.v1"


class ResearchInput(Record):
    owner: Literal["triad", "aegis"]
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    mode: Literal["FIXTURE", "SIMULATED", "REAL"]
    start: datetime
    end: datetime
    bars: tuple[Bar, ...] = Field(min_length=3, max_length=20000)


class ProductResearch:
    def __init__(self, owner):
        if owner not in {"triad", "aegis"}:
            raise ValueError("Explicit product owner required")
        self.owner = owner

    def frame(self, supplied: ResearchInput):
        supplied = ResearchInput.model_validate(supplied)
        if supplied.owner != self.owner:
            raise PermissionError("Research input belongs to another product")
        if supplied.start >= supplied.end:
            raise ValueError("Nonempty research window required")
        symbols = sorted({bar.symbol for bar in supplied.bars})
        rows = [bar.model_dump(mode="json") for bar in supplied.bars]
        if len(encoded(rows)) > LabLimits().max_bytes:
            raise ValueError("Research input exceeds Core data capacity")
        for bar in supplied.bars:
            if bar.dataset_version != supplied.dataset_version or not all(
                (bar.source, bar.source_symbol, bar.provenance_id)
            ):
                raise ValueError("Retain consistent dataset version and source provenance")
        for symbol in symbols:
            report, _ = quality(
                [row for row in rows if row["symbol"] == symbol],
                symbol,
                supplied.start,
                supplied.end,
            )
            if report["status"] != "PASS":
                raise ValueError("Core research data contract failed: " + str(report["issues"]))
        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["bar_end"] = frame.timestamp + timedelta(minutes=1)
        # Preserve input ordering: this adapter does not silently sort or repair.
        if not frame.timestamp.is_monotonic_increasing:
            raise ValueError("Research bars must be ordered across symbols")
        return frame

    def run(
        self, supplied: ResearchInput, experiment: Experiment, *, strategy=None, guard=lambda: None
    ):
        supplied = ResearchInput.model_validate(supplied)
        experiment = Experiment.model_validate(experiment)
        if (
            experiment.dataset_id != supplied.dataset_id
            or experiment.dataset_version != supplied.dataset_version
            or experiment.timeframe != "1m"
            or set(experiment.symbols) != {bar.symbol for bar in supplied.bars}
            or experiment.start_time < supplied.start
            or experiment.end_time > supplied.end
        ):
            raise ValueError(
                "Experiment must resolve the exact supplied dataset and one-minute contract"
            )
        guard()
        result = run_engine(self.frame(supplied), experiment, guard=guard, strategy=strategy)
        return {
            "contract": CONTRACT,
            "owner": self.owner,
            "dataset_id": supplied.dataset_id,
            "dataset_version": supplied.dataset_version,
            "dataset_sha256": digest(encoded([b.model_dump(mode="json") for b in supplied.bars])),
            "experiment_id": experiment.experiment_id,
            "mode": supplied.mode,
            "provenance_scope": "CALLER_SUPPLIED; structural quality checks do not certify market source or publish canonical data",
            "strategy": "PRODUCT_SUPPLIED" if strategy is not None else experiment.strategy_version,
            "results": result,
            "limitations": [
                "No broker or stored-record access",
                "Fixture strategies establish engine behavior, not a trading edge",
                "One-minute XNYS regular-session contract; calendar currently covers 2026",
            ],
        }
