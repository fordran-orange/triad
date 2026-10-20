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


# --- Task 2: labels, stars and the restorable delete ----------------------------------------------


from products.aegis.library import Refused
from products.aegis.strategies import StrategyLibrary, StrategyReferenced


def test_delete_moves_each_kind_to_the_trash_and_restore_brings_it_back(world):
    repository, library, run = world
    (repository.root / "experiments" / "exp-a.cells").mkdir(exist_ok=True)
    study_doc = repository.get_study("study-a")
    repository.delete_study("study-a")  # the experiment may only go once its studies are gone
    before = {
        kind: repository.read_document(folder, ident)
        for kind, folder, ident in (
            ("backtest", "runs", "run-a"),
            ("optimization", "optimizations", "opt-a"),
            ("walkforward", "walkforward", "wf-a"),
            ("experiment", "experiments", "exp-a"),
        )
    }
    for kind, ident in (
        ("backtest", "run-a"),
        ("optimization", "opt-a"),
        ("walkforward", "wf-a"),
        ("experiment", "exp-a"),
    ):
        library.delete(kind, ident)
    assert library.query(LibraryQuery())["total"] == 0
    assert not (repository.root / "experiments" / "exp-a.cells").exists()
    trashed = library.query(LibraryQuery(deleted=True))
    assert {(e.kind, e.id) for e in trashed["entries"]} == {
        ("backtest", "run-a"),
        ("optimization", "opt-a"),
        ("walkforward", "wf-a"),
        ("experiment", "exp-a"),
    }
    assert all(e.status == "deleted" and e.deleted_at for e in trashed["entries"])
    for kind, ident in (
        ("backtest", "run-a"),
        ("optimization", "opt-a"),
        ("walkforward", "wf-a"),
        ("experiment", "exp-a"),
    ):
        library.restore(kind, ident)
    assert repository.get_run("run-a")["result_hash"] == run["result_hash"]
    for kind, folder, ident in (
        ("backtest", "runs", "run-a"),
        ("optimization", "optimizations", "opt-a"),
        ("walkforward", "walkforward", "wf-a"),
        ("experiment", "experiments", "exp-a"),
    ):
        assert repository.read_document(folder, ident) == before[kind], kind
    assert (repository.root / "experiments" / "exp-a.cells").is_dir()
    assert library.query(LibraryQuery(deleted=True))["total"] == 0
    repository.save_study(study_doc)
    library.delete("study", "study-a")
    library.restore("study", "study-a")
    assert repository.get_study("study-a")["name"] == "walk breakout"


def test_delete_refusals(world):
    repository, library, _run = world
    with pytest.raises(Refused, match="experiment exp-a has studies: study-a; delete them first"):
        library.delete("experiment", "exp-a")
    for status in ("queued", "running"):
        doc = repository.get_optimization("opt-a")
        repository.save_optimization({**doc, "status": status})
        with pytest.raises(Refused, match=f"optimization opt-a is {status}; cancel it first"):
            library.delete("optimization", "opt-a")
        wf = repository.get_walkforward("wf-a")
        repository.save_walkforward({**wf, "status": status})
        with pytest.raises(Refused, match=f"walkforward wf-a is {status}; cancel it first"):
            library.delete("walkforward", "wf-a")
    for status in ("queued", "running", "paused"):
        study = repository.get_study("study-a")
        repository.save_study({**study, "status": status})
        with pytest.raises(Refused, match=f"study study-a is {status}; cancel it first"):
            library.delete("study", "study-a")
    repository.delete_study("study-a")
    for status in ("queued", "running", "paused"):
        exp = repository.get_experiment("exp-a")
        repository.save_experiment({**exp, "status": status})
        with pytest.raises(Refused, match=f"experiment exp-a is {status}; cancel it first"):
            library.delete("experiment", "exp-a")
    with pytest.raises(KeyError):
        library.delete("backtest", "no-such-run")


def test_empty_erases_only_the_trash(world):
    repository, library, _run = world
    library.annotations.set("backtest", "run-a", "keep me", "", True)
    library.delete("backtest", "run-a")
    assert library.empty([("backtest", "run-a")]) == 1
    assert not (repository.root / "trash" / "runs" / "run-a").exists()
    assert "backtest:run-a" not in library.annotations.all()
    assert library.query(LibraryQuery())["total"] == 4  # the live items are untouched
    library.delete("optimization", "opt-a")
    library.delete("walkforward", "wf-a")
    assert library.empty(None) == 2 and library.query(LibraryQuery(deleted=True))["total"] == 0


