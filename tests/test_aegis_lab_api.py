"""Optimization Lab v2, Phase 2 (Task 8): the `/aegis/api/lab` routes over `exp:` and `opt:`
sources. Real experiments and optimizations run through the API on the synthetic 52-bar archive;
the Lab cache is one instance per test, so a test can evict and inspect it."""

import json
import re
import shutil
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from products.aegis import experiments as experiments_module
from products.aegis.data import ArchiveStore
from products.aegis.experiments import ExperimentDocument, _same
from products.aegis.indicators import IndicatorCache
from products.aegis.lab import convergence as convergence_module
from products.aegis.lab import identity, sources
from products.aegis.lab import store as lab_store_module
from products.aegis.lab.cache import LabCache
from products.aegis.lab.importance import importance_key
from products.aegis.lab.tasks import LabTasks, task_key
from products.aegis.pool import METRICS, SCOPES
from products.aegis.results import strategy_hash
from products.aegis.runs import JsonRunRepository, aegis_data_root
from products.aegis.surface import apply_params
from test_aegis_api import (
    RANGE,
    NoCore,
    _experiment_body,
    _optimize_payload,
    _runner,
    _wait,
    _wait_experiment,
)
from test_aegis_data import write_archive
from test_aegis_optimize import small_strategy

pytestmark = pytest.mark.aegis

LAB = "/aegis/api/lab"
DONCHIAN = "long_side.indicators.donchian.length"
RSI = "long_side.indicators.rsi.length"
HEX32 = re.compile(r"[0-9a-f]{32}")


@pytest.fixture
def lab_cache():
    return LabCache(64 * 1024 * 1024)


@pytest.fixture
def client(tmp_path, monkeypatch, lab_cache):
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=100.0)
    store = ArchiveStore(tmp_path)
    repository = JsonRunRepository(tmp_path / "aegis")
    server.app.dependency_overrides[api.get_store] = lambda: store
    server.app.dependency_overrides[api.get_repository] = lambda: repository
    cache = IndicatorCache()
    server.app.dependency_overrides[api.get_cache] = lambda: cache
    server.app.dependency_overrides[api.get_core_reasoning] = lambda: NoCore()
    # One instance per test, captured: an override runs on every request, so a fresh cache per
    # call would never hit and an evict in a test would reach no route's cache.
    server.app.dependency_overrides[api.get_lab_cache] = lambda: lab_cache
    monkeypatch.setattr(server, "Store", lambda **_: SimpleNamespace(list_work=list))
    # No Lab request ever builds the worker's own runner on the real store, nor its Lab task
    # executor: one per test reads the test's runner and is shut down when the test ends.
    runner = _runner(repository)
    tasks = LabTasks(sharing_cpu=lambda: api._sharing_cpu(runner))
    server.app.dependency_overrides[api.get_lab_tasks] = lambda: tasks
    yield TestClient(server.app, raise_server_exceptions=False), store, repository
    server.app.dependency_overrides.clear()
    tasks.shutdown()


