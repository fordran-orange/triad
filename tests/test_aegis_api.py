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

pytestmark = pytest.mark.aegis

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


def test_indicators_endpoint_names_outputs_and_panes(client):
    c, _, _ = client
    body = c.post(
        "/aegis/api/indicators",
        json={
            "symbol": "QQQ",
            "timeframe": "15m",
            **RANGE,
            "indicators": [
                {"id": "donchian", "kind": "DONCHIAN", "length": 5},
                {"id": "rsi", "kind": "RSI", "length": 5},
                {"id": "macd", "kind": "MACD", "length": 3, "params": {"slow": 5, "signal": 3}},
            ],
        },
    )
    assert body.status_code == 200, body.text
    body = body.json()
    assert set(body["series"]) == {
        "donchian.upper",
        "donchian.lower",
        "donchian.middle",
        "rsi",
        "macd.line",
        "macd.signal",
        "macd.histogram",
    }
    assert body["outputs"] == {
        "donchian": ["upper", "lower", "middle"],
        "rsi": [],
        "macd": ["line", "signal", "histogram"],
    }
    assert body["pane"] == {"donchian": "price", "rsi": "own", "macd": "own"}
    assert body["series"]["rsi"][4] is None and body["series"]["rsi"][5] is not None


# --- strategy documents (Mission 5 spec §8) ---------------------------------------------------


def test_strategy_routes_round_trip(client):
    c, _, _ = client
    listed = c.get("/aegis/api/strategies").json()
    assert listed[0]["id"] == "ema9-sma30-cross-v1" and listed[0]["builtin"] is True
    created = c.post(
        "/aegis/api/strategies",
        json={"name": "Breakout", "spec": default_strategy().model_dump(mode="json")},
    )
    assert created.status_code == 201, created.text
    doc = created.json()
    assert doc["id"] == "breakout" and doc["spec"]["id"] == "breakout"
    assert c.get("/aegis/api/strategies/breakout").json() == doc
    renamed = c.put("/aegis/api/strategies/breakout", json={"name": "Breakout v2"})
    assert renamed.status_code == 200 and renamed.json()["spec"]["name"] == "Breakout v2"
    copy = c.post("/aegis/api/strategies/breakout/duplicate", json={"name": "Copy"})
    assert copy.status_code == 201 and copy.json()["parent"] == "breakout"
    assert c.delete("/aegis/api/strategies/copy").json() == {"deleted": "copy"}
    assert c.get("/aegis/api/strategies/copy").status_code == 404


def test_strategy_route_refusals(client):
    c, _, _ = client
    assert c.get("/aegis/api/strategies/nope").status_code == 404
    assert c.delete("/aegis/api/strategies/nope").status_code == 404
    builtin = c.put("/aegis/api/strategies/ema9-sma30-cross-v1", json={"name": "x"})
    assert builtin.status_code == 422 and "read-only" in builtin.text
    assert c.delete("/aegis/api/strategies/ema9-sma30-cross-v1").status_code == 422
    assert (
        c.post(
            "/aegis/api/strategies",
            json={"name": "   ", "spec": default_strategy().model_dump(mode="json")},
        ).status_code
        == 422
    )
    spec = default_strategy().model_dump(mode="json")
    spec["long_side"]["entry"]["right"] = "nope"
    bad = c.post("/aegis/api/strategies", json={"name": "Bad", "spec": spec})
    assert bad.status_code == 422 and "nope" in bad.text


def test_backtest_envelope_carries_strategy_identity_outside_the_hash(client):
    from products.aegis.results import result_hash

    c, _, _ = client
    payload = {
        "strategy": default_strategy().model_dump(mode="json"),
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
    }
    body = c.post("/aegis/api/backtest", json=payload).json()
    assert body["strategy_id"] == "ema9-sma30-cross-v1" and len(body["strategy_hash"]) == 64
    assert "strategy_id" not in body["result"] and "strategy_hash" not in body["result"]
    assert body["result_hash"] == result_hash(body["result"])
    [summary] = c.get("/aegis/api/runs").json()
    assert summary["strategy_id"] == "ema9-sma30-cross-v1"


