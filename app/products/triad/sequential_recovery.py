"""Explicit host recovery of a rejected, unapplied patch; never replay a merge."""

import json
from zoneinfo import ZoneInfo

from trading_core.cycle_records import CycleRecord
from trading_core.product_changes import PRODUCT_ROOTS
from trading_core.product_deployment import health
from trading_core.work import State, now

ERROR = "Product source changed since proposal"
EMPTY_PATCH_ERROR = 'Invalid product artifact: [{"type": "too_short", "loc": ["files"], "msg": "Tuple should have at least 1 item after validation, not 0"}]'
ORDER = ("CODEX", "CLAUDE", "GROK")


def require(condition, message):
    if not condition:
        raise PermissionError(message)


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
        require(
            len(failures) == len(evidence) == 1
            and failures[0].get("error_class") == "NativeResultViolation"
            and evidence[0].get("boundary") == "DOCKER_OFFLINE_TOOLS",
            "Canonical native rejection required",
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


def resume_patch_failure(flow, mission):
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
            native = (
                prior.get("failure_code") == "ProviderError" and error == "NativeResultViolation"
            )
            empty_patch = (
                prior.get("failure_code") == "ProductResponseFormatError"
                and error == EMPTY_PATCH_ERROR
            )
            native = native or empty_patch
            require(
                prior["status"] == "BLOCKED"
                and (native or (prior.get("failure_code") == "PermissionError" and error == ERROR)),
                "Only a rejected, unapplied source or native-result failure may resume",
            )
            history = [
                r
                for r in daily.product.list("DailyCycleTransition", conn=conn)
                if r["cycle_id"] == mission
            ]
            require(
                bool(history)
                and history[-1]["from"] == "BUILDING"
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
                now().astimezone(ZoneInfo(program["timezone"])).date().isoformat() == day,
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
            if native:
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
            if not native:
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
            refund = 0 if native else 1
            require(len(reservations) == refund, "Unexpected improvement reservation count")
            reservation = None
            if not native:
                require(len(reservations) == 1, "Exact failed improvement reservation required")
                reservation = reservations[0]
                payload = reservation["payload"]
                require(
                    payload["day"] == day
                    and payload["agent"] == agent
                    and all(payload[k] == 0 for k in ("cost", "tokens", "seconds")),
                    "Unexpected reservation contents",
                )
            action_id = "patch-recovery-" + work.work_item_id
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
                    "action": "resume_unapplied_product_patch",
                    "cycle_id": mission,
                    "failed_work_item_id": work.work_item_id,
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