def _finished_experiment(c, monkeypatch, name="four cells", **overrides) -> str:
    """The 4-cell layout-2 experiment, two chunks of two, run to `done` through the API."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    monkeypatch.setattr(experiments_module, "CHUNK_CELLS", 2)
    created = c.post("/aegis/api/experiments", json=_experiment_body(c, name=name, **overrides))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    return experiment_id


def _trial_url(src: str, trial_id: str) -> str:
    return f"{LAB}/{src}/trials/{quote(trial_id, safe='')}"


def test_summary_of_a_layout2_experiment(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    response = c.get(f"{LAB}/exp:{experiment_id}/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    document = c.get(f"/aegis/api/experiments/{experiment_id}").json()
    assert body["source"] == f"exp:{experiment_id}" and body["kind"] == "exp"
    assert body["layout"] == 2 and body["status"] == "done"
    assert body["counts"]["completed"] == 4 and body["counts"]["filtered"] == 4
    assert body["counts"]["space"] == body["counts"]["valid"] == 4
    assert body["counts"]["unique"] == 4 and body["counts"]["filters_active"] == 0
    assert [entry["path"] for entry in body["parameters"]] == [DONCHIAN, RSI]
    assert [entry["values"] for entry in body["parameters"]] == [[10.0, 15.0], [7.0, 14.0]]
    for entry in body["parameters"]:
        assert entry["tested_per_value"] == [2, 2] and entry["bucketed"] is False
        assert entry["n_values"] == 2 and entry["side"] == "long" and entry["type"] == "int"
    assert len(body["versions"]["engine_build"]) == 64
    assert body["provisional"] is False and body["filter_hash"] is None
    assert body["snapshots"]["latest"] == {"generation": 1, "chunk_watermark": 1}
    spec = ExperimentDocument.model_validate(document).spec
    effective = identity.full_effective_params(spec)
    assert body["spec_values"] == {DONCHIAN: effective[DONCHIAN], RSI: effective[RSI]}
    assert body["data_pinned"] == document["data_pinned"] and body["engine"] == "kernel"
    headline = body["headline"]
    assert headline["objective"] == "net_pnl" and headline["completed"] == 4
    assert headline["undefined"] == 0
    best = headline["best"]
    assert best is not None and best["trial_id"].startswith(f"exp:{experiment_id}#")
    page = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "page"}).json()
    assert best["value"] == max(row["values"]["combined.net_pnl"] for row in page["rows"])


def test_query_views_share_one_scope(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    url = f"{LAB}/exp:{experiment_id}/query"
    flt = {"ranges": {DONCHIAN: [10, 12]}}
    bodies = {
        "counts": {"view": "counts", "metric": "net_pnl"},
        "matrix": {
            "view": "matrix",
            "rows": DONCHIAN,
            "cols": RSI,
            "metric": "net_pnl",
            "mode": "aggregate",
        },
        "page": {"view": "page", "metric": "net_pnl"},
        "top": {"view": "top", "metric": "net_pnl"},
        "bundles": {"view": "parallel", "metric": "net_pnl"},
        "sample": {"view": "parallel", "metric": "net_pnl", "parallel_mode": "sample"},
        "pareto": {"view": "pareto", "metric": "net_pnl", "objectives": ["mar", "max_drawdown"]},
        "convergence": {"view": "convergence", "metric": "net_pnl"},
    }
    answers = {}
    for name, body in bodies.items():
        response = c.post(url, json={"filter": flt, **body})
        assert response.status_code == 200, (name, response.text)
        answers[name] = response.json()
        assert answers[name]["view"] == body["view"] and answers[name]["provisional"] is False
        assert answers[name]["snapshot"] == {"generation": 1, "chunk_watermark": 1}
    trimmed = [
        {k: v for k, v in answer["scope"].items() if k not in ("shown", "basis")}
        for answer in answers.values()
    ]
    assert all(scope == trimmed[0] for scope in trimmed)
    assert trimmed[0]["filtered"] == 2 and trimmed[0]["completed"] == 4
    assert trimmed[0]["filters_active"] == 1
    page = answers["page"]
    assert page["total"] == page["scope"]["filtered"] == 2
    assert page["scope"]["shown"] == len(page["rows"]) == 2
    assert answers["matrix"]["scope"]["basis"] == "Aggregated from tested (n = 2)"
    assert answers["matrix"]["scope"]["shown"] == 2  # the squares holding trials
    assert answers["counts"]["scope"]["basis"] == "Tested (exact)"


def test_query_echoes_filter_hash_and_bounds(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    url = f"{LAB}/exp:{experiment_id}/query"
    echoed = c.post(url, json={"filter": {}, "view": "counts", "filter_hash": "cafe0001"})
    assert echoed.status_code == 200, echoed.text
    assert echoed.json()["filter_hash"] == "cafe0001"
    bare = c.post(url, json={"view": "counts", "filter": {}})
    assert bare.status_code == 200, bare.text
    assert bare.json()["filter_hash"] is None and bare.json()["scope"]["filtered"] == 4
    assert c.post(url, json={"view": "counts", "filter": {}, "metric": "cagr"}).status_code == 200
    two = c.post(url, json={"filter": {}, "view": "page", "limit": 2})
    assert two.status_code == 200 and len(two.json()["rows"]) == 2
    refused = [
        {"filter": {}, "view": "page", "limit": 501},
        {"filter": {}, "view": "top", "k": 501},
        {"filter": {}, "view": "matrix", "rows": DONCHIAN, "cols": DONCHIAN, "metric": "net_pnl"},
        {"filter": {}, "view": "matrix", "rows": DONCHIAN, "cols": RSI},
        {"filter": {}, "view": "page", "sort": "nope"},
        {"filter": {"ranges": {"long_side.indicators.nope.length": [1, 2]}}, "view": "counts"},
        {"filter": {}, "view": "counts", "metric": "nope"},
        {"filter": {}, "view": "counts", "brush": {}},
        {"filter": {}, "view": "square_trials", "rows": DONCHIAN, "cols": RSI},
    ]
    for body in refused:
        response = c.post(url, json=body)
        assert response.status_code == 422, (body, response.text)
    sort = c.post(url, json={"filter": {}, "view": "page", "sort": "nope"}).json()["detail"]
    assert "unknown sort column" in sort
    path = c.post(url, json={"filter": {"values": {"long_side.nope": 1}}, "view": "counts"}).json()[
        "detail"
    ]
    assert "unknown path" in path
    for literal in ('{"ranges": {"p": [NaN, 1]}}', '{"values": {"p": -Infinity}}'):
        raw = c.post(  # raw text: `json=` cannot emit the literals Starlette's json.loads accepts
            url,
            content=f'{{"filter": {literal}, "view": "counts"}}',
            headers={"content-type": "application/json"},
        )
        assert raw.status_code == 422, raw.text
        assert raw.json()["detail"][0]["type"] == "finite_number"


def test_query_loads_projected_columns_only(client, lab_cache, monkeypatch):
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    recorded: list[tuple | None] = []
    one_trial: list[tuple[int | None, int]] = []  # each read's trial_no and the rows it returned
    original = experiments_module.ExperimentStore.trials

    def recording(self, experiment_id, columns=None, *, snapshot=None, trial_no=None):
        recorded.append(None if columns is None else tuple(columns))
        trials = original(self, experiment_id, columns, snapshot=snapshot, trial_no=trial_no)
        one_trial.append((trial_no, trials.table.num_rows))
        return trials

    monkeypatch.setattr(experiments_module.ExperimentStore, "trials", recording)
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    meta = sources.experiment_meta(document)
    url = f"{LAB}/exp:{experiment_id}/query"
    base = {"filter": {"ranges": {RSI: [7, 14]}}}
    queries = [
        {"view": "counts"},
        {"view": "counts", "metric": "cagr"},
        {"view": "matrix", "rows": DONCHIAN, "cols": RSI, "metric": "net_pnl"},
        {"view": "matrix", "rows": DONCHIAN, "cols": RSI, "metric": "mar", "mode": "aggregate"},
        {"view": "page"},
        {"view": "top", "metric": "mar"},
        {"view": "marginals", "metric": "net_pnl"},
        {"view": "parallel", "axes": [DONCHIAN, RSI], "metric": "net_pnl"},
        {
            "view": "square_trials",
            "rows": DONCHIAN,
            "cols": RSI,
            "row_value": 10,
            "col_value": 7,
        },
    ]
    lab_cache.evict((("exp", experiment_id),))
    assert c.get(f"{LAB}/exp:{experiment_id}/summary").status_code == 200
    allowed = [sources.COLUMNS_FOR("summary", None, meta.parameters, meta.objective)]
    for query in queries:
        lab_cache.evict((("exp", experiment_id),))  # every view a miss, so each one reads
        body = {**base, **query}
        response = c.post(url, json=body)
        assert response.status_code == 200, (query, response.text)
        request = api.QueryRequest.model_validate(body)
        allowed.append(sources.COLUMNS_FOR(query["view"], request, meta.parameters, meta.objective))
    assert len(recorded) == 10
    for columns, permitted in zip(recorded, allowed, strict=True):
        assert columns is not None and set(columns) <= set(permitted), (columns, permitted)
    assert set(recorded[1]) == {"trial_no", "block", "status", "param_key", RSI}
    assert all(len(columns) < 25 for columns in recorded)  # never the 50+ columns of a trial
    page = {**base, "view": "page"}  # square_trials loads the page's columns: evict it first
    lab_cache.evict((("exp", experiment_id),))
    assert c.post(url, json=page).status_code == 200
    assert len(recorded) == 11
    hits = lab_cache.stats()["hits"]
    assert c.post(url, json=page).status_code == 200  # the same snapshot and columns: a hit
    assert len(recorded) == 11 and lab_cache.stats()["hits"] > hits
    assert all(trial_no is None for trial_no, _ in one_trial)
    # The trial route reads one trial through the store's predicate, never through the cache.
    cached = lab_cache.stats()["entries"]
    trial = c.get(f"{LAB}/exp:{experiment_id}/trials/exp%3A{experiment_id}%232")
    assert trial.status_code == 200 and trial.json()["trial_no"] == 2
    assert len(recorded) == 12 and lab_cache.stats()["entries"] == cached
    assert one_trial[-1][0] == 2 and one_trial[-1][1] <= 2  # its canonical row(s) only
    trial_columns = sources.COLUMNS_FOR("trial", None, meta.parameters, meta.objective)
    assert set(recorded[-1]) <= set(trial_columns)
    # Every cached table and unique count names this instance of the experiment: its document's
    # creation stamp follows the source tuple in the key.
    keys = [
        key
        for key in lab_cache._entries
        if key[0] in (("exp", experiment_id), ("exp-unique", experiment_id))
    ]
    assert {key[0][0] for key in keys} == {"exp", "exp-unique"}
    assert all(key[1] == document.created_at for key in keys)
    # The same id created again (a later created_at) never meets the earlier tables.
    store = experiments_module.ExperimentStore(repository)
    store.save(
        store.get(experiment_id).model_copy(update={"created_at": "2099-01-01T00:00:00+00:00"})
    )
    assert c.post(url, json=page).status_code == 200
    assert len(recorded) == 13 and one_trial[-1] == (None, 4)
    # Phase 3 Task 6: the importance task's three views load BASE, design, pass, every parameter
    # and the metric column of the scope, whatever the filter names; the task reads the route's
    # table (a K = 0 experiment's every-block rows are its block-0 rows), so one read each.
    tasks = _tasks()
    task_columns = {*sources.BASE, "design", "pass", DONCHIAN, RSI, "combined.net_pnl"}
    for view in ("importance", "interactions", "triples"):
        lab_cache.evict((("exp", experiment_id),))
        before = len(recorded)
        body = {**base, "view": view}
        response = c.post(url, json=body)
        assert response.status_code == 200, (view, response.text)
        assert tasks.wait(response.json()["task"]["id"], WAIT_S).state == "done"
        request = api.QueryRequest.model_validate(body)
        allowed = sources.COLUMNS_FOR(view, request, meta.parameters, meta.objective)
        assert set(allowed) == task_columns
        assert len(recorded) == before + 1 and set(recorded[-1]) == task_columns, view
    # Phase 3 Task 7: the two robustness views load BASE, design, pass, every parameter with its
    # stored position (`index.codes_for` checks one against the other) and the metric column, one
    # read each; a K = 0 experiment's card reads no block rows.
    hood_columns = {*task_columns, "pos.0", "pos.1"}
    trial = f"exp:{experiment_id}#0"
    for query in (
        {"view": "neighbourhood", "trial": trial},
        {"view": "robustness"},
        {"view": "robustness", "trial": trial},
    ):
        lab_cache.evict((("exp", experiment_id),))
        before = len(recorded)
        body = {**base, **query}
        response = c.post(url, json=body)
        assert response.status_code == 200, (query, response.text)
        request = api.QueryRequest.model_validate(body)
        allowed = sources.COLUMNS_FOR(query["view"], request, meta.parameters, meta.objective)
        assert set(allowed) == hood_columns
        assert len(recorded) == before + 1 and set(recorded[-1]) == hood_columns, query
    # Phase 3 Task 8: Pareto loads BASE, the filter's paths, its objectives and the metric the
    # scope's `undefined` counts; the exact sample what the bundles load; convergence what a
    # neighbourhood loads, so the two share one table.
    pareto_columns = {*sources.BASE, RSI, "combined.net_pnl", "combined.max_drawdown"}
    for query, expected in (
        ({"view": "pareto", "objectives": ["net_pnl", "max_drawdown"]}, pareto_columns),
        (
            {"view": "pareto", "objectives": ["cagr", "mar", "exposure"], "metric": "win_rate"},
            {
                *sources.BASE,
                RSI,
                "combined.cagr",
                "combined.mar",
                "combined.exposure",
                "combined.win_rate",
            },
        ),
        (
            {"view": "parallel", "parallel_mode": "sample", "axes": [DONCHIAN], "metric": "mar"},
            {*sources.BASE, RSI, DONCHIAN, "combined.mar"},
        ),
        ({"view": "convergence"}, hood_columns),
        (
            {"view": "convergence", "metric": "mar"},
            (hood_columns - {"combined.net_pnl"}) | {"combined.mar"},
        ),
    ):
        lab_cache.evict((("exp", experiment_id),))
        before = len(recorded)
        body = {**base, **query}
        response = c.post(url, json=body)
        assert response.status_code == 200, (query, response.text)
        request = api.QueryRequest.model_validate(body)
        allowed = sources.COLUMNS_FOR(query["view"], request, meta.parameters, meta.objective)
        assert set(allowed) == expected
        assert len(recorded) == before + 1 and set(recorded[-1]) == expected, query


def test_trial_no_round_trips_with_a_warmup_skip(client, monkeypatch):
    c, _, _ = client
    surface = {
        "parameters": [
            {"path": RSI, "start": 7, "stop": 14, "step": 7},
            {"path": DONCHIAN, "start": 10, "stop": 60, "step": 50},  # 60 > the 52 bars
        ]
    }
    experiment_id = _finished_experiment(c, monkeypatch, name="warm-up skips", surface=surface)
    plan = c.get(f"/aegis/api/experiments/{experiment_id}").json()["plan"]
    assert plan["mode"] == "exhaustive" and plan["skip_reasons"] == {"insufficient bars": 2}
    summary = c.get(f"{LAB}/exp:{experiment_id}/summary").json()
    assert summary["counts"]["valid"] == plan["valid_cells"] == 2
    assert summary["counts"]["scheduled"] == plan["valid_cells"]
    assert summary["counts"]["space"] == plan["grid_cells"] == 4
    assert summary["counts"]["completed"] == 2 and summary["counts"]["pending"] == 0
    page = c.post(
        f"{LAB}/exp:{experiment_id}/query",
        json={"filter": {}, "view": "page", "sort": "trial_no"},
    ).json()
    assert [row["trial_no"] for row in page["rows"]] == [0, 1]
    assert [row["cell"] for row in page["rows"]] == [0, 2]  # a skipped cell has no trial number
    for row in page["rows"]:
        trial = c.get(_trial_url(f"exp:{experiment_id}", row["trial_id"]))
        assert trial.status_code == 200, trial.text
        assert trial.json()["trial_no"] == row["trial_no"] and trial.json()["cell"] == row["cell"]


def test_build_route_warns_below_10gb(client, monkeypatch):
    c, _, _ = client
    total = 500 * 1024**3

    def usage(free_gb):
        free = free_gb * 1024**3
        return lambda path: SimpleNamespace(total=total, used=total - free, free=free)

    monkeypatch.setattr(shutil, "disk_usage", usage(9))
    low = c.get(f"{LAB}/build")
    assert low.status_code == 200, low.text
    assert low.json()["disk"]["low"] is True and low.json()["disk"]["free_gb"] == 9.0
    assert low.json()["disk"]["root"] == str(aegis_data_root())
    monkeypatch.setattr(shutil, "disk_usage", usage(50))
    high = c.get(f"{LAB}/build").json()
    assert high["disk"]["low"] is False and high["disk"]["free_gb"] == 50.0


def test_trial_route_round_trips_the_id(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    document = c.get(f"/aegis/api/experiments/{experiment_id}").json()
    response = c.get(f"{LAB}/exp:{experiment_id}/trials/exp%3A{experiment_id}%232")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trial_id"] == f"exp:{experiment_id}#2" and body["trial_no"] == 2
    assert (body["status"], body["block"], body["attempt"]) == ("ok", 0, 0)
    assert (body["pass"], body["design"]) == ("grid", "uniform")
    assert set(body["params"]) == {DONCHIAN, RSI} and len(body["pos"]) == 2
    assert HEX32.fullmatch(body["param_key"])
    assert body["finished_at"] is not None and body["chunk"] is not None
    for scope in SCOPES:
        metrics = body["metrics"][scope]
        assert set(metrics) == {*METRICS, "sharpe_trade", "low_n"}
        assert metrics["low_n"] == (metrics["trade_count"] < 20)
    expected = identity.inputs_key(
        document["strategy_hash"],
        document["data_pinned"],
        document["settings"],
        document["versions"]["engine_build"],
    )
    assert HEX32.fullmatch(body["identity"]["inputs_key"])
    assert body["identity"]["inputs_key"] == expected
    assert body["identity"]["strategy_hash"] == document["strategy_hash"]
    assert body["identity"]["data_pinned"] == document["data_pinned"]
    foreign = c.get(f"{LAB}/exp:{experiment_id}/trials/exp%3Aanother%232")
    assert foreign.status_code == 422, foreign.text
    other_kind = c.get(f"{LAB}/exp:{experiment_id}/trials/opt%3A{experiment_id}%232")
    assert other_kind.status_code == 422
    malformed = c.get(f"{LAB}/exp:{experiment_id}/trials/exp%3A{experiment_id}%23two")
    assert malformed.status_code == 422
    missing = c.get(f"{LAB}/exp:{experiment_id}/trials/exp%3A{experiment_id}%2399")
    assert missing.status_code == 404, missing.text


def test_running_experiment_is_provisional(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    gate = threading.Event()
    _runner(repository, after_unit=lambda done: gate.wait(10))
    try:
        created = c.post("/aegis/api/experiments", json=_experiment_body(c, name="held"))
        assert created.status_code == 202, created.text
        experiment_id = created.json()["experiment_id"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:  # the one unit is committed and saved, then held
            held = c.get(f"/aegis/api/experiments/{experiment_id}").json()
            if held["status"] == "running" and held["progress"]["cells_done"] == 4:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the experiment never reached its held unit")
        summary = c.get(f"{LAB}/exp:{experiment_id}/summary")
        assert summary.status_code == 200, summary.text
        assert summary.json()["provisional"] is True and summary.json()["status"] == "running"
        assert summary.json()["snapshots"]["latest"] is not None
        assert summary.json()["counts"]["completed"] == 4
        counts = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "counts"})
        assert counts.status_code == 200 and counts.json()["provisional"] is True
        held = _view(c, f"exp:{experiment_id}", "convergence")
        assert held["provisional"] is True and len(held["best"]) == 4
    finally:
        gate.set()
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert c.get(f"{LAB}/exp:{experiment_id}/summary").json()["provisional"] is False
    assert _view(c, f"exp:{experiment_id}", "convergence")["provisional"] is False


def test_materialize_matches_lab_page_row(client, monkeypatch):
    """Gate 3 parity (spec:1419): a Lab page row, its materialized run and its trial detail agree
    metric for metric, on the pinned data. A materialized run carries the hash of the spec with
    the trial's parameters applied; the document's `strategy_hash` (the pinned spec's) is the
    trial identity's."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    document = c.get(f"/aegis/api/experiments/{experiment_id}").json()
    spec = ExperimentDocument.model_validate(document).spec
    page = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "page"}).json()
    for row in page["rows"][:2]:
        response = c.post(f"/aegis/api/experiments/{experiment_id}/cells/{row['cell']}/materialize")
        assert response.status_code == 200, response.text
        run = response.json()
        trial = c.get(_trial_url(f"exp:{experiment_id}", row["trial_id"])).json()
        checked = 0
        for name, value in row["values"].items():
            scope, metric = name.split(".", 1)
            if metric not in METRICS:  # sharpe_trade: never in a run's golden-pinned metrics
                continue
            assert _same(value, run["result"][scope]["metrics"][metric]), name
            assert _same(trial["metrics"][scope][metric], value), name
            checked += 1
        assert checked == 4  # net_pnl (the objective), max_drawdown, trade_count, exposure
        assert run["data"]["sha256"] == document["data_pinned"]["sha256"]
        assert run["strategy_hash"] == strategy_hash(apply_params(spec, row["params"]))
        assert trial["identity"]["strategy_hash"] == document["strategy_hash"]
        assert run["cell"] == row["cell"] and trial["params"] == row["params"]


