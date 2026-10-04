"""Correct independently rejected candidates without replaying completed turns."""

from contextlib import nullcontext
from math import isfinite

from trading_core.contracts import AgentRunResult
from trading_core.product_changes import AcceptanceAssessment, acceptance_problems
from trading_core.work import State

from products.triad.sequential_candidate_recovery import retain_application_candidate
from products.triad.sequential_recovery import require


def require_closed_review(service, conn, reviewer, request, raw, usage, review, proposal):
    """Bind canonical routing and actual completed native observation."""
    run, expected = review["run_id"], reviewer.work_item_id
    require(
        all(
            r.get("work_item_id", expected) == expected and r.get("run_id") == run
            for r in (request, raw, usage)
        )
        and request.get("allowed_tools") == ["read_file"]
        and set(request.get("allowed_paths", [])) == set(reviewer.allowed_paths)
        and request.get("context_packet", {}).get("proposal") == proposal.model_dump(mode="json")
        and request.get("context_packet", {}).get("exact_commit") == review["commit"]
        and raw.get("mode") == usage.get("mode") == "REAL"
        and raw.get("status") != "BLOCKED"
        and not raw.get("files_changed")
        and not raw.get("proposal")
        and usage.get("usage_known") is True
        and type(usage.get("duration")) in {int, float}
        and isfinite(usage["duration"])
        and usage["duration"] >= 0,
        "Closed real read-only review and known usage required",
    )
    rows = conn.execute(
        "SELECT kind,work_item_id,payload FROM core.day3_records WHERE owner='triad' AND payload->>'run_id'=%s AND kind IN ('TransportRun','Event')",
        (run,),
    ).fetchall()
    require(
        all(
            r["work_item_id"] == expected and r["payload"].get("work_item_id", expected) == expected
            for r in rows
        ),
        "Crossed native review evidence",
    )
    transports = [r["payload"] for r in rows if r["kind"] == "TransportRun"]
    native = [
        r["payload"]
        for r in rows
        if r["kind"] == "Event" and r["payload"].get("event") == "native_executor_evidence"
    ]
    require(
        len(transports) == len(native) == 1
        and not any(r["payload"].get("event") == "provider_failed" for r in rows),
        "Unique completed native reviewer evidence required",
    )
    transport, evidence = transports[0], native[0]
    routed = service.canonical.get("route-" + expected, conn=conn)
    require(
        routed["kind"] == "CapabilityRoutingDecision" and routed["owner"] == "triad",
        "Canonical reviewer route required",
    )
    route = routed["selected"]
    require(
        route.get("agent_id") == reviewer.assigned_agent
        and transport.get("agent") == reviewer.assigned_agent
        and transport.get("status") == "SUCCESS"
        and transport.get("completed_at")
        and all(
            r.get("provider") == route["provider"] and r.get("transport") == route["transport"]
            for r in (usage, transport)
        )
        and all(
            type(usage.get(k)) is int
            and type(evidence.get(k)) is int
            and usage[k] >= 0
            and usage[k] == evidence[k]
            for k in ("input_tokens", "output_tokens")
        ),
        "Actual reviewer route or measured usage differs",
    )
    if reviewer.assigned_agent == "CODEX":
        require(
            evidence.get("boundary") == "DOCKER_REMOTE_EXECUTOR_READ_ONLY"
            and type(evidence.get("denied_operations")) is int
            and evidence["denied_operations"] == 0
            and evidence.get("commands")
            and evidence.get("executed_argv")
            and len(evidence["commands"]) == len(evidence["executed_argv"]),
            "Completed Codex read-only review required",
        )
    else:
        require(
            evidence.get("boundary") == "DOCKER_OFFLINE_TOOLS"
            and type(evidence.get("denials")) is int
            and evidence["denials"] == 0
            and evidence.get("calls")
            and all(c.get("tool") == "read_file" for c in evidence["calls"])
            and (
                evidence.get("usage_scope") == "COMPLETE"
                or (reviewer.assigned_agent == "GROK" and "usage_scope" not in evidence)
            ),
            "Completed native read-only review required",
        )