def test_a_trashed_id_is_never_reused(world):  # Review Focus 4
    repository, library, _run = world
    store = ExperimentStore(repository)
    repository.delete_study("study-a")
    exp = store.get("exp-a")
    library.delete("experiment", "exp-a")
    assert store.free_id("exp a") != "exp-a"
    clash = exp.model_copy(update={"id": store.free_id("exp a")})
    store.save(clash)
    library.restore("experiment", "exp-a")
    assert store.get("exp-a").name == exp.name and store.get(clash.id).id == clash.id


def test_restore_order_of_an_experiment_and_its_studies(world):  # Review Focus 5
    repository, library, _run = world
    library.delete("study", "study-a")
    library.delete("experiment", "exp-a")  # its only study is in the trash
    with pytest.raises(Refused, match="study study-a needs its experiment exp-a restored first"):
        library.restore("study", "study-a")
    library.restore("experiment", "exp-a")
    library.restore("study", "study-a")
    assert repository.get_study("study-a")["experiment_id"] == "exp-a"


def test_trashed_runs_do_not_hold_a_strategy(world):
    repository, library, run = world
    strategies = StrategyLibrary(repository)
    document = strategies.create("Held by a run", default_strategy())
    repository.save_run({**run, "run_id": "held", "strategy_id": document.id})
    with pytest.raises(StrategyReferenced):
        strategies.delete(document.id)
    library.delete("backtest", "held")
    strategies.delete(document.id)


def test_annotations_round_trip_and_limits(world):
    _repository, library, _run = world
    library.annotations.set("backtest", "run-a", "baseline", "the reference run", True)
    entry = next(e for e in library.query(LibraryQuery(starred=True))["entries"])
    assert (entry.id, entry.label, entry.notes, entry.starred) == (
        "run-a",
        "baseline",
        "the reference run",
        True,
    )
    assert [e.id for e in library.query(LibraryQuery(q="reference"))["entries"]] == ["run-a"]
    with pytest.raises(ValueError, match="label"):
        library.annotations.set("backtest", "run-a", "x" * 81, "", False)
    with pytest.raises(ValueError, match="notes"):
        library.annotations.set("backtest", "run-a", "", "x" * 2001, False)


# --- the final review's fix pass -----------------------------------------------------------------


def test_the_headline_cache_never_overwrites_a_concurrent_save(world):  # final review I2
    repository, library, _run = world
    doc = {**save_walkforward(repository, job_id="wf-race")}
    library.entries()
    repository.save_walkforward(doc)  # any save drops the cached block
    compute = library._block

    def a_save_lands_meanwhile(kind, identifier):
        block = compute(kind, identifier)
        if identifier == "wf-race":
            repository.save_walkforward({**doc, "status": "cancelled"})
        return block

    library._block = a_save_lands_meanwhile
    library.entries()
    sidecar = repository.root / "walkforward" / "wf-race.summary.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["status"] == "cancelled"


def test_a_running_job_is_listed_without_rewriting_its_sidecar(world):  # final review I2
    repository, library, _run = world
    doc = save_walkforward(repository, job_id="wf-live")
    repository.save_walkforward({**doc, "status": "running"})
    sidecar = repository.root / "walkforward" / "wf-live.summary.json"
    before = sidecar.read_text(encoding="utf-8")
    entries, preparing = library.entries()
    entry = next(e for e in entries if e.id == "wf-live")
    assert entry.status == "running" and entry.headline["windows"] == 4 and preparing == 0
    assert sidecar.read_text(encoding="utf-8") == before


def test_an_unreadable_document_is_ready_with_an_empty_headline(world):  # final review I3
    repository, library, _run = world
    repository.save_run({"run_id": "broken", "created_at": "2026-10-01T00:00:00+00:00"})
    entries = {e.id: e for e in library.query(LibraryQuery(kinds=["backtest"]))["entries"]}
    assert entries["broken"].headline == {} and entries["broken"].ready is True
    waiting = library.query(LibraryQuery(kinds=["backtest"]), budget_seconds=0)
    assert all(e.ready for e in waiting["entries"])  # cached blocks stay ready
    repository.save_run({"run_id": "new", "created_at": "2026-10-02T00:00:00+00:00"})
    fresh = {e.id: e for e in library.query(LibraryQuery(), budget_seconds=0)["entries"]}
    assert fresh["new"].ready is False


