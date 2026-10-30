"""Optimization Lab v2, Phase 3, Task 3: Lab tasks, a single-thread executor beside the
experiment job (spec §9.4, decision 6, Review Focus 2 and 3).

One task runs at a time on one daemon thread. A task coalesces on (source identity, method,
metric, scope, seed), holds the snapshot it pinned at request time and is cached per (key,
snapshot); per key at most one runs and one waits, a newer snapshot replacing the waiting one.
Every test drives the task bodies with events, never with sleeps: a gate holds a stage until the
test opens it, `recorded[k]` says stage k is in the task's status, and `LabTasks.wait` blocks
until a task has finished. `WAIT_S` only bounds a hung test."""

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from products.aegis import api, pool, server
from products.aegis import experiments as exp
from products.aegis.jobs import JobRunner
from products.aegis.lab import sources
from products.aegis.lab import store as lab_store
from products.aegis.lab import tasks as tasks_module
from products.aegis.lab.cache import LabCache
from products.aegis.lab.importance import importance_basis, importance_key
from products.aegis.lab.store import Snapshot
from products.aegis.lab.tasks import (
    Cancelled,
    Checkpoint,
    LabTasks,
    snapshot_label,
    task_key,
    task_of,
)
from test_aegis_experiments import world  # noqa: F401 - the shared experiments fixture
from test_aegis_lab_harness import scratch_lifespan  # noqa: F401 - the real lifespan, scratch root
from test_lab_store import (
    EXPERIMENT,
    NOW,
    PATHS,
    hand_document,
    layout2_dir,
    rows_of,
    write_trials,
)

pytestmark = pytest.mark.aegis

WAIT_S = 30.0  # bounds a hung test; no outcome depends on it
SOURCE = ("exp", "coalescing", "2026-10-29T00:00:00+00:00")
KEY = task_key(SOURCE, "importance", "net_pnl", "combined", 1)
LAB = "/aegis/api/lab"


def seed(n: int) -> tuple:
    """Another key of the same source: another seed."""
    return task_key(SOURCE, "importance", "net_pnl", "combined", n)


def snap(n: int) -> Snapshot:
    """The n-th successive snapshot of a running experiment: every chunk moves the watermark."""
    return Snapshot(generation=0, chunk_watermark=n)


class Body:
    """A task body the test drives: it records its start (and its thread), then for each stage
    waits for that stage's gate when it has one, passes a checkpoint and yields `{"value": k}`.
    `recorded[k]` is set once the executor asks for more after stage k, so stage k is in the
    task's status by then."""

    def __init__(self, name: str, stages: int, gates, log: list[str]) -> None:
        self.name = name
        self.stages = stages
        self.log = log
        self.started = threading.Event()
        self.thread: threading.Thread | None = None
        self.gates = {k: threading.Event() for k in gates}
        self.recorded = {k: threading.Event() for k in range(1, stages + 1)}

    def open(self, stage: int | None = None) -> None:
        for k, gate in self.gates.items():
            if stage is None or k == stage:
                gate.set()

    def __call__(self, checkpoint: Checkpoint):
        self.thread = threading.current_thread()
        self.log.append(f"{self.name} start")
        self.started.set()
        for k in range(1, self.stages + 1):
            gate = self.gates.get(k)
            if gate is not None:
                assert gate.wait(WAIT_S), f"{self.name}: stage {k}'s gate never opened"
            checkpoint()
            yield {"value": k}
            self.recorded[k].set()
        self.log.append(f"{self.name} end")


class Lab:
    """One executor and the bodies a test made; `close` opens every gate, shuts the executor
    down and checks its thread stopped."""

    def __init__(self, **kwargs) -> None:
        self.tasks = LabTasks(**kwargs)
        self.bodies: list[Body] = []
        self.log: list[str] = []

    def body(self, name: str = "", *, stages: int = 3, gates=()) -> Body:
        made = Body(name, stages, gates, self.log)
        self.bodies.append(made)
        return made

    def close(self) -> None:
        for body in self.bodies:
            body.open()
        self.tasks.shutdown()
        for body in self.bodies:
            assert body.thread is None or not body.thread.is_alive()


@pytest.fixture
def lab():
    made = Lab()
    yield made
    made.close()


def fake_pin(n: int) -> int:
    """A registry hold standing for a pinned snapshot's file set (`sources.pin_experiment`)."""
    return lab_store.REGISTRY.open(SOURCE[1], snap(n), [Path(f"{n:06d}.parquet")])


def test_one_task_runs_at_a_time(lab):
    first = lab.body("first", gates=(1,))
    second = lab.body("second")
    a = lab.tasks.request(KEY, "importance", 3, first)
    assert first.started.wait(WAIT_S)
    b = lab.tasks.request(seed(2), "importance", 3, second)
    assert b.id != a.id and b.state == "queued"
    assert (b.stage, b.stages, b.progress, b.result) == (0, 3, 0.0, None)
    assert b.started_at is None and b.finished_at is None and b.error is None
    assert lab.tasks.status(a.id).state == "running" and lab.tasks.status(a.id).started_at
    assert lab.tasks.status(b.id).state == "queued" and not second.started.is_set()
    first.open()
    done_a = lab.tasks.wait(a.id, WAIT_S)
    done_b = lab.tasks.wait(b.id, WAIT_S)
    assert done_a.state == done_b.state == "done"
    assert lab.log == ["first start", "first end", "second start", "second end"]
    assert done_a.finished_at <= done_b.started_at
    assert first.thread is second.thread  # the one executor thread


def test_same_key_joins(lab):
    blocker = lab.body("blocker", gates=(1,))
    lab.tasks.request(seed(9), "importance", 3, blocker)
    assert blocker.started.wait(WAIT_S)
    body, spare = lab.body("body", gates=(1,)), lab.body("spare")
    queued = lab.tasks.request(KEY, "importance", 3, body, snapshot=snap(1))
    joined = lab.tasks.request(KEY, "importance", 3, spare, snapshot=snap(1))
    assert joined.id == queued.id and joined.state == "queued"  # joins a waiting task
    blocker.open()
    assert body.started.wait(WAIT_S)
    running = lab.tasks.request(KEY, "importance", 3, spare, snapshot=snap(1))
    assert running.id == queued.id and running.state == "running"  # and a running one
    body.open()
    assert lab.tasks.wait(queued.id, WAIT_S).state == "done"
    assert not spare.started.is_set()


def test_done_result_is_cached(lab):
    body, spare = lab.body("body"), lab.body("spare")
    first = lab.tasks.request(KEY, "importance", 3, body, snapshot=snap(4))
    done = lab.tasks.wait(first.id, WAIT_S)
    assert done.id == first.id and done.key == KEY and done.label == "importance"
    assert (done.state, done.stage, done.stages, done.progress) == ("done", 3, 3, 1.0)
    assert done.result == {
        "value": 3,
        "stage": 3,
        "stages": 3,
        "partial": False,
        "snapshot": {"generation": 0, "chunk_watermark": 4},
    }
    assert done.error is None and done.started_at <= done.finished_at
    assert done.sharing_cpu is False
    hold = fake_pin(4)
    again = lab.tasks.request(KEY, "importance", 3, spare, snapshot=snap(4), hold=hold)
    assert again == done and not spare.started.is_set()
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()  # a cached answer needs no pinned files
    assert lab.tasks.result(KEY) == lab.tasks.result(KEY, snap(4)) == done.result
    assert lab.tasks.result(KEY, snap(5)) is None and lab.tasks.result(seed(2)) is None