def test_deleting_a_document_a_running_job_uses_is_409(client):
    """Review Focus 5: a running job's persisted summary is a reference."""
    c, _, repository = client
    _runner, gate = _held_runner(repository)
    try:
        doc = c.post(
            "/aegis/api/strategies",
            json={"name": "Held", "spec": small_strategy().model_dump(mode="json")},
        ).json()
        payload = {**_optimize_payload(), "strategy": doc["spec"]}
        started = c.post("/aegis/api/optimize", json=payload)
        assert started.status_code == 202, started.text
        status = c.get(f"/aegis/api/optimize/{started.json()['job_id']}").json()
        assert status["strategy_id"] == "held" and len(status["strategy_hash"]) == 64
        refused = c.delete("/aegis/api/strategies/held")
        assert refused.status_code == 409
        assert "referenced by 0 runs, 1 optimization, 0 walk-forwards" in refused.text
    finally:
        gate.set()


# --- Mission 6: the compiled engine --------------------------------------------------------


def test_status_reports_the_kernel(client):
    c, _, _ = client
    body = c.get("/aegis/api/status").json()
    assert body["kernel_available"] is True and body["kernel_error"] is None


def test_backtest_envelope_names_its_engine(client):
    c, _, _ = client
    payload = {
        "strategy": default_strategy().model_dump(mode="json"),
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
    }
    body = c.post("/aegis/api/backtest", json=payload).json()
    assert body["engine"] == "kernel"
    assert "engine" not in body["result"]
    reference = c.post("/aegis/api/backtest", json={**payload, "engine": "reference"}).json()
    assert reference["engine"] == "reference"
    assert reference["result_hash"] == body["result_hash"]


# --- experiments (Mission 6 spec §5.6, §6) ----------------------------------------------------


def _experiment_body(c, name="four cells", **overrides):
    """A saved breakout document and a 4-cell surface that fits the synthetic 52-bar archive."""
    from test_aegis_surface import pinned

    listed = c.get("/aegis/api/strategies").json()
    doc = next((d for d in listed if d["name"] == "Breakout for experiments"), None)
    if doc is None:
        doc = c.post(
            "/aegis/api/strategies",
            json={"name": "Breakout for experiments", "spec": pinned().model_dump(mode="json")},
        ).json()
    body = {
        "name": name,
        "strategy_id": doc["id"],
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
        "settings": {"initial_capital": 100000, "allocation_fraction": 1},
        "objective": "net_pnl",
        "surface": {
            "parameters": [
                {
                    "path": "long_side.indicators.donchian.length",
                    "start": 10,
                    "stop": 15,
                    "step": 5,
                },
                {"path": "long_side.indicators.rsi.length", "start": 7, "stop": 14, "step": 7},
            ]
        },
        "budget": {"runs": 100},
    }
    body.update(overrides)
    return body


