"""The original author explains remaining corrections within immutable scope."""

import hashlib
import json

from pydantic import Field
from trading_core.work import Record, State

from products.triad.sequential_recovery import require


class CorrectionStep(Record):
    check_id: str = Field(min_length=1)
    files: tuple[str, ...] = Field(min_length=1)
    approach: str = Field(min_length=1)


class CorrectionPlan(Record):
    summary: str = Field(min_length=1)
    steps: tuple[CorrectionStep, ...] = Field(min_length=1)


def validate_steps(plan, proposal, assessment, problems=()):
    required = {c.check_id for c in proposal.acceptance}
    checks = assessment["checks"]
    failed = {
        key
        for key in required
        if len([c for c in checks if c["check_id"] == key]) != 1
        or any(c["check_id"] == key and c["status"] != "VERIFIED" for c in checks)
    }
    failed.update(key for key in required if any(p.startswith(key + ":") for p in problems))
    ids = [step.check_id for step in plan.steps]
    require(
        len(ids) == len(set(ids)) and set(ids) <= required and failed <= set(ids),
        "Correction plan must cover every unverified original check",
    )
    require(
        plan.summary.strip()
        and all(
            step.approach.strip() and set(step.files) <= set(proposal.files) for step in plan.steps
        ),
        "Correction plan cannot expand approved file scope",
    )


def author_request(agent, proposal, retained, baseline):
    """Deterministic evidence packet; planning does not request build file grants."""
    return (
        (
            "You are the CORRECTION_AUTHOR for your retained, unmerged implementation. Write one brief CorrectionPlan "
            "addressing the actual independent QA gaps, using exactly the supplied schema. Do not restate already verified "
            "initial work as the new change. Give a concrete test/code approach and approved file paths for each unverified "
            "check. Preserve the original proposal, file manifest, acceptance criteria and fixture limitations. No new features "
            "or scope expansion; no code execution or claims that proposed tests already passed."
        ),
        {
            "task_assignment": {
                "phase": "CORRECTION_AUTHOR",
                "author": agent,
                "execution_role": "REVIEW",
                "execution_role_meaning": "Read-only author reasoning about remaining corrections",
            },
            "proposal": proposal.model_dump(mode="json"),
            "base_commit": baseline,
            "retained_unmerged_candidate": retained,
            "latest_renewal_feedback": retained.get("renewal_feedback"),
            "allowed_check_ids": [c.check_id for c in proposal.acceptance],
            "approved_file_manifest": list(proposal.files),
            "schema": CorrectionPlan.model_json_schema(),
        },
    )


def author_plan(flow, mission, agent, proposal, retained, baseline):
    from products.triad.sequential_correction_review import BEHAVIORAL_EVIDENCE_GUIDANCE

    objective, context = author_request(agent, proposal, retained, baseline)
    # Keep author_request reproducible for the proved historical pre-start denial.
    # Newly dispatched revisions must resolve feedback, not paraphrase an old plan.
    objective += (
        " latest_renewal_feedback concerns the PREVIOUS unapproved plan. Resolve each "
        "remaining behavioral objection explicitly in the new steps. Preserve approaches "
        "the reviewer already found adequate. Remove rejected alternatives instead of "
        "repeating them as options. If concrete values or an ordered sequence are required, "
        "supply actual values and actions, not statements that they will be concrete later. "
        "Describe the currently proposed behavior separately from historical mistakes."
    ) + BEHAVIORAL_EVIDENCE_GUIDANCE
    # Preserve exact candidate/QA bytes and authority; do not invite copying an
    # unapproved plan embedded inside the retained candidate as current guidance.
    context["retained_unmerged_candidate"] = {
        k: v for k, v in retained.items() if k not in {"author_correction_plan", "renewal_feedback"}
    }
    context["correction_author_version"] = "current-obligations-v2"
    context["historical_context_notice"] = (
        "Retained source and independent QA describe the candidate before correction. "
        "latest_renewal_feedback evaluates the previous unapproved plan; its method "
        "suggestions do not replace the original acceptance behavior. Preserve adequate "
        "approaches and correct the remaining causal gaps using the actual source."
    )
    work, _result, plan, usage = flow.call(mission, agent, objective, context, CorrectionPlan)
    validate_steps(
        plan,
        proposal,
        retained["independent_qa"]["assessment"],
        retained["independent_qa"]["findings"],
    )
    require(flow.s.git.clean_baseline() == baseline, "Baseline moved during correction planning")
    payload = {
        "agent": agent,
        "base_commit": baseline,
        "original_approval": retained["approval_id"],
        "candidate_commit": retained["commit"],
        "qa_id": retained["independent_qa"]["qa_id"],
        "author_work_item_id": work.work_item_id,
        "author_run_id": usage["run_id"],
        "plan": plan.model_dump(mode="json"),
        "plan_sha256": hashlib.sha256(plan.model_dump_json().encode()).hexdigest(),
    }
    identifier = flow.s.record("ProductCorrectionPlan", mission, **payload)
    return flow.s.canonical.get(identifier)