def test_finished_results_are_bounded_least_recently_used():
    lab = Lab(max_results=2)
    try:
        finished = {}
        for n in (1, 2):
            status = lab.tasks.request(seed(n), "importance", 3, lab.body(f"seed {n}"))
            finished[n] = lab.tasks.wait(status.id, WAIT_S)
        assert lab.tasks.result(seed(1)) is not None  # seed 1 used last: seed 2 is the oldest
        third = lab.tasks.request(seed(3), "importance", 3, lab.body("seed 3"))
        assert lab.tasks.wait(third.id, WAIT_S).state == "done"
        assert lab.tasks.result(seed(2)) is None
        assert lab.tasks.result(seed(1)) is not None and lab.tasks.result(seed(3)) is not None
        with pytest.raises(KeyError):
            lab.tasks.status(finished[2].id)
        recomputed = lab.body("seed 2 again")
        again = lab.tasks.request(seed(2), "importance", 3, recomputed)
        assert again.id != finished[2].id
        assert lab.tasks.wait(again.id, WAIT_S).state == "done" and recomputed.started.is_set()
    finally:
        lab.close()


def test_cancel_keeps_finished_stages(lab):
    """Review Focus 3: cancelled in its third stage, a task keeps its first two, labelled
    partial; a request while it stops starts a new task rather than joining it."""
    body = lab.body("cancelled", gates=(3,))
    task = lab.tasks.request(KEY, "importance", 3, body)
    assert body.recorded[2].wait(WAIT_S)
    running = lab.tasks.status(task.id)
    assert running.state == "running" and running.stage == 2
    assert running.result["stage"] == 2 and running.result["partial"] is True
    assert lab.tasks.cancel(task.id) is True
    assert lab.tasks.cancel(task.id) is False  # already cancelling
    restart = lab.body("restart")
    again = lab.tasks.request(KEY, "importance", 3, restart)
    assert again.id != task.id and again.state == "queued"
    body.open(3)  # the third stage starts and stops at its checkpoint
    cancelled = lab.tasks.wait(task.id, WAIT_S)
    assert cancelled.state == "cancelled" and cancelled.error is None
    assert cancelled.result["stage"] == 2 and cancelled.result["partial"] is True
    assert cancelled.result["value"] == 2 and cancelled.stage == 2
    assert cancelled.progress == pytest.approx(2 / 3) and cancelled.finished_at
    done = lab.tasks.wait(again.id, WAIT_S)
    assert done.state == "done" and done.result["stage"] == 3 and done.result["partial"] is False
    assert lab.log == ["cancelled start", "restart start", "restart end"]
    assert lab.tasks.status(task.id).state == "cancelled"  # its stages stay readable
    assert lab.tasks.cancel(again.id) is False  # finished
    with pytest.raises(KeyError):
        lab.tasks.cancel("0" * 32)


def test_cancel_a_waiting_task_at_once(lab):
    blocker = lab.body("blocker", gates=(1,))
    lab.tasks.request(seed(9), "importance", 3, blocker)
    assert blocker.started.wait(WAIT_S)
    waiting = lab.body("waiting")
    task = lab.tasks.request(KEY, "importance", 3, waiting, snapshot=snap(2), hold=fake_pin(2))
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000002.parquet")}
    assert lab.tasks.cancel(task.id) is True
    cancelled = lab.tasks.status(task.id)
    assert cancelled.state == "cancelled" and cancelled.result is None
    assert cancelled.started_at is None and cancelled.finished_at
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()  # its pin released at once
    blocker.open()
    later = lab.tasks.request(seed(3), "importance", 3, lab.body("later"))
    assert lab.tasks.wait(later.id, WAIT_S).state == "done"
    assert not waiting.started.is_set()


def test_cancel_stops_a_body_between_stages(lab):
    """A body that never calls its checkpoint still stops between stages once cancelled, and it
    is closed, so its own `finally` releases what it opened (a frame's registry handle)."""
    resumed, proceed, closed, third = (threading.Event() for _ in range(4))

    def uncooperative(checkpoint):
        try:
            yield {"value": 1}
            resumed.set()
            assert proceed.wait(WAIT_S)
            yield {"value": 2}
            third.set()
            yield {"value": 3}
        finally:
            closed.set()

    task = lab.tasks.request(KEY, "importance", 3, uncooperative)
    assert resumed.wait(WAIT_S)
    assert lab.tasks.cancel(task.id) is True
    proceed.set()
    cancelled = lab.tasks.wait(task.id, WAIT_S)
    assert cancelled.state == "cancelled" and cancelled.result["stage"] == 2
    assert closed.is_set() and not third.is_set()


def test_results_are_copies(lab):
    """A caller that labels a result it was given (Task 6's view) never changes the cache."""
    body = lab.body("body", gates=(2,))
    task = lab.tasks.request(KEY, "importance", 3, body, snapshot=snap(1))
    assert body.recorded[1].wait(WAIT_S)
    partial = lab.tasks.status(task.id).result
    partial["label"] = "changed"
    assert "label" not in lab.tasks.status(task.id).result
    body.open()
    done = lab.tasks.wait(task.id, WAIT_S)
    cached = lab.tasks.request(KEY, "importance", 3, body, snapshot=snap(1))
    assert cached.id == task.id
    for given in (done.result, lab.tasks.result(KEY), cached.result):
        given["label"], given["value"] = "changed", -1
    for read in (lab.tasks.status(task.id).result, lab.tasks.result(KEY, snap(1))):
        assert "label" not in read and read["value"] == 3


class Paused(LabTasks):
    """An executor that pauses each task between taking it from the queue and running its body:
    the window a cancel or a shutdown can land in before the first checkpoint."""

    def __init__(self) -> None:
        super().__init__()
        self.taken, self.proceed = threading.Event(), threading.Event()
        self.task = None

    def _run(self, task, body, hold):
        self.task = task
        self.taken.set()
        assert self.proceed.wait(WAIT_S)
        super()._run(task, body, hold)


@pytest.mark.parametrize("how", ["cancel", "shutdown"])
def test_a_task_cancelled_before_its_body_starts_never_runs_it(how):
    tasks = Paused()
    body = Body("never", 3, (), [])
    try:
        task = tasks.request(KEY, "importance", 3, body, snapshot=snap(6), hold=fake_pin(6))
        assert tasks.taken.wait(WAIT_S) and tasks.status(task.id).state == "running"
        if how == "cancel":
            assert tasks.cancel(task.id) is True
            stopper = None
        else:
            stopper = threading.Thread(target=tasks.shutdown)
            stopper.start()
            assert tasks.task.cancel.wait(WAIT_S)  # the shutdown has asked it to stop
        tasks.proceed.set()
        stopped = tasks.wait(task.id, WAIT_S)
        if stopper is not None:
            stopper.join(WAIT_S)
            assert not stopper.is_alive()
        assert stopped.state == "cancelled" and stopped.stage == 0 and stopped.result is None
        assert not body.started.is_set()
        assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    finally:
        tasks.proceed.set()
        tasks.shutdown()


def test_a_cancel_after_the_last_stage_is_done(lab):
    """A body that passes a checkpoint after its last stage has finished: the cancel that meets
    it there changes nothing, and the complete result is cached as done."""
    resumed, proceed = threading.Event(), threading.Event()

    def thorough(checkpoint):
        for k in (1, 2, 3):
            yield {"value": k}
        resumed.set()
        assert proceed.wait(WAIT_S)
        checkpoint()

    task = lab.tasks.request(KEY, "importance", 3, thorough, snapshot=snap(2))
    assert resumed.wait(WAIT_S)
    assert lab.tasks.cancel(task.id) is True
    proceed.set()
    done = lab.tasks.wait(task.id, WAIT_S)
    assert done.state == "done" and done.error is None
    assert done.result["stage"] == 3 and done.result["partial"] is False
    assert lab.tasks.result(KEY, snap(2)) == done.result


