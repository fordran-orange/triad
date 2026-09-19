# ruff: noqa: F811
from datetime import UTC, datetime

import pytest
from test_day3_integration import engine  # noqa: F401
from trading_core.integrations.adapters import CapabilityUnavailable, MarketDataAdapter
from trading_core.integrations.contracts import DataRequest, IntegrationRecord
from trading_core.integrations.data import DataAccess
from trading_core.research.data import FixtureProvider
from trading_core.store import Store

pytestmark = pytest.mark.integration


class ReviewedFixtureAdapter(MarketDataAdapter):
    data_mode = "FIXTURE"
    normalization_version = "canonical-normalizer-v2"

    def __init__(self, archive):
        self.archive = archive
        super().__init__(
            IntegrationRecord(
                integration_id="fixture-data",
                name="Reviewed data fixture",
                provider="fixture-provider",
                category="HISTORICAL_DATA",
                capabilities={"HISTORICAL_BARS": "IMPLEMENTED"},
                authentication_type="NONE",
                status="AVAILABLE",
                configured=True,
                connected=True,
                enabled=True,
                environment="TEST",
                cost_model="FREE",
            )
        )

    def license_notes(self, request):
        return {"allowed_uses": ["research"], "notes": "Synthetic engine validation only"}

    def fetch_historical_bars(self, request):
        return FixtureProvider().fetch_bars(request.symbols[0], request.start, request.end)

    def normalize_raw(self, raw, metadata):
        return self.archive.normalize(raw, metadata)


def test_nonbroker_ingestion_keeps_provenance_and_local_matching(engine, tmp_path):
    access = DataAccess(engine.host.store, tmp_path)
    access.registry.seed()
    access.seed()
    adapter = ReviewedFixtureAdapter(access.local.archive)
    access.registry.host.append("IntegrationDefinition", adapter.metadata(), owner="core")
    request = DataRequest(
        symbols=("LABTEST",),
        start=datetime(2026, 9, 17, 13, 30, tzinfo=UTC),
        end=datetime(2026, 9, 17, 13, 35, tzinfo=UTC),
        mode="FIXTURE",
    )
    with pytest.raises(PermissionError):
        access.ingest(adapter, request)
    manifests = access.ingest(adapter, request, operator_authorized=True)
    manifest = manifests[0]
    raw = manifest.raw_sources[0]
    assert raw["integration_provenance"]["integration"] == "fixture-data"
    assert raw["license_use_notes"]["allowed_uses"] == ["research"]
    assert raw["checksum"] and manifest.file_checksums and manifest.quality_status == "PASS"
    matches = access.match(request)
    assert matches["eligible"][0]["dataset_id"] == manifest.dataset_id
    assert len(access.local.fetch_historical_bars(request, dataset_id=manifest.dataset_id)) == 5
    assert not access.match(request.model_copy(update={"mode": "REAL"}))["eligible"]
    assert not access.match(
        request.model_copy(update={"end": datetime(2026, 9, 17, 14, tzinfo=UTC)})
    )["eligible"]
    with pytest.raises(PermissionError):
        access.ingest(
            adapter, request.model_copy(update={"mode": "REAL"}), operator_authorized=True
        )
    with pytest.raises(PermissionError):
        access.ingest(
            adapter, request.model_copy(update={"max_cost_usd": 1}), operator_authorized=True
        )
    # A second eligible source is not silently combined or selected.
    access.ingest(adapter, request, operator_authorized=True)
    with pytest.raises(CapabilityUnavailable):
        access.local.fetch_historical_bars(request)
    # Corruption removes the affected dataset from eligibility.
    (tmp_path / manifest.canonical_paths[0]).write_bytes(b"corrupt")
    assert manifest.dataset_id not in {r["dataset_id"] for r in access.match(request)["eligible"]}
    product = DataAccess(Store(engine.host.store.settings, scope="triad"), tmp_path)
    with pytest.raises(PermissionError):
        product.ingest(adapter, request, operator_authorized=True)
