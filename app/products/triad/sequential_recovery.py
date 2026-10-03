"""Explicit host recovery of a rejected, unapplied patch; never replay a merge."""

import json
from zoneinfo import ZoneInfo

from trading_core.cycle_records import CycleRecord
from trading_core.product_changes import PRODUCT_ROOTS
from trading_core.product_deployment import health
from trading_core.work import State, now

ERROR = "Product source changed since proposal"
SELECTION_ERROR = "Requested agent is not eligible; no silent substitution"
EMPTY_PATCH_ERROR = 'Invalid product artifact: [{"type": "too_short", "loc": ["files"], "msg": "Tuple should have at least 1 item after validation, not 0"}]'
ORDER = ("CODEX", "CLAUDE", "GROK")


def require(condition, message):
    if not condition:
        raise PermissionError(message)


def selection_rejection(daily, mission, agent, prior, conn, turns):
    """A routing refusal before a build can replan, never replay product writes."""
    works = [w for w in daily.product.store.list_work(10000) if w.mission_id == mission]
    retained_work = {
        daily.host.get(t["implementation_id"], conn=conn)["work_item_id"]
        for t in turns
        if t.get("implementation_id")
    }
    pending = [
        w
        for w in works
        if w.work_item_id not in retained_work and w.work_item_id != prior["parent_work_item_id"]
    ]
    require(
        all(
            w.owner == "triad"
            and w.parent_work_item_id == prior["parent_work_item_id"]
            and w.work_type == "review"
            and w.authority_tier == 0
            and set(w.execution_permissions) == {"read"}
            and set(w.allowed_tools) <= {"read_file"}
            for w in pending
        ),
        "Unaccounted write authority prevents selection recovery",
    )
    for kind in ("ProductBuildCheckpoint", "ProductBuild", "ImplementationRun"):
        require(
            not any(
                (
                    r.get("mission_id") == mission
                    or r.get("work_item_id") in {w.work_item_id for w in works}
                )
                and r.get("work_item_id") not in retained_work
                for r in daily.product.list(kind, conn=conn)
            ),
            "Unaccounted build evidence prevents selection recovery",
        )
    reservations = conn.execute(
        "SELECT work_item_id FROM core.day3_records WHERE owner='triad' AND kind='BudgetReservation' "
        "AND work_item_id=ANY(%s) AND payload->>'improvement'='true'",
        ([w.work_item_id for w in pending],),
    ).fetchall()
    require(not reservations, "Unaccounted change reservation prevents selection recovery")
    require(
        not any(w.status == State.IN_PROGRESS for w in works),
        "Selection recovery requires an idle cycle",
    )
    require(
        not any(
            w.work_type == "development" and w.assigned_agent not in ORDER[: ORDER.index(agent)]
            for w in works
        ),
        "Selection recovery cannot replay a development assignment",
    )
    require(
        not any(
            r.get("cycle_id") == mission and r.get("builder") not in ORDER[: ORDER.index(agent)]
            for r in daily.product.list("ProductTurnApproval", conn=conn)
        ),
        "Selection recovery requires an unapproved next turn",
    )
    reviews = [
        w
        for w in works
        if w.work_type == "review"
        and w.assigned_agent == agent
        and w.owner == "triad"
        and w.parent_work_item_id == prior["parent_work_item_id"]
    ]
    contexts = [
        r
        for r in daily.product.list("ProductPlanningContext", conn=conn)
        if r.get("mission_id") == mission and r.get("proposer") == agent
    ]
    require(bool(reviews) and bool(contexts), "Canonical read-only planning evidence required")
    requests = conn.execute(
        "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind='AgentRunRequest' "
        "AND work_item_id=%s",
        (reviews[0].work_item_id,),
    ).fetchall()
    require(
        len(requests) == 1
        and all(
            requests[0]["payload"].get(k) == v
            for k, v in {
                "work_item_id": reviews[0].work_item_id,
                "mission_id": mission,
                "agent_id": agent,
                "role": "REVIEW",
                "execution_permissions": ["read"],
                "allowed_tools": ["read_file"],
                "control_epoch": prior["control_epoch"],
            }.items()
        ),
        "Canonical read-only planning request required",
    )
    return reviews[0], contexts[-1]["base_commit"]


