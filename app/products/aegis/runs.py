"""Persistence boundary for Aegis runs and optimizations (spec §2b.8).

`RunRepository` is the narrow interface business logic depends on; `JsonRunRepository` is the
only implementation in this slice (JSON files under data/aegis/). A Core-backed repository is
a future option behind the same interface and is not built here.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import threading
import time
import zlib
from pathlib import Path
from typing import Protocol

from products.aegis.data import DATA_ROOT

log = logging.getLogger("aegis")

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SUMMARY_KEYS = (
    "run_id",
    "job_id",
    "created_at",
    "elapsed_ms",
    "result_hash",
    "data",
    "strategy",
    "side",
    "status",
    "objective",
    "progress",
    "total_cells",
    "skipped_cells",
    "cells_done",
    "pooled",
    "ms_per_cell_bar",
    "ms_per_bar",
    "kind",
    "windows",
    "in_sample_bars",
    "out_of_sample_bars",
    "cells_per_window",
    "strategy_id",
    "strategy_hash",
    "experiment_id",
    "cell",
    "engine",
)
EXPERIMENT_SUMMARY_KEYS = (
    "id",
    "name",
    "strategy_id",
    "strategy_hash",
    "objective",
    "status",
    "progress",
    "created_at",
    "updated_at",
    "parent",
    "decision",
    "latest_report",
    "job_id",
    "engine",
    "budget",
    "tolerance",
    "ms_per_cell_bar",
    "error",
    # Optimization Lab v2: provenance in the listing; a sidecar written before simply lacks them
    "cells_layout",
    "data_pinned",
    "versions",
)
STUDY_SUMMARY_KEYS = (
    "id",
    "name",
    "experiment_id",
    "status",
    "progress",
    "symbols",
    "objective",
    "created_at",
    "updated_at",
    "decision",
    "job_id",
    "error",
)
# What belongs to one item beside its document, as `<id>.<entry>`: moved with it to Recently
# deleted, restored with it and removed by its hard delete, so the three paths share one list.
# Every entry is a folder except `events.jsonl`, a file: a loose `<id>.*.json` would list as a
# document (`_list`), so the views live in a folder of their own.
ITEM_FOLDERS = {
    "experiments": (
        "cells",
        "curves",
        "reports",
        "replays",
        "final",
        "folds",
        "searchspaces",
        "holdout",
        "views",
        "events.jsonl",
    ),
    "studies": ("windows",),
}
STRATEGY_SUMMARY_KEYS = (
    "id",
    "name",
    "created_at",
    "updated_at",
    "strategy_hash",
    "parent",
    "builtin",
)


class RunRepository(Protocol):
    def save_run(self, envelope: dict) -> str: ...
    def get_run(self, run_id: str) -> dict: ...
    def list_runs(self) -> list[dict]: ...
    def save_optimization(self, envelope: dict) -> str: ...
    def get_optimization(self, job_id: str) -> dict: ...
    def list_optimizations(self) -> list[dict]: ...
    def save_walkforward(self, envelope: dict) -> str: ...
    def get_walkforward(self, job_id: str) -> dict: ...
    def list_walkforwards(self) -> list[dict]: ...
    def save_strategy(self, document: dict) -> str: ...
    def get_strategy(self, strategy_id: str) -> dict: ...
    def list_strategies(self) -> list[dict]: ...
    def delete_strategy(self, strategy_id: str) -> None: ...
    def save_experiment(self, document: dict) -> str: ...
    def get_experiment(self, experiment_id: str) -> dict: ...
    def list_experiments(self) -> list[dict]: ...
    def delete_experiment(self, experiment_id: str) -> None: ...
    def experiment_dir(self, experiment_id: str, kind: str) -> Path: ...
    def save_study(self, document: dict) -> str: ...
    def get_study(self, study_id: str) -> dict: ...
    def list_studies(self) -> list[dict]: ...
    def delete_study(self, study_id: str) -> None: ...
    def study_dir(self, study_id: str) -> Path: ...
    def read_document(self, folder: str, identifier: str) -> dict: ...
    def cache_summary(self, folder: str, identifier: str, expected: dict, block: dict) -> bool: ...
    def move_to_trash(self, folder: str, identifier: str, meta: dict) -> None: ...
    def restore_from_trash(self, folder: str, identifier: str) -> None: ...
    def list_trash(self) -> list[dict]: ...
    def heal_trash(self) -> list[str]: ...
    def read_trashed(self, folder: str, identifier: str) -> dict: ...
    def erase_from_trash(self, folder: str, identifier: str) -> None: ...
    def trashed_ids(self, folder: str) -> set[str]: ...


class ExperimentReferenced(Exception):
    """An experiment that live experiments still name as their parent cannot be deleted (409):
    each child goes first, as each study does before its experiment."""

    def __init__(self, identifier: str, children: list[str]) -> None:
        self.identifier, self.children = identifier, children
        super().__init__(
            f"experiment {identifier} is the parent of {', '.join(children)}; delete them first"
        )


def _check_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise ValueError(f"invalid identifier {identifier!r}")
    return identifier


# Mission 11: a document is saved gzip-compressed as `<id>.json.gz`; one saved before is a plain
# `<id>.json` and still reads. Sidecars, trash.json and every other small file stay plain.
COMPRESS_LEVEL = 6
DOCUMENT_FORMS = (".json.gz", ".json")  # the compressed form first: it is the newer one


def document_path(folder: Path, identifier: str) -> Path | None:
    """Where an item's document is in `folder`: compressed, else plain, else None."""
    for suffix in DOCUMENT_FORMS:
        path = folder / f"{identifier}{suffix}"
        if path.is_file():
            return path
    return None


