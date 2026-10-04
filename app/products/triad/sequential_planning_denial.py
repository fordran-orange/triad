"""Recover only a proved pre-dispatch correction-plan path-grant denial."""

import hashlib
import json

from products.triad.sequential_correction_plan import CorrectionPlan, author_request
from products.triad.sequential_planning import token_guidance
from products.triad.sequential_recovery import require


def require_unstarted_planning(flow, mission, prior, proposal, retained, review, conn):
    action = "qa-resume-" + retained["independent_qa"]["qa_id"] + "-" + review["id"]
    checkpoint = conn.execute(
        "SELECT owner,kind,payload,created_at FROM core.day3_records WHERE id=%s", (action,)
    ).fetchone()
    require(
        checkpoint and checkpoint["owner"] == "core" and checkpoint["kind"] == "ControlAction",
        "Previous reviewed correction resume required",
    )
    payload = checkpoint["payload"]
    require(
        all(
            payload.get(k) == v
            for k, v in {
                "action": "resume_independently_requested_candidate_correction",
                "cycle_id": mission,
                "implementation_id": retained["implementation_id"],
                "prior_qa_id": retained["independent_qa"]["qa_id"],
                "candidate_commit": retained["commit"],
                "released_change_slots": 0,
            }.items()
        ),
        "Previous resume checkpoint differs",
    )
    baseline = payload["revision"]
    flow.s.git.git("merge-base", "--is-ancestor", baseline, flow.s.git.clean_baseline())
    rows = conn.execute(
        "SELECT id,payload FROM core.intelligence_records WHERE owner='triad' AND kind='CapabilityRoutingDecision' AND payload->>'decision'='DENY' AND created_at>%s ORDER BY created_at,id",
        (checkpoint["created_at"],),
    ).fetchall()
    require(len(rows) == 1, "One exact denied assignment required")
    denied = rows[0]
    request = denied["payload"]
    agent = retained["agent"]
    objective, context = author_request(agent, proposal, retained, baseline)
    history = flow.s.canonical.list(
        "ProductAutoRecovery", matching={"mission_id": mission}, conn=conn
    )
    expected_key = hashlib.sha256(
        json.dumps(
            [agent, objective, context, list(proposal.files)], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    require(
        history
        and history[-1]["agent"] == agent
        and history[-1]["status"] == "NEEDS_ATTENTION"
        and history[-1]["failure_class"] == "PermissionError"
        and history[-1].get("previous_run_id") is None
        and history[-1]["stage_key"] == expected_key,
        "Denied planning stage identity differs",
    )
    expanded = (
        objective
        + token_guidance(agent)
        + (
            "Do not execute commands or claim host tests. Top-level files_changed must be [] and proposal must be null; "
            "the requested Proposal or Patch is data inside analysis_artifacts, not the outer proposal field."
        )
    )
    _, expected = flow.s.call(
        mission,
        agent,
        "REVIEW",
        expanded,
        {
            **context,
            "evidence_delivery": "files-v1",
            "response_format_feedback": [],
            "response_envelope": {
                "files_changed": [],
                "proposal": None,
                "analysis_artifacts": "Exactly one JSON object for the requested schema; never encode it as a string",
            },
        },
        paths=proposal.files,
        schema=CorrectionPlan,
        parent=prior["parent_work_item_id"],
        _preview=True,
    )
    selected = [c for c in request["candidates"] if c["agent_id"] == agent]
    require(
        request["requirements"] == expected.model_dump(mode="json")
        and len(selected) == 1
        and selected[0]["exclusions"] == ["Assignment exceeds configured path grant"]
        and selected[0]["eligible"] is False,
        "Not solely the known pre-dispatch path grant denial",
    )
    work_id = request["work_item_id"]
    require(
        not conn.execute(
            "SELECT 1 FROM core.work_items WHERE id=%s OR (owner='triad' AND mission_id=%s AND created_at>%s)",
            (work_id, mission, checkpoint["created_at"]),
        ).fetchone(),
        "Work already began after resume",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.day3_records WHERE work_item_id=%s AND kind IN ('AgentRunRequest','AgentRunResult','TransportRun','Usage','Event')",
            (work_id,),
        ).fetchone(),
        "Denied assignment has execution evidence",
    )
    require(
        not conn.execute(
            "SELECT 1 FROM core.intelligence_records WHERE owner='triad' AND kind='ProductCorrectionPlan' AND payload->>'mission_id'=%s AND created_at>%s",
            (mission, checkpoint["created_at"]),
        ).fetchone(),
        "Completed planning must not be replayed",
    )
    return denied["id"]