def test_opt_source_summary_matrix_and_page(client):
    c, _, repository = client
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    done = _wait(c, job_id, "done")
    assert done["skipped_cells"] == 0 and done["total_cells"] == len(done["cells"]) == 9
    src = f"opt:{job_id}"
    fast, slow = f"long_side.{done['fast_path']}", f"long_side.{done['slow_path']}"
    response = c.get(f"{LAB}/{src}/summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["kind"] == "opt" and summary["source"] == src and summary["layout"] is None
    assert [entry["path"] for entry in summary["parameters"]] == [fast, slow]
    assert all(entry["tested_per_value"] == [3, 3, 3] for entry in summary["parameters"])
    counts = summary["counts"]
    assert counts["space"] == done["total_cells"] and counts["completed"] == 9
    assert counts["block"] == 0 and counts["unique"] == 9
    assert summary["spec_values"] is None and summary["snapshots"]["latest"] is None
    assert summary["provisional"] is False and summary["status"] == "done"
    best = summary["headline"]["best"]
    assert best is not None and best["trial_id"].startswith(f"opt:{job_id}#")
    assert best["value"] == max(cell["metrics"]["net_pnl"] for cell in done["cells"])
    url = f"{LAB}/{src}/query"
    matrix = c.post(
        url,
        json={
            "filter": {"scope": "long"},
            "view": "matrix",
            "rows": fast,
            "cols": slow,
            "metric": "net_pnl",
        },
    )
    assert matrix.status_code == 200, matrix.text
    reference = c.get(
        f"/aegis/api/optimize/{job_id}/matrix",
        params={"rows": done["fast_path"], "cols": done["slow_path"], "metric": "net_pnl"},
    ).json()
    assert matrix.json()["values"] == reference["metrics"]["net_pnl"]["values"]
    assert matrix.json()["counts"] == reference["counts"]
    assert (matrix.json()["rows"], matrix.json()["cols"]) == (reference["rows"], reference["cols"])
    assert matrix.json()["snapshot"] is None
    page = c.post(url, json={"filter": {"scope": "long"}, "view": "page", "limit": 9}).json()
    cells = repository.get_optimization(job_id)["cells"]
    assert page["total"] == 9 and len(page["rows"]) == 9
    for row in page["rows"]:
        k = row["trial_no"]
        assert row["trial_id"] == f"opt:{job_id}#{k}" and row["cell"] == k
        assert row["params"] == {f"long_side.{p}": v for p, v in cells[k]["params"].items()}
        assert row["values"]["long.net_pnl"] == cells[k]["metrics"]["net_pnl"]
    trial = c.get(_trial_url(src, f"{src}#4"))
    assert trial.status_code == 200, trial.text
    assert trial.json()["trial_no"] == 4 and trial.json()["identity"]["inputs_key"] is None
    assert trial.json()["metrics"]["long"]["net_pnl"] == cells[4]["metrics"]["net_pnl"]
    for scope in ("short", "combined"):
        refused = c.post(url, json={"filter": {"scope": scope}, "view": "counts"})
        assert refused.status_code == 422
        assert refused.json()["detail"] == "an optimizer source has one side"


def test_bad_and_unknown_sources(client):
    c, _, _ = client
    assert c.get(f"{LAB}/nonsense/summary").status_code == 422
    assert c.get(f"{LAB}/run:abc/summary").status_code == 422
    assert c.get(f"{LAB}/exp:.hidden/summary").status_code == 422
    assert c.get(f"{LAB}/exp:missing/summary").status_code == 404
    assert c.get(f"{LAB}/opt:missing/summary").status_code == 404
    query = {"filter": {}, "view": "counts"}
    assert c.post(f"{LAB}/nonsense/query", json=query).status_code == 422
    assert c.post(f"{LAB}/exp:missing/query", json=query).status_code == 404
    assert c.get(_trial_url("exp:missing", "exp:missing#0")).status_code == 404


def test_expired_snapshot_answers_409(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)

    def raiser(*args, **kwargs):
        raise lab_store_module.SnapshotExpired("part-1.parquet of generation 1 is gone")

    # Before any Lab request on this experiment: a cached table would answer without a read.
    monkeypatch.setattr(lab_store_module, "read_trials", raiser)
    response = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "counts"})
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "snapshot expired"}
    assert lab_store_module.REGISTRY.held(experiment_id) == set()
    assert c.get(f"{LAB}/exp:{experiment_id}/summary").status_code == 409
    trial = c.get(_trial_url(f"exp:{experiment_id}", f"exp:{experiment_id}#0"))
    assert trial.status_code == 409
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_build_route(client, lab_cache):
    c, _, _ = client
    response = c.get(f"{LAB}/build")
    assert response.status_code == 200, response.text
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{64}", body["engine_build"])
    assert body["engine_build"] == identity.engine_build() == body["versions"]["engine_build"]
    assert body["versions"]["strategy_hash"] == ""
    assert Path(body["app_root"]).name == "app"
    assert body["data_root"] == str(aegis_data_root())
    assert body["cache"] == lab_cache.stats()
    assert set(body["disk"]) == {"free_gb", "low", "root"}


# --- Phase 3 Task 0: one cache entry per column set, the matrix payload, the summary's counts ---


def _open(repository, cache: LabCache, experiment_id: str, columns):
    """One request's frame over `columns`, its registry hold released at once."""
    store = experiments_module.ExperimentStore(repository)
    document = store.get(experiment_id)
    frame, handle = sources.open_experiment(document, store, cache, columns)
    lab_store_module.REGISTRY.release(handle)
    return document, frame


def test_cache_key_is_the_column_set(client, lab_cache, monkeypatch):
    """Two projections of the same columns in different orders share one cache entry (the key
    is the sorted column set beside the row selection, Ruling P1), and each request's table
    follows its own order without a copy."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    meta = sources.experiment_meta(document)
    columns = sources.COLUMNS_FOR("summary", None, meta.parameters, meta.objective)
    reordered = (*reversed(columns[4:]), *columns[:4])
    assert reordered != columns and set(reordered) == set(columns)
    lab_cache.evict((("exp", experiment_id),))
    _, first = _open(repository, lab_cache, experiment_id, columns)
    _, second = _open(repository, lab_cache, experiment_id, reordered)
    assert first.table.column_names == list(columns)
    assert second.table.column_names == list(reordered)
    keys = [key for key in lab_cache._entries if key[0] == ("exp", experiment_id)]
    assert len(keys) == 1, keys
    (key,) = keys
    assert key[-1] == tuple(sorted(columns)) and key[-2] == sources.BLOCK0
    assert lab_cache.stats()["hits"] >= 1
    for name in columns:  # the same buffers, selected in another order
        a, b = first.table.column(name).chunk(0), second.table.column(name).chunk(0)
        assert [x.address for x in a.buffers() if x] == [y.address for y in b.buffers() if y]


def test_stat_change_is_served_from_the_matrix_payload(client, lab_cache, monkeypatch):
    """An aggregate matrix computes its four stats once per (source, snapshot, filter, axes,
    metric, slice): `median` after `best` answers from the cached payload, equal to its own
    computation, and the client's `filter_hash` is still echoed as sent."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    calls: list[str] = []
    original = sources.matrix_view

    def spy(*args, **kwargs):
        calls.append(kwargs.get("stat"))
        return original(*args, **kwargs)

    monkeypatch.setattr(sources, "matrix_view", spy)
    url = f"{LAB}/exp:{experiment_id}/query"
    body = {
        "filter": {},
        "view": "matrix",
        "rows": DONCHIAN,
        "cols": RSI,
        "metric": "net_pnl",
        "mode": "aggregate",
    }
    answers = {}
    for stat, filter_hash in (("best", "aa01"), ("median", "bb02"), ("worst", None)):
        response = c.post(url, json={**body, "stat": stat, "filter_hash": filter_hash})
        assert response.status_code == 200, response.text
        answers[stat] = response.json()
        assert answers[stat]["filter_hash"] == filter_hash
    assert calls == ["best"]
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    meta = sources.experiment_meta(document)
    request = api.QueryRequest.model_validate({**body, "stat": "median"})
    columns = sources.COLUMNS_FOR("matrix", request, meta.parameters, meta.objective)
    _, frame = _open(repository, LabCache(), experiment_id, columns)
    for stat, answer in answers.items():
        own = original(
            frame,
            request.filter,
            rows=DONCHIAN,
            cols=RSI,
            metric="net_pnl",
            mode="aggregate",
            stat=stat,
        )
        assert {key: answer[key] for key in own} == own
        assert "values_by_stat" not in answer
    other = c.post(url, json={**body, "filter": {"ranges": {RSI: [7, 7]}}, "stat": "median"})
    assert other.status_code == 200 and calls == ["best", "median"]  # another filter: computed


def test_matrix_payload_never_crosses_sources(client, lab_cache, monkeypatch):
    """Two experiments at the same snapshot numbers and filter each answer their own matrix,
    each from its own cache entry."""
    c, _, repository = client
    first = _finished_experiment(c, monkeypatch, name="first")
    surface = {
        "parameters": [
            {"path": DONCHIAN, "start": 10, "stop": 20, "step": 10},
            {"path": RSI, "start": 7, "stop": 14, "step": 7},
        ]
    }
    second = _finished_experiment(c, monkeypatch, name="second", surface=surface)
    calls: list[str] = []
    original = sources.matrix_view

    def spy(*args, **kwargs):
        calls.append(args[0].source)
        return original(*args, **kwargs)

    monkeypatch.setattr(sources, "matrix_view", spy)
    body = {
        "filter": {},
        "view": "matrix",
        "rows": DONCHIAN,
        "cols": RSI,
        "metric": "net_pnl",
        "mode": "aggregate",
    }
    answers: dict[str, dict] = {}
    for _ in range(2):
        for experiment_id in (first, second):
            response = c.post(f"{LAB}/exp:{experiment_id}/query", json=body)
            assert response.status_code == 200, response.text
            answer = response.json()
            assert answer["snapshot"] == {"generation": 1, "chunk_watermark": 1}
            assert answers.setdefault(experiment_id, answer) == answer
    assert calls == [f"exp:{first}", f"exp:{second}"]  # each computed once, never the other's
    assert answers[first]["rows"] == [10.0, 15.0] and answers[second]["rows"] == [10.0, 20.0]
    request = api.QueryRequest.model_validate(body)
    for experiment_id in (first, second):
        document = experiments_module.ExperimentStore(repository).get(experiment_id)
        meta = sources.experiment_meta(document)
        columns = sources.COLUMNS_FOR("matrix", request, meta.parameters, meta.objective)
        _, frame = _open(repository, LabCache(), experiment_id, columns)
        own = original(
            frame, request.filter, rows=DONCHIAN, cols=RSI, metric="net_pnl", mode="aggregate"
        )
        assert {key: answers[experiment_id][key] for key in own} == own


def test_summary_tested_per_value_equals_marginals_n(client, monkeypatch):
    """The summary counts each value's tested trials from the index's codes, one count per
    parameter and never the marginals' grouping of the metric, equal to the marginals' `n`; a
    lattice over MARGINAL_BUCKETS values keeps its buckets."""
    from products.aegis.lab import query as query_module
    from products.aegis.lab.index import build_index
    from products.aegis.lab.query import LabFilter, marginals_view
    from test_lab_query import frame_of, metrics

    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    counted: list[str] = []
    grouped: list[int] = []
    tested, groups = sources.tested_per_value, query_module._Groups

    def count(frame, parameter, members, index):
        counted.append(parameter.path)
        return tested(frame, parameter, members, index)

    class Groups(groups):  # the marginals' (and the matrix's) sort of the metric by group
        def __init__(self, *args, **kwargs):
            grouped.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(sources, "tested_per_value", count)
    monkeypatch.setattr(query_module, "_Groups", Groups)
    summary = c.get(f"{LAB}/exp:{experiment_id}/summary")
    assert summary.status_code == 200, summary.text
    assert counted == [DONCHIAN, RSI] and grouped == []
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    meta = sources.experiment_meta(document)
    columns = sources.COLUMNS_FOR("summary", None, meta.parameters, meta.objective)
    _, frame = _open(repository, LabCache(), experiment_id, columns)
    marginals = marginals_view(frame, LabFilter(), metric="net_pnl")["marginals"]
    assert grouped  # the spy sees a grouping: the summary's empty list is not vacuous
    for entry in summary.json()["parameters"]:
        assert entry["tested_per_value"] == marginals[entry["path"]]["n"]
        assert entry["values"] == marginals[entry["path"]]["values"]
    fine, coarse = "long_side.indicators.fine.length", "short_side.indicators.coarse.length"
    rows = [
        {
            "params": {fine: 1.0 + (7 * t) % 300, coarse: 2.0 * (t % 16)},
            "metrics": metrics(net_pnl=float(t % 9)),
            "status": "failed" if t % 11 == 0 else "ok",
        }
        for t in range(900)
    ]
    hand = frame_of(rows, (fine, coarse), values={fine: [1.0 + v for v in range(300)]})
    status = {"side": "long", "status": "done", "data": None, "engine": None}
    built = sources.summary(hand, None, status, None, index=build_index(hand))
    expected = marginals_view(hand, LabFilter(scope="long"), metric="net_pnl")["marginals"]
    by_path = {entry["path"]: entry for entry in built["parameters"]}
    assert by_path[fine]["bucketed"] is True and by_path[fine]["values"] is None
    assert by_path[coarse]["bucketed"] is False
    for path in (fine, coarse):
        assert by_path[path]["tested_per_value"] == expected[path]["n"]


def test_memory_released_after_a_load(monkeypatch):
    """A miss that loads Arrow memory (a table, an index: `release=True`) hands what Arrow freed
    while loading back to the system, and so does an eviction; a hit releases nothing."""
    import pyarrow as pa
    from products.aegis.lab import cache as cache_module

    released: list[str] = []

    class Pool:
        def release_unused(self) -> None:
            released.append("released")

    monkeypatch.setattr(cache_module.pa, "default_memory_pool", lambda: Pool())
    cache = LabCache(10_000)

    def table(rows: int):
        return lambda: pa.table({"x": list(range(rows))})

    cache.get(("a",), table(500), size=lambda t: t.nbytes, release=True)  # 4,000 bytes: a miss
    assert released == ["released"]
    cache.get(("a",), table(500), size=lambda t: t.nbytes, release=True)  # a hit
    assert released == ["released"]
    cache.get(("b",), table(1000), size=lambda t: t.nbytes, release=True)  # a miss evicting a
    assert len(released) == 2 and cache.stats()["entries"] == 1
    assert cache.evict(("b",)) == 1 and len(released) == 3