def prepare_correction(flow, mission, agent, proposal, git, build, qa_id, *, existing_conn=None):
    """Bind advisory code/findings and the one turn reservation to closed real QA."""
    from products.triad.sequential import REVIEWERS

    service = flow.s
    host = service.daily.host
    require(host.store.scope is None, "Core host correction required")
    with (
        nullcontext()
        if existing_conn is not None
        else host.store.lease("triad-product-development"),
        nullcontext() if existing_conn is not None else service.ledger.gate(),
        nullcontext(existing_conn) if existing_conn is not None else host.store.connect() as conn,
    ):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (mission,))
        prior = service.daily.current(mission, conn)
        flow.guard(mission)
        require(
            prior["status"]
            in ({"BLOCKED"} if existing_conn is not None else {"AWAITING_QA", "CORRECTING"}),
            "Not a correction checkpoint",
        )
        turns = service.daily.require_turn_prefix(mission, prior, conn)
        require(
            len(turns) < 3 and agent == ("CODEX", "CLAUDE", "GROK")[len(turns)],
            "Next provider mismatch",
        )
        recorded = service.canonical.get(build["id"], conn=conn) if build.get("id") else None
        builds = service.canonical.list("ProductBuild", matching={"mission_id": mission}, conn=conn)
        candidates = [b for b in builds if b["builder"] == agent]
        require(
            bool(candidates) and candidates[-1]["implementation_id"] == build["implementation_id"],
            "Latest candidate required",
        )
        recorded = recorded or candidates[-1]
        require(
            recorded["owner"] == "triad"
            and recorded["kind"] == "ProductBuild"
            and all(recorded[k] == build[k] for k in ("git", "checks", "approval", "work_item_id")),
            "Build identity changed",
        )
        approved = flow.approval(mission, agent, proposal, build["approval"])
        require(
            approved["base_commit"] == build["git"]["base_commit"], "Approval baseline mismatch"
        )
        require(
            git.git("rev-parse", "HEAD", cwd=build["git"]["worktree"])
            == build["git"]["change_commit"]
            and not git.git("status", "--porcelain", cwd=build["git"]["worktree"]),
            "Rejected candidate moved or is dirty",
        )
        actual = git.verify(build["git"])
        require(
            all(actual[k] == build["checks"][k] for k in ("files", "hashes", "diff")),
            "Candidate differs from QA",
        )
        reviews = service.canonical.list(
            "QARun", matching={"implementation_run_id": build["implementation_id"]}, conn=conn
        )
        require(bool(reviews), "Canonical QA required")
        qa = reviews[-1]
        require(
            qa["owner"] == "triad"
            and qa["kind"] == "QARun"
            and qa["id"] == qa_id
            and qa["decision"] == "CHANGES_REQUIRED"
            and qa["qa_agent"] == REVIEWERS[agent]
            and qa["execution_mode"] == "REAL_PROVIDER"
            and qa["reviewed_commit"] == build["git"]["change_commit"],
            "Latest independent requested correction required",
        )
        refs = [
            e.removeprefix("acceptance-review:")
            for e in qa["evidence"]
            if e.startswith("acceptance-review:")
        ]
        require(len(refs) == 1, "One exact acceptance review required")
        review = service.canonical.get(refs[0], conn=conn)
        require(
            review["kind"] == "ProductAcceptanceReview"
            and review["owner"] == "triad"
            and review["cycle_id"] == mission
            and review["implementation_id"] == build["implementation_id"]
            and review["qa_id"] == qa_id
            and review["reviewer"] == REVIEWERS[agent]
            and review["commit"] == build["git"]["change_commit"]
            and review["approval_id"] == build["approval"]
            and review["required"] == approved["proposal"]["acceptance"],
            "Acceptance review binding changed",
        )
        work = host.store.get(build["work_item_id"], conn=conn)
        reviewer = host.store.get(qa["qa_work_item_id"], conn=conn)
        require(
            work.status == State.CHANGES_REQUESTED
            and work.owner == "triad"
            and work.mission_id == mission
            and work.assigned_agent == agent
            and work.parent_work_item_id == prior["parent_work_item_id"]
            and reviewer.status == State.COMPLETED
            and reviewer.owner == "triad"
            and reviewer.mission_id == mission
            and reviewer.assigned_agent == REVIEWERS[agent]
            and reviewer.parent_work_item_id == prior["parent_work_item_id"]
            and reviewer.authority_tier == 0
            and set(reviewer.execution_permissions) == {"read"}
            and set(reviewer.allowed_tools) <= {"read_file"},
            "Closed independent work required",
        )
        require(
            not any(
                w.mission_id == mission
                and w.work_item_id != prior["parent_work_item_id"]
                and w.status in {State.IN_PROGRESS, State.AWAITING_REVIEW}
                for w in host.store.list_work(10000)
            ),
            "Active child work prevents correction",
        )
        records = {}
        for kind in ("AgentRunRequest", "AgentRunResult", "Usage"):
            rows = conn.execute(
                "SELECT payload,work_item_id FROM core.day3_records WHERE owner='triad' AND kind=%s AND payload->>'run_id'=%s",
                (kind, review["run_id"]),
            ).fetchall()
            require(
                len(rows) == 1 and rows[0]["work_item_id"] == reviewer.work_item_id,
                "Exact reviewer run required",
            )
            records[kind] = rows[0]["payload"]
        request, raw, usage = (records[k] for k in ("AgentRunRequest", "AgentRunResult", "Usage"))
        require_closed_review(service, conn, reviewer, request, raw, usage, review, proposal)
        require(
            request["mission_id"] == mission
            and request["agent_id"] == REVIEWERS[agent]
            and request["role"] == "REVIEW"
            and request["control_epoch"] == prior["control_epoch"]
            and request["execution_permissions"] == ["read"]
            and usage["status"] == "SUCCESS"
            and usage["agent"] == REVIEWERS[agent]
            and usage["run_id"] == request["run_id"] == raw["run_id"],
            "Actual reviewer authority or completion differs",
        )
        result = AgentRunResult.model_validate(
            {k: v for k, v in raw.items() if k in AgentRunResult.model_fields}
        )
        assessment = AcceptanceAssessment.model_validate(review["assessment"])
        require(
            result.review_decision in {"REQUEST_CHANGES", "APPROVE"}
            and len(result.analysis_artifacts) == 1
            and (
                AcceptanceAssessment.model_validate_json(result.analysis_artifacts[0])
                if isinstance(result.analysis_artifacts[0], str)
                else AcceptanceAssessment.model_validate(result.analysis_artifacts[0])
            )
            == assessment,
            "Not an independent request for correction",
        )
        ids = review["test_record_ids"]
        require(
            len(ids) == 2 and len(set(ids)) == 2 and ids[0] == build["checks"]["test_record_id"],
            "Exact repeated tests required",
        )
        proofs = {i: service.canonical.get(i, conn=conn) for i in ids}
        require(
            all(
                p["kind"] == "EngineeringTestRun"
                and p["owner"] == "triad"
                and p.get("commit") == review["commit"]
                and p.get("work_item_id") == work.work_item_id
                and p.get("status") == "PASS"
                for p in proofs.values()
            ),
            "Original candidate test evidence differs",
        )
        missing = acceptance_problems(review["required"], assessment, review["commit"], proofs)
        require(
            list(missing) == review["problems"] == qa["required_changes"]
            and list(result.findings) + list(missing) == qa["findings"],
            "Full QA findings differ",
        )
        merges = service.canonical.list("ProductMerge", matching={"mission_id": mission}, conn=conn)
        require(
            not any(m["implementation_id"] == build["implementation_id"] for m in merges),
            "Applied work cannot be rebuilt",
        )
        # Follow canonical predecessor links, keeping one change reservation
        # for one provider turn. Actual native inference is never refunded.
        chain = recorded
        seen = set()
        while chain.get("correction_of"):
            require(chain["implementation_id"] not in seen, "Correction lineage loop")
            seen.add(chain["implementation_id"])
            parents = [b for b in candidates if b["implementation_id"] == chain["correction_of"]]
            require(len(parents) == 1, "Correction predecessor missing")
            parent = parents[0]
            require(
                parent["approval"] == chain["approval"]
                or chain.get("renewed_approval_from") == parent["approval"],
                "Correction changed proposal authority",
            )
            require(
                not any(m["implementation_id"] == parent["implementation_id"] for m in merges),
                "Applied predecessor cannot be rebuilt",
            )
            chain = parent
        slot = chain["work_item_id"]
        reservations = conn.execute(
            "SELECT id,payload FROM core.day3_records WHERE owner='triad' AND kind='BudgetReservation' AND work_item_id=%s AND payload->>'improvement'='true'",
            (slot,),
        ).fetchall()
        require(len(reservations) == 1, "One original improvement reservation required")
        reservation = reservations[0]
        require(
            reservation["payload"]["day"] == flow.improvement_day
            and reservation["payload"]["agent"] == agent
            and all(reservation["payload"][k] == 0 for k in ("cost", "tokens", "seconds")),
            "Original turn reservation differs",
        )
        feedback = {
            "qa_id": qa_id,
            "acceptance_review_id": review["id"],
            "findings": qa["findings"],
            "assessment": review["assessment"],
            "required": review["required"],
        }
        retained = retain_application_candidate(
            flow,
            mission,
            agent,
            prior,
            work,
            {"git": build["git"], "phase": "ISOLATED"},
            conn,
            qa_feedback=feedback,
        )
        retained.update(
            implementation_id=build["implementation_id"],
            approval_id=build["approval"],
            reservation_id=reservation["id"],
            reservation_work_item_id=slot,
        )
        action = "candidate-correction-" + qa_id
        require(
            not conn.execute("SELECT 1 FROM core.day3_records WHERE id=%s", (action,)).fetchone(),
            "Correction already dispatched",
        )
        host.ledger.put(
            "ControlAction",
            {
                "action": "correct_independently_rejected_candidate",
                "cycle_id": mission,
                "implementation_id": build["implementation_id"],
                "qa_id": qa_id,
                "candidate_commit": review["commit"],
                "snapshot_sha256": retained["snapshot_sha256"],
                "reservation_id": reservation["id"],
                "released_change_slots": 0,
                "retained_turn_ids": [t["id"] for t in turns],
                "day": flow.improvement_day,
            },
            identifier=action,
            conn=conn,
        )
        return retained


