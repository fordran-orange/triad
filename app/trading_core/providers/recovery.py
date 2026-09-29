"""Reviewed recovery policy; runtime observations are never independent QA.

Core may remeasure previously granted capabilities after an installation/model
change. It cannot widen a grant, enable an API or invent a successful proof.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from trading_core.intelligence.capabilities import fingerprint
from trading_core.intelligence.model_binding import _validate
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.providers.contracts import SPECS
from trading_core.store import Store
from trading_core.work import now

READ = {
    "structured_output",
    "isolated_text_read",
    "document_analysis",
    "local_execution",
    "private_local_processing",
}
WRITE = {"isolated_text_proposal", "isolated_product_ui_edit"}
SOURCE = "app/trading_core/providers/recovery.py"


def activate(records, implementation_id, commit):
    """One operator-authorized rollout of independently reviewed recovery code."""
    if records.store.scope is not None:
        raise PermissionError("Recovery policy requires Core host")
    from trading_core.engineering import effective_ui_role

    with records.store.lease("provider-recovery-policy"), records.store.connect() as conn:
        records.ledger.check(records.ledger.control(conn, True))
        qa = Quality(records).require_pass(implementation_id, commit, conn=conn)
        build = records.get(implementation_id, conn=conn)
        if build["owner"] != "core" or SOURCE not in build["files"]:
            raise PermissionError("Recovery implementation must have independent source QA")
        versions = records.list("CapabilityVersion", conn=conn)
        baseline = {}
        for row in conn.execute(
            "SELECT definition FROM core.agent_instances WHERE owner='core'"
        ).fetchall():
            raw = row["definition"]
            tid = raw.get("preferred_transport")
            if raw["agent_type"] != "static" or SPECS.get(tid, {}).get("type") not in {
                "CLI",
                "LOCAL",
            }:
                continue
            authority = effective_ui_role(records, raw, conn=conn)
            snapshot_row = conn.execute(
                "SELECT payload FROM core.day3_records WHERE id=%s", ("transport-status-" + tid,)
            ).fetchone()
            status = snapshot_row["payload"] if snapshot_row else {}
            current_model = (status.get("workitem") or {}).get("actual_model") or raw["model"]
            eligible = {}
            for v in versions:
                c = v["capability"]
                if v["owner"] == "core" and c["transport"] == tid and c["model"] == current_model:
                    eligible[c["capability"]] = v
            baseline[raw["agent_id"]] = {
                "digest": fingerprint(raw),
                "templates": [
                    v
                    for name, v in eligible.items()
                    if name in READ | WRITE
                    and name in authority["capabilities"]
                    and v["capability"]["status"] == "AVAILABLE"
                    and v["capability"]["verification_status"] == "VERIFIED"
                ],
                "engineering_adoption": authority.get("engineering_role_adoption"),
            }
        return records.append(
            "ProviderRecoveryPolicy",
            {
                "implementation_id": implementation_id,
                "commit": commit,
                "qa_id": qa["id"],
                "baseline": baseline,
                "enabled": True,
                "created_at": now().isoformat(),
            },
            conn=conn,
        )


def policy(records, conn):
    rows = [r for r in records.list("ProviderRecoveryPolicy", conn=conn) if r["owner"] == "core"]
    if not rows or not rows[-1].get("enabled"):
        return None
    value = rows[-1]
    qa = Quality(records).require_pass(value["implementation_id"], value["commit"], conn=conn)
    if qa["id"] != value["qa_id"]:
        raise PermissionError("Recovery policy approval has changed")
    return value


def validate_attestation(records, raw, value, approved, conn):
    baseline = approved["baseline"][raw["agent_id"]]
    if value["policy_id"] != approved["id"] or fingerprint(raw) != baseline["digest"]:
        raise PermissionError("Recovery authority changed")
    request = SimpleNamespace(
        agent_id=raw["agent_id"],
        previous_model=raw["model"],
        model=value["model"],
        provider=raw["provider"],
        transport=raw["preferred_transport"],
        base_definition_digest=baseline["digest"],
        test_proof=value["test_proof"],
        work_proof=value["work_proof"],
        runtime_identity=value["runtime_identity"],
    )
    _validate(records, raw, request, conn=conn, check_capabilities=False)
    templates = authority(records, raw, approved, conn, model=value["model"])
    templates = [
        t
        for t in templates
        if t["capability"]["capability"] not in WRITE or value.get("write_proof")
    ]
    if value.get("write_proof"):
        from trading_core.providers.recovery_probe import validate_write

        validate_write(
            records,
            raw,
            value,
            conn=conn,
            require_engineering=any(
                t["capability"]["capability"] == "isolated_product_ui_edit" for t in templates
            ),
        )
    return templates


def authority(records, raw, approved, conn, *, model):
    baseline = approved["baseline"][raw["agent_id"]]
    if fingerprint(raw) != baseline["digest"]:
        raise PermissionError("Immutable grant no longer matches recovery policy")
    # Resolve the reviewed role against the original grant, not the moving model.
    if baseline.get("engineering_adoption"):
        # effective_ui_role uses capability.current; raw canonical baseline checks
        # below establish its exact capability first to avoid recursive overlays.
        rows = [
            r
            for r in records.list("EngineeringRoleAdoption", conn=conn)
            if r["owner"] == "core" and r.get("agent") == raw["agent_id"]
        ]
        adoption = next((r for r in rows if r["id"] == baseline["engineering_adoption"]), None)
        if not adoption or rows[-1]["id"] != adoption["id"]:
            raise PermissionError("Engineering role changed")
        if (
            Quality(records).require_pass(
                adoption["implementation_id"], adoption["commit"], conn=conn
            )["id"]
            != adoption["qa_id"]
        ):
            raise PermissionError("Engineering role review revoked")
    # An explicit capability downgrade or withdrawn baseline review remains authoritative.
    versions = records.list("CapabilityVersion", conn=conn)
    current = {}
    for version in versions:
        cap = version["capability"]
        if version["owner"] == "core":
            current[(cap["provider"], cap["transport"], cap["model"], cap["capability"])] = version
    templates = []
    for template in baseline["templates"]:
        cap = template["capability"]
        key = (cap["provider"], cap["transport"], cap["model"], cap["capability"])
        if current.get(key, {}).get("id") != template["id"]:
            raise PermissionError("Baseline capability approval was superseded")
        qa = records.get(template["qa_run_id"], conn=conn)
        build = records.get(qa["implementation_run_id"], conn=conn)
        if (
            Quality(records).require_pass(build["id"], build["change_commit"], conn=conn)["id"]
            != qa["id"]
        ):
            raise PermissionError("Baseline capability review revoked")
        target = current.get((cap["provider"], cap["transport"], model, cap["capability"]))
        if target and (
            target["capability"]["status"] != "AVAILABLE"
            or target["capability"]["verification_status"] != "VERIFIED"
        ):
            raise PermissionError("Current capability was explicitly restricted")
        templates.append(template)
    return templates


def resolved(records, raw, conn):
    approved = policy(records, conn)
    if not approved or raw["agent_id"] not in approved["baseline"]:
        return None
    rows = [
        r
        for r in records.list("ProviderRuntimeAttestation", conn=conn)
        if r["owner"] == "core" and r.get("agent") == raw["agent_id"]
    ]
    if not rows:
        return None
    value = rows[-1]
    templates = validate_attestation(records, raw, value, approved, conn)
    return value, templates


def effective(records, raw, conn):
    try:
        result = resolved(records, raw, conn)
        return {**raw, "model": result[0]["model"]} if result else None
    except (PermissionError, KeyError, ValueError, TypeError):
        return {**raw, "execution_eligible": False, "model_binding_status": "RECOVERING"}


def capabilities(records, *, conn=None):
    if records.store.scope is not None:
        records = Records(Store(records.store.settings))
    if conn is None:
        with records.store.connect() as connection:
            return capabilities(records, conn=connection)
    found = []
    try:
        if not policy(records, conn):
            return found
    except (PermissionError, KeyError, ValueError, TypeError):
        return found
    for row in conn.execute(
        "SELECT definition FROM core.agent_instances WHERE owner='core'"
    ).fetchall():
        raw = row["definition"]
        try:
            result = resolved(records, raw, conn)
            if not result:
                continue
            value, templates = result
            for template in templates:
                cap = template["capability"]
                found.append(
                    {
                        "id": value["id"] + ":" + cap["capability"],
                        "owner": "core",
                        "review_status": "POLICY_VERIFIED",
                        "baseline_qa_run_id": template["qa_run_id"],
                        "runtime_attestation": value["id"],
                        "capability": {
                            **cap,
                            "model": value["model"],
                            "capability_id": cap["transport"]
                            + ":"
                            + value["model"]
                            + ":"
                            + cap["capability"],
                            "verified_at": value["created_at"],
                            "discovery_source": "runtime",
                            "evidence": ["runtime-attestation:" + value["id"]],
                        },
                    }
                )
        except (PermissionError, KeyError, ValueError, TypeError):
            continue
    return found


def recover(control, transport):
    """Called only by trusted host monitoring/preflight. Two bounded read probes;
    one staging probe only for an already approved writing capability. No merge.
    """
    if SPECS[transport]["type"] == "API" or control.ledger.store.scope is not None:
        return
    records = Records(control.ledger.store)
    agent = SPECS[transport]["agent"]
    with records.store.connect() as conn:
        approved = policy(records, conn)
        if not approved or agent not in approved["baseline"]:
            return
        raw = conn.execute(
            "SELECT definition FROM core.agent_instances WHERE id=%s", (agent,)
        ).fetchone()["definition"]
    epoch = control.ledger.guard(agent)["epoch"]
    with records.store.connect() as conn:
        authority(records, raw, approved, conn, model=raw["model"])
    key = "provider-recovery-" + transport
    previous = control.read(key)
    if previous.get("retry_at") and now() < datetime.fromisoformat(previous["retry_at"]):
        return
    with records.store.lease(key):
        if any(
            r.get("agent") == agent and r.get("status") == "RUNNING"
            for r in control.ledger.records("TransportRun", 1000)
        ):
            return
        state = control.snapshot(transport)
        if state.get("auth_state") != "AUTHENTICATED" or state.get("error"):
            return
        try:
            proof = state.get("workitem") or {}
            # Recheck defaults once per day, and immediately after an identity change.
            stale = not proof.get("completed_at") or now() - datetime.fromisoformat(
                proof["completed_at"]
            ) > timedelta(days=1)
            latest = next(
                (
                    u
                    for u in control.ledger.records("Usage", 1000)
                    if u.get("transport") == transport
                    and (
                        u.get("status") == "SUCCESS"
                        or u.get("error_class") == "CapabilityRouteModelMismatch"
                    )
                ),
                {},
            )
            changed = latest.get("actual_model") not in {None, proof.get("actual_model")}
            changed = (
                changed
                or not state.get("runtime_identity")
                or any(
                    (state.get(k) or {}).get("runtime_identity") != state.get("runtime_identity")
                    for k in ("test", "workitem")
                )
            )
            if stale or changed or not control.proven(state):
                from trading_core.providers.verification import verify

                control.ledger.put(
                    "ProviderRecoveryState",
                    {
                        "agent": agent,
                        "status": "VERIFYING",
                        "retry_at": (now() + timedelta(minutes=30)).isoformat(),
                    },
                    identifier=key,
                )
                for acceptance in (False, True):
                    with records.store.connect() as conn:
                        latest_policy = policy(records, conn)
                        if not latest_policy or latest_policy["id"] != approved["id"]:
                            raise PermissionError("Recovery policy changed")
                        authority(
                            records,
                            raw,
                            approved,
                            conn,
                            model=(state.get("workitem") or {}).get("actual_model") or raw["model"],
                        )
                    result = verify(control, transport, acceptance=acceptance, expected_epoch=epoch)
                    if result.get("success") is not True:
                        raise PermissionError(
                            "Compatibility check failed: " + str(result.get("error", "unknown"))
                        )
                state = control.snapshot(transport)
            value = {
                "agent": agent,
                "policy_id": approved["id"],
                "model": state["workitem"]["actual_model"],
                "runtime_identity": state["runtime_identity"],
                "test_proof": state["test"]["proof_id"],
                "work_proof": state["workitem"]["proof_id"],
                "created_at": now().isoformat(),
            }
            try:
                with records.store.connect() as conn:
                    existing = resolved(records, raw, conn)
            except (PermissionError, KeyError, ValueError, TypeError):
                existing = None
            if existing and all(
                existing[0].get(k) == value[k]
                for k in ("policy_id", "model", "test_proof", "work_proof", "runtime_identity")
            ):
                return
            baseline = approved["baseline"][agent]
            if any(t["capability"]["capability"] in WRITE for t in baseline["templates"]):
                from trading_core.providers.recovery_probe import probe_write

                with records.store.connect() as conn:
                    latest_policy = policy(records, conn)
                    if not latest_policy or latest_policy["id"] != approved["id"]:
                        raise PermissionError("Recovery policy changed")
                    authority(records, raw, approved, conn, model=value["model"])
                value["write_proof"] = probe_write(control, raw, baseline, epoch=epoch)
            fresh = control.transport(transport).identity_data()
            if fresh != value["runtime_identity"]:
                raise PermissionError(
                    "Provider changed during compatibility checks; waiting for a stable installation"
                )
            with records.store.connect() as conn:
                control.ledger.check(control.ledger.control(conn, True), agent=agent, epoch=epoch)
                validate_attestation(records, raw, value, approved, conn)
                records.append("ProviderRuntimeAttestation", value, conn=conn)
            control.ledger.put(
                "ProviderRecoveryState",
                {
                    "agent": agent,
                    "status": "READY",
                    "message": "Verified runtime is ready; existing permissions retained.",
                },
                identifier=key,
            )
        except Exception as exc:  # noqa: BLE001 - record bounded failure without stopping other providers
            # One transition alert; repeated background attempts update state without spam.
            message = str(exc) if isinstance(exc, PermissionError) else type(exc).__name__
            control.ledger.put(
                "ProviderRecoveryState",
                {
                    "agent": agent,
                    "status": "BLOCKED",
                    "message": message,
                    "retry_at": (now() + timedelta(minutes=30)).isoformat(),
                },
                identifier=key,
            )
            if previous.get("status") != "BLOCKED" or previous.get("message") != message:
                control.ledger.event("provider_recovery_blocked", agent=agent, reason=message)