def native_rejection(daily, mission, agent, prior, policy, conn, *, empty_patch=False):
    """Prove the host rejected an isolated result before any patch or reservation."""
    works = [
        w
        for w in daily.product.store.list_work(10000)
        if w.mission_id == mission and w.work_type == "development"
    ]
    require(bool(works), "Failed native work required")
    work = works[0]
    require(
        work.owner == "triad"
        and work.assigned_agent == agent
        and work.status == State.FAILED
        and work.parent_work_item_id == prior["parent_work_item_id"],
        "Native work identity mismatch",
    )
    grant = daily.product.get("workspace-" + work.work_item_id, conn=conn)
    from trading_core.product_workspace_grant import PROFILE
    from trading_core.resource_policy import scope_digest

    require(
        grant["kind"] == "ProductWorkspaceGrant"
        and grant["profile"] == PROFILE
        and grant["work_item_id"] == work.work_item_id
        and grant["agent"] == agent
        and grant["scope_digest"] == scope_digest(work)
        and grant["epoch"] == prior["control_epoch"]
        and grant["policy_id"] == policy["id"],
        "Native workspace authority mismatch",
    )
    events = conn.execute(
        "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind='Event' "
        "AND work_item_id=%s ORDER BY created_at,id",
        (work.work_item_id,),
    ).fetchall()
    failures = [r["payload"] for r in events if r["payload"].get("event") == "provider_failed"]
    evidence = [
        r["payload"] for r in events if r["payload"].get("event") == "native_executor_evidence"
    ]
    if empty_patch:
        results = conn.execute(
            "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind='AgentRunResult' "
            "AND work_item_id=%s",
            (work.work_item_id,),
        ).fetchall()
        require(
            len(results) == 1 and len(evidence) == 1 and not failures,
            "Canonical empty workspace result required",
        )
        result = results[0]["payload"]
        require(
            result.get("status") == "CODE_CHANGE"
            and result.get("files_changed") == []
            and len(result.get("analysis_artifacts", [])) == 1
            and result["analysis_artifacts"][0] == json.dumps({"files": []})
            and evidence[0].get("boundary") == "DOCKER_PRODUCT_WORKSPACE"
            and evidence[0].get("calls") == []
            and type(evidence[0].get("denials")) is int
            and evidence[0]["denials"] == 0,
            "Only an observed empty workspace result may resume",
        )
        run_id = result.get("run_id")
    else:
        interrupted = prior.get("failures", [{}])[-1].get("message") == "GrokTurnIncomplete"
        require(
            len(failures) == len(evidence) == 1
            and failures[0].get("error_class")
            == ("GrokTurnIncomplete" if interrupted else "NativeResultViolation")
            and (
                agent == "GROK"
                and evidence[0].get("failure") == "GrokTurnIncomplete"
                and evidence[0].get("boundary") in {None, "DOCKER_PRODUCT_WORKSPACE"}
                if interrupted
                else evidence[0].get("boundary") == "DOCKER_OFFLINE_TOOLS"
            ),
            "Canonical native rejection required",
        )
        if interrupted:
            require(
                not conn.execute(
                    "SELECT id FROM core.day3_records WHERE owner='triad' AND kind='AgentRunResult' AND work_item_id=%s",
                    (work.work_item_id,),
                ).fetchall(),
                "Interrupted workspace must not have a completed result",
            )
        run_id = failures[0].get("run_id")
    require(
        isinstance(run_id, str) and bool(run_id.strip()) and run_id == evidence[0].get("run_id"),
        "Canonical native run identity required",
    )
    requests = conn.execute(
        "SELECT payload FROM core.day3_records WHERE owner='triad' AND kind='AgentRunRequest' "
        "AND work_item_id=%s",
        (work.work_item_id,),
    ).fetchall()
    expected = {
        "run_id": run_id,
        "work_item_id": work.work_item_id,
        "mission_id": mission,
        "agent_id": agent,
        "role": "IMPLEMENT",
        "control_epoch": prior["control_epoch"],
    }
    require(
        len(requests) == 1 and all(requests[0]["payload"].get(k) == v for k, v in expected.items()),
        "Native rejection must match its actual implementation request",
    )
    require(
        not any(
            r.get("work_item_id") == work.work_item_id
            for r in daily.product.list("ProductBuildCheckpoint", conn=conn)
        ),
        "Native failure already reached host patch application",
    )
    return work, grant["base_commit"]