def test_a_task_queued_behind_a_finishing_one_reuses_its_result(lab):
    """A request for the same key and snapshot while the running task is being cancelled
    queues a task; when the running one still finishes (its cancel came after its last stage),
    the queued one answers from that result instead of computing it again, and the cache holds
    one entry for the (key, snapshot)."""
    resumed, proceed = threading.Event(), threading.Event()

    def finishing(checkpoint):
        for k in (1, 2, 3):
            yield {"value": k}
        resumed.set()
        assert proceed.wait(WAIT_S)
        checkpoint()

    first = lab.tasks.request(KEY, "importance", 3, finishing, snapshot=snap(3))
    assert resumed.wait(WAIT_S)
    assert lab.tasks.cancel(first.id) is True
    spare = lab.body("spare")
    queued = lab.tasks.request(KEY, "importance", 3, spare, snapshot=snap(3), hold=fake_pin(3))
    assert queued.id != first.id and queued.state == "queued"
    proceed.set()
    done = lab.tasks.wait(first.id, WAIT_S)
    answered = lab.tasks.wait(queued.id, WAIT_S)
    assert done.state == answered.state == "done"
    assert answered.result == done.result and answered.result["stage"] == 3
    assert answered.stage == answered.stages == 3 and answered.progress == 1.0
    assert not spare.started.is_set()
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    assert sum(1 for t in lab.tasks._done.values() if t.key == KEY) == 1
    assert lab.tasks.request(KEY, "importance", 3, spare, snapshot=snap(3)).id == first.id


def test_snapshot_changes_coalesce(lab):
    """Review Focus 2: ten requests for ten successive snapshots while the first runs. The key
    never has more than one task running and one waiting, each request's pin replaces the
    waiting one's, the first finishes on its own snapshot and the last request's snapshot is the
    one computed next; in between, the view's label says the result is not current (Ruling P2:
    `result` gives the older finished result while the newer one computes)."""
    bodies = {n: lab.body(f"s{n}", gates=(1,)) for n in range(11)}
    first = lab.tasks.request(KEY, "importance", 3, bodies[0], snapshot=snap(0), hold=fake_pin(0))
    assert bodies[0].started.wait(WAIT_S)
    seen = {first.id}
    for n in range(1, 11):
        waiting = lab.tasks.request(
            KEY, "importance", 3, bodies[n], snapshot=snap(n), hold=fake_pin(n)
        )
        seen.add(waiting.id)
        live = [i for i in seen if lab.tasks.status(i).state in ("queued", "running")]
        assert len(live) <= 2, live
        assert lab.tasks.status(first.id).state == "running" and waiting.state == "queued"
        assert lab_store.REGISTRY.held(SOURCE[1]) == {
            Path("000000.parquet"),
            Path(f"{n:06d}.parquet"),
        }
        assert lab.tasks.result(KEY) is None
    assert len(seen) == 2  # one running, one waiting: replaced in place, never queued behind
    bodies[0].open()
    assert lab.tasks.wait(first.id, WAIT_S).state == "done"
    assert bodies[10].started.wait(WAIT_S)
    assert not any(bodies[n].started.is_set() for n in range(1, 10))  # dropped, never run
    computing = lab.tasks.status(waiting.id)
    assert computing.state == "running" and computing.result is None
    older = lab.tasks.result(KEY)
    assert older["snapshot"] == {"generation": 0, "chunk_watermark": 0}  # the first's own
    assert lab.tasks.result(KEY, snap(0)) == older
    assert lab.tasks.result(KEY, snap(10)) is None  # still computing
    assert snapshot_label(older, snap(10)) == "snapshot g0 c0 · current g0 c10"
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000010.parquet")}
    bodies[10].open()
    newest = lab.tasks.wait(waiting.id, WAIT_S)
    assert newest.state == "done"
    assert newest.result["snapshot"] == {"generation": 0, "chunk_watermark": 10}
    assert lab.tasks.result(KEY) == newest.result
    assert snapshot_label(newest.result, snap(10)) is None  # current: no label
    assert snapshot_label(None, snap(10)) is None and snapshot_label(newest.result, None) is None
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    assert lab.log == ["s0 start", "s0 end", "s10 start", "s10 end"]


def test_failure_is_reported_not_raised(lab):
    def failing(checkpoint):
        yield {"value": 1}
        raise ValueError("no finite net_pnl")

    failed = lab.tasks.wait(lab.tasks.request(KEY, "importance", 3, failing).id, WAIT_S)
    assert failed.state == "failed" and "no finite net_pnl" in failed.error
    assert failed.result["stage"] == 1 and failed.result["partial"] is True
    assert lab.tasks.result(KEY) is None
    # A body that stops short of its stages, or runs past them, fails the same way.
    short = lab.tasks.request(seed(2), "importance", 3, lambda checkpoint: iter([{}]))
    assert "finished after stage 1 of 3" in lab.tasks.wait(short.id, WAIT_S).error
    long = lab.tasks.request(seed(3), "importance", 2, lambda checkpoint: iter([{}] * 3))
    assert "more than 2 stages" in lab.tasks.wait(long.id, WAIT_S).error
    with pytest.raises(ValueError, match="at least one stage"):  # refused, its pin released
        lab.tasks.request(seed(5), "importance", 0, lab.body("none"), hold=fake_pin(5))
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    after = lab.body("after")  # the thread survives every failure
    assert lab.tasks.wait(lab.tasks.request(seed(4), "x", 3, after).id, WAIT_S).state == "done"


