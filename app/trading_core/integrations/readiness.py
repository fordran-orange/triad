"""Read-only, product-neutral evaluation of the Day 7 readiness definitions.

Discovery and available-data quality are not readiness. A READY decision also
requires exact-request, exact-dataset independent evidence ingested by Core.
No provider acquisition, ownership change or repair is performed here.
"""

import hashlib
import json
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from trading_core.integrations.contracts import DataRequest
from trading_core.integrations.data import DataAccess, licensed
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.research.calendar import Calendar
from trading_core.research.contracts import Bar
from trading_core.research.data import quality
from trading_core.work import Record, now

POLICY = "day7-readiness-definitions-v2"
DEFINITION_SHA256 = "9542a822398e252302dc3a79358732675d30f24c15429cc9e1611c9cc8d32fba"
CHECKS = (
    "schema_required_values",
    "finite_valid_ohlcv",
    "duplicates",
    "ordering",
    "expected_coverage",
    "timezone_session",
    "source_consistency",
    "outlier_review",
    "file_integrity",
    "license_provenance",
    "independent_reproduction",
)


Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CompletedCheck(Record):
    status: Literal["COMPLETED"]
    result: Literal["PASS"]
    evidence: tuple[Nonblank, ...] = Field(min_length=1)


class ResolvedFinding(Record):
    resolved: Literal[True]
    evidence: tuple[Nonblank, ...] = Field(min_length=1)
    description: Nonblank | None = None


class ReadinessAttestation(Record):
    request_hash: str
    dataset_hash: str
    policy: Literal["day7-readiness-definitions-v2"]
    executed_at: AwareDatetime
    normalizer_version: Nonblank
    outlier_method: Nonblank
    outlier_parameters: dict = Field(min_length=1)
    outlier_reference_evidence: tuple[Nonblank, ...] = Field(min_length=1)
    outlier_findings: tuple[ResolvedFinding, ...]
    outlier_disposition: Nonblank
    critical_findings: tuple[dict, ...] = Field(max_length=0)
    checks: dict[str, CompletedCheck]
    session_checks: dict[str, dict[str, dict[str, CompletedCheck]]]

    @model_validator(mode="after")
    def complete(self):
        if self.executed_at > now() or set(self.checks) != set(CHECKS):
            raise ValueError("Exact completed checks and an observed execution time required")
        return self


class ReadinessRequest(DataRequest):
    universe: str = Field(default="Explicit symbols", min_length=1, max_length=160)
    membership_rule: Literal["EXPLICIT_SYMBOLS", "HISTORICAL_CONSTITUENTS"] = "EXPLICIT_SYMBOLS"
    integration_id: str = Field(default="local-canonical", min_length=1, max_length=80)
    dataset_id: str | None = Field(default=None, max_length=100)
    session: Literal["REGULAR"] = "REGULAR"
    required_fields: tuple[
        Literal["timestamp", "symbol", "open", "high", "low", "close", "volume"], ...
    ] = (
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
    )


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def request_key(request):
    return fingerprint(request.model_dump(mode="json", exclude={"request_id", "requested_at"}))


