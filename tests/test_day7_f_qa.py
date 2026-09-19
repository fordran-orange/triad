"""Independent neutral-data authority, integrity and failure-lineage QA."""
# ruff: noqa: F811

import json
from datetime import UTC, datetime

import pytest
from test_day3_integration import engine  # noqa: F401
from test_integration_data import ReviewedFixtureAdapter
from trading_core.integrations.adapters import CapabilityUnavailable
from trading_core.integrations.contracts import DataRequest
from trading_core.integrations.data import DataAccess
from trading_core.intelligence.records import Records
from trading_core.research.data import FixtureProvider
from trading_core.store import Store
from trading_core.work import WorkItem, uid

pytestmark = pytest.mark.integration


def setup(engine, tmp_path):
    access = DataAccess(engine.host.store, tmp_path)
    adapter = ReviewedFixtureAdapter(access.local.archive)
    access.registry.host.append("IntegrationDefinition", adapter.metadata(), owner="core")
    req = DataRequest(
        symbols=("LABTEST",),
        start=datetime(2026, 9, 17, 13, 30, tzinfo=UTC),
        end=datetime(2026, 9, 17, 13, 35, tzinfo=UTC),
        mode="FIXTURE",
    )
    return access, adapter, req


@pytest.mark.parametrize("revoked_field", ["enabled", "configured"])
def test_ingest_honors_current_registry_revocation(engine, tmp_path, monkeypatch, revoked_field):
    access, adapter, req = setup(engine, tmp_path)
    access.registry.host.append(
        "IntegrationDefinition", {**adapter.metadata(), revoked_field: False}, owner="core"
    )
    calls = []
    original = adapter.fetch_historical_bars

    def observed(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(adapter, "fetch_historical_bars", observed)
    with pytest.raises((PermissionError, CapabilityUnavailable)):
        access.ingest(adapter, req, operator_authorized=True)
    assert not calls


def test_failed_normalization_links_retained_raw_evidence(engine, tmp_path, monkeypatch):
    access, adapter, req = setup(engine, tmp_path)

    def invalid(raw, metadata):
        raise ValueError("fixture unsupported source schema")

    monkeypatch.setattr(adapter, "normalize_raw", invalid)
    with pytest.raises(ValueError):
        access.ingest(adapter, req, operator_authorized=True)
    failures = [r for r in access.registry.host.list("DataAcquisition") if r["status"] == "FAILED"]
    assert len(failures) == 1
    assert list(tmp_path.glob("data/raw/*/source.json"))
    retained = failures[0].get("raw_artifact")
    assert retained and retained["checksum"] and (tmp_path / retained["path"]).is_file()


def test_corrupt_retained_source_is_not_an_integrity_verified_match(engine, tmp_path):
    access, adapter, req = setup(engine, tmp_path)
    manifest = access.ingest(adapter, req, operator_authorized=True)[0]
    (tmp_path / manifest.raw_sources[0]["path"]).write_bytes(b"corrupt retained source")
    assert not access.match(req)["eligible"]


def test_fixture_provenance_cannot_be_presented_as_real(engine, tmp_path):
    access, adapter, req = setup(engine, tmp_path)
    manifest = access.ingest(adapter, req, operator_authorized=True)[0]
    # A contradictory historical manifest, without modifying its fixture artifacts.
    forged = manifest.model_dump(mode="json") | {"dataset_id": uid(), "mode": "REAL"}
    engine.ledger.put("DatasetManifest", forged, identifier=forged["dataset_id"])
    assert not access.match(req.model_copy(update={"mode": "REAL"}))["eligible"]


def test_license_use_requires_exact_structured_allowlist(engine, tmp_path, monkeypatch):
    access, adapter, req = setup(engine, tmp_path)
    monkeypatch.setattr(
        adapter, "license_notes", lambda request: {"allowed_uses": "not-for-research"}
    )
    with pytest.raises((PermissionError, ValueError)):
        access.ingest(adapter, req, operator_authorized=True)


def test_stop_between_symbols_prevents_next_external_fetch(engine, tmp_path, monkeypatch):
    access, adapter, req = setup(engine, tmp_path)
    req = req.model_copy(update={"symbols": ("LABTEST", "SECOND")})
    calls = []

    def fetch(request):
        symbol = request.symbols[0]
        calls.append(symbol)
        rows = json.loads(FixtureProvider().fetch_bars("LABTEST", request.start, request.end))
        return json.dumps([{**row, "symbol": symbol} for row in rows]).encode()

    monkeypatch.setattr(adapter, "fetch_historical_bars", fetch)
    original_append = Records.append

    def append(records, kind, payload, **kwargs):
        value = original_append(records, kind, payload, **kwargs)
        if kind == "DataAcquisition" and payload.get("status") == "COMPLETED":
            engine.ledger.operate("kill")
        return value

    monkeypatch.setattr(Records, "append", append)
    with pytest.raises(PermissionError):
        access.ingest(adapter, req, operator_authorized=True)
    assert calls == ["LABTEST"]


def test_private_manifests_are_not_shared_and_empty_sessions_fail(engine, tmp_path):
    access, adapter, req = setup(engine, tmp_path)
    manifest = access.ingest(adapter, req, operator_authorized=True)[0]
    private = engine.host.store.create(
        WorkItem(owner="triad", title="Private dataset", description="Private source")
    )
    private_manifest = manifest.model_dump(mode="json") | {
        "dataset_id": uid(),
        "source": "private-triad-source",
    }
    engine.ledger.put(
        "DatasetManifest",
        private_manifest,
        identifier=private_manifest["dataset_id"],
        work_id=private.work_item_id,
    )
    other = DataAccess(Store(engine.host.store.settings, scope="aegis"), tmp_path)
    matches = other.match(req)["eligible"]
    assert {r["dataset_id"] for r in matches} == {manifest.dataset_id}
    with pytest.raises(PermissionError):
        other.ingest(adapter, req, operator_authorized=True)
    weekend = req.model_copy(
        update={
            "start": datetime(2026, 9, 19, 13, 30, tzinfo=UTC),
            "end": datetime(2026, 9, 19, 13, 35, tzinfo=UTC),
        }
    )
    with pytest.raises(ValueError):
        access.ingest(adapter, weekend, operator_authorized=True)
    assert not access.match(weekend)["eligible"]
