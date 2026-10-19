"""Persistence boundary for Aegis runs and optimizations (spec §2b.8).

`RunRepository` is the narrow interface business logic depends on; `JsonRunRepository` is the
only implementation in this slice (JSON files under data/aegis/). A Core-backed repository is
a future option behind the same interface and is not built here.
"""

from __future__ import annotations

import json
import re
import shutil
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


def _check_id(identifier: str) -> str:
    if not isinstance(identifier, str) or not _ID.match(identifier):
        raise ValueError(f"invalid identifier {identifier!r}")
    return identifier


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

    def _save(self, kind: str, key: str, envelope: dict, summarize=_summary) -> str:
        identifier = _check_id(envelope[key])
        folder = self._folder(kind)
        self._write(folder / f"{identifier}.json", envelope)
        # Sidecar summary: listing never has to parse full envelopes (series, equity, cells).
        self._write(folder / f"{identifier}.summary.json", summarize(envelope))
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

    def _list(self, kind: str, summarize=_summary) -> list[dict]:
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
                summary = summarize(self._read(path))
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
        path = folder / f"{identifier}.json"
        if not path.is_file():
            raise KeyError(experiment_id)
        _retry(path.unlink)
        sidecar = folder / f"{identifier}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
        for kind in ("cells", "curves", "reports"):
            tree = folder / f"{identifier}.{kind}"
            if tree.is_dir():
                shutil.rmtree(tree, ignore_errors=True)

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
        path = folder / f"{identifier}.json"
        if not path.is_file():
            raise KeyError(study_id)
        _retry(path.unlink)
        sidecar = folder / f"{identifier}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
        tree = folder / f"{identifier}.windows"
        if tree.is_dir():
            shutil.rmtree(tree, ignore_errors=True)

    def delete_strategy(self, strategy_id: str) -> None:
        folder = self._folder("strategies")
        path = folder / f"{_check_id(strategy_id)}.json"
        if not path.is_file():
            raise KeyError(strategy_id)
        _retry(path.unlink)
        sidecar = folder / f"{strategy_id}.summary.json"
        if sidecar.is_file():
            _retry(sidecar.unlink)
