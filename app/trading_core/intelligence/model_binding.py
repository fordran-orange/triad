"""Reviewed model identity overlays; immutable configured grants remain authoritative."""

from pydantic import Field, model_validator

from trading_core.intelligence.capabilities import Capabilities, fingerprint
from trading_core.intelligence.quality import Quality
from trading_core.providers.contracts import PREFERRED, SPECS, ProviderPolicy
from trading_core.providers.control import ProviderControl
from trading_core.work import Record, now

READ_CAPABILITIES = frozenset({"structured_output", "isolated_text_read", "document_analysis"})


class ModelBindingRequest(Record):
    agent_id: str = Field(min_length=1)
    base_definition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous_model: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    transport: str = Field(min_length=1)
    test_proof: str = Field(min_length=1)
    work_proof: str = Field(min_length=1)
    capability_versions: tuple[str, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def distinct(self):
        if self.model == self.previous_model or len(set(self.capability_versions)) != 3:
            raise ValueError("Model binding requires a changed model and three distinct versions")
        return self


def binding_marker(request: ModelBindingRequest):
    return "agent-model-binding:" + fingerprint(request.model_dump(mode="json"))


def _record(conn, identifier, kind):
    row = conn.execute(
        "SELECT kind,owner,work_item_id,payload FROM core.day3_records WHERE id=%s",
        (identifier,),
    ).fetchone()
    if not row or row["kind"] != kind or row["owner"] != "core":
        raise PermissionError("Model binding requires canonical Core provider evidence")
    return row


def _validate(records, definition, request, *, conn, check_capabilities=True):
    if (
        definition["agent_type"] != "static"
        or definition["agent_id"] != request.agent_id
        or definition["executor_identity"] != request.agent_id
        or request.agent_id not in PREFERRED
        or definition["model"] != request.previous_model
        or fingerprint(definition) != request.base_definition_digest
        or definition["provider"] != request.provider
        or definition["preferred_transport"] != request.transport
        or SPECS.get(request.transport, {}).get("type")
        not in ({"CLI"} if check_capabilities else {"CLI", "LOCAL"})
        or SPECS[request.transport]["agent"] != request.agent_id
        or SPECS[request.transport]["provider"] != request.provider
    ):
        raise PermissionError("Model binding does not match the immutable static grant")
    billing = "LOCAL" if request.transport == "ollama" else "SUBSCRIPTION"
    status = _record(conn, "transport-status-" + request.transport, "TransportStatus")["payload"]
    policy_row = conn.execute(
        "SELECT owner,payload FROM core.day3_records WHERE id=%s AND kind='ProviderPolicy'",
        ("provider-policy-" + request.agent_id,),
    ).fetchone()
    if policy_row and policy_row["owner"] != "core":
        raise PermissionError("Provider policy must be Core-owned")
    policy = (
        ProviderPolicy.model_validate(policy_row["payload"]["policy"])
        if policy_row
        else ProviderPolicy(agent=request.agent_id, preferred_transport=PREFERRED[request.agent_id])
    )
    if (
        not ProviderControl.proven(status)
        or status.get("billing_source") != billing
        or policy.agent != request.agent_id
        or policy.preferred_transport != request.transport
        or policy.models.get(request.transport, "Auto") not in {"Auto", request.model}
    ):
        raise PermissionError("Current provider policy or runtime proof does not permit binding")
    proofs = {}
    for name, identifier in (("test", request.test_proof), ("workitem", request.work_proof)):
        snapshot = status.get(name) or {}
        proof_row = _record(conn, identifier, "TransportVerification")
        proof = proof_row["payload"]
        if (
            snapshot.get("proof_id") != identifier
            or proof_row["work_item_id"] != proof.get("work_item_id")
            or snapshot.get("success") is not True
            or proof.get("success") is not True
            or proof.get("mode") != "REAL"
            or proof.get("kind") != name
            or any(
                proof.get(k) != v
                for k, v in {
                    "agent": request.agent_id,
                    "provider": request.provider,
                    "transport": request.transport,
                    "actual_model": request.model,
                    "billing_source": billing,
                }.items()
            )
            or any(
                snapshot.get(k) != proof.get(k)
                for k in ("actual_model", "run_id", "work_item_id", "usage_id", "completed_at")
            )
        ):
            raise PermissionError("Model binding proof is missing, changed or mismatched")
        usage = _record(conn, proof["usage_id"], "Usage")
        runs = conn.execute(
            "SELECT owner,work_item_id,payload FROM core.day3_records "
            "WHERE kind='TransportRun' AND payload->>'run_id'=%s",
            (proof["run_id"],),
        ).fetchall()
        if len(runs) != 1:
            raise PermissionError("Model binding requires one canonical successful transport run")
        run = runs[0]
        if (
            run["owner"] != "core"
            or run["payload"].get("status") != "SUCCESS"
            or run["work_item_id"] != proof["work_item_id"]
            or usage["work_item_id"] != proof["work_item_id"]
            or usage["payload"].get("usage_known") is not True
            or any(
                run["payload"].get(k) != v
                for k, v in {
                    "agent": request.agent_id,
                    "provider": request.provider,
                    "transport": request.transport,
                    "actual_model": request.model,
                    "billing_source": billing,
                }.items()
            )
            or any(
                usage["payload"].get(k) != v
                for k, v in {
                    "status": "SUCCESS",
                    "mode": "REAL",
                    "run_id": proof["run_id"],
                    "actual_model": request.model,
                    "provider": request.provider,
                    "transport": request.transport,
                    "billing_source": billing,
                    "agent": request.agent_id,
                }.items()
            )
        ):
            raise PermissionError("Model binding requires matching successful run and known usage")
        identity = getattr(request, "runtime_identity", None)
        if identity is not None and any(
            record.get("runtime_identity") != identity
            for record in (status, proof, usage["payload"], run["payload"])
        ):
            raise PermissionError("Compatibility evidence belongs to a different installation")
        proofs[name] = proof
    if not check_capabilities:
        return proofs
    current = {v["id"]: v for v in Capabilities(records).current(conn=conn)}
    names = set()
    for identifier in request.capability_versions:
        version = current.get(identifier)
        if not version or version["review_status"] != "APPROVED":
            raise PermissionError("Model binding capability version is stale or missing")
        cap = version["capability"]
        if (
            cap["provider"] != request.provider
            or cap["transport"] != request.transport
            or cap["model"] != request.model
            or cap["status"] != "AVAILABLE"
            or cap["verification_status"] != "VERIFIED"
            or cap["permissions_required"] != ["read"]
            or not {"transport-proof:" + request.work_proof, "run:" + proofs["workitem"]["run_id"]}
            <= set(cap["evidence"])
        ):
            raise PermissionError(
                "Model binding capabilities must be verified for these read proofs"
            )
        adoption_qa = records.get(version["qa_run_id"], conn=conn)
        build = records.get(adoption_qa["implementation_run_id"], conn=conn)
        latest = Quality(records).require_pass(build["id"], build["change_commit"], conn=conn)
        if (
            latest["id"] != adoption_qa["id"]
            or build["owner"] != "core"
            or "capability:" + fingerprint(cap) not in build["evidence"]
        ):
            raise PermissionError("Capability adoption QA is no longer valid")
        names.add(cap["capability"])
    if names != READ_CAPABILITIES:
        raise PermissionError("Model binding requires exactly the three bounded read capabilities")


def publish_model_binding(records, request, implementation_id, commit):
    """Trusted Core publication, never an agent/API route or mutable grant update."""
    if records.store.scope is not None:
        raise PermissionError("Model binding publication requires trusted Core host")
    request = ModelBindingRequest.model_validate(request)
    with records.store.lease("agent-creation"), records.store.connect() as conn:
        records.ledger.check(records.ledger.control(conn, True), agent=request.agent_id)
        row = conn.execute(
            "SELECT owner,definition,status,active_runs FROM core.agent_instances WHERE id=%s FOR UPDATE",
            (request.agent_id,),
        ).fetchone()
        if not row or row["owner"] != "core" or row["status"] != "ACTIVE" or row["active_runs"]:
            raise PermissionError("Model binding requires an idle active Core-owned agent")
        running = conn.execute(
            "SELECT 1 FROM core.day3_records WHERE kind='TransportRun' "
            "AND payload->>'agent'=%s AND payload->>'status'='RUNNING' LIMIT 1",
            (request.agent_id,),
        ).fetchone()
        if running:
            raise PermissionError("Model binding requires no active provider run")
        qa = Quality(records).require_pass(implementation_id, commit, conn=conn)
        build = records.get(implementation_id, conn=conn)
        marker = binding_marker(request)
        if (
            build["owner"] != "core"
            or marker not in build["evidence"]
            or marker not in qa["evidence"]
        ):
            raise PermissionError("Independent QA must cover this exact model binding")
        _validate(records, row["definition"], request, conn=conn)
        return records.append(
            "AgentModelBinding",
            {
                "request": request.model_dump(mode="json"),
                "implementation_id": implementation_id,
                "commit": commit,
                "qa_id": qa["id"],
                "adopted_at": now().isoformat(),
            },
            owner="core",
            conn=conn,
        )


def effective_model(records, definition, *, conn):
    from trading_core.providers.recovery import effective

    recovered = effective(records, definition, conn)
    if recovered is not None:
        return recovered
    rows = [
        r
        for r in records.list("AgentModelBinding", conn=conn)
        if r["owner"] == "core"
        and (r.get("request") or {}).get("agent_id") == definition["agent_id"]
    ]
    if not rows:
        return definition
    binding = rows[-1]
    try:
        request = ModelBindingRequest.model_validate(binding["request"])
        qa = Quality(records).require_pass(
            binding["implementation_id"], binding["commit"], conn=conn
        )
        build = records.get(binding["implementation_id"], conn=conn)
        marker = binding_marker(request)
        if (
            qa["id"] != binding["qa_id"]
            or build["owner"] != "core"
            or marker not in build["evidence"]
            or marker not in qa["evidence"]
        ):
            raise PermissionError("Model binding QA is no longer current")
        _validate(records, definition, request, conn=conn)
    except (PermissionError, KeyError, ValueError, TypeError):
        return {**definition, "execution_eligible": False, "model_binding_status": "UNAVAILABLE"}
    return {**definition, "model": request.model}
