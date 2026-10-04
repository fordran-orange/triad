"""Continue substantive read-only revisions without approving by exhaustion."""

import hashlib
import json


def proposal_digest(proposal):
    """Title/evidence-only churn is not a correction of the proposed behavior."""

    def normalize(value):
        if isinstance(value, str):
            return " ".join(value.split())
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [normalize(v) for v in value]
        return value

    content = {
        k: proposal[k] for k in ("outcome", "change", "files", "acceptance") if k in proposal
    }
    contribution = proposal.get("value_plan", {}).get("application_contribution")
    if contribution is not None:
        content["application_contribution"] = contribution
    return hashlib.sha256(json.dumps(normalize(content), sort_keys=True).encode()).hexdigest()


def reviewed_revision(daily, mission, agent, prior, author_work, conn):
    """Prove a stopped, unapproved read-only revision; never override its verdict."""
    from trading_core.work import State

    from products.triad.sequential import REVIEWERS, Proposal
    from products.triad.sequential_autorecovery import proposal_author
    from products.triad.sequential_recovery import require

    started = daily.product.list("ProductTurnStarted", matching={"mission_id": mission}, conn=conn)
    require(bool(started) and started[-1].get("agent") == agent, "Current revision turn required")
    proposals = daily.product.list(
        "ProductProposal", matching={"mission_id": mission, "proposer": agent}, conn=conn
    )
    reviews = daily.product.list(
        "ProductProposalReview", matching={"mission_id": mission, "proposer": agent}, conn=conn
    )
    require(bool(proposals) and bool(reviews), "Completed revision checkpoint required")
    saved, review = proposals[-1], reviews[-1]
    proposal = Proposal.model_validate(saved["proposal"])
    message = prior["failures"][-1]["message"]
    stalled = message == "Proposal revision made no progress: " + review["summary"]
    require(
        review.get("decision")
        in ({"REQUEST_CHANGES", "REJECT"} if stalled else {"REQUEST_CHANGES"})
        and review.get("reviewer") == REVIEWERS[agent]
        and review.get("attempt") == saved.get("attempt")
        and review.get("proposal") == saved["proposal"]
        and type(saved.get("attempt")) is int
        and saved["attempt"] >= (2 if stalled else 3)
        and (stalled or message == "Proposal revision attempts exhausted: " + review["summary"]),
        "Exact latest unapproved revision checkpoint required",
    )
    if stalled:
        # The stop was deliberate. Explicit continuation requires its actual
        # repeated behavior, not just a caller-supplied failure message.
        repeated = {
            p["attempt"]: p["proposal"]
            for p in proposals[:-1]
            if type(p.get("attempt")) is int and p["attempt"] < saved["attempt"]
        }
        require(
            any(
                r.get("decision") in {"REQUEST_CHANGES", "REJECT"}
                and r.get("reviewer") == REVIEWERS[agent]
                and type(r.get("attempt")) is int
                and r["attempt"] in repeated
                and r.get("proposal") == repeated[r["attempt"]]
                and proposal_digest(r["proposal"]) == proposal_digest(saved["proposal"])
                for r in reviews[:-1]
            ),
            "Stopped revision requires matching earlier unapproved repeated behavior",
        )
    rows = conn.execute(
        "SELECT kind,work_item_id,payload FROM core.day3_records WHERE owner='triad' "
        "AND kind IN ('AgentRunRequest','AgentRunResult','Usage','TransportRun','Event') "
        "AND (payload->>'mission_id'=%s OR work_item_id=ANY(SELECT id FROM core.work_items WHERE mission_id=%s)) "
        "ORDER BY created_at,id",
        (mission, mission),
    ).fetchall()
    requests = [r["payload"] for r in rows if r["kind"] == "AgentRunRequest"]
    author = proposal_author(daily, rows, requests, proposal, mission, agent, prior, conn)
    require(author["work_item_id"] == author_work.work_item_id, "Latest revision author differs")
    require(bool(requests), "Latest revision reviewer request required")
    request = requests[-1]
    work = daily.product.store.get(request["work_item_id"], conn=conn)
    require(
        request.get("run_id") == review["run_id"]
        and request.get("agent_id") == REVIEWERS[agent]
        and request.get("mission_id") == mission
        and request.get("control_epoch") == prior["control_epoch"]
        and request.get("role") == "REVIEW"
        and request.get("execution_permissions") == ["read"]
        and request.get("allowed_tools") == ["read_file"]
        and request.get("context_packet", {}).get("proposal") == saved["proposal"]
        and request.get("context_packet", {}).get("base_commit")
        == author["context_packet"]["base_commit"]
        and work.owner == "triad"
        and work.mission_id == mission
        and work.parent_work_item_id == prior["parent_work_item_id"]
        and work.assigned_agent == REVIEWERS[agent]
        and work.work_type == "review"
        and work.authority_tier == 0
        and work.status == State.COMPLETED
        and set(work.allowed_tools) == {"read_file"}
        and set(work.execution_permissions) == {"read"},
        "Completed independent revision reviewer required",
    )
    for current, run, expected_agent in (
        (author_work, author["run_id"], agent),
        (work, review["run_id"], REVIEWERS[agent]),
    ):
        evidence = [r for r in rows if r["payload"].get("run_id") == run]
        require(
            sum(r["kind"] == "AgentRunRequest" for r in evidence) == 1,
            "Unique canonical revision request required",
        )
        require(
            all(r["work_item_id"] == current.work_item_id for r in evidence),
            "Crossed revision run evidence",
        )
        results = [r["payload"] for r in evidence if r["kind"] == "AgentRunResult"]
        usages = [r["payload"] for r in evidence if r["kind"] == "Usage"]
        transports = [r["payload"] for r in evidence if r["kind"] == "TransportRun"]
        native = [
            r["payload"]
            for r in evidence
            if r["kind"] == "Event" and r["payload"].get("event") == "native_executor_evidence"
        ]
        require(
            len(results) == len(usages) == len(transports) == len(native) == 1,
            "Unique completed revision proof required",
        )
        result, usage, transport = results[0], usages[0], transports[0]
        routed = daily.product.get("route-" + current.work_item_id, conn=conn)
        require(
            routed.get("kind") == "CapabilityRoutingDecision" and routed.get("owner") == "triad",
            "Canonical revision route required",
        )
        route = routed["selected"]
        require(
            result.get("mode") == "REAL"
            and result.get("status") != "BLOCKED"
            and not result.get("files_changed")
            and not result.get("proposal")
            and usage.get("mode") == "REAL"
            and usage.get("status") == "SUCCESS"
            and usage.get("agent") == expected_agent
            and transport.get("status") == "SUCCESS"
            and bool(transport.get("completed_at"))
            and transport.get("work_item_id") == current.work_item_id
            and transport.get("agent") == expected_agent,
            "Revision requires successful real read-only provider proof",
        )
        require(
            route.get("agent_id") == expected_agent
            and usage.get("usage_known") is True
            and all(
                item.get("provider") == route["provider"]
                and item.get("transport") == route["transport"]
                for item in (usage, transport)
            )
            and all(
                type(usage.get(k)) is int
                and type(native[0].get(k)) is int
                and usage[k] >= 0
                and usage[k] == native[0].get(k)
                for k in ("input_tokens", "output_tokens")
            ),
            "Revision route and measured usage differ",
        )
        if expected_agent == "CODEX":
            require(
                native[0].get("boundary") == "DOCKER_REMOTE_EXECUTOR_READ_ONLY"
                and type(native[0].get("denied_operations")) is int
                and native[0]["denied_operations"] == 0
                and bool(native[0].get("commands"))
                and bool(native[0].get("executed_argv"))
                and len(native[0]["commands"]) == len(native[0]["executed_argv"]),
                "Completed Codex read-only revision evidence required",
            )
        else:
            require(
                native[0].get("boundary") == "DOCKER_OFFLINE_TOOLS"
                and type(native[0].get("denials")) is int
                and native[0]["denials"] == 0
                and bool(native[0].get("calls"))
                and all(x.get("tool") == "read_file" for x in native[0]["calls"])
                and (
                    native[0].get("usage_scope") == "COMPLETE"
                    or (expected_agent == "GROK" and "usage_scope" not in native[0])
                ),
                "Completed native revision evidence required",
            )
        if current.work_item_id == work.work_item_id:
            require(
                route.get("agent_id") == REVIEWERS[agent]
                and transport.get("provider") == route["provider"]
                and transport.get("transport") == route["transport"]
                and result.get("review_decision") == review["decision"]
                and result.get("summary") == review["summary"]
                and result.get("findings") == review["findings"],
                "Saved corrections differ from observed independent review",
            )
    return {"review_id": review["id"], "work_item_id": work.work_item_id}
