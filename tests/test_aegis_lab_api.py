"""Optimization Lab v2, Phase 2 (Task 8): the `/aegis/api/lab` routes over `exp:` and `opt:`
sources. Real experiments and optimizations run through the API on the synthetic 52-bar archive;
the Lab cache is one instance per test, so a test can evict and inspect it."""

import re
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from products.aegis import experiments as experiments_module
from products.aegis.data import ArchiveStore
from products.aegis.experiments import ExperimentDocument, _same
from products.aegis.indicators import IndicatorCache
from products.aegis.lab import identity, sources
from products.aegis.lab import store as lab_store_module
from products.aegis.lab.cache import LabCache
from products.aegis.pool import METRICS, SCOPES
from products.aegis.results import strategy_hash
from products.aegis.runs import JsonRunRepository, aegis_data_root
from products.aegis.surface import apply_params
from test_aegis_api import (
    NoCore,
    _experiment_body,
    _optimize_payload,
    _runner,
    _wait,
    _wait_experiment,
)
from test_aegis_data import write_archive

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
    _runner(repository)  # no Lab request ever builds the worker's own runner on the real store
    yield TestClient(server.app, raise_server_exceptions=False), store, repository
    server.app.dependency_overrides.clear()


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
    original = experiments_module.ExperimentStore.trials

    def recording(self, experiment_id, columns=None, *, snapshot=None):
        recorded.append(None if columns is None else tuple(columns))
        return original(self, experiment_id, columns, snapshot=snapshot)

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
    finally:
        gate.set()
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert c.get(f"{LAB}/exp:{experiment_id}/summary").json()["provisional"] is False


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
