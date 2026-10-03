"""Bounded recovery of stopped read-only operations, inside the cycle's host lease.

Never changes a verdict, provider, authority, budget or completed product turn.
Attempts are append-only and shared across process restarts and format repairs.
"""

import hashlib
import json
import time

from trading_core.resource_policy import ResourceBlocked, ResourceType
from trading_core.runtime import ProviderError

MAX_STAGE_RETRIES = 2
MAX_CYCLE_RETRIES = 6
TRANSIENT = frozenset(
    {
        "DeadlineExceeded",
        "CodexTurnFailed",
        "CodexExecutionEvidenceMissing",
        "NativeReadEvidenceMissing",
        "GrokTurnIncomplete",
    }
)


def recoverable(exc):
    if getattr(exc, "provider_stopped", False) is not True:
        return False
    if isinstance(exc, ResourceBlocked):
        return (
            exc.decision.get("resource_type") == ResourceType.TIME
            and str(exc) == "No new progress; repeated evidence cannot extend a run"
        )
    return isinstance(exc, ProviderError) and exc.error_class in TRANSIENT


def read_with_recovery(flow, mission, agent, objective, context, paths, operation):
    """Only SequentialCycle's read path may call this; implementations never do."""
    key = hashlib.sha256(
        json.dumps(
            [agent, objective, context, list(paths)],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    baseline = flow.s.git.clean_baseline()
    retried = False
    while True:
        flow.guard(mission)
        try:
            completed = operation()
        except Exception as exc:
            eligible = recoverable(exc)
            history = flow.s.rows("ProductAutoRecovery", mission)
            claims = [r for r in history if r.get("status") == "RETRYING"]
            used = sum(r.get("stage_key") == key for r in claims)
            exhausted = used >= MAX_STAGE_RETRIES or len(claims) >= MAX_CYCLE_RETRIES
            if not eligible or exhausted:
                flow.s.record(
                    "ProductAutoRecovery",
                    mission,
                    agent=agent,
                    stage_key=key,
                    status="NEEDS_ATTENTION",
                    attempt=used,
                    previous_run_id=getattr(exc, "run_id", None),
                    failure_class=type(exc).__name__,
                    message=(
                        "Automatic recovery stopped after repeated failures. Earlier work is retained."
                        if exhausted
                        else "This failure requires investigation; automatic retry cannot safely resolve it."
                    ),
                )
                raise
            # A clean unchanged checkout and current authority are checked before
            # every retry. No failed operation can expand its own grant.
            head = flow.s.git.clean_baseline()
            if head != baseline:
                raise PermissionError("Source changed during automatic read recovery") from exc
            flow.guard(mission)
            flow.s.record(
                "ProductAutoRecovery",
                mission,
                agent=agent,
                stage_key=key,
                status="RETRYING",
                attempt=used + 1,
                previous_run_id=getattr(exc, "run_id", None),
                previous_work_item_id=getattr(exc, "work_item_id", None),
                failure_class=type(exc).__name__,
                base_commit=head,
                message=f"Retrying a stopped {agent} read-only task (attempt {used + 1} of {MAX_STAGE_RETRIES}). Completed changes are retained.",
            )
            retried = True
            # Interruptible by the normal kill switch, epoch and policy guards.
            try:
                for _ in range(5 * (used + 1)):
                    time.sleep(1)
                    flow.guard(mission)
                if flow.s.git.clean_baseline() != baseline:
                    raise PermissionError("Source changed during automatic read recovery") from exc
            except Exception:
                flow.s.record(
                    "ProductAutoRecovery",
                    mission,
                    agent=agent,
                    stage_key=key,
                    status="NEEDS_ATTENTION",
                    attempt=used + 1,
                    message="Recovery stopped because execution authority or the checked source changed.",
                )
                raise
            continue
        if retried:
            flow.s.record(
                "ProductAutoRecovery",
                mission,
                agent=agent,
                stage_key=key,
                status="RECOVERED",
                run_id=completed[3].get("run_id"),
                message=f"{agent}'s read-only task recovered. The cycle is continuing.",
            )
        return completed


def retained_selection(flow, mission, agent, prior, conn):
    """Validate an old stopped selection before host-authorized checkpoint recovery.

    The caller additionally proves the completed turn prefix, no unaccounted
    writes/merges/reservations, unchanged product source and unchanged authority.
    This path does not auto-dispatch historical cycles or refund inference usage.
    """
    from datetime import datetime, timedelta

    from trading_core.work import State, now

    from products.triad.sequential import REVIEWERS, Proposal
    from products.triad.sequential_recovery import require

    daily = flow.s.daily
    created = prior["created_at"]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    require(
        timedelta(0) <= now() - created <= timedelta(hours=48),
        "Stale cycle requires a fresh operator assessment",
    )
    all_cycles = daily.product.list("CycleRecord", conn=conn)
    require(
        not any(
            r.get("cycle_type") == "DAILY_PRODUCT"
            and r.get("cycle_id") != mission
            and datetime.fromisoformat(r["created_at"]) > created
            for r in all_cycles
        ),
        "A newer daily cycle prevents checkpoint recovery",
    )
    proposals = [
        r
        for r in daily.product.list("ProductProposal", conn=conn)
        if r.get("mission_id") == mission and r.get("proposer") == agent
    ]
    require(bool(proposals), "Saved proposal required")
    saved = proposals[-1]
    proposal = Proposal.model_validate(saved["proposal"])
    records = conn.execute(
        "SELECT kind,work_item_id,payload FROM core.day3_records "
        "WHERE owner='triad' AND kind IN ('AgentRunRequest','AgentRunResult','ResourceExtensionDecision','TransportRun','Event') "
        "ORDER BY created_at,id"
    ).fetchall()
    requests = [
        r["payload"]
        for r in records
        if r["kind"] == "AgentRunRequest" and r["payload"].get("mission_id") == mission
    ]
    require(bool(requests), "Canonical read request required")
    author = proposal_author(daily, records, requests, proposal, mission, agent, prior, conn)
    selection = {
        "proposal": proposal,
        "attempt": saved["attempt"],
        "checkpoint_id": saved["id"],
        "author_work_id": author["work_item_id"],
        "author_run_id": author["run_id"],
    }
    if (
        prior.get("failure_code") == "PermissionError"
        and prior.get("failures", [{}])[-1].get("message") == "Invalid or terminal cycle transition"
    ):
        # A completed revised proposal was stored before an erroneous duplicate
        # SELECTING transition. No reviewer or builder ran for this checkpoint.
        require(requests[-1] == author, "Later work prevents proposal checkpoint recovery")
        reviews = [
            r
            for r in daily.product.list("ProductProposalReview", conn=conn)
            if r.get("mission_id") == mission and r.get("proposer") == agent
        ]
        require(
            not any(r.get("proposal") == saved["proposal"] for r in reviews),
            "An already reviewed proposal must not be replayed",
        )
        require(
            bool(reviews)
            and reviews[-1].get("decision") == "REQUEST_CHANGES"
            and reviews[-1]["recorded_at"] < saved["recorded_at"],
            "Prior correction request and later saved proposal required",
        )
        return {**selection, "failed_work_id": None, "failed_run_id": None}
    failed = requests[-1]
    failed_rows = [r for r in records if r["kind"] == "AgentRunRequest" and r["payload"] == failed]
    require(
        len(failed_rows) == 1 and failed_rows[0]["work_item_id"] == failed["work_item_id"],
        "Failed request record identity mismatch",
    )
    work = daily.product.store.get(failed["work_item_id"], conn=conn)
    missing_reads = (
        prior.get("failure_code") == "ProviderError"
        and prior.get("failures", [{}])[-1].get("message") == "NativeReadEvidenceMissing"
    )
    require(
        failed.get("role") == "REVIEW"
        and failed.get("agent_id") == REVIEWERS[agent]
        and work.owner == "triad"
        and work.mission_id == mission
        and work.status == (State.FAILED if missing_reads else State.BLOCKED)
        and work.work_type == "review"
        and work.authority_tier == 0
        and work.assigned_agent == REVIEWERS[agent]
        and work.parent_work_item_id == prior["parent_work_item_id"]
        and failed.get("execution_permissions") == ["read"]
        and failed.get("allowed_tools") == ["read_file"]
        and failed.get("control_epoch") == prior["control_epoch"],
        "Only the next designated reviewer's stopped read may resume",
    )
    run_id = failed["run_id"]
    evidence = [r for r in records if r["payload"].get("run_id") == run_id]
    require(
        all(
            r["work_item_id"] == failed["work_item_id"]
            if r["kind"] != "ResourceExtensionDecision"
            else r["work_item_id"] in (None, failed["work_item_id"])
            and r["payload"].get("work_item_id") == failed["work_item_id"]
            and r["payload"].get("agent_id") == REVIEWERS[agent]
            for r in evidence
        ),
        "Failed run evidence belongs to another work assignment",
    )
    require(
        not any(r["kind"] == "AgentRunResult" for r in evidence),
        "Completed review must not be replayed",
    )
    transports = [r["payload"] for r in evidence if r["kind"] == "TransportRun"]
    if missing_reads:
        events = [r["payload"] for r in evidence if r["kind"] == "Event"]
        failures = [r for r in events if r.get("event") == "provider_failed"]
        native = [r for r in events if r.get("event") == "native_executor_evidence"]
        # Native evidence is appended only after the isolated harness's finally
        # closes/waits for its process. Require that cleanup evidence plus the
        # terminal transport, never a model's assertion that its work stopped.
        require(
            len(failures) == len(native) == len(transports) == 1
            and failures[0].get("error_class") == "NativeReadEvidenceMissing"
            and native[0].get("boundary") == "DOCKER_OFFLINE_TOOLS"
            and type(native[0].get("denials")) is int
            and native[0]["denials"] == 0
            and bool(native[0].get("calls"))
            and all(call.get("tool") == "read_file" for call in native[0]["calls"])
            and transports[0].get("status") == "DEGRADED"
            and transports[0].get("error_class") == "NativeReadEvidenceMissing"
            and bool(transports[0].get("completed_at")),
            "Canonical stopped native read evidence required",
        )
    else:
        decisions = [r["payload"] for r in evidence if r["kind"] == "ResourceExtensionDecision"]
        require(
            bool(decisions)
            and decisions[-1].get("decision") == "DENY"
            and decisions[-1].get("resource_type") == ResourceType.TIME
            and decisions[-1].get("reason") == "No new progress; repeated evidence cannot extend a run",
            "Canonical read timeout required",
        )
        require(
            bool(transports) and transports[-1].get("status") == "BLOCKED_RESOURCE_LIMIT",
            "Terminal transport evidence required",
        )
    route = daily.product.get("route-" + work.work_item_id, conn=conn)["selected"]
    require(
        route.get("agent_id") == REVIEWERS[agent]
        and all(
            t.get("work_item_id") == work.work_item_id
            and t.get("agent") == REVIEWERS[agent]
            and t.get("provider") == route["provider"]
            and t.get("transport") == route["transport"]
            for t in transports
        ),
        "Stopped transport differs from the canonical provider route",
    )
    return {
        **selection,
        "failed_work_id": failed["work_item_id"],
        "failed_run_id": failed["run_id"],
    }


def proposal_author(daily, records, requests, proposal, mission, agent, prior, conn):
    from trading_core.work import State

    from products.triad.sequential import Proposal
    from products.triad.sequential_recovery import require

    authors = []
    for request in requests:
        if request.get("agent_id") != agent or request.get("role") != "REVIEW":
            continue
        results = [
            r["payload"]
            for r in records
            if r["kind"] == "AgentRunResult" and r["payload"].get("run_id") == request["run_id"]
        ]
        for result in results:
            artifacts = result.get("analysis_artifacts", [])
            if len(artifacts) != 1:
                continue
            try:
                parsed = (
                    Proposal.model_validate(artifacts[0])
                    if isinstance(artifacts[0], dict)
                    else Proposal.model_validate_json(artifacts[0])
                )
            except ValueError:
                continue
            if parsed == proposal:
                require(
                    all(
                        r["work_item_id"] == request["work_item_id"]
                        for r in records
                        if r["kind"] in {"AgentRunRequest", "AgentRunResult"}
                        and r["payload"].get("run_id") == request["run_id"]
                    ),
                    "Author request/result record identity mismatch",
                )
                authors.append(request)
    require(len(authors) == 1, "Unambiguous original proposal author evidence required")
    author = authors[0]
    author_work = daily.product.store.get(author["work_item_id"], conn=conn)
    require(
        author_work.status == State.COMPLETED
        and author_work.authority_tier == 0
        and author_work.owner == "triad"
        and author_work.mission_id == mission
        and author_work.assigned_agent == agent
        and author_work.parent_work_item_id == prior["parent_work_item_id"]
        and author.get("control_epoch") == prior["control_epoch"]
        and author.get("execution_permissions") == ["read"]
        and author.get("allowed_tools") == ["read_file"],
        "Completed read-only proposal required",
    )
    return author
