"""The rules of a plateau walk-forward (Mission 8 spec §5, §7): pure functions only.

Each rule keeps one capital chain per enabled side (plan ruling P1): the engine simulates the
sides independently with full capital, so each side's window runs with the other side disabled,
on the whole history before it with `evaluate_from` at its first bar, starting from the side's
chained cash and carried position; only the last window closes at its edge. A rule's combined
result merges both sides' trades on the initial capital exactly as the engine's `_combine` does,
so a fixed configuration chained over every window equals one continuous run. A flat window
(plan ruling P2) closes a carried position at its first bar open and opens nothing.
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass
from datetime import datetime

from products.aegis.analysis import _columns, objective_values
from products.aegis.backtest import (
    BacktestRequest,
    BacktestSettings,
    OpenPosition,
    _combine,
    _metrics,
    run_backtest,
)
from products.aegis.indicators import IndicatorCache
from products.aegis.results import _clean, result_hash
from products.aegis.strategy import StrategySpec
from products.aegis.surface import Grid, _distance
from products.aegis.walkforward import Window, flag_edge_exits, rebase

RULES = ("plateau", "peak", "frozen")
SIDES = ("long", "short")
SIDE_KEY = {"long": "long_side", "short": "short_side"}
CHART_POINTS = 256
RAW_LABEL = "RAW ARCHIVE · NOT RESEARCH-ELIGIBLE"
OBJECTIVE_NAMES = {
    "net_pnl": "net P&L",
    "net_return": "return",
    "cagr": "CAGR",
    "max_drawdown": "max drawdown",
    "mar": "MAR",
    "win_rate": "win rate",
    "expectancy": "expectancy",
    "profit_factor": "profit factor",
    "trade_count": "trade count",
    "exposure": "exposure",
}
REPORT_METRICS = ("net_pnl", "net_return", "cagr", "max_drawdown", "mar", "trade_count", "exposure")


@dataclass
class SideChain:
    """One side of one rule between windows: realized cash, the open position carried into the
    next window (if any) and the marked equity the next window is measured from."""

    cash: float
    carry: dict | None = None
    equity: float | None = None

    def __post_init__(self) -> None:
        if self.equity is None:
            self.equity = self.cash

    def as_dict(self) -> dict:
        return {"cash": self.cash, "carry": self.carry, "equity": self.equity}

    @classmethod
    def of(cls, data: dict) -> SideChain:
        return cls(cash=float(data["cash"]), carry=data.get("carry"), equity=data.get("equity"))


def enabled_sides(spec: StrategySpec) -> list[str]:
    return [side for side in SIDES if getattr(spec, SIDE_KEY[side]).enabled]


def start_chains(spec: StrategySpec, initial_capital: float) -> dict[str, SideChain]:
    return {side: SideChain(cash=float(initial_capital)) for side in enabled_sides(spec)}


def _moment(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _iso(value) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _side_only(spec: StrategySpec, side: str) -> StrategySpec:
    other = SIDE_KEY["short" if side == "long" else "long"]
    return spec.model_copy(
        update={other: getattr(spec, other).model_copy(update={"enabled": False})}
    )


def _held(
    trades: list[dict], open_position: dict | None, moments: list[datetime], start: int, end: int
) -> set[int]:
    """Bars of [start, end) the side held a position, as the engine flags them: from the entry
    fill bar up to (not including) the exit fill bar; an end-of-data close holds its last bar; a
    position still open holds to the window's end."""

    def index(value: str) -> int:
        return bisect.bisect_left(moments, _moment(value))

    held: set[int] = set()
    for trade in trades:
        first = max(index(trade["entry_time"]), start)
        stop = index(trade["exit_time"])
        if trade.get("exit_signal_time") == trade.get("exit_time"):
            stop += 1
        held.update(range(first, min(stop, end)))
    if open_position is not None:
        held.update(range(max(index(open_position["entry_time"]), start), end))
    return held


