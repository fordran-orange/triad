"""Optimization Lab v2, Phase 3, Task 3: Lab tasks, a single-thread executor beside the
experiment job (spec §9.4, decision 6, Review Focus 2 and 3).

One task runs at a time on one daemon thread. A task coalesces on (source identity, method,
metric, scope, seed), holds the snapshot it pinned at request time and is cached per (key,
snapshot); per key at most one runs and one waits, a newer snapshot replacing the waiting one.
Every test drives the task bodies with events, never with sleeps: a gate holds a stage until the
test opens it, `recorded[k]` says stage k is in the task's status, and `LabTasks.wait` blocks
until a task has finished. `WAIT_S` only bounds a hung test."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from products.aegis import api, pool, server
from products.aegis import experiments as exp
from products.aegis.jobs import JobRunner
from products.aegis.lab import sources
from products.aegis.lab import store as lab_store
from products.aegis.lab.cache import LabCache
from products.aegis.lab.store import Snapshot
from products.aegis.lab.tasks import Cancelled, Checkpoint, LabTasks, snapshot_label
from test_aegis_experiments import world  # noqa: F401 - the shared experiments fixture
from test_aegis_lab_harness import scratch_lifespan  # noqa: F401 - the real lifespan, scratch root
from test_lab_store import EXPERIMENT, NOW, hand_document, layout2_dir, rows_of, write_trials

pytestmark = pytest.mark.aegis

WAIT_S = 30.0  # bounds a hung test; no outcome depends on it
SOURCE = ("exp", "coalescing", "2026-10-29T00:00:00+00:00")
KEY = (SOURCE, "importance", "net_pnl", "combined", 1)
LAB = "/aegis/api/lab"


def seed(n: int) -> tuple:
    """Another key of the same source: another seed."""
    return (*KEY[:-1], n)


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


def test_lifespan_shuts_the_tasks_down(scratch_lifespan):  # noqa: F811
    api.get_lab_tasks.cache_clear()
    spinning = threading.Event()
    threads = []

    def spin(checkpoint):
        threads.append(threading.current_thread())
        spinning.set()
        while True:
            checkpoint()
            yield from ()

    try:
        with TestClient(server.app):
            tasks = api.get_lab_tasks()
            running = tasks.request(KEY, "importance", 3, spin)
            assert spinning.wait(WAIT_S)
        assert tasks.status(running.id).state == "cancelled"
        assert not threads[0].is_alive()
        assert api.get_lab_tasks() is not tasks  # a later lifespan builds a fresh executor
    finally:
        api.get_lab_tasks().shutdown()
        api.get_lab_tasks.cache_clear()


def test_cancel_route_answers_404_for_an_unknown_task(lab):
    server.app.dependency_overrides[api.get_lab_tasks] = lambda: lab.tasks
    try:
        c = TestClient(server.app, raise_server_exceptions=False)
        unknown = c.post(f"{LAB}/exp:{SOURCE[1]}/tasks/{'0' * 32}/cancel")
        assert unknown.status_code == 404, unknown.text
        assert "unknown task" in unknown.json()["detail"]
        blocker = lab.body("blocker", gates=(1,))
        lab.tasks.request(KEY, "importance", 3, blocker)
        assert blocker.started.wait(WAIT_S)
        waiting = lab.tasks.request(seed(2), "importance", 3, lab.body("waiting"))
        url = f"{LAB}/exp:{SOURCE[1]}/tasks/{waiting.id}/cancel"
        # Another source's route never answers for this source's task.
        assert c.post(f"{LAB}/exp:elsewhere/tasks/{waiting.id}/cancel").status_code == 404
        assert c.post(f"{LAB}/opt:{SOURCE[1]}/tasks/{waiting.id}/cancel").status_code == 404
        assert lab.tasks.status(waiting.id).state == "queued"
        cancelled = c.post(url)
        assert cancelled.status_code == 200 and cancelled.json() == {"cancelled": True}
        assert lab.tasks.status(waiting.id).state == "cancelled"
        assert c.post(url).json() == {"cancelled": False}  # finished already
        assert c.post(f"{LAB}/nonsense/tasks/{waiting.id}/cancel").status_code == 422
    finally:
        server.app.dependency_overrides.pop(api.get_lab_tasks, None)


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
