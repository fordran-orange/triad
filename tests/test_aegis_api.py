"""Offline API checks for the Aegis worker routes; no database, synthetic archive on tmp_path."""

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from products.aegis.backtest import BacktestRequest
from products.aegis.data import ArchiveStore
from products.aegis.indicators import IndicatorCache
from products.aegis.jobs import JobRunner
from products.aegis.optimize import OptimizerRunner
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import apply_parameters, default_strategy
from pydantic import ValidationError
from test_aegis_data import write_archive
from test_aegis_optimize import small_strategy
from test_aegis_walkforward import small_ranges

RANGE = {"start": "2026-10-30", "end": "2026-11-02"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=100.0)
    store = ArchiveStore(tmp_path)
    repository = JsonRunRepository(tmp_path / "aegis")
    server.app.dependency_overrides[api.get_store] = lambda: store
    server.app.dependency_overrides[api.get_repository] = lambda: repository
    cache = IndicatorCache()
    server.app.dependency_overrides[api.get_cache] = lambda: cache
    monkeypatch.setattr(server, "Store", lambda **_: SimpleNamespace(list_work=list))
    yield TestClient(server.app, raise_server_exceptions=False), store, repository
    server.app.dependency_overrides.clear()


def test_status_contract_unchanged(client):
    c, _, _ = client
    body = c.get("/aegis/api/status").json()
    assert body["mode"] == "human_directed" and body["exchange"] == "CLOSED"
    assert body["work_items"] == []


def test_symbols_lists_archives_with_provenance(client):
    c, _, _ = client
    body = c.get("/aegis/api/data/symbols").json()
    assert body["timeframes"] == ["1m", "15m", "30m", "1h", "1D"]
    (qqq,) = body["symbols"]
    assert qqq["symbol"] == "QQQ" and qqq["source"] == "raw_archive"
    assert qqq["research_eligible"] is False and qqq["vintage"] == "20260301T000000000000Z"
    assert len(qqq["sha256"]) == 64 and qqq["row_count"] == 780


