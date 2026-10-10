"""Persistence boundary for Aegis runs and optimizations (spec §2b.8).

`RunRepository` is the narrow interface business logic depends on; `JsonRunRepository` is the
only implementation in this slice (JSON files under data/aegis/). A Core-backed repository is
a future option behind the same interface and is not built here.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Protocol

from products.aegis.data import DATA_ROOT

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
    "ms_per_bar",
    "kind",
    "windows",
    "in_sample_bars",
    "out_of_sample_bars",
    "cells_per_window",
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


def _check_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise ValueError(f"invalid identifier {identifier!r}")
    return identifier


def _summary(envelope: dict) -> dict:
    return {key: envelope[key] for key in SUMMARY_KEYS if key in envelope}


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


class JsonRunRepository:
    """One JSON file per run (`runs/<run_id>.json`) and per optimization (`optimizations/`)."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else DATA_ROOT / "data" / "aegis"

    def _folder(self, kind: str) -> Path:
        folder = self.root / kind
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _save(self, kind: str, key: str, envelope: dict) -> str:
        identifier = _check_id(envelope[key])
        folder = self._folder(kind)
        self._write(folder / f"{identifier}.json", envelope)
        # Sidecar summary: listing never has to parse full envelopes (series, equity, cells).
        self._write(folder / f"{identifier}.summary.json", _summary(envelope))
        return identifier

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True, allow_nan=False), encoding="utf-8")
        _retry(lambda: tmp.replace(path))  # Windows refuses the swap while a reader holds the file

    @staticmethod
    def _read(path: Path) -> dict:
        return _retry(lambda: json.loads(path.read_text(encoding="utf-8")))

    def _get(self, kind: str, identifier: str) -> dict:
        path = self._folder(kind) / f"{_check_id(identifier)}.json"
        if not path.is_file():
            raise KeyError(identifier)
        return self._read(path)

    def _list(self, kind: str) -> list[dict]:
        folder = self._folder(kind)
        items: dict[str, dict] = {}
        for path in folder.glob("*.summary.json"):
            try:
                items[path.name[: -len(".summary.json")]] = self._read(path)
            except (OSError, ValueError):
                continue  # a torn write never hides the rest of the history
        for path in folder.glob("*.json"):
            if path.name.endswith(".summary.json") or path.stem in items:
                continue
            try:  # legacy envelope without a sidecar: summarize once and keep the sidecar
                summary = _summary(self._read(path))
            except (OSError, ValueError):
                continue
            items[path.stem] = summary
            try:
                self._write(folder / f"{path.stem}.summary.json", summary)
            except OSError:
                pass
        return sorted(items.values(), key=lambda item: item.get("created_at", ""), reverse=True)

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
