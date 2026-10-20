"""Comparing two backtests (Mission 9 spec §7): pure functions over two saved run envelopes.

Nothing here runs a backtest. The equity curves are each run's combined (trade-exit) curve, the
engine's own definition behind its combined metrics (plan ruling P5), extended to the run's first and
last evaluated bars so both start at 0% and span their runs, on one calendar axis (P8).
"""

from __future__ import annotations

import json
from datetime import datetime
from statistics import fmean

METRICS = (
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
)
HIGHER_IS_BETTER = {
    "net_pnl",
    "net_return",
    "cagr",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
}
LOWER_IS_BETTER = {"max_drawdown"}
SCOPES = ("combined", "long", "short")
SPEC_IGNORED = {"id", "name", "description", "version"}
ASSUMED_CAPITAL = 100_000.0
MAX_POINTS = 1000


def _capital(run: dict) -> tuple[float, bool]:
    settings = run.get("settings") or {}
    capital = settings.get("initial_capital")
    if isinstance(capital, int | float) and capital > 0:
        return float(capital), False
    return ASSUMED_CAPITAL, True


def _flatten(value, prefix: str, out: dict) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if not prefix and key in SPEC_IGNORED:
                continue
            if key == "optimization":  # ranges to search, not how the strategy trades
                continue
            _flatten(inner, f"{prefix}.{key}" if prefix else key, out)
    elif (
        isinstance(value, list) and value and all(isinstance(v, dict) and "id" in v for v in value)
    ):
        for item in value:
            _flatten({k: v for k, v in item.items() if k != "id"}, f"{prefix}.{item['id']}", out)
    elif isinstance(value, list):
        out[prefix] = json.dumps(value, sort_keys=True)
    else:
        out[prefix] = value


def differences(a: dict, b: dict) -> list[dict]:
    """Every differing path of the two strategies (indicators by id) and of the settings that
    shape a run (initial capital, allocation), sorted by path (plan ruling P6)."""
    left: dict = {}
    right: dict = {}
    _flatten(a.get("strategy") or {}, "", left)
    _flatten(b.get("strategy") or {}, "", right)
    if a.get("settings") and b.get("settings"):
        for key in ("initial_capital", "allocation_fraction"):
            left[f"settings.{key}"] = a["settings"].get(key)
            right[f"settings.{key}"] = b["settings"].get(key)
    rows = []
    for path in sorted(set(left) | set(right)):
        if left.get(path) != right.get(path):
            rows.append({"path": path, "a": _unjson(left.get(path)), "b": _unjson(right.get(path))})
    return rows


def _unjson(value):
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _mark(metric: str, diff: float | None) -> str | None:
    if diff is None or diff == 0:
        return None
    if metric in HIGHER_IS_BETTER:
        return "better" if diff > 0 else "worse"
    if metric in LOWER_IS_BETTER:
        return "better" if diff < 0 else "worse"
    return None


def _number(value) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def metrics(a: dict, b: dict) -> dict:
    out = {}
    for scope in SCOPES:
        left = (((a.get("result") or {}).get(scope) or {}).get("metrics")) or {}
        right = (((b.get("result") or {}).get(scope) or {}).get("metrics")) or {}
        rows = []
        for metric in METRICS:
            x, y = _number(left.get(metric)), _number(right.get(metric))
            diff = None if x is None or y is None else y - x
            rows.append(
                {
                    "metric": metric,
                    "a": left.get(metric),
                    "b": right.get(metric),
                    "diff": diff,
                    "mark": _mark(metric, diff),
                }
            )
        out[scope] = rows
    return out


def _span(run: dict) -> tuple[str | None, str | None]:
    """The first and last evaluated bar of the run (from its per-bar side curves), else its
    selection's dates."""
    result = run.get("result") or {}
    firsts, lasts = [], []
    for side in ("long", "short"):
        curve = (result.get(side) or {}).get("equity") or []
        if curve:
            firsts.append(curve[0]["timestamp"])
            lasts.append(curve[-1]["timestamp"])
    if firsts:
        return min(firsts), max(lasts)
    data = run.get("data") or {}
    return (
        str(data["start"]) if data.get("start") else None,
        str(data["end"]) if data.get("end") else None,
    )


