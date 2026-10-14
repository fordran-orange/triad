"""Truthful read-only readiness against real retained fixture bytes."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_lab import END, START, dataset
from trading_core.integrations.data import LocalCanonicalStore
from trading_core.integrations.readiness import Readiness, ReadinessRequest, request_key

# Owned by Triad: Triad's trusted post-merge gate (app/products/triad/daily_verification.py)
# runs it under the Triad scope, so another owner would silently drop it from that gate;
# tests/test_pytest_scope.py pins this.
pytestmark = pytest.mark.triad


def service(tmp_path, monkeypatch):
    archive, _, manifest = dataset(tmp_path)
    local = LocalCanonicalStore.__new__(LocalCanonicalStore)
    local.archive = archive
    local.manifests = lambda: [manifest]
    access = SimpleNamespace(
        local=local,
        registry=SimpleNamespace(
            catalog=lambda: [
                {
                    "integration_id": "local-canonical",
                    "status": "AVAILABLE",
                    "capabilities": {"HISTORICAL_BARS": "IMPLEMENTED"},
                    "enabled": True,
                    "configured": True,
                    "connected": True,
                }
            ]
        ),
        match=lambda r: {"eligible": local.eligible(r)},
    )
    ready = Readiness.__new__(Readiness)
    ready.access = access
    ready.records = SimpleNamespace(list=lambda _: [])
    req = ReadinessRequest(
        symbols=("LABTEST",), start=START, end=END, mode="FIXTURE", dataset_id=manifest.dataset_id
    )
    return ready, req, archive, manifest


def test_fixture_quality_is_not_real_or_complete_readiness(tmp_path, monkeypatch):
    ready, req, _, _ = service(tmp_path, monkeypatch)
    report = ready.evaluate(req)
    assert report["status"] == "PARTIALLY_READY"
    assert report["expected_coverage"]["bars_per_symbol"] == 60
    assert report["dataset"]["mode"] == "FIXTURE"
    assert report["independent_evidence"] is None
    assert "outliers" in " ".join(report["missing"])
    assert ready.evaluate(req.model_copy(update={"mode": "REAL"}))["status"] == "NOT_READY"
    assert report["strategy_status"] == "NOT_EVALUATED"


def test_explicit_source_dataset_calendar_and_nonempty_coverage(tmp_path, monkeypatch):
    ready, req, _, _ = service(tmp_path, monkeypatch)
    assert ready.evaluate(req.model_copy(update={"dataset_id": None}))["status"] == "NOT_READY"
    assert (
        ready.evaluate(req.model_copy(update={"dataset_id": "private-dataset"}))["dataset"] is None
    )
    assert (
        ready.evaluate(req.model_copy(update={"end": END + timedelta(days=365)}))["status"]
        == "UNKNOWN"
    )
    weekend = req.model_copy(
        update={"start": START + timedelta(days=5), "end": END + timedelta(days=5)}
    )
    assert ready.evaluate(weekend)["expected_coverage"]["total_bars"] == 0
    assert ready.evaluate(weekend)["status"] == "NOT_READY"
    assert "membership" in " ".join(
        ready.evaluate(req.model_copy(update={"membership_rule": "HISTORICAL_CONSTITUENTS"}))[
            "missing"
        ]
    )


def test_corruption_is_blocked_and_request_fingerprint_is_semantic(tmp_path, monkeypatch):
    ready, req, archive, manifest = service(tmp_path, monkeypatch)
    assert request_key(req) == request_key(req.model_copy(update={"request_id": "new"}))
    assert request_key(req) != request_key(req.model_copy(update={"symbols": ("SPY",)}))
    (archive.root / manifest.canonical_paths[0]).write_bytes(b"broken")
    assert ready.evaluate(req)["status"] == "BLOCKED"


def test_missing_symbols_and_unverified_adapter_never_pass(tmp_path, monkeypatch):
    ready, req, _, _ = service(tmp_path, monkeypatch)
    assert ready.evaluate(req.model_copy(update={"symbols": ("SPY",)}))["status"] != "READY"
    ready.access.registry.catalog = lambda: [{"integration_id": "broker", "enabled": True}]
    report = ready.evaluate(req.model_copy(update={"integration_id": "broker"}))
    assert report["status"] == "BLOCKED"
    assert report["paid_fallback"] == "NEVER_AUTOMATIC"


def test_unknown_fields_are_not_silently_accepted():
    with pytest.raises(ValueError):
        ReadinessRequest(symbols=("SPY",), start=START, end=END, allow_paid_fallback=True)