def _wait_experiment(c, experiment_id, statuses, timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = c.get(f"/aegis/api/experiments/{experiment_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"experiment {experiment_id} never reached {statuses}")


def test_experiment_plan_route(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, _ = client
    response = c.post("/aegis/api/experiments/plan", json=_experiment_body(c))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "exhaustive" and body["grid_cells"] == body["valid_cells"] == 4
    assert body["bars"] == 52 and body["workers"] == 2 and body["levers"] == []
    assert body["price_source"] == "starting_guess"  # no experiment has finished on this store
    for key in (
        "planned_runs",
        "first_pass",
        "refinement",
        "sampled_fraction",
        "estimate_seconds",
        "ms_per_cell_bar",
        "skip_reasons",
    ):
        assert key in body
    bad = c.post(
        "/aegis/api/experiments/plan",
        json=_experiment_body(
            c,
            surface={
                "parameters": [
                    {"path": "long_side.indicators.nope.length", "start": 1, "stop": 2, "step": 1}
                ]
            },
        ),
    )
    assert bad.status_code == 422 and "long_side.indicators.nope.length" in bad.text


def test_experiment_runs_pauses_resumes_cancels_and_materializes(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    from products.aegis import experiments as exp

    monkeypatch.setattr(exp, "CHUNK_CELLS", 2)
    c, _, repository = client
    _runner(repository)
    created = c.post("/aegis/api/experiments", json=_experiment_body(c))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    assert created.json()["job_id"]
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert done["progress"]["cells_done"] == 4 and done["engine"] == "kernel"
    listed = c.get("/aegis/api/experiments").json()
    assert any(item["id"] == experiment_id and item["status"] == "done" for item in listed)

    cells = c.get(
        f"/aegis/api/experiments/{experiment_id}/cells?limit=3&sort=combined.net_pnl&descending=true"
    ).json()
    assert cells["total"] == 4 and len(cells["rows"]) == 3
    values = [r["combined.net_pnl"] for r in cells["rows"]]
    assert values == sorted(values, reverse=True)
    curves = c.get(f"/aegis/api/experiments/{experiment_id}/curves?cells=0,1").json()
    assert set(curves) == {"0", "1"} and len(curves["0"]) == 128

    materialized = c.post(f"/aegis/api/experiments/{experiment_id}/cells/0/materialize")
    assert materialized.status_code == 200, materialized.text
    again = c.post(f"/aegis/api/experiments/{experiment_id}/cells/0/materialize").json()
    assert materialized.json()["result_hash"] == again["result_hash"]
    assert (
        materialized.json()["experiment_id"] == experiment_id and materialized.json()["cell"] == 0
    )
    assert c.post(f"/aegis/api/experiments/{experiment_id}/cells/99/materialize").status_code == 404

    assert c.post(f"/aegis/api/experiments/{experiment_id}/pause").status_code == 409  # finished
    assert c.post(f"/aegis/api/experiments/{experiment_id}/resume").status_code == 409
    assert c.delete(f"/aegis/api/experiments/{experiment_id}").json() == {"deleted": experiment_id}
    assert c.get(f"/aegis/api/experiments/{experiment_id}").status_code == 404
    assert c.delete(f"/aegis/api/experiments/{experiment_id}").status_code == 404


def test_experiment_created_queued_while_another_job_runs(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    _runner, gate = _held_runner(repository)
    try:
        started = c.post("/aegis/api/optimize", json=_optimize_payload())
        assert started.status_code == 202
        created = c.post("/aegis/api/experiments", json=_experiment_body(c, name="queued one"))
        assert created.status_code == 202, created.text
        assert created.json()["status"] == "queued" and created.json()["job_id"] is None
        experiment_id = created.json()["experiment_id"]
        assert c.post(f"/aegis/api/experiments/{experiment_id}/resume").status_code == 409
        assert c.delete(f"/aegis/api/experiments/{experiment_id}").status_code == 409
    finally:
        gate.set()
    _wait(c, started.json()["job_id"], "done")
    resumed = c.post(f"/aegis/api/experiments/{experiment_id}/resume")
    assert resumed.status_code == 202, resumed.text
    assert _wait_experiment(c, experiment_id, ("done", "failed"))["status"] == "done"


def test_experiment_route_refusals(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    _runner(repository)
    assert c.get("/aegis/api/experiments/nope").status_code == 404
    assert c.post("/aegis/api/experiments/nope/pause").status_code == 404
    unknown = c.post("/aegis/api/experiments", json=_experiment_body(c, strategy_id="nope"))
    assert unknown.status_code == 404 and "nope" in unknown.text
    eleven = _experiment_body(
        c,
        surface={
            "parameters": [
                {"path": f"long_side.indicators.rsi.length{i}", "start": 1, "stop": 2, "step": 1}
                for i in range(11)
            ]
        },
    )
    assert c.post("/aegis/api/experiments/plan", json=eleven).status_code == 422
    zero = c.post("/aegis/api/experiments/plan", json=_experiment_body(c, budget={"runs": 0}))
    assert zero.status_code == 422 and "runs must be positive" in zero.text
    carried = c.post(
        "/aegis/api/experiments/plan",
        json=_experiment_body(
            c, settings={"initial_capital": 100000, "allocation_fraction": 1, "close_at_end": False}
        ),
    )
    assert carried.status_code == 422 and "settings.close_at_end" in carried.text


def test_experiment_report_decision_and_refine_routes(client, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    c, _, repository = client
    _runner(repository)
    created = c.post("/aegis/api/experiments", json=_experiment_body(c, name="reported"))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    done = _wait_experiment(c, experiment_id, ("done", "failed"))
    assert done["status"] == "done" and done["latest_report"] == 1

    report = c.get(f"/aegis/api/experiments/{experiment_id}/report").json()
    assert report["report_id"] == 1 and "statement" in report and report["objective"] == "net_pnl"
    markdown = c.get(f"/aegis/api/experiments/{experiment_id}/report.md")
    assert markdown.status_code == 200 and markdown.text.startswith("# Recommendation")
    assert markdown.headers["content-type"].startswith("text/markdown")
    again = c.post(
        f"/aegis/api/experiments/{experiment_id}/report",
        json={"objective": "trade_count", "tolerance": 0.2},
    )
    assert again.status_code == 200 and again.json()["report_id"] == 2
    assert (
        c.get(f"/aegis/api/experiments/{experiment_id}/report?n=1").json()["objective"] == "net_pnl"
    )
    assert c.get(f"/aegis/api/experiments/{experiment_id}/report?n=9").status_code == 404
    bad = c.post(f"/aegis/api/experiments/{experiment_id}/report", json={"objective": "sharpe"})
    assert bad.status_code == 422

    decided = c.put(
        f"/aegis/api/experiments/{experiment_id}/decision",
        json={"verdict": "deferred", "notes": "later"},
    )
    assert decided.status_code == 200 and decided.json()["decision"]["verdict"] == "deferred"
    assert (
        c.put(
            f"/aegis/api/experiments/{experiment_id}/decision",
            json={"verdict": "maybe", "notes": ""},
        ).status_code
        == 422
    )

    from products.aegis import experiments as exp

    store = exp.ExperimentStore(repository)
    doc = store.get(experiment_id)
    latest = store.read_report(experiment_id, doc.latest_report)
    if latest["recommendation"] is None:  # 4 cells rarely plateau; give refine something to narrow
        from products.aegis.surface import build_grid

        grid = build_grid(doc.spec, doc.surface)
        latest["recommendation"] = {
            "plateau": 1,
            "centre": {"cell": 0},
            "supported_peak": None,
            "fragile_peaks": [],
            "statement": "x",
        }
        latest["plateaus"] = [{"id": 1, "cells": list(range(grid.size)), "centre": {"cell": 0}}]
        store.write_report(experiment_id, doc.latest_report, latest, "# Recommendation — x\n")
    refined = c.post(f"/aegis/api/experiments/{experiment_id}/refine")
    assert refined.status_code == 201, refined.text
    child = refined.json()
    assert child["parent"] == experiment_id and child["status"] == "queued"
    assert c.get(f"/aegis/api/experiments/{child['id']}").status_code == 200
    latest["recommendation"] = None
    store.write_report(experiment_id, doc.latest_report, latest, "# Recommendation — none\n")
    assert c.post(f"/aegis/api/experiments/{experiment_id}/refine").status_code == 422


def test_a_stored_strategy_that_no_longer_parses_is_422_naming_the_field(client, tmp_path):
    import json

    c, _, _ = client
    created = c.post(
        "/aegis/api/strategies",
        json={"name": "Breakout", "spec": default_strategy().model_dump(mode="json")},
    )
    assert created.status_code == 201, created.text
    path = tmp_path / "aegis" / "strategies" / "breakout.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["spec"]["long_side"]["entry"]["right"] = "nope"
    path.write_text(json.dumps(raw), encoding="utf-8")
    for response in (
        c.get("/aegis/api/strategies/breakout"),
        c.put("/aegis/api/strategies/breakout", json={"name": "Breakout v2"}),
        c.post("/aegis/api/strategies/breakout/duplicate", json={"name": "Copy"}),
    ):
        assert response.status_code == 422, response.text
        assert response.json()["detail"].startswith("strategy breakout no longer parses: spec")
    assert c.delete("/aegis/api/strategies/breakout").json() == {
        "deleted": "breakout"
    }  # still deletable


def test_a_paused_experiment_can_be_cancelled_then_deleted(client, monkeypatch):
    """Review finding 1: every real pause persists the job_id; cancel and delete both refused."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    from products.aegis import experiments as exp
    from products.aegis.strategies import StrategyLibrary

    c, _, repository = client
    _runner(repository)
    store = exp.ExperimentStore(repository)
    body = exp.ExperimentRequest.model_validate(_experiment_body(c, name="paused one"))
    doc = exp.create(store, StrategyLibrary(repository), body, bars=52, max_workers=2)
    repository.save_experiment(
        {**doc.model_dump(mode="json"), "status": "paused", "job_id": "dead"}
    )
    cancelled = c.post(f"/aegis/api/experiments/{doc.id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert c.get(f"/aegis/api/experiments/{doc.id}").json()["status"] == "cancelled"
    assert c.delete(f"/aegis/api/experiments/{doc.id}").json() == {"deleted": doc.id}


def test_resume_continues_a_failed_experiment(client, monkeypatch):
    """Review finding 2c: a failed experiment keeps its cells; resume runs the rest."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    from products.aegis import experiments as exp
    from products.aegis.strategies import StrategyLibrary

    c, _, repository = client
    _runner(repository)
    store = exp.ExperimentStore(repository)
    body = exp.ExperimentRequest.model_validate(_experiment_body(c, name="failed one"))
    doc = exp.create(store, StrategyLibrary(repository), body, bars=52, max_workers=2)
    repository.save_experiment(
        {
            **doc.model_dump(mode="json"),
            "status": "failed",
            "job_id": "dead",
            "error": "ValueError: boom",
        }
    )
    resumed = c.post(f"/aegis/api/experiments/{doc.id}/resume")
    assert resumed.status_code == 202, resumed.text
    finished = _wait_experiment(c, doc.id, ("done", "failed"))
    assert finished["status"] == "done", finished.get("error")
    assert finished["progress"]["cells_done"] == 4 and finished["error"] is None


# --- studies (Mission 8 spec §6) ---------------------------------------------------------------


def _finished_experiment(repository, recommendation=True, status="done"):
    """A finished 4-cell experiment on the synthetic 1m archive (780 bars), saved directly."""
    from products.aegis.experiments import ExperimentDocument, ExperimentStore
    from products.aegis.surface import Budget, Parameter, Surface
    from products.aegis.surface import plan as plan_surface
    from test_aegis_surface import pinned

    surface = Surface(
        parameters=[
            Parameter(path="long_side.indicators.donchian.length", start=10, stop=15, step=5),
            Parameter(path="long_side.indicators.rsi.length", start=7, stop=14, step=7),
        ]
    )
    planned = plan_surface(pinned(), surface, Budget(runs=100), 300, 0.01, 2, "1m")
    document = ExperimentDocument(
        id="four-cells",
        name="four cells",
        strategy_id="breakout",
        strategy_hash="0" * 64,
        spec=pinned(),
        data={"symbol": "QQQ", "timeframe": "1m", **RANGE},
        settings={"initial_capital": 100_000, "allocation_fraction": 1},
        objective="net_pnl",
        surface=surface,
        budget=Budget(runs=100),
        tolerance=0.15,
        seed=1,
        plan=planned.model_dump(mode="json"),
        status=status,
        progress={"cells_done": 4, "cells_planned": 4, "chunks_done": 1, "chunks_total": 1},
        created_at="2026-10-15T00:00:00+00:00",
        updated_at="2026-10-15T00:00:00+00:00",
        latest_report=1,
    )
    store = ExperimentStore(repository)
    store.save(document)
    centre = {
        "cell": 1,
        "params": {
            "long_side.indicators.donchian.length": 10.0,
            "long_side.indicators.rsi.length": 14.0,
        },
    }
    store.write_report(
        document.id, 1, {"recommendation": {"centre": centre} if recommendation else None}, "# r"
    )
    return document


STUDY_BODY = {
    "experiment_id": "four-cells",
    "symbols": ["QQQ", "SPY"],
    "in_sample_bars": 300,
    "out_of_sample_bars": 150,
}


def _wait_study(c, study_id, statuses, timeout=180.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = c.get(f"/aegis/api/studies/{study_id}").json()
        if body["status"] in statuses:
            return body
        time.sleep(0.05)
    raise AssertionError(f"study {study_id} never reached {statuses}")


def test_study_routes_plan_create_get_decide_delete(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0)
    c, _, repository = client
    _runner(repository)
    _finished_experiment(repository)
    plan = c.post("/aegis/api/studies/plan", json=STUDY_BODY)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert [s["symbol"] for s in body["symbols"]] == ["QQQ", "SPY"]
    assert [s["windows"] for s in body["symbols"]] == [3, 3]  # (780 - 300) // 150
    assert body["symbols"][0]["cells_per_window"] == 4 and body["total_runs"] == 24
    created = c.post("/aegis/api/studies", json={**STUDY_BODY, "name": "walk four"})
    assert created.status_code == 202, created.text
    study_id = created.json()["study_id"]
    assert created.json()["job_id"] and created.json()["status"] == "running"
    started = time.perf_counter()
    c.get(f"/aegis/api/studies/{study_id}")
    assert time.perf_counter() - started < 0.5  # the status route answers while it runs
    done = _wait_study(c, study_id, ("done", "failed"))
    assert done["status"] == "done", done.get("error")
    assert done["report"]["raw_archive"] is True and set(done["windows"]) == {"QQQ", "SPY"}
    listed = c.get("/aegis/api/studies").json()
    assert [s["id"] for s in listed] == [study_id]
    assert c.get("/aegis/api/studies?experiment_id=four-cells").json()[0]["id"] == study_id
    assert c.get("/aegis/api/studies?experiment_id=other").json() == []
    cells = c.get(f"/aegis/api/studies/{study_id}/windows/QQQ/0/cells?limit=2").json()
    assert cells["total"] == 4 and len(cells["rows"]) == 2
    assert c.get(f"/aegis/api/studies/{study_id}/windows/QQQ/9/cells").status_code == 404
    assert c.get(f"/aegis/api/studies/{study_id}/windows/ZZZ/0/cells").status_code == 404
    markdown = c.get(f"/aegis/api/studies/{study_id}/report.md")
    assert markdown.status_code == 200 and markdown.text.startswith("# Plateau walk-forward:")
    assert "RAW ARCHIVE · NOT RESEARCH-ELIGIBLE" in markdown.text
    decided = c.put(
        f"/aegis/api/studies/{study_id}/decision",
        json={"verdict": "accepted", "notes": "walk it on more symbols"},
    )
    assert decided.status_code == 200 and decided.json()["decision"]["verdict"] == "accepted"
    assert c.get("/aegis/api/studies").json()[0]["decision"]["notes"] == "walk it on more symbols"
    # Review Focus 4: a study's parent is part of its evidence.
    refused = c.delete("/aegis/api/experiments/four-cells")
    assert refused.status_code == 409 and study_id in refused.json()["detail"]
    assert c.delete(f"/aegis/api/studies/{study_id}").json() == {"deleted": study_id}
    assert c.get(f"/aegis/api/studies/{study_id}").status_code == 404
    assert c.delete("/aegis/api/experiments/four-cells").status_code == 200


def test_study_route_refusals(client, tmp_path, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0)
    c, _, repository = client
    _finished_experiment(repository)
    assert (
        c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "experiment_id": "nope"}).status_code
        == 404
    )
    unknown = c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "symbols": ["ZZZ"]})
    assert unknown.status_code == 422 and "unknown symbol 'ZZZ'" in unknown.text
    floor = c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "in_sample_bars": 30})
    assert floor.status_code == 422 and "in_sample_bars 30 below 35" in floor.text
    short = c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "in_sample_bars": 700})
    assert short.status_code == 422 and "range too short" in short.text
    assert c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "symbols": []}).status_code == 422

    _held, gate = _held_runner(repository)
    try:
        started = c.post("/aegis/api/optimize", json=_optimize_payload())
        assert started.status_code == 202
        busy = c.post("/aegis/api/studies", json=STUDY_BODY)
        assert busy.status_code == 409 and "another job is running" in busy.text
        assert c.get("/aegis/api/studies").json() == []  # nothing left queued behind the refusal
    finally:
        gate.set()
    _wait(c, started.json()["job_id"], "done")

    _runner(repository)
    from products.aegis.studies import StudyStore

    created = c.post("/aegis/api/studies", json=STUDY_BODY).json()
    study_id = created["study_id"]
    _wait_study(c, study_id, ("done", "failed"))
    assert c.post(f"/aegis/api/studies/{study_id}/pause").status_code == 409
    assert c.post(f"/aegis/api/studies/{study_id}/resume").status_code == 409
    assert (
        c.put(f"/aegis/api/studies/{study_id}/decision", json={"verdict": "maybe"}).status_code
        == 422
    )
    store = StudyStore(repository)
    paused = store.get(study_id).model_copy(update={"status": "paused"})
    store.save(paused)
    gone = c.delete(f"/aegis/api/studies/{study_id}")
    assert gone.status_code == 409 and "cancel it first" in gone.text
    assert c.post(f"/aegis/api/studies/{study_id}/cancel").json() == {"cancelled": True}
    assert c.get(f"/aegis/api/studies/{study_id}").json()["status"] == "cancelled"
    assert c.delete(f"/aegis/api/studies/{study_id}").status_code == 200
    assert c.post("/aegis/api/studies/nope/pause").status_code == 404


