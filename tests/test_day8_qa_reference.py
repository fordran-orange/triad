"""Trusted backend QA context never broadens the candidate or tool grant."""

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from products.triad.development import INSPECTION_PATHS, Development
from trading_core.contracts import Limits

from products.triad import qa_reference as module

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def metadata():
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return {"base_commit": base, "change_commit": "1" * 40}


def test_real_contract_behavior_and_provenance_are_bounded(metadata):
    bundle = module.readiness_reference(ROOT, metadata, {"sources": [], "datasets": []})
    assert bundle["source_revision"] == metadata["base_commit"]
    assert bundle["candidate_revision"] == metadata["change_commit"]
    assert bundle["source_revision"] != bundle["candidate_revision"]
    serialized = json.dumps(
        {k: v for k, v in bundle.items() if k != "sha256"}, sort_keys=True, separators=(",", ":")
    )
    assert len(serialized) <= module.MAX_REFERENCE_CHARS
    assert hashlib.sha256(serialized.encode()).hexdigest() == bundle["sha256"]
    schema = bundle["request_schema"]["properties"]
    assert {
        "integration_id",
        "dataset_id",
        "symbols",
        "start",
        "end",
        "mode",
        "membership_rule",
        "required_fields",
        "session",
    } <= schema.keys()
    text = json.dumps(bundle)
    for phrase in (
        "/api/core/research-readiness/evaluate",
        "@router.post",
        "app.include_router(integration_router)",
        "app.include_router(daily_router)",
        "/triad/product/research-readiness",
        "/triad/assets/research-readiness.js",
        "independent_evidence",
        "PARTIALLY_READY",
        "Historical constituent membership evidence is unavailable",
        "No unresolved critical finding is acceptable",
    ):
        assert phrase in text
    for source in bundle["sources"]:
        original = module._blob(ROOT, metadata["base_commit"], source["path"])
        assert source["file_sha256"] == hashlib.sha256(original).hexdigest()
        for excerpt in source["excerpts"]:
            assert excerpt["sha256"] == hashlib.sha256(excerpt["text"].encode()).hexdigest()


def test_catalog_only_bounded_public_sample(metadata):
    catalog = {
        "sources": [
            {
                "integration_id": "example",
                "name": "x" * 300,
                "enabled": False,
                "password": "NEVER_INCLUDE",
                "endpoint": "NEVER_INCLUDE",
            }
        ]
        * 12,
        "datasets": [{"dataset_id": "d", "raw_provenance": "NEVER_INCLUDE"}] * 7,
    }
    bundle = module.readiness_reference(ROOT, metadata, catalog)
    sample = bundle["catalog_sample"]
    assert len(sample["sources"]) == len(sample["datasets"]) == 4
    assert sample["sources_omitted"] == 8 and sample["datasets_omitted"] == 3
    assert len(sample["sources"][0]["name"]) == 160
    assert "NEVER_INCLUDE" not in json.dumps(bundle)
    assert sample["sources"][0]["enabled"] is False


@pytest.mark.parametrize("key", ["base_commit", "change_commit"])
def test_nonexact_revisions_rejected(metadata, key):
    metadata[key] = "HEAD"
    with pytest.raises(ValueError, match="exact base and candidate"):
        module.readiness_reference(ROOT, metadata, {})


def test_backend_schema_drift_fails_closed(metadata, monkeypatch):
    original = module._blob

    def changed(root, revision, path):
        data = original(root, revision, path)
        return (
            data + b"\n# different backend\n"
            if path.endswith("integrations/contracts.py")
            else data
        )

    monkeypatch.setattr(module, "_blob", changed)
    with pytest.raises(PermissionError, match="Loaded schema differs"):
        module.readiness_reference(ROOT, metadata, {})


def test_reference_ceiling_denies_instead_of_silent_truncation(metadata, monkeypatch):
    monkeypatch.setattr(module, "MAX_REFERENCE_CHARS", 10)
    with pytest.raises(ValueError, match="bounded context"):
        module.readiness_reference(ROOT, metadata, {})


def test_legacy_empty_hook_and_review_packet_binding():
    dev = Development.__new__(Development)
    assert dev.qa_references({}) == {}
    references = {"source_revision": "a" * 40, "candidate_revision": "b" * 40, "sha256": "c" * 64}
    dev.qa_references = lambda build: references
    dev.ledger = SimpleNamespace(control=lambda: {"limits": Limits().model_dump(mode="json")})
    dev.exact_checks = lambda *args: {"checks": ["fixed check"], "hashes": {}}
    reviewed = []
    dev.quality = SimpleNamespace(review=reviewed.append)
    saved = []
    dev.record = lambda *args, **kwargs: saved.append(kwargs)
    observed = {}

    def call(mission, agent, role, objective, context, **kwargs):
        observed.update(context=context, kwargs=kwargs, role=role, agent=agent)
        return (
            SimpleNamespace(work_item_id="qa-work"),
            SimpleNamespace(review_decision="APPROVE", findings=()),
            None,
            {"provider": "fixture", "actual_model": "fixture", "run_id": "fixture-run"},
        )

    dev.call = call
    proposal = SimpleNamespace(affected_components=("docs",), model_dump=lambda **kwargs: {})
    build = {
        "git": {"change_commit": "b" * 40},
        "builder": "CLAUDE",
        "work_item_id": "builder-work",
        "implementation_id": "implementation",
    }
    qa = dev.qa("mission", proposal, build)
    assert observed["context"]["trusted_backend_reference"] == references
    assert observed["context"]["exact_commit"] == "b" * 40
    assert observed["kwargs"]["paths"] == INSPECTION_PATHS
    assert observed["role"] == "REVIEW" and observed["agent"] == "CODEX"
    assert "qa-reference:" + references["sha256"] in qa.evidence
    assert saved[0]["qa_reference"] == references and reviewed == [qa]
