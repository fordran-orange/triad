"""Three sequential provider turns. Core owns file application and merge authority."""

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import Field
from trading_core.contracts import FileChange
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.product_changes import ProductGit, active_policy, check_candidate, product_path
from trading_core.work import Record, now

ORDER = ("CODEX", "CLAUDE", "GROK")
REVIEWERS = {"CODEX": "CLAUDE", "CLAUDE": "GROK", "GROK": "CODEX"}


class Proposal(Record):
    title: str = Field(min_length=1, max_length=160)
    problem: str = Field(min_length=1)
    change: str = Field(min_length=1)
    files: tuple[str, ...] = Field(min_length=1)
    acceptance: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...] = Field(min_length=1)


class Patch(Record):
    files: tuple[FileChange, ...] = Field(min_length=1)


class SequentialCycle:
    def __init__(self, service):
        self.s = service
        self.root = service.git.root
        self.policy = active_policy(service.canonical)

    def guard(self, mission):
        cycle = self.s.daily.current(mission)
        self.s.ledger.guard(work_id=cycle["parent_work_item_id"], epoch=cycle["control_epoch"])
        if active_policy(self.s.canonical)["id"] != self.policy["id"]:
            raise PermissionError("Sequential execution policy changed")

    def inventory(self):
        names = self.s.git.git("ls-files").splitlines()
        permitted = []
        for path in names:
            try:
                product_path(path)
            except PermissionError:
                continue
            ProductGit((path,), root=self.root).path(self.root, path)
            permitted.append(path)
        return permitted

    def approval(self, mission, agent, proposal, identifier):
        self.guard(mission)
        row = self.s.canonical.get(identifier)
        expected = hashlib.sha256(proposal.model_dump_json().encode()).hexdigest()
        if (
            row["kind"] != "ProductTurnApproval"
            or row["owner"] != "triad"
            or row["cycle_id"] != mission
            or row["builder"] != agent
            or row["reviewer"] != REVIEWERS[agent]
            or row["policy_id"] != self.policy["id"]
            or row["proposal_sha256"] != expected
            or Proposal.model_validate(row["proposal"]) != proposal
        ):
            raise PermissionError("Proposal differs from its independent approval")
        return row

    def test_snapshot(self, git, metadata):
        files = {}
        for p in git.git("ls-files", cwd=metadata["worktree"]).splitlines():
            try:
                product_path(p)
            except PermissionError:
                continue
            target = ProductGit((p,), root=self.root).path(metadata["worktree"], p)
            files[p] = target.read_text(encoding="utf-8")
        return files

    def call(self, mission, agent, objective, context, schema=None, paths=()):
        self.guard(mission)
        objective += (
            " Token guidance: aim for 8192 reasoning and 6144 output tokens; these are targets, "
            "not cutoffs. Use what is needed for a complete correct result. "
            "Do not execute commands or claim host tests. Return no files_changed; proposed code is data in analysis_artifacts."
        )
        return self.s.call(
            mission,
            agent,
            "REVIEW",
            objective,
            context,
            schema=schema,
            paths=paths,
            parent=self.s.daily.current(mission)["parent_work_item_id"],
        )

    def readiness(self, mission):
        from trading_core.intelligence.capabilities import Capabilities

        # Only selected development transports are refreshed. Local maintenance
        # availability cannot hold a frontier development cycle hostage.
        from trading_core.providers.recovery import recover

        control = self.s.routing.control
        for agent in ORDER:
            tid = control.policy(agent).preferred_transport
            with control.ledger.store.lease("provider-auth-" + tid):
                control.refresh(tid)
                recover(control, tid)
        versions = Capabilities(self.s.routing.records).current()
        checks = []
        for agent in ORDER:
            work, requirements = self.s.call(
                mission, agent, "REVIEW", "Sequential development readiness", {}, _preview=True
            )
            value = self.s.routing._candidate(
                self.s.routing.agents.get(agent), work, requirements, versions
            )
            checks.append(
                {"agent": agent, "ready": value["eligible"], "reasons": value["exclusions"]}
            )
        self.s.record(
            "DailyReadiness",
            mission,
            checks=checks,
            program="three_sequential_turns",
            maintenance_required=False,
        )
        if any(not c["ready"] for c in checks):
            raise PermissionError("Development readiness: " + json.dumps(checks))

    def propose(self, mission, agent):
        baseline = self.s.git.clean_baseline()
        inventory = self.inventory()
        sources = tuple(
            p
            for p in inventory
            if p.startswith("app/products/triad/")
            and ProductGit((p,), root=self.root).path(self.root, p).stat().st_size < 12000
        )
        _, _, proposal, _ = self.call(
            mission,
            agent,
            "Inspect the current product and propose one useful improvement of your choice. You may change product UI, "
            "backend modules, data-processing logic, documentation and product tests. Governance, orchestration and other products are protected. "
            "Choose exact existing/new product file paths. The following turn sees the prior deployed change. "
            "Return exactly one Proposal JSON string in analysis_artifacts using the supplied schema.",
            {
                "inventory": inventory,
                "schema": Proposal.model_json_schema(),
                "protected": "Core, governance, Triad scheduling/cycles/development machinery, credentials, Aegis",
                "previous_turns": self.s.rows("ProductTurn", mission),
            },
            Proposal,
            sources,
        )
        for p in proposal.files:
            product_path(p)
        if len({p.casefold() for p in proposal.files}) != len(proposal.files):
            raise PermissionError("Duplicate or ambiguous proposed files")
        self.s.record(
            "ProductProposal", mission, proposer=agent, proposal=proposal.model_dump(mode="json")
        )
        self.s.transition(mission, "SELECTING", ["Independent proposal review"])
        _, review, _, usage = self.call(
            mission,
            REVIEWERS[agent],
            "Independently review this proposal for usefulness, protected boundaries, feasibility and acceptance criteria. "
            "Return review_decision APPROVE/REQUEST_CHANGES/REJECT with concrete findings. Approve only a useful testable product change.",
            {
                "proposal": proposal.model_dump(mode="json"),
                "inventory": inventory,
                "base_commit": baseline,
                "sources": {
                    p: ProductGit(proposal.files, root=self.root)
                    .path(self.root, p)
                    .read_text(encoding="utf-8")
                    for p in proposal.files
                    if (self.root / p).is_file()
                },
            },
        )
        if review.review_decision != "APPROVE":
            raise PermissionError("Proposal not approved: " + review.summary)
        if self.s.git.clean_baseline() != baseline:
            raise PermissionError("Source changed during proposal review")
        approval = self.s.canonical.append(
            "ProductTurnApproval",
            {
                "cycle_id": mission,
                "builder": agent,
                "reviewer": REVIEWERS[agent],
                "proposal": proposal.model_dump(mode="json"),
                "proposal_sha256": hashlib.sha256(proposal.model_dump_json().encode()).hexdigest(),
                "run_id": usage["run_id"],
                "policy_id": self.policy["id"],
                "base_commit": baseline,
            },
            owner="triad",
        )
        return proposal, approval

    def build(self, mission, agent, proposal, approval):
        approved = self.approval(mission, agent, proposal, approval)
        self.guard(mission)
        git = ProductGit(proposal.files, root=self.root)
        if git.clean_baseline() != approved["base_commit"]:
            raise PermissionError("Baseline changed after proposal review")
        sources = {
            p: git.path(self.root, p).read_text(encoding="utf-8")
            for p in proposal.files
            if (self.root / p).is_file()
        }
        work, _result, patch, usage = self.call(
            mission,
            agent,
            "Implement your independently approved proposal. Return exactly one Patch JSON string in analysis_artifacts. "
            "Each entry contains path, complete replacement content, and the supplied original_sha256 (null for a new file). "
            "Core applies this data in an isolated worktree; you have no host write authority. Include meaningful product unit tests "
            "under tests/products/triad when behavior changes. Use Python unittest for executable tests. Never change protected orchestration. "
            "Do not substitute documentation for the requested implementation.",
            {
                "proposal": proposal.model_dump(mode="json"),
                "schema": Patch.model_json_schema(),
                "sources": sources,
                "original_sha256": {
                    p: hashlib.sha256(git.path(self.root, p).read_bytes()).hexdigest()
                    if (self.root / p).is_file()
                    else None
                    for p in proposal.files
                },
            },
            Patch,
        )
        self.s.ledger.reserve(
            agent,
            work.work_item_id,
            improvement=True,
            day=datetime.fromisoformat(self.s.daily.current(mission)["created_at"])
            .astimezone(ZoneInfo(self.s.daily.schedule()["timezone"]))
            .date()
            .isoformat(),
            billing_source="SUBSCRIPTION",
        )
        metadata = git.isolate(work.work_item_id, agent)
        self.s.record(
            "ProductBuildCheckpoint",
            mission,
            work_item_id=work.work_item_id,
            git=metadata,
            phase="ISOLATED",
        )
        self.s.check_ownership(patch.files)
        git.apply(metadata, patch.files)
        git.commit(metadata, agent)
        checks = git.verify(metadata)
        proof = check_candidate(
            self.test_snapshot(git, metadata),
            lambda: self.guard(mission),
            self.policy["test_image"],
        )
        checks["checks"].append(
            "Offline syntax validation; executed unit tests: " + str(proof["executed_tests"])
        )
        checks["test_result"] = proof
        check_id = self.s.canonical.append(
            "EngineeringTestRun",
            {**proof, "work_item_id": work.work_item_id, "commit": metadata["change_commit"]},
            owner="triad",
        )
        checks["test_record_id"] = check_id
        implementation = ImplementationRun(
            owner="triad",
            builder=agent,
            work_item_id=work.work_item_id,
            provider=usage["provider"],
            model=usage["actual_model"],
            transport=usage["transport"],
            base_commit=metadata["base_commit"],
            change_commit=metadata["change_commit"],
            files=tuple(checks["files"]),
            tests=tuple(checks["checks"]),
            evidence=(
                "run:" + usage["run_id"],
                "proposal-approval:" + approval,
                "offline-check:" + check_id,
            ),
        )
        self.s.quality.implementation(implementation)
        build = {
            "implementation_id": implementation.implementation_run_id,
            "work_item_id": work.work_item_id,
            "builder": agent,
            "git": metadata,
            "checks": checks,
            "usage": usage,
            "approval": approval,
        }
        self.s.record("ProductBuild", mission, **build)
        return git, build

    def qa(self, mission, agent, proposal, git, build):
        before = git.verify(build["git"])
        if any(before[k] != build["checks"][k] for k in ("files", "hashes", "diff")):
            raise PermissionError("Candidate changed before independent QA")
        repeated = check_candidate(
            self.test_snapshot(git, build["git"]),
            lambda: self.guard(mission),
            self.policy["test_image"],
        )
        repeated_id = self.s.canonical.append(
            "EngineeringTestRun",
            {
                **repeated,
                "work_item_id": build["work_item_id"],
                "commit": build["git"]["change_commit"],
            },
            owner="triad",
        )
        work, result, _, usage = self.call(
            mission,
            REVIEWERS[agent],
            "Independently review this exact candidate code and diff against the approved proposal and test evidence. "
            "Check behavior, failure cases, regressions, product isolation and any attempt to bypass governance through product code. "
            "Reject unsafe imports/access to private storage, orchestration, credentials or permission changes. "
            "Require meaningful tests for behavior changes; syntax alone is insufficient. Return review_decision and findings; no claimed tool execution.",
            {
                "proposal": proposal.model_dump(mode="json"),
                "exact_commit": build["git"]["change_commit"],
                "checks": build["checks"],
                "repeated_test_result": repeated,
                "repeated_test_record_id": repeated_id,
            },
        )
        decision = {
            "APPROVE": "PASS_WITH_OBSERVATIONS" if result.findings else "PASS",
            "REQUEST_CHANGES": "CHANGES_REQUIRED",
            "REJECT": "REJECT",
        }.get(result.review_decision, "BLOCKED")
        qa = QARun(
            implementation_run_id=build["implementation_id"],
            qa_work_item_id=work.work_item_id,
            qa_agent=REVIEWERS[agent],
            qa_provider=usage["provider"],
            qa_model=usage["actual_model"],
            reviewed_commit=build["git"]["change_commit"],
            agent_capabilities_used=("structured_output", "document_analysis"),
            findings=result.findings,
            tests_repeated=tuple(build["checks"]["checks"]),
            evidence=(
                "run:" + usage["run_id"],
                "offline-check:" + build["checks"]["test_record_id"],
                "offline-check:" + repeated_id,
            ),
            decision=decision,
            execution_mode="REAL_PROVIDER",
        )
        self.s.quality.review(qa)
        self.s.record(
            "ProductQA",
            mission,
            implementation_id=build["implementation_id"],
            reviewer=qa.qa_agent,
            decision=decision,
            usage=usage,
        )
        self.s.quality.require_pass(build["implementation_id"], build["git"]["change_commit"])
        return qa

    def merge(self, mission, agent, git, build, qa):
        metadata = build["git"]
        approved = self.s.canonical.get(build["approval"])
        self.approval(
            mission, agent, Proposal.model_validate(approved["proposal"]), build["approval"]
        )
        if (
            tuple(approved["proposal"]["files"]) != git.approved_files
            or metadata["base_commit"] != approved["base_commit"]
        ):
            raise PermissionError("Build differs from the approved proposal manifest")
        self.guard(mission)
        self.s.quality.require_pass(build["implementation_id"], metadata["change_commit"])
        git.review_commit(metadata, qa.qa_run_id, qa.decision)
        with self.s.ledger.store.lease("triad-product-development"), self.s.ledger.gate():
            self.guard(mission)
            current = self.s.quality.require_pass(
                build["implementation_id"], metadata["change_commit"]
            )
            if current["id"] != qa.qa_run_id:
                raise PermissionError("Independent QA changed before merge")
            self.s.check_ownership(
                [type("PathRecord", (), {"path": p}) for p in build["checks"]["files"]]
            )
            check = git.verify(metadata)
            if any(check[k] != build["checks"][k] for k in ("files", "hashes", "diff")):
                raise PermissionError("Candidate changed after review")
            git.merge(
                metadata,
                {
                    "decision": "APPROVE",
                    "reviewer": qa.qa_agent,
                    "worker": agent,
                    "review_id": qa.qa_run_id,
                    "change_commit": metadata["change_commit"],
                },
                None,
            )
            with self.s.host.store.connect() as conn:
                for path in check["files"]:
                    conn.execute(
                        "INSERT INTO core.artifact_owners(path,owner,record_id) VALUES (%s,'triad',%s) "
                        "ON CONFLICT(path) DO UPDATE SET record_id=EXCLUDED.record_id WHERE core.artifact_owners.owner='triad'",
                        (path, build["implementation_id"]),
                    )
        self.s.record(
            "ProductMerge",
            mission,
            implementation_id=build["implementation_id"],
            qa_id=qa.qa_run_id,
            git=metadata,
            files=check["files"],
            hashes=check["hashes"],
            status="MERGED",
        )
        metadata["program"] = "three_sequential_turns"
        return metadata

    def run(
        self, *, scheduled=False, cycle_id=None, verify=None, expected_epoch=None, schedule_id=None
    ):
        from contextlib import nullcontext

        if verify is None:
            raise PermissionError("Trusted post-deployment verification required")
        with self.s.host.store.lease("triad-daily-product-execution"):
            with (
                self.s.host.store.lease("triad-daily-schedule-slot") if scheduled else nullcontext()
            ):
                cycle = self.s.daily.create(
                    scheduled=scheduled,
                    cycle_id=cycle_id,
                    expected_epoch=expected_epoch,
                    schedule_id=schedule_id,
                )
            mission = cycle.cycle_id
            self.s.canonical.append(
                "SequentialDailyProgram",
                {
                    "cycle_id": mission,
                    "policy_id": self.policy["id"],
                    "parent_work_item_id": cycle.parent_work_item_id,
                    "control_epoch": cycle.control_epoch,
                    "order": list(ORDER),
                },
                owner="triad",
            )
            try:
                self.readiness(mission)
                for agent in ORDER:
                    self.s.record(
                        "ProductTurnStarted", mission, agent=agent, reviewer=REVIEWERS[agent]
                    )
                    self.s.transition(
                        mission, "INSPECTING", [agent + " turn; fresh deployed baseline"]
                    )
                    proposal, approval = self.propose(mission, agent)
                    self.s.transition(
                        mission,
                        "BUILDING",
                        [approval],
                        selected_proposal=proposal.model_dump(mode="json"),
                    )
                    git, build = self.build(mission, agent, proposal, approval)
                    self.s.transition(mission, "AWAITING_QA", [build["implementation_id"]])
                    qa = self.qa(mission, agent, proposal, git, build)
                    self.s.transition(mission, "MERGING", [qa.qa_run_id])
                    merged = self.merge(mission, agent, git, build, qa)
                    self.s.transition(
                        mission,
                        "VERIFYING",
                        [merged["merge_commit"]],
                        merge_commit=merged["merge_commit"],
                    )
                    with self.s.ledger.store.lease("triad-product-development"):
                        self.guard(mission)
                        verification = verify(
                            {
                                **merged,
                                "_deployment_guard": lambda: self.guard(mission),
                                "_deployment_gate": self.s.ledger.gate,
                            }
                        )
                    if verification.get("rolled_back"):
                        self.s.canonical.append(
                            "ProductRollback",
                            {
                                "mission_id": mission,
                                "implementation_id": build["implementation_id"],
                                "merge_commit": merged["merge_commit"],
                                **verification,
                            },
                            owner="triad",
                        )
                    self.s.canonical.append(
                        "DailyVerification",
                        {
                            "cycle_id": mission,
                            "agent": agent,
                            "merge_commit": merged["merge_commit"],
                            **verification,
                            "verified_at": now().isoformat(),
                        },
                        owner="triad",
                    )
                    if verification.get("status") != "PASS":
                        raise PermissionError(
                            "Post-deployment verification failed; further turns stopped"
                        )
                    self.s.canonical.append(
                        "ProductTurn",
                        {
                            "mission_id": mission,
                            "agent": agent,
                            "reviewer": REVIEWERS[agent],
                            "status": "COMPLETED",
                            "implementation_id": build["implementation_id"],
                            "qa_id": qa.qa_run_id,
                            "merge_commit": merged["merge_commit"],
                        },
                        owner="triad",
                    )
                self.s.transition(
                    mission, "DEBRIEFING", ["All three independent turns deployed and checked"]
                )
                corrections = ()
                for _ in range(3):
                    result = self.s.debrief(mission, corrections)
                    corrections = result.get("required_changes", ())
                    if result["decision"] in {"PASS", "PASS_WITH_OBSERVATIONS"}:
                        break
                else:
                    raise PermissionError("Daily debrief did not pass independent review")
                self.s.transition(
                    mission, "COMPLETED", ["Three sequential turns and reviewed debrief complete"]
                )
                return self.s.daily.current(mission)
            except Exception as exc:
                self.s.transition(
                    mission,
                    "BLOCKED",
                    [type(exc).__name__],
                    failures=({"code": type(exc).__name__, "message": str(exc)[:500]},),
                )
                raise
