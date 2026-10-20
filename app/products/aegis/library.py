"""The Results library (Mission 9 spec §4, §6): one index of every saved result.

The index merges the summary sidecars every kind already keeps. A summary that lacks the library's
block (the headline numbers, symbols, range and strategy name) has it computed once from the full
document and written back into the sidecar (plan ruling P1); any later save of the item rewrites the
sidecar without it, so the block is recomputed and never stale. A query computes at most a budget's
worth of blocks and reports the rest as `preparing` (P2).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from products.aegis.experiments import ExperimentStore
from products.aegis.runs import RunRepository

KINDS = ("backtest", "optimization", "walkforward", "experiment", "study")
FOLDERS = {
    "backtest": "runs",
    "optimization": "optimizations",
    "walkforward": "walkforward",
    "experiment": "experiments",
    "study": "studies",
}
ID_KEYS = {
    "backtest": "run_id",
    "optimization": "job_id",
    "walkforward": "job_id",
    "experiment": "id",
    "study": "id",
}
LISTERS = {
    "backtest": "list_runs",
    "optimization": "list_optimizations",
    "walkforward": "list_walkforwards",
    "experiment": "list_experiments",
    "study": "list_studies",
}
VERSION = 1
BACKTEST_HEADLINE = ("net_pnl", "net_return", "mar", "max_drawdown", "trade_count")


class LibraryEntry(BaseModel):
    kind: str
    id: str
    name: str
    label: str = ""
    notes: str = ""
    starred: bool = False
    symbols: list[str] = Field(default_factory=list)
    timeframe: str | None = None
    start: str | None = None
    end: str | None = None
    strategy_id: str | None = None
    strategy_name: str | None = None
    created_at: str | None = None
    status: str | None = None
    decision: dict | None = None
    headline: dict = Field(default_factory=dict)
    links: dict = Field(default_factory=dict)


class LibraryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kinds: list[Literal["backtest", "optimization", "walkforward", "experiment", "study"]] = Field(
        default_factory=list
    )
    symbol: str | None = None
    timeframe: str | None = None
    strategy: str | None = None
    starred: bool | None = None
    decision: str | None = None
    q: str | None = None
    sort: Literal["created", "net_pnl", "mar"] = "created"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)
    deleted: bool = False


# --- headlines per kind (spec §4.1) -----------------------------------------------------------


def _data_fields(data: dict | None) -> dict:
    data = data or {}
    symbol = data.get("symbol")
    return {
        "symbols": [symbol] if isinstance(symbol, str) and symbol else [],
        "timeframe": data.get("timeframe"),
        "start": _as_text(data.get("start")),
        "end": _as_text(data.get("end")),
    }


def _as_text(value) -> str | None:
    return None if value is None else str(value)


def _best(cells: list[dict], objective: str) -> float | None:
    """The best cell's objective (plan ruling P9): highest, or lowest for max drawdown."""
    values = [
        float(c["metrics"][objective])
        for c in cells
        if isinstance(c.get("metrics"), dict) and c["metrics"].get(objective) is not None
    ]
    if not values:
        return None
    return min(values) if objective == "max_drawdown" else max(values)


