"""Product-neutral execution lifecycle composed from Core services."""
from datetime import UTC, datetime

from triad.brain import Brain
from triad.day3.adapters import Runtime
from triad.day3.changes import GitChanges
from triad.day3.ledger import Ledger
from triad.orchestrator import Orchestrator
from triad.work import Handoff, State, WorkResult


class ExecutionServices:
    def __init__(self, store=None, git=None, day=None, registry=None):
        self.host = Orchestrator(store=store, registry=registry)
        self.ledger = Ledger(self.host.store)
        self.runtime = Runtime(self.ledger)
        self.git = git or GitChanges()
        self.day = day or datetime.now(UTC).date().isoformat()

    def initialize(self):
        self.host.initialize()
        self.ledger.initialize()
        Brain(self.host.store).initialize()

    def start_work(self, work, epoch=None):
        authority = self.ledger.guard(work.assigned_agent, work.work_item_id, epoch)["epoch"]
        work = self.host.advance(work, State.VALIDATING, "Host policy evaluation")
        policy = self.host.control.evaluate(work)
        if policy.decision not in {"ALLOW", "REQUIRE_REVIEW"}:
            self.host.advance(work, State.BLOCKED, "Host policy blocked", records=(policy,))
            raise PermissionError("Work policy denied")
        work = self.host.advance(
            work, State.APPROVED, "Bounded development assignment approved", records=(policy,)
        )
        work = self.host.advance(work, State.ASSIGNED, "Assigned bounded work")
        work = self.host.advance(work, State.IN_PROGRESS, "Host runtime started")
        self.ledger.put(
            "RunAuthority",
            {"epoch": authority},
            identifier="authority-" + work.work_item_id,
            work_id=work.work_item_id,
        )
        self.ledger.event("agent_started", work.work_item_id, agent=work.assigned_agent)
        return work, policy

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
            actions=("Provider proposed structured changes; host applied approved files",)
            if checks.get("files")
            else ("Validated structured provider output; no host files changed",),
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