def test_tasks_never_start_a_pool(lab, monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("a Lab task started a process pool or a job")

    monkeypatch.setattr(pool.Pool, "__init__", refused)
    monkeypatch.setattr(JobRunner, "start", refused)
    body = lab.body("analytics")
    done = lab.tasks.wait(lab.tasks.request(KEY, "importance", 3, body).id, WAIT_S)
    assert done.state == "done" and done.result["value"] == 3


def test_checkpoint_yields_and_raises_once_cancelled(monkeypatch):
    calls = []
    monkeypatch.setattr("products.aegis.lab.tasks.time.sleep", calls.append)
    cancel = threading.Event()
    checkpoint = Checkpoint(cancel)
    checkpoint()
    cancel.set()
    with pytest.raises(Cancelled):
        checkpoint()
    assert calls == [0, 0]


def test_sharing_cpu_while_an_experiment_job_runs():
    """`sharing_cpu` reads the runner once per status (`running_kind`, one hold of its lock):
    true while an experiment job runs, false before and after it and on a finished task."""
    entered, release, released = threading.Event(), threading.Event(), threading.Event()

    def run_unit(index):
        entered.set()
        assert release.wait(WAIT_S)

    kind = SimpleNamespace(
        name="experiment",
        side="long",
        total_units=1,
        bars_per_unit=1,
        run_unit=run_unit,
        commit=lambda index, result: None,
        snapshot=dict,
        finalize=lambda final: {},
        release=released.set,
    )
    runner = JobRunner(SimpleNamespace(save_experiment=lambda envelope: None))
    lab = Lab(sharing_cpu=lambda: api._sharing_cpu(runner))
    try:
        body = lab.body("body", gates=(1,))
        task = lab.tasks.request(KEY, "importance", 3, body)
        assert body.started.wait(WAIT_S)
        assert runner.running_kind() is None and lab.tasks.status(task.id).sharing_cpu is False
        runner.start(kind)
        assert entered.wait(WAIT_S)
        assert runner.running_kind() == "experiment"
        assert lab.tasks.status(task.id).sharing_cpu is True
        release.set()
        assert released.wait(WAIT_S)
        assert runner.running_kind() is None and lab.tasks.status(task.id).sharing_cpu is False
        body.open()
        assert lab.tasks.wait(task.id, WAIT_S).sharing_cpu is False
    finally:
        release.set()
        lab.close()
        runner._executor.shutdown(wait=True)


def test_shutdown_cancels_and_joins(lab):
    spinning = threading.Event()
    threads = []

    def spin(checkpoint):
        """Computes until it is cancelled, passing a checkpoint at every step."""
        threads.append(threading.current_thread())
        spinning.set()
        while True:
            checkpoint()
            yield from ()

    running = lab.tasks.request(KEY, "importance", 3, spin)
    assert spinning.wait(WAIT_S)
    waiting = lab.body("waiting")
    queued = lab.tasks.request(
        seed(2), "importance", 3, waiting, snapshot=snap(3), hold=fake_pin(3)
    )
    lab.tasks.shutdown()
    assert not threads[0].is_alive()
    assert lab.tasks.status(running.id).state == "cancelled"
    assert lab.tasks.status(queued.id).state == "cancelled" and not waiting.started.is_set()
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    hold = fake_pin(4)
    with pytest.raises(RuntimeError, match="shut down"):
        lab.tasks.request(seed(3), "importance", 3, lab.body("late"), hold=hold)
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()  # a refused request's pin is released
    lab.tasks.shutdown()  # twice is harmless


def _drop_cached_executor() -> None:
    """Shut down the worker's cached executor, if one was built, before forgetting it."""
    if api.get_lab_tasks.cache_info().currsize:
        api.get_lab_tasks().shutdown()
    api.get_lab_tasks.cache_clear()


def test_lifespan_shuts_the_tasks_down(scratch_lifespan, monkeypatch):  # noqa: F811
    """On exit the lifespan stops the executor this worker built, off the event loop (its join
    may wait for a checkpoint), and forgets it; a worker that built none builds none to stop."""
    _drop_cached_executor()
    spinning = threading.Event()
    threads = []
    shut = []
    built = []

    def counted(**kwargs):
        built.append(kwargs)
        return LabTasks(**kwargs)

    monkeypatch.setattr(api, "LabTasks", counted)

    def spin(checkpoint):
        threads.append(threading.current_thread())
        spinning.set()
        while True:
            checkpoint()
            yield from ()

    try:
        with TestClient(server.app):
            pass
        assert built == [] and api.get_lab_tasks.cache_info().currsize == 0  # none to stop
        with TestClient(server.app):
            tasks = api.get_lab_tasks()
            assert len(built) == 1
            stop = tasks.shutdown

            def recorded_shutdown(*args, **kwargs):
                try:
                    asyncio.get_running_loop()
                    shut.append("on the event loop")
                except RuntimeError:
                    shut.append("off the loop")
                stop(*args, **kwargs)

            monkeypatch.setattr(tasks, "shutdown", recorded_shutdown)
            running = tasks.request(KEY, "importance", 3, spin)
            assert spinning.wait(WAIT_S)
        assert shut == ["off the loop"]
        assert tasks.status(running.id).state == "cancelled"
        assert not threads[0].is_alive()
        assert api.get_lab_tasks.cache_info().currsize == 0  # a later lifespan builds afresh
    finally:
        _drop_cached_executor()


def test_task_keys_name_their_source():
    """One key builder (review B5): the full source identity, then method, metric, scope and
    seed. An experiment owns a key by its whole identity, so a recreated id is another source;
    an optimization by its job id, whatever cells it has done since."""
    key = task_key(SOURCE, "importance", "net_pnl", "combined", 1)
    assert key == (SOURCE, "importance", "net_pnl", "combined", 1)
    assert task_of(key, SOURCE)
    assert not task_of(key, ("exp", SOURCE[1], "2026-10-01T00:00:00+00:00"))  # recreated id
    assert not task_of(key, ("exp", "elsewhere", SOURCE[2]))
    assert not task_of(key, ("opt", SOURCE[1]))
    running = task_key(("opt", "job-1", 7), "importance", "net_pnl", "long", 1)
    assert task_of(running, ("opt", "job-1")) and task_of(running, ("opt", "job-1", 9))
    assert not task_of(running, ("opt", "job-2")) and not task_of(running, ("exp", "job-1", ""))
    for bad in (("exp", "x"), ("run", "x", 1), ()):
        with pytest.raises(ValueError, match="source identity"):
            task_key(bad, "importance", "net_pnl", "combined", 1)


def test_cancel_route_answers_404_for_an_unknown_task(lab, world):  # noqa: F811
    """The route cancels a task of its own source only: 404 for an unknown id, another source,
    another kind, or the task of a predecessor experiment whose id was created again."""
    repository, _library, strategy = world
    hand_document(repository, strategy, experiment_id=EXPERIMENT)
    current = sources.experiment_source(exp.ExperimentStore(repository).get(EXPERIMENT))
    predecessor = ("exp", EXPERIMENT, "2026-10-01T00:00:00+00:00")
    assert current[2] != predecessor[2]
    server.app.dependency_overrides[api.get_lab_tasks] = lambda: lab.tasks
    server.app.dependency_overrides[api.get_repository] = lambda: repository
    try:
        c = TestClient(server.app, raise_server_exceptions=False)
        unknown = c.post(f"{LAB}/exp:{EXPERIMENT}/tasks/{'0' * 32}/cancel")
        assert unknown.status_code == 404, unknown.text
        assert "unknown task" in unknown.json()["detail"]
        blocker = lab.body("blocker", gates=(1,))
        optimization = task_key(("opt", "job-1", 7), "importance", "net_pnl", "long", 1)
        running = lab.tasks.request(optimization, "importance", 3, blocker)
        assert blocker.started.wait(WAIT_S)
        mine = lab.tasks.request(
            task_key(current, "importance", "net_pnl", "combined", 1), "importance", 3, lab.body()
        )
        theirs = lab.tasks.request(
            task_key(predecessor, "importance", "net_pnl", "combined", 1),
            "importance",
            3,
            lab.body(),
        )
        url = f"{LAB}/exp:{EXPERIMENT}/tasks/{mine.id}/cancel"
        assert c.post(f"{LAB}/exp:{EXPERIMENT}/tasks/{theirs.id}/cancel").status_code == 404
        assert c.post(f"{LAB}/exp:elsewhere/tasks/{mine.id}/cancel").status_code == 404
        assert c.post(f"{LAB}/opt:{EXPERIMENT}/tasks/{mine.id}/cancel").status_code == 404
        assert c.post(f"{LAB}/opt:job-2/tasks/{running.id}/cancel").status_code == 404
        assert lab.tasks.status(mine.id).state == lab.tasks.status(theirs.id).state == "queued"
        cancelled = c.post(url)
        assert cancelled.status_code == 200 and cancelled.json() == {"cancelled": True}
        assert lab.tasks.status(mine.id).state == "cancelled"
        assert lab.tasks.status(theirs.id).state == "queued"
        assert c.post(url).json() == {"cancelled": False}  # finished already
        stopping = c.post(f"{LAB}/opt:job-1/tasks/{running.id}/cancel")  # whatever cells done
        assert stopping.status_code == 200 and stopping.json() == {"cancelled": True}
        assert c.post(f"{LAB}/nonsense/tasks/{mine.id}/cancel").status_code == 422
    finally:
        server.app.dependency_overrides.pop(api.get_lab_tasks, None)
        server.app.dependency_overrides.pop(api.get_repository, None)


def test_task_status_route_reads_a_task_of_its_own_source_only(lab, world):  # noqa: F811
    """Ruling P21's read-only route answers like the cancel route: a task of its own source (an
    experiment by its whole identity, an optimization by its job id whatever cells it has done),
    404 for an unknown id, another source, another kind, or a predecessor experiment's task. A
    read changes nothing: a queued task stays queued and no task is requested."""
    repository, _library, strategy = world
    hand_document(repository, strategy, experiment_id=EXPERIMENT)
    current = sources.experiment_source(exp.ExperimentStore(repository).get(EXPERIMENT))
    predecessor = ("exp", EXPERIMENT, "2026-10-01T00:00:00+00:00")
    server.app.dependency_overrides[api.get_lab_tasks] = lambda: lab.tasks
    server.app.dependency_overrides[api.get_repository] = lambda: repository
    try:
        c = TestClient(server.app, raise_server_exceptions=False)
        blocker = lab.body("blocker", gates=(1,))
        optimization = task_key(("opt", "job-1", 7), "importance", "net_pnl", "long", 1)
        running = lab.tasks.request(optimization, "importance", 3, blocker)
        assert blocker.started.wait(WAIT_S)
        mine = lab.tasks.request(
            task_key(current, "importance", "net_pnl", "combined", 1), "importance", 3, lab.body()
        )
        theirs = lab.tasks.request(
            task_key(predecessor, "importance", "net_pnl", "combined", 1),
            "importance",
            3,
            lab.body(),
        )
        unknown = c.get(f"{LAB}/exp:{EXPERIMENT}/tasks/{'0' * 32}")
        assert unknown.status_code == 404 and "unknown task" in unknown.json()["detail"]
        assert c.get(f"{LAB}/exp:{EXPERIMENT}/tasks/{theirs.id}").status_code == 404
        assert c.get(f"{LAB}/exp:elsewhere/tasks/{mine.id}").status_code == 404
        assert c.get(f"{LAB}/opt:{EXPERIMENT}/tasks/{mine.id}").status_code == 404
        assert c.get(f"{LAB}/opt:job-2/tasks/{running.id}").status_code == 404
        queued = c.get(f"{LAB}/exp:{EXPERIMENT}/tasks/{mine.id}")
        assert queued.status_code == 200 and queued.json()["state"] == "queued"
        assert queued.json()["id"] == mine.id and queued.json()["stage"] == 0
        live = c.get(f"{LAB}/opt:job-1/tasks/{running.id}")  # whatever cells it has done
        assert live.status_code == 200 and live.json()["state"] == "running"
        assert lab.tasks.status(mine.id).state == lab.tasks.status(theirs.id).state == "queued"
        assert c.get(f"{LAB}/nonsense/tasks/{mine.id}").status_code == 422
    finally:
        server.app.dependency_overrides.pop(api.get_lab_tasks, None)
        server.app.dependency_overrides.pop(api.get_repository, None)


# --- the pinned snapshot: `sources.pin_experiment` and `open_experiment(snapshot=)` ------------


def _experiment(world, tmp_path, chunks):  # noqa: F811
    repository, _library, document = world
    store = exp.ExperimentStore(repository)
    cells_dir = layout2_dir(tmp_path, chunks)
    hand_document(repository, document, experiment_id=EXPERIMENT, status="running", layout2=True)
    return store, store.get(EXPERIMENT), cells_dir


def _read(document, store, cache, snapshot=None):
    frame, handle = sources.open_experiment(document, store, cache, sources.BASE, snapshot=snapshot)
    lab_store.REGISTRY.release(handle)
    return frame


def test_open_experiment_reads_a_pinned_snapshot(world, tmp_path):  # noqa: F811
    store, document, cells_dir = _experiment(world, tmp_path, [rows_of(range(6))])
    cache = LabCache()
    pinned, hold = sources.pin_experiment(document, store)
    try:
        assert pinned == Snapshot(0, 0)
        assert lab_store.REGISTRY.held(EXPERIMENT) == {cells_dir / "000000.parquet"}
        write_trials(cells_dir, 1, rows_of(range(6, 12)))  # the job moves on
        old = _read(document, store, cache, pinned)
        new = _read(document, store, cache)
        assert old.snapshot == pinned and old.table.column("trial_no").to_pylist() == list(range(6))
        assert new.snapshot == Snapshot(0, 1) and new.table.num_rows == 12
        keys = [key for key in cache._entries if key[0] == ("exp", EXPERIMENT)]
        assert sorted(key[2:4] for key in keys) == [(0, 0), (0, 1)]  # generation, watermark
        misses = cache.stats()["misses"]
        again = _read(document, store, cache, pinned)
        assert again.table.num_rows == 6 and cache.stats()["misses"] == misses  # from its entry
    finally:
        lab_store.REGISTRY.release(hold)
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()


def test_a_reclaimed_pinned_snapshot_is_expired(world, tmp_path):  # noqa: F811
    """A pinned snapshot keeps its files from reclamation; once released and reclaimed, reading
    it is `snapshot expired`, never the latest read in its place, and leaves no hold behind."""
    store, document, cells_dir = _experiment(
        world, tmp_path, [rows_of(range(6)), rows_of(range(6, 12))]
    )
    cache = LabCache()
    pinned, hold = sources.pin_experiment(document, store)
    lab_store.compact(cells_dir, now=NOW)
    assert lab_store.reclaim(cells_dir, now=NOW + 601) == []  # held by the pin
    frame = _read(document, store, cache, pinned)
    assert frame.snapshot == pinned == Snapshot(0, 1) and frame.table.num_rows == 12
    lab_store.REGISTRY.release(hold)
    chunks = {cells_dir / "000000.parquet", cells_dir / "000001.parquet"}
    assert set(lab_store.reclaim(cells_dir, now=NOW + 601)) == chunks
    with pytest.raises(lab_store.SnapshotExpired):
        _read(document, store, cache, pinned)  # its table is cached: still refused
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()
    latest = _read(document, store, cache)
    assert latest.snapshot == Snapshot(1, 1) and latest.table.num_rows == 12
    for ahead in (Snapshot(1, 5), Snapshot(2, 1)):  # never a snapshot of this folder
        with pytest.raises(lab_store.SnapshotExpired):
            _read(document, store, cache, ahead)
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()


def test_a_task_reads_the_snapshot_it_pinned(world, tmp_path, lab):  # noqa: F811
    """At request time the task pins the source's current snapshot; it waits behind another
    task while the job writes, compacts and reclaims; it then reads its own snapshot, labels its
    result with it and releases the frame's handle and the pin."""
    store, document, cells_dir = _experiment(world, tmp_path, [rows_of(range(6))])
    cache = LabCache()
    blocker = lab.body("blocker", gates=(1,))
    lab.tasks.request(seed(9), "importance", 3, blocker)
    assert blocker.started.wait(WAIT_S)
    pinned, hold = sources.pin_experiment(document, store)
    read = {}

    def importance(checkpoint):
        frame, handle = sources.open_experiment(
            document, store, cache, sources.BASE, snapshot=pinned
        )
        try:
            checkpoint()
            read.update(rows=frame.table.num_rows, snapshot=frame.snapshot)
            yield {"rows": frame.table.num_rows}
        finally:
            lab_store.REGISTRY.release(handle)

    key = (sources.experiment_source(document), "importance", "net_pnl", "combined", 1)
    task = lab.tasks.request(key, "importance", 1, importance, snapshot=pinned, hold=hold)
    assert task.state == "queued"
    write_trials(cells_dir, 1, rows_of(range(6, 12)))
    lab_store.compact(cells_dir, now=NOW)
    assert lab_store.reclaim(cells_dir, now=NOW + 601) == [cells_dir / "000001.parquet"]
    assert (cells_dir / "000000.parquet").is_file()  # the pinned snapshot's chunk
    blocker.open()
    done = lab.tasks.wait(task.id, WAIT_S)
    assert done.state == "done", done.error
    assert read == {"rows": 6, "snapshot": pinned} and done.result["rows"] == 6
    assert done.result["snapshot"] == {"generation": 0, "chunk_watermark": 0}
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()
    _, current = lab_store.latest_snapshot(cells_dir)
    assert current == Snapshot(1, 1)
    assert snapshot_label(lab.tasks.result(key), current) == "snapshot g0 c0 · current g1 c1"


# --- Phase 3 Task 6: the newest task of a key, and the real importance body -------------------


def test_computing_names_the_task_a_view_shows(lab):
    """`computing(key)` (Ruling P14) is the task a view's line names: the one running, never the
    newer one waiting behind it; else the one waiting; else the key's newest, whatever its state;
    None for a key the executor knows no task of."""
    assert lab.tasks.computing(KEY) is None
    first_body = lab.body("first", gates=(2,))
    first = lab.tasks.request(KEY, "importance", 3, first_body, snapshot=snap(1))
    assert first_body.recorded[1].wait(WAIT_S)
    second_body = lab.body("second", gates=(1,))
    second = lab.tasks.request(KEY, "importance", 3, second_body, snapshot=snap(2))
    assert second.id != first.id and second.state == "queued"
    named = lab.tasks.computing(KEY)
    assert (named.id, named.state, named.result["stage"]) == (first.id, "running", 1)
    first_body.open()
    assert lab.tasks.wait(first.id, WAIT_S).state == "done"
    assert second_body.started.wait(WAIT_S)
    assert lab.tasks.computing(KEY).id == second.id
    second_body.open()
    assert lab.tasks.wait(second.id, WAIT_S).state == "done"
    newest = lab.tasks.computing(KEY)
    assert (newest.id, newest.state, newest.result["value"]) == (second.id, "done", 3)
    assert lab.tasks.computing(seed(2)) is None
    blocker = lab.body("blocker", gates=(1,))
    lab.tasks.request(seed(9), "importance", 3, blocker)
    assert blocker.started.wait(WAIT_S)
    waiting = lab.tasks.request(seed(3), "importance", 3, lab.body("waiting"))
    named = lab.tasks.computing(seed(3))
    assert (named.id, named.state) == (waiting.id, "queued")


@pytest.mark.parametrize("called_with", ["running", "waiting"])
def test_cancel_acts_on_the_key(lab, called_with):
    """Review fix 1: on a running experiment a key's running task has a newer one waiting, and a
    view can name only one of them. A cancel with either id stops the key: the waiting one is
    dropped at once with its pin, the running one stops at its next checkpoint with the stages it
    delivered, the waiting one's body never runs and polls stay stopped until the user asks again.
    Another key is untouched."""
    running_body = lab.body("running", gates=(2,))
    running = lab.tasks.request(
        KEY, "importance", 3, running_body, snapshot=snap(1), hold=fake_pin(1)
    )
    assert running_body.recorded[1].wait(WAIT_S)
    waiting_body = lab.body("waiting")
    waiting = lab.tasks.request(
        KEY, "importance", 3, waiting_body, snapshot=snap(2), hold=fake_pin(2)
    )
    other = lab.tasks.request(seed(2), "importance", 3, lab.body("other"))
    assert waiting.id != running.id
    chosen = running if called_with == "running" else waiting
    assert lab.tasks.cancel(chosen.id) is True
    assert lab.tasks.status(waiting.id).state == "cancelled"
    assert lab.tasks.status(other.id).state == "queued"
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000001.parquet")}  # the waiter's released
    assert lab.tasks.cancel(chosen.id) is False  # nothing live is left to stop
    assert lab.tasks.computing(KEY).id == running.id
    unrun = lab.body("unrun")
    kept = lab.tasks.request(
        KEY, "importance", 3, unrun, snapshot=snap(3), hold=fake_pin(3), keep_stopped=True
    )
    assert (kept.id, kept.state) == (running.id, "running")
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000001.parquet")}
    running_body.open()
    stopped = lab.tasks.wait(running.id, WAIT_S)
    assert stopped.state == "cancelled" and stopped.result["stage"] == 1
    assert not waiting_body.started.is_set() and not unrun.started.is_set()
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    named = lab.tasks.computing(KEY)  # the one that computed, not the waiter dropped after it
    assert (named.id, named.state, named.result["stage"]) == (running.id, "cancelled", 1)
    assert (
        lab.tasks.request(KEY, "x", 3, unrun, snapshot=snap(3), keep_stopped=True).id == running.id
    )
    assert lab.tasks.wait(other.id, WAIT_S).state == "done"
    again = lab.tasks.request(KEY, "importance", 3, lab.body("again"), snapshot=snap(3))
    assert again.id not in (running.id, waiting.id)
    assert lab.tasks.wait(again.id, WAIT_S).state == "done"
    assert lab.tasks.request(KEY, "x", 3, unrun, snapshot=snap(3), keep_stopped=True).id == again.id


def test_a_failure_stops_a_key_only_as_its_newest_task(lab):
    """A task that fails with a newer one waiting does not stop the key: the newer one runs, and
    only its own failure stands. A rerun clears the stop, and a task still stopping when the
    rerun's task is placed cannot put it back."""

    def failing(checkpoint):
        raise ValueError("no finite net_pnl")
        yield

    gate, started = threading.Event(), threading.Event()

    def held_failing(checkpoint):
        started.set()
        assert gate.wait(WAIT_S)
        raise ValueError("no finite net_pnl")
        yield

    first = lab.tasks.request(KEY, "importance", 3, held_failing, snapshot=snap(1))
    assert started.wait(WAIT_S)
    newer_body = lab.body("newer")
    newer = lab.tasks.request(KEY, "importance", 3, newer_body, snapshot=snap(2))
    gate.set()
    assert lab.tasks.wait(first.id, WAIT_S).state == "failed"
    assert lab.tasks.wait(newer.id, WAIT_S).state == "done" and newer_body.started.is_set()
    answered = lab.tasks.request(KEY, "x", 3, lab.body(), snapshot=snap(2), keep_stopped=True)
    assert answered.id == newer.id  # the failure did not stop the key
    latest = lab.tasks.request(seed(2), "importance", 3, failing)
    assert lab.tasks.wait(latest.id, WAIT_S).state == "failed"
    assert lab.tasks.request(seed(2), "x", 3, lab.body(), keep_stopped=True).id == latest.id
    # A rerun while the cancelled task still stops: that task's end does not stop the key again.
    stopping_body = lab.body("stopping", gates=(1,))
    stopping = lab.tasks.request(seed(3), "importance", 3, stopping_body)
    assert stopping_body.started.wait(WAIT_S)
    assert lab.tasks.cancel(stopping.id)
    rerun_body = lab.body("rerun", gates=(1,))
    rerun = lab.tasks.request(seed(3), "importance", 3, rerun_body)
    assert rerun.id != stopping.id
    stopping_body.open()
    assert lab.tasks.wait(stopping.id, WAIT_S).state == "cancelled"
    assert rerun_body.started.wait(WAIT_S)
    joined = lab.tasks.request(seed(3), "x", 3, lab.body(), keep_stopped=True)
    assert joined.id == rerun.id and joined.state == "running"
    rerun_body.open()
    assert lab.tasks.wait(rerun.id, WAIT_S).state == "done"


def test_a_stopped_key_outlasts_eviction():
    """Review fix 4: P13 is not a cache entry. At `max_results = 2` a key's failure is evicted by
    three later ones and is still answered, by a poll and by id, its stages readable; only a
    request that may restart clears it."""
    lab = Lab(max_results=2)
    try:

        def failing(checkpoint):
            yield {"value": 1}
            raise ValueError("no finite net_pnl")

        first = lab.tasks.request(KEY, "importance", 3, failing)
        assert lab.tasks.wait(first.id, WAIT_S).state == "failed"
        for n in (2, 3, 4):
            assert (
                lab.tasks.wait(
                    lab.tasks.request(seed(n), "importance", 3, failing).id, WAIT_S
                ).state
                == "failed"
            )
        assert first.id not in lab.tasks._ended
        unrun = lab.body("unrun")
        kept = lab.tasks.request(KEY, "x", 3, unrun, keep_stopped=True)
        assert (kept.id, kept.state, kept.result["value"]) == (first.id, "failed", 1)
        assert "no finite net_pnl" in kept.error
        assert lab.tasks.status(first.id).state == "failed"
        assert lab.tasks.computing(KEY).id == first.id
        again = lab.tasks.request(KEY, "importance", 3, lab.body("again"))
        assert again.id != first.id and lab.tasks.wait(again.id, WAIT_S).state == "done"
        assert lab.tasks.request(KEY, "x", 3, unrun, keep_stopped=True).id == again.id
        assert not unrun.started.is_set()
    finally:
        lab.close()


def test_stopped_keys_are_bounded(monkeypatch):
    """The stopped keys are bounded by a named constant, the oldest forgotten: a poll of that key
    requests again, while a newer one still stands."""
    assert tasks_module.TASK_STOPPED_KEYS == 32
    monkeypatch.setattr(tasks_module, "TASK_STOPPED_KEYS", 2)
    lab = Lab()
    try:

        def failing(checkpoint):
            raise ValueError("no finite net_pnl")
            yield

        ended = {
            n: lab.tasks.wait(lab.tasks.request(seed(n), "x", 3, failing).id, WAIT_S)
            for n in (1, 2, 3)
        }
        assert len(lab.tasks._stops) == 2
        assert lab.tasks.request(seed(3), "x", 3, lab.body(), keep_stopped=True).id == ended[3].id
        restarted = lab.tasks.request(seed(1), "x", 3, lab.body(), keep_stopped=True)
        assert restarted.id != ended[1].id
        assert lab.tasks.wait(restarted.id, WAIT_S).state == "done"
    finally:
        lab.close()


def test_a_generation_bump_is_the_same_evidence(lab):
    """Review fix 11: snapshots of one chunk watermark hold the same rows (compaction merges
    them, `test_compaction_keeps_the_canonical_rows_at_its_watermark`), so for the cache, for
    coalescing and for the label they are one snapshot: a newer generation joins the running or
    waiting task, answers from a finished one and reads no label."""
    body = lab.body("running", gates=(1,))
    running = lab.tasks.request(
        KEY, "importance", 3, body, snapshot=Snapshot(0, 5), hold=fake_pin(5)
    )
    assert body.started.wait(WAIT_S)
    unrun = lab.body("unrun")
    joined = lab.tasks.request(
        KEY, "importance", 3, unrun, snapshot=Snapshot(1, 5), hold=fake_pin(7)
    )
    assert joined.id == running.id
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000005.parquet")}
    waiting_body = lab.body("waiting")
    waiting = lab.tasks.request(
        KEY, "importance", 3, waiting_body, snapshot=Snapshot(1, 6), hold=fake_pin(6)
    )
    assert waiting.id != running.id
    kept = lab.tasks.request(KEY, "importance", 3, unrun, snapshot=Snapshot(2, 6), hold=fake_pin(8))
    assert kept.id == waiting.id  # neither its body nor its pin replaced
    assert lab_store.REGISTRY.held(SOURCE[1]) == {Path("000005.parquet"), Path("000006.parquet")}
    body.open()
    done = lab.tasks.wait(running.id, WAIT_S)
    newest = lab.tasks.wait(waiting.id, WAIT_S)
    assert done.state == newest.state == "done" and waiting_body.started.is_set()
    assert not unrun.started.is_set()
    assert lab.tasks.request(KEY, "x", 3, unrun, snapshot=Snapshot(9, 5)).id == running.id
    assert lab.tasks.result(KEY, Snapshot(9, 5)) == done.result
    assert lab.tasks.result(KEY, Snapshot(9, 6)) == newest.result
    assert lab.tasks.result(KEY, Snapshot(9, 7)) is None
    assert done.result["snapshot"] == {"generation": 0, "chunk_watermark": 5}
    assert snapshot_label(done.result, Snapshot(9, 5)) is None
    assert snapshot_label(done.result, Snapshot(1, 6)) == "snapshot g0 c5 · current g1 c6"
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()


def test_importance_task_never_starts_a_pool(world, tmp_path, lab, monkeypatch):  # noqa: F811
    """Task 3's guard, run with the real importance body (review M6): with `pool.Pool.__init__`
    and `JobRunner.start` refused, one importance task over a real experiment's store opens its
    own frame at the snapshot its route pinned, runs its three stages to `done` and releases
    both its frame's handle and the pin."""

    def refused(*args, **kwargs):
        raise AssertionError("a Lab task started a process pool or a job")

    store, document, _ = _experiment(world, tmp_path, [rows_of(range(6)), rows_of(range(6, 12))])
    monkeypatch.setattr(pool.Pool, "__init__", refused)
    monkeypatch.setattr(JobRunner, "start", refused)
    meta = sources.experiment_meta(document)
    request = api.QueryRequest.model_validate({"filter": {}, "view": "importance"})
    columns = sources.COLUMNS_FOR("importance", request, meta.parameters, meta.objective)
    source = sources.experiment_source(document)
    key = importance_key(source, "net_pnl", "combined", 1)
    assert key == task_key(source, "importance", "net_pnl", "combined", 1)
    pinned, hold = sources.pin_experiment(document, store)
    body = sources.experiment_importance(
        document,
        store,
        LabCache(),
        columns,
        snapshot=pinned,
        metric="net_pnl",
        scope="combined",
        seed=1,
    )
    task = lab.tasks.request(key, "importance", 3, body, snapshot=pinned, hold=hold)
    done = lab.tasks.wait(task.id, WAIT_S)
    assert done.state == "done", done.error
    assert done.result["stage"] == 3 and done.result["partial"] is False
    assert done.result["n"] == 12 and done.result["N"] == sources.scheduled_uniform(document)
    assert done.result["snapshot"] == {"generation": 0, "chunk_watermark": 1}
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()


def test_keep_stopped_answers_a_failed_or_cancelled_task(lab):
    """Ruling P13 at the one lock that places a task: `keep_stopped` answers the key's stopped
    task (it failed, was cancelled, is being cancelled, or finished with a cancel it met after its
    last stage), whatever the snapshot, its body never run and the request's pin released; without
    it the same request restarts. A key whose newest task is live or done requests as ever."""
    blocker = lab.body("blocker", gates=(1,))
    lab.tasks.request(seed(9), "importance", 3, blocker)
    assert blocker.started.wait(WAIT_S)
    first = lab.tasks.request(KEY, "importance", 3, lab.body("first"), snapshot=snap(1))
    assert lab.tasks.cancel(first.id)
    unrun = lab.body("unrun")
    kept = lab.tasks.request(
        KEY, "importance", 3, unrun, snapshot=snap(2), hold=fake_pin(2), keep_stopped=True
    )
    assert (kept.id, kept.state) == (first.id, "cancelled")
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    assert lab.tasks.computing(KEY).id == first.id  # nothing was placed
    restarted = lab.tasks.request(KEY, "importance", 3, lab.body("again"), snapshot=snap(2))
    assert restarted.id != first.id and restarted.state == "queued"
    live = lab.tasks.request(KEY, "x", 3, lab.body(), snapshot=snap(2), keep_stopped=True)
    assert live.id == restarted.id  # a live task joins, as ever
    blocker.open()
    assert lab.tasks.wait(restarted.id, WAIT_S).state == "done"
    newer = lab.tasks.request(KEY, "x", 3, lab.body("newer"), snapshot=snap(3), keep_stopped=True)
    assert newer.id != restarted.id  # done: a new snapshot requests, as ever
    assert lab.tasks.wait(newer.id, WAIT_S).state == "done"

    def failing(checkpoint):
        raise ValueError("no finite net_pnl")
        yield

    failed = lab.tasks.request(seed(3), "importance", 3, failing)
    lab.tasks.wait(failed.id, WAIT_S)
    again = lab.tasks.request(seed(3), "x", 3, lab.body("unrun"), keep_stopped=True)
    assert (again.id, again.state) == (failed.id, "failed")
    # Being cancelled, its state still `running`: a poll in that window restarts nothing.
    stopping_body = lab.body("stopping", gates=(1,))
    stopping = lab.tasks.request(seed(4), "importance", 3, stopping_body)
    assert stopping_body.started.wait(WAIT_S)
    assert lab.tasks.cancel(stopping.id)
    pending = lab.tasks.request(seed(4), "x", 3, lab.body("unrun"), keep_stopped=True)
    assert (pending.id, pending.state) == (stopping.id, "running")
    stopping_body.open()
    assert lab.tasks.wait(stopping.id, WAIT_S).state == "cancelled"
    # Review fix 5: a cancel after the last stage leaves a complete `done` result, but the user
    # asked to stop: the next chunk's poll starts nothing, and only a rerun requests again.
    finished, proceed = threading.Event(), threading.Event()

    def thorough(checkpoint):
        yield {"value": 1}
        finished.set()
        assert proceed.wait(WAIT_S)
        checkpoint()

    late = lab.tasks.request(seed(5), "importance", 1, thorough, snapshot=snap(1))
    assert finished.wait(WAIT_S)
    assert lab.tasks.cancel(late.id)
    proceed.set()
    assert lab.tasks.wait(late.id, WAIT_S).state == "done"
    kept_late = lab.tasks.request(
        seed(5), "x", 1, unrun, snapshot=snap(2), hold=fake_pin(2), keep_stopped=True
    )
    assert (kept_late.id, kept_late.state) == (late.id, "done")
    assert lab_store.REGISTRY.held(SOURCE[1]) == set()
    assert lab.tasks.result(seed(5))["value"] == 1  # its result stays readable
    next_one = lab.tasks.request(seed(5), "x", 1, lab.body(stages=1), snapshot=snap(2))
    assert next_one.id != late.id
    assert lab.tasks.wait(next_one.id, WAIT_S).state == "done"
    assert unrun.started.is_set() is False


def test_importance_holds_no_lock_during_compute(world, tmp_path, lab, monkeypatch):  # noqa: F811
    """The body's frame is opened under the read lock, which is released before it computes; the
    registry keeps the frame's files until the body's `finally`, and the pin until the task
    ends."""
    store, document, _ = _experiment(world, tmp_path, [rows_of(range(12))])
    seen = {}

    def stages(frame, **kwargs):
        seen["readers"] = dict(lab_store.LOCKS._lock(EXPERIMENT).readers)
        seen["held"] = lab_store.REGISTRY.held(EXPERIMENT)
        seen["rows"] = frame.table.num_rows
        for _ in range(3):
            yield {}

    monkeypatch.setattr(sources, "importance_stages", stages)
    assert _importance_of(document, store, lab).state == "done"
    assert seen["readers"] == {} and seen["rows"] == 12
    assert seen["held"]  # its files held by the registry instead
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()


def test_importance_on_a_legacy_experiment(world, lab):  # noqa: F811
    """Review Focus 5: a layout-1 experiment gets importance with `design` inferred from `pass`,
    its rows promoted on read, and the basis line `computed on n uniform trials of N`."""
    repository, _library, strategy = world
    store = exp.ExperimentStore(repository)
    legacy = hand_document(repository, strategy, experiment_id="legacy-importance", status="done")
    store.write_chunk(legacy.id, 0, rows_of(range(12)), PATHS)
    assert store.layout(legacy.id) == 1
    done = _importance_of(legacy, store, lab)
    assert done.state == "done", done.error
    assert importance_basis(done.result) == (
        "computed on 12 uniform trials of 12; adaptive rows excluded; ignores the active filter"
    )
    assert lab_store.REGISTRY.held(legacy.id) == set()


def _importance_of(document, store, lab, *, cache=None):
    """One real importance task on `document`, pinned as its route pins it, run to its end."""
    meta = sources.experiment_meta(document)
    request = api.QueryRequest.model_validate({"filter": {}, "view": "importance"})
    columns = sources.COLUMNS_FOR("importance", request, meta.parameters, meta.objective)
    pinned, hold = sources.pin_experiment(document, store)
    body = sources.experiment_importance(
        document,
        store,
        cache or LabCache(),
        columns,
        snapshot=pinned,
        metric="net_pnl",
        scope="combined",
        seed=1,
    )
    key = importance_key(sources.experiment_source(document), "net_pnl", "combined", 1)
    task = lab.tasks.request(key, "importance", 3, body, snapshot=pinned, hold=hold)
    return lab.tasks.wait(task.id, WAIT_S)


def test_a_sampled_experiments_n_is_its_first_pass(world, tmp_path, lab):  # noqa: F811
    """N is the document's first pass, which a frame cannot tell: a sampled experiment's frame
    schedules its refinement cells too, whose rows are adaptive and excluded from n."""
    first = rows_of(range(6), **{"pass": "sample"})
    refinement = rows_of(range(6, 8), **{"pass": "refine"})
    store, document, _ = _experiment(world, tmp_path, [first, refinement])
    sampled = document.model_copy(
        update={
            "plan": {**document.plan, "mode": "sampled", "first_pass": 6, "refinement": 2},
            "first_pass_cells": list(range(6)),
            "refinement_cells": [6, 7],
            "counts": {**document.counts, "scheduled": 8},
        }
    )
    assert _read(sampled, store, LabCache()).scheduled == 8  # first pass and refinement
    done = _importance_of(sampled, store, lab)
    assert done.state == "done", done.error
    assert (done.result["n"], done.result["attempted"], done.result["N"]) == (6, 6, 6)
    assert importance_basis(done.result) == (
        "computed on 6 uniform trials of 6; adaptive rows excluded; ignores the active filter"
    )


def test_importance_before_the_first_chunk_finishes_on_no_rows(world, tmp_path, lab):  # noqa: F811
    """A poll before the job's first chunk runs the task on no rows: it finishes, saying so,
    rather than failing, since a failed task stays failed until the user asks again (P13)."""
    store, document, _ = _experiment(world, tmp_path, [])
    done = _importance_of(document, store, lab)
    assert done.state == "done", done.error
    assert (done.result["n"], done.result["attempted"]) == (0, 0)
    assert done.result["N"] == sources.scheduled_uniform(document) > 0
    assert done.result["availability"]["reason"] == "no uniform rows of the current space"
    assert importance_basis(done.result).startswith("computed on 0 uniform trials of ")
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()


def test_a_compaction_with_no_new_chunk_recomputes_nothing(world, tmp_path, lab):  # noqa: F811
    """Review fix 11 on a real store: a compaction with no new chunk bumps the generation alone.
    The poll that follows joins the finished task, reads no label, and the stages computed at the
    new generation are the old ones, whose rows they are."""
    store, document, cells_dir = _experiment(
        world, tmp_path, [rows_of(range(6)), rows_of(range(6, 12))]
    )
    cache = LabCache()
    first = _importance_of(document, store, lab, cache=cache)
    assert first.state == "done", first.error
    assert first.result["snapshot"] == {"generation": 0, "chunk_watermark": 1}
    manifest = lab_store.compact(cells_dir, now=NOW)
    assert manifest.generation == 1
    meta = sources.experiment_meta(document)
    request = api.QueryRequest.model_validate({"filter": {}, "view": "importance"})
    columns = sources.COLUMNS_FOR("importance", request, meta.parameters, meta.objective)
    pinned, hold = sources.pin_experiment(document, store)
    assert pinned == Snapshot(1, 1)
    unrun = lab.body("unrun")
    key = importance_key(sources.experiment_source(document), "net_pnl", "combined", 1)
    again = lab.tasks.request(key, "importance", 3, unrun, snapshot=pinned, hold=hold)
    assert again.id == first.id and again.state == "done"
    assert snapshot_label(first.result, pinned) is None
    assert lab_store.REGISTRY.held(EXPERIMENT) == set()
    frame, handle = sources.open_experiment(document, store, cache, columns, snapshot=pinned)
    lab_store.REGISTRY.release(handle)
    assert frame.snapshot == pinned
    *_, last = sources.importance_stages(
        frame,
        metric="net_pnl",
        scope="combined",
        seed=1,
        checkpoint=lambda: None,
        scheduled=sources.scheduled_uniform(document),
    )
    moved = ("snapshot", "elapsed_s")
    assert {k: v for k, v in last.items() if k not in moved} == {
        k: v for k, v in first.result.items() if k not in moved
    }


def test_the_clock_starts_before_the_frame_opens(world, tmp_path, lab, monkeypatch):  # noqa: F811
    """Review fix 6: `elapsed_s` counts from the body's start, the frame's load included, so stage
    3's figure is the whole task's (Task 12 reads it)."""
    store, document, _ = _experiment(world, tmp_path, [rows_of(range(12))])
    opened, started = [], []
    real_open, real_stages = sources.open_experiment, sources.importance_stages

    def opening(*args, **kwargs):
        opened.append(time.perf_counter())
        return real_open(*args, **kwargs)

    def stages(frame, **kwargs):
        started.append(kwargs["started"])
        yield from real_stages(frame, **kwargs)

    monkeypatch.setattr(sources, "open_experiment", opening)
    monkeypatch.setattr(sources, "importance_stages", stages)
    done = _importance_of(document, store, lab)
    assert done.state == "done", done.error
    assert len(opened) == len(started) == 1 and started[0] <= opened[0]