def resample(points: list, limit: int = MAX_POINTS) -> list:
    if len(points) <= limit:
        return list(points)
    last = len(points) - 1
    return [points[(k * last) // (limit - 1)] for k in range(limit)]


def equity(run: dict) -> list[dict]:
    capital, _ = _capital(run)
    start, end = _span(run)
    curve = (((run.get("result") or {}).get("combined") or {}).get("equity")) or []
    points = []
    if start is not None and (not curve or start < curve[0]["timestamp"]):
        points.append({"t": start, "pct": 0.0, "usd": capital, "dd": 0.0})
    for point in curve:
        value = float(point["equity"])
        points.append(
            {
                "t": point["timestamp"],
                "pct": value / capital - 1,
                "usd": value,
                "dd": float(point.get("drawdown") or 0.0),
            }
        )
    if end is not None and points and end > points[-1]["t"]:
        points.append({**points[-1], "t": end})
    return resample(points)


def _hours(trade: dict) -> float | None:
    try:
        held = datetime.fromisoformat(trade["exit_time"]) - datetime.fromisoformat(
            trade["entry_time"]
        )
    except (KeyError, TypeError, ValueError):
        return None
    return held.total_seconds() / 3600


def trades(run: dict) -> dict:
    out = {}
    for side in ("long", "short"):
        rows = (((run.get("result") or {}).get(side) or {}).get("trades")) or []
        nets = [float(t["net_pnl"]) for t in rows if t.get("net_pnl") is not None]
        holds = [h for h in (_hours(t) for t in rows) if h is not None]
        out[side] = {
            "count": len(rows),
            "avg_net": fmean(nets) if nets else None,
            "win_rate": sum(1 for n in nets if n > 0) / len(nets) if nets else None,
            "avg_hold_hours": fmean(holds) if holds else None,
            "max_hold_hours": max(holds) if holds else None,
        }
    return out


def _identity(run: dict) -> dict:
    data = run.get("data") or {}
    strategy = run.get("strategy") or {}
    capital, _ = _capital(run)
    return {
        "run_id": run.get("run_id"),
        "symbol": data.get("symbol"),
        "timeframe": data.get("timeframe"),
        "start": str(data["start"]) if data.get("start") else None,
        "end": str(data["end"]) if data.get("end") else None,
        "strategy_name": strategy.get("name"),
        "strategy_hash": run.get("strategy_hash"),
        "result_hash": run.get("result_hash"),
        "data_hash": data.get("data_hash"),
        "initial_capital": capital,
        "created_at": run.get("created_at"),
    }


def _notes(a: dict, b: dict) -> list[str]:
    notes = []
    if a.get("result_hash") and a.get("result_hash") == b.get("result_hash"):
        notes.append("identical result")
    left, right = a.get("data") or {}, b.get("data") or {}
    if left.get("data_hash") and left.get("data_hash") == right.get("data_hash"):
        notes.append("same data")
    if a.get("strategy_hash") and a.get("strategy_hash") == b.get("strategy_hash"):
        notes.append("same strategy")
    spans = [(str(d.get("start")), str(d.get("end"))) for d in (left, right)]
    if all(d.get("start") and d.get("end") for d in (left, right)) and spans[0] != spans[1]:
        start, end = max(s for s, _ in spans), min(e for _, e in spans)
        notes.append(
            f"different periods: shared {start} → {end}"
            if start <= end
            else "different periods: no shared span"
        )
    return notes


def compare(a: dict, b: dict) -> dict:
    curves = {"a": equity(a), "b": equity(b)}
    stamps = [p["t"] for curve in curves.values() for p in curve]
    return {
        "identity": {"a": _identity(a), "b": _identity(b)},
        "notes": _notes(a, b),
        "differences": differences(a, b),
        "metrics": metrics(a, b),
        "equity": curves,
        "domain": {"start": min(stamps), "end": max(stamps)} if stamps else None,
        "trades": {"a": trades(a), "b": trades(b)},
        "capital_assumed": {"a": _capital(a)[1], "b": _capital(b)[1]},
    }


__all__ = ["METRICS", "compare", "differences", "equity", "metrics", "trades"]