def renew_with_plan(flow, mission, agent, proposal, retained, baseline):
    """Revise a concrete plan on requested changes, never manufacture approval."""
    from products.triad.sequential_planning import planning_context

    seen = set()
    feedback = []
    while True:
        planned = author_plan(flow, mission, agent, proposal, retained, baseline)
        # A reordered plan or changed headline is not substantive progress.
        digest = json.dumps(
            sorted(
                (
                    step["check_id"],
                    sorted(set(step["files"])),
                    " ".join(step["approach"].split()),
                )
                for step in planned["plan"]["steps"]
            ),
            sort_keys=True,
        )
        require(digest not in seen, "Correction plan made no progress; unmerged work retained")
        seen.add(digest)
        retained["author_correction_plan"] = planned
        prior = flow.s.rows("ProductProposalReview", mission)
        attempt = (
            max((r.get("attempt", 0) for r in prior if r.get("proposer") == agent), default=0) + 1
        )
        _, approval, assessment = flow.review_proposal(
            mission,
            agent,
            proposal,
            feedback,
            attempt,
            baseline,
            flow.inventory(),
            planning_context(flow.s, mission, baseline),
            planned["author_work_item_id"],
            planned["author_run_id"],
            correction_plan=planned,
        )
        if approval is not None:
            require(assessment["decision"] == "APPROVE", "Correction plan approval differs")
            return approval, planned
        require(
            assessment["decision"] == "REQUEST_CHANGES",
            "Current-baseline correction proposal did not pass independent review: "
            + assessment["summary"],
        )
        feedback.append(assessment)
        retained["renewal_feedback"] = assessment


