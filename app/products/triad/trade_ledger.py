"""Stateless user-supplied closed-trade accounting; no Core dependencies."""
import re
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from itertools import groupby

COLUMNS = ("trade_id", "symbol", "direction", "quantity", "entry_price",
           "exit_price", "entry_time", "exit_time", "total_cost")
MAX_BYTES = 1_000_000
ASSUMPTIONS = [
    "User-supplied records: each row is one complete matched round trip in USD.",
    "Realized P&L only, not mark-to-market equity or intratrade drawdown.",
    "Cash flows and open positions are excluded.",
    "Overlapping trades are accepted; capital/margin feasibility is not established.",
    "All-in costs are deducted once exactly as supplied; no calculator cost model is applied.",
    "Ledger completeness and supplied execution prices and costs are user assumptions.",
    "This report does not validate a strategy or establish future performance.",
]


def fail(row, field, message):
    raise ValueError(f"Row {row}, {field}: {message}")


def number(value, row, field, maximum, zero=False):
    if not isinstance(value, str):
        fail(row, field, "a decimal string is required")
    value = value.strip()
    if len(value) > 32 or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,8})?", value):
        fail(row, field, "use ordinary decimal notation with at most 8 fractional digits and 32 characters")
    result = Decimal(value)
    if result > maximum or (result < 0 if zero else result <= 0):
        fail(row, field, f"must be {'nonnegative' if zero else 'positive'} and <= {maximum}")
    return result


def timestamp(value, row, field):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        fail(row, field, "timezone-aware ISO-8601 timestamp required (up to microsecond precision)")
    if value[-1] != "Z" and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        fail(row, field, "invalid timezone offset")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        fail(row, field, "invalid timestamp")


def csv_records(text):
    """Strict quoted CSV without process-global csv.field_size_limit changes.

    The caller enforces the whole-text byte ceiling before parsing.
    """
    state, field, cells = "start", [], []
    index = 0
    record = 1
    active = False
    while index < len(text):
        char = text[index]
        index += 1
        if state == "quoted":
            if char == '"':
                state = "closed"
            else:
                field.append(char)
            continue
        if state == "closed" and char == '"':
            field.append('"')
            state = "quoted"
            continue
        if char in ",\r\n":
            if char == ",":
                cells.append("".join(field))
                field = []
                active = True
            else:
                if char == "\r" and index < len(text) and text[index] == "\n":
                    index += 1
                yield cells + ["".join(field)] if active or field or state == "closed" else []
                record += 1
                cells, field, active = [], [], False
            state = "start"
        elif state == "closed":
            fail(record, "csv_text", "malformed quoted CSV")
        elif char == '"':
            if state != "start":
                fail(record, "csv_text", "quote in unquoted field")
            state, active = "quoted", True
        else:
            field.append(char)
            state, active = "plain", True
    if state == "quoted":
        fail(record, "csv_text", "unterminated quoted field")
    if active:
        yield cells + ["".join(field)]


def analyze_trade_ledger(initial_balance, csv_text):
    with localcontext() as context:
        context.prec = 50
        return _analyze(initial_balance, csv_text)


def _analyze(initial_balance, csv_text):
    initial = number(initial_balance, 0, "initial_balance", 1_000_000_000_000)
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
    rows, ids = [], set()
    header = [v.strip() for v in next(reader, [])]
    if len(header) != len(COLUMNS) or set(header) != set(COLUMNS):
        fail(1, "headers", "exactly the nine documented columns required, without duplicates")
    for index, cells in enumerate(reader, 2):
        if index > 2001:
            fail(index, "records", "maximum 2000 records")
        if len(cells) != len(header):
            fail(index, "cells", "missing or extra cells")
        row = dict(zip(header, (v.strip() for v in cells)))
        for field, value in row.items():
            if not value:
                fail(index, field, "required value is blank")
        for field, pattern in (("trade_id", r"[A-Za-z0-9_-]{1,64}"),
                               ("symbol", r"[A-Z0-9._-]{1,20}")):
            if not re.fullmatch(pattern, row[field]):
                fail(index, field, "invalid identifier")
        if row["trade_id"] in ids:
            fail(index, "trade_id", "duplicate ID")
        ids.add(row["trade_id"])
        if row["direction"] not in ("LONG", "SHORT"):
            fail(index, "direction", "must be LONG or SHORT")
        times = {f: timestamp(row[f], index, f) for f in ("entry_time", "exit_time")}
        if times["entry_time"] > times["exit_time"]:
            fail(index, "entry_time", "must not follow exit_time")
        values = {f: number(row[f], index, f, 1_000_000, f == "total_cost")
                  for f in ("quantity", "entry_price", "exit_price", "total_cost")}
        gross = values["quantity"] * (values["exit_price"] - values["entry_price"])
        if row["direction"] == "SHORT":
            gross = -gross
        row.update(values)
        row.update(times)
        row.update(gross_pnl=gross, net_pnl=gross - values["total_cost"])
        rows.append(row)
    if not rows:
        fail(2, "records", "at least one record required")
    rows.sort(key=lambda r: (r["exit_time"], r["trade_id"]))
    balance = peak = initial
    max_dd = max_pct = Decimal(0)
    curve = [dict(timestamp=None, balance=format(initial, "f"), drawdown="0", drawdown_pct="0")]
    for time, group in groupby(rows, key=lambda r: r["exit_time"]):
        balance += sum((r["net_pnl"] for r in group), Decimal(0))
        peak = max(peak, balance)
        dd = peak - balance
        pct = 100 * dd / peak
        max_dd, max_pct = max(max_dd, dd), max(max_pct, pct)
        curve.append(dict(timestamp=time.isoformat(), balance=format(balance, "f"),
                          drawdown=format(dd, "f"), drawdown_pct=format(pct, "f")))
    positive = [r["net_pnl"] for r in rows if r["net_pnl"] > 0]
    negative = [r["net_pnl"] for r in rows if r["net_pnl"] < 0]
    gross = sum((r["gross_pnl"] for r in rows), Decimal(0))
    costs = sum((r["total_cost"] for r in rows), Decimal(0))
    net = gross - costs
    def encode(value):
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, datetime):
            return value.isoformat()
        return value
    return dict(
        schema_version="triad.trade-ledger.v1", currency="USD",
        monetary_encoding="decimal strings", percentage_unit="percent",
        assumptions=list(ASSUMPTIONS), initial_balance=encode(initial),
        trade_count=len(rows), gross_pnl=encode(gross), total_costs=encode(costs),
        net_pnl=encode(net), ending_realized_balance=encode(balance),
        positive_count=len(positive), negative_count=len(negative),
        zero_count=len(rows)-len(positive)-len(negative),
        win_rate_pct=encode(Decimal(100)*len(positive)/len(rows)),
        average_net_pnl=encode(net/len(rows)),
        profit_factor=encode(sum(positive, Decimal(0)) / -sum(negative)) if negative else None,
        profit_factor_reason=None if negative else "no_losses",
        max_drawdown=encode(max_dd), max_drawdown_pct=encode(max_pct),
        rows=[{k: encode(v) for k, v in r.items()} for r in rows],
        realized_balance_curve=curve,
    )
