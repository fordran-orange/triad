"""Proposals cannot silently replace verified capability truth."""

import hashlib
import json

from trading_core.intelligence.contracts import Capability
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.providers.contracts import SPECS
from trading_core.work import now


def fingerprint(record):
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Capabilities:
    def __init__(self, records=None):
        self.records = records or Records()

    def current(self):
        versions = {}
        for row in self.records.list("CapabilityVersion", shared=True):
            if row["owner"] == "core":
                capability = row["capability"]
                # IDs identify proposals, not separate grants for the same fact.
                # A later downgrade must supersede every older verification.
                key = tuple(
                    capability[name] for name in ("provider", "model", "transport", "capability")
                )
                versions[key] = row
        return list(versions.values())

    def propose(self, capability: Capability, *, actor, work_id=None):
        self.records.ledger.guard(work_id=work_id)
        if self.records.store.scope is not None and (
            not work_id or self.records.store.get(work_id).assigned_agent != actor
        ):
            raise PermissionError("Agent proposal requires its own bounded assignment")
        return self.records.append(
            "CapabilityProposal",
            {
                "capability": capability.model_dump(mode="json"),
                "proposed_by": actor,
                "parent_work_item": work_id,
                "proposed_at": now().isoformat(),
                "review_status": "PENDING",
                "digest": fingerprint(capability.model_dump(mode="json")),
            },
            owner=self.records.store.scope or "core",
        )

    def approve(self, proposal_id, implementation_id, commit):
        if self.records.store.scope is not None:
            raise PermissionError("Capability truth is governed by Core")
        with self.records.store.lease("capability-approval"), self.records.store.connect() as conn:
            self.records.ledger.check(self.records.ledger.control(conn))
            proposal = self.records.get(proposal_id, conn=conn)
            if proposal["kind"] != "CapabilityProposal":
                raise ValueError("Expected a capability proposal")
            capability = Capability.model_validate(proposal["capability"])
            if fingerprint(capability.model_dump(mode="json")) != proposal["digest"]:
                raise PermissionError("Capability proposal digest does not match its contents")
            quality = Quality(self.records)
            qa = quality.require_pass(implementation_id, commit, conn=conn)
            build = self.records.get(implementation_id, conn=conn)
            if (
                build["owner"] != "core"
                or "capability:" + proposal["digest"] not in build["evidence"]
            ):
                raise PermissionError("QA must cover this exact capability update")
            if any(
                v.get("proposal_id") == proposal_id
                for v in self.records.list("CapabilityVersion", conn=conn)
            ):
                raise ValueError("Proposal already adopted")
            return self.records.append(
                "CapabilityVersion",
                {
                    "capability": proposal["capability"],
                    "proposal_id": proposal_id,
                    "qa_run_id": qa["id"],
                    "adopted_at": now().isoformat(),
                    "review_status": "APPROVED",
                },
                conn=conn,
            )

    def discover_runtime(self, control):
        """Cheap discovery consumes recorded successful tests; performs no inference."""
        found = []
        for transport, spec in SPECS.items():
            snapshot = control.snapshot(transport)
            proof = snapshot.get("workitem") or {}
            if (
                not proof.get("success")
                or proof.get("mode") != "REAL"
                or not proof.get("actual_model")
            ):
                continue
            # Each claim is narrow: successful structured result, and for CLI tests
            # only supplied text reads. General shell/web/X access is not implied.
            names = ["structured_output"]
            if spec["type"] == "CLI":
                names += ["isolated_text_read", "document_analysis"]
            if spec["agent"] == "LOCAL_QWEN":
                # HTTPTransport pins this proof path to loopback Ollama. This
                # does not describe arbitrary endpoints of legacy HttpProvider.
                names += ["local_execution", "private_local_processing"]
            for name in names:
                found.append(
                    Capability(
                        capability_id=f"{transport}:{proof['actual_model']}:{name}",
                        provider=spec["provider"],
                        model=proof["actual_model"],
                        transport=transport,
                        capability=name,
                        native_or_tool_mediated="local"
                        if spec["agent"] == "LOCAL_QWEN"
                        else "tool_mediated",
                        status="AVAILABLE",
                        verification_status="VERIFIED",
                        discovery_source="runtime",
                        evidence=("transport-proof:" + proof["proof_id"], "run:" + proof["run_id"]),
                        verified_at=proof["completed_at"],
                        verified_by="Core runtime verifier",
                        limitations=(
                            "Only the bounded tested transport path; no broader native tool authority",
                        ),
                        permissions_required=("read",),
                        cost_characteristics={"billing_source": proof["billing_source"]},
                        latency_characteristics={"observed_seconds": proof.get("latency")},
                    )
                )
        # Text proposal capability requires measured native staging, not a model's claim.
        if not hasattr(control, "ledger"):
            return found
        events = {
            r.get("run_id"): r
            for r in control.ledger.records("Event", 1000)
            if r.get("event") == "native_executor_evidence"
        }
        seen = set()
        requests = {r.get("run_id"): r for r in control.ledger.records("AgentRunRequest", 1000)}
        for usage in control.ledger.records("Usage", 1000):
            transport = usage.get("transport")
            event = events.get(usage.get("run_id"), {})
            proof = (
                (control.snapshot(transport).get("workitem") or {}) if transport in SPECS else {}
            )
            model = usage.get("actual_model") or event.get("model") or proof.get("actual_model")
            if (
                transport not in {"claude_code_cli", "grok_build_cli"}
                or transport in seen
                or usage.get("mode") != "REAL"
                or requests.get(usage.get("run_id"), {}).get("role") not in {"PROPOSE", "IMPLEMENT"}
                or not model
                or model != proof.get("actual_model")
            ):
                continue
            seen.add(transport)
            verified = (
                usage.get("status") == "SUCCESS"
                and event.get("boundary") == "DOCKER_OFFLINE_TOOLS"
                and any(c.get("tool") == "propose_file_change" for c in event.get("calls", []))
            )
            found.append(
                Capability(
                    capability_id=f"{transport}:{model}:isolated_text_proposal",
                    provider=SPECS[transport]["provider"],
                    model=model,
                    transport=transport,
                    capability="isolated_text_proposal",
                    native_or_tool_mediated="tool_mediated",
                    status="AVAILABLE" if verified else "RESTRICTED",
                    verification_status="VERIFIED" if verified else "DEGRADED",
                    discovery_source="runtime",
                    evidence=(
                        "run:" + usage["run_id"],
                        "usage:" + usage["id"],
                        "native-evidence:" + event.get("id", "not_recorded"),
                    ),
                    verified_at=usage["timestamp"] if verified else None,
                    verified_by="Core runtime and native tool broker" if verified else None,
                    notes="Latest write probe: "
                    + (
                        "verified staged tool execution"
                        if verified
                        else str(usage.get("error_class") or "No matching native staging evidence")
                    ),
                    limitations=(
                        "Staged non-executable text proposals only; host applies reviewed files through Git broker",
                    ),
                    permissions_required=("write_docs",),
                    cost_characteristics={"billing_source": usage["billing_source"]},
                    latency_characteristics={"observed_seconds": usage["duration"]},
                )
            )
        return found

    def discover_introspection(self, control):
        found = []
        for transport, spec in SPECS.items():
            if spec["type"] != "CLI":
                continue
            snapshot = control.snapshot(transport)
            model = (snapshot.get("workitem") or {}).get("actual_model") or "not_verified"
            installed = control.transport(transport).capabilities()
            for name in (
                "native_web_access",
                "native_x_access",
                "shell_execution",
                "git_operations",
                "repository_editing",
                "mcp",
            ):
                found.append(
                    Capability(
                        capability_id=f"{transport}:{model}:{name}",
                        provider=spec["provider"],
                        model=model,
                        transport=transport,
                        capability=name,
                        native_or_tool_mediated="tool_mediated",
                        status="UNAVAILABLE",
                        verification_status="UNAVAILABLE",
                        discovery_source="introspection",
                        evidence=(
                            "installed-tool-boundary:"
                            + transport
                            + ":"
                            + installed["outer_boundary"],
                        ),
                        limitations=(
                            "Not granted by the installed isolated transport. This is not a claim about the unrestricted provider product.",
                        ),
                        notes="Current granted tools: " + ", ".join(installed["granted"]),
                    )
                )
        return found
