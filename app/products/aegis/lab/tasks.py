"""Lab tasks (Optimization Lab v2 spec §9.4, Phase 3 Task 3): the Lab's heavy analytics, one at
a time on one background thread beside a running experiment job.

A task never starts a process pool, never calls `JobRunner.start` and never blocks a request
thread. A route asks for a task (`request`), reads it (`status`, `result`) and cancels it
(`cancel`), each under this executor's one lock for a few field copies; the task's body runs on
the executor's daemon thread, started at the first request, with no lock held. The body is a
generator: it yields one result per finished stage and calls its `Checkpoint` between resamples,
where it yields the CPU and stops once the task was cancelled. The stages it finished stay
readable, labelled `partial` until the last one.

A task coalesces on its key, `(source identity, method, metric, scope, seed)`: the importance
view ignores the filter, so no filter is in it. Its result is cached per (key, snapshot): the
snapshot the route pinned at request time (`sources.pin_experiment`, whose registry handle the
task holds until it ends and releases in a `finally`), or None for an `opt:` source, whose
identity carries its cells done instead. Per key at most one task runs and one waits: a request
for a newer snapshot replaces the waiting one, never queues behind it, since a running
experiment's snapshot changes with every chunk and a 2 s poll would otherwise queue a 180 s task
per chunk. Finished results stay in memory, at most `TASK_RESULTS` least recently used, and a
restart loses them (decision 6).

**Evidence.** Two snapshots of one chunk watermark are one snapshot here, for the cache, for
coalescing and for the label: compaction merges a watermark's chunks into a part and leaves their
canonical rows as they were, so a generation bump alone neither recomputes nor reads as stale.

**Stopping.** A cancel acts on the key, since on a running experiment a key has a running task and
a newer one waiting and a view can name only one of them. A key's stop stands apart from the
results, outlasting their eviction, until a request that may restart clears it (Ruling P13).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from products.aegis.lab.policy import TASK_RESULTS, TASK_STOPPED_KEYS
from products.aegis.lab.store import REGISTRY, Snapshot, snapshot_json

log = logging.getLogger("aegis")

State = Literal["queued", "running", "done", "cancelled", "failed"]
ACTIVE = ("queued", "running")
FINISHED = ("done", "cancelled", "failed")
SHUTDOWN_JOIN_S = 10.0  # how long `shutdown` waits for the running task to reach a checkpoint
THREAD_NAME = "aegis-lab-tasks"
_STOP = None  # the queue's last item: the thread returns
# A task's status as a view sends it: its key is the executor's, its result the view's to choose.
_STATUS_FIELDS = (
    "id",
    "label",
    "state",
    "stage",
    "stages",
    "progress",
    "error",
    "started_at",
    "finished_at",
    "sharing_cpu",
)


class Cancelled(Exception):
    """Raised at a checkpoint of a cancelled task: its body stops there."""


class Checkpoint:
    """What a task's body calls between resamples: it yields the CPU (`time.sleep(0)`), so the
    job's thread and the request threads run beside a long computation, and raises `Cancelled`
    once the task was cancelled."""

    def __init__(self, cancel: threading.Event) -> None:
        self._cancel = cancel

    def __call__(self) -> None:
        time.sleep(0)
        if self._cancel.is_set():
            raise Cancelled


Body = Callable[[Checkpoint], Iterator[dict]]


@dataclass(frozen=True)
class TaskStatus:
    """One read of a task, copied under the executor's lock. `result` is the latest finished
    stage's (with its `stage`, `stages`, `partial` and the `snapshot` the task computed on), a
    copy the caller may label without touching the cache. `sharing_cpu` is true while an
    experiment job is running beside a queued or running task."""

    id: str
    key: tuple
    label: str
    state: State
    stage: int
    stages: int
    progress: float
    result: dict | None
    error: str | None
    started_at: str | None
    finished_at: str | None
    sharing_cpu: bool


@dataclass(eq=False)
class _Task:
    id: str
    key: tuple
    label: str
    stages: int
    body: Body | None  # until the thread takes it
    snapshot: Snapshot | None
    hold: int | None  # the pinned snapshot's registry handle, until the thread takes it
    state: State = "queued"
    stage: int = 0
    result: dict | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    order: int = 0  # the finish order, newest highest
    requested: int = 0  # the request order, newest highest
    cancel: threading.Event = field(default_factory=threading.Event)


def task_key(source: tuple, method: str, metric: str, scope: str, seed: int) -> tuple:
    """A task's coalescing key (review B5): the source's full identity, `("exp", id,
    created_at)` (`sources.experiment_source`) or `("opt", job_id, cells_done)`
    (`sources.optimization_source`), then the method, metric, scope and seed. No filter:
    importance ignores it (§7.3)."""
    if len(source) != 3 or source[0] not in ("exp", "opt"):
        raise ValueError(f"{source!r} is not a source identity: (exp|opt, id, created/cells)")
    return (tuple(source), method, metric, scope, seed)


def task_of(key: tuple, source: tuple) -> bool:
    """Whether `key` (`task_key`) is a task of `source`. An experiment owns it by its whole
    identity, so an experiment deleted and created again under the same id never owns its
    predecessor's tasks; an optimization by its job id alone, `("opt", job_id)` being enough,
    since the cells it has done move while it runs."""
    mine = key[0] if key and isinstance(key[0], tuple) and len(key[0]) == 3 else None
    if mine is None or len(source) < 2 or mine[0] != source[0]:
        return False
    if mine[0] == "opt":
        return mine[1] == source[1]
    return mine == tuple(source)


def status_json(status: TaskStatus | None) -> dict | None:
    """A task's status in a view's answer: everything but its key and its result."""
    return None if status is None else {name: getattr(status, name) for name in _STATUS_FIELDS}


def snapshot_label(result: Mapping | None, current: Snapshot | None) -> str | None:
    """`snapshot X · current Y` for a result computed on a snapshot the source has moved on from,
    each named `g<generation> c<chunk watermark>`, so a view never shows it as current. None when
    it is the current one (a generation bump alone moves no evidence: module docstring), when
    nothing was computed, or for a source without snapshots (an `opt:` source's cells done are in
    its key instead)."""
    computed = None if result is None else result.get("snapshot")
    shown = snapshot_json(current)
    if computed is None or shown is None:
        return None
    if computed["chunk_watermark"] == shown["chunk_watermark"]:
        return None
    return f"snapshot {_name(computed)} · current {_name(shown)}"


def _name(snapshot: Mapping) -> str:
    return f"g{snapshot['generation']} c{snapshot['chunk_watermark']}"


def _evidence(snapshot: Snapshot | None) -> int:
    """A snapshot's place among a source's evidence, which its watermark alone decides (module
    docstring): equal for one evidence, greater for newer (a watermark only grows)."""
    return -1 if snapshot is None else snapshot.chunk_watermark


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _release(*holds: int | None) -> None:
    for hold in holds:
        if hold is not None:
            REGISTRY.release(hold)


class LabTasks:
    """The worker's Lab tasks: one runs at a time, the others wait `queued` in request order.
    `sharing_cpu` is read once per status of a queued or running task, outside the lock."""

    def __init__(
        self,
        max_results: int = TASK_RESULTS,
        *,
        sharing_cpu: Callable[[], bool] | None = None,
    ) -> None:
        if max_results < 1:
            raise ValueError(f"max_results must be at least 1, not {max_results}")
        self.max_results = max_results
        self._sharing_cpu = sharing_cpu or (lambda: False)
        self._lock = threading.Condition(threading.Lock())
        self._active: dict[str, _Task] = {}  # queued and running, by id
        self._waiting: dict[tuple, _Task] = {}  # the one queued task of each key
        # The keys a poll must not restart, each with the task it answers; oldest first.
        self._stops: OrderedDict[tuple, _Task] = OrderedDict()
        self._running: _Task | None = None
        self._done: OrderedDict[str, _Task] = OrderedDict()  # the finished results, LRU
        # Every other end, newest last: cancelled, failed, or done from another task's result.
        self._ended: OrderedDict[str, _Task] = OrderedDict()
        self._queue: queue.Queue[str | None] = queue.Queue()  # task ids, in request order
        self._thread: threading.Thread | None = None
        self._closed = False
        self._finished = 0
        self._requested = 0

    # -- the routes' side ---------------------------------------------------------------------

    def request(
        self,
        key: tuple,
        label: str,
        stages: int,
        fn: Body,
        *,
        snapshot: Snapshot | None = None,
        hold: int | None = None,
        keep_stopped: bool = False,
    ) -> TaskStatus:
        """The task for `key` at `snapshot`: its finished result when one is cached, else the
        running or waiting task of the key it joins, else a new task queued behind the others.
        A newer snapshot than the waiting task's replaces that task's snapshot, body and pin in
        place (its id stays); an older one joins what is there. A task being cancelled is never
        joined. `hold` is the registry handle pinning `snapshot`'s files: the task keeps it until
        it ends, and a request that needs none (joined, cached, replaced, refused, kept) releases
        it.

        With `keep_stopped` (Ruling P13: a view's poll) a stopped key answers its stopped task
        instead, whatever the snapshot: a poll never restarts what the user cancelled or what
        failed. It is decided here, under the one lock that places a task, so a cancel arriving
        while a poll loads its frame still holds. Without it the request clears the key's stop:
        it is the user asking again."""
        placed = None
        try:
            if stages < 1:
                raise ValueError(f"a Lab task has at least one stage, not {stages}")
            with self._lock:
                if self._closed:
                    raise RuntimeError("the Lab tasks are shut down")
                stopped = self._stops.get(key) if keep_stopped else None
                if stopped is not None:
                    placed = (stopped, hold)
                else:
                    self._stops.pop(key, None)
                    placed = self._place(key, label, stages, fn, snapshot, hold)
                status = self._status_of(placed[0])
        finally:
            if placed is None:  # refused: the pin is not kept (a release is idempotent)
                _release(hold)
        _release(placed[1])
        return self._with_cpu(status)

    def status(self, task_id: str) -> TaskStatus:
        """The task's status; KeyError for an id this executor does not know (any more)."""
        with self._lock:
            status = self._status_of(self._task(task_id))
        return self._with_cpu(status)

    def result(self, key: tuple, snapshot: Snapshot | None = None) -> dict | None:
        """The newest finished result of `key` (Ruling P2), or its result at `snapshot`'s evidence
        when one is given; None when there is none, even while a task for it computes."""
        with self._lock:
            found = [
                task
                for task in self._done.values()
                if task.key == key
                and (snapshot is None or _evidence(task.snapshot) == _evidence(snapshot))
            ]
            if not found:
                return None
            newest = max(found, key=lambda task: (_evidence(task.snapshot), task.order))
            self._done.move_to_end(newest.id)
            return dict(newest.result)

    def computing(self, key: tuple) -> TaskStatus | None:
        """The task a view's line names for `key` (Ruling P14): the one running, never the newer
        one waiting behind it; else the one waiting; else the one its stop answers, else its
        newest, in any state; None when this executor knows none of that key (any more). Reads the
        runner for a live task, so never under an experiment's read lock."""
        with self._lock:
            task = self._running
            if task is None or task.key != key:
                task = self._waiting.get(key) or self._stops.get(key) or self._newest(key)
            if task is None:
                return None
            status = self._status_of(task)
        return self._with_cpu(status)

    def cancel(self, task_id: str) -> bool:
        """Stop the task's key, whichever of its tasks `task_id` names (module docstring): its
        waiting task is dropped at once and its pin released, its running one stops at its next
        checkpoint, its finished stages kept, and the key stays stopped until a request that may
        restart clears it. False when the key has nothing live left to stop; KeyError for an
        unknown id."""
        with self._lock:
            key = self._task(task_id).key
            running = self._running
            if running is not None and running.key != key:
                running = None
            waiting = self._waiting.get(key)
            spare = None if waiting is None else self._drop(waiting)
            stops_running = running is not None and not running.cancel.is_set()
            if stops_running:
                running.cancel.set()
            cancelled = stops_running or waiting is not None
            if cancelled:  # the one that computed answers, not the waiter dropped after it
                self._stop(running if running is not None else waiting)
        _release(spare)
        return cancelled

    def wait(self, task_id: str, timeout: float | None = None) -> TaskStatus:
        """Block until the task has finished and return its status; TimeoutError after `timeout`
        seconds (a caller that must block: a test, a benchmark; never a route)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._lock:
            while True:
                task = self._task(task_id)
                if task.state in FINISHED:
                    return self._status_of(task)
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError(f"Lab task {task_id} still {task.state} after {timeout} s")
                self._lock.wait(remaining)

    def shutdown(self, timeout: float = SHUTDOWN_JOIN_S) -> None:
        """Stop for good: every waiting task is cancelled and its pin released, the running one
        stops at its next checkpoint, and the thread is joined (for at most `timeout` seconds:
        it is a daemon, so a body that never reaches a checkpoint cannot hold the process). A
        later `request` is a RuntimeError; a second shutdown does nothing more."""
        with self._lock:
            self._closed = True
            thread, self._thread = self._thread, None
            spare = [self._drop(task) for task in list(self._waiting.values())]
            if self._running is not None:
                self._running.cancel.set()
        _release(*spare)
        if thread is not None:
            self._queue.put(_STOP)
            thread.join(timeout)
            if thread.is_alive():
                log.warning(
                    "a Lab task did not reach a checkpoint within %s s of shutdown", timeout
                )

    # -- under the lock -----------------------------------------------------------------------

    def _newest(self, key: tuple) -> _Task | None:
        """The last task requested for `key`, in any state."""
        found = [
            task
            for tasks in (self._active, self._done, self._ended, self._stops)
            for task in tasks.values()
            if task.key == key
        ]
        return max(found, key=lambda task: task.requested) if found else None

    def _stop(self, task: _Task) -> None:
        """Stop `task`'s key, answered by `task`, the oldest stop forgotten beyond its bound."""
        self._stops[task.key] = task
        self._stops.move_to_end(task.key)
        while len(self._stops) > TASK_STOPPED_KEYS:
            self._stops.popitem(last=False)

    def _place(self, key, label, stages, fn, snapshot, hold) -> tuple[_Task, int | None]:
        """The task that answers a request and the pin it does not need (the caller releases it
        outside the lock)."""
        done = self._cached(key, snapshot)
        if done is not None:
            return done, hold
        running = self._running
        if running is not None and (running.key != key or running.cancel.is_set()):
            running = None
        if running is not None and _evidence(running.snapshot) == _evidence(snapshot):
            return running, hold
        waiting = self._waiting.get(key)
        if waiting is not None:
            if _evidence(snapshot) <= _evidence(waiting.snapshot):
                return waiting, hold
            spare = waiting.hold
            waiting.label, waiting.stages, waiting.body = label, stages, fn
            waiting.snapshot, waiting.hold = snapshot, hold
            return waiting, spare
        if running is not None and _evidence(snapshot) < _evidence(running.snapshot):
            return running, hold
        self._requested += 1
        task = _Task(
            uuid.uuid4().hex, key, label, stages, fn, snapshot, hold, requested=self._requested
        )
        self._active[task.id] = task
        self._waiting[key] = task
        self._queue.put(task.id)
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._work, args=(self._queue,), name=THREAD_NAME, daemon=True
            )
            self._thread.start()
        return task, None

    def _cached(self, key: tuple, snapshot: Snapshot | None) -> _Task | None:
        """The finished task holding the result of (key, snapshot's evidence), marked as just
        used."""
        for task in reversed(self._done.values()):
            if task.key == key and _evidence(task.snapshot) == _evidence(snapshot):
                self._done.move_to_end(task.id)
                return task
        return None

    def _task(self, task_id: str) -> _Task:
        for tasks in (self._active, self._done, self._ended):
            task = tasks.get(task_id)
            if task is not None:
                return task
        for task in self._stops.values():  # readable as long as its stop stands
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def _status_of(self, task: _Task) -> TaskStatus:
        return TaskStatus(
            id=task.id,
            key=task.key,
            label=task.label,
            state=task.state,
            stage=task.stage,
            stages=task.stages,
            progress=task.stage / task.stages,
            result=None if task.result is None else dict(task.result),
            error=task.error,
            started_at=task.started_at,
            finished_at=task.finished_at,
            sharing_cpu=False,
        )

    def _drop(self, task: _Task) -> int | None:
        """Cancel a waiting task; its pin, for the caller to release outside the lock. Its id
        stays in the queue, and the thread skips it."""
        hold, task.body, task.hold = task.hold, None, None
        del self._waiting[task.key]
        self._end(task, "cancelled", None)
        return hold

    def _end(self, task: _Task, state: State, error: str | None, *, cached: bool = True) -> None:
        """Record a task's end. A `done` task's result is cached, unless it answered from one
        already there (`cached=False`): one entry per (key, snapshot); every other end is kept
        apart, so no failure ever evicts a result. A failure or a cancel stops its key when it is
        the key's newest task: a newer one waiting still runs, and a rerun's task is not undone by
        the end of the task it replaced."""
        task.state, task.error, task.finished_at = state, error, _now()
        self._active.pop(task.id, None)
        if self._running is task:
            self._running = None
        self._finished += 1
        task.order = self._finished
        kept = self._done if state == "done" and cached else self._ended
        kept[task.id] = task
        while len(kept) > self.max_results:
            kept.popitem(last=False)
        if state in ("failed", "cancelled") and self._newest(task.key) is task:
            self._stop(task)
        self._lock.notify_all()

    def _with_cpu(self, status: TaskStatus) -> TaskStatus:
        if status.state not in ACTIVE:
            return status
        return replace(status, sharing_cpu=bool(self._sharing_cpu()))

    # -- the executor's thread ----------------------------------------------------------------

    def _work(self, pending: queue.Queue) -> None:
        while True:
            task_id = pending.get()
            if task_id is _STOP:
                return
            with self._lock:
                task = self._active.get(task_id)
                if task is None:  # cancelled while it waited
                    continue
                del self._waiting[task.key]
                body, hold, task.body, task.hold = task.body, task.hold, None, None
                # Queued behind a task being cancelled that still finished on the same snapshot:
                # its result answers this one, never computed twice.
                done = self._cached(task.key, task.snapshot)
                if done is not None:
                    task.stage, task.stages, task.result = done.stage, done.stages, done.result
                    self._end(task, "done", None, cached=False)
                else:
                    task.state, task.started_at = "running", _now()
                    self._running = task
                    self._lock.notify_all()
            if done is not None:
                _release(hold)
                continue
            self._run(task, body, hold)

    def _run(self, task: _Task, body: Body, hold: int | None) -> None:
        """One task, with no lock held while its body computes. Whatever ends it, the body is
        closed (so its own `finally` releases what it opened), its pin is released and its end
        is recorded; a failure is reported in its status, never raised."""
        state, error = "failed", "interrupted"
        stages = None
        try:
            if task.cancel.is_set():  # cancelled or shut down before its body began
                raise Cancelled
            stages = iter(body(Checkpoint(task.cancel)))
            for produced in stages:
                self._record(task, produced)
                if task.cancel.is_set() and task.stage < task.stages:
                    raise Cancelled
            if task.stage < task.stages:
                raise RuntimeError(
                    f"{task.label} finished after stage {task.stage} of {task.stages}"
                )
            state, error = "done", None
        except Cancelled:
            # A cancel that meets a checkpoint after the last stage changes nothing: the result
            # is complete, and it is cached as done.
            state = "done" if task.stage == task.stages else "cancelled"
            error = None
        except Exception as exc:  # noqa: BLE001 - a failing task is reported, never raised: the thread serves the next
            state, error = "failed", f"{type(exc).__name__}: {exc}"
            log.warning("Lab task %s (%s) failed: %s", task.id, task.label, error)
        finally:
            close = getattr(stages, "close", None)
            if close is not None:
                try:
                    close()
                except Exception as exc:  # noqa: BLE001 - the task's end is still recorded
                    log.warning("Lab task %s did not close cleanly: %s", task.id, exc)
            _release(hold)
            with self._lock:
                self._end(task, state, error)

    def _record(self, task: _Task, produced: Mapping) -> None:
        """A finished stage's result, labelled with its stage, `partial` until the last and the
        snapshot the task computed on; a new dict, so a status read before it stays whole."""
        with self._lock:
            if task.stage >= task.stages:
                raise RuntimeError(f"{task.label} yielded more than {task.stages} stages")
            task.stage += 1
            task.result = {
                **produced,
                "stage": task.stage,
                "stages": task.stages,
                "partial": task.stage < task.stages,
                "snapshot": snapshot_json(task.snapshot),
            }
            self._lock.notify_all()
