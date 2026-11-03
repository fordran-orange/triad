"""Optimization Lab v2, Phase 2, Task 9: the DEMO synthetic layout-2 fixture and the benchmark
records. The §9.6a / §9.6b thresholds are constants, asserted here against the spec's tables
written out literally; `evaluate()` reports each as True / False or as a named absence; both
benchmark modes refuse the product store and the product worker; the fixture is a layout-2
experiment the Lab routes read; the benchmark strategy carries the ten ranged paths of the
2.87 × 10¹¹-cell surface; and `lab_benchmark.py` imports nothing heavy at module level, so the
walk can import it on the Core interpreter."""

import copy
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from products.aegis.experiments import ExperimentStore
from products.aegis.lab.store import read_latest
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import StrategySpec
from products.aegis.surface import Parameter, Surface, apply_params, build_grid

pytestmark = pytest.mark.aegis

CHECKOUT = Path(__file__).resolve().parents[1]
BENCH_DIR = CHECKOUT / "tests" / "products" / "aegis"
sys.path.insert(0, str(BENCH_DIR))
import lab_benchmark
import lab_fixture
from lab_benchmark import (
    BENCH_CASES,
    BENCH_SURFACE,
    TRACK_A_BUDGETS_MS,
    TRACK_A_LIMITS,
    TRACK_B_LIMITS,
    TRACK_B_THRESHOLDS,
    evaluate,
    product_root,
    refuse_product_targets,
    retest_due,
)
from test_aegis_api import client  # noqa: F401

# --- the records ----------------------------------------------------------------------------

EXPLORE = {
    "mode": "explore",
    "host": {"cpu": {"name": "test cpu", "logical": 12}, "os": "test os", "ram_gb": 15.8},
    "engine_build": "e" * 64,
    "git_head": "0" * 40,
    "basis": "http (scratch worker)",
    "operations": {
        "open": {"basis": "http", "http_ms": {"p95": 900.0}},
        "open_cold": {"basis": "http", "http_ms": {"p95": 2500.0}},
        "filter_heatmap": {"basis": "http", "http_ms": {"p95": 250.0}},
        "stat_change": {"basis": "http", "http_ms": {"p95": 150.0}},
        "page": {"basis": "http", "http_ms": {"p95": 400.0}},
        "exact_slice": {"basis": "http", "http_ms": {"p95": 120.0}},
        "parallel": {"basis": "http", "http_ms": {"p95": 500.0}},
        "progress_poll": {"basis": "http", "http_ms": {"p95": 20.0}},
    },
    "resources": {"worker_rss_delta_mb": 300.0, "disk_mb": 200.0, "compaction_1m_s": 4.0},
}
# One number per key pushed just past its line (§9.6a).
EXPLORE_PAST = {
    "open": ("operations", 1501.0),
    "open_cold": ("operations", 4001.0),
    "filter_heatmap": ("operations", 401.0),
    "stat_change": ("operations", 301.0),
    "page": ("operations", 601.0),
    "exact_slice": ("operations", 301.0),
    "parallel": ("operations", 801.0),
    "progress_poll": ("operations", 101.0),
    "worker_rss_delta_mb": ("resources", 451.0),
    "disk_mb": ("resources", 351.0),
    "compaction_1m_s": ("resources", 10.5),
}


def _case(bars: int, nominal: int, rate: float, first_chunk: float) -> dict:
    return {
        "bars": bars,
        "bars_nominal": nominal,
        "trials_per_s": rate,
        "first_chunk_s": first_chunk,
        "chunk_write_ms_p95": 30.0,
        "host_growth_mb": 40.0,
        "compaction_s": 0.5,
        "invalid": 0,
        "failed": 0,
        "worker_peak_mb": 158.0,
        "progress_poll_ms_p95": 20.0,
    }


EXECUTE = {
    "mode": "execute",
    "host": {"cpu": {"name": "test cpu", "logical": 12}, "os": "test os", "ram_gb": 15.8},
    "engine_build": "e" * 64,
    "git_head": "0" * 40,
    "cases": {
        "A": _case(2_603, 2_603, 180.0, 12.0),
        "B": _case(9_669, 9_669, 80.0, 15.0),
        "C": _case(46_034, 46_034, 23.0, 25.0),
    },
    "with_queries": {"query_throughput_ratio": 0.8, "query_p95_ratio": 2.1},
}
# (case, measure, value past the line) per §9.6b row; the pool-child line is 160 + 400e-6 × bars.
EXECUTE_PAST = [
    ("A", "trials_per_s", 149.0),
    ("B", "trials_per_s", 64.0),
    ("C", "trials_per_s", 18.9),
    ("A", "first_chunk_s", 20.5),
    ("C", "first_chunk_s", 35.5),
    ("A", "chunk_write_ms_p95", 101.0),
    ("A", "host_growth_mb", 101.0),
    ("A", "compaction_s", 10.5),
    ("A", "invalid", 1),
    ("A", "failed", 1),
    ("A", "worker_peak_mb", 160.0 + 400e-6 * 2_603 + 0.1),
    ("C", "worker_peak_mb", 160.0 + 400e-6 * 46_034 + 0.1),
    ("A", "progress_poll_ms_p95", 101.0),
]


