"""Stateless user-supplied OHLCV inspection; no shared research engine imports."""
import re
from decimal import Decimal, localcontext

from products.triad.trade_ledger import csv_records, fail, number, timestamp

COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
MAX_BYTES = 1_000_000
MAX_ROWS = 5_000
PRICE_CEILING = 1_000_000
ASSUMPTIONS = [
    "User-supplied bars only; this is not a market feed.",
    "This inspection is not a chart.",
    "This inspection is not a backtest.",
    "This inspection does not establish strategy edge.",
    "Corporate actions are not adjusted.",
    "Minute boundaries are not required.",
    "Returns and signals are not computed.",
    "OHLC coherence is a structural check of the supplied rows only.",
    "Duplicate symbol and timestamp pairs are rejected; duplicate_count is zero when inspection succeeds.",
]


def inspect_bars(csv_text):
    with localcontext() as context:
        context.prec = 50
        return _inspect(csv_text)


def _inspect(csv_text):
    if not isinstance(csv_text, str) or len(csv_text) > MAX_BYTES:
        fail(0, "csv_text", "maximum 1,000,000 UTF-8 bytes")
    try:
        size = len(csv_text.encode("utf-8"))
    except UnicodeEncodeError:
        fail(0, "csv_text", "invalid UTF-8 text")
    if size > MAX_BYTES:
        fail(0, "csv_text", "maximum 1,000,000 UTF-8 bytes")
    text = csv_text.removeprefix("\ufeff")
    reader = csv_records(text)
    header = [value.strip() for value in next(reader, [])]
    if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
        fail(1, "headers", "exactly the seven documented columns required, without duplicates")
    rows = []
    seen = set()
    for index, cells in enumerate(reader, 2):
        if index > MAX_ROWS + 1:
            fail(index, "records", "maximum 5000 data rows")
        if len(cells) != len(header):
            fail(index, "cells", "missing or extra cells")
        raw = dict(zip(header, (value.strip() for value in cells)))
        for field, value in raw.items():
            if not value:
                fail(index, field, "required value is blank")
        if not re.fullmatch(r"[A-Z0-9._-]{1,20}", raw["symbol"]):
            fail(index, "symbol", "invalid identifier")
        moment = timestamp(raw["timestamp"], index, "timestamp")
        prices = {
            field: number(raw[field], index, field, PRICE_CEILING)
            for field in ("open", "high", "low", "close")
        }
        volume = number(raw["volume"], index, "volume", PRICE_CEILING, zero=True)
        if prices["high"] < max(prices["open"], prices["low"], prices["close"]):
            fail(index, "high", "high is below max(open, low, close)")
        if prices["low"] > min(prices["open"], prices["close"]):
            fail(index, "low", "low is above min(open, close)")
        key = (raw["symbol"], moment)
        if key in seen:
            fail(index, "timestamp", "duplicate symbol and timestamp")
        seen.add(key)
        rows.append({"symbol": raw["symbol"], "timestamp": moment, **prices, "volume": volume})
    if not rows:
        fail(2, "records", "at least one bar required")
    symbols = sorted({row["symbol"] for row in rows})
    coverage = []
    for symbol in symbols:
        symbol_rows = [row for row in rows if row["symbol"] == symbol]
        first = min(symbol_rows, key=lambda row: row["timestamp"])
        last = max(symbol_rows, key=lambda row: row["timestamp"])
        coverage.append({
            "symbol": symbol,
            "bar_count": len(symbol_rows),
            "first_timestamp": first["timestamp"].isoformat(),
            "last_timestamp": last["timestamp"].isoformat(),
        })
    rows.sort(key=lambda row: (row["timestamp"], row["symbol"]))

    def encode(value):
        if isinstance(value, Decimal):
            return format(value, "f")
        return value.isoformat()

    return {
        "schema_version": "triad.bar-inspection.v1",
        "row_count": len(rows),
        "symbols": symbols,
        "duplicate_count": 0,
        "assumptions": list(ASSUMPTIONS),
        "coverage": coverage,
        "rows": [
            {
                "timestamp": row["timestamp"].isoformat(),
                "symbol": row["symbol"],
                "open": encode(row["open"]),
                "high": encode(row["high"]),
                "low": encode(row["low"]),
                "close": encode(row["close"]),
                "volume": encode(row["volume"]),
            }
            for row in rows
        ],
    }
