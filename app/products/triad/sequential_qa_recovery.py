"""Explicit host recovery of an unchanged candidate blocked only by omitted citations."""

from zoneinfo import ZoneInfo

from trading_core.contracts import AgentRunResult
from trading_core.cycle_records import CycleRecord
from trading_core.product_changes import AcceptanceAssessment, ProductGit, acceptance_problems
from trading_core.product_deployment import health
from trading_core.work import State, now

from products.triad.sequential import ORDER, REVIEWERS, Proposal
from products.triad.sequential_citations import citation_omission
from products.triad.sequential_recovery import require


def resume_citation_failure(flow, mission):
    """Caller holds daily execution lease. No build, reservation refund or test replay."""
    service, daily = flow.s, flow.s.daily
    host = daily.host
    require(host.store.scope is None, "Core host recovery required")
    with host.store.lease("triad-product-development"):
        head = service.git.clean_baseline()
        healthy = health(head)
        require(
            healthy.get("loaded_revision") == head
            and healthy.get("development_provider_gate") == "PASS",
            "Healthy exact baseline required",
        )
        with host.ledger.gate(), host.store.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (mission,))
            prior = daily.current(mission, conn)
            require(
                prior["status"] == "BLOCKED"
                and prior.get("failure_code") == "PermissionError"
                and prior.get("failures", [{}])[-1].get("message")
                == "Latest independent QA did not pass this revision",
                "Not a citation QA block",
            )
            flow.guard(mission)
            history = daily.product.list(
                "DailyCycleTransition", matching={"cycle_id": mission}, conn=conn
            )
            require(
                bool(history)
                and history[-1]["from"] == "AWAITING_QA"
                and history[-1]["to"] == "BLOCKED",
                "Not an interrupted QA turn",
            )
            programs = daily.product.list(
                "SequentialDailyProgram", matching={"cycle_id": mission}, conn=conn
            )
            require(len(programs) == 1, "One canonical program required")
            program = programs[0]
            require(
                program["policy_id"] == flow.policy["id"]
                and program["order"] == list(ORDER)
                and program["control_epoch"] == prior["control_epoch"]
                and program["parent_work_item_id"] == prior["parent_work_item_id"],
                "Authority changed",
            )
            day = program["local_date"]
            require(
                now().astimezone(ZoneInfo(program["timezone"])).date().isoformat() == day,
                "Recovery requires original local day",
            )
            turns = daily.require_turn_prefix(mission, prior, conn)
            require(len(turns) < 3, "Completed cycle cannot resume")
            agent = ORDER[len(turns)]
            retained = {t.get("implementation_id") for t in turns}
            merges = daily.product.list("ProductMerge", matching={"mission_id": mission}, conn=conn)
            require(
                all(r.get("implementation_id") in retained for r in merges), "Unaccounted merge"
            )
            builds = daily.product.list("ProductBuild", matching={"mission_id": mission}, conn=conn)
            pending = [b for b in builds if b["implementation_id"] not in retained]
            require(len(pending) == 1, "One pending implementation required")
            build = pending[0]
            require(
                build["builder"] == agent and build["git"]["base_commit"] == head,
                "Candidate baseline or builder changed",
            )
            work = service.host.store.get(build["work_item_id"], conn=conn)
            require(
                work.status == State.CHANGES_REQUESTED
                and work.owner == "triad"
                and work.mission_id == mission
                and work.assigned_agent == agent
                and work.reviewer == REVIEWERS[agent]
                and work.parent_work_item_id == prior["parent_work_item_id"],
                "Work identity changed",
            )
            require(
                not any(
                    w.mission_id == mission
                    and w.status in {State.IN_PROGRESS, State.AWAITING_REVIEW}
                    and w.work_item_id != prior["parent_work_item_id"]
                    for w in service.host.store.list_work(10000)
                ),
                "Cycle has active work",
            )
            approved = host.get(build["approval"], conn=conn)
            proposal = Proposal.model_validate(approved["proposal"])
            flow.approval(mission, agent, proposal, build["approval"])
            require(approved["base_commit"] == head, "Approval baseline changed")
            git = ProductGit(proposal.files, root=flow.root)
            actual = git.verify(build["git"])
            require(
                all(actual[k] == build["checks"][k] for k in ("files", "hashes", "diff")),
                "Candidate changed since QA",
            )
            reviews = host.list(
                "QARun", matching={"implementation_run_id": build["implementation_id"]}, conn=conn
            )
            require(bool(reviews), "Canonical QA required")
            qa = reviews[-1]
            references = [
                e.removeprefix("acceptance-review:")
                for e in qa["evidence"]
                if e.startswith("acceptance-review:")
            ]
            require(
                len(references) == 1
                and qa["decision"] == "CHANGES_REQUIRED"
                and qa["qa_agent"] == REVIEWERS[agent]
                and qa["reviewed_commit"] == build["git"]["change_commit"],
                "Latest QA changed",
            )
            review = host.get(references[0], conn=conn)
            require(
                review["kind"] == "ProductAcceptanceReview"
                and review["owner"] == "triad"
                and review["cycle_id"] == mission
                and review["qa_id"] == qa["id"]
                and review["implementation_id"] == build["implementation_id"]
                and review["approval_id"] == build["approval"]
                and review["required"] == [c.model_dump(mode="json") for c in proposal.acceptance],
                "Review authority mismatch",
            )

            def record(kind):
                rows = conn.execute(
                    "SELECT id,payload FROM core.day3_records WHERE owner='triad' "
                    "AND kind=%s AND payload->>'run_id'=%s",
                    (kind, review["run_id"]),
                ).fetchall()
                require(len(rows) == 1, "Unambiguous original review record required")
                return {**rows[0]["payload"], "id": rows[0]["id"]}

            raw, usage = record("AgentRunResult"), record("Usage")
            result = AgentRunResult.model_validate(
                {k: v for k, v in raw.items() if k in AgentRunResult.model_fields}
            )
            assessment = AcceptanceAssessment.model_validate(review["assessment"])
            require(
                len(result.analysis_artifacts) == 1
                and AcceptanceAssessment.model_validate(result.analysis_artifacts[0]) == assessment,
                "Original assessment differs",
            )
            require(
                usage["status"] == "SUCCESS" and usage["agent"] == REVIEWERS[agent],
                "Original usage invalid",
            )
            ids = review["test_record_ids"]
            require(
                len(ids) == 2
                and len(set(ids)) == 2
                and ids[0] == build["checks"]["test_record_id"],
                "Two original test proofs required",
            )
            proofs = {i: host.get(i, conn=conn) for i in ids}
            require(
                all(p.get("work_item_id") == build["work_item_id"] for p in proofs.values()),
                "Test work identity changed",
            )
            require(
                citation_omission(
                    review["required"], assessment, review["commit"], proofs, result.review_decision
                ),
                "Not solely a citation omission",
            )
            problems = acceptance_problems(review["required"], assessment, review["commit"], proofs)
            require(
                list(problems) == review["problems"]
                and list(problems) == qa["required_changes"]
                and list(result.findings) + list(problems) == qa["findings"]
                and "run:" + review["run_id"] in qa["evidence"]
                and qa["execution_mode"] == "REAL_PROVIDER",
                "Latest QA contains additional or different findings",
            )
            require(
                not host.list(
                    "ProductCitationCorrectionRequested",
                    matching={"implementation_id": build["implementation_id"]},
                    conn=conn,
                ),
                "Citation correction already attempted",
            )
            action = "citation-recovery-" + build["implementation_id"]
            require(
                not conn.execute(
                    "SELECT 1 FROM core.day3_records WHERE id=%s", (action,)
                ).fetchone(),
                "Recovery already attempted",
            )
            policy = service.host.control.evaluate(work)
            require(
                policy.decision in {"ALLOW", "REQUIRE_REVIEW"}, "Current policy denied recovery"
            )
            flow.guard(mission)
            require(service.git.clean_baseline() == head, "Baseline moved")
            host.ledger.put(
                "ControlAction",
                {
                    "action": "resume_exact_candidate_citation_review",
                    "cycle_id": mission,
                    "implementation_id": build["implementation_id"],
                    "prior_qa_id": qa["id"],
                    "revision": head,
                    "health": healthy,
                    "retained_turn_ids": [t["id"] for t in turns],
                    "released_change_slots": 0,
                },
                identifier=action,
                conn=conn,
            )
            # Re-enter the normal review lifecycle, without invoking or claiming a builder run.
            for state in (
                State.VALIDATING,
                State.APPROVED,
                State.ASSIGNED,
                State.IN_PROGRESS,
                State.AWAITING_REVIEW,
            ):
                work = service.host.advance(
                    work,
                    state,
                    "Citation-only re-review of unchanged implementation; no build executed",
                    conn=conn,
                    records=(policy,) if state == State.APPROVED else (),
                )
            payload = {k: v for k, v in prior.items() if k in CycleRecord.model_fields}
            payload.update(
                status="AWAITING_QA",
                finished_at=None,
                blocked_at=None,
                failure_code=None,
                recovery_action=action,
                recorded_at=now(),
            )
            cycle = CycleRecord.model_validate(payload)
            host.append("CycleRecord", cycle.model_dump(mode="json"), owner="triad", conn=conn)
            host.append(
                "DailyCycleTransition",
                {
                    "cycle_id": mission,
                    "from": "BLOCKED",
                    "to": "AWAITING_QA",
                    "timestamp": now().isoformat(),
                    "evidence": [action],
                },
                owner="triad",
                conn=conn,
            )
            qa_work = service.host.store.get(qa["qa_work_item_id"], conn=conn)
            return (
                cycle,
                len(turns),
                day,
                (proposal, git, build, (qa_work, result, assessment, usage, ids[1])),
            )
