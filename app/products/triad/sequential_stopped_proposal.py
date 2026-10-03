"""A rejected read-only proposal may replan; claimed edits are never applied."""

from trading_core.work import State

from products.triad.sequential_recovery import require


def require_stopped_proposal(daily, mission, agent, prior, work, conn):
    require(
        work.owner == "triad"
        and work.mission_id == mission
        and work.assigned_agent == agent
        and work.status == State.FAILED
        and work.parent_work_item_id == prior["parent_work_item_id"]
        and work.work_type == "review"
        and work.authority_tier == 0
        and set(work.execution_permissions) == {"read"}
        and set(work.allowed_tools) == {"read_file"},
        "Stopped proposal must be the next agent's failed read-only work",
    )
    started = daily.product.list("ProductTurnStarted", matching={"mission_id": mission}, conn=conn)
    require(bool(started) and started[-1]["agent"] == agent, "Next proposal turn identity required")
    requests = conn.execute(
        "SELECT work_item_id,payload FROM core.day3_records WHERE owner='triad' "
        "AND kind='AgentRunRequest' AND payload->>'mission_id'=%s ORDER BY created_at DESC,id DESC",
        (mission,),
    ).fetchall()
    require(bool(requests), "Stopped proposal request required")
    request = requests[0]["payload"]
    require(
        requests[0]["work_item_id"] == work.work_item_id
        and all(
            request.get(k) == v
            for k, v in {
                "work_item_id": work.work_item_id,
                "mission_id": mission,
                "agent_id": agent,
                "role": "REVIEW",
                "execution_permissions": ["read"],
                "allowed_tools": ["read_file"],
                "control_epoch": prior["control_epoch"],
            }.items()
        )
        and isinstance(request.get("run_id"), str)
        and bool(request["run_id"]),
        "Stopped proposal request identity differs",
    )
    rows = conn.execute(
        "SELECT kind,work_item_id,payload FROM core.day3_records WHERE owner='triad' "
        "AND (work_item_id=%s OR payload->>'run_id'=%s) ORDER BY created_at,id",
        (work.work_item_id, request["run_id"]),
    ).fetchall()
    require(
        not any(r["kind"] == "AgentRunResult" for r in rows), "Completed proposal cannot replay"
    )
    failures = [
        r["payload"]
        for r in rows
        if r["kind"] == "Event" and r["payload"].get("event") == "provider_failed"
    ]
    native = [
        r["payload"]
        for r in rows
        if r["kind"] == "Event" and r["payload"].get("event") == "native_executor_evidence"
    ]
    transports = [r["payload"] for r in rows if r["kind"] == "TransportRun"]
    require(
        len(failures) == len(native) == len(transports) == 1,
        "Unique stopped proposal evidence required",
    )
    routing = daily.product.get("route-" + work.work_item_id, conn=conn)
    require(
        routing["kind"] == "CapabilityRoutingDecision" and routing["owner"] == "triad",
        "Canonical proposal route required",
    )
    route = routing["selected"]
    require(
        all(r["work_item_id"] == work.work_item_id for r in rows)
        and all(r.get("run_id") == request["run_id"] for r in failures + native + transports)
        and failures[0].get("error_class") == "NativeProposalEvidenceMismatch"
        and native[0].get("boundary") == "DOCKER_OFFLINE_TOOLS"
        and type(native[0].get("denials")) is int
        and native[0]["denials"] == 0
        and bool(native[0].get("calls"))
        and all(c.get("tool") == "read_file" for c in native[0]["calls"])
        and native[0].get("usage_scope") == "COMPLETE"
        and all(
            type(native[0].get(k)) is int and native[0][k] >= 0
            for k in ("input_tokens", "output_tokens")
        )
        and route.get("agent_id") == agent
        and transports[0].get("work_item_id") == work.work_item_id
        and transports[0].get("agent") == agent
        and transports[0].get("provider") == route["provider"]
        and transports[0].get("transport") == route["transport"]
        and transports[0].get("status") == "DEGRADED"
        and transports[0].get("error_class") == "NativeProposalEvidenceMismatch"
        and bool(transports[0].get("completed_at")),
        "Canonical stopped read-only proposal evidence required",
    )
