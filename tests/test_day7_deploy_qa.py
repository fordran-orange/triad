"""Non-DB deployment evidence preflight probes with isolated files and host stubs."""

import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.core


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    repo = Path(__file__).parents[1]
    source = Path(os.getenv("DAY7_HELPER_QA_SOURCE", repo / "tools/day7_deploy_evidence.py"))
    spec = importlib.util.spec_from_file_location("deployment_evidence_qa", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reviewed = "56e4f96cd9ab43a319302edb694897d75143237a"
    original = subprocess.check_output(["git", "show", reviewed + ":" + module.ORIGINAL], cwd=repo)
    definitions = subprocess.check_output(
        ["git", "show", reviewed + ":" + module.DEFINITIONS], cwd=repo
    )
    assert hashlib.sha256(original).hexdigest() == module.ORIGINAL_SHA
    for name, content in [
        (module.ORIGINAL, original),
        (module.DEFINITIONS, definitions),
        ("docs/qa/DAY7_GHI_FINAL_QA.md", ("**PASS** reviewed " + reviewed).encode()),
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (tmp_path / "logs").mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    if hasattr(module, "subprocess"):

        def git_show(args, **kwargs):
            assert args == ["git", "show", reviewed + ":" + module.DEFINITIONS]
            assert kwargs["cwd"] == tmp_path and kwargs["check"] is True
            return SimpleNamespace(stdout=definitions)

        monkeypatch.setattr(module.subprocess, "run", git_show)
    calls = {"records": 0, "appends": [], "seeds": 0, "backfills": 0, "links": []}
    debt = {
        "id": module.DEBT,
        "kind": "QualityDebt",
        "owner": "triad",
        "status": "OPEN",
        "finding": "Definitions required",
    }
    resolutions = []

    class HostRecords:
        def __init__(self):
            calls["records"] += 1

        def get(self, identifier):
            assert identifier == module.DEBT
            return dict(debt)

        def list(self, kind):
            assert kind == "QualityDebtResolution"
            return list(resolutions)

        def append(self, kind, payload, *, owner):
            assert kind == "QualityDebtResolution" and owner == "triad"
            calls["appends"].append(dict(payload))
            resolutions.append({"id": "fixture-resolution", **payload})
            return "fixture-resolution"

    class Registry:
        def seed(self):
            calls["seeds"] += 1

        def catalog(self):
            return [
                {
                    "integration_id": name,
                    "category": "BROKER" if name != "local-canonical" else "HISTORICAL_DATA",
                    "enabled": False,
                }
                for name in ("schwab", "robinhood", "local-canonical")
            ]

    class History:
        def __init__(self, store):
            pass

        def backfill(self):
            calls["backfills"] += 1

        def list(self):
            return [
                {
                    "cycle_id": module.BLOCKED,
                    "status": "BLOCKED",
                    **({"recovered_by_cycle_id": module.RECOVERY} if calls["links"] else {}),
                },
                {
                    "cycle_id": module.RECOVERY,
                    "status": "COMPLETED",
                    "quality_debt": [{"id": module.DEBT, "resolutions": list(resolutions)}],
                },
            ]

        def link(self, source, target, relation):
            calls["links"].append((source, target, relation))

    monkeypatch.setattr(module, "Records", HostRecords)
    monkeypatch.setattr(module, "ExternalIntegrationRegistry", Registry)
    monkeypatch.setattr(module, "DataAccess", lambda: Registry())
    monkeypatch.setattr(module, "Store", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(module, "CycleHistory", History)
    return module, calls, tmp_path, definitions


def test_unreviewed_definitions_rejected_before_database_access(deployment):
    module, calls, folder, _ = deployment
    (folder / module.DEFINITIONS).write_text("Unreviewed altered definitions", encoding="utf-8")
    try:
        module.main()
    except RuntimeError:
        pass
    assert calls["records"] == 0
    assert calls["appends"] == []


@pytest.mark.parametrize("fault", ["original", "qa"])
def test_original_and_qa_preconditions_fail_before_database(deployment, fault):
    module, calls, folder, _ = deployment
    target = module.ORIGINAL if fault == "original" else "docs/qa/DAY7_GHI_FINAL_QA.md"
    (folder / target).write_text("Not reviewed evidence", encoding="utf-8")
    with pytest.raises((AssertionError, RuntimeError)):
        module.main()
    assert calls["records"] == 0 and calls["appends"] == []


def test_reviewed_resolution_is_append_only_and_repeat_safe(deployment):
    module, calls, _, definitions = deployment
    module.main()
    module.main()
    assert len(calls["appends"]) == 1
    resolution = calls["appends"][0]
    assert resolution["status"] == "RESOLVED_DEFINITIONS_ONLY"
    assert resolution["artifact_sha256"] == hashlib.sha256(definitions).hexdigest()
    assert resolution["reviewed_commit"] == "56e4f96cd9ab43a319302edb694897d75143237a"
    assert all(
        link == (module.BLOCKED, module.RECOVERY, "recovered_by_cycle_id")
        for link in calls["links"]
    )