def test_release_only_after_table_and_index_loads(client, lab_cache, monkeypatch):
    """The routes release Arrow's freed memory after loading a table or an index, never after a
    miss that holds no Arrow memory (metadata, `unique`, the summary part, a matrix payload),
    unless that miss evicts."""
    from products.aegis.lab import cache as cache_module

    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    released: list[str] = []
    monkeypatch.setattr(cache_module, "release_unused", lambda: released.append("released"))
    lab_cache.evict((("exp", experiment_id),))
    released.clear()
    url = f"{LAB}/exp:{experiment_id}/query"
    body = {"filter": {}, "view": "matrix", "rows": DONCHIAN, "cols": RSI, "metric": "net_pnl"}
    first = c.post(url, json={**body, "mode": "aggregate"})
    assert first.status_code == 200, first.text
    assert released == ["released", "released"]  # the table, then the index; never the rest
    other = c.post(url, json={**body, "mode": "aggregate", "filter": {"ranges": {RSI: [7, 7]}}})
    assert other.status_code == 200 and released == ["released"] * 2  # a payload-only miss
    plain = LabCache(10_000)
    plain.get(("payload",), lambda: {"values": [1.0]}, size=lambda _: 4_000)
    assert released == ["released"] * 2
    plain.get(("payload", 2), lambda: {"values": [2.0]}, size=lambda _: 8_000)  # evicts one
    assert released == ["released"] * 3


def test_index_only_for_the_views_that_read_it(client, lab_cache, monkeypatch):
    """`top`, `parallel` in either mode and `square_trials` never read the index, so their requests
    never build or fetch it; counts, matrix, page, marginals, pareto, convergence and the summary
    do."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    built: list[str] = []
    original = sources.experiment_index

    def spy(cache, frame, document):
        built.append("index")
        return original(cache, frame, document)

    monkeypatch.setattr(sources, "experiment_index", spy)
    url = f"{LAB}/exp:{experiment_id}/query"
    unread = [
        {"view": "top", "metric": "net_pnl"},
        {"view": "parallel", "axes": [DONCHIAN, RSI], "metric": "net_pnl"},
        {"view": "parallel", "parallel_mode": "sample", "axes": [DONCHIAN], "metric": "net_pnl"},
        {"view": "square_trials", "rows": DONCHIAN, "cols": RSI, "row_value": 10, "col_value": 7},
    ]
    for body in unread:
        response = c.post(url, json={"filter": {}, **body})
        assert response.status_code == 200, (body, response.text)
    assert built == []
    assert not [key for key in lab_cache._entries if key[0] == ("exp-index", experiment_id)]
    read = [
        {"view": "counts"},
        {"view": "matrix", "rows": DONCHIAN, "cols": RSI, "metric": "net_pnl"},
        {"view": "page"},
        {"view": "marginals", "metric": "net_pnl"},
        {"view": "pareto", "objectives": ["net_pnl", "max_drawdown"]},
        {"view": "convergence"},
    ]
    for body in read:
        response = c.post(url, json={"filter": {}, **body})
        assert response.status_code == 200, (body, response.text)
    assert c.get(f"{LAB}/exp:{experiment_id}/summary").status_code == 200
    assert built == ["index"] * 7


# --- Phase 3 Task 6: the staged importance task and the importance, interactions, triples views --

WAIT_S = 30.0  # bounds a hung task; no outcome depends on it
TASK_FIELDS = {
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
}
RUNNING_OPTIMIZATION = "importance is available when the optimization finishes"


def _tasks() -> LabTasks:
    """The test's Lab task executor: the `client` fixture's override."""
    return server.app.dependency_overrides[api.get_lab_tasks]()


def _view(c, src: str, view: str = "importance", **body) -> dict:
    """One answer of a task view, the filter empty unless `body` gives one."""
    response = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": view, **body})
    assert response.status_code == 200, response.text
    return response.json()


def _done(c, src: str, **body) -> dict:
    """The importance view once its task is done (waiting on the executor, never sleeping)."""
    first = _view(c, src, **body)
    finished = _tasks().wait(first["task"]["id"], WAIT_S)
    assert finished.state == "done", finished.error
    return _view(c, src, **body)


def test_importance_view_starts_then_answers(client, monkeypatch):
    """The first poll requests the task (queued, or running or done if it is quick) and answers
    with no result yet; a later poll is `done` with stage 3, the basis line naming n of N, and
    the triple-level arrays left to the triples view. Another seed is another task."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    first = _view(c, src)
    task = first["task"]
    assert set(task) == TASK_FIELDS and HEX32.fullmatch(task["id"])
    assert task["state"] in ("queued", "running", "done") and task["label"] == "importance"
    assert task["stages"] == 3 and first["view"] == "importance" and first["reason"] is None
    assert first["snapshot"] == {"generation": 1, "chunk_watermark": 1}
    assert _tasks().wait(task["id"], WAIT_S).state == "done"
    later = _view(c, src)
    assert later["task"]["id"] == task["id"] and later["task"]["state"] == "done"
    assert later["task"]["progress"] == 1.0 and later["task"]["finished_at"]
    importance = later["importance"]
    assert importance["stage"] == importance["stages"] == 3 and importance["partial"] is False
    assert importance["seed"] == 1 and importance["snapshot"] == later["snapshot"]
    assert importance["paths"] == [DONCHIAN, RSI] and importance["metric"] == "net_pnl"
    assert importance["n"] == importance["N"] == importance["attempted"] == 4
    assert isinstance(importance["elapsed_s"], float)
    assert importance["uncertainty"]["period"] == "not measured: no screening blocks"
    assert [s["label"] for s in importance["statuses"]] == ["Insufficient coverage"] * 2
    assert importance["constants"]["THETA_MIN"] == 0.01
    assert "triples" not in importance["coarse"] and later["snapshot_label"] is None
    scope = later["scope"]
    assert scope["basis"] == (
        "computed on 4 uniform trials of 4; adaptive rows excluded; ignores the active filter"
    )
    assert scope["completed"] == scope["filtered"] == 4 and scope["shown"] == 0
    other = _view(c, src, seed=2)
    assert other["task"]["id"] != task["id"]
    assert _tasks().wait(other["task"]["id"], WAIT_S).result["seed"] == 2
    refused = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": "importance", "seed": -1})
    assert refused.status_code == 422


def test_importance_ignores_the_filter(client, monkeypatch):
    """Importance reads the unfiltered uniform rows (§7.3): the same answer, scope included, with
    and without `filter.ranges`, for each of the three views."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    plain = _done(c, src)
    narrowed = {"ranges": {RSI: [7, 7]}, "pass": ["grid"]}
    assert _view(c, src, filter=narrowed) == plain
    assert plain["scope"]["filters_active"] == 0 and plain["scope"]["filtered"] == 4
    for view in ("interactions", "triples"):
        assert _view(c, src, view, filter=narrowed) == _view(c, src, view)
    unknown = {"ranges": {"long_side.indicators.nope.length": [1, 2]}}
    refused = c.post(f"{LAB}/{src}/query", json={"filter": unknown, "view": "importance"})
    assert refused.status_code == 422 and "unknown path" in refused.json()["detail"]


def test_interactions_and_triples_views_answer_from_the_task(client, monkeypatch):
    """`interactions` and `triples` answer from the importance task's latest stage (the same
    task: no second computation): the experiment's one pair, and no triple at d = 2."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    importance = _done(c, src)
    pairs = _view(c, src, "interactions")
    assert pairs["task"] == importance["task"] and pairs["view"] == "interactions"
    assert [p["pair"] for p in pairs["pairs"]] == [[DONCHIAN, RSI]]
    assert pairs["total_pairs"] == 1 and pairs["scope"]["shown"] == 1
    assert pairs["truncated"] is False and "bounded" not in pairs
    assert pairs["computed"]["stage"] == 3 and pairs["computed"]["seed"] == 1
    assert pairs["constants"] == importance["importance"]["constants"]
    assert pairs["scope"]["basis"] == importance["scope"]["basis"]
    triples = _view(c, src, "triples")
    assert triples["task"] == importance["task"] and triples["triples"] == []
    assert triples["total_triples"] == 0 and triples["scope"]["shown"] == 0
    assert triples["bounded"] is True and "truncated" not in triples


def test_basis_counts_the_scheduled_uniform_configurations(client, monkeypatch):
    """N is the experiment's scheduled uniform configurations, its first pass: every valid cell
    when exhaustive; when sampled, the cells its Latin hypercube drew, or before the draw the
    planned first pass (refinement rows are adaptive)."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    assert document.plan["mode"] == "exhaustive" and sources.scheduled_uniform(document) == 4
    sampled = {**document.plan, "mode": "sampled", "first_pass": 3, "refinement": 1}
    planned = document.model_copy(update={"plan": sampled, "first_pass_cells": None})
    assert sources.scheduled_uniform(planned) == 3
    drawn = planned.model_copy(update={"first_pass_cells": [0, 2], "refinement_cells": [1]})
    assert sources.scheduled_uniform(drawn) == 2


def test_importance_on_an_optimization_grid(client):
    """Review Focus 5: a finished `opt:` grid job gets importance on its exhaustive grid, every
    cell a uniform trial and N its kept cells, with the period uncertainty `not measured: no
    screening blocks` and no snapshot."""
    c, _, _ = client
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    done = _wait(c, job_id, "done")
    src = f"opt:{job_id}"
    answer = _done(c, src, filter={"scope": "long"})
    importance = answer["importance"]
    assert importance["uncertainty"]["period"] == "not measured: no screening blocks"
    assert importance["K"] == 0 and importance["block_range"] is None
    assert importance["n"] == importance["N"] == done["total_cells"] == 9
    assert importance["scope"] == "long" and importance["metric"] == "net_pnl"
    assert importance["stage"] == 3 and importance["snapshot"] is None
    assert answer["snapshot"] is None and answer["provisional"] is False
    assert answer["scope"]["basis"] == (
        "computed on 9 uniform trials of 9; adaptive rows excluded; ignores the active filter"
    )
    fast, slow = f"long_side.{done['fast_path']}", f"long_side.{done['slow_path']}"
    assert importance["paths"] == [fast, slow]
    pairs = _view(c, src, "interactions", filter={"scope": "long"})
    assert [p["pair"] for p in pairs["pairs"]] == [[fast, slow]]
    combined = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": "importance"})
    assert combined.status_code == 422  # an optimizer source has one side


def test_importance_waits_for_a_running_optimization(client, monkeypatch):
    """A running optimization's identity carries its cells done, so every poll would key a new
    task: no task is requested until it finishes; each view answers no task, no result and the
    reason. Once it is done the importance task runs."""
    c, _, repository = client
    gate = threading.Event()
    _runner(repository, after_unit=lambda done: gate.wait(WAIT_S))
    tasks = _tasks()
    requested = []
    original = tasks.request

    def recording(key, *args, **kwargs):
        requested.append(key)
        return original(key, *args, **kwargs)

    monkeypatch.setattr(tasks, "request", recording)
    long = {"filter": {"scope": "long"}}
    try:
        job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
        src = f"opt:{job_id}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            job = c.get(f"/aegis/api/optimize/{job_id}").json()
            if job["status"] == "running" and job["progress"]["done"] >= 1:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("the optimization never reached its held unit")
        for view in ("importance", "importance", "interactions", "triples"):
            answer = _view(c, src, view, **long)
            assert answer["task"] is None and answer["reason"] == RUNNING_OPTIMIZATION, view
            assert answer["provisional"] is True
        assert answer["triples"] == [] and answer["computed"] is None
        assert _view(c, src, **long)["importance"] is None
        assert _view(c, src, rerun=True, **long)["task"] is None  # not even when asked again
        assert requested == []
    finally:
        gate.set()
    done = _wait(c, job_id, "done")
    answer = _done(c, src, **long)
    assert answer["reason"] is None and answer["importance"]["N"] == done["total_cells"]
    assert len(set(requested)) == 1 and requested[0][0] == ("opt", job_id, done["total_cells"])


@pytest.mark.parametrize("how", ["cancel", "fail"])
def test_a_cancelled_or_failed_importance_is_never_restarted_by_a_poll(client, monkeypatch, how):
    """Ruling P13: once the key's newest task was cancelled or failed, polls answer that task and
    request nothing, whatever the executor does meanwhile; only `rerun` requests again."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    tasks = _tasks()
    real = sources.importance_stages
    if how == "cancel":  # held behind another task, then cancelled through the route
        gate, started = threading.Event(), threading.Event()

        def blocker(checkpoint):
            started.set()
            assert gate.wait(WAIT_S)
            checkpoint()
            yield {}

        other = task_key(("opt", "blocker", 0), "importance", "net_pnl", "long", 1)
        tasks.request(other, "blocker", 1, blocker)
        assert started.wait(WAIT_S)
        first = _view(c, src)
        assert first["task"]["state"] == "queued"
        cancel = c.post(f"{LAB}/{src}/tasks/{first['task']['id']}/cancel")
        assert cancel.json() == {"cancelled": True}
        gate.set()
    else:

        def failing(*args, **kwargs):
            raise ValueError("no finite net_pnl")
            yield

        monkeypatch.setattr(sources, "importance_stages", failing)
        first = _view(c, src)
        assert tasks.wait(first["task"]["id"], WAIT_S).state == "failed"
        monkeypatch.setattr(sources, "importance_stages", real)
    ended = "cancelled" if how == "cancel" else "failed"
    for _ in range(2):
        again = _view(c, src)
        assert again["task"]["id"] == first["task"]["id"] and again["task"]["state"] == ended
        assert again["importance"] is None
        assert _view(c, src, "interactions")["task"]["id"] == first["task"]["id"]
    if how == "fail":
        assert "no finite net_pnl" in again["task"]["error"]
    rerun = _view(c, src, rerun=True)
    assert rerun["task"]["id"] != first["task"]["id"]
    assert tasks.wait(rerun["task"]["id"], WAIT_S).state == "done"
    after = _view(c, src)
    assert after["task"]["id"] == rerun["task"]["id"] and after["importance"]["stage"] == 3


