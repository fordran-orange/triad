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

from products.aegis.lab.policy import TASK_RESULTS
from products.aegis.lab.store import REGISTRY, Snapshot

log = logging.getLogger("aegis")

State = Literal["queued", "running", "done", "cancelled", "failed"]
ACTIVE = ("queued", "running")
FINISHED = ("done", "cancelled", "failed")
SHUTDOWN_JOIN_S = 10.0  # how long `shutdown` waits for the running task to reach a checkpoint
THREAD_NAME = "aegis-lab-tasks"
_STOP = None  # the queue's last item: the thread returns


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
    stage's (with its `stage`, `stages`, `partial` and the `snapshot` the task computed on), the
    executor's own dict: never changed once published, and read-only to the caller.
    `sharing_cpu` is true while an experiment job is running beside a queued or running task."""

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
    cancel: threading.Event = field(default_factory=threading.Event)


def snapshot_json(snapshot: Snapshot | None) -> dict | None:
    """A snapshot as every Lab answer carries it (`query.envelope`)."""
    if snapshot is None:
        return None
    return {"generation": snapshot.generation, "chunk_watermark": snapshot.chunk_watermark}


def snapshot_label(result: Mapping | None, current: Snapshot | None) -> str | None:
    """`snapshot X · current Y` for a result computed on a snapshot the source has moved on from,
    each named `g<generation> c<chunk watermark>`, so a view never shows it as current. None when
    it is the current one, when nothing was computed, or for a source without snapshots (an `opt:`
    source's cells done are in its key instead)."""
    computed = None if result is None else result.get("snapshot")
    shown = snapshot_json(current)
    if computed is None or shown is None or computed == shown:
        return None
    return f"snapshot {_name(computed)} · current {_name(shown)}"


def _name(snapshot: Mapping) -> str:
    return f"g{snapshot['generation']} c{snapshot['chunk_watermark']}"


def _order(snapshot: Snapshot | None) -> tuple[int, int]:
    """Snapshots in the order a source takes them (generation and watermark only grow)."""
    if snapshot is None:
        return (-1, -1)
    return (snapshot.generation, snapshot.chunk_watermark)


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
        self._running: _Task | None = None
        self._done: OrderedDict[str, _Task] = OrderedDict()  # the finished results, LRU
        self._ended: OrderedDict[str, _Task] = OrderedDict()  # cancelled and failed, newest last
        self._queue: queue.Queue[str | None] = queue.Queue()  # task ids, in request order
        self._thread: threading.Thread | None = None
        self._closed = False
        self._finished = 0

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
    ) -> TaskStatus:
        """The task for `key` at `snapshot`: its finished result when one is cached, else the
        running or waiting task of the key it joins, else a new task queued behind the others.
        A newer snapshot than the waiting task's replaces that task's snapshot, body and pin in
        place (its id stays); an older one joins what is there. A task being cancelled is never
        joined. `hold` is the registry handle pinning `snapshot`'s files: the task keeps it until
        it ends, and a request that needs none (joined, cached, replaced, refused) releases it."""
        placed = None
        try:
            if stages < 1:
                raise ValueError(f"a Lab task has at least one stage, not {stages}")
            with self._lock:
                if self._closed:
                    raise RuntimeError("the Lab tasks are shut down")
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
        """The newest finished result of `key` (Ruling P2), or its result at `snapshot` when one
        is given; None when there is none, even while a task for it computes."""
        with self._lock:
            found = [
                task
                for task in self._done.values()
                if task.key == key and (snapshot is None or task.snapshot == snapshot)
            ]
            if not found:
                return None
            newest = max(found, key=lambda task: (_order(task.snapshot), task.order))
            self._done.move_to_end(newest.id)
            return newest.result

    def cancel(self, task_id: str) -> bool:
        """A waiting task is cancelled at once and its pin released; a running one stops at its
        next checkpoint, its finished stages kept. False for a task finished or already
        cancelling; KeyError for an unknown id."""
        spare = None
        with self._lock:
            task = self._task(task_id)
            if task.state == "queued":
                spare = self._drop(task)
                cancelled = True
            elif task.state == "running" and not task.cancel.is_set():
                task.cancel.set()
                cancelled = True
            else:
                cancelled = False
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

    def _place(self, key, label, stages, fn, snapshot, hold) -> tuple[_Task, int | None]:
        """The task that answers a request and the pin it does not need (the caller releases it
        outside the lock)."""
        for task in reversed(self._done.values()):
            if task.key == key and task.snapshot == snapshot:
                self._done.move_to_end(task.id)
                return task, hold
        running = self._running
        if running is not None and (running.key != key or running.cancel.is_set()):
            running = None
        if running is not None and running.snapshot == snapshot:
            return running, hold
        waiting = self._waiting.get(key)
        if waiting is not None:
            if _order(snapshot) <= _order(waiting.snapshot):
                return waiting, hold
            spare = waiting.hold
            waiting.label, waiting.stages, waiting.body = label, stages, fn
            waiting.snapshot, waiting.hold = snapshot, hold
            return waiting, spare
        if running is not None and _order(snapshot) < _order(running.snapshot):
            return running, hold
        task = _Task(uuid.uuid4().hex, key, label, stages, fn, snapshot, hold)
        self._active[task.id] = task
        self._waiting[key] = task
        self._queue.put(task.id)
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._work, args=(self._queue,), name=THREAD_NAME, daemon=True
            )
            self._thread.start()
        return task, None

    def _task(self, task_id: str) -> _Task:
        for tasks in (self._active, self._done, self._ended):
            task = tasks.get(task_id)
            if task is not None:
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
            result=task.result,
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

    def _end(self, task: _Task, state: State, error: str | None) -> None:
        task.state, task.error, task.finished_at = state, error, _now()
        self._active.pop(task.id, None)
        if self._running is task:
            self._running = None
        self._finished += 1
        task.order = self._finished
        kept = self._done if state == "done" else self._ended
        kept[task.id] = task
        while len(kept) > self.max_results:
            kept.popitem(last=False)
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
                task.state, task.started_at = "running", _now()
                self._running = task
                body, hold, task.body, task.hold = task.body, task.hold, None, None
                self._lock.notify_all()
            self._run(task, body, hold)

    def _run(self, task: _Task, body: Body, hold: int | None) -> None:
        """One task, with no lock held while its body computes. Whatever ends it, the body is
        closed (so its own `finally` releases what it opened), its pin is released and its end
        is recorded; a failure is reported in its status, never raised."""
        state, error = "failed", "interrupted"
        stages = None
        try:
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
            state, error = "cancelled", None
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