class Readiness:
    def __init__(self, access=None):
        self.access = access or DataAccess()
        self.records = Records(self.access.store)

    def catalog(self):
        return {
            "sources": self.access.registry.catalog(),
            "datasets": [self.summary(m) for m in self.access.local.manifests()],
            "policy": POLICY,
            "supported_calendar": Calendar.version,
            "limitations": [
                "XNYS regular session, 2026, at most 32 days per evaluation",
                "Explicit symbols only; constituent history is not available",
                "No automatic acquisition or paid fallback",
            ],
        }

    @staticmethod
    def summary(manifest):
        return {
            "dataset_id": manifest.dataset_id,
            "version": manifest.dataset_version,
            "mode": manifest.mode,
            "provider": manifest.source,
            "symbols": manifest.symbols,
            "resolution": manifest.resolution,
            "start": manifest.start_time.isoformat(),
            "end": manifest.end_time.isoformat(),
            "rows": manifest.row_count,
            "quality": manifest.quality_status,
            "calendar": manifest.calendar_version,
            "checksum": manifest.checksum,
            "canonical_paths": manifest.canonical_paths,
            "raw_provenance": [
                {
                    k: s.get(k)
                    for k in ("raw_id", "provider", "mode", "path", "checksum", "downloaded_at")
                }
                for s in manifest.raw_sources
            ],
            "license_use": [s.get("license_use_notes") for s in manifest.raw_sources],
            "known_gaps": manifest.known_gaps,
        }

    def reviewed_checks(self, request, manifest):
        # Only host-owned evidence can attest checks, with exact independent QA.
        matches = [
            r
            for r in self.records.list("ReadinessEvidence")
            if r["owner"] == "core"
            and r.get("request_hash") == request_key(request)
            and r.get("dataset_hash") == fingerprint(manifest.model_dump(mode="json"))
            and r.get("policy") == POLICY
        ]
        if not matches:
            return None
        evidence = matches[-1]
        try:
            qa = Quality(self.records).require_pass(
                evidence["implementation_id"], evidence["commit"]
            )
            if (
                qa["id"] != evidence["qa_id"]
                or "readiness:" + evidence["digest"] not in qa["evidence"]
            ):
                return None
            payload = {
                k: v
                for k, v in evidence.items()
                if k
                not in {"id", "kind", "owner", "digest", "implementation_id", "commit", "qa_id"}
            }
            if fingerprint(payload) != evidence["digest"]:
                return None
            attestation = ReadinessAttestation.model_validate(payload)
            sessions = {
                t.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                for t in Calendar().expected(request.start, request.end)
            }
            if not sessions or set(attestation.session_checks) != set(request.symbols):
                return None
            for symbol in request.symbols:
                if set(attestation.session_checks[symbol]) != sessions or any(
                    set(checks) != set(CHECKS)
                    for checks in attestation.session_checks[symbol].values()
                ):
                    return None
            return {"record_id": evidence["id"], "qa_id": qa["id"], "checks": evidence["checks"]}
        except (KeyError, ValueError, PermissionError, TypeError, AttributeError):
            return None

    def evaluate(self, request):
        request = ReadinessRequest.model_validate(request)
        result = {
            "request": request.model_dump(mode="json"),
            "request_hash": request_key(request),
            "policy": POLICY,
            "definition_sha256": DEFINITION_SHA256,
            "evaluated_at": now().isoformat(),
            "status": "NOT_READY",
            "strategy_status": "NOT_EVALUATED",
            "strategy_notice": "Data readiness does not establish strategy edge, validation or trading authority.",
            "expected_coverage": None,
            "source": None,
            "dataset": None,
            "missing": [],
            "checks": [],
            "eligible_sources": [],
            "paid_fallback": "NEVER_AUTOMATIC",
        }
        missing = result["missing"]
        sources = self.access.registry.catalog()
        result["source"] = next(
            (s for s in sources if s["integration_id"] == request.integration_id), None
        )
        if not result["source"]:
            missing.append("Selected integration is not in the Core registry")
            return result
        if request.integration_id != "local-canonical":
            result["status"] = "BLOCKED"
            missing.append(
                "No configured and independently verified historical acquisition adapter; no fetch attempted"
            )
            return result
        if (
            not all(result["source"].get(k) for k in ("enabled", "configured", "connected"))
            or result["source"].get("status") != "AVAILABLE"
            or result["source"].get("capabilities", {}).get("HISTORICAL_BARS") != "IMPLEMENTED"
        ):
            result["status"] = "BLOCKED"
            missing.append("Selected integration is disabled or disconnected")
            return result
        if request.membership_rule != "EXPLICIT_SYMBOLS":
            missing.append("Historical constituent membership evidence is unavailable")
        try:
            expected = Calendar().expected(request.start, request.end)
        except ValueError:
            result["status"] = "UNKNOWN"
            missing.append("Requested calendar/interval is unsupported: XNYS 2026, at most 32 days")
            return result
        result["expected_coverage"] = {
            "calendar": Calendar.version,
            "bars_per_symbol": len(expected),
            "total_bars": len(expected) * len(request.symbols),
            "sessions": len({t.astimezone(ZoneInfo("America/New_York")).date() for t in expected}),
            "gap_tolerance": 0,
        }
        if not expected:
            missing.append("No expected regular-session bars; empty coverage cannot pass")
            return result
        base = DataRequest.model_validate(
            {k: v for k, v in request.model_dump().items() if k in DataRequest.model_fields}
        )
        result["eligible_sources"] = self.access.match(base)["eligible"]
        manifests = self.access.local.manifests()
        manifest = next((m for m in manifests if m.dataset_id == request.dataset_id), None)
        if not manifest:
            missing.append(
                "Select a retained shared dataset explicitly"
                if not request.dataset_id
                else "Selected dataset is unavailable in the shared catalog"
            )
            return result
        result["dataset"] = self.summary(manifest)
        if manifest.mode != request.mode:
            missing.append("Dataset mode does not match the requested REAL/FIXTURE mode")
        if (
            manifest.resolution != request.resolution
            or manifest.calendar_version != Calendar.version
        ):
            missing.append("Dataset resolution or calendar version does not match request")
        if not set(request.symbols) <= set(manifest.symbols):
            missing.append("Requested symbols are absent from this dataset")
        if manifest.known_gaps or manifest.quality_status != "PASS":
            missing.append("Manifest has known gaps or failed quality")
        try:
            frame = self.access.local.archive.load(manifest)
            result["checks"].append({"name": "canonical_integrity", "status": "PASS"})
            for symbol in request.symbols:
                part = frame[
                    (frame.symbol == symbol)
                    & (frame.timestamp >= request.start)
                    & (frame.timestamp < request.end)
                ]
                rows = [
                    {k: v for k, v in row.items() if k in Bar.model_fields}
                    for row in part.to_dict("records")
                ]
                report, _ = quality(rows, symbol, request.start, request.end)
                if not part.empty and not (part.source == manifest.source).all():
                    report["status"] = "FAIL"
                    report["issues"].append({"check": "manifest_source_mismatch"})
                result["checks"].append(
                    {"name": "available_data_quality", "symbol": symbol, **report}
                )
                if report["status"] != "PASS" or len(part) != len(expected):
                    missing.append("Coverage or required OHLCV checks failed for " + symbol)
            if manifest.dataset_id not in {c["dataset_id"] for c in result["eligible_sources"]}:
                missing.append(
                    "Core source matching did not verify coverage, raw integrity, mode and license"
                )
        except (OSError, ValueError, KeyError, PermissionError):
            result["status"] = "BLOCKED"
            missing.append("Canonical files failed integrity or bounded loading checks")
            return result
        if request.mode == "REAL" and (
            not manifest.raw_sources
            or any(
                not licensed(s.get("license_use_notes"), request.license_use)
                for s in manifest.raw_sources
            )
        ):
            missing.append("Real-data license/use evidence is missing")
        reviewed = self.reviewed_checks(request, manifest)
        result["independent_evidence"] = reviewed
        if not reviewed:
            missing.append(
                "Completed independently reviewed checks are missing, including outliers and reproducibility"
            )
        result["status"] = (
            "READY"
            if not missing
            else (
                "PARTIALLY_READY"
                if manifest.mode == request.mode and not frame.empty
                else "NOT_READY"
            )
        )
        result["missing"] = list(dict.fromkeys(missing))
        return result
