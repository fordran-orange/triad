"""Portable one-minute candle contract. Synthetic examples only."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[Decimal, Field(max_digits=38, decimal_places=12, allow_inf_nan=False)]
SCHEMA = pa.schema(
    [
        pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        *[
            pa.field(name, pa.decimal128(38, 12), nullable=False)
            for name in ("open", "high", "low", "close", "volume")
        ],
        pa.field("source", pa.string(), nullable=False),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("data_version", pa.string(), nullable=False),
        pa.field("provenance_id", pa.string(), nullable=False),
    ],
    metadata={b"contract": b"triad.candles.1m.v1", b"timestamp_semantics": b"UTC interval start"},
)


class Candle1m(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timestamp: datetime
    symbol: str = Field(min_length=1)
    open: Number
    high: Number
    low: Number
    close: Number
    volume: Number = Field(ge=0)
    source: str = Field(min_length=1)
    ingested_at: datetime
    data_version: str = Field(min_length=1)
    provenance_id: str = Field(min_length=1)

    @field_validator("timestamp", "ingested_at")
    @classmethod
    def aware_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps require a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistency(self):
        if self.timestamp.second or self.timestamp.microsecond:
            raise ValueError("base candles must align to minute boundaries")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must bound OHLC")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must bound OHLC")
        if self.ingested_at < self.timestamp:
            raise ValueError("ingestion cannot precede candle interval")
        return self


def write_candles(path: Path, candles: list[Candle1m]) -> None:
    """Write a new immutable archive; refuse duplicates and accidental overwrites."""
    rows = [Candle1m.model_validate(c.model_dump()).model_dump() for c in candles]
    keys = [(r["timestamp"], r["symbol"], r["source"], r["data_version"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate canonical candle key")
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        pq.write_table(table, handle, compression="zstd")
