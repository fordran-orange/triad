"""Validate retained independent decisions to leave an exact product baseline unchanged."""

import hashlib


def require_no_change(records, turn, cycle, conn=None):
    if conn is None:
        with records.store.connect() as connection:
            return require_no_change(records, turn, cycle, connection)
    from products.triad.sequential import REVIEWERS, Proposal

    proof = records.get(turn["no_change_id"], conn=conn)
    approval = records.get(proof["approval_id"], conn=conn)
    proposal = Proposal.model_validate(approval["proposal"])
    programs = [
        r
        for r in records.list("SequentialDailyProgram", conn=conn)
        if r["owner"] == "triad" and r["cycle_id"] == cycle["cycle_id"]
    ]
    if (
        turn.get("outcome") != "NO_CHANGE"
        or turn.get("owner") != "triad"
        or turn.get("mission_id") != cycle["cycle_id"]
        or turn.get("status") != "COMPLETED"
        or proof["kind"] != "ProductNoChange"
        or proof["owner"] != "triad"
        or approval["kind"] != "ProductTurnApproval"
        or approval["owner"] != "triad"
        or proposal.outcome != "NO_CHANGE"
        or approval["proposal_sha256"]
        != hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
        or not programs
        or approval["policy_id"] != programs[-1]["policy_id"]
        or not all(row["cycle_id"] == cycle["cycle_id"] for row in (proof, approval))
        or proof["agent"] != turn["agent"]
        or approval["builder"] != turn["agent"]
        or turn["reviewer"] != REVIEWERS[turn["agent"]]
        or any(row["reviewer"] != turn["reviewer"] for row in (proof, approval))
        or proof["baseline"] != approval["base_commit"]
        or proof["baseline"] != turn["verified_revision"]
        or proof["health"].get("loaded_revision") != proof["baseline"]
        or proof["health"].get("development_provider_gate") != "PASS"
        or not proof["health"].get("routes")
        or any(status != 200 for status in proof["health"]["routes"].values())
    ):
        raise PermissionError("No-change decision lacks exact independently reviewed evidence")
    for agent, work_id, run_id in (
        (turn["agent"], approval["author_work_item_id"], approval["author_run_id"]),
        (turn["reviewer"], approval["review_work_item_id"], approval["run_id"]),
    ):
        work = records.store.get(work_id, conn=conn)
        if (
            work.owner != "triad"
            or work.mission_id != cycle["cycle_id"]
            or work.parent_work_item_id != cycle["parent_work_item_id"]
            or work.assigned_agent != agent
            or work.status != "COMPLETED"
            or work.work_type != "review"
        ):
            raise PermissionError("No-change author/reviewer assignment mismatch")
        rows = conn.execute(
            "SELECT kind,payload FROM core.day3_records WHERE owner='triad' AND work_item_id=%s "
            "AND kind IN ('Usage','AgentRunResult') AND payload->>'run_id'=%s",
            (work_id, run_id),
        ).fetchall()
        usage = [r["payload"] for r in rows if r["kind"] == "Usage"]
        results = [r["payload"] for r in rows if r["kind"] == "AgentRunResult"]
        if (
            len(usage) != 1
            or len(results) != 1
            or usage[0]["status"] != "SUCCESS"
            or usage[0]["mode"] != "REAL"
            or usage[0]["agent"] != agent
            or results[0].get("mode") != "REAL"
            or results[0].get("files_changed")
            or results[0].get("proposal")
        ):
            raise PermissionError("No-change requires successful real provider evidence")
        result = results[0]
        if agent == turn["agent"]:
            if (
                len(result["analysis_artifacts"]) != 1
                or Proposal.model_validate_json(result["analysis_artifacts"][0]) != proposal
            ):
                raise PermissionError("No-change proposal differs from observed provider output")
        elif result.get("review_decision") != "APPROVE":
            raise PermissionError("No-change decision was not independently approved")
    return proof
