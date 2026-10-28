import json

import pytest
from products.aegis.runs import JsonRunRepository, document_path

pytestmark = pytest.mark.aegis


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
    stored = JsonRunRepository._read(document_path(tmp_path / "aegis" / "runs", "r-new"))
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
    document_path(tmp_path / "runs", "a").unlink()  # listing must not need the full envelope
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


def test_strategies_kind_saves_lists_and_deletes(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    document = {
        "id": "breakout",
        "name": "Breakout",
        "spec": {
            "long_side": {"indicators": [{"kind": "DONCHIAN"}]},
            "short_side": {"indicators": []},
        },
        "created_at": "2026-10-11T01:00:00+00:00",
        "updated_at": "2026-10-11T01:00:00+00:00",
        "strategy_hash": "abc",
        "parent": None,
        "builtin": False,
    }
    assert repo.save_strategy(document) == "breakout"
    assert repo.get_strategy("breakout") == document
    [summary] = repo.list_strategies()
    assert (
        summary["id"] == "breakout" and summary["kinds"] == ["DONCHIAN"] and "spec" not in summary
    )
    repo.delete_strategy("breakout")
    assert repo.list_strategies() == []
    assert list((tmp_path / "aegis" / "strategies").iterdir()) == []
    with pytest.raises(KeyError):
        repo.delete_strategy("breakout")


def test_experiments_kind_saves_lists_and_deletes_its_files(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    document = {
        "id": "twelve",
        "name": "twelve cells",
        "strategy_id": "breakout",
        "status": "done",
        "objective": "net_pnl",
        "plan": {
            "mode": "exhaustive",
            "planned_runs": 12,
            "valid_cells": 12,
            "sampled_fraction": 1.0,
        },
        "surface": {"parameters": [{"path": "a", "start": 1, "stop": 2, "step": 1}]},
        "progress": {"cells_done": 12, "cells_planned": 12, "chunks_done": 3, "chunks_total": 3},
        "created_at": "2026-10-12T01:00:00+00:00",
        "updated_at": "2026-10-12T01:00:00+00:00",
    }
    assert repo.save_experiment(document) == "twelve"
    assert repo.get_experiment("twelve") == document
    [summary] = repo.list_experiments()
    assert (
        summary["id"] == "twelve" and summary["mode"] == "exhaustive" and summary["parameters"] == 1
    )
    assert "surface" not in summary
    cells = repo.experiment_dir("twelve", "cells")
    cells.mkdir(parents=True)
    (cells / "000000.parquet").write_bytes(b"x")
    reports = repo.experiment_dir("twelve", "reports")
    reports.mkdir(parents=True)
    (reports / "1.json").write_text("{}", encoding="utf-8")
    assert [s["id"] for s in repo.list_experiments()] == ["twelve"]  # never the report
    repo.delete_experiment("twelve")
    assert repo.list_experiments() == [] and not cells.exists() and not reports.exists()
    with pytest.raises(KeyError):
        repo.delete_experiment("twelve")


def test_studies_kind_round_trips_and_deletes_its_windows(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    document = {
        "id": "walk-qqq",
        "name": "walk QQQ",
        "experiment_id": "twelve",
        "status": "done",
        "objective": "mar",
        "symbols": ["QQQ", "SPY"],
        "progress": {"windows_done": 3, "windows_total": 3},
        "decision": None,
        "windows": {"QQQ": [{"index": 0}]},
        "report": {"summary": "x"},
        "created_at": "2026-10-16T01:00:00+00:00",
        "updated_at": "2026-10-16T01:00:00+00:00",
    }
    assert repo.save_study(document) == "walk-qqq"
    assert repo.get_study("walk-qqq") == document
    [summary] = repo.list_studies()
    assert summary["id"] == "walk-qqq" and summary["experiment_id"] == "twelve"
    assert summary["symbols"] == ["QQQ", "SPY"] and summary["status"] == "done"
    assert "windows" not in summary and "report" not in summary
    windows = repo.study_dir("walk-qqq")
    (windows / "QQQ").mkdir(parents=True)
    (windows / "QQQ" / "0.json").write_text("{}", encoding="utf-8")
    (windows / "QQQ" / "0.parquet").write_bytes(b"x")
    assert [s["id"] for s in repo.list_studies()] == ["walk-qqq"]  # never a window file
    repo.delete_study("walk-qqq")
    assert repo.list_studies() == [] and not windows.exists()
    with pytest.raises(KeyError):
        repo.delete_study("walk-qqq")


# --- Mission 11: compressed saved documents ------------------------------------------------------


def _canonical(document) -> bytes:
    return json.dumps(document, sort_keys=True, allow_nan=False).encode("utf-8")


def _gz(path, document) -> None:
    import gzip

    path.write_bytes(gzip.compress(_canonical(document), compresslevel=6, mtime=0))


def test_a_saved_document_is_compressed_and_reads_back_equal(tmp_path):
    import gzip

    from products.aegis.runs import COMPRESS_LEVEL, document_path

    repo = JsonRunRepository(tmp_path / "aegis")
    run = envelope("r1", "2026-10-21T01:00:00+00:00", note="é")
    repo.save_run(run)
    folder = tmp_path / "aegis" / "runs"
    assert COMPRESS_LEVEL == 6
    assert (
        document_path(folder, "r1") == folder / "r1.json.gz" and not (folder / "r1.json").exists()
    )
    raw = (folder / "r1.json.gz").read_bytes()
    assert gzip.decompress(raw) == _canonical(run) and raw[4:8] == b"\0\0\0\0"  # mtime 0
    assert repo.get_run("r1") == run
    sidecar = json.loads((folder / "r1.summary.json").read_text(encoding="utf-8"))
    assert sidecar["run_id"] == "r1"  # the sidecar stays plain JSON
    assert document_path(folder, "absent") is None


def test_a_plain_document_still_reads(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "runs"
    folder.mkdir(parents=True)
    old = envelope("old", "2026-10-01T01:00:00+00:00")
    (folder / "old.json").write_text(json.dumps(old), encoding="utf-8")
    assert repo.get_run("old") == old
    assert [r["run_id"] for r in repo.list_runs()] == ["old"]


def test_saving_again_leaves_one_compressed_document(tmp_path):  # Review Focus 4
    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "experiments"
    folder.mkdir(parents=True)
    (folder / "x.json").write_text(json.dumps({"id": "x", "status": "queued"}), encoding="utf-8")
    for status in ("running", "running", "done"):
        repo.save_experiment({"id": "x", "status": status})
    assert sorted(p.name for p in folder.iterdir()) == ["x.json.gz", "x.summary.json"]
    assert repo.get_experiment("x")["status"] == "done"


def test_both_forms_read_the_compressed_one(tmp_path):  # Review Focus 1
    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "runs"
    folder.mkdir(parents=True)
    old = envelope("x", "2026-10-01T01:00:00+00:00", version="old")
    new = envelope("x", "2026-10-01T01:00:00+00:00", version="new")
    (folder / "x.json").write_text(json.dumps(old), encoding="utf-8")
    _gz(folder / "x.json.gz", new)  # a crash after writing the new form, before removing the old
    assert repo.get_run("x")["version"] == "new"
    assert [r["run_id"] for r in repo.list_runs()] == ["x"]
    repo.move_to_trash("runs", "x", {"deleted_at": "2026-10-21T02:00:00+00:00"})
    assert not (folder / "x.json").exists() and not (folder / "x.json.gz").exists()
    repo.restore_from_trash("runs", "x")
    assert (folder / "x.json").exists() and (folder / "x.json.gz").exists()
    assert repo.get_run("x")["version"] == "new"


def test_a_corrupt_compressed_document_reads_as_torn(tmp_path):  # Review Focus 3
    repo = JsonRunRepository(tmp_path / "aegis")
    repo.save_run(envelope("good", "2026-10-21T01:00:00+00:00"))
    folder = tmp_path / "aegis" / "runs"
    (folder / "bad.json.gz").write_bytes(b"\x1f\x8b\x08\x00not really gzip")
    with pytest.raises(ValueError):
        repo.get_run("bad")
    assert [r["run_id"] for r in repo.list_runs()] == ["good"]  # no sidecar: skipped, not fatal


def test_trash_and_restore_keep_each_form(tmp_path):  # Review Focus 2
    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "runs"
    compressed = envelope("c", "2026-10-21T01:00:00+00:00")
    repo.save_run(compressed)
    plain = envelope("p", "2026-10-01T01:00:00+00:00")
    (folder / "p.json").write_text(json.dumps(plain), encoding="utf-8")
    for run_id in ("c", "p"):
        repo.move_to_trash("runs", run_id, {"deleted_at": "2026-10-21T02:00:00+00:00"})
    assert sorted(i["id"] for i in repo.list_trash()) == ["c", "p"]
    assert repo.read_trashed("runs", "c") == compressed and repo.read_trashed("runs", "p") == plain
    for run_id in ("c", "p"):
        repo.restore_from_trash("runs", run_id)
    assert (folder / "c.json.gz").exists() and (folder / "p.json").exists()
    assert repo.get_run("c")["result_hash"] == "h-c" and repo.get_run("p")["result_hash"] == "h-p"
    # restoring over a live item in either form refuses
    repo.move_to_trash("runs", "c", {})
    repo.save_run(compressed)
    with pytest.raises(FileExistsError):
        repo.restore_from_trash("runs", "c")
    repo.erase_from_trash("runs", "c")
    assert repo.list_trash() == []
    # a delete that stopped before moving the compressed document heals back at startup
    repo.save_run(compressed)
    repo.move_to_trash("runs", "c", {})
    trash = tmp_path / "aegis" / "trash" / "runs" / "c"
    (trash / "c.json.gz").replace(folder / "c.json.gz")  # the document is live; its sidecar is not
    assert repo.heal_trash() == ["runs/c"] and not trash.exists()
    assert repo.get_run("c") == compressed and (folder / "c.summary.json").exists()


def test_deletes_take_either_form(tmp_path):
    repo = JsonRunRepository(tmp_path / "aegis")
    for kind, save, delete in (
        ("experiments", repo.save_experiment, repo.delete_experiment),
        ("studies", repo.save_study, repo.delete_study),
        ("strategies", repo.save_strategy, repo.delete_strategy),
    ):
        folder = tmp_path / "aegis" / kind
        save({"id": "zipped", "name": "z"})
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "flat.json").write_text(json.dumps({"id": "flat"}), encoding="utf-8")
        delete("zipped")
        delete("flat")
        assert not any(p.name.startswith(("zipped.", "flat.")) for p in folder.iterdir()), kind
        with pytest.raises(KeyError):
            delete("zipped")


def test_the_first_save_over_a_plain_document_never_fails_on_its_predecessor(tmp_path, monkeypatch):
    """Review I1 (re-graded): resuming an experiment saved before Mission 11 replaces its plain
    document; a plain file held by a reader, or already removed by another save, must not fail the
    save (the job would read "failed" though the document was written)."""
    from pathlib import Path

    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "experiments"
    folder.mkdir(parents=True)
    real_unlink = Path.unlink
    for refusal in (PermissionError(5, "Access is denied"), FileNotFoundError(2, "gone")):
        (folder / "x.json").write_text(
            json.dumps({"id": "x", "status": "paused"}), encoding="utf-8"
        )

        def unlink(self, *args, refusal=refusal, **kwargs):
            if self.name == "x.json":
                raise refusal
            return real_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", unlink)
        repo.save_experiment({"id": "x", "status": "running"})  # does not raise
        monkeypatch.setattr(Path, "unlink", real_unlink)
        assert repo.get_experiment("x")["status"] == "running"  # the compressed one wins
        assert (
            json.loads((folder / "x.summary.json").read_text(encoding="utf-8"))["status"]
            == "running"
        )
        repo.save_experiment(
            {"id": "x", "status": "running"}
        )  # the next save removes the plain one
        assert sorted(p.name for p in folder.iterdir()) == ["x.json.gz", "x.summary.json"]
        (folder / "x.json.gz").unlink()


def test_a_read_racing_the_first_save_finds_the_new_document(tmp_path, monkeypatch):
    """Review I2 (re-graded): a read that found the plain document just before a save swapped in
    the compressed one and removed the plain file reads the new document, not a 500."""
    from products.aegis import runs as runs_module

    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "experiments"
    folder.mkdir(parents=True)
    (folder / "x.json").write_text(json.dumps({"id": "x", "status": "paused"}), encoding="utf-8")
    real_read = JsonRunRepository._read

    def read(path):
        if path.name == "x.json":  # the save lands between finding and reading the plain file
            repo.save_experiment({"id": "x", "status": "running"})
        return real_read(path)

    monkeypatch.setattr(runs_module.JsonRunRepository, "_read", staticmethod(read))
    assert repo.get_experiment("x")["status"] == "running"
    with pytest.raises(KeyError):
        repo.get_experiment("nope")


# --- Optimization Lab v2, Phase 2 (Task 6): every attachment goes with its experiment ----------


def test_delete_experiment_removes_every_attachment_folder(tmp_path):
    from products.aegis.runs import ITEM_FOLDERS

    repo = JsonRunRepository(tmp_path / "aegis")
    folder = tmp_path / "aegis" / "experiments"
    assert ITEM_FOLDERS["experiments"] == (
        "cells",
        "curves",
        "reports",
        "replays",
        "final",
        "folds",
        "searchspaces",
        "holdout",
        "views",
        "events.jsonl",
    )
    for identifier in ("twelve", "twelve-b"):  # a neighbour whose id starts with the same name
        repo.save_experiment({"id": identifier, "name": identifier, "status": "done"})
        for suffix in ITEM_FOLDERS["experiments"]:
            path = folder / f"{identifier}.{suffix}"
            if suffix.endswith(".jsonl"):
                path.write_text('{"event": "created"}\n', encoding="utf-8")
                continue
            (path / "nested").mkdir(parents=True)
            (path / "000000.parquet").write_bytes(b"x")
            (path / "nested" / "1.json").write_text("{}", encoding="utf-8")
    repo.delete_experiment("twelve")
    assert not any(p.name.startswith("twelve.") for p in folder.iterdir())
    kept = sorted(p.name for p in folder.iterdir())
    assert kept == sorted(
        [
            "twelve-b.json.gz",
            "twelve-b.summary.json",
            *[f"twelve-b.{suffix}" for suffix in ITEM_FOLDERS["experiments"]],
        ]
    )
    assert (folder / "twelve-b.cells" / "nested" / "1.json").is_file()
    assert [s["id"] for s in repo.list_experiments()] == ["twelve-b"]
    with pytest.raises(KeyError):
        repo.delete_experiment("twelve")