def test_an_annotation_survives_a_busy_file(world, monkeypatch):  # final review I5
    from pathlib import Path

    _repository, library, _run = world
    real = Path.replace
    refusals = []

    def busy_once(self, target):
        if self.name.startswith("annotations") and not refusals:
            refusals.append(self.name)
            raise PermissionError("Windows: another handle is open")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", busy_once)
    library.annotations.set("backtest", "run-a", label="kept")
    assert refusals and library.annotations.get("backtest", "run-a")["label"] == "kept"


def test_a_busy_read_never_wipes_the_other_annotations(world, monkeypatch):  # final review I5
    from pathlib import Path

    _repository, library, _run = world
    library.annotations.set("backtest", "run-a", label="first")
    real = Path.read_text
    refusals = []

    def busy_once(self, *args, **kwargs):
        if self.name == "annotations.json" and not refusals:
            refusals.append(self.name)
            raise PermissionError("Windows: another handle is open")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", busy_once)
    library.annotations.set("optimization", "opt-a", starred=True)
    assert refusals
    assert library.annotations.get("backtest", "run-a")["label"] == "first"
    assert library.annotations.get("optimization", "opt-a")["starred"] is True


def _pieces(path):
    return sorted(p.name for p in path.iterdir()) if path.is_dir() else []


def test_an_interrupted_restore_is_finished_not_stranded(world):  # final review I4
    import shutil

    repository, library, _run = world
    live = repository.root / "experiments"
    trash = repository.root / "trash" / "experiments" / "exp-a"
    library.delete("study", "study-a")
    library.delete("experiment", "exp-a")
    assert "exp-a.reports" in _pieces(trash)
    shutil.move(str(trash / "exp-a.json"), str(live / "exp-a.json"))  # stopped after the document
    assert "exp-a" not in [e.id for e in library.trashed()]  # the document's place decides
    assert library.empty([("experiment", "exp-a")]) == 0 and "exp-a.reports" in _pieces(trash)
    library.restore("experiment", "exp-a")
    assert not trash.exists() and {"exp-a.reports", "exp-a.summary.json"} <= set(_pieces(live))


def test_an_interrupted_delete_is_finished_by_the_next_delete(world):  # final review I4
    import shutil

    repository, library, _run = world
    live = repository.root / "experiments"
    trash = repository.root / "trash" / "experiments" / "exp-a"
    library.delete("study", "study-a")
    trash.mkdir(parents=True)
    (trash / "trash.json").write_text(json.dumps({"kind": "experiment", "id": "exp-a"}))
    shutil.move(str(live / "exp-a.reports"), str(trash / "exp-a.reports"))  # stopped early
    assert "exp-a" in [e.id for e in library.entries()[0]]
    assert "exp-a" not in [e.id for e in library.trashed()]
    library.delete("experiment", "exp-a")
    assert {"exp-a.json", "exp-a.reports", "exp-a.summary.json"} <= set(_pieces(trash))
    assert not (live / "exp-a.json").exists()
    library.restore("experiment", "exp-a")
    assert not trash.exists() and "exp-a.reports" in _pieces(live)


def test_startup_finishes_a_stranded_move(world):  # final review I4
    import shutil

    repository, library, _run = world
    trash = repository.root / "trash" / "studies" / "study-a"
    library.delete("study", "study-a")
    shutil.move(str(trash / "study-a.json"), str(repository.root / "studies" / "study-a.json"))
    repository.heal_trash()
    assert not trash.exists() and repository.read_document("studies", "study-a")["id"] == "study-a"


def test_a_torn_trash_record_still_lists_and_restores(world):  # final review (minor, folded in)
    repository, library, run = world
    library.delete("backtest", "run-a")
    (repository.root / "trash" / "runs" / "run-a" / "trash.json").write_text("{torn")
    listed = {e.id: e for e in library.trashed()}
    assert listed["run-a"].kind == "backtest" and listed["run-a"].status == "deleted"
    library.restore("backtest", "run-a")
    assert repository.read_document("runs", "run-a")["result_hash"] == run["result_hash"]
