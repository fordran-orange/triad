"""Caller-supplied preparation, separate from source certification.

Prepared SHA-256: UTF-8 JSON of schema_version, owner, metadata, window, rows;
sorted keys, compact separators, ensure_ascii=False, allow_nan=False.
Raw SHA-256: exact submitted UTF-8 bytes.
"""
import hashlib
import json
from datetime import UTC, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator, model_validator
from products.triad.bar_inspection import inspect_bars
from products.triad.research_adapter import validate_research_input
from trading_core.product_sdk import ResearchInput
from trading_core.research.contracts import Bar

CONTRACT = "triad.research-dataset.v1"


class MarketDeclarations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: Literal["1m"]
    exchange: Literal["XNYS"]
    session: Literal["REGULAR"]
    currency: Literal["USD"]
    asset_class: Literal["equity"]
    adjustment_status: Literal["UNADJUSTED"]
    confirmed: bool = Field(strict=True)


class DatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(strict=True, max_length=1_000_000)
    source: str = Field(strict=True, min_length=1, max_length=120)
    source_timezone: str = Field(strict=True, min_length=1, max_length=80)
    dataset_version: str = Field(strict=True, min_length=1, max_length=80)
    mode: Literal["FIXTURE", "SIMULATED", "REAL"]
    ingested_at: AwareDatetime
    start: AwareDatetime
    end: AwareDatetime
    market: MarketDeclarations

    @field_validator("source", "source_timezone", "dataset_version")
    @classmethod
    def metadata(cls, value):
        if not value.strip() or not value.isprintable():
            raise ValueError("Printable nonblank metadata required")
        value.encode("utf-8")
        return value

    @field_validator("source_timezone")
    @classmethod
    def timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Known source timezone required") from None
        return value

    @field_validator("start", "end", "ingested_at", mode="before")
    @classmethod
    def iso_timestamp(cls, value):
        if not isinstance(value, str) or len(value) > 80 or "T" not in value:
            raise ValueError("Aware ISO timestamp required")
        return value

    @model_validator(mode="after")
    def window(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=31):
            raise ValueError("Nonempty window of at most 31 days required")
        return self


def prepare_dataset(request: DatasetRequest):
    inspected = inspect_bars(request.csv_text)
    def utc(dt):
        return dt.astimezone(UTC).isoformat()
    metadata = {key: getattr(request, key) for key in
                ("source", "source_timezone", "mode", "dataset_version")}
    metadata.update(ingested_at=utc(request.ingested_at), market=request.market.model_dump())
    payload = dict(schema_version=CONTRACT, owner="triad", metadata=metadata,
                   window={"start": utc(request.start), "end": utc(request.end)},
                   rows=inspected["rows"])
    identity = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
    report = {**payload, "prepared_sha256": identity,
              "raw_sha256": hashlib.sha256(request.csv_text.encode("utf-8")).hexdigest(),
              **{key: inspected[key] for key in ("coverage", "symbols", "row_count")},
              "transformations": [
                  "Leading BOM removed if present; header and cell whitespace trimmed",
                  "Aware timestamps normalized to UTC; declared source timezone retained as provenance",
                  "Decimals encoded as fixed-point strings, retaining trailing zeros",
                  "Rows sorted by UTC timestamp then symbol; no dropped rows or filled gaps",
                  "Decimal strings converted to floats only at SDK boundary; report remains exact",
                  "Window and ingestion timestamps normalized to UTC; other metadata retained verbatim",
              ],
              "identity_specification": "SHA-256 over UTF-8 sorted-key compact JSON of schema_version, owner, metadata, window and rows; ensure_ascii=False, allow_nan=False. Raw SHA-256 covers exact submitted UTF-8.",
              "provenance_scope": "CALLER_SUPPLIED; structural acceptance does not certify source",
              "core_input": None}
    category = "MARKET_CONFIRMATION_REQUIRED"
    reasons = ["Confirm one-minute XNYS regular-session USD equity and UNADJUSTED declarations."]
    if request.market.confirmed:
        try:
            category = "CORE_BAR_CONTRACT"
            bars = tuple(Bar(**row, source=request.source, source_symbol=row["symbol"],
                             timezone=request.source_timezone, ingested_at=request.ingested_at,
                             dataset_version=request.dataset_version, provenance_id=identity)
                         for row in inspected["rows"])
            supplied = ResearchInput(owner="triad", dataset_id=identity,
                                     dataset_version=request.dataset_version, mode=request.mode,
                                     start=request.start, end=request.end, bars=bars)
            category = "CORE_COVERAGE_OR_WINDOW"
            validate_research_input(supplied)
        except ValueError:
            reasons = ["Core rejected bars or coverage. Require supported symbols, minute boundaries, ingestion at or after data, at least three bars and complete XNYS 2026 coverage inside the window."]
        else:
            category, reasons = "ACCEPTED", []
            report["core_input"] = supplied.model_dump(mode="json")
    report["core_eligibility"] = dict(eligible=report["core_input"] is not None,
                                      category=category, reasons=reasons)
    return report
