"""The Results library (Mission 9 spec §4, §6): one index of every saved result with cached
headlines, filters, search, sort and paging; labels, stars and a restorable delete."""

import json

import pytest
from products.aegis.backtest import BacktestRequest, BacktestSettings, run_backtest
from products.aegis.experiments import ExperimentStore
from products.aegis.library import Library, LibraryQuery
from products.aegis.results import envelope
from products.aegis.runs import JsonRunRepository
from products.aegis.strategy import default_strategy
from test_aegis_studies import experiment
from test_aegis_walkforward import wave_bars

pytestmark = pytest.mark.aegis

DATA = {
    "source": "raw_archive",
    "symbol": "QQQ",
    "timeframe": "1h",
    "start": "2024-01-01",
    "end": "2024-02-01",
    "research_eligible": False,
}
ROWS = wave_bars(n=300, period=37.0, amplitude=10.0)


def save_run(repository, run_id="run-a", ema=9, data=DATA, created="2026-10-19T01:00:00+00:00"):
    spec = default_strategy()
    side = spec.long_side.model_copy(
        update={
            "indicators": [
                i.model_copy(update={"length": ema}) if i.id == "ema" else i
                for i in spec.long_side.indicators
            ]
        }
    )
    spec = spec.model_copy(update={"long_side": side})
    settings = BacktestSettings()
    result = run_backtest(BacktestRequest(strategy=spec, bars=ROWS, settings=settings))
    run = envelope(result, spec, settings, data, 5)
    run.update(run_id=run_id, created_at=created)
    repository.save_run(run)
    return run


def save_optimization(repository, job_id="opt-a"):
    cells = [
        {
            "fast": 5.0,
            "slow": 20.0,
            "params": {"indicators.ema.length": 5},
            "metrics": {"net_pnl": -10.0, "mar": None},
        },
        {
            "fast": 7.0,
            "slow": 20.0,
            "params": {"indicators.ema.length": 7},
            "metrics": {"net_pnl": 42.0, "mar": 0.5},
        },
        {
            "fast": 9.0,
            "slow": 20.0,
            "params": {"indicators.ema.length": 9},
            "metrics": {"net_pnl": 12.0, "mar": 0.2},
        },
    ]
    doc = {
        "job_id": job_id,
        "kind": "optimization",
        "side": "long",
        "status": "done",
        "objective": "net_pnl",
        "data": {**DATA, "symbol": "SPY"},
        "strategy": default_strategy().model_dump(mode="json"),
        "strategy_id": "ema9-sma30-cross-v1",
        "progress": {"done": 3, "total": 3},
        "total_cells": 3,
        "cells": cells,
        "created_at": "2026-10-19T02:00:00+00:00",
    }
    repository.save_optimization(doc)
    return doc


def save_walkforward(repository, job_id="wf-a"):
    doc = {
        "job_id": job_id,
        "kind": "walkforward",
        "side": "short",
        "status": "done",
        "objective": "mar",
        "data": {**DATA, "timeframe": "1D"},
        "strategy": default_strategy().model_dump(mode="json"),
        "strategy_id": "ema9-sma30-cross-v1",
        "windows": {"done": 4, "total": 4},
        "stitched": {"metrics": {"net_pnl": 1234.5, "mar": 0.8}, "trades": [], "equity": []},
        "created_at": "2026-10-19T03:00:00+00:00",
    }
    repository.save_walkforward(doc)
    return doc


def save_experiment(repository, recommend=True):
    store = ExperimentStore(repository)
    doc = experiment(bars=120).model_copy(
        update={
            "id": "exp-a",
            "created_at": "2026-10-19T04:00:00+00:00",
            "decision": {"verdict": "accepted", "notes": "", "decided_at": "x"},
        }
    )
    store.save(doc)
    report = {"recommendation": {"centre": {"cell": 1, "params": {}}} if recommend else None}
    store.write_report(doc.id, 1, report, "# r")
    return doc


def save_study(repository):
    doc = {
        "id": "study-a",
        "name": "walk breakout",
        "experiment_id": "exp-a",
        "strategy_id": "breakout",
        "spec": default_strategy().model_dump(mode="json"),
        "symbols": ["QQQ", "SPY"],
        "timeframe": "1h",
        "start": "2016-09-19",
        "end": "2026-09-18",
        "status": "done",
        "objective": "mar",
        "progress": {"windows_done": 7, "windows_total": 7},
        "report": {"summary": "plateau rule ahead of the peak rule on 2 of 2 symbols by MAR"},
        "decision": None,
        "created_at": "2026-10-19T05:00:00+00:00",
    }
    repository.save_study(doc)
    return doc


@pytest.fixture
def world(tmp_path):
    repository = JsonRunRepository(tmp_path / "aegis")
    run = save_run(repository)
    save_optimization(repository)
    save_walkforward(repository)
    save_experiment(repository)
    save_study(repository)
    return repository, Library(repository, ExperimentStore(repository)), run


def by_kind(result):
    return {e.kind: e for e in result["entries"]}


