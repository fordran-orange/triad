"""Prove a stopped, read-only correction approval renewal; never replay a build."""

from trading_core.work import State

from products.triad.sequential_recovery import require

PREFIX = "Current-baseline correction proposal did not pass independent review: "
PLANNING_DENIED = "No authorized verified provider/role fits this task"
REVIEW_BASELINE_MOVED = "Source changed during proposal review"


def renewal_checkpoint(
    flow, mission, prior, build, proposal, qa, conn, *, planning_denial=False, baseline_moved=False
):
    from products.triad.sequential import REVIEWERS
    from products.triad.sequential_corrections import require_closed_review

    agent = build["builder"]
    reviews = flow.s.canonical.list(
        "ProductProposalReview", matching={"mission_id": mission, "proposer": agent}, conn=conn
    )
    require(bool(reviews), "Latest correction renewal review required")
    review = reviews[-1]
    require(
        review["owner"] == "triad"
        and review["reviewer"] == REVIEWERS[agent]
        and review["decision"]
        in ({"REQUEST_CHANGES", "APPROVE"} if baseline_moved else {"REQUEST_CHANGES"})
        and review["proposal"] == proposal.model_dump(mode="json")
        and prior["failures"][-1]["message"]
        == (
            REVIEW_BASELINE_MOVED
            if baseline_moved
            else PLANNING_DENIED
            if planning_denial
            else (PREFIX + review["summary"])[:500]
        ),
        "Exact stopped renewal REQUEST_CHANGES required",
    )
    records = {}
    for kind in ("AgentRunRequest", "AgentRunResult", "Usage"):
        rows = conn.execute(
            "SELECT payload,work_item_id FROM core.day3_records WHERE owner='triad' AND kind=%s AND payload->>'run_id'=%s",
            (kind, review["run_id"]),
        ).fetchall()
        require(len(rows) == 1, "Unique closed renewal evidence required")
        records[kind] = rows[0]
    request, raw, usage = (
        records[k]["payload"] for k in ("AgentRunRequest", "AgentRunResult", "Usage")
    )
    work_id = records["AgentRunRequest"]["work_item_id"]
    require(
        all(r["work_item_id"] == work_id for r in records.values()), "Crossed renewal work identity"
    )
    work = flow.s.daily.host.store.get(work_id, conn=conn)
    require(
        work.owner == "triad"
        and work.mission_id == mission
        and work.parent_work_item_id == prior["parent_work_item_id"]
        and work.assigned_agent == REVIEWERS[agent]
        and work.status == State.COMPLETED
        and work.work_type == "review"
        and work.authority_tier == 0
        and work.execution_permissions == ("read",)
        and work.allowed_tools == ("read_file",),
        "Completed read-only renewal reviewer required",
    )
    context = request.get("context_packet", {})
    retained = context.get("retained_unmerged_candidate", {})
    require(
        request.get("mission_id") == mission
        and request.get("agent_id") == REVIEWERS[agent]
        and request.get("role") == "REVIEW"
        and request.get("control_epoch") == prior["control_epoch"]
        and request.get("execution_permissions") == ["read"]
        and usage.get("status") == "SUCCESS"
        and usage.get("agent") == REVIEWERS[agent]
        and raw.get("review_decision") == review["decision"]
        and raw.get("summary") == review["summary"]
        and raw.get("findings") == review["findings"]
        and context.get("task_assignment", {}).get("phase") == "PROPOSAL_REVIEWER"
        and retained.get("commit") == build["git"]["change_commit"]
        and retained.get("implementation_id") == build["implementation_id"]
        and retained.get("independent_qa", {}).get("qa_id") == qa["id"],
        "Actual renewal checkpoint differs",
    )
    base = context.get("base_commit")
    require(isinstance(base, str), "Renewal baseline required")
    if baseline_moved:
        require(base != flow.s.git.clean_baseline(), "A moved reviewer baseline is required")
        require(
            not conn.execute(
                "SELECT 1 FROM core.work_items WHERE owner='triad' AND mission_id=%s "
                "AND created_at>(SELECT created_at FROM core.work_items WHERE id=%s)",
                (mission, work_id),
            ).fetchone(),
            "Later work prevents completed-review baseline recovery",
        )
    flow.s.git.git("merge-base", "--is-ancestor", base, flow.s.git.clean_baseline())
    require_closed_review(
        flow.s,
        conn,
        work,
        request,
        raw,
        usage,
        {"run_id": review["run_id"], "commit": base},
        proposal,
        context_key="base_commit",
    )
    require(
        not any(
            a.get("run_id") == review["run_id"]
            for a in flow.s.canonical.list(
                "ProductTurnApproval", matching={"cycle_id": mission}, conn=conn
            )
        ),
        "Unapproved renewal required",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.day3_records WHERE id=%s", ("correction-build-" + qa["id"],)
        ).fetchone(),
        "A correction was already dispatched",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.day3_records r WHERE r.owner='triad' AND r.kind='AgentRunRequest' AND r.payload->>'mission_id'=%s AND r.payload->>'role'='IMPLEMENT' AND r.created_at>(SELECT created_at FROM core.intelligence_records WHERE id=%s)",
            (mission, qa["id"]),
        ).fetchone(),
        "New implementation prevents stopped renewal recovery",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.work_items w WHERE w.owner='triad' AND w.mission_id=%s "
            "AND (w.payload->>'work_type'='development' OR w.payload->'execution_permissions' ?| ARRAY['write_code','write_research']) "
            "AND w.created_at>(SELECT created_at FROM core.intelligence_records WHERE id=%s)",
            (mission, qa["id"]),
        ).fetchone(),
        "Later write assignment prevents stopped renewal recovery",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.intelligence_records r WHERE r.owner='triad' AND r.kind IN ('ProductBuild','ProductBuildCheckpoint') "
            "AND r.payload->>'mission_id'=%s AND r.created_at>(SELECT created_at FROM core.intelligence_records WHERE id=%s)",
            (mission, qa["id"]),
        ).fetchone(),
        "Later build evidence prevents stopped renewal recovery",
    )
    return review