def test_lab_benchmark_record():
    # The constants equal the spec's tables (§9.6a, §9.6b), every number written out here.
    assert TRACK_A_BUDGETS_MS == {
        "open": 1500,
        "open_cold": 4000,
        "filter_heatmap": 400,
        "stat_change": 300,
        "page": 600,
        "exact_slice": 300,
        "parallel": 800,
        "progress_poll": 100,
        "pareto": 800,
        "neighbourhood": 150,
    }
    assert TRACK_A_LIMITS == {
        "worker_rss_delta_mb": 450.0,
        "disk_mb": 350.0,
        "compaction_1m_s": 10.0,
        "browser_heap_mb": 300.0,
    }
    assert TRACK_B_THRESHOLDS == {"A": 150.0, "B": 65.0, "C": 19.0, "A100k": 71.0}
    assert TRACK_B_LIMITS == {
        "first_chunk_s_le_10k_bars": 20.0,
        "first_chunk_s_50k_bars": 35.0,
        "chunk_write_ms_p95": 100.0,
        "host_growth_mb": 100.0,
        "compaction_s": 10.0,
        "invalid": 0,
        "failed": 0,
        "query_throughput_ratio_min": 0.75,
        "query_p95_ratio_max": 2.5,
        "progress_poll_ms_p95": 100.0,
        "worker_peak_mb": (160.0, 400e-6),
        "bars_drift_max": 0.02,
    }
    assert "browser_heap_mb" in TRACK_A_LIMITS and TRACK_A_LIMITS["browser_heap_mb"] == 300.0

    # An explore record that meets every line; each number pushed past its line fails it alone.
    verdict = evaluate(EXPLORE)
    assert set(verdict) == {*TRACK_A_BUDGETS_MS, *TRACK_A_LIMITS}
    assert all(verdict[key] is True for key in EXPLORE_PAST), verdict
    for key, (section, value) in EXPLORE_PAST.items():
        record = copy.deepcopy(EXPLORE)
        if section == "operations":
            record["operations"][key]["http_ms"]["p95"] = value
        else:
            record["resources"][key] = value
        result = evaluate(record)
        assert result[key] is False, key
        assert all(result[k] is True for k in EXPLORE_PAST if k != key), key

    # Nothing in explore measures a browser: the heap row is absent on every explore record.
    assert verdict["browser_heap_mb"] == "absent"
    assert evaluate({"mode": "explore"})["browser_heap_mb"] == "absent"
    heap = copy.deepcopy(EXPLORE)
    heap["resources"]["browser_heap_mb"] = 120.0
    assert evaluate(heap)["browser_heap_mb"] == "absent"
    # A missing measurement is absent, never passed.
    assert all(value == "absent" for value in evaluate({"mode": "explore"}).values())
    # In-process timings are a proxy: no latency row is evaluated from them.
    proxy = copy.deepcopy(EXPLORE)
    proxy["basis"] = "in-process (no HTTP)"
    result = evaluate(proxy)
    assert all(result[key] == "absent" for key in TRACK_A_BUDGETS_MS)
    assert result["disk_mb"] is True and result["compaction_1m_s"] is True

    # An execute record that meets every line.
    verdict = evaluate(EXECUTE)
    for label in ("A", "B", "C"):
        for measure in lab_benchmark.CASE_MEASURES:
            assert verdict[f"{label}.{measure}"] is True, (label, measure)
    assert verdict["query_throughput_ratio"] is True and verdict["query_p95_ratio"] is True
    # The 100,000-trial case runs at the milestone: named, never absent and never passed.
    assert all(
        verdict[f"A100k.{measure}"] == "not run at R3" for measure in lab_benchmark.CASE_MEASURES
    )
    for label, measure, value in EXECUTE_PAST:
        record = copy.deepcopy(EXECUTE)
        record["cases"][label][measure] = value
        result = evaluate(record)
        assert result[f"{label}.{measure}"] is False, (label, measure)
        others = [k for k, v in verdict.items() if v is True and k != f"{label}.{measure}"]
        assert all(result[k] is True for k in others), (label, measure)
    for key, value in (("query_throughput_ratio", 0.7), ("query_p95_ratio", 2.6)):
        record = copy.deepcopy(EXECUTE)
        record["with_queries"][key] = value
        assert evaluate(record)[key] is False, key
    # A bar count 3.7 % off the configuration's is a failure, never an absence.
    drifted = copy.deepcopy(EXECUTE)
    drifted["cases"]["A"]["bars"] = 2_700
    assert drifted["cases"]["A"]["bars_nominal"] == 2_603
    assert evaluate(drifted)["A.bars_drift"] is False
    # The first-chunk line follows the bar count: 20 s at <= 10k bars, 35 s above.
    assert evaluate(EXECUTE)["C.first_chunk_s"] is True  # 25 s at 46,034 bars
    late = copy.deepcopy(EXECUTE)
    late["cases"]["B"]["first_chunk_s"] = 25.0
    assert evaluate(late)["B.first_chunk_s"] is False  # 25 s at 9,669 bars
    # A100k measured is evaluated against its own threshold.
    sustained = copy.deepcopy(EXECUTE)
    sustained["cases"]["A100k"] = _case(2_603, 2_603, 70.0, 12.0)
    assert evaluate(sustained)["A100k.trials_per_s"] is False
    sustained["cases"]["A100k"]["trials_per_s"] = 89.0
    assert evaluate(sustained)["A100k.trials_per_s"] is True
    # Without the query run its two rows are absent.
    quiet = copy.deepcopy(EXECUTE)
    del quiet["with_queries"]
    assert evaluate(quiet)["query_throughput_ratio"] == "absent"
    assert evaluate(quiet)["query_p95_ratio"] == "absent"
    # The measured per-trial cost uses the pool observed (4), never the size expected (10).
    observed = {"bars": 2_603, "trials_per_s": 100.0, "pool_workers": 4, "workers_expected": 10}
    cost = lab_benchmark.per_trial_cost(observed)
    model = 27 + 0.0079 * 2_603
    assert cost["measured_worker_ms_per_trial"] == 40.0  # 4 × 1000 / 100, not 10 × 1000 / 100
    assert cost["model_ms_per_trial"] == round(model, 3)
    assert cost["measured_to_model"] == round(40.0 / model, 3)
    assert cost["workers_mismatch"] == "expected 10 workers; the pool ran 4"
    matched = lab_benchmark.per_trial_cost({**observed, "workers_expected": 4})
    assert "workers_mismatch" not in matched and matched["measured_worker_ms_per_trial"] == 40.0
    unmeasured = lab_benchmark.per_trial_cost({**observed, "trials_per_s": None})
    assert unmeasured["measured_worker_ms_per_trial"] is None
    assert unmeasured["measured_to_model"] is None

    # A record as explore and execute build it carries the host, the mode, the engine build,
    # the commit and its operations or cases (no timing is run here).
    for mode, section in (("explore", "operations"), ("execute", "cases")):
        record = lab_benchmark.new_record(mode)
        assert record["mode"] == mode and section in record
        assert len(record["engine_build"]) == 64 and len(record["git_head"]) == 40
        assert set(record["host"]) == {
            "cpu",
            "ram_gb",
            "free_memory_gb_at_start",
            "os",
            "python",
            "numba",
            "numpy",
            "pyarrow",
            "engine_build",
            "git_head",
            "app_root",
            "workers",
            "power_throttling",
            "curves_kept",
            "measured_at",
            "indicators_per_side",
            "ranged_parameters",
            "bars_max",
            "kinds",
        }
        assert set(record["host"]["power_throttling"]) == {"host", "child"}
        assert Path(record["host"]["app_root"]) == CHECKOUT / "app"
        assert record["host"]["ranged_parameters"] == 10
        assert record["host"]["indicators_per_side"] == 4
        assert record["host"]["bars_max"] == 46_034


# --- refusals --------------------------------------------------------------------------------


def _git_common_dir() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=CHECKOUT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Path(out)


def _refused(call) -> str:
    with pytest.raises(SystemExit) as caught:
        call()
    assert caught.value.code == 2
    text = str(caught.value)
    assert text.startswith("refused"), text
    return text


def _no_network(base):
    raise AssertionError(f"/health/live of {base} was asked before the data-root refusal")


def _past_the_refusal(*args, **kwargs):
    raise AssertionError("a benchmark mode went past its refusal")


# What explore and execute do after their refusal: ask the worker, resolve its processes, take
# the host record, write the fixture, open a connection. Each fails the test if it is reached.
PAST_THE_REFUSAL = ("_require_worker_root", "worker_process", "new_record", "_fixture", "_Http")


