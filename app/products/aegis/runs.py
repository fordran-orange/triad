"""Persistence boundary for Aegis runs and optimizations (spec §2b.8).

`RunRepository` is the narrow interface business logic depends on; `JsonRunRepository` is the
only implementation in this slice (JSON files under data/aegis/). A Core-backed repository is
a future option behind the same interface and is not built here.
"""

from __future__ import annotations

import json
import re
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
)


class RunRepository(Protocol):
    def save_run(self, envelope: dict) -> str: ...
    def get_run(self, run_id: str) -> dict: ...
    def list_runs(self) -> list[dict]: ...
    def save_optimization(self, envelope: dict) -> str: ...
    def get_optimization(self, job_id: str) -> dict: ...
    def list_optimizations(self) -> list[dict]: ...


def _check_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise ValueError(f"invalid identifier {identifier!r}")
    return identifier


def _summary(envelope: dict) -> dict:
    return {key: envelope[key] for key in SUMMARY_KEYS if key in envelope}


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
        path = self._folder(kind) / f"{identifier}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, sort_keys=True, allow_nan=False), encoding="utf-8")
        tmp.replace(path)
        return identifier

    def _get(self, kind: str, identifier: str) -> dict:
        path = self._folder(kind) / f"{_check_id(identifier)}.json"
        if not path.is_file():
            raise KeyError(identifier)
        return json.loads(path.read_text(encoding="utf-8"))

    def _list(self, kind: str) -> list[dict]:
        items = []
        for path in self._folder(kind).glob("*.json"):
            try:
                items.append(_summary(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue  # a torn write never hides the rest of the history
        return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)

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