def claim_correction_build(flow, mission, agent, proposal, approval, retained):
    """One dispatch per closed QA; interrupted native execution is never replayed."""
    qa_id = retained["independent_qa"]["qa_id"]
    host = flow.s.daily.host
    require(host.store.scope is None, "Core host correction required")
    with flow.s.ledger.gate(), host.store.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (mission,))
        flow.guard(mission)
        current = flow.s.daily.current(mission, conn)
        require(current["status"] == "CORRECTING", "Correction lifecycle required")
        rows = flow.s.canonical.list(
            "QARun", matching={"implementation_run_id": retained["implementation_id"]}, conn=conn
        )
        require(
            rows and rows[-1]["id"] == qa_id and rows[-1]["decision"] == "CHANGES_REQUIRED",
            "QA changed before correction dispatch",
        )
        old = flow.s.canonical.get(retained["approval_id"], conn=conn)
        approved = flow.approval(mission, agent, proposal, approval)
        require(
            old["proposal"] == approved["proposal"],
            "Correction must preserve exact approved proposal",
        )
        action = "correction-build-" + qa_id
        require(
            conn.execute(
                "SELECT 1 FROM core.day3_records WHERE id=%s", ("candidate-correction-" + qa_id,)
            ).fetchone(),
            "Verified correction checkpoint required",
        )
        require(
            not conn.execute("SELECT 1 FROM core.day3_records WHERE id=%s", (action,)).fetchone(),
            "Correction build already attempted",
        )
        host.ledger.put(
            "ControlAction",
            {
                "action": "dispatch_exact_candidate_correction",
                "cycle_id": mission,
                "agent": agent,
                "qa_id": qa_id,
                "implementation_id": retained["implementation_id"],
                "original_approval": retained["approval_id"],
                "approval": approval,
                "reservation_id": retained["reservation_id"],
                "released_change_slots": 0,
            },
            identifier=action,
            conn=conn,
        )