def test_importance_beside_a_running_experiment(client, monkeypatch):
    """While the experiment runs, the basis line names the attempted configurations beside the
    scheduled N. Once the source moves on, a poll queues the new snapshot's task and shows the
    newest finished result labelled `snapshot X · current Y`; cancelling that task keeps the
    result and the label, and no poll restarts it. Ruling P14: when a rerun's task has delivered
    its first stage, the view still answers the done result, and its line names that task."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    monkeypatch.setattr(experiments_module, "CHUNK_CELLS", 2)
    c, _, repository = client
    gate, stop, started = threading.Event(), threading.Event(), threading.Event()
    _runner(repository, after_unit=lambda done: gate.wait(WAIT_S))
    tasks = _tasks()
    try:
        created = c.post("/aegis/api/experiments", json=_experiment_body(c, name="held"))
        assert created.status_code == 202, created.text
        experiment_id = created.json()["experiment_id"]
        src = f"exp:{experiment_id}"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:  # the first unit of two cells is committed, then held
            held = c.get(f"/aegis/api/experiments/{experiment_id}").json()
            if held["status"] == "running" and held["progress"]["cells_done"] == 2:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("the experiment never reached its held unit")
        running = _done(c, src)
        computed = running["importance"]
        assert running["provisional"] is True
        assert (computed["n"], computed["attempted"], computed["N"]) == (2, 2, 4)
        assert running["scope"]["basis"] == (
            "computed on 2 uniform trials of 4 (2 attempted); adaptive rows excluded; "
            "ignores the active filter"
        )

        def blocker(checkpoint):
            started.set()
            assert stop.wait(WAIT_S)
            checkpoint()
            yield {}

        tasks.request(task_key(("opt", "blocker", 0), "x", "net_pnl", "long", 1), "x", 1, blocker)
        assert started.wait(WAIT_S)
    finally:
        gate.set()
    try:
        finished = _wait_experiment(c, experiment_id, ("done", "failed"))
        assert finished["status"] == "done", finished.get("error")
        moved = _view(c, src)
        assert moved["task"]["id"] != running["task"]["id"]
        assert moved["task"]["state"] == "queued"
        assert moved["importance"] == computed  # the newest finished result, not current
        was, now = computed["snapshot"], moved["snapshot"]
        assert was != now
        label = (
            f"snapshot g{was['generation']} c{was['chunk_watermark']} · "
            f"current g{now['generation']} c{now['chunk_watermark']}"
        )
        assert moved["snapshot_label"] == label
        cancel = c.post(f"{LAB}/{src}/tasks/{moved['task']['id']}/cancel")
        assert cancel.json() == {"cancelled": True}
    finally:
        stop.set()
    for _ in range(2):
        again = _view(c, src)
        assert again["task"]["id"] == moved["task"]["id"]
        assert again["task"]["state"] == "cancelled"
        assert again["importance"] == computed and again["snapshot_label"] == label
    delivered, proceed = threading.Event(), threading.Event()
    real = sources.importance_stages

    def held(frame, **kwargs):
        stages = real(frame, **kwargs)
        yield next(stages)
        delivered.set()
        assert proceed.wait(WAIT_S)
        yield from stages

    monkeypatch.setattr(sources, "importance_stages", held)
    whole = _view(c, src, rerun=True)
    try:
        assert delivered.wait(WAIT_S)
        computing = _view(c, src)
        assert computing["task"]["id"] == whole["task"]["id"]
        assert computing["task"]["state"] == "running" and computing["task"]["stage"] == 1
        assert computing["importance"] == computed and computing["snapshot_label"] == label
    finally:
        proceed.set()
    assert tasks.wait(whole["task"]["id"], WAIT_S).state == "done"
    current = _view(c, src)
    assert current["importance"]["n"] == current["importance"]["N"] == 4
    assert current["snapshot_label"] is None


def test_a_task_view_never_waits_for_the_runner_under_the_read_lock(client, monkeypatch):
    """The job holds the runner's lock while it takes the experiment's write lock (`finalize`
    compacts), so a route that waited for the runner under the read lock could deadlock with it:
    every read of `sharing_cpu` during a task view happens outside the read lock, the newest task
    still queued or running."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    reads, under_the_lock = [], []

    def probe(runner) -> bool:
        reads.append(1)
        if threading.get_ident() in lab_store_module.LOCKS._lock(experiment_id).readers:
            under_the_lock.append(1)
        return False

    monkeypatch.setattr(api, "_sharing_cpu", probe)
    tasks = _tasks()
    gate, started = threading.Event(), threading.Event()

    def blocker(checkpoint):
        started.set()
        assert gate.wait(WAIT_S)
        checkpoint()
        yield {}

    tasks.request(task_key(("opt", "blocker", 0), "x", "net_pnl", "long", 1), "x", 1, blocker)
    assert started.wait(WAIT_S)
    try:
        for _ in range(2):  # the second finds its key's newest task live
            assert _view(c, src)["task"]["state"] == "queued"
        assert reads and under_the_lock == []
    finally:
        gate.set()


def test_a_cancelled_task_keeps_its_stages_readable(client, monkeypatch):
    """Review Focus 3, with the real stages: cancelled in the middle of stage 3, the stages
    delivered stay readable and partial, no half-computed interval shows, its frame's handle and
    its pin are released, polls never restart it and `rerun` computes the whole again."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    tasks = _tasks()
    delivered, cancelled = threading.Event(), threading.Event()
    real = sources.importance_stages

    def held(frame, **kwargs):
        stages = real(frame, **kwargs)
        yield next(stages)
        yield next(stages)
        delivered.set()  # the executor asked for more: stage 2 is in the task's status
        assert cancelled.wait(WAIT_S)
        yield from stages  # its next checkpoint stops it

    monkeypatch.setattr(sources, "importance_stages", held)
    first = _view(c, src)
    assert delivered.wait(WAIT_S)
    running = _view(c, src)
    assert running["task"]["id"] == first["task"]["id"]
    assert running["task"]["state"] == "running" and running["task"]["stage"] == 2
    assert running["importance"]["stage"] == 2 and running["importance"]["partial"] is True
    cancel = c.post(f"{LAB}/{src}/tasks/{first['task']['id']}/cancel")
    assert cancel.json() == {"cancelled": True}
    stopping = _view(c, src)  # before its next checkpoint: still running, and never restarted
    assert stopping["task"]["id"] == first["task"]["id"] and stopping["task"]["state"] == "running"
    cancelled.set()
    assert tasks.wait(first["task"]["id"], WAIT_S).state == "cancelled"
    assert lab_store_module.REGISTRY.held(experiment_id) == set()
    monkeypatch.setattr(sources, "importance_stages", real)
    for _ in range(2):
        again = _view(c, src)
        assert again["task"]["id"] == first["task"]["id"]
        assert again["task"]["state"] == "cancelled" and again["task"]["stage"] == 2
        kept = again["importance"]
        assert kept["stage"] == 2 and kept["partial"] is True
        assert kept["coarse_bounds"] is None and kept["coarse"]["lo"] is None
    pairs = _view(c, src, "interactions")
    assert pairs["computed"]["stage"] == 2 and pairs["computed"]["partial"] is True
    assert pairs["total_pairs"] == 1
    rerun = _view(c, src, rerun=True)
    assert rerun["task"]["id"] != first["task"]["id"]
    assert tasks.wait(rerun["task"]["id"], WAIT_S).state == "done"
    assert _view(c, src)["importance"]["stage"] == 3


def test_importance_reads_every_block_of_a_screened_experiment(
    client, lab_cache, monkeypatch, tmp_path
):
    """A task view starts the task whichever view asks first. On a screened experiment the task
    reads every block under its own cache entry, the route's scope stays block 0's and the
    snapshot's ordinary views are untouched; the answer echoes the filter hash and no handle is
    left behind."""
    c, _, _ = client
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0, missing=290)
    experiment_id = _finished_experiment(
        c,
        monkeypatch,
        name="screened",
        data={"symbol": "SPY", "timeframe": "1m", **RANGE},
        blocks=2,
    )
    src = f"exp:{experiment_id}"
    first = _view(c, src, "triples", filter_hash="cafe0001")
    assert first["filter_hash"] == "cafe0001" and first["task"]["label"] == "importance"
    assert first["computed"] is None and first["triples"] == []
    assert first["scope"]["basis"] == "importance not computed yet; ignores the active filter"
    assert _tasks().wait(first["task"]["id"], WAIT_S).state == "done"
    answer = _view(c, src, filter_hash="cafe0002")
    assert answer["filter_hash"] == "cafe0002" and answer["task"]["id"] == first["task"]["id"]
    importance = answer["importance"]
    assert importance["K"] == 2 and sorted(importance["blocks"]) == ["1", "2"]
    assert importance["n"] == importance["N"] == importance["attempted"] == 4
    assert importance["uncertainty"]["period"] == "block range over 2 screening blocks"
    for k, found in enumerate(importance["block_range"]):  # None where no block measured it
        shares = [importance["blocks"][b]["S"][k] for b in ("1", "2")]
        measured = [share for share in shares if share is not None]
        assert found == ([min(measured), max(measured)] if measured else None)
    scope = answer["scope"]
    assert scope["block"] == 0 and scope["attempted"] == 4 and scope["evaluations_done"] == 12
    selections = {key[4] for key in lab_cache._entries if key[0] == ("exp", experiment_id)}
    assert selections == {sources.BLOCK0, sources.ALL_BLOCKS}
    counts = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": "counts"}).json()
    assert counts["scope"]["attempted"] == 4 and counts["scope"]["filtered"] == 4
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_a_failed_importance_on_an_optimization_is_not_restarted(client, monkeypatch):
    """Ruling P13 on an `opt:` source: a finished job's identity is stable, so its failed task
    stands through polls until `rerun`."""
    c, _, _ = client
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, job_id, "done")
    src = f"opt:{job_id}"
    long = {"filter": {"scope": "long"}}
    tasks = _tasks()
    real = sources.importance_stages

    def failing(*args, **kwargs):
        raise ValueError("no finite net_pnl")
        yield

    monkeypatch.setattr(sources, "importance_stages", failing)
    first = _view(c, src, **long)
    assert tasks.wait(first["task"]["id"], WAIT_S).state == "failed"
    monkeypatch.setattr(sources, "importance_stages", real)
    for _ in range(2):
        again = _view(c, src, **long)
        assert again["task"]["id"] == first["task"]["id"] and again["task"]["state"] == "failed"
        assert "no finite net_pnl" in again["task"]["error"] and again["importance"] is None
    rerun = _view(c, src, rerun=True, **long)
    assert rerun["task"]["id"] != first["task"]["id"]
    assert tasks.wait(rerun["task"]["id"], WAIT_S).state == "done"
    assert _view(c, src, **long)["importance"]["stage"] == 3


def _held_experiment(c, gate_of: threading.Event, repository, name: str = "held") -> str:
    """An experiment of two chunks of two, its job held after the first: the job's next chunk
    arrives once the test sets `gate_of`."""
    _runner(repository, after_unit=lambda done: gate_of.wait(WAIT_S))
    created = c.post("/aegis/api/experiments", json=_experiment_body(c, name=name))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        held = c.get(f"/aegis/api/experiments/{experiment_id}").json()
        if held["status"] == "running" and held["progress"]["cells_done"] == 2:
            return experiment_id
        time.sleep(0.05)
    raise AssertionError("the experiment never reached its held unit")


def test_task_status_route_reads_a_running_then_a_done_task(client, monkeypatch):
    """Ruling P21: `GET /lab/{src}/tasks/{task_id}` is the read-only status of one task, the
    `task` field of a view built the same way. Held after stage 1 of the real stages it reads
    `running` at stage 1; once released, `done` at stage 3 with its finish time."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    delivered, proceed = threading.Event(), threading.Event()
    real = sources.importance_stages

    def held(frame, **kwargs):
        stages = real(frame, **kwargs)
        yield next(stages)
        delivered.set()  # the executor asked for more: stage 1 is in the task's status
        assert proceed.wait(WAIT_S)
        yield from stages

    monkeypatch.setattr(sources, "importance_stages", held)
    task_id = _view(c, src)["task"]["id"]
    assert delivered.wait(WAIT_S)
    url = f"{LAB}/{src}/tasks/{task_id}"
    running = c.get(url)
    assert running.status_code == 200, running.text
    body = running.json()
    assert set(body) == TASK_FIELDS and body["id"] == task_id and body["label"] == "importance"
    assert body["state"] == "running" and body["stage"] == 1 and body["stages"] == 3
    assert body["finished_at"] is None and body["started_at"]
    assert body == _view(c, src)["task"]  # the field a view carries, built the same way
    proceed.set()
    assert _tasks().wait(task_id, WAIT_S).state == "done"
    done = c.get(url)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["state"] == "done" and body["stage"] == 3 and body["progress"] == 1.0
    assert body["finished_at"] and body["error"] is None
    assert body == _view(c, src)["task"]