def headline(kind: str, document: dict, experiments: ExperimentStore | None) -> dict:
    """The library block of one document: headline numbers, symbols, range and strategy name."""
    strategy = document.get("strategy") or document.get("spec") or {}
    block = {"strategy_name": strategy.get("name") if isinstance(strategy, dict) else None}
    if kind == "backtest":
        block |= _data_fields(document.get("data"))
        metrics = (((document.get("result") or {}).get("combined") or {}).get("metrics")) or {}
        block["headline"] = {k: metrics.get(k) for k in BACKTEST_HEADLINE} if metrics else {}
    elif kind == "optimization":
        block |= _data_fields(document.get("data"))
        progress = document.get("progress") or {}
        objective = document.get("objective")
        block["headline"] = {
            "side": document.get("side"),
            "cells_run": progress.get("done"),
            "cells_total": document.get("total_cells"),
            "objective": objective,
            "best": _best(document.get("cells") or [], objective) if objective else None,
        }
    elif kind == "walkforward":
        block |= _data_fields(document.get("data"))
        metrics = (document.get("stitched") or {}).get("metrics") or {}
        block["headline"] = {
            "side": document.get("side"),
            "windows": (document.get("windows") or {}).get("total"),
            "net_pnl": metrics.get("net_pnl"),
            "mar": metrics.get("mar"),
        }
    elif kind == "experiment":
        block |= _data_fields(document.get("data"))
        progress = document.get("progress") or {}
        recommended = None
        if experiments is not None and document.get("latest_report") is not None:
            try:
                report = experiments.read_report(document["id"], document["latest_report"])
                recommended = report.get("recommendation") is not None
            except (KeyError, OSError, ValueError):
                recommended = None
        block["headline"] = {
            "mode": (document.get("plan") or {}).get("mode"),
            "cells_done": progress.get("cells_done"),
            "cells_planned": progress.get("cells_planned"),
            "objective": document.get("objective"),
            "recommended": recommended,
        }
    elif kind == "study":
        symbols = [s for s in document.get("symbols") or [] if isinstance(s, str)]
        block |= {
            "symbols": symbols,
            "timeframe": document.get("timeframe"),
            "start": _as_text(document.get("start")),
            "end": _as_text(document.get("end")),
        }
        block["headline"] = {
            "symbols": symbols,
            "windows": (document.get("progress") or {}).get("windows_total"),
            "summary_line": (document.get("report") or {}).get("summary"),
        }
    return block


# --- annotations (spec §6.1) --------------------------------------------------------------------


class Annotations:
    """Labels, notes and stars in one small file, `library/annotations.json`, keyed kind:id."""

    def __init__(self, repository: RunRepository) -> None:
        root = getattr(repository, "root", None)
        self.path = Path(root) / "library" / "annotations.json" if root is not None else None

    def all(self) -> dict[str, dict]:
        if self.path is None or not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


# --- the index ------------------------------------------------------------------------------------