def test_explore_refuses_product_root(monkeypatch, capsys, tmp_path):
    assert product_root() == _git_common_dir().parent / "data" / "aegis"
    monkeypatch.setattr(lab_benchmark, "health_live", _no_network)
    text = _refused(lambda: refuse_product_targets(product_root(), None))
    assert text == "refused: --data-root is the product root; pass --data-root <scratch>"
    # main refuses before anything else: no worker is asked and nothing is written.
    logs = sorted((CHECKOUT / "logs").glob("lab-benchmark-*.json"))
    argv = ["explore", "--data-root", str(product_root()), "--base", "http://127.0.0.1:8103/aegis/"]
    assert lab_benchmark.main([*argv, "--pid-file", "logs/none.pid", "--trials", "4000"]) == 2
    assert "refused: --data-root is the product root" in capsys.readouterr().err
    assert sorted((CHECKOUT / "logs").glob("lab-benchmark-*.json")) == logs
    # explore refuses by itself (the walk imports it), before any request, process or file.
    for name in PAST_THE_REFUSAL:
        monkeypatch.setattr(lab_benchmark, name, _past_the_refusal)
    bench = product_root() / "bench"
    held = bench.exists()
    pid_file = tmp_path / "none.pid"
    for base in ("http://127.0.0.1:8103/aegis/", "http://127.0.0.1:8102/aegis/"):
        text = _refused(
            lambda base=base: lab_benchmark.explore(
                product_root(), base=base, pid_file=pid_file, trials=4_000
            )
        )
        assert text == "refused: --data-root is the product root; pass --data-root <scratch>"
    scratch = tmp_path / "scratch"
    text = _refused(
        lambda: lab_benchmark.explore(
            scratch, base="http://127.0.0.1:8102/aegis/", pid_file=pid_file, trials=4_000
        )
    )
    assert text == "refused: the worker on port 8102 is the product worker"
    assert not scratch.exists() and bench.exists() == held


