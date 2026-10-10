"""Offline API checks for the Aegis worker routes; no database, synthetic archive on tmp_path."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from products.aegis import api, server
from products.aegis.backtest import BacktestRequest
from products.aegis.data import ArchiveStore
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import default_strategy
from pydantic import ValidationError
from test_aegis_data import write_archive

RANGE = {"start": "2026-10-30", "end": "2026-11-02"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    write_archive(tmp_path, "20260301T000000000000Z", "QQQ", price=100.0)
    store = ArchiveStore(tmp_path)
    repository = JsonRunRepository(tmp_path / "aegis")
    server.app.dependency_overrides[api.get_store] = lambda: store
    server.app.dependency_overrides[api.get_repository] = lambda: repository
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