def _side_run(
    spec: StrategySpec,
    side: str,
    rows: list[dict],
    window: Window,
    chain: SideChain,
    settings: BacktestSettings,
    last: bool,
    flat: bool,
    cache: IndicatorCache | None,
) -> dict:
    carry = chain.carry
    if flat and carry is None:  # nothing to close and nothing may open: the side holds its cash
        return {
            "trades": [],
            "metrics": _metrics([], [], chain.equity),
            "ending_cash": chain.cash,
            "ending_equity": chain.cash,
            "carried_in": False,
            "open_position": None,
            "flat": True,
            "run_hash": None,
            "held": set(),
        }
    if flat and carry.get("exit_signal_time") is None:
        # Plan ruling P2: the carried position's exit is signalled on the bar before the window,
        # so the engine fills it at the window's first bar open; the run ends on that bar, so no
        # entry can fill.
        carry = {
            **carry,
            "exit_signal_time": _iso(rows[window.oos_start - 1]["timestamp"]),
            "exit_tags": [],
        }
    bars = rows[: window.oos_start + 1] if flat else rows[: window.oos_end]
    run_settings = settings.model_copy(
        update={
            "evaluate_from": _moment(rows[window.oos_start]["timestamp"]),
            "initial_capital": chain.cash,
            "initial_position": OpenPosition(**carry) if carry is not None else None,
            "close_at_end": last and not flat,
        }
    )
    result = run_backtest(
        BacktestRequest(strategy=_side_only(spec, side), bars=bars, settings=run_settings),
        cache=cache,
    )[side]
    trades = flag_edge_exits(result["trades"])
    if flat:
        trades = [{**t, "window_flat_exit": True} for t in trades]
    open_position = result["open_position"]
    if open_position is not None and open_position.get("origin_window") is None:
        open_position = {**open_position, "origin_window": window.index}
    rebased = rebase(
        result["trades"], result["equity"], chain.equity, result["metrics"]["exposure"]
    )
    ending_equity = float(result["ending_cash"]) if flat else float(result["ending_equity"])
    return {
        "trades": trades,
        "metrics": rebased["metrics"],
        "ending_cash": float(result["ending_cash"]),
        "ending_equity": ending_equity,
        "carried_in": chain.carry is not None,
        "open_position": open_position,
        "flat": flat,
        "run_hash": result_hash(_clean({"trades": result["trades"], "metrics": result["metrics"]})),
        "held": None,  # filled by run_window, which knows the window's bars
    }


def run_window(
    spec: StrategySpec,
    rows: list[dict],
    window: Window,
    chains: dict[str, SideChain],
    settings: BacktestSettings,
    last: bool,
    flat: bool = False,
    cache: IndicatorCache | None = None,
) -> dict:
    """One rule's out-of-sample window: each chained side run on its own, then combined. `spec`
    is the configuration traded; when `flat`, it only manages the forced exit (plan ruling P2)."""
    moments = [_moment(row["timestamp"]) for row in rows[: window.oos_end]]
    start, end = window.oos_start, window.oos_end
    sides: dict[str, dict] = {}
    held: set[int] = set()
    for side, chain in chains.items():
        record = _side_run(spec, side, rows, window, chain, settings, last, flat, cache)
        if record["held"] is None:
            record["held"] = _held(record["trades"], record["open_position"], moments, start, end)
        held |= record.pop("held")
        sides[side] = record
    initial = float(settings.initial_capital)
    previous = initial + sum(float(c.equity) - initial for c in chains.values())
    ending = initial + sum(r["ending_equity"] - initial for r in sides.values())
    trades = sorted((t for r in sides.values() for t in r["trades"]), key=lambda t: t["exit_time"])
    bars = end - start
    return {
        "flat": flat,
        "sides": sides,
        "combined": {
            "trades": trades,
            "trade_count": len(trades),
            "net_pnl": ending - previous,
            "net_return": ending / previous - 1 if previous else None,
            "ending_equity": ending,
            "held_bars": len(held),
            "bars": bars,
            "exposure": len(held) / bars if bars else 0.0,
        },
        "chains": {
            side: SideChain(
                cash=record["ending_cash"],
                carry=record["open_position"],
                equity=record["ending_equity"],
            )
            for side, record in sides.items()
        },
    }


def stitch_rule(window_results: list[dict], initial_capital: float) -> dict:
    """A rule's out-of-sample windows in order as one result, with the engine's combined
    metrics (trade-exit equity from the initial capital) and the union exposure over every
    out-of-sample bar (plan ruling P3); its hash is what an identical study reproduces (P11)."""
    trades = [t for result in window_results for t in result["combined"]["trades"]]
    combined = _combine({"trades": trades}, {"trades": []}, initial_capital)
    bars = sum(result["combined"]["bars"] for result in window_results)
    held = sum(result["combined"]["held_bars"] for result in window_results)
    combined["metrics"]["exposure"] = held / bars if bars else 0.0
    payload = _clean({"trades": combined["trades"], "metrics": combined["metrics"]})
    return {
        "trades": combined["trades"],
        "equity": combined["equity"],
        "metrics": combined["metrics"],
        "flat_windows": sum(1 for result in window_results if result["flat"]),
        "windows": len(window_results),
        "result_hash": result_hash(payload),
    }