def test_execute_refuses_product_worker(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    answers = {"data_root": str(product_root())}

    def health(base):
        return {"status": "ok", "product": "aegis", "app_root": str(CHECKOUT / "app"), **answers}

    monkeypatch.setattr(lab_benchmark, "health_live", health)
    text = _refused(lambda: refuse_product_targets(scratch, "http://127.0.0.1:8103/aegis/"))
    assert text == "refused: the worker's data_root is the product root"
    answers["data_root"] = str(scratch)
    text = _refused(lambda: refuse_product_targets(scratch, "http://127.0.0.1:8102/aegis/"))
    assert text == "refused: the worker on port 8102 is the product worker"
    text = _refused(lambda: refuse_product_targets(None, "http://localhost:8102/aegis/"))
    assert text == "refused: the worker on port 8102 is the product worker"
    # A scratch worker on a scratch root passes.
    assert refuse_product_targets(scratch, "http://127.0.0.1:8103/aegis/") is None

    # execute refuses by itself (the walk imports this module), before any request or job.
    for name in PAST_THE_REFUSAL:
        monkeypatch.setattr(lab_benchmark, name, _past_the_refusal)
    pid_file = tmp_path / "none.pid"

    def execute(base: str, data_root: Path):
        return lambda: lab_benchmark.execute(
            base, cases=["A"], pid_file=pid_file, data_root=data_root
        )

    monkeypatch.setattr(lab_benchmark, "health_live", _no_network)
    text = _refused(execute("http://127.0.0.1:8102/aegis/", scratch))
    assert text == "refused: the worker on port 8102 is the product worker"
    text = _refused(execute("http://127.0.0.1:8103/aegis/", product_root()))
    assert text == "refused: --data-root is the product root; pass --data-root <scratch>"
    # A worker on another port that serves the product store: refused from its /health/live.
    answers["data_root"] = str(product_root())
    monkeypatch.setattr(lab_benchmark, "health_live", health)
    text = _refused(execute("http://127.0.0.1:8103/aegis/", scratch))
    assert text == "refused: the worker's data_root is the product root"
    assert not scratch.exists()


# --- re-test triggers ------------------------------------------------------------------------

PREVIOUS = {
    "mode": "execute",
    "engine_build": "a" * 64,
    "host": {
        "cpu": {"name": "test cpu", "logical": 12},
        "os": "test os",
        "ram_gb": 15.8,
        "free_memory_gb_at_start": 6.0,
        "indicators_per_side": 4,
        "ranged_parameters": 10,
        "bars_max": 46_034,
        "kinds": ["EMA", "MACD", "RSI", "SMA"],
    },
    "cases": {
        "A": {"bars": 2_603, "trials_per_s": 180.0},
        "B": {"bars": 9_669, "trials_per_s": 80.0},
    },
}
RETEST_KEYS = {
    "engine_build_changed",
    "surface_larger",
    "bars_over_50k",
    "new_kind",
    "rate_drift_over_15pct",
    "free_memory_under_2gb",
    "new_host",
}


def test_retest_triggers():
    same = copy.deepcopy(PREVIOUS)
    same["cases"]["A"]["trials_per_s"] = 200.0  # +11 %, within 15 %
    due = retest_due(same, PREVIOUS)
    assert set(due) == RETEST_KEYS
    assert not any(due.values()), due

    def only(record) -> set[str]:
        return {key for key, value in retest_due(record, PREVIOUS).items() if value}

    changed = copy.deepcopy(PREVIOUS)
    changed["engine_build"] = "b" * 64
    assert only(changed) == {"engine_build_changed"}
    low = copy.deepcopy(PREVIOUS)
    low["host"]["free_memory_gb_at_start"] = 1.9
    assert only(low) == {"free_memory_under_2gb"}
    drift = copy.deepcopy(PREVIOUS)
    drift["cases"]["B"]["trials_per_s"] = 60.0  # -25 %
    assert only(drift) == {"rate_drift_over_15pct"}
    larger = copy.deepcopy(PREVIOUS)
    larger["host"]["ranged_parameters"] = 20
    assert only(larger) == {"surface_larger"}
    wider = copy.deepcopy(PREVIOUS)
    wider["host"]["indicators_per_side"] = 5
    assert only(wider) == {"surface_larger"}
    longer = copy.deepcopy(PREVIOUS)
    longer["cases"]["C"] = {"bars": 60_000, "trials_per_s": 15.0}
    assert only(longer) == {"bars_over_50k"}
    kind = copy.deepcopy(PREVIOUS)
    kind["host"]["kinds"] = [*PREVIOUS["host"]["kinds"], "ATR"]
    assert only(kind) == {"new_kind"}
    host = copy.deepcopy(PREVIOUS)
    host["host"]["ram_gb"] = 32.0
    assert only(host) == {"new_host"}

    first = retest_due(PREVIOUS, None)
    assert set(first) == RETEST_KEYS
    assert all(first[key] for key in RETEST_KEYS - {"free_memory_under_2gb"})
    assert first["free_memory_under_2gb"] is False  # read from the record alone
    assert retest_due(low, None)["free_memory_under_2gb"] is True


# --- the fixture -----------------------------------------------------------------------------


def test_fixture_writes_a_layout2_experiment_readable_by_the_lab(client, tmp_path):  # noqa: F811
    c, _, _ = client
    root = tmp_path / "aegis"
    document = lab_fixture.write_fixture(root, trials=4_000, parameters=10, seed=1, part_rows=1_000)
    store = ExperimentStore(JsonRunRepository(root))
    assert store.layout(document.id) == 2
    saved = store.get(document.id)
    assert saved.name.startswith("DEMO · synthetic")
    assert len(saved.surface.parameters) == 10
    for k, parameter in enumerate(saved.surface.parameters):
        assert parameter.path == BENCH_SURFACE[k].path
        assert len(Parameter(**parameter.model_dump()).values()) == BENCH_SURFACE[k].n_values
    trials = read_latest(store.cells_dir(document.id))
    assert len(trials.table) == 4_000 and trials.duplicates == 0
    assert trials.table.column("trial_no").to_pylist() == list(range(4_000))
    # `cell` is the mixed-radix grid index of the positions.
    grid = build_grid(saved.spec, saved.surface, None)
    sample = trials.table.slice(0, 50).to_pylist()
    for row in sample:
        positions = tuple(row[f"pos.{k}"] for k in range(10))
        assert row["cell"] == grid.index_at(positions)
        assert grid.positions(row["cell"]) == positions
        assert {path: row[path] for path in grid.paths} == grid.cell_values(row["cell"])

    source = f"exp:{document.id}"
    summary = c.get(f"/aegis/api/lab/{source}/summary")
    assert summary.status_code == 200, summary.text
    counts = summary.json()["counts"]
    assert counts["scheduled"] == 4_000 and counts["completed"] == 4_000
    assert counts["space"] == counts["valid"] == 287_570_497_536
    assert counts["budget_total"] == counts["scheduled"] == 4_000
    answer = c.post(
        f"/aegis/api/lab/{source}/query", json={"view": "counts", "filter": {}, "metric": "cagr"}
    )
    assert answer.status_code == 200, answer.text
    scope = answer.json()["scope"]
    assert scope["undefined"] / scope["completed"] == pytest.approx(0.03, abs=0.01)


def test_fixture_document_validates_under_the_surface_cap(tmp_path):
    root = tmp_path / "aegis"
    document = lab_fixture.write_fixture(
        root, experiment_id="demo-cap", trials=1_000, parameters=10, seed=2, part_rows=1_000
    )
    saved = ExperimentStore(JsonRunRepository(root)).get(document.id)
    assert len(saved.surface.parameters) == 10
    with pytest.raises(ValueError, match="exceeds the 10 bench paths"):
        lab_fixture.write_fixture(root, experiment_id="demo-eleven", trials=1_000, parameters=11)
    assert not (root / "experiments" / "demo-eleven.json.gz").exists()
    assert not (root / "experiments" / "demo-eleven.cells").exists()
    # The cap the fixture lives under, asserted literally: eleven distinct paths are refused.
    eleven = [
        Parameter(path=f"long_side.indicators.rsi.params.p{k}", start=1, stop=2, step=1)
        for k in range(11)
    ]
    with pytest.raises(ValueError, match="at most 10 parameters"):
        Surface(parameters=eleven)


def _one(positions: list[int]) -> dict:
    """known_metrics of one row; the same seed gives every call the same noise and draws."""
    return lab_fixture.known_metrics(
        np.array([positions], dtype=np.uint16), np.random.default_rng(5)
    )


def test_known_metrics_structure():
    top = [p.n_values - 1 for p in BENCH_SURFACE]
    # Outside the plateau and off the spike (p5 = p6 = their last positions), every structure
    # path below its midpoint.
    base = [0, 0, 0, 0, 0, top[5], top[6], 0, 0, 0]

    def net(**changes) -> float:
        row = list(base)
        for name, value in changes.items():
            row[int(name[1:])] = value
        return float(_one(row)["combined.net_pnl"][0])

    hi = {f"p{k}": top[k] for k in range(10)}
    # The XOR pair: p0's effect flips sign across p1's midpoint (+4 below it, -4 above it), so
    # the two diagonal quadrants agree and the two off-diagonal ones sit 4 higher.
    assert net(p0=hi["p0"]) - net() == pytest.approx(4.0, abs=1e-12)
    assert net(p0=hi["p0"], p1=hi["p1"]) - net(p1=hi["p1"]) == pytest.approx(-4.0, abs=1e-12)
    assert net(p0=hi["p0"], p1=hi["p1"]) == pytest.approx(net(), abs=1e-12)
    assert net(p1=hi["p1"]) == pytest.approx(net(p0=hi["p0"]), abs=1e-12)
    # The conditional triple adds exactly 2 where all three of p2, p3, p4 hold, else nothing.
    all_three = {"p2": hi["p2"], "p3": hi["p3"], "p4": hi["p4"]}
    assert net(**all_three) - net() == pytest.approx(2.0, abs=1e-12)
    for missing in all_three:
        two = {name: value for name, value in all_three.items() if name != missing}
        assert net(**two) == pytest.approx(net(), abs=1e-12), missing
    # The plateau / spike pair over p5 and p6: a broad gain and one sharp loss.
    plateau = {"p5": round(0.3 * top[5]), "p6": round(0.3 * top[6])}
    spike = {"p5": round(0.8 * top[5]), "p6": round(0.8 * top[6])}
    assert net(**plateau) - net() == pytest.approx(lab_fixture.PLATEAU_GAIN, abs=1e-12)
    assert net(**spike) - net() == pytest.approx(-6.0, abs=1e-12)
    # Only p0..p6 are read: ten parameters suffice, whatever the others' value counts.
    rng_rows = np.random.default_rng(9)
    positions = np.column_stack(
        [rng_rows.integers(0, p.n_values, 500) for p in BENCH_SURFACE]
    ).astype(np.uint16)
    full = lab_fixture.known_metrics(positions, np.random.default_rng(3))
    seven = lab_fixture.known_metrics(positions[:, :7].copy(), np.random.default_rng(3))
    shuffled = positions.copy()
    shuffled[:, 7:] = rng_rows.integers(0, 40_000, (500, 3))
    other = lab_fixture.known_metrics(shuffled, np.random.default_rng(3))
    assert set(full) == {f"{s}.{m}" for s in ("combined", "long", "short") for m in METRIC_KEYS}
    for name in full:
        np.testing.assert_array_equal(full[name], seven[name])
        np.testing.assert_array_equal(full[name], other[name])
    with pytest.raises(ValueError, match="p0..p6"):
        lab_fixture.known_metrics(positions[:, :6].copy(), np.random.default_rng(3))


METRIC_KEYS = (
    "net_pnl",
    "net_return",
    "cagr",
    "max_drawdown",
    "mar",
    "win_rate",
    "expectancy",
    "profit_factor",
    "trade_count",
    "exposure",
    "sharpe_trade",
)


# --- the benchmark strategy and the import rule ------------------------------------------------

IMPORT_RULE = (
    "import sys; import lab_benchmark; "
    "assert 'numba' not in sys.modules and 'pyarrow' not in sys.modules "
    "and 'products.aegis.surface' not in sys.modules and 'products.aegis.lab' not in sys.modules "
    "and 'lab_fixture' not in sys.modules"
)
CORE_BODY = (
    "import lab_benchmark; from products.aegis import kernel; assert kernel.AVAILABLE is False; "
    "lab_benchmark.bench_strategy(); lab_benchmark.bench_surface()"
)
CORE_INTERPRETER = Path("C:/Triad/.venv/Scripts/python.exe")


def _run(interpreter, code: str) -> None:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(CHECKOUT / "app"), str(BENCH_DIR)])}
    done = subprocess.run(
        [str(interpreter), "-c", code], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_bench_strategy_validates_and_has_ten_ranged_paths():
    spec = lab_benchmark.bench_strategy()
    assert StrategySpec.model_validate(spec.model_dump(mode="json")) == spec
    for side in (spec.long_side, spec.short_side):
        assert [i.id for i in side.indicators] == ["ema", "sma", "rsi", "macd"]
        assert [i.kind for i in side.indicators] == ["EMA", "SMA", "RSI", "MACD"]
        assert len(side.entry.all_of) == 3 and len(side.exit.any_of) == 2
        assert side.stop_loss_pct is not None and side.take_profit_pct is not None
    assert spec.execution.commission_per_side == 1.0 and spec.execution.slippage_bps == 5.0
    assert len(BENCH_SURFACE) == 10
    assert BENCH_SURFACE[0].path == "long_side.indicators.ema.length"
    for bench in BENCH_SURFACE:
        apply_params(spec, {bench.path: bench.start})  # every path resolves on the spec
        apply_params(spec, {bench.path: bench.stop})
        parameter = Parameter(path=bench.path, start=bench.start, stop=bench.stop, step=bench.step)
        assert bench.n_values == len(parameter.values()), bench.path
    assert Parameter(**lab_benchmark.bench_surface().parameters[0].model_dump()).values()[1] == 10
    size = build_grid(spec, lab_benchmark.bench_surface(), None).size
    assert size == math.prod(p.n_values for p in BENCH_SURFACE) == 287_570_497_536
    assert abs(size - 2.87e11) / 2.87e11 < 0.01
    assert BENCH_CASES["A"].bars_nominal == 2_603 and BENCH_CASES["A"].timeframe == "1h"

    # The import rule, in fresh interpreters (this one has imported numba already).
    _run(sys.executable, IMPORT_RULE)
    _run(sys.executable, "import sys; sys.modules['numba'] = None; " + CORE_BODY)
    if CORE_INTERPRETER.exists():
        _run(CORE_INTERPRETER, CORE_BODY)


# --- analytics (Phase 3, Task 12) --------------------------------------------------------------

ANALYTICS = {
    "mode": "analytics",
    "host": {"cpu": {"name": "test cpu", "logical": 12}, "os": "test os", "ram_gb": 15.8},
    "engine_build": "e" * 64,
    "git_head": "0" * 40,
    "basis": "http (scratch worker)",
    "operations": {
        "pareto": {"basis": "http", "http_ms": {"p95": 500.0}},
        "neighbourhood": {"basis": "http", "http_ms": {"p95": 90.0}},
        "candidate": {"basis": "http", "http_ms": {"p95": 120.0}},
        "rankings": {"basis": "http", "http_ms": {"p95": 2_000.0}},  # recorded, never judged
    },
    "task": {
        "task_s": 120.0,
        "fine_stage_s": 20.0,
        "fine_stage_is_bound": True,
        "beside_job": True,
    },
    "wide": {"task": {"fine_stage_s": 25.0, "fine_stage_is_bound": False, "beside_job": True}},
    "cases": {"quiet": {"trials_per_s": 180.0}, "loaded": {"trials_per_s": 135.0}},
}
# One number per key pushed just past its line (§9.6a: the task budget, the fine stage, two views;
# the candidate's robustness shares the neighbourhood's 150 ms row; the fine stage at 20 values).
ANALYTICS_PAST = {
    "importance_task_s": ("task", "task_s", 180.5),
    "fine_stage_s": ("task", "fine_stage_s", 30.5),
    "fine_stage_20_s": ("wide", "fine_stage_s", 30.5),
    "pareto": ("operations", "pareto", 801.0),
    "neighbourhood": ("operations", "neighbourhood", 151.0),
    "candidate": ("operations", "candidate", 151.0),
}


def _analytics_past(record: dict, key: str) -> None:
    section, name, value = ANALYTICS_PAST[key]
    if section == "task":
        record["task"][name] = value
    elif section == "wide":
        record["wide"]["task"][name] = value
    else:
        record["operations"][name]["http_ms"]["p95"] = value


class _ScriptedHttp:
    """A worker's answers, scripted: `_TaskLoad` over it without a worker."""

    answers: ClassVar[list] = []
    posts: ClassVar[list] = []

    def __init__(self, base):
        self.base = base

    def get(self, path):
        return {"status": "running", "progress": {"cells_done": 5}}

    def post(self, path, body):
        _ScriptedHttp.posts.append((path, body))
        answers = _ScriptedHttp.answers
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def close(self):
        pass


def _importance_answer(state: str, stage: int | None, elapsed: float | None = None) -> dict:
    """An `importance` view's answer: the task's status and the latest stage delivered."""
    shown = (
        None if stage is None else {"stage": stage, "stages": 3, "elapsed_s": elapsed, "n": 50_000}
    )
    task = {"id": "t1", "label": "importance", "state": state, "stage": stage or 0, "stages": 3}
    return {"task": task, "importance": shown, "reason": None}


def test_analytics_record(monkeypatch):
    # The constants: the two views' budgets join §9.6a's table, the task has its own two lines.
    assert TRACK_A_BUDGETS_MS["pareto"] == 800 and TRACK_A_BUDGETS_MS["neighbourhood"] == 150
    assert lab_benchmark.TRACK_ANALYTICS_LIMITS == {
        "importance_task_s": 180.0,
        "fine_stage_s": 30.0,
    }

    # A record that meets every line; each number pushed past its line fails it alone.
    verdict = evaluate(ANALYTICS)
    assert verdict == {key: True for key in ANALYTICS_PAST}, verdict
    for key in ANALYTICS_PAST:
        record = copy.deepcopy(ANALYTICS)
        _analytics_past(record, key)
        result = evaluate(record)
        assert result[key] is False, key
        assert all(result[k] is True for k in ANALYTICS_PAST if k != key), key
    # The lines themselves pass (<=), and a missing measurement is absent, never passed.
    edge = copy.deepcopy(ANALYTICS)
    edge["task"].update(task_s=180.0, fine_stage_s=30.0)
    assert evaluate(edge)["importance_task_s"] is True and evaluate(edge)["fine_stage_s"] is True
    assert all(value == "absent" for value in evaluate({"mode": "analytics"}).values())
    assert set(evaluate({"mode": "analytics"})) == set(ANALYTICS_PAST)
    # The task's rows are measured beside a running job or not at all: a task that ran on an
    # idle worker (cached, or the job ended first) is absent, not passed with a quiet number.
    idle = copy.deepcopy(ANALYTICS)
    idle["task"]["beside_job"] = False
    result = evaluate(idle)
    assert result["importance_task_s"] == "absent" and result["fine_stage_s"] == "absent"
    assert result["pareto"] is True and result["neighbourhood"] is True
    assert result["candidate"] is True and result["fine_stage_20_s"] is True
    # The 20-value pass is judged under its own key, beside a job or not at all, and `absent`
    # when it was not run (the 1M fixture with 20 values is optional).
    wide_idle = copy.deepcopy(ANALYTICS)
    wide_idle["wide"]["task"]["beside_job"] = False
    assert evaluate(wide_idle)["fine_stage_20_s"] == "absent"
    no_wide = {key: value for key, value in ANALYTICS.items() if key != "wide"}
    assert evaluate(no_wide)["fine_stage_20_s"] == "absent"
    assert evaluate(no_wide)["fine_stage_s"] is True
    # `rankings`, `convergence` and the Pareto variants are recorded, never judged (the spec's
    # §9.6a states no line for them): they are no key of the verdict.
    assert not set(evaluate(ANALYTICS)) & {"rankings", "convergence", "pareto_3", "pareto_widest"}
    # M-1: the fine stage is a bound when stage 1 was not read; the record's evaluate basis says
    # so beside the verdict, and says "measured" when stage 1's own time was read.
    basis = lab_benchmark.evaluate_basis(ANALYTICS)
    assert "upper bound" in basis["fine_stage_s"] and "measured" in basis["fine_stage_20_s"], basis
    assert "150" in basis["candidate"] and "robustness of one candidate" in basis["candidate"]
    assert set(basis) == set(ANALYTICS_PAST), basis
    # The job's throughput loss is recorded, never judged: no key of the verdict carries it.
    assert not [key for key in verdict if "loss" in key or "throughput" in key]

    # throughput_loss = 1 - loaded / quiet; a faster loaded run is a negative loss, kept as
    # measured; a missing rate is None.
    assert lab_benchmark.throughput_loss(180.0, 135.0) == pytest.approx(0.25)
    assert lab_benchmark.throughput_loss(100.0, 105.0) == pytest.approx(-0.05)
    assert lab_benchmark.throughput_loss(None, 135.0) is None
    assert lab_benchmark.throughput_loss(180.0, None) is None
    assert lab_benchmark.throughput_loss(0.0, 135.0) is None

    # The loaded rate counts only the chunks committed while the task ran: per run, those inside
    # the window, the first one's rows left out (its work began before the window), rows over the
    # seconds between the first and the last; runs add up. A run with one chunk in the window
    # adds nothing, and nothing inside the window is None.
    run_a = ([float(t) for t in range(10)], [200] * 10)  # 200 rows a second, t = 0 .. 9
    run_b = ([20.0, 20.5, 21.0, 21.5, 40.0], [100, 100, 100, 100, 100])  # 200 rows a second
    window = lab_benchmark.overlap_rate([run_a, run_b], 2.5, 21.2)
    # run_a: t = 3 .. 9 -> 6 later chunks of 200 over 6 s; run_b: t = 20 .. 21 -> 2 of 100 over 1 s
    assert window["rows"] == 1_400 and window["seconds"] == pytest.approx(7.0)
    assert window["trials_per_s"] == pytest.approx(200.0)
    assert [r["chunks"] for r in window["runs"]] == [7, 3]
    one = lab_benchmark.overlap_rate([run_a], 2.5, 3.5)
    assert one["trials_per_s"] is None and one["rows"] == 0 and one["runs"][0]["chunks"] == 1
    assert lab_benchmark.overlap_rate([run_a], 50.0, 60.0)["trials_per_s"] is None
    slow = ([0.0, 2.0, 4.0], [200, 200, 200])  # 100 rows a second
    both = lab_benchmark.overlap_rate([run_a, slow], 0.0, 9.0)
    assert both["rows"] == 1_800 + 400 and both["seconds"] == pytest.approx(9.0 + 4.0)

    # "Beside a job" is a share of the task's window that the job's runs cover (their union):
    # back-to-back runs with a gap between them leave it short of 1.
    assert lab_benchmark.job_coverage([(0.0, 10.0), (12.0, 20.0)], 5.0, 15.0) == pytest.approx(0.8)
    assert lab_benchmark.job_coverage([(0.0, 100.0)], 5.0, 15.0) == pytest.approx(1.0)
    assert lab_benchmark.job_coverage([(0.0, 10.0), (5.0, 12.0)], 0.0, 12.0) == pytest.approx(1.0)
    assert lab_benchmark.job_coverage([], 0.0, 10.0) == 0.0
    assert lab_benchmark.job_coverage([(20.0, 30.0)], 0.0, 10.0) == 0.0
    assert lab_benchmark.job_coverage([(0.0, 10.0)], 5.0, 5.0) == 0.0

    # The loaded rate is judged against the quiet run over the same offsets from its creation: a
    # run's whole-run rate carries its start-up and its compaction pause, which a short window may
    # not. Per loaded run, the window's part inside its [created, final], as offsets from creation.
    assert lab_benchmark.window_offsets([(100.0, 180.0)], 110.0, 122.0) == [(10.0, 22.0)]
    assert lab_benchmark.window_offsets([(100.0, 180.0)], 90.0, 190.0) == [(0.0, 80.0)]
    two = [(100.0, 130.0), (135.0, 200.0)]  # back to back, a gap between them
    assert lab_benchmark.window_offsets(two, 120.0, 150.0) == [(20.0, 30.0), (0.0, 15.0)]
    assert lab_benchmark.window_offsets(two, 131.0, 134.0) == []
    assert lab_benchmark.window_offsets([(100.0, 130.0)], 200.0, 210.0) == []
    # A quiet run created at 1000 s whose first chunk lands 10 s later (a rate of 200 a second
    # to 1,030, then 100 a second): a window read from the creation, not from the epoch.
    times = [1_010.0 + t for t in range(20)] + [1_030.0 + 2.0 * t for t in range(1, 21)]
    quiet = (times, [200] * 20 + [200] * 20)
    matched = lab_benchmark.matched_rate(quiet, 1_000.0, [(10.0, 22.0), (0.0, 15.0)])
    # (10, 22): chunks at 1,010 .. 1,022, 12 of 200 over 12 s; (0, 15): chunks at 1,010 .. 1,015,
    # 5 of 200 over 5 s
    assert matched["rows"] == 12 * 200 + 5 * 200 and matched["seconds"] == pytest.approx(17.0)
    assert matched["trials_per_s"] == pytest.approx(200.0)
    assert [w["chunks"] for w in matched["windows"]] == [13, 6]
    slow = lab_benchmark.matched_rate(quiet, 1_000.0, [(31.0, 39.0)])  # the 100 a second part
    assert slow["trials_per_s"] == pytest.approx(100.0)
    assert lab_benchmark.matched_rate(quiet, 1_000.0, [])["trials_per_s"] is None
    # Dropping the creation from the window (reading it from the epoch) finds no chunk at all.
    assert lab_benchmark.matched_rate(quiet, 0.0, [(10.0, 22.0)])["trials_per_s"] is None

    # The fine-grid stage: stage 1's own elapsed time when a poll read it; when stage 2 had already
    # landed, the first stage read is an upper bound and says so; nothing read, nothing claimed.
    both = {"1": {"wall_s": 6.0, "elapsed_s": 5.5}, "2": {"wall_s": 7.0, "elapsed_s": 6.5}}
    assert lab_benchmark.fine_stage(both) == (5.5, "server elapsed_s of stage 1", False)
    late = {"3": {"wall_s": 12.0, "elapsed_s": 11.4}, "2": {"wall_s": 7.4, "elapsed_s": 6.7}}
    value, basis, bound = lab_benchmark.fine_stage(late)
    assert value == 6.7 and "stage 2" in basis and "upper bound" in basis, (value, basis)
    assert bound is True
    assert lab_benchmark.fine_stage({}) == (None, None, None)
    assert lab_benchmark.fine_stage({"2": {"wall_s": 7.0, "elapsed_s": None}}) == (None, None, None)

    # "Beside a job" as a rule: a task that finished (not cached at request, not stopped) whose
    # window the job's runs covered at 0.9 or more.
    done = {"state": "done", "cached_at_request": False}
    assert lab_benchmark.beside_job(done, 0.9) is True
    assert lab_benchmark.beside_job(done, 0.89) is False
    assert lab_benchmark.beside_job({**done, "cached_at_request": True}, 1.0) is False
    assert lab_benchmark.beside_job({**done, "state": "cancelled"}, 1.0) is False
    assert lab_benchmark.beside_job({}, 1.0) is False  # the thread failed: no result at all

    # The plan against the actual wall time of a case, and the widest front among pairs.
    assert lab_benchmark.plan_vs_actual(100.0, 440.0) == {
        "estimate_s": 100.0,
        "actual_s": 440.0,
        "actual_over_estimate": 4.4,
    }
    assert lab_benchmark.plan_vs_actual(None, 440.0)["actual_over_estimate"] is None
    fronts = {("a", "b"): 10, ("a", "c"): 57, ("b", "c"): 3}
    assert lab_benchmark.widest_front(fronts) == (("a", "c"), 57)
    assert lab_benchmark.widest_front({}) is None

    # The headline's basis says what the two rates are and which figure to read.
    text = lab_benchmark.throughput_basis(150.0, 152.0, 184.0, 8, 7.6)
    assert "whole-run" in text and "8-chunk" in text and "not comparable" in text, text
    assert "throughput_loss_matched" in text and "150.0" in text and "152.0" in text, text

    # The two views' requests, as the UI sends them: a Pareto front of the objective against max
    # drawdown, and the neighbourhood of a seeded trial (a different one every run).
    document = type(
        "Doc",
        (),
        {
            "id": "demo-synthetic-1m",
            "objective": "net_pnl",
            "surface": lab_benchmark.bench_surface(),
        },
    )()
    operations = lab_benchmark._operations(document, 1_000_000, 1)
    lab = "lab/exp:demo-synthetic-1m"
    assert operations["pareto"](0) == [
        (
            "POST",
            f"{lab}/query",
            {"filter": {}, "view": "pareto", "objectives": ["net_pnl", "max_drawdown"]},
        )
    ]
    pool = [f"exp:demo-synthetic-1m#{n}" for n in range(1_000, 1_300)]  # the ranking's 300
    with_pool = lab_benchmark._operations(document, 1_000_000, 1, task_seed=3, pool=pool)
    assert "candidate" not in operations  # no pool, no candidate: explore has no importance
    chosen = []
    for i in range(20):
        ((method, path, body),) = with_pool["candidate"](i)
        assert (method, path) == ("POST", f"{lab}/query"), (method, path)
        assert body["view"] == "robustness" and body["trial"] in pool, body
        assert body["metric"] == "net_pnl" and body["seed"] == 3, body  # B reads this seed's task
        chosen.append(body["trial"])
    assert len(set(chosen)) == 20  # 20 different candidates of the pool
    second = lab_benchmark._operations(document, 1_000_000, 2, pool=pool)
    assert chosen != [second["candidate"](i)[0][2]["trial"] for i in range(20)]
    assert with_pool["rankings"](0) == [
        (
            "POST",
            f"{lab}/query",
            {"filter": {}, "view": "robustness", "metric": "net_pnl", "seed": 3},
        )
    ]
    assert with_pool["convergence"](0)[0][2]["view"] == "convergence"
    three = with_pool["pareto_3"](0)[0][2]
    assert three["view"] == "pareto" and len(three["objectives"]) == 3, three
    # Every body is what the worker's endpoint takes (extra fields are forbidden, `view` a literal).
    from products.aegis import api

    for name in ("pareto", "neighbourhood", "candidate", "rankings", "convergence", "pareto_3"):
        for i in range(3):
            for _, _, request_body in with_pool[name](i):
                api.QueryRequest.model_validate(request_body)
    trials = []
    for i in range(20):
        ((method, path, body),) = operations["neighbourhood"](i)
        assert (method, path) == ("POST", f"{lab}/query"), (method, path)
        assert set(body) == {"filter", "view", "trial", "metric"}, body
        assert body["view"] == "neighbourhood" and body["filter"] == {}
        assert body["metric"] == "net_pnl"
        prefix, _, number = body["trial"].partition("#")
        assert prefix == "exp:demo-synthetic-1m" and 0 <= int(number) < 1_000_000
        trials.append(int(number))
    assert len(set(trials)) == 20  # a different trial every run
    again = lab_benchmark._operations(document, 1_000_000, 1)["neighbourhood"]
    assert [int(again(i)[0][2]["trial"].partition("#")[2]) for i in range(20)] == trials
    for seed in (2, 7):  # a different trial every run for other seeds too, and other trials
        other = lab_benchmark._operations(document, 1_000_000, seed)["neighbourhood"]
        picked = [int(other(i)[0][2]["trial"].partition("#")[2]) for i in range(20)]
        assert len(set(picked)) == 20 and picked != trials, seed
    # explore times both beside the Phase 2 rows, from the one budget table, and records the
    # rows no §9.6a line states.
    assert set(TRACK_A_BUDGETS_MS) - {"open_cold"} <= set(operations)  # open_cold is open, once
    assert set(lab_benchmark.RECORDED_OPERATIONS) == {"rankings", "convergence", "pareto_3"}
    assert set(lab_benchmark.RECORDED_OPERATIONS) <= set(with_pool)

    # `_timed` keeps the cold first sample apart, and calls `on_first` after the first run only.
    seen = []

    def call(method, path, body):
        seen.append(path)

    timed = lab_benchmark._timed(
        call, operations["pareto"], 5, "http", on_first=lambda: seen.append("first")
    )
    assert seen[:2] == [f"{lab}/query", "first"] and seen.count("first") == 1, seen
    assert timed["cold_ms"] == timed["http_ms"]["samples"][0]
    assert timed["warm_ms"]["n"] == 4 and timed["http_ms"]["n"] == 5

    # An analytics record as the command builds it: the host, the engine build, the commit, the
    # operations (the two views) and the cases (the quiet run and the loaded rate).
    record = lab_benchmark.new_record("analytics")
    assert record["mode"] == "analytics" and "operations" in record and "cases" in record
    assert len(record["engine_build"]) == 64 and len(record["git_head"]) == 40
    # It says what it does not measure: the fixture has no blocks and ten parameters.
    rows = lab_benchmark.ANALYTICS_NOT_MEASURED
    assert all({"row", "why", "owner"} <= set(entry) and entry["owner"] for entry in rows), rows
    text = " ".join(f"{entry['row']} {entry['why']}" for entry in rows)
    assert "10 parameters" in text and "no blocks" in text
    assert "per-block mains" in text and "d = 20" in text and "K = 20" in text
    assert "all-on-front" in text and "opt:" in text
    # The re-test triggers read it like the others (rates from its cases).
    due = retest_due(
        ANALYTICS | {"host": PREVIOUS["host"]}, PREVIOUS | {"cases": ANALYTICS["cases"]}
    )
    assert set(due) == RETEST_KEYS

    # The task thread over scripted answers: it waits for the job, requests the task, polls to
    # done, keeps the stages it read (stage 1 missed: a bound), the poll latencies and the window.
    monkeypatch.setattr(lab_benchmark, "_Http", _ScriptedHttp)
    monkeypatch.setattr(lab_benchmark, "ANALYTICS_POLL_S", 0.0)
    _ScriptedHttp.posts = []
    _ScriptedHttp.answers = [
        _importance_answer("running", None),
        _importance_answer("running", 2, 6.5),
        _importance_answer("done", 3, 11.0),
    ]
    load = lab_benchmark._TaskLoad("http://x/aegis/", "exp:demo", 1, 60.0)
    load.start("exp:job")
    load.join()
    assert load.finished.is_set() and load.error is None, load.error
    result = load.result
    assert result["state"] == "done" and result["task_s"] == 11.0 and result["polls"] == 3
    assert result["fine_stage_s"] == 6.5 and result["fine_stage_is_bound"] is True, result
    assert result["cached_at_request"] is False and sorted(result["stages_seen"]) == ["2", "3"]
    assert len(result["poll_ms"]["samples"]) == 3 and result["poll_cadence_s"] == 0.0
    assert load.window is not None and load.window[1] >= load.window[0]
    assert all(body["view"] == "importance" for _, body in _ScriptedHttp.posts)
    # A worker that answers no task: the thread records why and stops the loop.
    _ScriptedHttp.answers = [{"task": None, "importance": None, "reason": "no rows"}]
    refused = lab_benchmark._TaskLoad("http://x/aegis/", "exp:demo", 1, 60.0)
    refused.start("exp:job")
    refused.join()
    assert refused.finished.is_set() and "no importance task: no rows" in (refused.error or "")
    # A task still running at the timeout is cancelled through its route.
    _ScriptedHttp.posts = []
    _ScriptedHttp.answers = [_importance_answer("running", 1, 3.0)]
    slow = lab_benchmark._TaskLoad("http://x/aegis/", "exp:demo", 1, 0.0)
    slow.start("exp:job")
    slow.join()
    assert slow.result["cancelled_at_timeout"] is True and slow.result["task_s"] is None
    assert any(path.endswith("/tasks/t1/cancel") for path, _ in _ScriptedHttp.posts)
    monkeypatch.undo()

    # analytics refuses the product targets itself, before any request, process or file; and the
    # command refuses before anything else.
    for name in PAST_THE_REFUSAL:
        monkeypatch.setattr(lab_benchmark, name, _past_the_refusal)
    monkeypatch.setattr(lab_benchmark, "health_live", _no_network)
    pid_file = Path("none.pid")
    text = _refused(
        lambda: lab_benchmark.analytics(
            product_root(), base="http://127.0.0.1:8103/aegis/", pid_file=pid_file
        )
    )
    assert text == "refused: --data-root is the product root; pass --data-root <scratch>"
    scratch = Path("scratch-not-written")
    text = _refused(
        lambda: lab_benchmark.analytics(
            scratch, base="http://127.0.0.1:8102/aegis/", pid_file=pid_file
        )
    )
    assert text == "refused: the worker on port 8102 is the product worker"
    assert not scratch.exists()
    argv = [
        "analytics",
        "--data-root",
        str(product_root()),
        "--base",
        "http://127.0.0.1:8103/aegis/",
        "--pid-file",
        "logs/none.pid",
    ]
    logs = sorted((CHECKOUT / "logs").glob("lab-benchmark-*.json"))
    assert lab_benchmark.main(argv) == 2
    assert sorted((CHECKOUT / "logs").glob("lab-benchmark-*.json")) == logs


# --- category A read back from its inputs (the walk's items 111 and 124) -----------------------


def _a_card(resolved=True, classification=None, reason=None, **changes) -> dict:
    inputs = {
        "n": 7,
        "valid": 8,
        "tested": 7,
        "undefined": 0,
        "coverage": 0.875,
        "min_coverage": 0.5,
        "required_n": 7,
        "r": 1,
        "m": 2,
        "probes": 8,
        "valid_basis": "frame",
        "p25": 90.0,
        "p75": 110.0,
        "iqr": 20.0,
        "tau": 15.0,
        "value": 100.0,
        "distance": 10.0,
        "peak_factor": 3.0,
        "peak_line": 170.0,
        "orientation": 1,
    } | changes
    return {
        "resolved": resolved,
        "classification": classification,
        "reason": reason,
        "inputs": inputs,
    }


def test_a_rule_reads_a_card_back_from_its_inputs():
    rule = lab_benchmark.a_rule
    # The three classifications, from the worker's own numbers.
    assert rule(_a_card(classification="stable local")) == "stable local"  # |100 - 90| <= 15
    mixed = _a_card(classification="mixed", value=150.0, distance=60.0)
    assert rule(mixed) == "mixed"  # 60 > 15 and 150 <= 170
    peak = _a_card(classification="isolated peak", value=200.0, distance=110.0)
    assert rule(peak) == "isolated peak"  # 200 > 170 = 110 + 3 x 20
    # A label the inputs do not give fails, whichever way it is wrong.
    for card in (
        _a_card(classification="mixed"),  # stable by the inputs
        _a_card(classification="isolated peak", value=150.0, distance=60.0),  # not above the line
        _a_card(classification="stable local", value=150.0, distance=60.0),  # not within tau
    ):
        with pytest.raises(AssertionError):
            rule(card)
    # The rule recomputes distance and the peak line: a worker feeding it a wrong one is caught.
    with pytest.raises(AssertionError):
        rule(_a_card(classification="stable local", distance=1.0))  # |100 - 90| is 10
    with pytest.raises(AssertionError):
        rule(_a_card(classification="mixed", value=150.0, distance=60.0, peak_line=120.0))
    # A resolved card needs the coverage, the n and a spread: any shortfall fails.
    for short in ({"coverage": 0.4}, {"n": 6}, {"tau": 0.0}):
        with pytest.raises(AssertionError):
            rule(_a_card(classification="stable local", **short))
    # An unresolved card names the shortfall it has, for every reason the worker gives.
    unmet = _a_card(False, reason="untested surroundings (coverage 0.0 of 0.5)", coverage=0.0, n=0)
    assert rule(unmet) == "unresolved"
    few = _a_card(False, reason="untested surroundings (n 3 of 7)", n=3, tested=3)
    assert rule(few) == "unresolved"
    flat = _a_card(False, reason="no spread in the metric (τ = 0)", tau=0.0)
    assert rule(flat) == "unresolved"
    gone = _a_card(False, reason="undefined metric value", value=None, distance=None)
    assert rule(gone) == "unresolved"
    for card in (
        _a_card(False, reason="untested surroundings (coverage 0.9 of 0.5)"),  # enough evidence
        _a_card(False, reason="no spread in the metric (τ = 0)"),  # tau > 0
        _a_card(False, reason="no spread in the metric (τ = 0)", tau=0.0, coverage=0.1),  # short
        _a_card(False, reason="undefined metric value"),  # the value is defined
        _a_card(False, reason="a reason nobody sends"),
    ):
        with pytest.raises(AssertionError):
            rule(card)


def test_fixture_values_option(tmp_path):
    root = tmp_path / "aegis"
    document = lab_fixture.write_fixture(
        root,
        experiment_id="demo-wide",
        trials=2_000,
        parameters=10,
        seed=3,
        part_rows=1_000,
        values=20,
    )
    saved = ExperimentStore(JsonRunRepository(root)).get(document.id)
    assert "20 values per parameter" in saved.name
    for k, parameter in enumerate(saved.surface.parameters):
        assert parameter.path == BENCH_SURFACE[k].path and parameter.start == BENCH_SURFACE[k].start
        assert parameter.step == BENCH_SURFACE[k].step
        assert len(Parameter(**parameter.model_dump()).values()) == 20
    trials = read_latest(ExperimentStore(JsonRunRepository(root)).cells_dir(document.id))
    positions = np.column_stack([trials.table.column(f"pos.{k}").to_numpy() for k in range(10)])
    assert positions.max() == 19 and len(trials.table) == 2_000  # 20 values reached on a path
    assert lab_benchmark.fixture_id(1_000_000, 20) == "demo-synthetic-1m-20v"
    assert lab_benchmark.fixture_id(1_000_000) == "demo-synthetic-1m"
