"""A rejected read-only proposal may replan; claimed edits are never applied."""

from trading_core.work import State

from products.triad.sequential_recovery import require


def settled_failed_turn_work(daily, mission, prior, works, turns, conn, git):
    """Account only host-recovered failures preceding a validated completed turn.

    The caller has already validated the entire completed prefix. This consumes
    original settlement evidence; it never releases another reservation or
    authorizes another build of an old attempt.
    """
    import re

    retained = set()
    by_agent = {t["agent"]: (index, t) for index, t in enumerate(turns)}
    for work in works:
        if work.work_type != "development" or work.status != State.FAILED:
            continue
        require(
            work.owner == "triad"
            and work.mission_id == mission
            and work.parent_work_item_id == prior["parent_work_item_id"]
            and work.authority_tier == 2
            and set(work.execution_permissions) == {"read", "write_code"}
            and set(work.allowed_tools) == {"read_file", "write_artifact"}
            and work.assigned_agent in by_agent,
            "Failed predecessor lacks a validated completed provider turn",
        )
        index, turn = by_agent[work.assigned_agent]
        action_id = "patch-recovery-" + work.work_item_id
        rows = conn.execute(
            "SELECT id,payload,created_at FROM core.day3_records WHERE id=%s "
            "AND kind='ControlAction' AND owner='core'",
            (action_id,),
        ).fetchall()
        require(len(rows) == 1, "Exact Core predecessor settlement required")
        row, action = rows[0], rows[0]["payload"]
        completed = conn.execute(
            "SELECT created_at FROM core.intelligence_records WHERE id=%s "
            "AND kind='ProductTurn' AND owner='triad'",
            (turn["id"],),
        ).fetchone()
        blocked = conn.execute(
            "SELECT payload FROM core.intelligence_records WHERE owner='triad' "
            "AND kind='CycleRecord' AND payload->>'cycle_id'=%s AND created_at<%s "
            "ORDER BY created_at DESC,id DESC LIMIT 1",
            (mission, row["created_at"]),
        ).fetchone()
        day = daily.product.list(
            "SequentialDailyProgram", matching={"cycle_id": mission}, conn=conn
        )[0]["local_date"]
        revision = action.get("revision")
        healthy = action.get("health", {})
        require(
            completed
            and row["created_at"] < completed["created_at"]
            and blocked
            and blocked["payload"].get("status") == "BLOCKED"
            and bool(blocked["payload"].get("failures"))
            and action.get("prior_failure") == blocked["payload"]["failures"]
            and action.get("action") == "resume_unapplied_product_patch"
            and action.get("cycle_id") == mission
            and action.get("failed_work_item_id") == work.work_item_id
            and action.get("retained_turn_ids") == [t["id"] for t in turns[:index]]
            and action.get("day") == day
            and isinstance(revision, str)
            and re.fullmatch(r"[a-f0-9]{40}", revision)
            and healthy.get("loaded_revision") == revision
            and healthy.get("development_provider_gate") == "PASS"
            and bool(healthy.get("routes"))
            and all(status == 200 for status in healthy["routes"].values())
            and type(action.get("released_change_slots")) is int
            and action["released_change_slots"] in {0, 1},
            "Predecessor settlement identity, ordering or health differs",
        )
        require(git is not None, "Canonical predecessor Git proof required")
        git.git(
            "merge-base",
            "--is-ancestor",
            revision,
            turn.get("merge_commit") or turn.get("verified_revision"),
        )
        reservations = conn.execute(
            "SELECT id,payload FROM core.day3_records WHERE kind='BudgetReservation' "
            "AND owner='triad' AND work_item_id=%s AND payload->>'improvement'='true'",
            (work.work_item_id,),
        ).fetchall()
        refund = action["released_change_slots"]
        require(len(reservations) == refund, "Predecessor reservation settlement differs")
        if refund:
            reservation = reservations[0]
            payload = reservation["payload"]
            require(
                reservation["id"] == action.get("reservation_id")
                and payload.get("day") == day
                and payload.get("agent") == work.assigned_agent
                and all(payload.get(k) == 0 for k in ("cost", "tokens", "seconds")),
                "Predecessor refund does not bind its original reservation",
            )
        else:
            require(action.get("reservation_id") is None, "Unexpected predecessor refund")
        require(
            not any(
                r.get("work_item_id") == work.work_item_id
                for kind in ("ImplementationRun", "ProductBuild", "ProductMerge")
                for r in daily.product.list(kind, conn=conn)
            ),
            "Implemented predecessor cannot be treated as an unapplied failure",
        )
        retained.add(work.work_item_id)
    return retained


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
        "AND kind IN ('Event','TransportRun','AgentRunResult') "
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
