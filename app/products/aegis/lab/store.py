"""The Lab's trial store (Optimization Lab v2 spec §9.2): an experiment's cells folder.

Part 1 (Task 4): the manifest's shape and its atomic write, the chunk-name rule (F16: the next
chunk is named by the highest index ever used + 1, so a file already on disk, readable or torn,
is never overwritten) and the counters the job owns (§6.4).

Part 2 (Task 5): the one reader every layout goes through (parts plus the chunks not merged,
copies collapsed, the highest attempt kept; a legacy chunk promoted to the layout-2 columns),
compaction of a layout-2 folder's chunks into parts with the manifest, immutable snapshots with an
in-process registry, the per-experiment reader-writer lock, retention and reclamation, and
`decompact`. A legacy (layout 1) folder is read here and never compacted (§12 retained data).
Retained-data code: independent QA at R3 (AGENTS.md).

This module never imports `experiments.py` at load time (`experiments.py` imports it); the one
definition of the layout-2 columns, `experiments._cells_schema_v2`, is looked up at call time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from products.aegis.lab import identity, policy
from products.aegis.lab.policy import RETAIN_MERGED_SECONDS
from products.aegis.runs import _retry

if TYPE_CHECKING:
    from products.aegis.surface import Grid

log = logging.getLogger("aegis")
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


# --- part 2 (Task 5): snapshots, the reader, compaction, reclamation, decompact ---------------

TRIAL_NO = "trial_no"
# One evaluation's copy is a repeat of all three; the canonical row of (trial_no, block) is its
# highest attempt (§7.3a).
_EVALUATION = ("trial_no", "block", "attempt")
_KEPT = ("trial_no", "block", "status")  # always in a projection, beside the columns asked for


class SnapshotExpired(RuntimeError):
    """A snapshot whose files are not all on disk any more (a chunk reclaimed once the registry
    that held it was lost, a part gone, or a generation the manifest no longer has): reported as
    `snapshot expired`, never served partially (§9.2)."""


@dataclass(frozen=True)
class Snapshot:
    """An immutable file set (§9.2): the parts of generations up to `generation`, plus the chunk
    files with an index up to `chunk_watermark` that no part of those generations merged."""

    generation: int
    chunk_watermark: int


@dataclass
class LegacyContext:
    """What promoting a layout-1 chunk needs: the experiment's grid (`pos.<k>`) and its surface
    paths (the parameter columns), from the document (`ExperimentStore.trials`)."""

    grid: Grid
    paths: list[str]


@dataclass
class TrialTable:
    """The canonical trials of one snapshot. `duplicates` counts the copies collapsed; the store's
    `provisional` is true while the set holds chunks no compaction has merged yet (the Lab routes
    decide theirs from the document's status); `layout` is the folder's."""

    table: pa.Table
    duplicates: int
    snapshot: Snapshot
    provisional: bool
    layout: int


def _experiment_id(cells_dir: Path) -> str:
    """The id a cells folder is named by (`experiments/<id>.cells`, runs.py `experiment_dir`)."""
    return cells_dir.name.removesuffix(".cells")


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).isoformat()


def _layout2_schema(paths: Sequence[str]) -> pa.Schema:
    """The layout-2 columns over `paths`. Their one definition sits beside the writer
    (`experiments._cells_schema_v2`, Task 4) and is looked up at call time, because
    `experiments.py` imports this module."""
    from products.aegis.experiments import _cells_schema_v2

    return _cells_schema_v2(list(paths))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# -- the folder and its snapshots -------------------------------------------------------------


def readable_chunks(cells_dir: Path) -> list[tuple[int, Path]]:
    """The chunk files `pq.read_metadata` accepts, by index (`experiments._readable`'s rule): a
    file it rejects is logged and left out, so it is never merged, its trials stay pending and
    F16 still counts its name."""
    chunks = []
    for path in cells_dir.glob("[0-9]*.parquet"):
        index = chunk_index_of(path)
        if index is None:
            continue
        try:
            pq.read_metadata(path)
        except Exception as exc:  # noqa: BLE001 - an unreadable chunk is rerun, never trusted
            log.warning("experiment chunk %s unreadable, its cells will rerun: %s", path.name, exc)
            continue
        chunks.append((index, path))
    return sorted(chunks)


def _carries_trial_no(path: Path) -> bool:
    try:
        return TRIAL_NO in pq.read_schema(path).names
    except Exception:  # noqa: BLE001 - a chunk gone since it was listed decides nothing
        return False


def _manifest_of(cells_dir: Path, chunks: list[tuple[int, Path]]) -> Manifest:
    """The folder's manifest, or the generation-0 one a folder without `manifest.json` stands
    for: layout 2 when a chunk carries `trial_no` (a decompacted folder), else 1 (a legacy one),
    `ExperimentStore.layout`'s rule."""
    manifest = read_manifest(cells_dir)
    if manifest is not None:
        return manifest
    return Manifest(
        layout=2 if any(_carries_trial_no(path) for _, path in chunks) else 1,
        generation=0,
        parts=[],
        merged_chunks=[],
        generations=[],
        chunk_watermark=max((index for index, _ in chunks), default=-1),
        unique=None,
        unique_generation=None,
        updated_at="",
    )


def _watermark(manifest: Manifest, chunks: list[tuple[int, Path]]) -> int:
    """The highest readable chunk index or the manifest's watermark, whichever is higher: once
    every merged chunk is reclaimed the manifest's is the only record of the indices used, and
    `next_chunk_index`, `file_set` and `unmerged_chunks` agree on it."""
    return max(max((index for index, _ in chunks), default=-1), manifest.chunk_watermark)


def latest_snapshot(cells_dir: Path) -> tuple[Manifest, Snapshot]:
    """The manifest and the latest snapshot, read at the start of a request and only then
    (§9.2); one reader serves a legacy, a decompacted and a layout-2 folder alike."""
    chunks = readable_chunks(cells_dir)
    manifest = _manifest_of(cells_dir, chunks)
    return manifest, Snapshot(manifest.generation, _watermark(manifest, chunks))


def file_set(cells_dir: Path, manifest: Manifest, snapshot: Snapshot) -> list[Path]:
    """The snapshot's files under `manifest` (the latest, which only ever grows): its parts, then
    its readable unmerged chunks by index. `SnapshotExpired` when a listed part or a chunk the
    snapshot relies on is gone; an unreadable chunk is not gone, it is simply not in the set."""
    return _file_set(cells_dir, manifest, snapshot, readable_chunks(cells_dir))


def _file_set(
    cells_dir: Path, manifest: Manifest, snapshot: Snapshot, chunks: list[tuple[int, Path]]
) -> list[Path]:
    if snapshot.generation > manifest.generation:
        raise SnapshotExpired(
            f"{cells_dir.name}: generation {snapshot.generation} is not in the manifest "
            f"(generation {manifest.generation})"
        )
    files = []
    for part in manifest.parts:
        if part["generation"] <= snapshot.generation:
            path = cells_dir / part["file"]
            if not path.is_file():
                raise SnapshotExpired(f"{part['file']} of generation {part['generation']} is gone")
            files.append(path)
    # Membership never depends on reclamation: a chunk merged after the snapshot's generation is
    # still the snapshot's, and its file must still be there.
    merged = {entry["file"]: entry["generation"] for entry in manifest.merged_chunks}
    for name, generation in merged.items():
        index = chunk_index_of(Path(name))
        if (
            generation > snapshot.generation
            and index is not None
            and index <= snapshot.chunk_watermark
            and not (cells_dir / name).exists()
        ):
            raise SnapshotExpired(
                f"{name}, which generation {snapshot.generation} reads, was reclaimed"
            )
    for index, path in chunks:
        generation = merged.get(path.name)
        if index > snapshot.chunk_watermark or (
            generation is not None and generation <= snapshot.generation
        ):
            continue
        files.append(path)
    return files


# -- the lock and the registry ----------------------------------------------------------------


@dataclass
class _ReadWrite:
    condition: threading.Condition = field(default_factory=threading.Condition)
    readers: dict[int, int] = field(default_factory=dict)  # thread -> the reads it holds
    writer: int | None = None
    depth: int = 0  # the writer's own nested holds
    waiting: int = 0  # writers waiting


class ExperimentLocks:
    """One reader-writer lock per experiment id, in-process and writer-preferring: a waiting
    write blocks every new read until it has run, while the reads already held (and a thread's
    re-entrant reads under them) complete first. A reader-preferring lock would let a polling Lab
    client's tight read loop starve the job's compaction forever."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, _ReadWrite] = {}

    def _lock(self, experiment_id: str) -> _ReadWrite:
        with self._guard:
            return self._locks.setdefault(experiment_id, _ReadWrite())

    @contextmanager
    def read(self, experiment_id: str) -> Iterator[None]:
        lock = self._lock(experiment_id)
        me = threading.get_ident()
        with lock.condition:
            if me not in lock.readers and lock.writer != me:  # a nested read never waits
                while lock.writer is not None or lock.waiting:
                    lock.condition.wait()
            lock.readers[me] = lock.readers.get(me, 0) + 1
        try:
            yield
        finally:
            with lock.condition:
                lock.readers[me] -= 1
                if not lock.readers[me]:
                    del lock.readers[me]
                    lock.condition.notify_all()

    @contextmanager
    def write(self, experiment_id: str) -> Iterator[None]:
        lock = self._lock(experiment_id)
        me = threading.get_ident()
        with lock.condition:
            if lock.writer == me:
                lock.depth += 1
            else:
                if me in lock.readers:
                    raise RuntimeError(
                        f"experiment {experiment_id}: a thread holding a read cannot take the "
                        "write lock (it would wait for itself)"
                    )
                lock.waiting += 1
                try:
                    while lock.writer is not None or lock.readers:
                        lock.condition.wait()
                except BaseException:
                    lock.waiting -= 1
                    lock.condition.notify_all()
                    raise
                lock.waiting -= 1
                lock.writer, lock.depth = me, 1
        try:
            yield
        finally:
            with lock.condition:
                lock.depth -= 1
                if not lock.depth:
                    lock.writer = None
                    lock.condition.notify_all()


@dataclass(frozen=True)
class _Hold:
    experiment_id: str
    snapshot: Snapshot
    files: frozenset[Path]


class SnapshotRegistry:
    """The snapshots open in this worker (§9.2): a request holds its snapshot's files for its
    own life (`open` / `release`), a pin from Screen D until it is unpinned (`pin` / `unpin`).
    In-process by design: a restart loses it, and a snapshot whose files were reclaimed since
    answers `SnapshotExpired`."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._holds: dict[int, _Hold] = {}
        self._next = 0

    def open(self, experiment_id: str, snapshot: Snapshot, files: Sequence[Path]) -> int:
        with self._guard:
            self._next += 1
            self._holds[self._next] = _Hold(experiment_id, snapshot, frozenset(files))
            return self._next

    def release(self, handle: int) -> None:
        with self._guard:
            self._holds.pop(handle, None)

    def pin(self, experiment_id: str, snapshot: Snapshot, files: Sequence[Path]) -> int:
        return self.open(experiment_id, snapshot, files)

    def unpin(self, handle: int) -> None:
        self.release(handle)

    def held(self, experiment_id: str) -> set[Path]:
        """Every file an open or pinned snapshot of the experiment references."""
        with self._guard:
            return {
                path
                for hold in self._holds.values()
                if hold.experiment_id == experiment_id
                for path in hold.files
            }


LOCKS = ExperimentLocks()
REGISTRY = SnapshotRegistry()


# -- the reader -------------------------------------------------------------------------------


def _canonical(table: pa.Table) -> tuple[pa.Table, int]:
    """§7.3a in two steps: copies of one (trial_no, block, attempt) collapse to the first one
    read (parts before chunks), counted as duplicates; then the highest attempt of each
    (trial_no, block) is kept. Sorted by trial_no, then block."""
    if not len(table):
        return table, 0
    order = pc.sort_indices(
        table,
        sort_keys=[("trial_no", "ascending"), ("block", "ascending"), ("attempt", "descending")],
    )
    trial, block, attempt = (table.column(name).take(order).to_numpy() for name in _EVALUATION)
    same = np.zeros(len(order), dtype=bool)
    same[1:] = (trial[1:] == trial[:-1]) & (block[1:] == block[:-1])
    copies = same.copy()
    copies[1:] &= attempt[1:] == attempt[:-1]
    keep = order.to_numpy()[~same]
    return table.take(pa.array(keep)), int(copies.sum())


# What every promotion reads from a layout-1 chunk: trial_no is its cell, the status comes from
# valid / skip_reason and the design from its pass.
_PROMOTION_INPUTS = ("cell", "pass", "valid", "skip_reason")


def _legacy_columns(names: list[str], wanted: list[str] | None) -> list[str] | None:
    """The layout-1 columns a promotion to `wanted` reads, in the file's order: its inputs plus
    the wanted columns the chunk holds; every column for the full set (`wanted` None)."""
    if wanted is None:
        return None
    return [name for name in names if name in _PROMOTION_INPUTS or name in wanted]


def _promote(
    raw: pa.Table, index: int, legacy: LegacyContext, names: list[str], wanted: list[str] | None
) -> pa.Table:
    """A layout-1 chunk in the layout-2 columns `wanted` (all of them with None), built as Arrow
    arrays over the columns read, never per row: trial_no = cell, block 0, attempt 0, the design
    of its pass, the status from valid / skip_reason, the chunk's index, pos.<k> from the grid;
    param_key, reused_from, error, the trade Sharpe and finished_at are null (a layout-1 chunk
    holds none of them). `names` is the chunk file's own column list."""
    paths = list(legacy.paths)
    missing = [path for path in paths if path not in names]
    if missing:
        raise ValueError(f"chunk {index:06d} has no column for {', '.join(missing)}")
    schema = _layout2_schema(paths)
    out = schema.names if wanted is None else wanted
    n = len(raw)
    cell = raw.column("cell").combine_chunks()
    cells = cell.to_numpy(zero_copy_only=False)
    grid = legacy.grid
    if n and (cells.min() < 0 or cells.max() >= grid.size):
        raise IndexError(f"chunk {index:06d} holds a cell outside its grid of {grid.size}")

    def build(name: str) -> pa.Array | pa.ChunkedArray:
        kind = schema.field(name).type
        if name == TRIAL_NO:
            return cell
        if name.startswith("pos.") and name[4:].isdigit():
            k = int(name[4:])
            return pa.array((cells // grid.strides[k]) % grid.shape[k], kind)
        if name == "design":
            encoded = raw.column("pass").combine_chunks().dictionary_encode()
            labels = encoded.dictionary.to_pylist()
            designs = pa.array([identity.design_of(label) for label in labels], pa.string())
            return designs.take(encoded.indices).cast(kind)
        if name == "status":
            ok = pc.and_(
                pc.is_null(raw.column("skip_reason")), pc.fill_null(raw.column("valid"), False)
            )
            return pc.if_else(ok, "ok", "invalid").cast(kind)
        if name in ("block", "attempt"):
            return pa.array(np.zeros(n, dtype=np.uint8), kind)
        if name == "chunk":
            return pa.array(np.full(n, index, dtype=np.int32), kind)
        if name in raw.column_names:
            return raw.column(name).cast(kind)
        return pa.nulls(n, kind)

    return pa.Table.from_arrays(
        [build(name) for name in out], schema=pa.schema([schema.field(name) for name in out])
    )


def _read(path: Path, wanted: list[str] | None, legacy: LegacyContext | None) -> pa.Table:
    try:
        with pq.ParquetFile(path) as parquet:  # closed at once: an open handle blocks reclaim
            names = parquet.schema_arrow.names
            if TRIAL_NO in names:
                table = parquet.read(columns=wanted)
                return table if wanted is None else table.select(wanted)
            if legacy is None:
                raise ValueError(
                    f"{path.name} is a layout-1 chunk: it is read with its legacy context"
                )
            raw = parquet.read(columns=_legacy_columns(names, wanted))  # projected, never all
    except FileNotFoundError as exc:
        raise SnapshotExpired(f"{path.name} went missing while its snapshot was read") from exc
    return _promote(raw, chunk_index_of(path), legacy, names, wanted)


def _empty(wanted: list[str] | None, legacy: LegacyContext | None) -> pa.Table:
    """No file yet: the layout-2 columns (the parameter columns only when the paths are known)."""
    schema = _layout2_schema(legacy.paths if legacy is not None else [])
    if wanted is None:
        return schema.empty_table()

    def field_of(name: str) -> pa.Field:
        if name in schema.names:
            return schema.field(name)
        return pa.field(name, pa.uint16() if name.startswith("pos.") else pa.float64())

    return pa.schema([field_of(name) for name in wanted]).empty_table()


def read_trials(
    cells_dir: Path,
    snapshot: Snapshot,
    columns: Sequence[str] | None = None,
    *,
    legacy: LegacyContext | None = None,
) -> TrialTable:
    """The canonical trials of `snapshot`: its file set read (layout-1 chunks promoted through
    `legacy`), copies collapsed and counted, the highest attempt per (trial_no, block) kept,
    sorted by trial_no then block. With `columns`, those plus trial_no, block and status; with
    None the full layout-2 set, so a projection never widens a table."""
    chunks = readable_chunks(cells_dir)
    manifest = _manifest_of(cells_dir, chunks)
    files = _file_set(cells_dir, manifest, snapshot, chunks)
    wanted = None if columns is None else list(dict.fromkeys([*columns, *_EVALUATION, "status"]))
    tables = [_read(path, wanted, legacy) for path in files]
    table = pa.concat_tables(tables) if tables else _empty(wanted, legacy)
    table, duplicates = _canonical(table)
    if columns is not None:
        table = table.select(list(dict.fromkeys([*columns, *_KEPT])))
    provisional = manifest.layout == 2 and any(chunk_index_of(path) is not None for path in files)
    return TrialTable(table, duplicates, snapshot, provisional, manifest.layout)


def read_latest(
    cells_dir: Path,
    columns: Sequence[str] | None = None,
    *,
    legacy: LegacyContext | None = None,
) -> TrialTable:
    """The latest snapshot's canonical trials. `read_trials` is this module's global looked up
    at call time, so a test that patches it is seen by every reader that comes through here."""
    _, snapshot = latest_snapshot(cells_dir)
    return read_trials(cells_dir, snapshot, columns, legacy=legacy)


def unmerged_chunks(manifest: Manifest, cells_dir: Path) -> int:
    """The readable chunks no part has merged (what `_compact_if_due` counts)."""
    merged = {entry["file"] for entry in manifest.merged_chunks}
    return sum(1 for _, path in readable_chunks(cells_dir) if path.name not in merged)


# -- compaction and reclamation (retained data: independent QA at R3) --------------------------


def write_part(
    cells_dir: Path, table: pa.Table, generation: int, *, compaction_ms: float | None = None
) -> dict:
    """`part-<generation>.parquet`: zstd, row groups of `PART_ROW_GROUP`, sorted by trial_no then
    block, written beside its name and swapped in. A part the manifest lists is never rewritten
    (one part per generation in Phase 2). Returns its manifest entry."""
    name = f"part-{generation}.parquet"
    listed = read_manifest(cells_dir)
    if listed is not None and any(part["file"] == name for part in listed.parts):
        raise ValueError(f"{name} is listed in the manifest: a part is never rewritten")
    path = cells_dir / name
    tmp = path.with_name(name + ".tmp")
    ordered = table.sort_by(
        [("trial_no", "ascending"), ("block", "ascending"), ("attempt", "ascending")]
    )
    cells_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        ordered, tmp, compression=policy.PART_COMPRESSION, row_group_size=policy.PART_ROW_GROUP
    )
    digest = _sha256(tmp)
    _retry(lambda: tmp.replace(path))  # Windows refuses the swap while a reader holds the file
    trial_no = ordered.column(TRIAL_NO)
    return {
        "file": name,
        "generation": generation,
        "trial_no_min": pc.min(trial_no).as_py(),
        "trial_no_max": pc.max(trial_no).as_py(),
        "rows": len(ordered),
        "sha256": digest,
        "compaction_ms": compaction_ms,
    }


def _unique(cells_dir: Path, parts: list[dict]) -> int:
    """§6.4: the distinct `param_key` among the parts' canonical block-0 trials whose status is
    `ok`; invalid and failed trials never count, so unique <= completed."""
    columns = [*_EVALUATION, "status", "param_key"]
    rows = pa.concat_tables(
        [pq.read_table(cells_dir / part["file"], columns=columns) for part in parts]
    )
    table, _ = _canonical(rows)
    ok = pc.and_(
        pc.equal(table.column("block"), 0),
        pc.equal(table.column("status").cast(pa.string()), "ok"),
    )
    return len(pc.unique(table.filter(ok).column("param_key").drop_null()))


def compact(cells_dir: Path, *, now: float, hooks: Callable[[str], None] | None = None) -> Manifest:
    """Merge every readable chunk not yet merged into `part-<generation + 1>.parquet`, then write
    the manifest: the new part, the chunks listed merged at `now` (never deleted here),
    the generation, the watermark and `unique`. Under the experiment's write lock. A crash before
    the manifest leaves an unlisted part the reader never reads and a re-run replaces; a second
    run with nothing new returns the manifest unchanged. Refuses a layout-1 folder: a legacy
    experiment is never compacted. `hooks` sees `part_written` and `manifest_written`."""
    with LOCKS.write(_experiment_id(cells_dir)):
        started = time.perf_counter()
        chunks = readable_chunks(cells_dir)
        manifest = _manifest_of(cells_dir, chunks)
        if manifest.layout != 2:
            raise ValueError(
                f"{cells_dir.name} is layout 1: a legacy experiment is never compacted"
            )
        watermark = _watermark(manifest, chunks)
        merged = {entry["file"] for entry in manifest.merged_chunks}
        todo = [(i, path) for i, path in chunks if i <= watermark and path.name not in merged]
        if not todo:
            return manifest
        tables = []
        for _, path in todo:
            table = pq.read_table(path)
            if TRIAL_NO not in table.column_names:
                raise ValueError(f"{path.name} is a layout-1 chunk: never compacted")
            tables.append(table)
        rows = pa.concat_tables(tables)
        generation = manifest.generation + 1
        entry = write_part(cells_dir, rows, generation)
        if hooks is not None:
            hooks("part_written")
        parts = [*manifest.parts, entry]
        unique = _unique(cells_dir, parts)
        entry["compaction_ms"] = round((time.perf_counter() - started) * 1000, 3)
        compacted = Manifest(
            layout=2,
            generation=generation,
            parts=parts,
            merged_chunks=[
                *manifest.merged_chunks,
                *(
                    {"file": path.name, "generation": generation, "merged_at": now}
                    for _, path in todo
                ),
            ],
            generations=[
                *manifest.generations,
                {
                    "generation": generation,
                    "at": now,
                    "rows": len(rows),
                    "compaction_ms": entry["compaction_ms"],
                    "reclaim_ms": None,
                },
            ],
            chunk_watermark=max(manifest.chunk_watermark, max(i for i, _ in todo)),
            unique=unique,
            unique_generation=generation,
            updated_at=_iso(now),
        )
        write_manifest(cells_dir, compacted)
        if hooks is not None:
            hooks("manifest_written")
        return compacted


def reclaim(
    cells_dir: Path,
    *,
    now: float,
    retain_seconds: float = RETAIN_MERGED_SECONDS,
    registry: SnapshotRegistry = REGISTRY,
) -> list[Path]:
    """Unlink every merged chunk merged at least `retain_seconds` before `now` (inclusive, so
    `retain_seconds=0` with compaction's own `now` reclaims at once) that no open or pinned
    snapshot holds; never a part. A reclaimed entry stays in `merged_chunks` with `reclaimed_at`;
    one Windows refuses to unlink (a handle still open) keeps none and waits for the next pass.
    Records `reclaim_ms` on the latest generation; returns the paths removed. Raises nothing:
    a reclamation never fails the job."""
    removed: list[Path] = []
    try:
        with LOCKS.write(_experiment_id(cells_dir)):
            started = time.perf_counter()
            manifest = read_manifest(cells_dir)
            if manifest is None:
                return removed
            held = {path.name for path in registry.held(_experiment_id(cells_dir))}
            changed = False
            for entry in manifest.merged_chunks:
                name = entry["file"]
                if entry.get("reclaimed_at") is not None or chunk_index_of(Path(name)) is None:
                    continue  # reclaimed already; a part is never reclaimed
                if now - entry["merged_at"] < retain_seconds or name in held:
                    continue
                path = cells_dir / name
                existed = path.exists()
                try:
                    _retry(lambda path=path: path.unlink(missing_ok=True))
                except PermissionError:
                    log.warning("reclaim: %s held open, retried next pass", name)
                    continue
                except OSError as exc:
                    log.warning("reclaim: %s not removed, retried next pass: %s", name, exc)
                    continue
                entry["reclaimed_at"] = now
                changed = True
                if existed:
                    removed.append(path)
            if changed:
                if manifest.generations:
                    elapsed = round((time.perf_counter() - started) * 1000, 3)
                    manifest.generations[-1]["reclaim_ms"] = elapsed
                manifest.updated_at = _iso(now)
                write_manifest(cells_dir, manifest)
    except Exception as exc:  # noqa: BLE001 - reclamation never fails the job; the next pass retries
        log.warning("reclaim of %s stopped, retried next pass: %s", cells_dir.name, exc)
    return removed


def decompact(cells_dir: Path, *, dry_run: bool = False) -> dict:
    """Restore a compacted folder to plain chunks for tools that read chunk files: every part's
    rows, grouped by their `chunk` column, are written back as `NNNNNN.parquet` with their
    layout-2 columns as they are (a name still on disk is kept, never overwritten); then the
    manifest and the parts are removed. The folder stays layout 2. Refuses, before anything is
    written or removed, a listed part that is missing or fails its sha256, and a chunk name on
    disk that is unreadable while its rows are only in a part. The manifest goes before the
    parts, so a crash leaves a folder whose chunks hold every row and a re-run finishes it.
    With `dry_run`, the same report and nothing written. Retained data: QA at R3."""
    with LOCKS.write(_experiment_id(cells_dir)):
        manifest = read_manifest(cells_dir)
        listed = [] if manifest is None else manifest.parts
        for part in listed:
            path = cells_dir / part["file"]
            if not path.is_file():
                raise RuntimeError(f"decompact refused: {part['file']} is listed but missing")
            if _sha256(path) != part["sha256"]:
                raise RuntimeError(f"decompact refused: {part['file']} fails its sha256")
        sources = [cells_dir / part["file"] for part in listed]
        # An unlisted part is a torn compaction's (its chunks were never merged, so they are all
        # still on disk) or a torn decompact's: read the same way, it only restores missing names.
        sources += sorted(p for p in cells_dir.glob("part-*.parquet") if p not in sources)
        writes: list[tuple[Path, pa.Table]] = []
        if sources:
            rows = pa.concat_tables([pq.read_table(path) for path in sources])
            indices = rows.column("chunk").to_pylist()
            if None in indices:
                raise RuntimeError("decompact refused: a part row has no chunk index")
            for index in sorted(set(indices)):
                path = cells_dir / f"{index:06d}.parquet"
                if path.exists():
                    try:
                        pq.read_metadata(path)
                    except Exception as exc:  # refused: removing the parts would lose its rows
                        raise RuntimeError(
                            f"decompact refused: {path.name} is unreadable and its rows are "
                            "only in the parts"
                        ) from exc
                    continue
                group = rows.filter(pc.equal(rows.column("chunk"), index))
                writes.append((path, group.sort_by([("trial_no", "ascending")])))
        report = {"chunks_written": len(writes), "parts_removed": len(sources)}
        if dry_run:
            return report
        for path, table in writes:
            tmp = path.with_name(path.name + ".tmp")
            pq.write_table(table, tmp)
            _retry(lambda tmp=tmp, path=path: tmp.replace(path))
            if pq.read_metadata(path).num_rows != len(table):
                raise RuntimeError(f"decompact: {path.name} did not read back whole")
        if manifest is not None:
            for entry in manifest.merged_chunks:
                if not (cells_dir / entry["file"]).exists():
                    log.warning(
                        "decompact: %s was merged but no part row names its index; its rows "
                        "carry another chunk's (a copy)",
                        entry["file"],
                    )
            _retry((cells_dir / MANIFEST).unlink)
        for path in sources:
            _retry(path.unlink)
        return report


__all__ = [
    "LOCKS",
    "MANIFEST",
    "REGISTRY",
    "Counters",
    "ExperimentLocks",
    "LegacyContext",
    "Manifest",
    "Snapshot",
    "SnapshotExpired",
    "SnapshotRegistry",
    "TrialTable",
    "chunk_index_of",
    "compact",
    "decompact",
    "file_set",
    "latest_snapshot",
    "next_chunk_index",
    "read_latest",
    "read_manifest",
    "read_trials",
    "readable_chunks",
    "reclaim",
    "unmerged_chunks",
    "write_manifest",
    "write_part",
]