def _summary(envelope: dict) -> dict:
    return {key: envelope[key] for key in SUMMARY_KEYS if key in envelope}


def _experiment_summary(document: dict) -> dict:
    """An experiment's listing entry: identity, status, progress, the plan's headline numbers
    and the surface's size, never the spec or the levers."""
    plan = document.get("plan") or {}
    parameters = (document.get("surface") or {}).get("parameters") or []
    return {
        **{key: document[key] for key in EXPERIMENT_SUMMARY_KEYS if key in document},
        "mode": plan.get("mode"),
        "planned_runs": plan.get("planned_runs"),
        "valid_cells": plan.get("valid_cells"),
        "sampled_fraction": plan.get("sampled_fraction"),
        "estimate_seconds": plan.get("estimate_seconds"),
        "parameters": len(parameters),
        "paths": [p.get("path") for p in parameters],
    }


def _study_summary(document: dict) -> dict:
    """A study's listing entry: identity, parent, status and progress, never its windows or
    report."""
    return {key: document[key] for key in STUDY_SUMMARY_KEYS if key in document}


def _strategy_summary(document: dict) -> dict:
    """A strategy document's listing entry: identity, timestamps, hash and the kinds it uses."""
    spec = document.get("spec") or {}
    kinds = sorted(
        {
            str(indicator.get("kind", "")).upper()
            for side in ("long_side", "short_side")
            for indicator in (spec.get(side) or {}).get("indicators", [])
        }
    )
    return {
        **{key: document[key] for key in STRATEGY_SUMMARY_KEYS if key in document},
        "kinds": kinds,
    }


# Every summary sidecar write takes this lock, so the library's cache write can compare the
# sidecar it read with the one on disk and never put back a copy a save has replaced (Mission 9
# final review I2).
_SIDECARS = threading.RLock()


def _drop_superseded(plain: Path) -> None:
    """Remove the plain document a compressed save replaced. Best effort: a leftover is harmless
    (the compressed one wins every read) and the next save removes it, so a held or already
    removed file never fails the save (Mission 11 review)."""
    try:
        _retry(lambda: plain.unlink(missing_ok=True))
    except OSError as exc:
        log.warning("superseded %s kept for the next save: %s", plain.name, exc)


def _unlink_document(folder: Path, identifier: str) -> None:
    """Remove an item's document in either form (both when a crash left both); KeyError if none."""
    paths = [folder / f"{identifier}{suffix}" for suffix in DOCUMENT_FORMS]
    present = [path for path in paths if path.is_file()]
    if not present:
        raise KeyError(identifier)
    for path in present:
        _retry(path.unlink)


def _retry(action, attempts: int = 50, delay: float = 0.01):
    """Run a file operation that Windows may refuse while another handle is open on the file."""
    for attempt in range(attempts):
        try:
            return action()
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
    return None  # unreachable; keeps type checkers calm


