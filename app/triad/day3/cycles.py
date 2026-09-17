"""Review-first rotation, operator controls and auditable cycle summaries."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from triad.brain import Brain
from triad.day3.adapters import Runtime
from triad.day3.changes import GitChanges
from triad.day3.contracts import (
    AgentRunRequest,
    AgentRunResult,
    Candidate,
    CycleSummary,
    Disagreement,
    Limits,
)
from triad.day3.ledger import Ledger, Stopped
from triad.gateway import ToolGateway
from triad.orchestrator import Orchestrator
from triad.settings import ROOT
from triad.work import (
    ComputeBudget,
    Handoff,
    PolicyDecision,
    Review,
    State,
    WorkItem,
    WorkResult,
    now,
    uid,
)


def failure_code(exc):
    # Preserve only a host-owned code; never persist arbitrary provider error text.
    if isinstance(exc, PermissionError) and str(exc) == "AUTONOMY_BUDGET_EXHAUSTED":
        return "AUTONOMY_BUDGET_EXHAUSTED"
    return type(exc).__name__


class Cycles:
    def __init__(self, store=None, git=None, day=None):
        self.host = Orchestrator(store=store)
        self.ledger = Ledger(self.host.store)
        self.runtime = Runtime(self.ledger)
        self.git = git or GitChanges()
        self.day = (
            day
            or datetime.now(
                ZoneInfo(
                    json.loads((ROOT / "agents/day3.json").read_text())["scheduler"]["timezone"]
                )
            )
            .date()
            .isoformat()
        )
        self.rotation = tuple(json.loads((ROOT / "agents/day3.json").read_text())["rotation"])
        if self.rotation != self.host.registry.rotation:
            raise ValueError("Runtime and agent registry rotations must agree")

    def initialize(self):
        self.host.initialize()
        self.ledger.initialize()
        Brain(self.host.store).initialize()

    def seed_backlog(self):
        candidates = [
            (
                "recovery",
                "Document how to distinguish failed inference from an unavailable provider",
                ("docs/DAY2_VERIFICATION.md", "docs/LOCAL_MODEL.md"),
            ),
            (
                "lineage",
                "Document the exact evidence an operator should inspect before accepting a generated report",
                ("docs/PROVENANCE.md", "docs/REVIEW_SYSTEM.md"),
            ),
            (
                "budgets",
                "Document why a blocked or no-change outcome is useful rather than forcing daily edits",
                ("docs/ORCHESTRATION.md", "docs/PERMISSIONS.md"),
            ),
        ]
        for key, problem, evidence in candidates:
            identifier = "candidate-" + key
            try:
                self.ledger.get(identifier)
            except KeyError:
                candidate = Candidate(
                    candidate_id=identifier,
                    source="Day 3 setup seed: Day 2 documentation review",
                    problem=problem,
                    evidence=evidence,
                    impact="Operator clarity and reproducible evidence checks",
                    estimated_effort="One bounded Markdown note",
                    confidence=0.8,
                )
                self.ledger.put(
                    "Candidate", candidate.model_dump(mode="json"), identifier=identifier
                )

    def make_work(self, agent, cycle_id, parent=None):
        limits = Limits.model_validate(self.ledger.control()["limits"])
        return self.host.create(
            WorkItem(
                title="One bounded reliability or documentation improvement",
                description="Independently identify a justified low-risk improvement from evidence. No change is acceptable. Never increase trading or governance authority.",
                mission_id=cycle_id,
                parent_work_item_id=parent,
                assigned_agent=agent,
                reviewer=self.host.registry.successor(agent),
                work_type="development",
                authority_tier=2,
                allowed_paths=tuple(dict.fromkeys(("docs", *limits.allowed_directories))),
                reasoning_budget=1024,
                compute_budget=ComputeBudget(
                    max_input_chars=limits.max_input_chars,
                    max_output_tokens=limits.max_output_tokens,
                    timeout_seconds=limits.timeout_seconds,
                ),
                expected_outputs=(
                    "Improvement proposal and bounded text change or justified no-change outcome",
                ),
                acceptance_criteria=(
                    "Change addresses supplied evidence without introducing unsupported claims",
                    "Only approved non-executable text paths are changed",
                    "Host validation passes and independent reviewer approves exact commit",
                ),
            )
        )

    def start_work(self, work, epoch=None):
        authority = self.ledger.guard(work.assigned_agent, work.work_item_id, epoch)["epoch"]
        work = self.host.advance(work, State.VALIDATING, "Day 3 policy evaluation")
        policy = self.host.control.evaluate(work)
        if policy.decision not in {"ALLOW", "REQUIRE_REVIEW"}:
            self.host.advance(work, State.BLOCKED, "Day 3 policy blocked", records=(policy,))
            raise PermissionError("Work policy denied")
        work = self.host.advance(
            work, State.APPROVED, "Bounded development assignment approved", records=(policy,)
        )
        work = self.host.advance(work, State.ASSIGNED, "Assigned cycle improvement opportunity")
        work = self.host.advance(work, State.IN_PROGRESS, "Day 3 runtime started")
        self.ledger.put(
            "RunAuthority",
            {"epoch": authority},
            identifier="authority-" + work.work_item_id,
            work_id=work.work_item_id,
        )
        self.ledger.event("agent_started", work.work_item_id, agent=work.assigned_agent)
        return work, policy

    def request(self, work, policy, role, context, agent=None):
        read = role == "REVIEW"
        return AgentRunRequest(
            agent_id=agent or work.assigned_agent,
            control_epoch=self.ledger.get("authority-" + work.work_item_id)["epoch"],
            work_item_id=work.work_item_id,
            mission_id=work.mission_id,
            context_packet=context,
            role=role,
            objective=work.description,
            allowed_tools=() if read else ("propose_file_change",),
            allowed_paths=work.allowed_paths,
            acceptance_criteria=work.acceptance_criteria,
            token_budget=work.compute_budget.max_output_tokens,
            reasoning_budget=min(work.reasoning_budget, work.compute_budget.max_output_tokens),
            execution_permissions=("read",) if read else ("write_docs",),
            policy_decision=policy.model_dump(mode="json"),
            required_output_schema=AgentRunResult.model_json_schema(),
        )

    def evaluate_proposal(self, proposal, work):
        limits = Limits.model_validate(self.ledger.control()["limits"])
        if proposal.agent != work.assigned_agent:
            verdict, reason = "DENY", "Proposal identity mismatch"
        elif proposal.risk_class != "LOW":
            verdict, reason = (
                "REQUIRE_HUMAN_APPROVAL",
                "Higher-risk proposals cannot execute under current autonomy policy",
            )
        elif not set(proposal.permissions_required) <= {"write_docs"} or not set(
            proposal.affected_components
        ) <= set(limits.allowed_directories):
            verdict, reason = "DENY", "Proposal exceeds immutable assignment scope"
        elif (
            proposal.estimated_cost > limits.max_cost_run
            or not proposal.test_plan
            or not proposal.rollback_plan
        ):
            verdict, reason = "DENY", "Missing verification/reversibility or excessive cost"
        else:
            verdict, reason = (
                "ALLOW",
                "Low-risk reversible bounded text improvement; mandatory independent review",
            )
        self.ledger.put(
            "Proposal",
            {
                **proposal.model_dump(mode="json"),
                "decision": verdict,
                "reason": reason,
                "evaluated_at": now().isoformat(),
                "policy_version": "day3-v1",
            },
            identifier=proposal.proposal_id,
            work_id=work.work_item_id,
        )
        self.ledger.event(
            "proposal_approved" if verdict == "ALLOW" else "proposal_denied",
            work.work_item_id,
            proposal_id=proposal.proposal_id,
            decision=verdict,
        )
        return verdict

    def proposal_action(self, identifier, action):
        record = self.ledger.get(identifier)
        if record["kind"] != "Proposal":
            raise ValueError("Expected proposal")
        if action == "deny":
            record["decision"] = "DENY"
            record["reason"] = "Denied by human operator"
            self.ledger.operate("stop", work_id=record["work_item_id"])
        elif action == "approve":
            if record["decision"] != "ALLOW":
                raise PermissionError(
                    "Human UI approval cannot override scope, risk or budget ceilings"
                )
            record["human_approved"] = True
        else:
            raise ValueError("Unknown proposal action")
        self.ledger.put("Proposal", record, identifier=identifier, work_id=record["work_item_id"])
        self.ledger.event(
            "human_proposal_" + action, record["work_item_id"], proposal_id=identifier
        )
        return record

    def handoff(self, work, result, metadata, checks, mode):
        commit = metadata.get("change_commit") if metadata else self.git.git("rev-parse", "HEAD")
        evidence = tuple(f"sha256:{v}:{k}" for k, v in checks.get("hashes", {}).items())
        journal = self.host.journal(
            work,
            kind="creation",
            result=result.summary,
            evidence=evidence,
            files=checks.get("files", ()),
            tests=checks.get("checks", ()),
            actions=("Provider proposed structured changes; host applied approved files",),
            mode=mode,
        ).model_copy(update={"git_commit": commit})
        handoff = Handoff(
            from_agent=work.assigned_agent,
            to_agent=work.reviewer,
            work_item_id=work.work_item_id,
            completed_work=result.summary,
            files_changed=tuple(checks.get("files", ())),
            tests_performed=tuple(checks.get("checks", ())),
            evidence=evidence,
            recommended_checks=work.acceptance_criteria,
            git_commit=commit,
            review_request="Independently inspect objective, criteria, source/diff and repeated checks; prior model reasoning is withheld initially",
        )
        legacy = WorkResult(
            summary=result.summary,
            tests=tuple(checks.get("checks", ())),
            evidence=evidence,
            execution_mode="deterministic_demo"
            if mode == "SIMULATED"
            else "ollama"
            if work.assigned_agent == "LOCAL_QWEN"
            else "cloud",
        )
        work = self.host.advance(
            work,
            State.AWAITING_REVIEW,
            "Structured journal and handoff persisted before independent review",
            records=(journal, handoff),
            result=legacy,
        )
        self.ledger.event("handoff_created", work.work_item_id, handoff_id=handoff.handoff_id)
        return work

    def review_change(self, change_id, *, human_merge=False):
        record = self.ledger.get(change_id)
        work = self.host.store.get(record["work_item_id"])
        if work.status not in {State.AWAITING_REVIEW, State.APPROVED_BY_REVIEWER}:
            raise PermissionError("No reviewable change")
        control = self.ledger.guard(work.reviewer, work.work_item_id)
        epoch = self.ledger.get("authority-" + work.work_item_id)["epoch"]
        self.ledger.guard(work.reviewer, work.work_item_id, epoch)
        limits = Limits.model_validate(control["limits"])
        metadata = record.get("git")
        if record.get("status") == "AWAITING_HUMAN_MERGE":
            if not human_merge:
                return record
            review_data = record["review"]
            if self.ledger.records("Disagreement") and any(
                d["work_item_id"] == work.work_item_id and d["status"] == "OPEN"
                for d in self.ledger.records("Disagreement")
            ):
                raise PermissionError("Unresolved disagreement blocks merge")
        else:
            self.ledger.event("review_started", work.work_item_id, reviewer=work.reviewer)
            checks = (
                self.git.verify(metadata, limits)
                if metadata
                else {
                    "passed": True,
                    "checks": ["No modification proposed"],
                    "sources": {},
                    "diff": "",
                    "hashes": {},
                    "files": [],
                }
            )
            policy_data = self.host.store.records("PolicyDecision", work.work_item_id, 1)[0]
            policy = PolicyDecision.model_validate(
                {k: v for k, v in policy_data.items() if k != "kind"}
            )
            context = {
                "objective": work.description,
                "original_sources": self.source_context(
                    work, {"evidence": record.get("source_paths", [])}
                ),
                "acceptance_criteria": work.acceptance_criteria,
                "sources": checks["sources"],
                "diff": checks["diff"],
                "tests": {k: v for k, v in checks.items() if k not in {"sources", "diff"}},
                "resulting_state": {
                    "base_commit": metadata.get("base_commit") if metadata else None,
                    "change_commit": metadata.get("change_commit") if metadata else None,
                },
                "no_change": metadata is None,
            }
            request = self.request(work, policy, "REVIEW", context, agent=work.reviewer)
            result = self.runtime.execute(request, mode=record["mode"], day=self.day)
            if not result.review_decision:
                raise ValueError("Reviewer omitted structured verdict")
            if result.files_changed or result.proposal:
                raise PermissionError("Reviewer cannot implement during independent review")
            review = Review(
                reviewer=work.reviewer,
                work_item_id=work.work_item_id,
                decision=result.review_decision,
                findings=result.findings or (result.summary,),
                severity="NONE" if result.review_decision == "APPROVE" else "MEDIUM",
                required_changes=result.findings if result.review_decision != "APPROVE" else (),
                evidence_checked=tuple(checks["hashes"].values()),
                tests_repeated=tuple(checks["checks"]),
                execution_mode=record["mode"],
            )
            review_data = {
                **review.model_dump(mode="json"),
                "worker": work.assigned_agent,
                "change_commit": metadata.get("change_commit") if metadata else None,
            }
            self.record_review(review_data, work.work_item_id)
            journal = self.host.journal(
                work,
                kind="review",
                result=f"{review.decision}: " + result.summary,
                evidence=review.evidence_checked,
                tests=review.tests_repeated,
                mode=record["mode"],
            )
            target = {
                "APPROVE": State.APPROVED_BY_REVIEWER,
                "REJECT": State.REJECTED,
                "REQUEST_CHANGES": State.CHANGES_REQUESTED,
            }[review.decision]
            work = self.host.advance(
                work,
                target,
                "Independent Day 3 review persisted",
                records=(review, journal),
                review=review,
            )
            record["review"] = review_data
            self.ledger.event(
                "review_completed",
                work.work_item_id,
                review_id=review.review_id,
                decision=review.decision,
            )
            if metadata:
                metadata = self.git.review_commit(metadata, review.review_id, review.decision)
                record["git"] = metadata
            if review.decision != "APPROVE":
                disagreement = Disagreement(
                    work_item_id=work.work_item_id,
                    agents=(work.assigned_agent, work.reviewer),
                    claims_in_conflict=("Worker proposed acceptance", *review.findings),
                    evidence_used=review.evidence_checked,
                    severity="MEDIUM",
                    review_ids=(review.review_id,),
                )
                self.ledger.put(
                    "Disagreement",
                    disagreement.model_dump(mode="json"),
                    identifier=disagreement.disagreement_id,
                    work_id=work.work_item_id,
                )
                record["status"] = review.decision
                self.ledger.put("Change", record, identifier=change_id, work_id=work.work_item_id)
                return record
        # Fresh human controls, proposal decisions and exact Git hashes are checked immediately before merge.
        self.ledger.guard(work.assigned_agent, work.work_item_id, epoch)
        if (
            record.get("proposal_id")
            and self.ledger.get(record["proposal_id"])["decision"] != "ALLOW"
        ):
            raise PermissionError("Proposal is no longer approved")
        if control["require_human_review"] and not human_merge:
            record["status"] = "AWAITING_HUMAN_MERGE"
            self.ledger.put("Change", record, identifier=change_id, work_id=work.work_item_id)
            return record
        if any(
            d["work_item_id"] == work.work_item_id and d["status"] == "OPEN"
            for d in self.ledger.records("Disagreement")
        ):
            raise PermissionError("Unresolved disagreement blocks merge")
        with self.ledger.gate(work.assigned_agent, work.work_item_id, epoch) as fresh:
            if fresh["require_human_review"] and not human_merge:
                raise Stopped("Human merge approval required")
            if metadata:
                record["git"] = self.git.merge(
                    metadata, review_data, Limits.model_validate(fresh["limits"])
                )
        work = self.host.advance(
            work,
            State.COMPLETED,
            "Independent review satisfied; protected change merged"
            if metadata
            else "Independent no-change decision accepted",
        )
        record["status"] = "MERGED" if metadata else "NO_CHANGE_JUSTIFIED"
        if record.get("rollback_of"):
            original = self.ledger.get(record["rollback_of"])
            original["status"] = "ROLLED_BACK"
            original["rollback_change_id"] = change_id
            self.ledger.put(
                "Change", original, identifier=original["id"], work_id=original["work_item_id"]
            )
            try:
                summary = self.ledger.get("summary-" + original["cycle_id"])
                summary["changes_rolled_back"] = list(
                    dict.fromkeys([*summary["changes_rolled_back"], original["id"]])
                )
                self.ledger.put("CycleSummary", summary, identifier=summary["id"])
                cycle = self.ledger.get(original["cycle_id"])
                cycle["summary"]["changes_rolled_back"] = summary["changes_rolled_back"]
                self.ledger.put("Cycle", cycle, identifier=cycle["id"])
            except KeyError:
                pass
        record["merge_authority"] = "authenticated_human" if human_merge else "host_policy_day3-v1"
        self.ledger.put("Change", record, identifier=change_id, work_id=work.work_item_id)
        self.ledger.event(
            "merge_completed" if metadata else "no_change_accepted",
            work.work_item_id,
            change_id=change_id,
            git=record.get("git"),
            authority=record["merge_authority"],
        )
        return record

    def stage(self, agent, cycle_id, mode, candidate, parent=None):
        work = self.make_work(agent, cycle_id, parent)
        epoch = self.ledger.reserve(agent, work.work_item_id, improvement=True, day=self.day)
        work, policy = self.start_work(work, epoch)
        try:
            result = self.runtime.execute(
                self.request(
                    work,
                    policy,
                    "PROPOSE",
                    {
                        "candidate": candidate,
                        "source_files": self.source_context(work, candidate),
                        "write_directories": self.ledger.control()["limits"]["allowed_directories"],
                        "charter": "Bounded engineering; human governance; no live trading",
                    },
                ),
                mode=mode,
                day=self.day,
            )
            metadata = None
            checks = {
                "passed": True,
                "checks": ["No modification proposed"],
                "files": [],
                "hashes": {},
            }
            proposal_id = None
            if result.status != "NO_CHANGE_JUSTIFIED":
                if result.status == "BLOCKED" or not result.proposal:
                    raise PermissionError("No actionable structured proposal")
                proposal_id = result.proposal.proposal_id
                self.ledger.event("proposal_created", work.work_item_id, proposal_id=proposal_id)
                if self.evaluate_proposal(result.proposal, work) != "ALLOW":
                    raise PermissionError("Proposal requires denial or human review")
                self.ledger.guard(
                    agent,
                    work.work_item_id,
                    self.ledger.get("authority-" + work.work_item_id)["epoch"],
                )
                result = self.runtime.execute(
                    self.request(
                        work,
                        policy,
                        "IMPLEMENT",
                        {
                            "proposal": result.proposal.model_dump(mode="json"),
                            "candidate": candidate,
                            "source_files": self.source_context(work, candidate),
                            "write_directories": self.ledger.control()["limits"][
                                "allowed_directories"
                            ],
                            "instruction": "Return proposed file contents; host applies them after scope validation.",
                        },
                    ),
                    mode=mode,
                    day=self.day,
                )
                if result.status != "NO_CHANGE_JUSTIFIED":
                    metadata = self.git.isolate(work.work_item_id, agent)
                    self.ledger.put(
                        "GitCheckpoint",
                        {"git": metadata, "status": "ISOLATED"},
                        identifier="git-" + work.work_item_id,
                        work_id=work.work_item_id,
                    )
                    limits = Limits.model_validate(
                        self.ledger.guard(
                            agent,
                            work.work_item_id,
                            self.ledger.get("authority-" + work.work_item_id)["epoch"],
                        )["limits"]
                    )
                    if self.ledger.get(proposal_id)["decision"] != "ALLOW":
                        raise PermissionError("Proposal no longer approved")
                    checks = self.git.apply(metadata, result.files_changed, limits)
                    for path in checks["files"]:
                        self.ledger.event("file_changed", work.work_item_id, path=path)
                    self.ledger.event("test_started", work.work_item_id, checks=checks["checks"])
                    self.ledger.event("test_passed", work.work_item_id, evidence=checks["hashes"])
                    self.ledger.guard(
                        agent,
                        work.work_item_id,
                        self.ledger.get("authority-" + work.work_item_id)["epoch"],
                    )
                    metadata = self.git.commit(metadata, agent)
                    self.ledger.put(
                        "GitCheckpoint",
                        {"git": metadata, "status": "COMMITTED"},
                        identifier="git-" + work.work_item_id,
                        work_id=work.work_item_id,
                    )
            if result.status == "NO_CHANGE_JUSTIFIED" and result.files_changed:
                raise PermissionError("No-change response contains modifications")
            work = self.handoff(work, result, metadata, checks, mode)
            change_id = uid()
            record = {
                "cycle_id": cycle_id,
                "agent": agent,
                "reviewer": work.reviewer,
                "mode": mode,
                "proposal_id": proposal_id,
                "status": "AWAITING_REVIEW",
                "git": metadata,
                "outcome": result.status,
                "candidate_id": candidate["candidate_id"],
                "source_paths": candidate["evidence"],
            }
            self.ledger.put("Change", record, identifier=change_id, work_id=work.work_item_id)
            outcome = self.review_change(change_id)
            return outcome
        except Exception as exc:
            current = self.host.store.get(work.work_item_id)
            if current.status in {
                State.IN_PROGRESS,
                State.AWAITING_REVIEW,
                State.APPROVED_BY_REVIEWER,
            }:
                journal = self.host.journal(
                    current,
                    kind="failure",
                    result="Day 3 bounded stage stopped",
                    failures=(failure_code(exc),),
                    mode=mode,
                )
                self.host.advance(
                    current,
                    State.BLOCKED,
                    "Stage stopped; inspect evidence before resuming",
                    records=(journal,),
                    failure_reason=failure_code(exc),
                )
            for change in self.ledger.records("Change"):
                if (
                    change["work_item_id"] == work.work_item_id
                    and change["status"] == "AWAITING_REVIEW"
                ):
                    change.update(status="BLOCKED", failure_reason=failure_code(exc))
                    self.ledger.put(
                        "Change", change, identifier=change["id"], work_id=work.work_item_id
                    )
            self.ledger.event(
                "stage_failed", work.work_item_id, error_class=failure_code(exc), mode=mode
            )
            raise

    def run(self, mode="REAL", scheduled=False, expected_epoch=None):
        if mode not in {"REAL", "SIMULATED"}:
            raise ValueError("Explicit REAL or SIMULATED mode required")
        with self.host.store.lease("day3-cycle"):
            cycle_epoch = self.ledger.guard(epoch=expected_epoch)["epoch"]
            self.seed_backlog()
            cycle_id = uid()
            with self.host.store.connect() as c:
                existing = c.execute(
                    "SELECT cycle_id FROM triad.cycle_slots WHERE day=%s AND mode=%s",
                    (self.day, mode),
                ).fetchone()
                if existing:
                    return self.ledger.get(existing["cycle_id"])
                c.execute(
                    "INSERT INTO triad.cycle_slots VALUES (%s,%s,%s)", (self.day, mode, cycle_id)
                )
                self.ledger.put(
                    "Cycle",
                    {
                        "cycle_id": cycle_id,
                        "date": self.day,
                        "mode": mode,
                        "status": "RUNNING",
                        "scheduled": scheduled,
                        "stage": None,
                    },
                    identifier=cycle_id,
                    conn=c,
                )
            self.ledger.event("cycle_started", cycle_id=cycle_id, mode=mode)
            accepted = []
            rejected = []
            failures = []
            agents = []
            parent = None
            try:
                for agent in self.rotation:
                    self.ledger.guard(agent, epoch=cycle_epoch)
                    adapter = self.runtime.provider(agent, mode)
                    health = adapter.health_check()
                    if health.status != "AVAILABLE":
                        failures.append(f"{agent}: {health.status} / {health.error_class}")
                        self.ledger.put(
                            "ProviderHealth",
                            health.model_dump(mode="json"),
                            identifier="health-" + agent,
                        )
                        self.ledger.event(
                            "provider_failed",
                            cycle_id=cycle_id,
                            agent=agent,
                            status=health.status,
                            mode="UNAVAILABLE",
                        )
                        continue
                    candidates = [
                        r
                        for r in self.ledger.records("Candidate")
                        if r["status"] == "OPEN" and r["risk"] == "LOW"
                    ]
                    if not candidates:
                        break
                    candidate = candidates[-1]
                    candidate["status"] = "SELECTED"
                    self.ledger.put("Candidate", candidate, identifier=candidate["candidate_id"])
                    self.ledger.put(
                        "Cycle",
                        {
                            "cycle_id": cycle_id,
                            "date": self.day,
                            "mode": mode,
                            "status": "RUNNING",
                            "stage": agent,
                            "next_agent": self.host.registry.successor(agent),
                        },
                        identifier=cycle_id,
                    )
                    agents.append(agent)
                    outcome = self.stage(agent, cycle_id, mode, candidate, parent)
                    if outcome["status"] not in {"MERGED", "NO_CHANGE_JUSTIFIED"}:
                        rejected.append(outcome["id"])
                        failures.append("Rotation stopped for review/human decision")
                        break
                    accepted.append(outcome["id"])
                    parent = outcome["work_item_id"]
                    candidate["status"] = "DONE"
                    self.ledger.put("Candidate", candidate, identifier=candidate["candidate_id"])
            except Exception as exc:  # noqa: BLE001 - persist redacted terminal cycle failure
                failures.append(failure_code(exc))
            changes = [r for r in self.ledger.records("Change") if r.get("cycle_id") == cycle_id]
            work_ids = {
                w.work_item_id for w in self.host.store.list_work(1000) if w.mission_id == cycle_id
            }
            reviews = [
                r for r in self.ledger.records("AutonomousReview") if r["work_item_id"] in work_ids
            ]
            disagreements = [
                r for r in self.ledger.records("Disagreement") if r["work_item_id"] in work_ids
            ]
            usages = [
                r for r in self.ledger.records("Usage", 1000) if r["work_item_id"] in work_ids
            ]
            summary = CycleSummary(
                cycle_id=cycle_id,
                date=self.day,
                agents_run=tuple(agents),
                proposals=tuple(r["proposal_id"] for r in changes if r.get("proposal_id")),
                changes_accepted=tuple(accepted),
                changes_rejected=tuple(rejected),
                reviews=tuple(r["id"] for r in reviews),
                disagreements=tuple(r["id"] for r in disagreements),
                tests=tuple(check for r in reviews for check in r["tests_repeated"]),
                cost=sum(r["estimated_cost"] for r in usages),
                failures=tuple(failures),
                lessons=("Decision evidence is separate from outcomes; no change is valid.",),
                open_questions=(
                    "Cloud-provider quality remains unverified without authorized credentials.",
                )
                if mode == "SIMULATED"
                else (),
                next_cycle_candidates=tuple(
                    r["candidate_id"]
                    for r in self.ledger.records("Candidate")
                    if r["status"] != "DONE"
                ),
            )
            self.ledger.put(
                "CycleSummary", summary.model_dump(mode="json"), identifier="summary-" + cycle_id
            )
            cycle = {
                "cycle_id": cycle_id,
                "date": self.day,
                "mode": mode,
                "status": "BLOCKED" if failures else "COMPLETED",
                "agents_run": agents,
                "summary": summary.model_dump(mode="json"),
            }
            self.ledger.put("Cycle", cycle, identifier=cycle_id)
            self.ledger.event("cycle_completed", cycle_id=cycle_id, status=cycle["status"])
            Brain(self.host.store).flush()
            return cycle

    def request_reasoning(self, work_id, agent, requested, justification):
        work = self.host.store.get(work_id)
        if agent != work.assigned_agent:
            raise PermissionError("Request identity mismatch")
        decision = "ALLOW" if 0 <= requested <= work.reasoning_budget else "REQUIRE_HUMAN_APPROVAL"
        if requested < 0 or requested > 2048:
            decision = "DENY"
        payload = {
            "work_item_id": work_id,
            "agent": agent,
            "requested": requested,
            "justification": justification,
            "decision": decision,
            "reason": "Existing ceiling remains immutable; increases require a new human-authorized assignment",
        }
        self.ledger.put("ReasoningRequest", payload, work_id=work_id)
        return payload

    def source_context(self, work, candidate):
        gateway = ToolGateway(work, self.git.root)
        entries = []
        for path in candidate.get("evidence", [])[:2]:
            if not (self.git.root / path).is_file():
                entries.append(
                    {
                        "source": path,
                        "classification": "OBSERVATION",
                        "text": "Source not available in this checkout",
                    }
                )
                continue
            text = gateway.read(path)
            entries.append(
                {
                    "source": path,
                    "timestamp": now().isoformat(),
                    "classification": "OBSERVATION",
                    "text": text[:3000],
                    "evidence": gateway.evidence[-1],
                    "excerpt": len(text) > 3000,
                }
            )
        return entries

    def record_review(self, review_data, work_id):
        existing = [
            r
            for r in self.ledger.records("AutonomousReview")
            if r["work_item_id"] == work_id
            and r.get("change_commit") == review_data.get("change_commit")
            and r["reviewer"] != review_data["reviewer"]
            and r["decision"] != review_data["decision"]
        ]
        self.ledger.put(
            "AutonomousReview", review_data, identifier=review_data["review_id"], work_id=work_id
        )
        for prior in existing:
            disagreement = Disagreement(
                work_item_id=work_id,
                agents=(prior["reviewer"], review_data["reviewer"]),
                claims_in_conflict=(prior["decision"], review_data["decision"]),
                evidence_used=tuple(prior["evidence_checked"])
                + tuple(review_data["evidence_checked"]),
                severity="HIGH",
                review_ids=(prior["review_id"], review_data["review_id"]),
            )
            self.ledger.put(
                "Disagreement",
                disagreement.model_dump(mode="json"),
                identifier=disagreement.disagreement_id,
                work_id=work_id,
            )

    def prepare_rollback(self, change_id):
        original = self.ledger.get(change_id)
        if original["kind"] != "Change" or original["status"] != "MERGED":
            raise PermissionError("Rollback requires a merged change")
        self.ledger.guard()
        original_work = self.host.store.get(original["work_item_id"])
        work = self.make_work(
            original_work.assigned_agent, original_work.mission_id, original_work.work_item_id
        )
        self.ledger.reserve(work.assigned_agent, work.work_item_id, improvement=True, day=self.day)
        work, _policy = self.start_work(work)
        self.ledger.event(
            "rollback_requested",
            work.work_item_id,
            original_change=change_id,
            actor="authenticated_operator",
        )
        metadata = self.git.prepare_revert(original["git"], work.work_item_id, work.assigned_agent)
        checks = self.git.verify(metadata, Limits.model_validate(self.ledger.control()["limits"]))
        result = AgentRunResult(
            run_id=uid(),
            status="BUG_FIX",
            summary="Host prepared an exact Git revert; independent review is required before merge",
        )
        self.handoff(work, result, metadata, checks, original["mode"])
        identifier = uid()
        self.ledger.put(
            "Change",
            {
                "cycle_id": original_work.mission_id,
                "agent": work.assigned_agent,
                "reviewer": work.reviewer,
                "mode": original["mode"],
                "proposal_id": None,
                "status": "AWAITING_REVIEW",
                "git": metadata,
                "outcome": "ROLLBACK",
                "rollback_of": change_id,
            },
            identifier=identifier,
            work_id=work.work_item_id,
        )
        return self.ledger.get(identifier)

    def recover(self):
        recovered = []
        with self.host.store.lease("day3-cycle"):
            for cycle in self.ledger.records("Cycle"):
                if cycle["status"] != "RUNNING":
                    continue
                for work in self.host.store.list_work(1000):
                    if work.mission_id != cycle["cycle_id"]:
                        continue
                    if work.status == State.CREATED:
                        work = self.host.advance(
                            work,
                            State.VALIDATING,
                            "Recovery inspects interrupted pending assignment",
                        )
                    if work.status in {
                        State.VALIDATING,
                        State.APPROVED,
                        State.ASSIGNED,
                        State.IN_PROGRESS,
                        State.AWAITING_REVIEW,
                        State.APPROVED_BY_REVIEWER,
                    }:
                        self.host.advance(
                            work,
                            State.BLOCKED,
                            "Interrupted cycle recovered; operator must reconcile recorded Git checkpoints",
                            failure_reason="InterruptedCycle",
                        )
                cycle["status"] = "BLOCKED"
                cycle["recovery"] = (
                    "Inspect Git checkpoints and actual branch/main before any new action; reservations retained"
                )
                self.ledger.put("Cycle", cycle, identifier=cycle["cycle_id"])
                self.ledger.event("cycle_recovered", cycle_id=cycle["cycle_id"])
                recovered.append(cycle["cycle_id"])
        Brain(self.host.store).flush()
        return {"recovered": recovered}