def test_task_status_route_answers_404_for_an_unknown_or_foreign_task(client, monkeypatch):
    """Like the cancel route: 404 for an id this executor does not know and for a task that is
    not this source's (another experiment, another kind, a source that does not exist)."""
    c, _, _ = client
    mine = _finished_experiment(c, monkeypatch)
    other = _finished_experiment(c, monkeypatch, name="another")
    assert other != mine
    task_id = _view(c, f"exp:{mine}")["task"]["id"]
    assert _tasks().wait(task_id, WAIT_S).state == "done"
    unknown = c.get(f"{LAB}/exp:{mine}/tasks/{'0' * 32}")
    assert unknown.status_code == 404, unknown.text
    assert "unknown task" in unknown.json()["detail"]
    for src in (f"exp:{other}", f"opt:{mine}", "exp:missing"):
        assert c.get(f"{LAB}/{src}/tasks/{task_id}").status_code == 404, src
    assert c.get(f"{LAB}/nonsense/tasks/{task_id}").status_code == 422
    assert c.get(f"{LAB}/exp:{mine}/tasks/{task_id}").status_code == 200  # its own source reads it


def test_task_status_route_never_creates_work(client, monkeypatch):
    """The Lab polls this route for a task it left behind, so a read must never create work: a
    spy on `LabTasks.request` is never called, and no frame is opened and no snapshot pinned
    (a view's poll does both, and on a running experiment a poll at a new chunk queues a task)."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    other = _finished_experiment(c, monkeypatch, name="another")
    src = f"exp:{experiment_id}"
    task_id = _view(c, src)["task"]["id"]
    assert _tasks().wait(task_id, WAIT_S).state == "done"
    requests: list[tuple] = []

    def spy(self, *args, **kwargs):
        requests.append(args)
        raise AssertionError("the status route requested a task")

    def refuse(*args, **kwargs):
        raise AssertionError("the status route opened a frame or pinned a snapshot")

    monkeypatch.setattr(LabTasks, "request", spy)
    for name in ("open_experiment", "pin_experiment"):
        monkeypatch.setattr(sources, name, refuse)
    monkeypatch.setattr(api, "_lab_experiment", refuse)
    for _ in range(3):
        assert c.get(f"{LAB}/{src}/tasks/{task_id}").status_code == 200
    assert c.get(f"{LAB}/{src}/tasks/{'0' * 32}").status_code == 404
    assert c.get(f"{LAB}/exp:{other}/tasks/{task_id}").status_code == 404
    assert requests == []
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_cancel_stops_the_key_of_a_running_experiment(client, monkeypatch):
    """Review fixes 1 and 2, the normal state of a running experiment. T1 is held after stage 1
    and a new chunk arrives, so a poll queues T2. Ruling P14: no done result yet, so the view shows
    T1's stage 1 (labelled, its snapshot being older), and its line names T1. A cancel through the
    route stops the key: T1 stops, T2 never runs, its delivered stage stays readable, and polls
    stay stopped until `rerun`."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    monkeypatch.setattr(experiments_module, "CHUNK_CELLS", 2)
    c, _, repository = client
    tasks = _tasks()
    gate, delivered, proceed = threading.Event(), threading.Event(), threading.Event()
    computed = []
    real = sources.importance_stages

    def held(frame, **kwargs):
        computed.append(frame.snapshot)
        stages = real(frame, **kwargs)
        yield next(stages)
        delivered.set()
        assert proceed.wait(WAIT_S)
        yield from stages

    monkeypatch.setattr(sources, "importance_stages", held)
    placed = []
    original = tasks.request

    def recording(*args, **kwargs):
        placed.append(original(*args, **kwargs))
        return placed[-1]

    monkeypatch.setattr(tasks, "request", recording)
    try:
        experiment_id = _held_experiment(c, gate, repository)
        src = f"exp:{experiment_id}"
        first = _view(c, src)
        assert delivered.wait(WAIT_S)
    finally:
        gate.set()
    try:
        finished = _wait_experiment(c, experiment_id, ("done", "failed"))
        assert finished["status"] == "done", finished.get("error")
        moved = _view(c, src)
        waiter = placed[-1]
        assert waiter.id != first["task"]["id"]
        assert tasks.status(waiter.id).state == "queued"
        assert moved["task"]["id"] == first["task"]["id"]  # the computing task, not the waiter
        assert moved["task"]["state"] == "running" and moved["task"]["stage"] == 1
        stage = moved["importance"]
        assert stage["stage"] == 1 and stage["partial"] is True
        was, now = stage["snapshot"], moved["snapshot"]
        assert was == {"generation": 0, "chunk_watermark": 0} and now["chunk_watermark"] == 1
        label = f"snapshot g0 c0 · current g{now['generation']} c{now['chunk_watermark']}"
        assert moved["snapshot_label"] == label
        cancel = c.post(f"{LAB}/{src}/tasks/{moved['task']['id']}/cancel")
        assert cancel.json() == {"cancelled": True}
        assert tasks.status(waiter.id).state == "cancelled"  # dropped at once
    finally:
        proceed.set()
    assert tasks.wait(first["task"]["id"], WAIT_S).state == "cancelled"
    assert len(computed) == 1  # T2's body never ran
    for _ in range(2):
        stopped = _view(c, src)
        assert stopped["task"]["id"] == first["task"]["id"]
        assert stopped["task"]["state"] == "cancelled"
        assert stopped["importance"]["stage"] == 1 and stopped["snapshot_label"] == label
    assert len(computed) == 1 and lab_store_module.REGISTRY.held(experiment_id) == set()
    rerun = _view(c, src, rerun=True)
    assert rerun["task"]["id"] not in (first["task"]["id"], waiter.id)
    assert tasks.wait(rerun["task"]["id"], WAIT_S).state == "done"
    whole = _view(c, src)
    assert whole["importance"]["stage"] == 3 and whole["snapshot_label"] is None
    assert whole["importance"]["n"] == 4


def test_a_compaction_with_no_new_chunk_moves_nothing(client, monkeypatch):
    """Review fix 11: a generation bump alone requests no new task, leaves the answer's stage and
    reads no `snapshot X · current Y`; the envelope's own `snapshot` is the current one."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    monkeypatch.setattr(experiments_module, "CHUNK_CELLS", 2)
    c, _, repository = client
    gate = threading.Event()
    try:
        experiment_id = _held_experiment(c, gate, repository)
        src = f"exp:{experiment_id}"
        before = _done(c, src)
        assert before["snapshot"] == {"generation": 0, "chunk_watermark": 0}
        store = experiments_module.ExperimentStore(repository)
        manifest = lab_store_module.compact(store.cells_dir(experiment_id), now=time.time())
        assert manifest.generation == 1
        after = _view(c, src)
        assert after["snapshot"] == {"generation": 1, "chunk_watermark": 0}
        assert after["task"] == before["task"] and after["importance"] == before["importance"]
        assert after["snapshot_label"] is None
    finally:
        gate.set()
    finished = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert finished["status"] == "done", finished.get("error")


@pytest.mark.parametrize("at", ["pin", "read"])
def test_a_task_view_answers_409_for_an_expired_snapshot(client, monkeypatch, at):
    """A snapshot whose files are gone is a 409, whichever read finds it; the pin taken before it
    is released and no task is requested."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    tasks = _tasks()
    requested = []
    original = tasks.request

    def recording(key, *args, **kwargs):
        requested.append(key)
        return original(key, *args, **kwargs)

    monkeypatch.setattr(tasks, "request", recording)

    def raiser(*args, **kwargs):
        raise lab_store_module.SnapshotExpired("part-1.parquet of generation 1 is gone")

    if at == "pin":
        monkeypatch.setattr(sources, "pin_experiment", raiser)
    else:  # before any Lab request: a cached table would answer without a read
        monkeypatch.setattr(lab_store_module, "read_trials", raiser)
    for view in ("importance", "interactions", "triples"):
        response = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": view})
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": "snapshot expired"}
        assert lab_store_module.REGISTRY.held(experiment_id) == set()
    assert requested == []


def test_a_malformed_stage_is_a_bug_not_a_refusal(client, monkeypatch):
    """A 422 is a request's refusal. A stored stage the view cannot read is the server's bug, and
    answers as one."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    key = importance_key(sources.experiment_source(document), "net_pnl", "combined", 1)
    tasks = _tasks()
    task = tasks.request(key, "importance", 3, lambda checkpoint: iter([{}] * 3))
    assert tasks.wait(task.id, WAIT_S).state == "done"
    response = c.post(f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "importance"})
    assert response.status_code == 500, response.text


# --- Phase 3 Task 7: the neighbourhood and robustness views --------------------------------------

SELECTION_ONLY = "unresolved · selection-period only"
NO_IMPORTANCE = "importance not computed for this snapshot"
NO_REPLAY = "no replay yet (stage 2)"
EVERY_TRIAL_BASIS = (
    "Tested (exact); neighbours and regions read every completed block-0 trial of the snapshot, "
    "the filter selects candidates only"
)


def _strict_json(response):
    """The body parsed with a NaN or an Infinity refused: every Lab payload is strict JSON."""

    def refuse(literal):
        raise AssertionError(f"{literal} in a Lab payload")

    return json.loads(response.text, parse_constant=refuse)


def _no_task_is_touched(monkeypatch) -> None:
    """These views read a finished result and nothing else: a live task's status reads the
    runner, which `finalize` holds while it waits for the write lock."""
    tasks = _tasks()

    def refuse(*args, **kwargs):
        raise AssertionError("a robustness view touched a live task")

    for name in ("request", "status", "computing", "cancel"):
        monkeypatch.setattr(tasks, name, refuse)


def test_neighbourhood_view_on_an_experiment(client, monkeypatch):
    """A 2 x 2 grid: trial 0's neighbours are trials 1 and 2, the diagonal is not one. A filter
    leaves its neighbours alone, says so on its basis line, and still counts the scope."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    trial = f"{src}#0"
    response = c.post(
        f"{LAB}/{src}/query",
        json={"filter": {}, "view": "neighbourhood", "trial": trial, "filter_hash": "cafe0001"},
    )
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["view"] == "neighbourhood" and answer["filter_hash"] == "cafe0001"
    assert answer["trial_id"] == trial and answer["empty"] is None
    assert answer["snapshot"] == {"generation": 1, "chunk_watermark": 1}
    assert answer["provisional"] is False
    found = answer["neighbourhood"]
    assert found["trial_no"] == 0 and found["trials"] == [1, 2]
    assert (found["probes"], found["valid"], found["tested"]) == (2, 2, 2)
    assert found["coverage"] == 1.0 and found["m"] == 1 and found["r"] == 1
    assert len(found["values"]) == 2 and found["iqr"] == found["p75"] - found["p25"]
    assert answer["constants"]["NEIGHBOUR_M_GRID"] == 1
    assert answer["scope"]["shown"] == 2 and answer["scope"]["basis"] == EVERY_TRIAL_BASIS
    brushed = _view(c, src, "neighbourhood", trial=trial, filter={"ranges": {DONCHIAN: [10, 10]}})
    assert brushed["neighbourhood"]["trials"] == [1, 2]
    assert brushed["scope"]["filtered"] == 2


