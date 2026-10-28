"""The Lab's trial store (Optimization Lab v2 spec §9.2): an experiment's cells folder.

Part 1 (Task 4): the manifest's shape and its atomic write, the chunk-name rule (F16: the next
chunk is named by the highest index ever used + 1, so a file already on disk, readable or torn,
is never overwritten) and the counters the job owns (§6.4). The reader, compaction, snapshots and
reclamation complete it (Task 5). This module never imports `experiments.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from products.aegis.runs import _retry

MANIFEST = "manifest.json"
# `NNNNNN.parquet`, or the `.tmp` a write died inside; indices past 999,999 simply grow a digit.
_CHUNK_NAME = re.compile(r"^([0-9]{6,})\.parquet(?:\.tmp)?$")


@dataclass
class Manifest:
    """`manifest.json` in a layout-2 cells folder (spec:1062, plus `generations`, `unique` and
    `unique_generation`; the schedule lives on the document). `merged_chunks` entries are
    `{file, generation, merged_at}` and `generations` entries `{generation, at, rows,
    compaction_ms, reclaim_ms}`, both written by compaction (Task 5)."""

    layout: int
    generation: int
    parts: list[dict]
    merged_chunks: list[dict]
    generations: list[dict]
    chunk_watermark: int
    unique: int | None
    unique_generation: int | None
    updated_at: str


@dataclass
class Counters:
    """The §6.4 counts the experiment job owns; `reserved`, `remaining`, `reused`,
    `evaluations`, `evaluations_done`, `duplicates`, `filtered`, `shown` and `undefined` are
    derived by the summary route. `unique` is set by compaction (Task 5)."""

    attempted: int = 0
    completed: int = 0
    invalid: int = 0
    failed: int = 0
    scheduled: int = 0
    budget_total: int = 0
    unique: int | None = None
    unique_generation: int | None = None

    def as_dict(self) -> dict:
        return {**asdict(self), "pending": self.scheduled - self.attempted}

    def tally(self, statuses: Iterable[str]) -> None:
        """Count one more attempt per status (`ok`, `invalid` or `failed`)."""
        for status in statuses:
            if status == "ok":
                self.completed += 1
            elif status == "invalid":
                self.invalid += 1
            elif status == "failed":
                self.failed += 1
            else:
                raise ValueError(f"unknown trial status {status!r}")
            self.attempted += 1

    def recount(self, statuses: Iterable[str]) -> None:
        """The four outcome counts from the trials on disk, replacing what a document carried;
        `scheduled`, `budget_total`, `unique` and `unique_generation` are kept."""
        self.attempted = self.completed = self.invalid = self.failed = 0
        self.tally(statuses)

    @classmethod
    def from_document(cls, document) -> Counters:
        """The document's `counts`; a legacy document has none, so its counts start at zero over
        its planned schedule (`Plan.first_pass` equals `valid_cells` for an exhaustive plan,
        surface.py:512, so one expression serves both modes)."""
        if document.counts is not None:
            names = {field.name for field in fields(cls)}
            return cls(**{key: value for key, value in document.counts.items() if key in names})
        return cls(
            scheduled=document.plan["first_pass"] + len(document.refinement_cells or []),
            budget_total=document.plan["planned_runs"],
        )


def read_manifest(cells_dir: Path) -> Manifest | None:
    """The folder's manifest, or None when it has none (a legacy folder, or a decompacted one)."""
    path = cells_dir / MANIFEST
    if not path.is_file():
        return None
    return Manifest(**_retry(lambda: json.loads(path.read_text(encoding="utf-8"))))


def write_manifest(cells_dir: Path, manifest: Manifest) -> None:
    """Written whole beside the old one and swapped in: a reader sees the old or the new."""
    cells_dir.mkdir(parents=True, exist_ok=True)
    path = cells_dir / MANIFEST
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(asdict(manifest), sort_keys=True, allow_nan=False)
    tmp.write_text(payload, encoding="utf-8")
    _retry(lambda: tmp.replace(path))  # Windows refuses the swap while a reader holds the file


def chunk_index_of(path: Path) -> int | None:
    """The index a chunk file is named by (`NNNNNN.parquet` or its `.tmp`); None for any other
    name (a part, the manifest)."""
    match = _CHUNK_NAME.match(path.name)
    return int(match.group(1)) if match else None


def next_chunk_index(cells_dir: Path, manifest: Manifest | None = None) -> int:
    """One past the highest index any chunk name in the folder or the manifest's watermark has
    used, 0 when none has: a reclaimed chunk's index is never reused, or compaction would take
    the new file for one it already merged."""
    names = (chunk_index_of(path) for path in cells_dir.glob("[0-9]*"))
    used = [index for index in names if index is not None]
    if manifest is not None:
        used.append(manifest.chunk_watermark)
    return max(used, default=-1) + 1


__all__ = [
    "MANIFEST",
    "Counters",
    "Manifest",
    "chunk_index_of",
    "next_chunk_index",
    "read_manifest",
    "write_manifest",
]