def best_cell(rows: list[dict], objective: str) -> int | None:
    """The highest oriented objective among valid cells with a value, ties to the lower cell
    index; None when no cell has a value (plan ruling P8)."""
    if not rows:
        return None
    values, _, _, _ = objective_values(_columns(rows), objective)
    if not values:
        return None
    return max(values, key=lambda cell: (values[cell], -cell))


def centre_inside(previous_plateau_cells: list[int] | None, centre: int | None) -> bool | None:
    if previous_plateau_cells is None or centre is None:
        return None
    return centre in set(previous_plateau_cells)


def move_distance(grid: Grid, a: int, b: int) -> float:
    """Euclidean distance between two cells, each parameter normalized by its range (P9)."""
    return _distance(grid, a, b)


def resample(points: list, limit: int = CHART_POINTS) -> list:
    """At most `limit` points by index, the first and last kept (plan ruling P10)."""
    if len(points) <= limit:
        return list(points)
    last = len(points) - 1
    return [points[(k * last) // (limit - 1)] for k in range(limit)]


# --- the report (spec §7) --------------------------------------------------------------------


def _two(value) -> str:
    return "—" if value is None else f"{float(value):.2f}"


def _oriented(objective: str, value) -> float | None:
    if value is None:
        return None
    return -float(value) if objective == "max_drawdown" else float(value)


def _comparison(symbol: str, objective: str, rules: dict) -> str:
    name = OBJECTIVE_NAMES.get(objective, objective)

    def value(rule: str) -> str:
        return _two(rules[rule].get("metrics", {}).get(objective))

    sentence = (
        f"On {symbol} the plateau rule's out-of-sample {name} was {value('plateau')}, "
        f"against {value('peak')} for the peak rule"
    )
    if "absent" in rules["frozen"]:
        return sentence + "."
    return sentence + f" and {value('frozen')} for the frozen centre."


def _stability(windows: list[dict]) -> dict:
    count = len(windows)
    found = [w for w in windows if w.get("plateau")]
    compared = [w["centre_inside"] for w in windows if w.get("centre_inside") is not None]
    moves = [float(w["moved"]) for w in windows if w.get("moved") is not None]
    paths: list[str] = []
    for w in found:
        for path in w["plateau"]["centre_params"]:
            if path not in paths:
                paths.append(path)
    return {
        "plateau_share": len(found) / count if count else None,
        "centre_kept_share": sum(1 for kept in compared if kept) / len(compared)
        if compared
        else None,
        "median_move": statistics.median(moves) if moves else None,
        "centre_path": {
            path: [
                float(w["plateau"]["centre_params"][path]) if w.get("plateau") else None
                for w in windows
            ]
            for path in paths
        },
    }


def _window_rows(windows: list[dict]) -> list[dict]:
    rows = []
    for w in windows:
        plateau = w.get("plateau")
        rules = w.get("rules") or {}
        rows.append(
            {
                "index": w["index"],
                "oos_start": w.get("oos_start"),
                "oos_end": w.get("oos_end"),
                "choice": (
                    f"plateau {plateau['id']} ({plateau['size']} cells), centre {plateau['centre_params']}"
                    if plateau
                    else f"no plateau: {w.get('no_plateau') or 'no statement'}"
                ),
                "best": w.get("best"),
                "net_pnl": {
                    rule: (record.get("combined") or {}).get("net_pnl")
                    for rule, record in rules.items()
                    if "absent" not in record
                },
                "flat": bool((rules.get("plateau") or {}).get("flat")),
                "centre_inside": w.get("centre_inside"),
                "moved": w.get("moved"),
            }
        )
    return rows


def study_report(document, per_symbol: dict[str, dict]) -> dict:
    """The study's report from each symbol's stitched rules and window records: the three rules
    side by side, the plateau rule's flat windows, one comparison sentence per symbol, the
    cross-symbol line with its caveats, stability, bounded chart curves and the window table."""
    objective = document.objective
    name = OBJECTIVE_NAMES.get(objective, objective)
    symbols: dict[str, dict] = {}
    ahead = comparable = 0
    for symbol in document.symbols:
        entry = per_symbol.get(symbol)
        if entry is None:
            continue
        rules: dict[str, dict] = {}
        for rule in RULES:
            stitched = entry["rules"][rule]
            if "absent" in stitched:
                rules[rule] = {"absent": stitched["absent"]}
                continue
            rules[rule] = {
                "metrics": {key: stitched["metrics"].get(key) for key in REPORT_METRICS},
                "objective": stitched["metrics"].get(objective),
                "flat_windows": stitched["flat_windows"],
                "windows": stitched["windows"],
                "result_hash": stitched["result_hash"],
            }
        plateau = _oriented(objective, rules["plateau"]["objective"])
        peak = _oriented(objective, rules["peak"]["objective"])
        if plateau is not None and peak is not None:
            comparable += 1
            ahead += plateau > peak
        windows = entry["windows"]
        symbols[symbol] = {
            "windows": len(windows),
            "rules": rules,
            "flat_line": f"flat in {rules['plateau']['flat_windows']} of {len(windows)} windows",
            "comparison": _comparison(symbol, objective, rules),
            "stability": _stability(windows),
            "curves": {
                rule: resample(entry["rules"][rule].get("equity") or [])
                for rule in RULES
                if "absent" not in entry["rules"][rule]
            },
            "window_rows": _window_rows(windows),
        }
    total = len(symbols)
    if comparable == total:
        summary = f"plateau rule ahead of the peak rule on {ahead} of {total} symbols by {name}"
    else:
        summary = (
            f"plateau rule ahead of the peak rule on {ahead} of {comparable} comparable symbols "
            f"by {name} ({total - comparable} not comparable)"
        )
    listed = list(symbols)
    trades = []
    for s in listed:
        counts = [
            f"{rule} {symbols[s]['rules'][rule]['metrics']['trade_count']}"
            for rule in RULES
            if "absent" not in symbols[s]["rules"][rule]
        ]
        trades.append(f"{s} " + " / ".join(counts))
    caveats = [
        "windows: " + ", ".join(f"{s} {symbols[s]['windows']}" for s in listed),
        "plateau rule flat windows: "
        + ", ".join(f"{s} {symbols[s]['rules']['plateau']['flat_windows']}" for s in listed),
        "out-of-sample trades: " + "; ".join(trades),
        "no significance test is claimed",
    ]
    return {
        "objective": objective,
        "data_label": f"{', '.join(listed)} {document.timeframe} {document.start} → {document.end}",
        "raw_archive": True,
        "label": RAW_LABEL,
        "frozen_absent": document.frozen_absent,
        "symbols": symbols,
        "summary": summary,
        "caveats": caveats,
    }


def render_study_markdown(report: dict) -> str:
    lines = [f"# Plateau walk-forward: {report['summary']}", ""]
    lines.append(f"{report['label']} · {report['data_label']} · objective {report['objective']}")
    lines.append("")
    lines.append("Caveats: " + "; ".join(report["caveats"]) + ".")
    if report.get("frozen_absent"):
        lines += ["", f"Frozen centre: absent — {report['frozen_absent']}."]
    for symbol, entry in report["symbols"].items():
        lines += ["", f"## {symbol}", "", entry["comparison"], ""]
        lines.append("| rule | net P&L | return | CAGR | max drawdown | MAR | trades | exposure |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for rule in RULES:
            record = entry["rules"][rule]
            if "absent" in record:
                lines.append(f"| {rule} | absent: {record['absent']} | | | | | | |")
                continue
            m = record["metrics"]
            lines.append(
                f"| {rule} | {_two(m['net_pnl'])} | {_two(m['net_return'])} | {_two(m['cagr'])} | "
                f"{_two(m['max_drawdown'])} | {_two(m['mar'])} | {m['trade_count']} | "
                f"{_two(m['exposure'])} |"
            )
        stability = entry["stability"]
        lines += [
            "",
            f"Plateau rule {entry['flat_line']}. Plateau found in {_two(stability['plateau_share'])} "
            "of windows; centre inside the previous plateau in "
            f"{_two(stability['centre_kept_share'])}; median move {_two(stability['median_move'])}.",
            "",
            "| window | out of sample | choice | plateau | peak | frozen | flat |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in entry["window_rows"]:
            nets = row["net_pnl"]
            lines.append(
                f"| {row['index']} | {row['oos_start']} → {row['oos_end']} | {row['choice']} | "
                f"{_two(nets.get('plateau'))} | {_two(nets.get('peak'))} | "
                f"{_two(nets.get('frozen'))} | {'yes' if row['flat'] else 'no'} |"
            )
    return "\n".join(lines) + "\n"


__all__ = [
    "CHART_POINTS",
    "RAW_LABEL",
    "RULES",
    "SIDES",
    "SideChain",
    "best_cell",
    "centre_inside",
    "enabled_sides",
    "move_distance",
    "render_study_markdown",
    "resample",
    "run_window",
    "start_chains",
    "stitch_rule",
    "study_report",
]
