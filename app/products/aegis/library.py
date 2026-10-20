"""The Results library (Mission 9 spec §4, §6): one index of every saved result.

The index merges the summary sidecars every kind already keeps. A summary that lacks the library's
block (the headline numbers, symbols, range and strategy name) has it computed once from the full
document and written back into the sidecar (plan ruling P1); any later save of the item rewrites the
sidecar without it, so the block is recomputed and never stale. A query computes at most a budget's
worth of blocks and reports the rest as `preparing` (P2).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from products.aegis.experiments import ExperimentStore
from products.aegis.runs import RunRepository, _retry

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
VERSION = 2  # 2: an optimization's cells_run counts cells, not a pooled job's chunks
UNFINISHED_JOBS = ("queued", "running")
UNFINISHED_DOCUMENTS = ("queued", "running", "paused")
LABEL_MAX = 80
NOTES_MAX = 2000
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
    deleted_at: str | None = None
    # False while the headline waits for the backfill; True once computed, even when the
    # document gave nothing to show (it then lists with "—", never "preparing…").
    ready: bool = True


class Refused(Exception):
    """A delete or restore the rules refuse (409, naming the reason)."""


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
            # a pooled job's progress counts chunks; cells_done counts cells (the limits change)
            "cells_run": document.get("cells_done", progress.get("done")),
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

    _lock = threading.Lock()

    def all(self) -> dict[str, dict]:
        """For listing: an unreadable file lists as no annotations."""
        try:
            return self._load()
        except (OSError, ValueError):
            return {}

    def _load(self) -> dict[str, dict]:
        """For a write: a busy file is retried, and one still unreadable raises rather than read
        as empty, so a save never writes back only its own note (final review I5)."""
        if self.path is None or not self.path.is_file():
            return {}
        data = _retry(lambda: json.loads(self.path.read_text(encoding="utf-8")))
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        if self.path is None:
            raise OSError("annotations need a file-backed repository")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        _retry(lambda: tmp.replace(self.path))  # Windows refuses the swap while a reader holds it

    def get(self, kind: str, identifier: str) -> dict:
        return self.all().get(f"{kind}:{identifier}", {})

    def set(
        self,
        kind: str,
        identifier: str,
        label: str | None = None,
        notes: str | None = None,
        starred: bool | None = None,
    ) -> dict:
        """Write the given fields; a field passed as None keeps its stored value."""
        if label is not None and len(label) > LABEL_MAX:
            raise ValueError(f"label longer than {LABEL_MAX} characters")
        if notes is not None and len(notes) > NOTES_MAX:
            raise ValueError(f"notes longer than {NOTES_MAX} characters")
        with self._lock:
            data = self._load()
            note = {
                "label": "",
                "notes": "",
                "starred": False,
                **data.get(f"{kind}:{identifier}", {}),
            }
            if label is not None:
                note["label"] = label
            if notes is not None:
                note["notes"] = notes
            if starred is not None:
                note["starred"] = bool(starred)
            data[f"{kind}:{identifier}"] = note
            self._save(data)
        return note

    def remove(self, kind: str, identifier: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(f"{kind}:{identifier}", None) is not None:
                self._save(data)


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
                        # A queued or running job saves again soon (and drops the block), so its
                        # headline is computed for this listing and never cached.
                        if summary.get("status") not in UNFINISHED_JOBS:
                            try:
                                self.repository.cache_summary(
                                    FOLDERS[kind], identifier, summary, block
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
            ready=block is not None,
        )

    # -- housekeeping (spec §6.2) --------------------------------------------------------------
    def _live(self, kind: str, identifier: str) -> dict:
        if kind not in KINDS:
            raise KeyError(kind)
        return self.repository.read_document(FOLDERS[kind], identifier)  # KeyError when unknown

    def delete(self, kind: str, identifier: str) -> None:
        """Move an item to Recently deleted, or raise Refused naming why it cannot go."""
        document = self._live(kind, identifier)
        status = document.get("status")
        if kind in ("optimization", "walkforward") and status in UNFINISHED_JOBS:
            raise Refused(f"{kind} {identifier} is {status}; cancel it first")
        if kind in ("experiment", "study") and status in UNFINISHED_DOCUMENTS:
            raise Refused(f"{kind} {identifier} is {status}; cancel it first")
        if kind == "experiment":
            children = [
                s.get("id")
                for s in self._summaries("study")
                if s.get("experiment_id") == identifier
            ]
            if children:
                raise Refused(
                    f"experiment {identifier} has studies: {', '.join(children)}; delete them first"
                )
        block = headline(kind, document, self.experiments)
        name = self._entry(kind, identifier, document, {"version": VERSION, **block}, None).name
        meta = {
            "kind": kind,
            "id": identifier,
            "name": name,
            "deleted_at": datetime.now(UTC).isoformat(),
        }
        try:
            self.repository.move_to_trash(FOLDERS[kind], identifier, meta)
        except FileExistsError as exc:
            raise Refused(str(exc)) from exc

    def restore(self, kind: str, identifier: str) -> None:
        if kind not in KINDS:
            raise KeyError(kind)
        folder = FOLDERS[kind]
        if kind == "study":
            try:
                parent = self.repository.read_trashed(folder, identifier).get("experiment_id")
            except KeyError:
                parent = None  # live already: the repository finishes a move that stopped
            if parent:
                try:
                    self.repository.read_document(FOLDERS["experiment"], parent)
                except KeyError as exc:
                    raise Refused(
                        f"study {identifier} needs its experiment {parent} restored first"
                    ) from exc
        try:
            self.repository.restore_from_trash(folder, identifier)
        except FileExistsError as exc:
            raise Refused(str(exc)) from exc

    def empty(self, items: list[tuple[str, str]] | None = None) -> int:
        """Erase trashed items for good (all, or the named ones); their annotations go too."""
        if items is None:
            items = [(self._trash_kind(t), t.get("id")) for t in self.repository.list_trash()]
        erased = 0
        for kind, identifier in items:
            if kind not in KINDS or not isinstance(identifier, str):
                continue
            try:
                self.repository.erase_from_trash(FOLDERS[kind], identifier)
            except KeyError:
                continue
            self.annotations.remove(kind, identifier)
            erased += 1
        return erased

    @staticmethod
    def _trash_kind(meta: dict) -> str | None:
        """The trash record's kind, or its folder's when the record is torn."""
        kind = meta.get("kind")
        if kind in KINDS:
            return kind
        return next((k for k, folder in FOLDERS.items() if folder == meta.get("folder")), None)

    def trashed(self) -> list[LibraryEntry]:
        notes = self.annotations.all()
        entries = []
        for meta in self.repository.list_trash():
            kind, identifier = self._trash_kind(meta), meta.get("id")
            if kind not in KINDS or not isinstance(identifier, str):
                continue
            try:
                document = self.repository.read_trashed(FOLDERS[kind], identifier)
            except (KeyError, OSError, ValueError):
                document = {}
            try:
                block = {"version": VERSION, **headline(kind, document, None)}
            except Exception:  # noqa: BLE001 - a trashed document lists with "—"
                block = {"version": VERSION, "headline": {}}
            entry = self._entry(
                kind, identifier, document, block, notes.get(f"{kind}:{identifier}")
            )
            entries.append(
                entry.model_copy(update={"status": "deleted", "deleted_at": meta.get("deleted_at")})
            )
        return entries

    def entry(self, kind: str, identifier: str) -> LibraryEntry:
        """One item by id, live or in Recently deleted (the page opens an item that its current
        list page does not show; milestone QA D2). KeyError when neither knows it."""
        if kind not in KINDS:
            raise KeyError(kind)
        notes = self.annotations.all()
        for summary in self._summaries(kind):
            if summary.get(ID_KEYS[kind]) != identifier:
                continue
            block = summary.get("library")
            if not (isinstance(block, dict) and block.get("version") == VERSION):
                block = self._block(kind, identifier)
            return self._entry(kind, identifier, summary, block, notes.get(f"{kind}:{identifier}"))
        for entry in self.trashed():
            if entry.kind == kind and entry.id == identifier:
                return entry
        raise KeyError(identifier)

    def query(self, q: LibraryQuery, budget_seconds: float = 1.5) -> dict:
        if q.deleted:
            entries, preparing = self.trashed(), 0
        else:
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
    "Refused",
    "headline",
]