def test_the_robustness_views_refuse_a_bad_trial(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    url = f"{LAB}/{src}/query"
    missing = c.post(url, json={"filter": {}, "view": "neighbourhood"})
    assert missing.status_code == 422 and "needs trial" in missing.json()["detail"]
    for view in ("neighbourhood", "robustness"):
        for trial, says in (
            (f"{src}#99", "no trial 99"),
            ("exp:another#0", "is not a trial of"),
            (f"{src}#x", "is not a trial number"),
        ):
            refused = c.post(url, json={"filter": {}, "view": view, "trial": trial})
            assert refused.status_code == 422, (view, trial, refused.text)
            assert says in refused.json()["detail"]
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_robustness_card_on_an_experiment_without_blocks(client, monkeypatch):
    """Ruling P16: K = 0 reads §7.6's `no blocks or folds`; the tolerance is the document's; no
    importance has run, so B says so; and nothing here requests or reads a live task."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch, tolerance=0.2)
    src = f"exp:{experiment_id}"
    _no_task_is_touched(monkeypatch)
    response = c.post(
        f"{LAB}/{src}/query",
        json={"filter": {}, "view": "robustness", "trial": f"{src}#3", "filter_hash": "cafe0002"},
    )
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["view"] == "robustness" and answer["filter_hash"] == "cafe0002"
    assert answer["rankings"] is None and answer["scope"]["shown"] == 1
    assert answer["scope"]["basis"] == EVERY_TRIAL_BASIS
    assert answer["tolerance"] == 0.2 and answer["tolerance_label"] is None
    assert answer["axes"] == [] and answer["constants"]["REGION_MIN_N"] == 30
    card = answer["card"]
    assert card["trial_id"] == f"{src}#3" and card["tolerance"] == 0.2
    categories = card["categories"]
    assert categories["A"]["inputs"]["valid_basis"] == "frame"
    assert categories["A"]["inputs"]["valid"] == 2
    assert categories["B"]["reason"] == NO_IMPORTANCE
    assert categories["C"]["reason"] == "no blocks or folds"
    assert categories["D"]["reason"] == NO_REPLAY
    assert card["findings"] == []
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_robustness_rankings_on_an_experiment(client, monkeypatch):
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    _no_task_is_touched(monkeypatch)
    response = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": "robustness"})
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["card"] is None
    ranks = answer["rankings"]
    assert len(ranks["peak"]) == 4 and set(ranks["peak"]) == set(ranks["robust"])
    assert ranks["k"] == answer["constants"]["RANKING_K"] == 20
    assert ranks["pool"] == 4 and answer["constants"]["RANK_POOL"] == 300
    assert ranks["b_max"] == answer["constants"]["RANK_B_MAX"] == 20
    assert answer["constants"]["PER_BARS"] == 1_000
    assert answer["scope"]["shown"] == 4 and answer["scope"]["filtered"] == 4
    # no importance result, so no axes and no B to speak of
    assert answer["axes"] == []
    assert answer["scope"]["basis"] == f"{EVERY_TRIAL_BASIS}; robust ranks the top 4 by peak"
    assert isinstance(ranks["disagree"], bool)
    short = _view(c, src, "robustness", k=2)
    two = short["rankings"]
    assert two["k"] == 2 and len(two["peak"]) == len(two["robust"]) == 2 and two["pool"] == 4
    assert short["scope"]["basis"] == f"{EVERY_TRIAL_BASIS}; robust ranks the top 4 by peak"
    widest = _view(c, src, "robustness", k=500)
    assert widest["rankings"]["k"] == 300 and len(widest["rankings"]["peak"]) == 4
    assert widest["scope"]["basis"] == f"{EVERY_TRIAL_BASIS}; robust ranks the top 4 by peak"
    # `k`'s default is `top`'s 200: only a `k` the request sent is a list length here
    assert api.QueryRequest.model_validate({"filter": {}, "view": "robustness"}).k == 200
    page = _view(c, src, "page")
    assert ranks["peak"][0] == page["rows"][0]["trial_id"]
    brushed = _view(c, src, "robustness", filter={"ranges": {DONCHIAN: [10, 10]}})
    assert len(brushed["rankings"]["peak"]) == 2 and brushed["scope"]["filtered"] == 2
    assert brushed["scope"]["basis"] == f"{EVERY_TRIAL_BASIS}; robust ranks the top 2 by peak"


def test_b_reads_the_importance_result_of_the_frames_snapshot(client, monkeypatch):
    """B's axes are the finished importance result's top shares at this snapshot and this seed. A
    result of an older chunk, another seed or none at all leaves B `importance not computed`,
    and the view never requests a task."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    document = experiments_module.ExperimentStore(repository).get(experiment_id)
    key = importance_key(sources.experiment_source(document), "net_pnl", "combined", 1)
    tasks = _tasks()
    stage = {"paths": [DONCHIAN, RSI], "fine": {"S": [0.2, 0.7]}}

    def body(checkpoint):
        return iter([stage] * 3)

    def card(**extra):
        return _view(c, src, "robustness", trial=f"{src}#0", **extra)

    # the snapshot before the last chunk: the same key, older evidence
    old = tasks.request(key, "importance", 3, body, snapshot=lab_store_module.Snapshot(1, 0))
    assert tasks.wait(old.id, WAIT_S).state == "done"
    assert tasks.result(key) is not None
    stale = card()
    assert stale["axes"] == []
    assert stale["card"]["categories"]["B"]["reason"] == NO_IMPORTANCE
    current = tasks.request(key, "importance", 3, body, snapshot=lab_store_module.Snapshot(1, 1))
    assert tasks.wait(current.id, WAIT_S).state == "done"
    answer = card()
    assert answer["axes"] == [RSI, DONCHIAN]
    b = answer["card"]["categories"]["B"]
    assert b["inputs"]["axes"] == [RSI, DONCHIAN]
    assert b["reason"].startswith("too few sampled trials in the region (")
    assert card(seed=2)["axes"] == []


def test_robustness_view_runs_on_a_real_importance_result(client, monkeypatch):
    """A 3 x 3 grid whose trials differ, so importance measures its shares (every cell of the
    breakout's surface has one P&L on this archive, and a share of no variance is undefined): B
    reads them as its axes."""
    c, _, _ = client
    fast, slow = "long_side.indicators.ema.length", "long_side.indicators.sma.length"
    strategy = c.post(
        "/aegis/api/strategies",
        json={"name": "Crossover", "spec": small_strategy().model_dump(mode="json")},
    ).json()
    surface = {
        "parameters": [
            {"path": fast, "start": 5, "stop": 7, "step": 1},
            {"path": slow, "start": 8, "stop": 10, "step": 1},
        ]
    }
    experiment_id = _finished_experiment(
        c, monkeypatch, name="nine cells", strategy_id=strategy["id"], surface=surface
    )
    src = f"exp:{experiment_id}"
    done = _done(c, src)
    assert done["importance"]["stage"] == 3 and done["importance"]["n"] == 9
    answer = _view(c, src, "robustness", trial=f"{src}#4")
    assert answer["axes"] and set(answer["axes"]) <= {fast, slow}
    b = answer["card"]["categories"]["B"]
    assert b["inputs"]["axes"] == answer["axes"] and b["reason"] != NO_IMPORTANCE
    # with axes B runs, on the top min(pool, k, RANK_B_MAX) rows: the basis line says how many
    ranks = _view(c, src, "robustness")
    assert ranks["axes"] == answer["axes"] and ranks["rankings"]["pool"] == 9
    assert ranks["scope"]["basis"] == (
        f"{EVERY_TRIAL_BASIS}; robust ranks the top 9 by peak, B reads at most 9"
    )
    short = _view(c, src, "robustness", k=2)
    assert short["scope"]["basis"].endswith("robust ranks the top 9 by peak, B reads at most 2")


def test_robustness_with_blocks_reads_the_selection_period_only(client, monkeypatch, tmp_path):
    """Ruling P16: with blocks and no folds C is `unresolved · selection-period only`, and the
    separate finding carries each block's figures: its row's metrics over its own bars."""
    c, _, repository = client
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0, missing=290)
    experiment_id = _finished_experiment(
        c,
        monkeypatch,
        name="screened card",
        data={"symbol": "SPY", "timeframe": "1m", **RANGE},
        blocks=2,
    )
    src = f"exp:{experiment_id}"
    _no_task_is_touched(monkeypatch)
    answer = _view(c, src, "robustness", trial=f"{src}#1")
    card = answer["card"]
    c_category = card["categories"]["C"]
    assert c_category["resolved"] is False and c_category["reason"] == SELECTION_ONLY
    assert c_category["inputs"]["blocks"] == 2
    assert card["categories"]["D"]["reason"] == NO_REPLAY
    assert [finding["name"] for finding in card["findings"]] == ["selection-period consistency"]
    assert card["findings"][0]["classification"] in (
        "consistent",
        "inconsistent",
        "not profitable on the full range",
    )
    store = experiments_module.ExperimentStore(repository)
    document = store.get(experiment_id)
    rows = store.trials(
        experiment_id,
        ["combined.net_pnl", "combined.max_drawdown", "combined.trade_count"],
        trial_no=1,
    ).table.to_pylist()
    by_block = {row["block"]: row for row in rows}
    bars = document.plan["bars"]
    bounds = experiments_module.block_bounds(bars, 2)
    finding = card["findings"][0]["inputs"]
    assert finding["full"]["bars"] == bars
    assert finding["full"]["net_pnl"] == by_block[0]["combined.net_pnl"]
    for b, figures in enumerate(finding["block_figures"], 1):
        assert figures["block"] == b
        assert figures["bars"] == bounds[b - 1][1] - bounds[b - 1][0]
        assert figures["net_pnl"] == by_block[b]["combined.net_pnl"]
        assert figures["max_drawdown"] == by_block[b]["combined.max_drawdown"]
        assert figures["trades"] == by_block[b]["combined.trade_count"]
    assert lab_store_module.REGISTRY.held(experiment_id) == set()
    assert answer["scope"]["block"] == 0 and answer["scope"]["attempted"] == 4
    # rankings read no block row: a card reads one trial's, through the store's predicate
    assert _view(c, src, "robustness")["rankings"]["k"] == 20


@pytest.mark.parametrize("fault", ["absent", "failed"])
def test_a_block_without_figures_gives_the_finding_no_verdict(client, monkeypatch, tmp_path, fault):
    """A screening block's row absent, or there but not `ok` whatever it holds: the finding reads
    no verdict and says why, and C is what it was. Every row is given a profit, since this archive's
    trials lose and a baseline ≤ 0 reads `not profitable` before any block is compared."""
    c, _, _ = client
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0, missing=290)
    experiment_id = _finished_experiment(
        c,
        monkeypatch,
        name="a block without figures",
        data={"symbol": "SPY", "timeframe": "1m", **RANGE},
        blocks=2,
    )
    src = f"exp:{experiment_id}"
    whole = _view(c, src, "robustness", trial=f"{src}#1")["card"]
    original = sources.open_experiment

    def faulty(*args, trial_no=None, **kwargs):
        frame, handle = original(*args, trial_no=trial_no, **kwargs)
        if trial_no is None:
            return frame, handle
        table = frame.table
        at = table.schema.get_field_index("combined.net_pnl")
        table = table.set_column(
            at, "combined.net_pnl", pa.array([100.0] * table.num_rows, pa.float64())
        )
        block = table.column("block").to_numpy()
        if fault == "absent":
            table = table.filter(pa.array(block != 2))
        else:
            words = table.column("status").to_pylist()
            status = ["failed" if b == 2 else word for b, word in zip(block, words, strict=True)]
            at = table.schema.get_field_index("status")
            table = table.set_column(at, "status", pa.array(status, table.schema.field(at).type))
        return replace(frame, table=table), handle

    monkeypatch.setattr(sources, "open_experiment", faulty)
    card = _view(c, src, "robustness", trial=f"{src}#1")["card"]
    finding = card["findings"][0]
    assert finding["classification"] is None
    assert finding["reason"] == "block 2 has no defined figures"
    assert finding["inputs"]["block_figures"][1]["net_pnl"] is None
    assert card["categories"]["C"] == whole["categories"]["C"]
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_a_block_read_on_an_expired_snapshot_is_a_409(client, monkeypatch, tmp_path):
    c, _, _ = client
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0, missing=290)
    experiment_id = _finished_experiment(
        c,
        monkeypatch,
        name="expired card",
        data={"symbol": "SPY", "timeframe": "1m", **RANGE},
        blocks=2,
    )
    src = f"exp:{experiment_id}"
    original = sources.open_experiment

    def expiring(*args, trial_no=None, **kwargs):
        if trial_no is not None:
            raise lab_store_module.SnapshotExpired("part-1.parquet of generation 1 is gone")
        return original(*args, trial_no=trial_no, **kwargs)

    monkeypatch.setattr(sources, "open_experiment", expiring)
    response = c.post(
        f"{LAB}/{src}/query", json={"filter": {}, "view": "robustness", "trial": f"{src}#0"}
    )
    assert response.status_code == 409 and response.json() == {"detail": "snapshot expired"}
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_robustness_on_an_optimization_uses_the_default_tolerance(client):
    """An `opt:` source has no tolerance of its own: 0.15, labelled. Its side is its scope, its
    neighbours are its grid's, and B reads the finished importance of those cells."""
    c, _, _ = client
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    done = _wait(c, job_id, "done")
    src = f"opt:{job_id}"
    long_side = {"filter": {"scope": "long"}}
    found = _view(c, src, "neighbourhood", trial=f"{src}#4", **long_side)["neighbourhood"]
    assert (found["tested"], found["valid"], found["m"]) == (4, 4, 1)
    answer = _view(c, src, "robustness", trial=f"{src}#4", **long_side)
    assert answer["tolerance"] == 0.15
    assert answer["tolerance_label"] == "default tolerance 0.15"
    card = answer["card"]
    assert card["tolerance_label"] == "default tolerance 0.15" and card["scope"] == "long"
    assert card["categories"]["A"]["resolved"] is True
    assert card["categories"]["B"]["reason"] == NO_IMPORTANCE
    assert card["categories"]["C"]["reason"] == "no blocks or folds"
    assert answer["snapshot"] is None
    ranks = _view(c, src, "robustness", **long_side)["rankings"]
    assert len(ranks["peak"]) == 9
    _done(c, src, **long_side)
    fast, slow = f"long_side.{done['fast_path']}", f"long_side.{done['slow_path']}"
    computed = _view(c, src, "robustness", trial=f"{src}#4", **long_side)
    assert set(computed["axes"]) <= {fast, slow}
    assert computed["axes"]
    refused = c.post(f"{LAB}/{src}/query", json={"filter": {}, "view": "robustness"})
    assert refused.status_code == 422  # an optimizer source has one side


# --- Phase 3 Task 8: Pareto, the exact parallel sample and convergence ---------------------------

PNL_DD = ["net_pnl", "max_drawdown"]


