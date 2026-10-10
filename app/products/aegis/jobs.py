"""Single-worker job runner shared by the optimizer and the walk-forward (Mission 4 spec §6.1).

One worker thread, one lock, one unfinished job at a time across every kind. A job is persisted
through the RunRepository from the moment it starts (queued → running after each unit → done /
cancelled / failed), so a restart can mark what it interrupted as `lost`. Cancel is cooperative
between units. The per-bar unit cost is learned from completed jobs, persisted with them, and
read back at startup; nothing here asserts a speed.

A job kind is a small object: `name` ("optimization" | "walkforward"), `side`, `bars_per_unit`,
`total_units`, `run_unit(index)` (heavy work, no lock), `commit(index, result)` (under the lock),
`snapshot()` (under the lock; kind-specific fields) and `finalize(status)` (under the lock at a
terminal status; extra fields such as `result_hash`). Persistence dispatches by name to the
repository's `save_<name>` / `get_<name>` / `list_<name>s`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from products.aegis.runs import RunRepository

# Starting guess for the per-bar unit cost until a job has been observed on this host; the
# runner replaces it with the measured figure of the last completed job (persisted with it).
MS_PER_BAR = 0.7
UNFINISHED = ("queued", "running")
KINDS = ("optimization", "walkforward")
log = logging.getLogger("aegis")


class JobBusy(RuntimeError):
    """Another job is still queued or running; one job at a time (spec §7)."""


def estimate_seconds(cells: int, bars: int, ms_per_bar: float = MS_PER_BAR) -> float:
    """Seconds for `cells` units of `bars` bars each at the given per-bar cost."""
    return cells * bars * ms_per_bar / 1000.0


@dataclass
class _Job:
    job_id: str
    kind: Any
    created_at: str
    status: str = "queued"
    done: int = 0
    started: float | None = None
    elapsed_ms: int = 0
    ms_per_bar: float | None = None
    error: str | None = None
    extra: dict = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)


class JobRunner:
    """Runs one job at a time on a dedicated thread and answers progress snapshots."""

    def __init__(self, repository: RunRepository, max_workers: int = 1, after_unit=None):
        self._repository = repository
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="aegis-jobs"
        )
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._after_unit = after_unit  # test hook: called with the completed-unit count
        self.ms_per_bar = self._learned_ms_per_bar()

    # -- persistence dispatch -----------------------------------------------------------------
    def _save(self, name: str, envelope: dict) -> None:
        getattr(self._repository, f"save_{name}")(envelope)

    def _get(self, name: str, job_id: str) -> dict:
        return getattr(self._repository, f"get_{name}")(job_id)

    def _list(self, name: str) -> list[dict]:
        lister = getattr(self._repository, f"list_{name}s", None)
        return lister() if lister is not None else []

    def _learned_ms_per_bar(self) -> float:
        """The last completed job's measured cost on this host (any kind), or the starting guess."""
        try:
            summaries = [s for name in KINDS for s in self._list(name)]
            summaries.sort(key=lambda s: s.get("created_at", ""), reverse=True)
            for summary in summaries:
                value = summary.get("ms_per_bar")
                if isinstance(value, int | float) and value > 0:
                    return float(value)
        except Exception as exc:  # noqa: BLE001 - a broken history must not stop the worker from starting
            log.warning("job history unreadable, using the default cost: %s", exc)
        return MS_PER_BAR

    # -- lifecycle ----------------------------------------------------------------------------
    def start(self, kind) -> str:
        job = _Job(job_id=str(uuid.uuid4()), kind=kind, created_at=datetime.now(UTC).isoformat())
        with self._lock:
            running = [j for j in self._jobs.values() if j.status in UNFINISHED]
            if running:
                raise JobBusy(running[0].job_id)
            self._jobs[job.job_id] = job
            envelope = self._snapshot(job)
        try:
            self._save(kind.name, envelope)  # queued: visible and markable as lost
        except Exception:
            with self._lock:
                self._jobs.pop(job.job_id, None)
            raise
        self._executor.submit(self._run, job)
        return job.job_id

    def _run(self, job: _Job) -> None:
        kind = job.kind
        with self._lock:
            job.status = "running"
            job.started = time.perf_counter()
        final, error = "done", None
        try:
            for index in range(kind.total_units):
                if job.cancel.is_set():
                    break
                result = kind.run_unit(index)
                with self._lock:
                    kind.commit(index, result)
                    job.done += 1
                    job.elapsed_ms = int((time.perf_counter() - job.started) * 1000)
                    job.ms_per_bar = self._observed_ms_per_bar(job)
                    envelope = self._snapshot(job)
                self._save(kind.name, envelope)  # progress survives a worker death
                if self._after_unit is not None:
                    self._after_unit(job.done)
            if job.cancel.is_set():
                final = "cancelled"
        except Exception as exc:  # noqa: BLE001 - a failing unit or save must fail the job visibly, never kill the thread
            final, error = "failed", f"{type(exc).__name__}: {exc}"
        # Persist first, then publish the terminal status: a client that sees `done` can reload it.
        try:
            with self._lock:
                job.elapsed_ms = int((time.perf_counter() - job.started) * 1000)
                job.ms_per_bar = self._observed_ms_per_bar(job)
                if error:
                    job.error = error
                job.extra = dict(kind.finalize(final))
                envelope = {**self._snapshot(job), "status": final, "elapsed_ms": job.elapsed_ms}
            self._save(kind.name, envelope)
            if final == "done" and job.ms_per_bar:
                self.ms_per_bar = job.ms_per_bar
        except Exception as exc:  # noqa: BLE001 - same reason: the runner must come back free
            final = "failed"
            with self._lock:
                job.error = job.error or f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                job.status = final

    @staticmethod
    def _observed_ms_per_bar(job: _Job) -> float | None:
        """Caller holds the lock."""
        bars = job.kind.bars_per_unit
        if job.done == 0 or job.started is None or not bars:
            return None
        elapsed_ms = (time.perf_counter() - job.started) * 1000
        return round(elapsed_ms / (job.done * bars), 4)

    def _snapshot(self, job: _Job) -> dict:
        """Caller holds the lock. The common envelope plus the kind's own fields."""
        kind = job.kind
        total = kind.total_units
        if job.status == "running" and job.started is not None:
            elapsed_ms = int((time.perf_counter() - job.started) * 1000)
        else:
            elapsed_ms = job.elapsed_ms
        remaining = total - job.done
        if job.done > 0 and elapsed_ms > 0:
            estimated = remaining * (elapsed_ms / job.done) / 1000.0
        else:
            estimated = estimate_seconds(remaining, kind.bars_per_unit, self.ms_per_bar)
        return {
            "job_id": job.job_id,
            "kind": kind.name,
            "side": kind.side,
            "status": job.status,
            "created_at": job.created_at,
            "progress": {"done": job.done, "total": total},
            "elapsed_ms": elapsed_ms,
            "estimated_seconds": round(estimated, 3),
            "ms_per_bar": job.ms_per_bar,
            "bars": kind.bars_per_unit,
            "error": job.error,
            **kind.snapshot(),
            **job.extra,
        }

    # -- queries ------------------------------------------------------------------------------
    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                return self._snapshot(job)
        for name in KINDS:  # persisted jobs after a restart; KeyError if no kind knows the id
            try:
                return self._get(name, job_id)
            except (KeyError, AttributeError):
                continue
        raise KeyError(job_id)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in UNFINISHED or job.cancel.is_set():
                return False
            job.cancel.set()
            return True

    def known(self, job_id: str) -> bool:
        """Whether any kind, in memory or persisted, knows this id (cancel answers 404 otherwise)."""
        with self._lock:
            if job_id in self._jobs:
                return True
        for name in KINDS:
            try:
                self._get(name, job_id)
                return True
            except (KeyError, ValueError, AttributeError):
                continue
        return False

    def mark_lost_on_startup(self) -> list[str]:
        """Persisted jobs of any kind still queued/running belong to a dead worker: mark them lost."""
        lost = []
        for name in KINDS:
            for summary in self._list(name):
                if summary.get("status") in UNFINISHED:
                    envelope = self._get(name, summary["job_id"])
                    envelope["status"] = "lost"
                    self._save(name, envelope)
                    lost.append(summary["job_id"])
        return lost

    def list_jobs(self, name: str | None = None) -> list[dict]:
        """Persisted jobs of one kind (or all kinds), unfinished ones included, newest first."""
        names = (name,) if name else KINDS
        items = [s for n in names for s in self._list(n)]
        return sorted(items, key=lambda s: s.get("created_at", ""), reverse=True)


__all__ = ["KINDS", "MS_PER_BAR", "UNFINISHED", "JobBusy", "JobRunner", "estimate_seconds"]