class Library:
    def __init__(
        self, repository: RunRepository, experiments: ExperimentStore | None = None
    ) -> None:
        self.repository = repository
        self.experiments = experiments
        self.annotations = Annotations(repository)

    def _summaries(self, kind: str) -> list[dict]:
        lister = getattr(self.repository, LISTERS[kind], None)
        try:
            return lister() if lister is not None else []
        except (OSError, ValueError):
            return []

    def _block(self, kind: str, identifier: str) -> dict:
        try:
            document = self.repository.read_document(FOLDERS[kind], identifier)
        except (KeyError, OSError, ValueError):
            document = {}
        try:
            block = headline(kind, document, self.experiments)
        except Exception:  # noqa: BLE001 - a document the index cannot read lists with "—"
            block = {"headline": {}}
        return {"version": VERSION, **block}

    def entries(self, budget_seconds: float = 1.5) -> tuple[list[LibraryEntry], int]:
        deadline = time.perf_counter() + budget_seconds
        notes = self.annotations.all()
        entries: list[LibraryEntry] = []
        preparing = 0
        for kind in KINDS:
            for summary in self._summaries(kind):
                identifier = summary.get(ID_KEYS[kind])
                if not isinstance(identifier, str):
                    continue
                block = summary.get("library")
                if not (isinstance(block, dict) and block.get("version") == VERSION):
                    if time.perf_counter() < deadline:
                        block = self._block(kind, identifier)
                        try:
                            self.repository.write_summary(
                                FOLDERS[kind], identifier, {**summary, "library": block}
                            )
                        except (OSError, ValueError):
                            pass  # the next query computes it again
                    else:
                        block = None
                        preparing += 1
                entries.append(
                    self._entry(kind, identifier, summary, block, notes.get(f"{kind}:{identifier}"))
                )
        return entries, preparing

    @staticmethod
    def _entry(
        kind: str, identifier: str, summary: dict, block: dict | None, note: dict | None
    ) -> LibraryEntry:
        fallback = (
            headline(kind, summary, None)
            if kind in ("backtest", "optimization", "walkforward")
            else {}
        )
        source = block or {
            "strategy_name": fallback.get("strategy_name"),
            "symbols": fallback.get("symbols", []),
            "timeframe": fallback.get("timeframe"),
            "start": fallback.get("start"),
            "end": fallback.get("end"),
            "headline": {},
        }
        strategy_name = source.get("strategy_name")
        side = (block or {}).get("headline", {}).get("side") or summary.get("side")
        if kind == "backtest":
            name = strategy_name or "Backtest"
        elif kind == "optimization":
            name = f"{strategy_name or 'Strategy'} · {side or ''} optimization".replace("  ", " ")
        elif kind == "walkforward":
            name = f"{strategy_name or 'Strategy'} · {side or ''} walk-forward".replace("  ", " ")
        else:
            name = str(summary.get("name") or identifier)
        links: dict = {}
        if kind == "backtest" and summary.get("experiment_id"):
            links = {"experiment_id": summary["experiment_id"], "cell": summary.get("cell")}
        elif kind == "experiment" and summary.get("parent"):
            links = {"parent": summary["parent"]}
        elif kind == "study" and summary.get("experiment_id"):
            links = {"experiment_id": summary["experiment_id"]}
        note = note or {}
        return LibraryEntry(
            kind=kind,
            id=identifier,
            name=name,
            label=str(note.get("label") or ""),
            notes=str(note.get("notes") or ""),
            starred=bool(note.get("starred")),
            symbols=list(source.get("symbols") or []),
            timeframe=source.get("timeframe"),
            start=source.get("start"),
            end=source.get("end"),
            strategy_id=summary.get("strategy_id"),
            strategy_name=strategy_name,
            created_at=summary.get("created_at"),
            status=summary.get("status") or ("done" if kind == "backtest" else None),
            decision=summary.get("decision") if kind in ("experiment", "study") else None,
            headline=dict(source.get("headline") or {}),
            links=links,
        )

    def query(self, q: LibraryQuery, budget_seconds: float = 1.5) -> dict:
        entries, preparing = self.entries(budget_seconds)
        text = (q.q or "").strip().lower()

        def keep(entry: LibraryEntry) -> bool:
            if q.symbol and q.symbol.upper() not in [s.upper() for s in entry.symbols]:
                return False
            if q.timeframe and entry.timeframe != q.timeframe:
                return False
            if q.strategy and q.strategy not in (entry.strategy_id, entry.strategy_name):
                return False
            if q.starred is not None and entry.starred != q.starred:
                return False
            if q.decision and (entry.decision or {}).get("verdict") != q.decision:
                return False
            if text:
                haystack = " ".join(
                    filter(None, (entry.name, entry.label, entry.notes, entry.strategy_name))
                ).lower()
                if text not in haystack:
                    return False
            return True

        kept = [e for e in entries if keep(e)]
        counts = {kind: sum(1 for e in kept if e.kind == kind) for kind in KINDS}
        if q.kinds:
            kept = [e for e in kept if e.kind in q.kinds]
        kept.sort(key=lambda e: e.created_at or "", reverse=True)
        if q.sort in ("net_pnl", "mar"):
            valued = [e for e in kept if e.headline.get(q.sort) is not None]
            missing = [e for e in kept if e.headline.get(q.sort) is None]
            valued.sort(key=lambda e: float(e.headline[q.sort]), reverse=True)
            kept = valued + missing
        return {
            "total": len(kept),
            "entries": kept[q.offset : q.offset + q.limit],
            "preparing": preparing,
            "counts_by_kind": counts,
        }


__all__ = [
    "FOLDERS",
    "ID_KEYS",
    "KINDS",
    "Annotations",
    "Library",
    "LibraryEntry",
    "LibraryQuery",
    "headline",
]
