"""Neutral historical data routing and ingestion. No silent source or paid fallback."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pyarrow.parquet as pq

from trading_core.integrations.adapters import CapabilityUnavailable, MarketDataAdapter
from trading_core.integrations.contracts import DataRequest, IntegrationRecord
from trading_core.integrations.registry import ExternalIntegrationRegistry, definition_fingerprint
from trading_core.intelligence.records import Records
from trading_core.research.calendar import Calendar
from trading_core.research.contracts import DatasetManifest
from trading_core.research.data import Archive, quality
from trading_core.settings import ROOT
from trading_core.store import Store
from trading_core.work import now, uid


class LocalCanonicalStore(MarketDataAdapter):
    def __init__(self, store=None, root=ROOT):
        self.store = store or Store()
        self.archive = Archive(root)
        super().__init__(
            IntegrationRecord(
                integration_id="local-canonical",
                name="Local Canonical Store",
                provider="Retained neutral data",
                category="HISTORICAL_DATA",
                status="AVAILABLE",
                capabilities={"HISTORICAL_BARS": "IMPLEMENTED"},
                authentication_type="Local Core ownership",
                configured=True,
                connected=True,
                enabled=True,
                environment="LOCAL",
                cost_model="LOCAL_COMPUTE",
                rate_limits={"network_requests": 0},
                data_limits=self.archive.limits.model_dump(mode="json"),
                notes=(
                    "Fixture and real datasets remain distinct. Availability does not imply real-market coverage.",
                    "Only Core/shared neutral datasets are discoverable; product-private conclusions are excluded.",
                ),
            )
        )

    def manifests(self):
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM core.day3_records WHERE kind='DatasetManifest' AND owner IN ('core','shared') ORDER BY created_at DESC"
            ).fetchall()
        return [
            DatasetManifest.model_validate(
                {k: v for k, v in r["payload"].items() if k in DatasetManifest.model_fields}
            )
            for r in rows
        ]

    def health_check(self):
        try:
            manifests = self.manifests()
            return {
                "status": "AVAILABLE",
                "connected": True,
                "detail": f"Local catalog reachable; {len(manifests)} retained manifests. Coverage is checked per request.",
            }
        except (OSError, ValueError):
            return {
                "status": "FAILED",
                "connected": False,
                "detail": "Local catalog could not be validated",
            }

    def eligible(self, request):
        request = DataRequest.model_validate(request)
        choices = []
        for manifest in self.manifests():
            if (
                manifest.mode != request.mode
                or manifest.asset_class != request.asset_class
                or manifest.resolution != request.resolution
                or not set(request.symbols) <= set(manifest.symbols)
                or manifest.start_time > request.start
                or manifest.end_time < request.end
                or manifest.quality_status != "PASS"
                or manifest.row_count <= 0
                or manifest.known_gaps
            ):
                continue
            licenses = [r.get("license_use_notes") for r in manifest.raw_sources]
            if request.mode == "REAL" and (
                not licenses or any(not licensed(item, request.license_use) for item in licenses)
            ):
                continue
            try:
                if not manifest.raw_sources:
                    continue
                for source in manifest.raw_sources:
                    target = (self.archive.root / source["path"]).resolve()
                    if (
                        source.get("mode") != manifest.mode
                        or source.get("provider") != manifest.source
                        or not target.is_relative_to(self.archive.root / "data/raw")
                        or target.stat().st_size > self.archive.limits.max_bytes
                        or hashlib.sha256(target.read_bytes()).hexdigest() != source["checksum"]
                    ):
                        raise ValueError("Retained raw provenance mismatch")
                frame = self.archive.load(manifest)
                for path in manifest.canonical_paths:
                    mode = (pq.read_schema(self.archive.root / path).metadata or {}).get(b"mode")
                    if mode != manifest.mode.encode():
                        raise ValueError("Canonical file mode contradicts manifest")
                expected = set(Calendar().expected(request.start, request.end))
                if not expected:
                    continue
                okay = True
                for symbol in request.symbols:
                    part = frame[
                        (frame.symbol == symbol)
                        & (frame.timestamp >= request.start)
                        & (frame.timestamp < request.end)
                    ]
                    if (
                        set(part.timestamp) != expected
                        or part.timestamp.duplicated().any()
                        or (request.volume_required and part.volume.isna().any())
                    ):
                        okay = False
                if not okay:
                    continue
            except (ValueError, OSError, KeyError):
                continue
            choices.append(
                {
                    "integration_id": "local-canonical",
                    "dataset_id": manifest.dataset_id,
                    "provider": manifest.source,
                    "mode": manifest.mode,
                    "coverage": {
                        "start": manifest.start_time.isoformat(),
                        "end": manifest.end_time.isoformat(),
                        "symbols": manifest.symbols,
                    },
                    "resolution": manifest.resolution,
                    "asset_class": manifest.asset_class,
                    "quality": "PASS; hashes and exact requested session coverage checked",
                    "estimated_cost_usd": 0,
                    "rate_limits": {"network_requests": 0},
                    "availability": "AVAILABLE",
                    "license": licenses
                    if request.mode == "REAL"
                    else "Synthetic engine-validation data only",
                    "existing_local_data": True,
                    "automatic_fallback": False,
                }
            )
        return choices

    def fetch_historical_bars(self, request, *, dataset_id=None):
        choices = self.eligible(request)
        if dataset_id is None:
            if len(choices) != 1:
                raise CapabilityUnavailable(
                    "Select one eligible dataset explicitly; sources are never silently combined"
                )
            dataset_id = choices[0]["dataset_id"]
        if dataset_id not in {c["dataset_id"] for c in choices}:
            raise CapabilityUnavailable(
                "Selected data does not cover the requested quality, license, mode and interval"
            )
        manifest = next(m for m in self.manifests() if m.dataset_id == dataset_id)
        frame = self.archive.load(manifest)
        return frame[
            (frame.symbol.isin(request.symbols))
            & (frame.timestamp >= request.start)
            & (frame.timestamp < request.end)
        ].copy()


class DataAccess:
    def __init__(self, store=None, root=ROOT):
        self.store = store or Store()
        self.root = Path(root)
        self.local = LocalCanonicalStore(self.store, root)
        self.registry = ExternalIntegrationRegistry(self.store)

    def seed(self):
        self.registry.require_host()
        with self.store.lease("external-integration-registry"):
            if not any(r["integration_id"] == "local-canonical" for r in self.registry.catalog()):
                self.registry.host.append(
                    "IntegrationDefinition", self.local.metadata(), owner="core"
                )

    def match(self, request):
        request = DataRequest.model_validate(request)
        matches = self.local.eligible(request)
        exclusions = []
        for integration in self.registry.catalog():
            if integration["integration_id"] == "local-canonical":
                continue
            exclusions.append(
                {
                    "integration_id": integration["integration_id"],
                    "reason": "No configured, verified historical-data acquisition adapter with request-specific coverage, license, quality and cost evidence",
                }
            )
        return {
            "request": request.model_dump(mode="json"),
            "eligible": matches,
            "excluded": exclusions,
            "selection_required": True,
            "paid_fallback": "NEVER_AUTOMATIC",
            "detail": "No matching retained coverage"
            if not matches
            else "Select one retained dataset; no data sources will be mixed",
        }

    def ingest(self, adapter, request, *, operator_authorized=False):
        """Trusted adapter-build extension point; no HTTP endpoint accepts adapter code.

        Vendor adapter must return raw bytes and normalize through its reviewed
        implementation. One request/source gets separate immutable artifacts.
        """
        self.registry.require_host()
        request = DataRequest.model_validate(request)
        if not operator_authorized:
            raise PermissionError(
                "External data acquisition requires explicit operator authorization"
            )
        if getattr(adapter, "data_mode", None) != request.mode:
            raise PermissionError("Actual source mode must match the requested real/fixture mode")
        adapter.require("HISTORICAL_BARS")
        definition = adapter.metadata()
        configured = next(
            (
                r
                for r in self.registry.catalog()
                if r["integration_id"] == definition["integration_id"]
            ),
            None,
        )
        if (
            not configured
            or configured["status"] != "AVAILABLE"
            or not configured["connected"]
            or not configured["enabled"]
            or not configured["configured"]
            or definition_fingerprint(configured) != definition_fingerprint(definition)
            or configured["capabilities"].get("HISTORICAL_BARS") != "IMPLEMENTED"
        ):
            raise CapabilityUnavailable("A reviewed configured historical adapter is required")
        # Paid adapter reservation/entitlements are not implemented in Day7.
        if definition["cost_model"] not in {"FREE", "LOCAL_COMPUTE"} or request.max_cost_usd > 0:
            raise PermissionError(
                "Paid data needs a separate reviewed cost reservation; no fallback"
            )
        license_notes = adapter.license_notes(request)
        if not licensed(license_notes, request.license_use):
            raise PermissionError("Requested use is not licensed")
        host = Records(self.store)
        if request.mode == "REAL":
            from trading_core.intelligence.quality import Quality

            candidate = next(
                (
                    r
                    for r in self.registry.candidates()
                    if r["candidate_id"] == configured.get("candidate_id")
                ),
                None,
            )
            if (
                not candidate
                or candidate["status"] != "IMPLEMENTED"
                or not configured.get("implementation_run_id")
                or not configured.get("implementation_commit")
            ):
                raise PermissionError(
                    "Real external acquisition requires the adopted reviewed Core adapter build"
                )
            build = host.get(configured["implementation_run_id"])
            if (
                build["owner"] != "core"
                or "integration-definition-sha256:" + definition_fingerprint(configured)
                not in build["evidence"]
            ):
                raise PermissionError(
                    "Real acquisition definition differs from reviewed implementation"
                )
            Quality(host).require_pass(
                configured["implementation_run_id"], configured["implementation_commit"]
            )
        epoch = host.ledger.guard()["epoch"]
        identifier = uid()
        manifests = []
        raw_artifacts = []
        provenance = {
            "integration": definition["integration_id"],
            "provider": definition["provider"],
            "request": request.model_dump(mode="json"),
            "request_time": request.requested_at.isoformat(),
            "symbols": request.symbols,
            "resolution": request.resolution,
            "coverage": {"start": request.start.isoformat(), "end": request.end.isoformat()},
            "normalization_version": adapter.normalization_version,
            "license_use_notes": license_notes,
        }
        try:
            for symbol in request.symbols:
                host.ledger.guard(epoch=epoch)
                current = next(
                    (
                        r
                        for r in self.registry.catalog()
                        if r["integration_id"] == definition["integration_id"]
                    ),
                    None,
                )
                if not current or definition_fingerprint(current) != definition_fingerprint(
                    definition
                ):
                    raise PermissionError("Integration configuration changed before acquisition")
                single = request.model_copy(update={"symbols": (symbol,)})
                raw = adapter.fetch_historical_bars(single)
                host.ledger.guard(epoch=epoch)
                provider = SimpleNamespace(
                    name=definition["provider"],
                    mode=request.mode,
                    integration_provenance=provenance,
                    license_use_notes=license_notes,
                )
                metadata = self.local.archive.preserve(
                    raw, provider, symbol, request.start, request.end, uid()
                )
                raw_artifacts.append(metadata)
                rows = adapter.normalize_raw(raw, metadata)
                report, bars = quality(rows, symbol, request.start, request.end)
                if report["status"] != "PASS" or report["expected_bars"] <= 0 or not bars:
                    host.append(
                        "DataAcquisition",
                        {
                            **provenance,
                            "acquisition_id": identifier,
                            "status": "QUALITY_FAILED",
                            "raw_artifact": metadata,
                            "quality_result": report,
                            "completed_at": now().isoformat(),
                        },
                        owner="core",
                    )
                    raise ValueError("External data failed nonempty canonical quality requirements")
                host.ledger.guard(epoch=epoch)
                manifest = self.local.archive.publish(bars, metadata, report)
                host.ledger.put(
                    "DatasetManifest",
                    manifest.model_dump(mode="json"),
                    identifier=manifest.dataset_id,
                )
                manifests.append(manifest)
                host.append(
                    "DataAcquisition",
                    {
                        **provenance,
                        "acquisition_id": identifier,
                        "status": "COMPLETED",
                        "raw_artifact": metadata,
                        "quality_result": report,
                        "dataset_id": manifest.dataset_id,
                        "completed_at": now().isoformat(),
                    },
                    owner="core",
                )
            return manifests
        except Exception as exc:
            host.append(
                "DataAcquisition",
                {
                    **provenance,
                    "acquisition_id": identifier,
                    "status": "FAILED",
                    "error_class": type(exc).__name__,
                    "raw_artifact": raw_artifacts[-1] if raw_artifacts else None,
                    "raw_artifacts": raw_artifacts,
                    "completed_dataset_ids": [m.dataset_id for m in manifests],
                    "completed_at": now().isoformat(),
                },
                owner="core",
            )
            raise


def licensed(notes, requested_use):
    if not isinstance(notes, dict):
        return False
    uses = notes.get("allowed_uses")
    return (
        isinstance(uses, (list, tuple))
        and bool(uses)
        and all(type(value) is str and value for value in uses)
        and requested_use in uses
        and type(notes.get("notes")) is str
        and bool(notes["notes"].strip())
    )