def resume_patch_failure(flow, mission, *, read_failure=False):
    """Caller holds the daily execution lease. Replan remaining turns normally."""
    service, daily = flow.s, flow.s.daily
    host = daily.host
    require(host.store.scope is None, "Core host recovery required")
    # Product merge/restart and governance changes cannot race the preflight.
    with host.store.lease("triad-product-development"):
        head = service.git.clean_baseline()
        healthy = health(head)
        with host.ledger.gate(), host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (mission,))
            prior = daily.current(mission, conn)
            error = prior.get("failures", [{}])[-1].get("message")
            selection = prior.get("failure_code") == "PermissionError" and error == SELECTION_ERROR
            read_selection = read_failure and (
                (
                    prior.get("failure_code") == "ResourceBlocked"
                    and error == "No new progress; repeated evidence cannot extend a run"
                )
                or (
                    prior.get("failure_code") == "PermissionError"
                    and error == "Invalid or terminal cycle transition"
                )
                or (
                    prior.get("failure_code") == "ProviderError"
                    and error == "NativeReadEvidenceMissing"
                )
            )
            require(
                not read_failure or read_selection,
                "Only a stopped read or saved selection checkpoint may resume",
            )
            selection = selection or read_selection
            native = prior.get("failure_code") == "ProviderError" and error in {
                "NativeResultViolation",
                "GrokTurnIncomplete",
            }
            empty_patch = (
                prior.get("failure_code") == "ProductResponseFormatError"
                and error == EMPTY_PATCH_ERROR
            )
            native = native or empty_patch
            require(
                prior["status"] == "BLOCKED"
                and (
                    selection
                    or native
                    or (prior.get("failure_code") == "PermissionError" and error == ERROR)
                ),
                "Only a rejected, unapplied source or native-result failure may resume",
            )
            history = [
                r
                for r in daily.product.list("DailyCycleTransition", conn=conn)
                if r["cycle_id"] == mission
            ]
            require(
                bool(history)
                and history[-1]["from"] == ("SELECTING" if selection else "BUILDING")
                and history[-1]["to"] == "BLOCKED",
                "Recovery requires a pre-QA build failure",
            )
            flow.guard(mission)
            programs = [
                r
                for r in daily.product.list("SequentialDailyProgram", conn=conn)
                if r["cycle_id"] == mission
            ]
            require(len(programs) == 1, "Unambiguous sequential program required")
            program = programs[0]
            require(
                program["policy_id"] == flow.policy["id"]
                and program["order"] == list(ORDER)
                and program["parent_work_item_id"] == prior["parent_work_item_id"]
                and program["control_epoch"] == prior["control_epoch"],
                "Cycle authority changed",
            )
            day = program["local_date"]
            require(
                read_selection
                or now().astimezone(ZoneInfo(program["timezone"])).date().isoformat() == day,
                "Patch recovery must use the original local day",
            )
            turns = daily.require_turn_prefix(mission, prior, conn)
            require(len(turns) < 3, "Completed provider turns cannot be replayed")
            agent = ORDER[len(turns)]
            retained = {r.get("implementation_id") for r in turns if r.get("implementation_id")}
            merges = [
                r
                for r in daily.product.list("ProductMerge", conn=conn)
                if r.get("mission_id") == mission
            ]
            require(
                all(r.get("implementation_id") in retained for r in merges),
                "Unaccounted merge prevents recovery",
            )
            for turn in turns:
                revision = turn.get("merge_commit") or turn.get("verified_revision")
                service.git.git("merge-base", "--is-ancestor", revision, head)
            if selection:
                work, base_commit = selection_rejection(daily, mission, agent, prior, conn, turns)
                if read_selection:
                    from products.triad.sequential_autorecovery import retained_selection

                    flow.saved_selection = retained_selection(flow, mission, agent, prior, conn)
            elif native:
                work, base_commit = native_rejection(
                    daily, mission, agent, prior, flow.policy, conn, empty_patch=empty_patch
                )
            else:
                checkpoints = [
                    r
                    for r in daily.product.list("ProductBuildCheckpoint", conn=conn)
                    if r.get("mission_id") == mission
                ]
                require(bool(checkpoints), "Isolated build checkpoint required")
                checkpoint = checkpoints[-1]
                work = daily.product.store.get(checkpoint["work_item_id"], conn=conn)
                require(
                    work.owner == "triad"
                    and work.mission_id == mission
                    and work.work_type == "development"
                    and work.parent_work_item_id == prior["parent_work_item_id"]
                    and work.assigned_agent == agent
                    and work.status == State.FAILED,
                    "Failed work does not match the next provider turn",
                )
                failures = [
                    r
                    for r in daily.product.list("ProductBuildFailure", conn=conn)
                    if r.get("work_item_id") == work.work_item_id
                ]
                require(
                    bool(failures) and failures[-1].get("reason") == ERROR,
                    "Canonical patch rejection required",
                )
            implementations = daily.product.list("ImplementationRun", conn=conn)
            require(
                not any(r.get("work_item_id") == work.work_item_id for r in implementations),
                "A recorded implementation cannot be replayed",
            )
            require(
                not any(
                    w.mission_id == mission
                    and w.work_type == "development"
                    and w.status in {State.IN_PROGRESS, State.AWAITING_REVIEW}
                    for w in daily.product.store.list_work(10000)
                ),
                "Cycle still has active development work",
            )
            if not (native or selection):
                git = checkpoint["git"]
                require(
                    checkpoint["phase"] == "ISOLATED"
                    and not git.get("change_commit")
                    and not service.git.git("status", "--porcelain", cwd=git["worktree"])
                    and service.git.git("rev-parse", "HEAD", cwd=git["worktree"])
                    == git["base_commit"],
                    "Failed checkout must remain clean and unapplied",
                )
                base_commit = git["base_commit"]
            service.git.git("merge-base", "--is-ancestor", base_commit, head)
            # The infrastructure repair may change protected orchestration, but
            # no autonomous product source may have moved since the failed build.
            from trading_core.product_changes import protected_orchestration

            changed = service.git.git(
                "diff", "--name-only", base_commit, head, "--", *PRODUCT_ROOTS
            ).splitlines()
            require(
                all(protected_orchestration(p) for p in changed),
                "Product baseline changed; cannot resume this cycle",
            )
            # Refund only the unused change slot, never actual inference usage.
            reservations = conn.execute(
                "SELECT id,payload FROM core.day3_records WHERE kind='BudgetReservation' "
                "AND work_item_id=%s AND payload->>'improvement'='true'",
                (work.work_item_id,),
            ).fetchall()
            refund = 0 if native or selection else 1
            require(len(reservations) == refund, "Unexpected improvement reservation count")
            reservation = None
            if not (native or selection):
                require(len(reservations) == 1, "Exact failed improvement reservation required")
                reservation = reservations[0]
                payload = reservation["payload"]
                require(
                    payload["day"] == day
                    and payload["agent"] == agent
                    and all(payload[k] == 0 for k in ("cost", "tokens", "seconds")),
                    "Unexpected reservation contents",
                )
            failed_work_id = (
                flow.saved_selection["failed_work_id"] if read_selection else work.work_item_id
            )
            action_key = failed_work_id or "proposal-" + flow.saved_selection["checkpoint_id"]
            action_id = ("read-recovery-" if read_selection else "patch-recovery-") + action_key
            require(
                not conn.execute(
                    "SELECT 1 FROM core.day3_records WHERE id=%s", (action_id,)
                ).fetchone(),
                "Failed reservation already recovered",
            )
            total = conn.execute(
                "SELECT changes FROM core.autonomy_daily WHERE day=%s FOR UPDATE", (day,)
            ).fetchone()
            require(total and total["changes"] >= refund, "Missing daily change reservation")
            require(
                not conn.execute(
                    "SELECT 1 FROM triad.improvement_slots WHERE day=%s AND agent=%s", (day, agent)
                ).fetchone(),
                "Legacy product slot requires separate reconciliation",
            )
            flow.guard(mission)
            require(service.git.clean_baseline() == head, "Recovery baseline moved")
            conn.execute(
                "UPDATE core.autonomy_daily SET changes=changes-%s WHERE day=%s", (refund, day)
            )
            host.ledger.put(
                "ControlAction",
                {
                    "action": "resume_stopped_read_review"
                    if read_selection
                    else "resume_unapproved_product_selection"
                    if selection
                    else "resume_unapplied_product_patch",
                    "cycle_id": mission,
                    "failed_work_item_id": failed_work_id,
                    "retained_proposal_id": flow.saved_selection["checkpoint_id"]
                    if read_selection
                    else None,
                    "reservation_id": reservation["id"] if reservation else None,
                    "retained_turn_ids": [r["id"] for r in turns],
                    "prior_failure": prior["failures"],
                    "released_change_slots": refund,
                    "day": day,
                    "revision": head,
                    "health": healthy,
                },
                identifier=action_id,
                conn=conn,
            )
            if prior.get("scheduled"):
                import os

                from products.triad.daily_process import process_info

                identity = process_info(os.getpid())
                require(
                    identity.get("state") == "RUNNING" and identity.get("creation_id"),
                    "Recovery process identity unavailable",
                )
                host.append(
                    "DailyDispatchProcess",
                    {
                        "cycle_id": mission,
                        "pid": os.getpid(),
                        **identity,
                        "recovery_action": action_id,
                    },
                    owner="triad",
                    conn=conn,
                )
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            state = "VERIFYING" if turns else "CREATED"
            payload.update(
                status=state,
                finished_at=None,
                blocked_at=None,
                failure_code=None,
                selected_proposal=None,
                recovery_action=action_id,
                recorded_at=now(),
            )
            record = CycleRecord.model_validate(payload)
            host.append("CycleRecord", record.model_dump(mode="json"), owner="triad", conn=conn)
            host.append(
                "DailyCycleTransition",
                {
                    "cycle_id": mission,
                    "from": "BLOCKED",
                    "to": state,
                    "timestamp": now().isoformat(),
                    "evidence": [action_id],
                },
                owner="triad",
                conn=conn,
            )
            return record, len(turns), day