def aegis_data_root() -> Path:
    """Where the worker keeps its saved documents: `AEGIS_DATA_ROOT` when it is set and not empty
    (a scratch worker's store, Optimization Lab v2 Phase 2), else `data/aegis` in this checkout.
    It moves the run store only; the raw archives stay under `DATA_ROOT`."""
    configured = os.environ.get("AEGIS_DATA_ROOT")
    return Path(configured) if configured else DATA_ROOT / "data" / "aegis"


class JsonRunRepository:
    """One document per run (`runs/<run_id>.json.gz`, plain `.json` before Mission 11) and per
    optimization (`optimizations/`), each with a plain summary sidecar."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else aegis_data_root()

    def _folder(self, kind: str) -> Path:
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _save(self, kind: str, key: str, envelope: dict, summarize=_summary) -> str:
        identifier = _check_id(envelope[key])
        folder = self._folder(kind)
        self._write_document(folder, identifier, envelope)
        # Sidecar summary: listing never has to parse full envelopes (series, equity, cells).
        with _SIDECARS:
            self._write(folder / f"{identifier}.summary.json", summarize(envelope))
        return identifier

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8")
        _retry(lambda: tmp.replace(path))  # Windows refuses the swap while a reader holds the file

    @staticmethod
    def _write_document(folder: Path, identifier: str, payload: dict) -> None:
        """The document as today's JSON, gzip-compressed and swapped in whole; a plain predecessor
        is removed only after (a crash in between leaves both, and the compressed one wins)."""
        path = folder / f"{identifier}.json.gz"
        tmp = path.with_name(path.name + ".tmp")
        text = json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")
        tmp.write_bytes(gzip.compress(text, compresslevel=COMPRESS_LEVEL, mtime=0))
        _retry(lambda: tmp.replace(path))
        _drop_superseded(folder / f"{identifier}.json")

    @staticmethod
    def _read(path: Path) -> dict:
        if not path.name.endswith(".gz"):
            return _retry(lambda: json.loads(path.read_text(encoding="utf-8")))

        def load() -> dict:
            try:
                return json.loads(gzip.decompress(path.read_bytes()))
            except (gzip.BadGzipFile, EOFError, zlib.error) as exc:  # torn like a plain file
                raise ValueError(f"unreadable compressed document {path.name}: {exc}") from exc

        return _retry(load)

    def _get(self, kind: str, identifier: str) -> dict:
        folder = self._folder(kind)
        path = document_path(folder, _check_id(identifier))
        if path is None:
            raise KeyError(identifier)
        try:
            return self._read(path)
        except FileNotFoundError:
            # a save swapped in the compressed form and removed this plain one between finding
            # and reading it (a document's first save since Mission 11): read the new one
            path = document_path(folder, identifier)
            if path is None:
                raise KeyError(identifier) from None
            return self._read(path)

    def _list(self, kind: str, summarize=_summary) -> list[dict]:
        folder = self._folder(kind)
        items: dict[str, dict] = {}
        for path in folder.glob("*.summary.json"):
            try:
                items[path.name[: -len(".summary.json")]] = self._read(path)
            except (OSError, ValueError):
                continue  # a torn write never hides the rest of the history
        # a document without a sidecar: summarize once and keep the sidecar; the compressed form
        # first, so an item in both forms is summarized from its newer document, once
        for path in [*folder.glob("*.json.gz"), *folder.glob("*.json")]:
            name = path.name
            if name.endswith(".summary.json"):
                continue
            identifier = name[: -len(".json.gz")] if name.endswith(".gz") else name[: -len(".json")]
            if identifier in items:
                continue
            try:
                summary = summarize(self._read(path))
            except (OSError, ValueError):
                continue
            items[identifier] = summary
            try:
                self._write(folder / f"{identifier}.summary.json", summary)
            except OSError:
                pass
        return sorted(items.values(), key=lambda item: item.get("created_at", ""), reverse=True)

    # The Results library (Mission 9): read any kind's document and rewrite its summary sidecar
    # with the library's cached block (plan ruling P1).
    def read_document(self, folder: str, identifier: str) -> dict:
        return self._get(folder, identifier)

    def cache_summary(self, folder: str, identifier: str, expected: dict, block: dict) -> bool:
        """Add the library's block to the sidecar only while it is still the copy the index
        read; a save in between wins and the next query computes the block again."""
        path = self._folder(folder) / f"{_check_id(identifier)}.summary.json"
        with _SIDECARS:
            try:
                current = self._read(path)
            except (OSError, ValueError):
                return False
            if current != expected:
                return False
            self._write(path, {**current, "library": block})
            return True

    # Recently deleted (Mission 9 spec §6.2, plan ruling P3): an item's document, sidecar and
    # folders move to trash/<folder>/<id>/ with trash.json; restore moves them back.
    def _trash(self, folder: str, identifier: str) -> Path:
        return self.root / "trash" / folder / _check_id(identifier)

    def _item_paths(self, folder: str, identifier: str) -> list[Path]:
        base = self._folder(folder)
        names = [f"{identifier}{suffix}" for suffix in DOCUMENT_FORMS]
        names += [f"{identifier}.summary.json"]
        names += [f"{identifier}.{suffix}" for suffix in ITEM_FOLDERS.get(folder, ())]
        return [base / name for name in names if (base / name).exists()]

    # The document's place decides where an item is (final review I4): a delete moves it last and
    # a restore moves it first, so an interrupted move leaves the item live with some pieces in
    # its trash folder. The next delete or restore of the item, and `heal_trash` at startup, put
    # those pieces back; nothing is overwritten and Empty never sees them.
    def _stranded(self, folder: str, identifier: str) -> bool:
        target = self._trash(folder, identifier)
        return target.is_dir() and document_path(target, identifier) is None

    def _bring_back(self, folder: str, identifier: str) -> None:
        """Move a trash folder's remaining pieces back beside the live document; a piece present
        on both sides stays where it is and keeps the folder."""
        target, live = self._trash(folder, identifier), self._folder(folder)
        clash = False
        for path in sorted(target.iterdir()):
            if path.name == "trash.json":
                continue
            if (live / path.name).exists():
                clash = True
                continue
            _retry(lambda path=path: shutil.move(str(path), str(live / path.name)))
        if not clash:
            shutil.rmtree(target, ignore_errors=True)

    def move_to_trash(self, folder: str, identifier: str, meta: dict) -> None:
        source = document_path(self._folder(folder), _check_id(identifier))
        if source is None:
            raise KeyError(identifier)
        target = self._trash(folder, identifier)
        if document_path(target, identifier) is not None:
            raise FileExistsError(f"{folder}/{identifier} is already in Recently deleted")
        if target.exists():
            self._bring_back(folder, identifier)  # an earlier move stopped part way
        if target.exists():
            raise FileExistsError(
                f"{folder}/{identifier} has pieces in Recently deleted that clash with the live item"
            )
        target.mkdir(parents=True)
        self._write(target / "trash.json", meta)
        pieces = [p for p in self._item_paths(folder, identifier) if p != source] + [source]
        for path in pieces:  # the document last: once it has moved, the item is deleted
            _retry(lambda path=path: shutil.move(str(path), str(target / path.name)))

    def restore_from_trash(self, folder: str, identifier: str) -> None:
        target = self._trash(folder, identifier)
        live = self._folder(folder)
        document = document_path(target, _check_id(identifier))
        if document is None:
            if self._stranded(folder, identifier) and document_path(live, identifier) is not None:
                self._bring_back(folder, identifier)  # an earlier move stopped part way
                return
            raise KeyError(identifier)
        if document_path(live, identifier) is not None:
            raise FileExistsError(f"an item with id {identifier} exists")
        _retry(lambda: shutil.move(str(document), str(live / document.name)))  # now live
        self._bring_back(folder, identifier)

    def heal_trash(self) -> list[str]:
        """Finish every move a crash or a refused file left part way (run at startup)."""
        healed = []
        root = self.root / "trash"
        for target in sorted(root.glob("*/*")) if root.is_dir() else []:
            folder, identifier = target.parent.name, target.name
            if not target.is_dir() or not self._stranded(folder, identifier):
                continue
            if document_path(self._folder(folder), identifier) is not None:
                self._bring_back(folder, identifier)
                healed.append(f"{folder}/{identifier}")
        return healed

    def list_trash(self) -> list[dict]:
        """Trashed items: every trash folder holding its document. A torn trash.json still lists,
        by its folder and id, without its deletion time."""
        root = self.root / "trash"
        items = []
        for target in sorted(root.glob("*/*")) if root.is_dir() else []:
            folder, identifier = target.parent.name, target.name
            if document_path(target, identifier) is None:
                continue
            try:
                meta = self._read(target / "trash.json")
            except (OSError, ValueError):
                meta = {}
            items.append({**meta, "id": identifier, "folder": folder})
        return items

    def read_trashed(self, folder: str, identifier: str) -> dict:
        path = document_path(self._trash(folder, identifier), identifier)
        if path is None:
            raise KeyError(identifier)
        return self._read(path)

    def erase_from_trash(self, folder: str, identifier: str) -> None:
        target = self._trash(folder, identifier)
        if document_path(target, _check_id(identifier)) is None:
            raise KeyError(identifier)  # only a trashed item, never a live item's stranded piece
        shutil.rmtree(target)

    def trashed_ids(self, folder: str) -> set[str]:
        root = self.root / "trash" / folder
        return {p.name for p in root.iterdir() if p.is_dir()} if root.is_dir() else set()

    def save_run(self, envelope: dict) -> str:
        return self._save("runs", "run_id", envelope)

    def get_run(self, run_id: str) -> dict:
        return self._get("runs", run_id)

    def list_runs(self) -> list[dict]:
        return self._list("runs")

    def save_optimization(self, envelope: dict) -> str:
        return self._save("optimizations", "job_id", envelope)

    def get_optimization(self, job_id: str) -> dict:
        return self._get("optimizations", job_id)

    def list_optimizations(self) -> list[dict]:
        return self._list("optimizations")

    def save_walkforward(self, envelope: dict) -> str:
        return self._save("walkforward", "job_id", envelope)

    def get_walkforward(self, job_id: str) -> dict:
        return self._get("walkforward", job_id)

    def list_walkforwards(self) -> list[dict]:
        return self._list("walkforward")

    # Strategy documents (Mission 5 spec §8): one JSON file per document under strategies/.
    def save_strategy(self, document: dict) -> str:
        return self._save("strategies", "id", document, _strategy_summary)

    def get_strategy(self, strategy_id: str) -> dict:
        return self._get("strategies", strategy_id)

    def list_strategies(self) -> list[dict]:
        return self._list("strategies", _strategy_summary)

    # Experiments (Mission 6 spec §6.2): the document on the repository, its cells, curves and
    # reports as files beside it, all named by the experiment id.
    def save_experiment(self, document: dict) -> str:
        return self._save("experiments", "id", document, _experiment_summary)

    def get_experiment(self, experiment_id: str) -> dict:
        return self._get("experiments", experiment_id)

    def list_experiments(self) -> list[dict]:
        return self._list("experiments", _experiment_summary)

    def experiment_dir(self, experiment_id: str, kind: str) -> Path:
        return self._folder("experiments") / f"{_check_id(experiment_id)}.{kind}"

    def delete_experiment(self, experiment_id: str) -> None:
        folder = self._folder("experiments")
        identifier = _check_id(experiment_id)
        _unlink_document(folder, identifier)
        sidecar = folder / f"{identifier}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
        for entry in ITEM_FOLDERS["experiments"]:  # the trash's list: nothing of it stays behind
            path = folder / f"{identifier}.{entry}"
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                _retry(path.unlink)

    # Studies (Mission 8 spec §6): the document on the repository, each window's files under
    # `studies/<id>.windows/<symbol>/`.
    def save_study(self, document: dict) -> str:
        return self._save("studies", "id", document, _study_summary)

    def get_study(self, study_id: str) -> dict:
        return self._get("studies", study_id)

    def list_studies(self) -> list[dict]:
        return self._list("studies", _study_summary)

    def study_dir(self, study_id: str) -> Path:
        return self._folder("studies") / f"{_check_id(study_id)}.windows"

    def delete_study(self, study_id: str) -> None:
        folder = self._folder("studies")
        identifier = _check_id(study_id)
        _unlink_document(folder, identifier)
        sidecar = folder / f"{identifier}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
        tree = folder / f"{identifier}.windows"
        if tree.is_dir():
            shutil.rmtree(tree, ignore_errors=True)

    def delete_strategy(self, strategy_id: str) -> None:
        folder = self._folder("strategies")
        _unlink_document(folder, _check_id(strategy_id))
        sidecar = folder / f"{strategy_id}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