def correct_until_pass(flow, mission, agent, proposal, git, build, qa):
    """No approval by exhaustion. Stop identical candidate content, not token use."""
    if qa.decision in {"PASS", "PASS_WITH_OBSERVATIONS"}:
        return git, build, qa
    require(qa.decision == "CHANGES_REQUIRED", "Independent QA rejected or blocked the candidate")
    seen = {tuple(sorted(build["checks"]["hashes"].items()))}
    while qa.decision == "CHANGES_REQUIRED":
        retained = getattr(flow, "_prepared_correction", None)
        flow._prepared_correction = None
        if retained is not None:
            require(
                retained["implementation_id"] == build["implementation_id"]
                and retained["independent_qa"]["qa_id"] == qa.qa_run_id,
                "Prepared correction checkpoint differs",
            )
        else:
            retained = prepare_correction(flow, mission, agent, proposal, git, build, qa.qa_run_id)
        flow.s.transition(mission, "CORRECTING", [qa.qa_run_id])
        flow.retained_application_candidate = retained
        approval = build["approval"]
        baseline = flow.s.git.clean_baseline()
        if baseline != build["git"]["base_commit"]:
            from products.triad.sequential_planning import planning_context

            original = flow.s.canonical.get(approval)
            prior_reviews = flow.s.rows("ProductProposalReview", mission)
            attempt = (
                max(
                    (r.get("attempt", 0) for r in prior_reviews if r.get("proposer") == agent),
                    default=0,
                )
                + 1
            )
            _, renewed, assessment = flow.review_proposal(
                mission,
                agent,
                proposal,
                [],
                attempt,
                baseline,
                flow.inventory(),
                planning_context(flow.s, mission, baseline),
                original["author_work_item_id"],
                original["author_run_id"],
            )
            require(
                renewed is not None,
                "Current-baseline correction proposal did not pass independent review: "
                + assessment["summary"],
            )
            flow.s.record(
                "ProductProposalApprovalRenewal",
                mission,
                original_approval=approval,
                approval=renewed,
                proposal=proposal.model_dump(mode="json"),
                base_commit=baseline,
            )
            approval = renewed
        git, build = flow.build(mission, agent, proposal, approval)
        digest = tuple(sorted(build["checks"]["hashes"].items()))
        require(digest not in seen, "Candidate correction made no progress; unmerged work retained")
        seen.add(digest)
        flow.s.transition(mission, "AWAITING_QA", [build["implementation_id"]])
        qa = flow.qa(mission, agent, proposal, git, build)
    require(
        qa.decision in {"PASS", "PASS_WITH_OBSERVATIONS"},
        "Independent QA rejected or blocked the candidate",
    )
    return git, build, qa
