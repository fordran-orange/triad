import json

import pytest
from products.aegis.runs import JsonRunRepository


def envelope(run_id, created_at, **extra):
    return {
        "run_id": run_id,
        "created_at": created_at,
        "elapsed_ms": 1,
        "result_hash": "h-" + run_id,
        "data": {"symbol": "QQQ", "timeframe": "1h"},
        "strategy": {"name": "9 EMA / 30 SMA Cross"},
        "result": {"combined": {"metrics": {"net_pnl": 1.0}}},
        **extra,
    }


def test_json_repository_round_trips_run_and_lists_newest_first(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    assert repo.list_runs() == []
    older = envelope("r-old", "2026-10-09T01:00:00+00:00")
    newer = envelope("r-new", "2026-10-09T02:00:00+00:00")
    assert repo.save_run(older) == "r-old"
    assert repo.save_run(newer) == "r-new"
    assert repo.get_run("r-old") == older
    listed = repo.list_runs()
    assert [r["run_id"] for r in listed] == ["r-new", "r-old"]
    assert set(listed[0]) >= {"run_id", "created_at", "result_hash", "data", "strategy"}
    assert "result" not in listed[0]  # summaries stay small
    stored = json.loads((tmp_path / "aegis" / "runs" / "r-new.json").read_text(encoding="utf-8"))
    assert stored == newer


def test_unknown_run_raises_key_error(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    with pytest.raises(KeyError):
        repo.get_run("nope")
    with pytest.raises(ValueError):
        repo.get_run("../escape")


def test_optimizations_round_trip_separately(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    job = {"job_id": "j1", "created_at": "2026-10-09T03:00:00+00:00", "status": "done", "cells": []}
    assert repo.save_optimization(job) == "j1"
    assert repo.get_optimization("j1") == job
    assert [j["job_id"] for j in repo.list_optimizations()] == ["j1"]
    assert repo.list_runs() == []


def test_list_runs_reads_sidecar_summaries_and_tolerates_legacy_files(tmp_path):
    import json

    repository = JsonRunRepository(tmp_path)
    repository.save_run(
        {
            "run_id": "a",
            "created_at": "2026-01-02T00:00:00+00:00",
            "result_hash": "h1",
            "result": {"big": [0] * 1000},
        }
    )
    assert (tmp_path / "runs" / "a.summary.json").is_file()
    (tmp_path / "runs" / "a.json").unlink()  # listing must not need the full envelope
    assert [r["run_id"] for r in repository.list_runs()] == ["a"]
    legacy = {"run_id": "b", "created_at": "2026-01-01T00:00:00+00:00", "result_hash": "h2"}
    (tmp_path / "runs" / "b.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert [r["run_id"] for r in repository.list_runs()] == ["a", "b"]
    assert "result" not in repository.list_runs()[0]


def test_walkforward_kind_round_trips_with_sidecar(tmp_path):
    repository = JsonRunRepository(tmp_path)
    repository.save_walkforward(
        {
            "job_id": "w1",
            "kind": "walkforward",
            "created_at": "2026-01-01T00:00:00+00:00",
            "status": "done",
            "side": "long",
            "windows": {"done": 2, "total": 2},
            "window_records": [{"big": [0] * 100}],
        }
    )
    assert (tmp_path / "walkforward" / "w1.summary.json").is_file()
    assert repository.get_walkforward("w1")["side"] == "long"
    listed = repository.list_walkforwards()
    assert [w["job_id"] for w in listed] == ["w1"] and "window_records" not in listed[0]
    assert listed[0]["windows"] == {"done": 2, "total": 2} and listed[0]["kind"] == "walkforward"
