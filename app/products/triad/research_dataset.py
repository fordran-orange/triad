"""Supplied data preparation; structural acceptance never certifies its source.

Identity: SHA-256 of UTF-8 json.dumps(payload, sort_keys=True,
separators=(',', ':'), ensure_ascii=False, allow_nan=False). Payload contains
schema_version, owner, metadata, window, rows. Datetimes use UTC isoformat().
Raw digest, transformations, eligibility and report times are excluded.
Decimal strings retain inspector formatting (including trailing zeroes).
"""
import hashlib
import json
from datetime import UTC
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator, model_validator
from products.triad.bar_inspection import inspect_bars
from products.triad.research_adapter import validate_research_input
from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Bar

CONTRACT = "triad.research-dataset.v1"


class DatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(strict=True, max_length=1_000_000)
    source: str = Field(strict=True, min_length=1, max_length=120)
    source_timezone: str = Field(strict=True, min_length=1, max_length=80)
    mode: Literal["FIXTURE", "SIMULATED", "REAL"]
    dataset_version: str = Field(strict=True, min_length=1, max_length=80)
    ingested_at: AwareDatetime
    start: AwareDatetime
    end: AwareDatetime

    @field_validator("source", "source_timezone", "dataset_version")
    @classmethod
    def metadata(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Nonblank printable metadata required")
        return value

    @field_validator("source_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Known source timezone required") from None
        return value

    @model_validator(mode="after")
    def window(self):
        if self.start >= self.end:
            raise ValueError("Nonempty aware window required")
        return self


def prepare_dataset(request: DatasetRequest):
    inspected = inspect_bars(request.csv_text)
    utc = lambda dt: dt.astimezone(UTC).isoformat()
    metadata = {key: getattr(request, key) for key in
                ("source", "source_timezone", "mode", "dataset_version")}
    metadata["ingested_at"] = utc(request.ingested_at)
    payload = dict(schema_version=CONTRACT, owner="triad", metadata=metadata,
                   window={"start": utc(request.start), "end": utc(request.end)},
                   rows=inspected["rows"])
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    report = {**payload, "prepared_sha256": identity,
              "raw_sha256": hashlib.sha256(request.csv_text.encode("utf-8")).hexdigest(),
              "coverage": inspected["coverage"], "symbols": inspected["symbols"],
              "row_count": inspected["row_count"],
              "transformations": [
                  "Leading BOM removed if present; present=" + str(request.csv_text.startswith("\ufeff")),
                  "Header and cell whitespace trimmed",
                  "Aware timestamps converted to UTC",
                  "Decimal values encoded as fixed-point strings",
                  "Rows sorted by UTC timestamp then symbol; original order is not retained",
                  "Core export converts decimal strings to SDK floating-point numbers; report rows remain exact",
              ],
              "provenance_scope": "CALLER_SUPPLIED; structural acceptance is not source certification",
              "core_assumptions": "XNYS regular-session one-minute USD equity, UNADJUSTED; no aggregation, gap repair or dropped rows",
              "core_input": None}
    try:
        bars = tuple(Bar(**row, source=request.source, source_symbol=row["symbol"],
                         timezone=request.source_timezone, ingested_at=request.ingested_at,
                         dataset_version=request.dataset_version, provenance_id=identity)
                     for row in inspected["rows"])
        supplied = ResearchInput(owner="triad", dataset_id=identity,
                                 dataset_version=request.dataset_version, mode=request.mode,
                                 start=request.start, end=request.end, bars=bars)
        validate_research_input(supplied)
    except ValueError:
        report["core_eligibility"] = {"eligible": False, "reasons": [
            "Core rejected the supplied bars or window: require at least three bars, supported symbols, minute boundaries, ingestion at or after data, and complete XNYS 2026 regular-session coverage."]}
    else:
        report["core_eligibility"] = {"eligible": True, "reasons": []}
        report["core_input"] = supplied.model_dump(mode="json")
    return report