def test_pareto_view_on_an_experiment(client, monkeypatch):
    """The 4-cell grid: every field is what the page's rows say, the brush narrows it, and the
    panel reads its bounds from the response. It reads no live task."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    _no_task_is_touched(monkeypatch)
    response = c.post(
        f"{LAB}/{src}/query",
        json={"filter": {}, "view": "pareto", "objectives": PNL_DD, "filter_hash": "cafe0001"},
    )
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["view"] == "pareto" and answer["filter_hash"] == "cafe0001"
    assert answer["snapshot"] == {"generation": 1, "chunk_watermark": 1}
    assert answer["provisional"] is False and answer["empty"] is None
    assert answer["objectives"] == PNL_DD and answer["orientation"] == [1, -1]
    assert answer["constants"] == {
        "PARETO_FRONT_MAX": 2_000,
        "PARETO_DENSITY_BINS": 64,
        "OBJECTIVES_MIN": 2,
        "OBJECTIVES_MAX": 3,
    }
    assert answer["sampled"] is False and answer["front_size"] == len(answer["front"]) >= 1
    assert answer["front_size"] + answer["dominated"] + answer["excluded"] == 4
    assert answer["scope"]["shown"] == answer["front_size"]
    assert answer["scope"]["basis"] == "Tested (exact)" and answer["scope"]["filtered"] == 4
    assert all(trial.startswith(f"{src}#") for trial in answer["front"])
    density = answer["density"]
    assert density["bins"] == 64 and len(density["counts"]) == 64
    assert sum(map(sum, density["counts"])) == answer["dominated"]
    rows = _view(c, src, "page")["rows"]
    values = {row["trial_id"]: row["values"] for row in rows}
    for point in answer["points"]:
        held = values[point["trial_id"]]
        assert point["values"] == [held["combined.net_pnl"], held["combined.max_drawdown"]]
    brushed = _view(c, src, "pareto", objectives=PNL_DD, filter={"ranges": {DONCHIAN: [10, 10]}})
    assert brushed["scope"]["filtered"] == 2 and len(brushed["front"]) <= 2
    lengths = {row["trial_id"]: row["params"][DONCHIAN] for row in rows}
    assert {lengths[trial] for trial in brushed["front"]} == {10.0}
    nothing = _view(c, src, "pareto", objectives=PNL_DD, filter={"values": {DONCHIAN: 999}})
    assert nothing["empty"] == "no trials match: 1 filter active" and nothing["front"] == []
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ({}, "the pareto view needs objectives"),
        ({"objectives": ["net_pnl"]}, "2 or 3 objectives"),
        ({"objectives": ["net_pnl", "mar", "cagr", "exposure"]}, "2 or 3 objectives"),
        ({"objectives": ["net_pnl", "net_pnl"]}, "named twice"),
        ({"objectives": ["net_pnl", "nope"]}, "unknown metric"),
    ],
)
def test_pareto_refuses_bad_objectives(client, monkeypatch, body, named):
    """A clean 422 naming the refusal, on an experiment and on an optimization."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    response = c.post(
        f"{LAB}/exp:{experiment_id}/query", json={"filter": {}, "view": "pareto", **body}
    )
    assert response.status_code == 422, response.text
    assert named in response.json()["detail"]
    assert lab_store_module.REGISTRY.held(experiment_id) == set()
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, job_id, "done")
    refused = c.post(
        f"{LAB}/opt:{job_id}/query",
        json={"filter": {"scope": "long"}, "view": "pareto", **body},
    )
    assert refused.status_code == 422, refused.text
    assert named in refused.json()["detail"]


def test_parallel_sample_on_an_experiment(client, monkeypatch):
    """`parallel_mode` picks the lines; the default stays the bundles; the seed is in the answer."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    bundled = _view(c, src, "parallel", axes=[DONCHIAN, RSI], metric="net_pnl")
    assert bundled["bundles"] and "lines" not in bundled
    response = c.post(
        f"{LAB}/{src}/query",
        json={
            "filter": {},
            "view": "parallel",
            "axes": [DONCHIAN, RSI],
            "metric": "net_pnl",
            "parallel_mode": "sample",
            "seed": 3,
        },
    )
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["sampled_from"] == 4 and answer["strata"] == 10 and answer["seed"] == 3
    assert answer["scope"]["basis"] == "Sampled 4 of 4 (stratified by decile of net_pnl)"
    assert answer["scope"]["shown"] == len(answer["lines"]) == 4
    assert answer["axes"] == [DONCHIAN, RSI] and answer["bundles"] == []
    assert answer["constants"] == {"PARALLEL_MAX_LINES": 5_000, "PARALLEL_STRATA": 10}
    rows = {row["trial_id"]: row for row in _view(c, src, "page")["rows"]}
    for line in answer["lines"]:
        row = rows[line["trial_id"]]
        assert line["values"] == [row["params"][DONCHIAN], row["params"][RSI]]
        assert line["metric"] == row["values"]["combined.net_pnl"]
    refused = c.post(
        f"{LAB}/{src}/query", json={"filter": {}, "view": "parallel", "parallel_mode": "lines"}
    )
    assert refused.status_code == 422, refused.text
    unknown = c.post(
        f"{LAB}/{src}/query",
        json={"filter": {}, "view": "parallel", "parallel_mode": "sample", "axes": ["nope"]},
    )
    assert unknown.status_code == 422 and "unknown path" in unknown.json()["detail"]


def test_convergence_view_on_an_experiment(client, monkeypatch):
    """Four trials: best-so-far by trial number, under two batches so the panel's empty state
    (`best` stays for the sparkline), and the basis line saying what the neighbours would read."""
    c, _, _ = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    _no_task_is_touched(monkeypatch)
    response = c.post(
        f"{LAB}/{src}/query",
        json={"filter": {}, "view": "convergence", "metric": "net_pnl", "filter_hash": "cafe0001"},
    )
    assert response.status_code == 200, response.text
    answer = _strict_json(response)
    assert answer["view"] == "convergence" and answer["filter_hash"] == "cafe0001"
    assert answer["snapshot"] == {"generation": 1, "chunk_watermark": 1}
    assert answer["provisional"] is False
    assert answer["robust"] == [] and answer["batches"] == 0 and answer["partial"] == 4
    reason = "fewer than 2 complete batches of 5000 trials with a defined net_pnl (4 so far)"
    assert answer["robust_reason"] == reason and answer["empty"] == reason
    page = _view(c, src, "page", sort="trial_no")["rows"]
    running, expected = float("-inf"), []
    for row in page:
        running = max(running, row["values"]["combined.net_pnl"])
        expected.append([row["trial_no"], running])
    assert answer["best"] == expected
    assert answer["scope"]["shown"] == 4 and answer["scope"]["filtered"] == 4
    assert answer["scope"]["basis"] == (
        "Tested (exact); neighbours read every completed block-0 trial of the snapshot, "
        "the filter selects each batch's top trials"
    )
    assert answer["constants"]["CONVERGENCE_BATCH"] == 5_000
    assert answer["constants"]["MIN_BATCHES"] == 2
    assert _view(c, src, "convergence", metric="max_drawdown")["orientation"] == -1
    missing = c.post(
        f"{LAB}/{src}/query", json={"filter": {}, "view": "convergence", "metric": "nope"}
    )
    assert missing.status_code == 422 and "unknown metric" in missing.json()["detail"]
    assert lab_store_module.REGISTRY.held(experiment_id) == set()


def test_the_new_views_answer_an_optimization(client, monkeypatch):
    """An `opt:` source has no snapshot, so no index, and one side: the three views read its cells
    under its own ids, and another scope is the shared refusal."""
    c, _, _ = client
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    done = _wait(c, job_id, "done")
    src = f"opt:{job_id}"
    long_side = {"filter": {"scope": "long"}}
    pareto = _view(c, src, "pareto", objectives=PNL_DD, **long_side)
    assert pareto["snapshot"] is None and pareto["scope"]["filtered"] == done["total_cells"] == 9
    assert pareto["front_size"] + pareto["dominated"] + pareto["excluded"] == 9
    assert all(trial.startswith(f"{src}#") for trial in pareto["front"])
    lines = _view(c, src, "parallel", parallel_mode="sample", **long_side)
    assert len(lines["lines"]) == 9 and all(path.startswith("long_side.") for path in lines["axes"])
    trend = _view(c, src, "convergence", **long_side)
    assert len(trend["best"]) == 9 and trend["robust"] == [] and trend["provisional"] is False
    assert trend["m"] == 1  # an exhaustive grid's reach
    assert trend["empty"] == trend["robust_reason"] is not None
    for body in (
        {"view": "pareto", "objectives": PNL_DD},
        {"view": "convergence"},
        {"view": "parallel", "parallel_mode": "sample"},
    ):
        refused = c.post(f"{LAB}/{src}/query", json={"filter": {"scope": "short"}, **body})
        assert refused.status_code == 422 and "one side" in refused.json()["detail"]


def _expected_batches(c, src: str, flt: dict, size: int) -> list[dict]:
    """The robust series of batches of `size` by the definition, through the routes: per batch of
    the page's rows by trial number, its best trial (ties to the lowest number) and that trial's
    own neighbourhood's P25, the one candidate's value being the batch's median and quartiles."""
    column = f"{flt.get('scope', 'combined')}.net_pnl"
    rows = _view(c, src, "page", sort="trial_no", filter=flt)["rows"]
    out = []
    for batch in range(len(rows) // size):
        members = rows[batch * size : (batch + 1) * size]
        leader = max(members, key=lambda row: (row["values"][column], -row["trial_no"]))
        found = _view(c, src, "neighbourhood", trial=leader["trial_id"], filter=flt)
        p25 = found["neighbourhood"]["p25"]
        out.append(
            {
                "batch": batch,
                "trial_no": members[-1]["trial_no"],
                "median": p25,
                "p25": p25,
                "p75": p25,
                "top": 1,
                "measured": 0 if p25 is None else 1,
            }
        )
    return out


@pytest.mark.parametrize("kind", ["exp", "opt"])
def test_the_robust_series_answers_through_the_route(client, monkeypatch, kind):
    """Small batches, so the robust path runs end to end: on an experiment over the snapshot's
    index, and on an optimization, which has none and whose 9 cells otherwise give under 2 batches.
    Its entries are the definition's, and there is no empty state."""
    c, _, _ = client
    monkeypatch.setattr(convergence_module, "CONVERGENCE_BATCH", 2)
    if kind == "exp":
        src, flt, batches, partial = f"exp:{_finished_experiment(c, monkeypatch)}", {}, 2, 0
    else:
        job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
        _wait(c, job_id, "done")
        src, flt, batches, partial = f"opt:{job_id}", {"scope": "long"}, 4, 1
    response = c.post(
        f"{LAB}/{src}/query",
        json={"filter": flt, "view": "convergence", "metric": "net_pnl"},
    )
    assert response.status_code == 200, response.text
    trend = _strict_json(response)
    assert trend["empty"] is None and trend["robust_reason"] is None
    assert trend["batches"] == batches and trend["partial"] == partial
    assert len(trend["robust"]) == batches
    assert trend["robust"] == _expected_batches(c, src, flt, 2)
    assert any(entry["measured"] for entry in trend["robust"])


def test_convergence_is_cached_per_snapshot_filter_and_metric(client, lab_cache, monkeypatch):
    """The ruling on its cost: a repeat is an entry's, a changed filter or metric recomputes, and a
    status change at one snapshot reads its own label. The key names this instance of the source."""
    c, _, repository = client
    experiment_id = _finished_experiment(c, monkeypatch)
    src = f"exp:{experiment_id}"
    computed: list[str] = []
    real = sources.convergence_payload

    def spy(*args, **kwargs):
        computed.append(kwargs["metric"])
        return real(*args, **kwargs)

    monkeypatch.setattr(sources, "convergence_payload", spy)
    first = _view(c, src, "convergence", filter_hash="aaaa0001")
    assert computed == ["net_pnl"] and first["provisional"] is False
    again = _view(c, src, "convergence", filter_hash="bbbb0002")
    assert computed == ["net_pnl"] and again["filter_hash"] == "bbbb0002"
    assert again["best"] == first["best"] and again["scope"] == first["scope"]
    keys = [key for key in lab_cache._entries if key[0][0] == "convergence"]
    store = experiments_module.ExperimentStore(repository)
    document = store.get(experiment_id)
    assert [key[0] for key in keys] == [("convergence", *sources.experiment_source(document))]
    assert keys[0][1] == (1, 1)
    # the job's status moves and the snapshot does not: the entry serves, the label is this request's
    store.save(document.model_copy(update={"status": "running"}))
    running = _view(c, src, "convergence")
    assert computed == ["net_pnl"] and running["provisional"] is True
    store.save(document)
    assert _view(c, src, "convergence")["provisional"] is False
    assert computed == ["net_pnl"]
    # a changed filter or metric is its own entry
    brushed = _view(c, src, "convergence", filter={"ranges": {DONCHIAN: [10, 10]}})
    assert computed == ["net_pnl", "net_pnl"] and brushed["scope"]["filtered"] == 2
    assert len(brushed["best"]) == 2
    other = _view(c, src, "convergence", metric="max_drawdown")
    assert computed == ["net_pnl", "net_pnl", "max_drawdown"] and other["orientation"] == -1
