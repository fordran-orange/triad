"""JobRunner (Mission 4 spec §6.1): one worker thread, one lock, kinds dispatched by name."""

import threading
import time

from products.aegis.jobs import JobBusy, JobRunner
from products.aegis.runs import JsonRunRepository


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

    def __init__(self, hold=None):
        self.seen = []
        self.hold = hold

    def run_unit(self, index):
        if self.hold is not None and index == 1:
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