def test_every_kind_becomes_one_entry_with_its_headline(world):
    _repository, library, run = world
    result = library.query(LibraryQuery())
    assert result["total"] == 5 and result["preparing"] == 0
    entries = by_kind(result)
    metrics = run["result"]["combined"]["metrics"]
    assert entries["backtest"].headline == {
        key: metrics[key] for key in ("net_pnl", "net_return", "mar", "max_drawdown", "trade_count")
    }
    assert entries["backtest"].symbols == ["QQQ"] and entries["backtest"].timeframe == "1h"
    assert entries["backtest"].strategy_name == "9 EMA / 30 SMA Cross"
    assert entries["optimization"].headline == {
        "side": "long",
        "cells_run": 3,
        "cells_total": 3,
        "objective": "net_pnl",
        "best": 42.0,
    }
    assert entries["walkforward"].headline == {
        "side": "short",
        "windows": 4,
        "net_pnl": 1234.5,
        "mar": 0.8,
    }
    assert entries["experiment"].headline["recommended"] is True
    assert entries["experiment"].headline["mode"] == "exhaustive"
    assert entries["experiment"].decision["verdict"] == "accepted"
    assert entries["study"].headline == {
        "symbols": ["QQQ", "SPY"],
        "windows": 7,
        "summary_line": "plateau rule ahead of the peak rule on 2 of 2 symbols by MAR",
    }
    assert entries["study"].links == {"experiment_id": "exp-a"}
    assert result["counts_by_kind"] == {
        k: 1 for k in ("backtest", "optimization", "walkforward", "experiment", "study")
    }


def test_filters_search_sort_and_pages(world):
    repository, library, _run = world
    save_run(repository, "run-b", ema=12, created="2026-10-19T06:00:00+00:00")
    save_run(
        repository,
        "run-c",
        ema=5,
        data={**DATA, "symbol": "ITOT"},
        created="2026-10-19T07:00:00+00:00",
    )
    ids = lambda q: [e.id for e in library.query(q)["entries"]]
    assert ids(LibraryQuery(kinds=["backtest"])) == ["run-c", "run-b", "run-a"]
    assert ids(LibraryQuery(kinds=["backtest", "study"]))[0] == "run-c"
    assert ids(LibraryQuery(symbol="ITOT")) == ["run-c"]
    assert ids(LibraryQuery(symbol="SPY")) == ["study-a", "opt-a"]  # a study names several symbols
    assert ids(LibraryQuery(timeframe="1D")) == ["wf-a"]
    assert ids(LibraryQuery(decision="accepted")) == ["exp-a"]
    assert ids(LibraryQuery(q="WALK BREAK")) == ["study-a"]
    assert ids(LibraryQuery(q="sma cross", kinds=["optimization"])) == ["opt-a"]
    by_pnl = ids(LibraryQuery(kinds=["backtest", "walkforward"], sort="net_pnl"))
    assert by_pnl[0] in ("wf-a", "run-a", "run-b", "run-c") and len(by_pnl) == 4
    pnls = [
        e.headline.get("net_pnl") for e in library.query(LibraryQuery(sort="net_pnl"))["entries"]
    ]
    known = [p for p in pnls if p is not None]
    assert known == sorted(known, reverse=True) and pnls[len(known) :] == [None] * (
        len(pnls) - len(known)
    )
    page = library.query(LibraryQuery(offset=2, limit=2))
    assert page["total"] == 7 and len(page["entries"]) == 2
    with pytest.raises(ValueError):
        LibraryQuery(limit=500)


def test_headline_is_cached_and_recomputed_after_a_save(world):
    repository, library, run = world
    library.query(LibraryQuery())
    sidecar = repository.root / "runs" / "run-a.summary.json"
    cached = json.loads(sidecar.read_text(encoding="utf-8"))
    assert cached["library"]["version"] == 1 and cached["library"]["headline"]["trade_count"] >= 0
    repository.save_run(run)  # any save rewrites the sidecar without the cache (plan P1)
    assert "library" not in json.loads(sidecar.read_text(encoding="utf-8"))
    assert (
        by_kind(library.query(LibraryQuery()))["backtest"].headline["net_pnl"]
        == run["result"]["combined"]["metrics"]["net_pnl"]
    )


def test_backfill_is_incremental_and_reports_preparing(tmp_path):  # Review Focus 3
    repository = JsonRunRepository(tmp_path / "aegis")
    for i in range(40):
        save_run(
            repository,
            f"run-{i:02d}",
            created=f"2026-10-19T{i // 4:02d}:{(i % 4) * 10:02d}:00+00:00",
        )
    library = Library(repository, ExperimentStore(repository))
    first = library.query(LibraryQuery(), budget_seconds=0)
    assert first["preparing"] == 40 and all(e.headline == {} for e in first["entries"])
    for _ in range(5):
        if library.query(LibraryQuery(), budget_seconds=1.0)["preparing"] == 0:
            break
    final = library.query(LibraryQuery(), budget_seconds=0)
    assert final["preparing"] == 0 and all(e.headline for e in final["entries"])


def test_index_survives_broken_and_legacy_documents(world):  # Review Focus 1
    repository, library, run = world
    (repository.root / "runs" / "torn.summary.json").write_text("{torn", encoding="utf-8")
    legacy = {k: v for k, v in run.items() if k not in ("data", "settings")}
    legacy["run_id"] = "legacy"
    repository.save_run(legacy)
    broken = {"run_id": "broken", "created_at": "2026-10-01T00:00:00+00:00"}  # no result at all
    repository.save_run(broken)
    entries = {e.id: e for e in library.query(LibraryQuery(kinds=["backtest"]))["entries"]}
    assert entries["legacy"].symbols == [] and entries["legacy"].headline["trade_count"] >= 0
    assert entries["broken"].headline == {} and "run-a" in entries
