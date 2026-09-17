"""Bounded operator-driven lifecycle; no provider has direct state or permission mutation."""

import subprocess
from typing import Literal

from triad.brain import Brain
from triad.context import packet_for
from triad.control import ControlPlane, Registry
from triad.gateway import ToolGateway
from triad.providers import DocumentationReviewer, DocumentationWorker, QwenProvider
from triad.settings import ROOT
from triad.store import Store
from triad.work import (
    ElevationRequest,
    Handoff,
    JournalEntry,
    Review,
    State,
    WorkItem,
    WorkResult,
    transition,
)


def implementation_commit() -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()


class Orchestrator:
    def __init__(self, store: Store | None = None, registry: Registry | None = None):
        self.store = store or Store()
        self.registry = registry or Registry()
        self.control = ControlPlane(self.registry)

    def initialize(self):
        self.store.migrate()
        for agent in self.registry.agents.values():
            self.store.add_record(agent)
        Brain(self.store).initialize()
        return Brain(self.store).flush()

    def create(self, work: WorkItem) -> WorkItem:
        work = WorkItem.model_validate(work.model_dump())
        agent, _ = self.registry.route(work)
        reviewer = (
            (work.reviewer or self.registry.successor(agent)) if work.review_required else None
        )
        work = WorkItem.model_validate(
            work.model_dump() | {"assigned_agent": agent, "reviewer": reviewer}
        )
        self.store.create(work)
        return work

    def advance(
        self, work: WorkItem, target: State, detail: str, records=(), review=None, **updates
    ):
        next_work = transition(work, target, approved_review=review)
        next_work = WorkItem.model_validate(next_work.model_dump() | updates)
        self.store.step(work, next_work, detail, tuple(records))
        return next_work

    def journal(
        self,
        work: WorkItem,
        *,
        kind: Literal["creation", "review", "failure"],
        result: str,
        evidence=(),
        actions=(),
        files=(),
        tests=(),
        failures=(),
        mode="host",
    ):
        return JournalEntry(
            agent=work.reviewer if kind == "review" else work.assigned_agent,
            work_item_id=work.work_item_id,
            mission_id=work.mission_id,
            objective=work.title,
            context_received=(f"work:{work.work_item_id}",),
            actions_taken=tuple(actions),
            files_changed=tuple(files),
            tests_run=tuple(tests),
            results=result,
            failures=tuple(failures),
            evidence=tuple(evidence),
            recommended_next_step="Inspect independent review"
            if kind == "creation"
            else "Operator may select the next bounded assignment",
            handoff_to=work.reviewer if kind == "creation" else None,
            git_commit=implementation_commit(),
            event_kind=kind,
            execution_mode=mode,
        )

    def submit_result(self, work: WorkItem, result: WorkResult, gateway: ToolGateway) -> WorkItem:
        if work.status != State.IN_PROGRESS:
            raise PermissionError("Results require an active host assignment")
        result = WorkResult.model_validate(result.model_dump())
        if (
            result.output_tokens > work.compute_budget.max_output_tokens
            or result.elapsed_seconds > work.compute_budget.timeout_seconds
        ):
            raise PermissionError("Provider exceeded compute budget")
        if any(c.kind in {"FACT", "TEST_RESULT"} for c in result.claims):
            raise PermissionError("Provider assertions cannot self-promote into verified facts")
        for artifact in result.artifacts:
            gateway.write(artifact.path, artifact.content)
        evidence = tuple(dict.fromkeys((*result.evidence, *gateway.evidence)))
        result = WorkResult.model_validate(result.model_dump() | {"evidence": evidence})
        journal = self.journal(
            work,
            kind="creation",
            result=result.summary,
            evidence=evidence,
            actions=result.actions,
            files=gateway.changed,
            tests=result.tests,
            failures=result.issues,
            mode=result.execution_mode,
        )
        records = [journal, *result.claims]
        if work.review_required:
            records.append(
                Handoff(
                    from_agent=work.assigned_agent,
                    to_agent=work.reviewer,
                    work_item_id=work.work_item_id,
                    completed_work=result.summary,
                    files_changed=tuple(gateway.changed),
                    tests_performed=result.tests,
                    evidence=evidence,
                    known_issues=result.issues,
                    recommended_checks=work.acceptance_criteria,
                    git_commit=implementation_commit(),
                    review_request="Independently verify source evidence and artifact; do not trust the worker's claims",
                )
            )
        return self.advance(
            work,
            State.AWAITING_REVIEW if work.review_required else State.COMPLETED,
            "Host accepted structured result and persisted journal/handoff",
            records=records,
            result=result,
        )

    def run(
        self,
        work_id: str,
        *,
        mode: Literal["deterministic_demo", "real"] = "deterministic_demo",
        auto_review: bool = True,
    ) -> WorkItem:
        with self.store.lease(work_id):
            work = self.store.get(work_id)
            if work.status not in {
                State.CREATED,
                State.CHANGES_REQUESTED,
                State.BLOCKED,
                State.FAILED,
            }:
                raise ValueError("Work is not executable in its current state")
            work = self.advance(
                work, State.VALIDATING, "Control Plane evaluating immutable assignment"
            )
            decision = self.control.evaluate(work)
            if decision.decision in {"DENY", "REQUIRE_HUMAN_APPROVAL"}:
                target = State.REJECTED if decision.decision == "DENY" else State.BLOCKED
                work = self.advance(
                    work,
                    target,
                    decision.reason,
                    records=(decision,),
                    failure_reason=decision.reason,
                )
            else:
                work = self.advance(
                    work, State.APPROVED, "Assignment passed policy", records=(decision,)
                )
                agent = self.registry.agents[work.assigned_agent]
                demo_available = (
                    mode == "deterministic_demo"
                    and work.work_type == "documentation_audit"
                    and agent.role == "member"
                )
                local_available = mode == "real" and agent.integration == "ollama"
                if not demo_available and not local_available:
                    work = self.advance(
                        work,
                        State.BLOCKED,
                        "Provider integration unavailable; no simulated cloud call substituted",
                        failure_reason="BLOCKED — requires external provider integration/authorization",
                    )
                else:
                    work = self.advance(
                        work,
                        State.ASSIGNED,
                        f"Bounded assignment to {work.assigned_agent}; mode={mode}",
                    )
                    try:
                        packet = packet_for(
                            work, self.store.records("JournalEntry"), self.store.records("Handoff")
                        )
                        work = self.advance(
                            work,
                            State.IN_PROGRESS,
                            "Provider began bounded work",
                            records=(packet,),
                        )
                        gateway = ToolGateway(work)
                        provider = (
                            DocumentationWorker()
                            if demo_available
                            else QwenProvider(self.store.settings)
                        )
                        result = provider.perform(work, packet, gateway)
                        work = self.submit_result(work, result, gateway)
                    except Exception as exc:
                        current = self.store.get(work_id)
                        if current.status in {State.ASSIGNED, State.IN_PROGRESS}:
                            failure = self.journal(
                                current,
                                kind="failure",
                                result="Bounded run failed",
                                failures=(type(exc).__name__,),
                            )
                            work = self.advance(
                                current,
                                State.FAILED
                                if current.status == State.IN_PROGRESS
                                else State.BLOCKED,
                                "Provider/tool failure",
                                records=(failure,),
                                failure_reason=type(exc).__name__,
                            )
                        else:
                            raise
        if work.status == State.AWAITING_REVIEW and auto_review:
            work = self.review(work_id, mode=mode)
        Brain(self.store).flush()
        return work

    def apply_review(self, work: WorkItem, review: Review) -> WorkItem:
        if (
            work.status != State.AWAITING_REVIEW
            or review.reviewer != work.reviewer
            or review.reviewer == work.assigned_agent
            or review.work_item_id != work.work_item_id
        ):
            raise PermissionError("Review does not match independent pending assignment")
        reviewer = self.registry.agents[review.reviewer]
        if not reviewer.review_eligible or not reviewer.enabled:
            raise PermissionError("Reviewer is not eligible")
        journal = self.journal(
            work,
            kind="review",
            result=f"{review.decision}: {'; '.join(review.findings)}",
            evidence=review.evidence_checked,
            actions=("Independent review",),
            tests=review.tests_repeated,
            failures=review.required_changes,
            mode=review.execution_mode,
        )
        target = {
            "APPROVE": State.APPROVED_BY_REVIEWER,
            "REJECT": State.REJECTED,
            "REQUEST_CHANGES": State.CHANGES_REQUESTED,
        }[review.decision]
        work = self.advance(
            work, target, "Independent review persisted", records=(review, journal), review=review
        )
        if target == State.APPROVED_BY_REVIEWER:
            work = self.advance(work, State.COMPLETED, "Mandatory independent review satisfied")
        return work

    def review(self, work_id: str, *, mode: str = "deterministic_demo") -> WorkItem:
        with self.store.lease(work_id):
            work = self.store.get(work_id)
            if work.status != State.AWAITING_REVIEW:
                raise ValueError("No pending review")
            if mode != "deterministic_demo" or work.work_type != "documentation_audit":
                # Preserve the pending handoff; never turn missing provider access into approval.
                return work
            handoff_data = self.store.records("Handoff", work_id, 1)[0]
            handoff = Handoff.model_validate({k: v for k, v in handoff_data.items() if k != "kind"})
            review = DocumentationReviewer().review(work, handoff, ToolGateway(work))
            work = self.apply_review(work, review)
        Brain(self.store).flush()
        return work

    def request_elevation(self, request: ElevationRequest):
        self.store.add_record(request)
        return request

    def demo(self, *, worker: str = "CODEX", parent: str | None = None) -> WorkItem:
        previous = self.store.get(parent) if parent else None
        if previous and previous.status != State.COMPLETED:
            raise ValueError("Improvement rotation requires a completed reviewed parent")
        if previous and worker != self.registry.successor(previous.assigned_agent):
            raise PermissionError("Improvement must follow the configured member rotation")
        return self.create(
            WorkItem(
                title="Evaluate documentation consistency",
                description="Inspect five architecture documents and produce a checksum-indexed report for independent review.",
                assigned_agent=worker,
                allowed_tools=("read_file", "write_artifact", "verify_docs"),
                parent_work_item_id=parent,
                **({"mission_id": previous.mission_id} if previous else {}),
            )
        )
