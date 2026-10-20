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
    assert prefs.get() == {"save_runs": "every"}
    assert prefs.set("kept") == {"save_runs": "kept"}
    assert Preferences(tmp_path).get() == {"save_runs": "kept"}
    assert json.loads((tmp_path / "preferences.json").read_text(encoding="utf-8")) == {
        "save_runs": "kept"
    }
    with pytest.raises(ValueError, match="save_runs"):
        prefs.set("sometimes")
    (tmp_path / "preferences.json").write_text("{broken", encoding="utf-8")
    assert Preferences(tmp_path).get() == {"save_runs": "every"}  # unreadable: the default


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
    assert c.get("/aegis/api/preferences").json() == {"save_runs": "every"}
    switched = c.put("/aegis/api/preferences", json={"save_runs": "kept"})
    assert switched.status_code == 200 and switched.json() == {"save_runs": "kept"}
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
    assert c.post(f"/aegis/api/runs/{run_id}/keep").status_code == 404
    assert c.get(f"/aegis/api/runs/{run_id}").status_code == 404
    assert c.post("/aegis/api/runs/not-a-run/keep").status_code == 404
