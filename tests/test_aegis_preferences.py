"""Mission 10 Task 6: save every backtest, or only what I keep (spec §8)."""

import json

import pytest
from products.aegis import api, server
from products.aegis.strategy import default_strategy
from test_aegis_api import RANGE, _experiment_body, _runner, _wait_experiment, client  # noqa: F401

pytestmark = pytest.mark.aegis


def test_preferences_default_and_round_trip(tmp_path):
    from products.aegis.preferences import Preferences

    prefs = Preferences(tmp_path)
    assert prefs.get() == {"save_runs": "every", "reader_provider": "CLAUDE"}
    assert prefs.set("kept") == {"save_runs": "kept", "reader_provider": "CLAUDE"}
    assert Preferences(tmp_path).get() == {"save_runs": "kept", "reader_provider": "CLAUDE"}
    assert json.loads((tmp_path / "preferences.json").read_text(encoding="utf-8")) == {
        "save_runs": "kept",
        "reader_provider": "CLAUDE",
    }
    with pytest.raises(ValueError, match="save_runs"):
        prefs.set("sometimes")
    (tmp_path / "preferences.json").write_text("{broken", encoding="utf-8")
    assert Preferences(tmp_path).get() == {"save_runs": "every", "reader_provider": "CLAUDE"}


def test_the_reader_provider_is_remembered(tmp_path):  # Mission 14
    from products.aegis.preferences import Preferences

    prefs = Preferences(tmp_path)
    (tmp_path / "preferences.json").write_text('{"save_runs": "kept"}', encoding="utf-8")
    assert prefs.get() == {"save_runs": "kept", "reader_provider": "CLAUDE"}  # an older file
    assert prefs.set(reader_provider="CODEX") == {"save_runs": "kept", "reader_provider": "CODEX"}
    assert prefs.set("every") == {"save_runs": "every", "reader_provider": "CODEX"}
    assert prefs.set(reader_provider="GROK")["reader_provider"] == "GROK"  # operator, 2026-10-27
    with pytest.raises(ValueError, match="reader_provider"):
        prefs.set(reader_provider="OPENAI")


def test_unsaved_runs_keep_only_the_last_20():
    from products.aegis.unsaved import UnsavedRuns

    unsaved = UnsavedRuns(limit=20)
    for i in range(25):
        unsaved.add({"run_id": f"r{i}", "created_at": f"2026-10-20T00:00:{i:02d}+00:00"})
    listed = unsaved.list()
    ids = [r["run_id"] for r in listed]
    assert len(ids) == 20 and ids[0] == "r24" and ids[-1] == "r5" and "r4" not in ids
    assert all(r["kept"] is False for r in listed)
    with pytest.raises(KeyError):
        unsaved.get("r0")
    assert unsaved.get("r7")["run_id"] == "r7"
    assert unsaved.pop("r24")["run_id"] == "r24" and len(unsaved.list()) == 19


@pytest.fixture
def kept(client):  # noqa: F811
    from products.aegis.unsaved import UnsavedRuns

    c, _, repository = client
    unsaved = UnsavedRuns()
    server.app.dependency_overrides[api.get_unsaved] = lambda: unsaved
    assert c.get("/aegis/api/preferences").json()["save_runs"] == "every"
    switched = c.put("/aegis/api/preferences", json={"save_runs": "kept"})
    assert switched.status_code == 200 and switched.json()["save_runs"] == "kept"
    return c, repository