def test_a_study_of_an_unfinished_experiment_is_refused(client, monkeypatch):
    c, _, repository = client
    _finished_experiment(repository, status="running")
    refused = c.post("/aegis/api/studies/plan", json={**STUDY_BODY, "symbols": ["QQQ"]})
    assert refused.status_code == 422
    assert "a study needs a finished experiment with a report" in refused.text


def test_a_decision_waits_until_the_study_has_stopped(client, tmp_path, monkeypatch):
    """Review finding: a decision saved on a running study was overwritten by the runner's next
    save of its own copy of the document; it is refused until the study stops."""
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    write_archive(tmp_path, "20260301T000000000000Z", "SPY", price=400.0)
    c, _, repository = client
    gate = threading.Event()

    def hold(done):
        if done == 1:
            gate.wait(30)

    _runner(repository, after_unit=hold)
    _finished_experiment(repository)
    try:
        created = c.post("/aegis/api/studies", json=STUDY_BODY)
        assert created.status_code == 202, created.text
        study_id = created.json()["study_id"]
        deadline = time.monotonic() + 60
        while c.get(f"/aegis/api/studies/{study_id}").json()["progress"]["windows_done"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        refused = c.put(
            f"/aegis/api/studies/{study_id}/decision",
            json={"verdict": "accepted", "notes": "early"},
        )
        assert refused.status_code == 409 and "is running" in refused.text
    finally:
        gate.set()
    _wait_study(c, study_id, ("done", "failed"))
    decided = c.put(
        f"/aegis/api/studies/{study_id}/decision", json={"verdict": "accepted", "notes": "after"}
    )
    assert decided.status_code == 200
    assert c.get(f"/aegis/api/studies/{study_id}").json()["decision"]["notes"] == "after"


# --- the Results library (Mission 9) ---------------------------------------------------------------


def test_library_route_lists_and_filters(client):
    c, _, repository = client
    _finished_experiment(repository)
    body = c.get("/aegis/api/library").json()
    assert body["total"] >= 1 and body["preparing"] == 0
    assert any(e["kind"] == "experiment" and e["id"] == "four-cells" for e in body["entries"])
    only = c.get("/aegis/api/library", params={"kind": "experiment"}).json()
    assert {e["kind"] for e in only["entries"]} == {"experiment"}
    assert c.get("/aegis/api/library", params={"q": "nothing like this"}).json()["total"] == 0
    assert c.get("/aegis/api/library", params={"limit": 500}).status_code == 422
    assert c.get("/aegis/api/library", params={"kind": "nope"}).status_code == 422


def test_experiment_delete_now_moves_to_the_trash(client):
    c, _, repository = client
    _finished_experiment(repository)
    assert c.delete("/aegis/api/experiments/four-cells").json() == {"deleted": "four-cells"}
    assert c.get("/aegis/api/experiments/four-cells").status_code == 404
    trashed = c.get("/aegis/api/library", params={"deleted": True}).json()
    assert [(e["kind"], e["id"]) for e in trashed["entries"]] == [("experiment", "four-cells")]
    assert c.post("/aegis/api/library/experiment/four-cells/restore").json() == {
        "restored": "four-cells"
    }
    assert c.get("/aegis/api/experiments/four-cells").status_code == 200


def test_library_annotation_delete_restore_and_empty_routes(client):
    c, _, repository = client
    _finished_experiment(repository)
    saved = c.put(
        "/aegis/api/library/experiment/four-cells/annotation",
        json={"label": "the four", "notes": "routes", "starred": True},
    )
    assert saved.status_code == 200 and saved.json()["label"] == "the four"
    assert (
        c.put(
            "/aegis/api/library/experiment/four-cells/annotation", json={"label": "x" * 81}
        ).status_code
        == 422
    )
    assert (
        c.put("/aegis/api/library/experiment/nope/annotation", json={"label": "x"}).status_code
        == 404
    )
    assert (
        c.put("/aegis/api/library/nope/four-cells/annotation", json={"label": "x"}).status_code
        == 404
    )
    assert c.delete("/aegis/api/library/experiment/four-cells").json() == {"deleted": "four-cells"}
    assert c.delete("/aegis/api/library/experiment/four-cells").status_code == 404
    assert c.post(
        "/aegis/api/library/trash/empty",
        json={"items": [{"kind": "experiment", "id": "four-cells"}]},
    ).json() == {"erased": 1}
    assert c.post("/aegis/api/library/experiment/four-cells/restore").status_code == 404