def test_bars_returns_epoch_ms_and_cap_422(client, monkeypatch):
    c, _, _ = client
    body = c.get(
        "/aegis/api/data/bars", params={"symbol": "QQQ", "timeframe": "1h", **RANGE}
    ).json()
    assert body["count"] == 14 and body["timezone"] == "America/New_York"
    import pandas as pd

    open_ms = int(pd.Timestamp("2026-10-30 09:30", tz="America/New_York").value // 1_000_000)
    assert body["bars"][0]["time"] == open_ms  # 2026-10-30 09:30 EDT
    assert set(body["bars"][0]) == {"time", "open", "high", "low", "close", "volume"}
    assert body["data"]["research_eligible"] is False and body["data"]["timeframe"] == "1h"
    import products.aegis.data as module

    monkeypatch.setattr(module, "BAR_CAP", 100)
    over = c.get("/aegis/api/data/bars", params={"symbol": "QQQ", "timeframe": "1m", **RANGE})
    assert over.status_code == 422 and "narrow the range" in over.json()["detail"]
    assert (
        c.get(
            "/aegis/api/data/bars", params={"symbol": "ZZZ", "timeframe": "1h", **RANGE}
        ).status_code
        == 404
    )
    assert (
        c.get(
            "/aegis/api/data/bars", params={"symbol": "QQQ", "timeframe": "2h", **RANGE}
        ).status_code
        == 422
    )


def test_indicators_endpoint_returns_series_per_indicator(client):
    c, _, _ = client
    body = c.post(
        "/aegis/api/indicators",
        json={
            "symbol": "QQQ",
            "timeframe": "15m",
            **RANGE,
            "indicators": [
                {"id": "ema", "kind": "EMA", "length": 9},
                {"id": "sma", "kind": "SMA", "length": 30},
            ],
        },
    ).json()
    assert set(body["series"]) == {"ema", "sma"} and len(body["times"]) == 52
    assert len(body["series"]["ema"]) == 52 and body["series"]["ema"][:8] == [None] * 8
    assert body["series"]["sma"][29] is not None and body["series"]["sma"][28] is None


def test_backtest_by_data_reference_persists_and_returns_hash(client):
    c, _, repository = client
    strategy = default_strategy().model_dump(mode="json")
    payload = {"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}}
    first = c.post("/aegis/api/backtest", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) >= {
        "run_id",
        "created_at",
        "elapsed_ms",
        "result_hash",
        "data",
        "strategy",
        "result",
        "series",
        "markers",
    }
    assert body["data"]["symbol"] == "QQQ" and body["data"]["research_eligible"] is False
    assert len(body["data"]["sha256"]) == 64 and len(body["data"]["data_hash"]) == 64
    assert body["result"]["combined"]["metrics"]["trade_count"] >= 0
    assert set(body["series"]) == {"long", "short"} and set(body["series"]["long"]) == {
        "ema",
        "sma",
    }
    second = c.post("/aegis/api/backtest", json=payload).json()
    assert second["result_hash"] == body["result_hash"] and second["run_id"] != body["run_id"]
    assert repository.get_run(body["run_id"])["result_hash"] == body["result_hash"]


def test_backtest_requires_exactly_one_of_data_or_bars(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    assert c.post("/aegis/api/backtest", json={"strategy": strategy}).status_code == 422
    both = {
        "strategy": strategy,
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
        "bars": [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ],
    }
    assert c.post("/aegis/api/backtest", json=both).status_code == 422
    missing = c.post(
        "/aegis/api/backtest",
        json={"strategy": strategy, "data": {"symbol": "ZZZ", "timeframe": "15m", **RANGE}},
    )
    assert missing.status_code == 404


def test_backtest_bars_over_bound_is_422(client):
    c, _, _ = client
    strategy = default_strategy()
    with pytest.raises(ValidationError, match="at most 200000"):
        BacktestRequest(strategy=strategy, bars=[{}] * 200_001)
    events = [{"event_type": "FOMC", "timestamp": "2026-01-05T15:00:00Z"}] * 10_001
    response = c.post(
        "/aegis/api/backtest",
        json={
            "strategy": strategy.model_dump(mode="json"),
            "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
            "events": events,
        },
    )
    assert response.status_code == 422


def test_runs_list_and_get(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    run = c.post(
        "/aegis/api/backtest",
        json={"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}},
    ).json()
    listed = c.get("/aegis/api/runs").json()
    assert [r["run_id"] for r in listed] == [run["run_id"]]
    assert "result" not in listed[0] and listed[0]["result_hash"] == run["result_hash"]
    fetched = c.get(f"/aegis/api/runs/{run['run_id']}").json()
    assert fetched["state"] == "ok" and fetched["result"] == run["result"]
    assert c.get("/aegis/api/runs/does-not-exist").status_code == 404


def test_reload_with_changed_file_hash_is_source_unavailable(client, tmp_path):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    run = c.post(
        "/aegis/api/backtest",
        json={"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}},
    ).json()
    assert run["state"] == "ok"
    # Same vintage, same path, different bytes: the pinned sha256 no longer matches.
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=101.0)
    reloaded = c.get(f"/aegis/api/runs/{run['run_id']}")
    assert reloaded.status_code == 200
    body = reloaded.json()
    assert body["state"] == "source_unavailable"
    assert "sha256 mismatch" in body["state_detail"]
    # The envelope is still returned in full; nothing falls forward to the new bytes.
    assert body["result_hash"] == run["result_hash"] and body["result"] == run["result"]
    assert body["data"]["sha256"] == run["data"]["sha256"]


def test_backtest_hash_stable_across_two_requests(client, tmp_path):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    payload = {"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}}
    first = c.post("/aegis/api/backtest", json=payload).json()
    # A cold store (fresh discovery, empty frame cache) must reproduce the same canonical result.
    server.app.dependency_overrides[api.get_store] = lambda: ArchiveStore(tmp_path)
    second = c.post("/aegis/api/backtest", json=payload).json()
    assert first["result_hash"] == second["result_hash"]
    assert first["result"] == second["result"]
    assert first["run_id"] != second["run_id"]
    assert first["data"]["sha256"] == second["data"]["sha256"]
    assert first["data"]["data_hash"] == second["data"]["data_hash"]


# --- optimizer routes (Task 12) -----------------------------------------------------------


def _optimize_payload(side="long", objective="net_pnl"):
    return {
        "strategy": small_strategy().model_dump(mode="json"),
        "side": side,
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
        "objective": objective,
    }


def _held_runner(repository):
    """A runner that pauses after its first cell until the returned gate is set."""
    gate = threading.Event()

    def after_cell(done):
        if done == 1:
            gate.wait(10)

    runner = OptimizerRunner(repository, after_cell=after_cell)
    server.app.dependency_overrides[api.get_runner] = lambda: runner
    return runner, gate


def _wait(c, job_id, status, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = c.get(f"/aegis/api/optimize/{job_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never reached {status}")


def test_optimize_returns_202_with_plan(client):
    c, _, repository = client
    server.app.dependency_overrides[api.get_runner] = lambda: OptimizerRunner(repository)
    plan = c.post("/aegis/api/optimize/plan", json=_optimize_payload())
    assert plan.status_code == 200, plan.text
    assert plan.json()["total_cells"] == 9 and plan.json()["skipped_cells"] == 0
    assert plan.json()["skip_reason"] is None
    assert plan.json()["bars"] == 52 and plan.json()["estimated_seconds"] > 0
    response = c.post("/aegis/api/optimize", json=_optimize_payload())
    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == {"job_id", "total_cells", "skipped_cells", "estimated_seconds"}
    assert body["total_cells"] == 9 and body["skipped_cells"] == 0
    done = _wait(c, body["job_id"], "done")
    assert done["progress"] == {"done": 9, "total": 9} and len(done["cells"]) == 9
    assert done["data"]["symbol"] == "QQQ" and done["data"]["research_eligible"] is False
    assert set(done["matrices"]) == {"net_pnl", "mar", "max_drawdown", "trade_count"}
    assert [j["job_id"] for j in c.get("/aegis/api/optimize").json()] == [body["job_id"]]
    too_big = _optimize_payload()
    too_big["strategy"]["long_side"]["optimization"][0].update({"start": 1, "stop": 25, "step": 1})
    too_big["strategy"]["long_side"]["optimization"][1].update(
        {"start": 30, "stop": 200, "step": 10}
    )
    assert c.post("/aegis/api/optimize", json=too_big).status_code == 422
    assert c.get("/aegis/api/optimize/does-not-exist").status_code == 404


def test_optimize_status_progresses_and_is_responsive_while_running(client):
    c, _, repository = client
    _, gate = _held_runner(repository)
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    mid = _wait(c, job_id, "running")
    deadline = time.monotonic() + 10
    while mid["progress"]["done"] < 1 and time.monotonic() < deadline:
        mid = c.get(f"/aegis/api/optimize/{job_id}").json()
    assert 0 < mid["progress"]["done"] < mid["progress"]["total"]
    assert len(mid["cells"]) == mid["progress"]["done"]
    for _ in range(5):
        started = time.perf_counter()
        response = c.get(f"/aegis/api/optimize/{job_id}")
        assert response.status_code == 200
        assert time.perf_counter() - started < 0.5
    assert c.get("/aegis/api/status").status_code == 200  # the rest of the API stays responsive
    gate.set()
    done = _wait(c, job_id, "done")
    assert done["progress"]["done"] == done["progress"]["total"] == 9


def test_optimize_cancel(client):
    c, _, repository = client
    _, gate = _held_runner(repository)
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, job_id, "running")
    assert c.post(f"/aegis/api/optimize/{job_id}/cancel").json() == {"cancelled": True}
    gate.set()
    cancelled = _wait(c, job_id, "cancelled")
    assert cancelled["progress"]["done"] == 1
    assert c.post(f"/aegis/api/optimize/{job_id}/cancel").json() == {"cancelled": False}
    assert repository.get_optimization(job_id)["status"] == "cancelled"


def test_second_job_while_running_is_409_and_first_continues_api(client):
    c, _, repository = client
    _, gate = _held_runner(repository)
    first = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, first, "running")
    second = c.post("/aegis/api/optimize", json=_optimize_payload("short"))
    assert second.status_code == 409
    assert second.json() == {"detail": "an optimization is already running"}
    gate.set()
    assert _wait(c, first, "done")["progress"] == {"done": 9, "total": 9}


# --- fix pass after the whole-branch review ---------------------------------------------------


def test_optimize_single_enabled_range_is_served_not_500(client):
    c, _, repository = client
    server.app.dependency_overrides[api.get_runner] = lambda: OptimizerRunner(repository)
    payload = _optimize_payload()
    payload["strategy"]["long_side"]["optimization"][1]["enabled"] = False
    plan = c.post("/aegis/api/optimize/plan", json=payload)
    assert plan.status_code == 200 and plan.json()["total_cells"] == 3
    response = c.post("/aegis/api/optimize", json=payload)
    assert response.status_code == 202, response.text
    done = _wait(c, response.json()["job_id"], "done")
    assert done["progress"] == {"done": 3, "total": 3} and done["slow_values"] == []
    assert c.get("/aegis/api/optimize").status_code == 200


def test_unfinished_job_is_listed_while_running(client):
    c, _, repository = client
    _, gate = _held_runner(repository)
    job_id = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, job_id, "running")
    listed = {j["job_id"]: j for j in c.get("/aegis/api/optimize").json()}
    assert listed[job_id]["status"] in ("queued", "running")
    gate.set()
    _wait(c, job_id, "done")


def test_optimize_plan_estimate_follows_the_runner_cost(client):
    c, _, repository = client
    runner = OptimizerRunner(repository)
    runner.ms_per_bar = 2.0
    server.app.dependency_overrides[api.get_runner] = lambda: runner
    plan = c.post("/aegis/api/optimize/plan", json=_optimize_payload()).json()
    assert plan["estimated_seconds"] == pytest.approx(9 * 52 * 2.0 / 1000)
    assert plan["ms_per_bar"] == 2.0


def test_backtest_envelope_carries_its_settings(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    data = {"symbol": "QQQ", "timeframe": "15m", **RANGE}
    default = c.post("/aegis/api/backtest", json={"strategy": strategy, "data": data}).json()
    assert default["settings"]["initial_capital"] == 100000.0
    assert default["settings"]["allocation_fraction"] == 1.0
    assert default["settings"]["evaluate_from"] is None  # no warm-up boundary on a plain run
    custom = c.post(
        "/aegis/api/backtest",
        json={"strategy": strategy, "data": data, "settings": {"initial_capital": 50000}},
    ).json()
    assert custom["settings"]["initial_capital"] == 50000.0
    assert custom["result_hash"] != default["result_hash"]
    reloaded = c.get(f"/aegis/api/runs/{custom['run_id']}").json()
    assert reloaded["settings"]["initial_capital"] == 50000.0


def test_warm_in_background_warms_every_discovered_symbol(client):
    class Fake:
        warmed = None

        def symbols(self):
            return [SimpleNamespace(symbol="QQQ"), SimpleNamespace(symbol="SPY")]

        def warm(self, symbols):
            Fake.warmed = list(symbols)

    thread = api.warm_in_background(Fake())
    thread.join(5)
    assert thread.daemon and Fake.warmed == ["QQQ", "SPY"]


# --- walk-forward routes, cross-kind 409, cancel 404, backtest cache (Task 6) --------------


def _runner(repository, after_unit=None):
    """One JobRunner instance for every request of a test (a new one per request would not
    know its own jobs in memory)."""
    runner = JobRunner(repository, after_unit=after_unit)
    server.app.dependency_overrides[api.get_runner] = lambda: runner
    return runner


def _wf_strategy():
    strategy = default_strategy()
    side = apply_parameters(
        strategy.long_side, {"indicators.ema.length": 5, "indicators.sma.length": 8}
    ).model_copy(update={"optimization": small_ranges(fast=(5, 6, 1), slow=(8, 9, 1))})
    return strategy.model_copy(update={"long_side": side}).model_dump(mode="json")


def _walkforward_payload(side="long", in_sample=100, out_of_sample=50):
    """780 one-minute bars in the fixture archive: in-sample 100 / out-of-sample 50 → 13 windows,
    30 unused tail bars, 4 cells per window, 65 units."""
    return {
        "strategy": _wf_strategy(),
        "side": side,
        "data": {"symbol": "QQQ", "timeframe": "1m", **RANGE},
        "objective": "net_pnl",
        "in_sample_bars": in_sample,
        "out_of_sample_bars": out_of_sample,
    }


def _wait_wf(c, job_id, status, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = c.get(f"/aegis/api/walkforward/{job_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"walk-forward {job_id} never reached {status}")


def test_walkforward_plan_and_start_return_the_window_plan(client):
    c, _, repository = client
    _runner(repository)
    plan = c.post("/aegis/api/walkforward/plan", json=_walkforward_payload())
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert {
        k: body[k]
        for k in ("windows", "cells_per_window", "total_units", "unused_tail_bars", "bars")
    } == {
        "windows": 13,
        "cells_per_window": 4,
        "total_units": 65,
        "unused_tail_bars": 30,
        "bars": 780,
    }
    assert body["estimated_seconds"] > 0 and body["ms_per_bar"] > 0
    started = c.post("/aegis/api/walkforward", json=_walkforward_payload())
    assert started.status_code == 202, started.text
    assert set(started.json()) == {
        "job_id",
        "windows",
        "cells_per_window",
        "total_units",
        "estimated_seconds",
    }
    job_id = started.json()["job_id"]
    done = _wait_wf(c, job_id, "done")
    assert done["kind"] == "walkforward" and done["windows"] == {"done": 13, "total": 13}
    assert len(done["result_hash"]) == 64 and done["data"]["research_eligible"] is False
    assert [j["job_id"] for j in c.get("/aegis/api/walkforward").json()] == [job_id]
    assert c.get("/aegis/api/walkforward/does-not-exist").status_code == 404


def test_walkforward_status_progresses_and_cancel_keeps_completed_windows(client):
    c, _, repository = client
    gate = threading.Event()

    def after_unit(done):
        if done == 5:  # window 0 complete
            gate.wait(10)

    _runner(repository, after_unit=after_unit)
    job_id = c.post("/aegis/api/walkforward", json=_walkforward_payload()).json()["job_id"]
    deadline = time.monotonic() + 30
    mid = c.get(f"/aegis/api/walkforward/{job_id}").json()
    while mid["progress"]["done"] < 5 and time.monotonic() < deadline:
        mid = c.get(f"/aegis/api/walkforward/{job_id}").json()
    assert mid["status"] == "running" and mid["windows"] == {"done": 1, "total": 13}
    assert [r["status"] for r in mid["window_records"][:2]] == ["done", "pending"]
    assert mid["stitched"]["metrics"]["trade_count"] == len(
        mid["window_records"][0]["oos"]["trades"]
    )
    assert c.post(f"/aegis/api/walkforward/{job_id}/cancel").json() == {"cancelled": True}
    gate.set()
    cancelled = _wait_wf(c, job_id, "cancelled")
    assert cancelled["windows"]["done"] == 1 and cancelled["result_hash"] is None
    assert c.post(f"/aegis/api/walkforward/{job_id}/cancel").json() == {"cancelled": False}


def test_cross_kind_busy_is_409_and_first_continues(client):
    c, _, repository = client
    gate = threading.Event()

    def after_unit(done):
        if done == 1:
            gate.wait(10)

    _runner(repository, after_unit=after_unit)
    first = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, first, "running")
    blocked = c.post("/aegis/api/walkforward", json=_walkforward_payload())
    assert blocked.status_code == 409 and blocked.json() == {
        "detail": "an optimization is already running"
    }
    gate.set()
    assert _wait(c, first, "done")["progress"] == {"done": 9, "total": 9}
    gate.clear()
    second = c.post("/aegis/api/walkforward", json=_walkforward_payload()).json()["job_id"]
    _wait_wf(c, second, "running")
    blocked = c.post("/aegis/api/optimize", json=_optimize_payload())
    assert blocked.status_code == 409
    gate.set()
    assert _wait_wf(c, second, "done")["windows"] == {"done": 13, "total": 13}


def test_walkforward_too_short_range_is_422_with_bar_counts(client):
    c, _, repository = client
    _runner(repository)
    short = _walkforward_payload(in_sample=700, out_of_sample=100)  # 780 - 700 < 100
    plan = c.post("/aegis/api/walkforward/plan", json=short)
    assert plan.status_code == 422 and "range too short: 780 bars" in plan.json()["detail"]
    assert c.post("/aegis/api/walkforward", json=short).status_code == 422
    assert (
        c.post(
            "/aegis/api/walkforward/plan", json={**_walkforward_payload(), "out_of_sample_bars": 10}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/aegis/api/walkforward/plan",
            json={**_walkforward_payload(), "data": {"symbol": "ZZZ", "timeframe": "1m", **RANGE}},
        ).status_code
        == 404
    )


def test_cancel_unknown_job_is_404_for_both_kinds(client):
    c, _, repository = client
    _runner(repository)
    assert c.post("/aegis/api/optimize/does-not-exist/cancel").status_code == 404
    assert c.post("/aegis/api/walkforward/does-not-exist/cancel").status_code == 404


def test_backtest_reuses_the_store_cache_across_requests(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    data = {"symbol": "QQQ", "timeframe": "15m", **RANGE}
    first = c.post("/aegis/api/backtest", json={"strategy": strategy, "data": data}).json()
    second = c.post("/aegis/api/backtest", json={"strategy": strategy, "data": data}).json()
    # One run already reuses the long side's series for the short side (2 hits); a repeat on the
    # same bars reuses every series (4 hits) because the store cache kept them.
    assert first["cache_hits"] == 2 and second["cache_hits"] == 4
    assert first["result_hash"] == second["result_hash"]


def test_status_routes_refuse_the_other_kind(client):
    c, _, repository = client
    _runner(repository)
    optimization = c.post("/aegis/api/optimize", json=_optimize_payload()).json()["job_id"]
    _wait(c, optimization, "done")
    walk = c.post("/aegis/api/walkforward", json=_walkforward_payload()).json()["job_id"]
    _wait_wf(c, walk, "done")
    assert c.get(f"/aegis/api/walkforward/{optimization}").status_code == 404
    assert c.get(f"/aegis/api/optimize/{walk}").status_code == 404
    assert c.post(f"/aegis/api/walkforward/{optimization}/cancel").status_code == 404
    assert c.get(f"/aegis/api/optimize/{optimization}").status_code == 200


def test_backtest_with_a_rule_on_a_removed_indicator_is_422_naming_it(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    strategy["long_side"]["indicators"] = [
        i for i in strategy["long_side"]["indicators"] if i["id"] != "sma"
    ]
    strategy["long_side"]["optimization"] = []
    payload = {"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}}
    response = c.post("/aegis/api/backtest", json=payload)
    assert response.status_code == 422
    assert "'sma'" in response.text


def test_backtest_with_a_range_on_a_removed_indicator_is_422_naming_the_path(client):
    c, _, _ = client
    strategy = default_strategy().model_dump(mode="json")
    strategy["long_side"]["optimization"].append(
        {"path": "indicators.rsi.length", "start": 7, "stop": 21, "step": 7}
    )
    payload = {"strategy": strategy, "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE}}
    response = c.post("/aegis/api/backtest", json=payload)
    assert response.status_code == 422
    assert "indicators.rsi.length" in response.text