def _backtest(c, **extra):
    payload = {
        "strategy": default_strategy().model_dump(mode="json"),
        "data": {"symbol": "QQQ", "timeframe": "15m", **RANGE},
        **extra,
    }
    response = c.post("/aegis/api/backtest", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _library_ids(c):
    return [
        e["id"] for e in c.get("/aegis/api/library", params={"kind": "backtest"}).json()["entries"]
    ]


def test_kept_mode_holds_unsaved_runs(kept):
    c, repository = kept
    run = _backtest(c)
    run_id = run["run_id"]
    assert run["saved"] is False
    listed = {r["run_id"]: r for r in c.get("/aegis/api/runs").json()}
    assert listed[run_id]["kept"] is False
    served = c.get(f"/aegis/api/runs/{run_id}").json()
    assert served["result_hash"] == run["result_hash"] and served["saved"] is False
    assert run_id not in [r["run_id"] for r in repository.list_runs()]
    assert run_id not in _library_ids(c)

    keep = c.post(f"/aegis/api/runs/{run_id}/keep")
    assert keep.status_code == 200 and keep.json() == {"saved": run_id}
    assert repository.get_run(run_id)["result_hash"] == run["result_hash"]
    assert run_id in _library_ids(c)
    assert c.get(f"/aegis/api/runs/{run_id}").json()["saved"] is True
    assert "kept" not in {r["run_id"]: r for r in c.get("/aegis/api/runs").json()}[run_id]
    again = c.post(f"/aegis/api/runs/{run_id}/keep")
    assert again.status_code == 200 and again.json() == {"saved": run_id}  # already saved


def test_save_overrides_the_preference(kept):
    c, repository = kept
    saved = _backtest(c, save=True)
    assert saved["saved"] is True and repository.get_run(saved["run_id"])
    c.put("/aegis/api/preferences", json={"save_runs": "every"})
    unsaved = _backtest(c, save=False)
    assert unsaved["saved"] is False
    assert unsaved["run_id"] not in [r["run_id"] for r in repository.list_runs()]
    assert _backtest(c)["saved"] is True  # the preference again


def test_materialize_always_saves(kept, monkeypatch):
    monkeypatch.setenv("AEGIS_POOL_WORKERS", "2")
    from products.aegis import experiments as exp

    monkeypatch.setattr(exp, "CHUNK_CELLS", 2)
    c, repository = kept
    _runner(repository)
    created = c.post("/aegis/api/experiments", json=_experiment_body(c))
    assert created.status_code == 202, created.text
    experiment_id = created.json()["experiment_id"]
    assert _wait_experiment(c, experiment_id, ("done", "failed"))["status"] == "done"
    materialized = c.post(f"/aegis/api/experiments/{experiment_id}/cells/0/materialize")
    assert materialized.status_code == 200, materialized.text
    assert repository.get_run(materialized.json()["run_id"])  # saved in "kept" mode too


def test_keep_of_a_forgotten_run_is_404(kept):  # Review Focus 5
    from products.aegis.unsaved import UnsavedRuns

    c, _ = kept
    run_id = _backtest(c)["run_id"]
    server.app.dependency_overrides[api.get_unsaved] = lambda: UnsavedRuns()  # a worker restart
    forgotten = c.post(f"/aegis/api/runs/{run_id}/keep")
    assert forgotten.status_code == 404 and "newer" in forgotten.json()["detail"], forgotten.text
    assert c.get(f"/aegis/api/runs/{run_id}").status_code == 404
    assert c.post("/aegis/api/runs/not-a-run/keep").status_code == 404


def _sized_run(i, trades):
    return {
        "run_id": f"r{i}",
        "created_at": f"2026-10-20T00:00:{i:02d}+00:00",
        "markers": [{}] * (2 * trades),
        "result": {
            s: {"trades": [{}] * trades, "equity": []} for s in ("long", "short", "combined")
        },
    }


def test_unsaved_runs_hold_a_bounded_number_of_bytes():  # Mission 10 review I2
    from products.aegis.unsaved import BYTES_PER_ITEM, MAX_BYTES, UnsavedRuns, weight

    assert MAX_BYTES == 512_000_000 and BYTES_PER_ITEM == 640
    big = _sized_run(0, 1_000)
    assert weight(big) == (3 * 1_000 + 2 * 1_000) * BYTES_PER_ITEM
    unsaved = UnsavedRuns(limit=20, max_bytes=2 * weight(big))
    for i in range(3):
        unsaved.add(_sized_run(i, 1_000))
    assert [r["run_id"] for r in unsaved.list()] == ["r2", "r1"]  # the oldest went first
    unsaved.add(_sized_run(9, 10_000))  # over the budget alone: held, as the only one
    assert [r["run_id"] for r in unsaved.list()] == ["r9"]
    assert unsaved.pop("r9")["run_id"] == "r9" and unsaved.list() == []
    unsaved.add(_sized_run(1, 1_000))
    assert [r["run_id"] for r in unsaved.list()] == ["r1"]  # popping gave its bytes back


def test_preferences_survive_a_file_held_by_another_reader(tmp_path, monkeypatch):
    """Windows refuses to swap or read a file another handle holds: a PUT then answered 500 and a
    read fell back to "every" (seen in the Mission 11 trial). Both retry, as the run store does."""
    from pathlib import Path

    from products.aegis.preferences import Preferences

    prefs = Preferences(tmp_path)
    real_replace, real_read = Path.replace, Path.read_text
    refusals = {"replace": 1, "read": 1}

    def replace(self, target):
        if refusals["replace"]:
            refusals["replace"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_replace(self, target)

    def read_text(self, *args, **kwargs):
        if self.name == "preferences.json" and refusals["read"]:
            refusals["read"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", replace)
    assert prefs.set("kept")["save_runs"] == "kept" and refusals["replace"] == 0
    monkeypatch.setattr(Path, "read_text", read_text)
    assert prefs.get()["save_runs"] == "kept" and refusals["read"] == 0  # not the default
    assert not list(tmp_path.glob("*.tmp"))
