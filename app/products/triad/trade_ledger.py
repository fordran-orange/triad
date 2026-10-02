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
    "Entry notional exposure uses quantity times entry price on [entry_time, exit_time); zero-duration trades are excluded only from exposure.",
    "Exposure is reconstructed from supplied completed records, excludes open positions and price changes, and does not establish margin feasibility or executable portfolio risk.",
    "Exposure ratios are entry notional divided by initial balance, not leverage or capital required.",
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


def entry_notional_exposure(rows, initial):
    """Additive v1 report extension; constant entry notionals on [entry, exit).

    At most two events per validated record: O(n log n) sorting, O(n) scan.
    Called inside the analyzer's 50-digit local Decimal context.
    """
    events = []
    excluded = 0
    for row in rows:
        if row["entry_time"] == row["exit_time"]:
            excluded += 1
            continue
        notional = row["quantity"] * row["entry_price"]
        for time, sign in ((row["entry_time"], 1), (row["exit_time"], -1)):
            events.append((time, sign, row["direction"], sign * notional))
    events.sort(key=lambda event: event[0])
    long = short = maximum = Decimal(0)
    count = max_count = 0
    count_time = gross_time = None
    timeline = []
    for time, group in groupby(events, key=lambda event: event[0]):
        for _, delta, direction, notional in group:
            count += delta
            if direction == "LONG":
                long += notional
            else:
                short += notional
        gross = long + short
        stamp = time.isoformat()
        if count > max_count:
            max_count, count_time = count, stamp
        if gross > maximum:
            maximum, gross_time = gross, stamp
        timeline.append(dict(
            timestamp=stamp, active_trade_count=count,
            long_entry_notional=format(long, "f"),
            short_entry_notional=format(short, "f"),
            gross_entry_notional=format(gross, "f"),
            net_entry_notional=format(long - short, "f"),
            gross_to_initial_balance_ratio=format(gross / initial, "f"),
        ))
    return dict(
        excluded_zero_duration_trade_count=excluded,
        max_concurrent_trades=max_count,
        max_concurrent_trades_timestamp=count_time,
        max_gross_entry_notional=format(maximum, "f"),
        max_gross_to_initial_balance_ratio=format(maximum / initial, "f"),
        max_gross_entry_notional_timestamp=gross_time,
        timeline=timeline,
    )


def symbol_breakdown(rows):
    """Additive v1 report extension; per-symbol attribution over validated rows.

    Called inside the analyzer's 50-digit local Decimal context.
    """
    breakdown = {}
    for symbol in sorted({row["symbol"] for row in rows}):
        symbol_rows = [row for row in rows if row["symbol"] == symbol]
        positive = [r["net_pnl"] for r in symbol_rows if r["net_pnl"] > 0]
        negative = [r["net_pnl"] for r in symbol_rows if r["net_pnl"] < 0]
        gross = sum((r["gross_pnl"] for r in symbol_rows), Decimal(0))
        costs = sum((r["total_cost"] for r in symbol_rows), Decimal(0))
        net = gross - costs
        breakdown[symbol] = dict(
            trade_count=len(symbol_rows),
            gross_pnl=format(gross, "f"),
            total_costs=format(costs, "f"),
            net_pnl=format(net, "f"),
            win_rate_pct=format(Decimal(100) * len(positive) / len(symbol_rows), "f"),
            average_net_pnl=format(net / len(symbol_rows), "f"),
            profit_factor=format(sum(positive, Decimal(0)) / -sum(negative), "f") if negative else None,
            profit_factor_reason=None if negative else "no_losses",
        )
    return breakdown


def drawdown_recovery(curve):
    """Independent maxima on grouped realized balances, inside local Decimal context.

    Ties select the earliest trough and latest preceding matching peak.
    Durations end at first recovery, or at the final observed exit.
    The initial baseline has no observed start time. O(n) per maximum.
    """
    def seconds(start, end):
        if start is None:
            return None
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        return format(Decimal(delta.days * 86400 + delta.seconds)
                      + Decimal(delta.microseconds) / Decimal(1000000), "f")

    episodes = {}
    for name, metric in (("max_dollar", "drawdown"), ("max_percent", "drawdown_pct")):
        index = max(range(len(curve)), key=lambda i: Decimal(curve[i][metric]))
        trough = curve[index]
        if Decimal(trough[metric]) == 0:
            episodes[name] = None
            continue
        peak_balance = Decimal(trough["balance"]) + Decimal(trough["drawdown"])
        peak = next(point for point in reversed(curve[:index])
                    if Decimal(point["balance"]) == peak_balance)
        recovery = next((point for point in curve[index + 1:]
                         if Decimal(point["balance"]) >= peak_balance), None)
        end = recovery if recovery is not None else curve[-1]
        episodes[name] = dict(
            status="RECOVERED" if recovery is not None else "UNRECOVERED_AT_END",
            peak_balance=format(peak_balance, "f"), trough_balance=trough["balance"],
            drawdown=trough["drawdown"], drawdown_pct=trough["drawdown_pct"],
            peak_timestamp=peak["timestamp"],
            peak_origin="INITIAL_BALANCE" if peak["timestamp"] is None else "OBSERVED_EXIT",
            trough_timestamp=trough["timestamp"],
            recovery_timestamp=recovery["timestamp"] if recovery is not None else None,
            observation_end_timestamp=curve[-1]["timestamp"],
            peak_to_end_seconds=seconds(peak["timestamp"], end["timestamp"]),
            trough_to_end_seconds=seconds(trough["timestamp"], end["timestamp"]),
        )
    return episodes


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
    text = csv_text.removeprefix("﻿")
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
        drawdown_recovery=drawdown_recovery(curve),
        entry_notional_exposure=entry_notional_exposure(rows, initial),
        symbol_breakdown=symbol_breakdown(rows),
    )