def require_approved_plan(flow, conn, mission, agent, proposal, retained, approved):
    from products.triad.sequential_corrections import require_closed_review

    supplied = retained.get("author_correction_plan")
    require(supplied is not None, "Current-baseline correction requires an approved author plan")
    row = flow.s.canonical.get(approved["correction_plan_id"], conn=conn)
    plan = CorrectionPlan.model_validate(row["plan"])
    require(
        row == supplied
        and row["kind"] == "ProductCorrectionPlan"
        and row["owner"] == "triad"
        and row["mission_id"] == mission
        and row["agent"] == agent
        and row["original_approval"] == retained["approval_id"]
        and row["base_commit"] == approved["base_commit"]
        and row["candidate_commit"] == approved["correction_candidate_commit"] == retained["commit"]
        and row["qa_id"] == approved["correction_qa_id"] == retained["independent_qa"]["qa_id"]
        and row["plan_sha256"]
        == approved["correction_plan_sha256"]
        == hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        and approved["author_work_item_id"] == row["author_work_item_id"]
        and approved["author_run_id"] == row["author_run_id"],
        "Approved correction plan binding changed",
    )
    validate_steps(
        plan,
        proposal,
        retained["independent_qa"]["assessment"],
        retained["independent_qa"]["findings"],
    )
    work = flow.s.daily.host.store.get(row["author_work_item_id"], conn=conn)
    prior = flow.s.daily.current(mission, conn)
    require(
        work.status == State.COMPLETED
        and work.owner == "triad"
        and work.mission_id == mission
        and work.parent_work_item_id == prior["parent_work_item_id"]
        and work.assigned_agent == agent
        and work.work_type == "review"
        and work.authority_tier == 0
        and work.execution_permissions == ("read",)
        and work.allowed_tools == ("read_file",),
        "Closed read-only correction author required",
    )
    records = {}
    for kind in ("AgentRunRequest", "AgentRunResult", "Usage"):
        rows = conn.execute(
            "SELECT payload,work_item_id FROM core.day3_records WHERE owner='triad' AND kind=%s AND payload->>'run_id'=%s",
            (kind, row["author_run_id"]),
        ).fetchall()
        require(
            len(rows) == 1 and rows[0]["work_item_id"] == work.work_item_id,
            "Unambiguous correction author evidence required",
        )
        records[kind] = rows[0]["payload"]
    request, raw, usage = (records[k] for k in ("AgentRunRequest", "AgentRunResult", "Usage"))
    context = request.get("context_packet", {})
    authored_candidate = context.get("retained_unmerged_candidate") or {}
    require(
        request.get("role") == "REVIEW"
        and request.get("agent_id") == agent
        and request.get("mission_id") == mission
        and request.get("control_epoch") == prior["control_epoch"]
        and request.get("execution_permissions") == ["read"]
        and usage.get("status") == "SUCCESS"
        and usage.get("agent") == agent
        and raw.get("analysis_artifacts") == [row["plan"]],
        "Actual correction author differs",
    )
    require(
        context.get("task_assignment", {}).get("phase") == "CORRECTION_AUTHOR"
        and all(
            authored_candidate.get(k) == retained[k]
            for k in (
                "commit",
                "implementation_id",
                "approval_id",
                "snapshot_sha256",
                "reservation_id",
                "reservation_work_item_id",
                "independent_qa",
            )
        ),
        "Correction author reasoned about a different candidate or QA",
    )
    require_closed_review(
        flow.s,
        conn,
        work,
        request,
        raw,
        usage,
        {"run_id": row["author_run_id"], "commit": row["base_commit"]},
        proposal,
        context_key="base_commit",
    )
    require(approved["reviewer"] != agent, "Correction author cannot approve own plan")
    reviewing = flow.s.daily.host.store.get(approved["review_work_item_id"], conn=conn)
    require(
        reviewing.status == State.COMPLETED
        and reviewing.owner == "triad"
        and reviewing.mission_id == mission
        and reviewing.parent_work_item_id == prior["parent_work_item_id"]
        and reviewing.assigned_agent == approved["reviewer"]
        and reviewing.work_type == "review"
        and reviewing.authority_tier == 0
        and reviewing.execution_permissions == ("read",)
        and reviewing.allowed_tools == ("read_file",),
        "Closed independent correction reviewer required",
    )
    records = {}
    for kind in ("AgentRunRequest", "AgentRunResult", "Usage"):
        rows = conn.execute(
            "SELECT payload,work_item_id FROM core.day3_records WHERE owner='triad' AND kind=%s AND payload->>'run_id'=%s",
            (kind, approved["run_id"]),
        ).fetchall()
        require(
            len(rows) == 1 and rows[0]["work_item_id"] == reviewing.work_item_id,
            "Unique correction approval run required",
        )
        records[kind] = rows[0]["payload"]
    request, raw, usage = (records[k] for k in ("AgentRunRequest", "AgentRunResult", "Usage"))
    context = request.get("context_packet", {})
    require(
        request.get("role") == "REVIEW"
        and request.get("agent_id") == approved["reviewer"]
        and request.get("mission_id") == mission
        and request.get("control_epoch") == prior["control_epoch"]
        and request.get("execution_permissions") == ["read"]
        and usage.get("status") == "SUCCESS"
        and usage.get("agent") == approved["reviewer"]
        and raw.get("review_decision") == "APPROVE"
        and context.get("correction_plan") == row
        and context.get("task_assignment", {}).get("phase") == "PROPOSAL_REVIEWER"
        and all(
            (context.get("retained_unmerged_candidate") or {}).get(k) == retained[k]
            for k in (
                "commit",
                "implementation_id",
                "approval_id",
                "snapshot_sha256",
                "independent_qa",
            )
        ),
        "Actual reviewer did not approve this exact correction plan",
    )
    require_closed_review(
        flow.s,
        conn,
        reviewing,
        request,
        raw,
        usage,
        {"run_id": approved["run_id"], "commit": row["base_commit"]},
        proposal,
        context_key="base_commit",
    )
