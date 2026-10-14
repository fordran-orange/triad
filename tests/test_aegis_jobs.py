"""JobRunner (Mission 4 spec §6.1): one worker thread, one lock, kinds dispatched by name."""

import threading
import time

import pytest
from products.aegis.jobs import JobBusy, JobRunner
from products.aegis.runs import JsonRunRepository

pytestmark = pytest.mark.aegis


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class Counting:
    """A trivial kind: three units, each returns its index."""

    name = "optimization"
    side = "long"
    bars_per_unit = 10
    total_units = 3

    def __init__(self, hold=None, hold_at=1):
        self.seen = []
        self.hold = hold
        self.hold_at = hold_at

    def run_unit(self, index):
        if self.hold is not None and index == self.hold_at:
            self.hold.wait(10)
        return index

    def commit(self, index, result):
        self.seen.append(result)

    def snapshot(self):
        return {"seen": list(self.seen)}

    def finalize(self, status):
        return {"final": status}


def test_runner_dispatches_by_kind_name_and_learns_cost(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = JobRunner(repository)
    job_id = runner.start(Counting())
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    status = runner.status(job_id)
    assert status["seen"] == [0, 1, 2] and status["final"] == "done"
    assert status["kind"] == "optimization" and status["side"] == "long"
    assert status["progress"] == {"done": 3, "total": 3} and status["bars"] == 10
    assert status["ms_per_bar"] > 0 and runner.ms_per_bar == status["ms_per_bar"]
    assert [j["job_id"] for j in runner.list_jobs("optimization")] == [job_id]
    assert repository.get_optimization(job_id)["final"] == "done"


def test_runner_refuses_a_second_kind_while_one_runs_and_cancels_between_units(tmp_path):
    gate = threading.Event()
    runner = JobRunner(JsonRunRepository(tmp_path))
    first = runner.start(Counting(hold=gate))
    assert wait_for(lambda: runner.status(first)["progress"]["done"] == 1)
    try:
        runner.start(Counting())
    except JobBusy:
        pass
    else:
        raise AssertionError("a second job was accepted while the first ran")
    assert runner.cancel(first) is True
    gate.set()
    assert wait_for(lambda: runner.status(first)["status"] == "cancelled")
    # The cancel lands either before unit 1 starts or while it runs; never after unit 2.
    assert runner.status(first)["seen"] in ([0], [0, 1])
    assert runner.status(first)["final"] == "cancelled"
    second = runner.start(Counting())  # free again
    assert wait_for(lambda: runner.status(second)["status"] == "done")


def test_a_running_job_is_persisted_as_running_before_its_first_unit_commits(tmp_path):
    """An experiment's first chunk can take seconds; a pause during it must find the document
    running (Mission 6 Task 9 finding: it read queued until the first commit)."""
    gate = threading.Event()
    repository = JsonRunRepository(tmp_path)
    runner = JobRunner(repository)
    job_id = runner.start(Counting(hold=gate, hold_at=0))
    try:
        assert wait_for(
            lambda: repository.get_optimization(job_id)["status"] == "running", timeout=3
        ), repository.get_optimization(job_id)["status"]
        persisted = repository.get_optimization(job_id)
        assert persisted["progress"] == {"done": 0, "total": 3} and persisted["job_id"] == job_id
    finally:
        gate.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")


def test_status_and_known_respect_the_kind(tmp_path):
    runner = JobRunner(JsonRunRepository(tmp_path))
    job_id = runner.start(Counting())
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    assert runner.status(job_id, kind="optimization")["status"] == "done"
    assert runner.known(job_id, kind="optimization") and not runner.known(
        job_id, kind="walkforward"
    )
    import pytest

    with pytest.raises(KeyError):
        runner.status(job_id, kind="walkforward")


def test_cancel_after_the_last_unit_still_completes(tmp_path):
    runner = JobRunner(JsonRunRepository(tmp_path))
    kind = Counting()

    def after_unit(done):
        if done == kind.total_units:
            runner.cancel(job_id)  # lands after the last commit, before the terminal publish

    runner._after_unit = after_unit
    job_id = runner.start(kind)
    assert wait_for(lambda: runner.status(job_id)["status"] in ("done", "cancelled"))
    status = runner.status(job_id)
    assert status["status"] == "done" and status["final"] == "done"


def test_release_is_called_once_the_terminal_status_is_persisted(tmp_path):
    class Releasing(Counting):
        released = False

        def release(self):
            self.released = True

    runner = JobRunner(JsonRunRepository(tmp_path))
    kind = Releasing()
    job_id = runner.start(kind)
    assert wait_for(lambda: runner.status(job_id)["status"] == "done")
    assert kind.released and runner.status(job_id)["seen"] == [0, 1, 2]


class Resumable(Counting):
    """A kind whose finalize decides the persisted terminal status (plan ruling P4)."""

    name = "experiment"
    resumable = True

    def snapshot(self):
        return {"id": "exp-1", "seen": list(self.seen)}

    def finalize(self, status):
        return {"status": "paused" if status == "cancelled" else status}


def test_a_kind_may_override_its_persisted_terminal_status(tmp_path):
    repository = JsonRunRepository(tmp_path)
    hold = threading.Event()
    runner = JobRunner(repository)
    kind = Resumable(hold=hold)
    job_id = runner.start(kind)
    assert wait_for(lambda: runner.status(job_id)["status"] == "running")
    assert runner.cancel(job_id)
    hold.set()
    assert wait_for(lambda: runner.status(job_id)["status"] == "cancelled")
    assert repository.get_experiment("exp-1")["status"] == "paused"
    assert runner.status(job_id)["status"] == "cancelled"  # the runner's own record is unchanged


class Exploding(Counting):
    """A kind whose finalize raises: the job must still be persisted as failed."""

    name = "optimization"

    def finalize(self, status):
        raise RuntimeError("report blew up")


def test_a_failing_finalize_is_persisted_as_failed(tmp_path):
    repository = JsonRunRepository(tmp_path)
    runner = JobRunner(repository)
    job_id = runner.start(Exploding())
    assert wait_for(lambda: runner.status(job_id)["status"] == "failed")
    persisted = repository.get_optimization(job_id)
    assert persisted["status"] == "failed"
    assert "RuntimeError: report blew up" in persisted["error"]
