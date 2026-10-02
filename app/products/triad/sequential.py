"""Three sequential provider turns. Core owns file application and merge authority."""

import hashlib
import json
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_serializer, model_validator
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.product_changes import (
    AcceptanceAssessment,
    ProductFileChange,
    ProductGit,
    RequiredCheck,
    acceptance_problems,
    active_policy,
    check_candidate,
    product_path,
)
from trading_core.work import Record, now, uid

from products.triad.development import ProductResponseFormatError
from products.triad.sequential_planning import (
    HISTORICAL,
    CurrentValuePlan,
    ValuePlan,
    core_context,
    planning_context,
    token_guidance,
)

ORDER = ("CODEX", "CLAUDE", "GROK")
REVIEWERS = {"CODEX": "CLAUDE", "CLAUDE": "GROK", "GROK": "CODEX"}


class Proposal(Record):
    outcome: Literal["CHANGE", "NO_CHANGE"] = "CHANGE"
    title: str = Field(min_length=1, max_length=160)
    problem: str = Field(min_length=1)
    change: str = Field(min_length=1)
    files: tuple[str, ...]
    acceptance: tuple[RequiredCheck, ...]
    evidence: tuple[str, ...] = Field(min_length=1)
    value_plan: ValuePlan | None = None  # Retained historical proposals remain readable.

    @model_serializer(mode="wrap")
    def retain_historical_shape(self, handler):
        data = handler(self)
        if self.value_plan is None:
            data.pop("value_plan", None)
        return data

    @model_validator(mode="after")
    def coherent_outcome(self):
        if self.outcome == "CHANGE" and (not self.files or not self.acceptance):
            raise ValueError("A change requires files and acceptance checks")
        if self.outcome == "NO_CHANGE" and (self.files or self.acceptance):
            raise ValueError("No-change proposals cannot include edits or pending checks")
        if not all(v.strip() for v in (self.problem, self.change, *self.evidence)):
            raise ValueError("A proposal requires substantive reasoning and evidence")
        return self


class Patch(Record):
    files: tuple[ProductFileChange, ...] = Field(min_length=1)


class CurrentProposal(Proposal):
    """New plans require value reasoning; historical evidence keeps its old schema."""

    value_plan: CurrentValuePlan


class SequentialCycle:
    def __init__(self, service):
        self.s = service
        self.root = service.git.root
        self.policy = active_policy(service.canonical)
        if self.policy.get("acceptance_contract") != "required-checks-v1":
            raise PermissionError("Reviewed required-check acceptance policy must be activated")

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
        objective += token_guidance(agent) + (
            "Do not execute commands or claim host tests. Top-level files_changed must be [] and proposal must be null; "
            "the requested Proposal or Patch is data inside analysis_artifacts, not the outer proposal field."
        )
        feedback = []
        recovery = None
        original_context, original_objective, original_paths = context, objective, paths
        for attempt in range(1, 4):
            self.guard(mission)
            try:
                completed = self.s.call(
                    mission,
                    agent,
                    "REVIEW",
                    objective,
                    {
                        **context,
                        "evidence_delivery": "files-v1",
                        "response_format_feedback": feedback,
                        "response_envelope": {
                            "files_changed": [],
                            "proposal": None,
                            "analysis_artifacts": (
                                "Exactly one JSON object for the requested schema; never encode it as a string"
                                if schema
                                else "Optional supporting artifacts; provide review_decision and findings"
                            ),
                        },
                    },
                    schema=schema,
                    paths=paths,
                    parent=self.s.daily.current(mission)["parent_work_item_id"],
                )
                if recovery:
                    self.s.record(
                        "ProductResponseRecovery",
                        mission,
                        agent=agent,
                        previous_run_id=recovery.get("run_id"),
                        run_id=completed[3].get("run_id"),
                        recovery_mode=recovery["mode"],
                        usage=completed[3],
                    )
                return completed
            except (PermissionError, ValueError) as exc:
                if not isinstance(exc, ProductResponseFormatError) and str(exc) not in {
                    "Read-only product inspection cannot change files",
                    "Expected exactly one structured product artifact",
                }:
                    raise
                artifact = getattr(exc, "artifact", None)

                def unique(pairs):
                    value = {}
                    for key, item in pairs:
                        if key in value:
                            raise ValueError("Ambiguous duplicate JSON key")
                        value[key] = item
                    return value

                def invalid_constant(value):
                    raise ValueError("Nonstandard JSON constant: " + value)

                try:
                    if isinstance(artifact, dict):
                        json.dumps(artifact, allow_nan=False)
                        complete = True
                    elif isinstance(artifact, str):
                        complete = isinstance(
                            json.loads(
                                artifact, object_pairs_hook=unique, parse_constant=invalid_constant
                            ),
                            dict,
                        )
                    else:
                        complete = False
                except (ValueError, TypeError):
                    complete = False
                recovery = {
                    "run_id": getattr(exc, "run_id", None),
                    "mode": "FORMAT_REPAIR" if complete else "FRESH_GENERATION",
                }
                self.s.record(
                    "ProductResponseRetry",
                    mission,
                    agent=agent,
                    attempt=attempt,
                    reason=str(exc),
                    failure_category="SCHEMA" if complete else "INCOMPLETE_OR_INVALID_JSON",
                    previous_run_id=recovery["run_id"],
                    recovery_mode=recovery["mode"],
                    usage=getattr(exc, "usage", None),
                )
                if complete:
                    context = {
                        "original_artifact": artifact,
                        "validation_errors": str(exc),
                        "schema": schema.model_json_schema() if schema else {},
                        "previous_run_id": recovery["run_id"],
                    }
                    objective = (
                        "Repair only the response format of the supplied complete artifact. "
                        "Preserve its substantive proposal, scope, evidence and conclusions. "
                        "Do not repeat planning or claim new source inspection. If correction needs "
                        "missing facts or substantive decisions, return BLOCKED instead of inventing them. "
                        "Return one structured JSON object in analysis_artifacts; files_changed stays empty, "
                        "proposal stays null. The result still requires normal validation and independent review."
                    )
                    paths = ()
                else:
                    # Never fabricate omitted JSON content. A fresh attempt retains the original evidence.
                    context, objective, paths = original_context, original_objective, original_paths

                feedback.append(
                    "Your previous response used an invalid envelope: "
                    + str(exc)
                    + ". Set top-level files_changed to [] and proposal to null. "
                    "Place the requested Proposal/Patch/AcceptanceAssessment JSON only in "
                    "analysis_artifacts as one JSON object. Match the supplied schema exactly: no extra fields. "
                    "Fix the validation locations listed above. Do not claim host writes."
                )
                if attempt == 3:
                    raise

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
        # Explicit recovery must retain the previous review's corrections.
        feedback = [
            {k: row[k] for k in ("proposal", "decision", "summary", "findings") if k in row}
            for row in self.s.rows("ProductProposalReview", mission)
            if row.get("proposer") == agent and row.get("decision") in {"REQUEST_CHANGES", "REJECT"}
        ][-3:]
        for attempt in range(1, 4):
            proposal, approval, review = self.proposal_attempt(mission, agent, feedback, attempt)
            if approval:
                return proposal, approval
            feedback.append({"proposal": proposal.model_dump(mode="json"), **review})
            if review["decision"] not in {"REQUEST_CHANGES", "REJECT"}:
                raise PermissionError("Invalid proposal review: " + review["summary"])
        raise PermissionError("Proposal revision attempts exhausted: " + feedback[-1]["summary"])

    def proposal_attempt(self, mission, agent, feedback, attempt):
        from trading_core.intake import Intake

        baseline = self.s.git.clean_baseline()
        inventory = self.inventory()
        strategy = planning_context(self.s, mission, baseline)
        sources = tuple(p for p in inventory if p.startswith("app/products/triad/"))
        additional_sources = {}
        for path in inventory:
            if path in sources or path in HISTORICAL:
                continue
            target = ProductGit((path,), root=self.root).path(self.root, path)
            additional_sources[path] = target.read_text(encoding="utf-8")
        author_work, _, proposal, author_usage = self.call(
            mission,
            agent,
            "Choose your perceived highest-value improvement toward Triad's trading-product mission and implement it this turn. "
            "Look beyond existing page polish: you may create new tools, spaces and capabilities using product UI, "
            "backend modules, data-processing logic, documentation and tests. Governance, orchestration and other products are protected. "
            "Supply value_plan: your initiative, concrete user outcome, why this is the highest-value feasible change, "
            "mission_contribution (the capability gap this increment closes), major_gaps (your evidence-based "
            "assessment of the largest remaining gaps in the complete application, not a fixed feature checklist), "
            "at least two meaningful alternatives with reasons not selected, next steps, and dependencies or blockers. "
            "Consult current Core interfaces and prior-cycle outcomes. Continue worthwhile prior work or explain changing direction. "
            "NO_CHANGE is valid only with evidence explaining why the compared meaningful alternatives cannot responsibly "
            "advance now; a finished checklist or lack of existing feature files is not sufficient. Keep files and acceptance "
            "empty for NO_CHANGE. Never invent low-value work to meet a quota. Historical grants are not current restrictions. "
            "Choose exact existing/new product file paths. The following turn sees the prior deployed change. "
            "Every acceptance criterion must name its verification method and unique check_id. Available premerge methods are "
            "SOURCE_REVIEW (exact source/diff inspection; no executed browser or interaction claims) and PYTHON_UNIT_TEST "
            "(offline Python unittest with installed project dependencies). Browser rendering/keyboard/viewport checks are NOT available. "
            "Do not require unsupported checks or pretend source review proves browser behavior. For behavioral changes include meaningful "
            "unit tests and their tests/products/triad file paths in the initial manifest. "
            "Address all prior review feedback when supplied. Read-only integration source establishes mount prefixes; "
            "it is context, never permission to change protected code. "
            "A rejected candidate is not approved: inspect the findings and propose a different useful candidate "
            "or an evidence-supported NO_CHANGE for a fresh independent review. Inspect existing tests before proposing new ones. "
            "Return exactly one Proposal JSON object in analysis_artifacts using the supplied schema.",
            {
                "product_planning": strategy,
                "inventory": inventory,
                "additional_product_sources_read_only": additional_sources,
                "base_commit": baseline,
                "optional_advisory_ideas": Intake(self.s.records).advisory("triad"),
                "schema": CurrentProposal.model_json_schema(),
                "protected": "Core, governance, Triad scheduling/cycles/development machinery, credentials, Aegis",
                "previous_turns": self.s.rows("ProductTurn", mission),
                "review_feedback": feedback,
                "integration_source_read_only": self.s.git.git(
                    "show", baseline + ":app/products/triad/server.py"
                ),
            },
            CurrentProposal,
            sources,
        )
        proposal = Proposal.model_validate(proposal.model_dump())
        self.s.record(
            "ProductPlanningContext",
            mission,
            proposer=agent,
            base_commit=baseline,
            context_sha256=hashlib.sha256(
                json.dumps(strategy, sort_keys=True).encode()
            ).hexdigest(),
            history_ids={k: [r["id"] for r in rows] for k, rows in strategy["history"].items()},
            core_source_revision=strategy["shared_core"]["source_revision"],
            mission_statement=strategy["mission"],
        )
        for p in proposal.files:
            product_path(p)
        if len({p.casefold() for p in proposal.files}) != len(proposal.files):
            raise PermissionError("Duplicate or ambiguous proposed files")
        if len({c.check_id for c in proposal.acceptance}) != len(proposal.acceptance):
            raise PermissionError("Acceptance check IDs must be unique")
        if any(c.method == "PYTHON_UNIT_TEST" for c in proposal.acceptance) and not any(
            p.startswith("tests/products/triad/") and p.endswith(".py") for p in proposal.files
        ):
            raise PermissionError("Required unit tests must be in the approved manifest")
        self.s.record(
            "ProductProposal",
            mission,
            proposer=agent,
            proposal=proposal.model_dump(mode="json"),
            attempt=attempt,
        )
        if attempt == 1:
            self.s.transition(mission, "SELECTING", ["Independent proposal review"])
        review_work, review, _, usage = self.call(
            mission,
            REVIEWERS[agent],
            "Independently review product value as well as correctness, protected boundaries, feasibility and acceptance. "
            "Evaluate the author's highest-value reasoning against alternatives, prior outcomes and current Core interfaces. "
            "Assess mission_contribution and major_gaps against the complete application mission. An initiative may "
            "span multiple turns or days; require a useful tested increment, not completion of the entire initiative today. "
            "Challenge cosmetic churn and unsupported NO_CHANGE: a finished shell is not a finished trading product. "
            "Do not require a large diff or choose the author's roadmap for them; small high-impact fixes are valid. "
            "Return APPROVE/REQUEST_CHANGES/REJECT with concrete findings, including the value assessment. "
            "Do not apply historical document-only grants or grant new authority.",
            {
                "product_planning": strategy,
                "proposal": proposal.model_dump(mode="json"),
                "inventory": inventory,
                "base_commit": baseline,
                "review_feedback": feedback,
                "integration_source_read_only": self.s.git.git(
                    "show", baseline + ":app/products/triad/server.py"
                ),
                "available_checks": {
                    "SOURCE_REVIEW": "Exact source/diff inspection only; cannot establish rendered, responsive or keyboard behavior",
                    "PYTHON_UNIT_TEST": "Offline Python unittest with pinned project dependencies; include test paths in manifest",
                },
                "sources": {
                    p: ProductGit(tuple(set(inventory) | set(proposal.files)), root=self.root)
                    .path(self.root, p)
                    .read_text(encoding="utf-8")
                    for p in sorted((set(inventory) - HISTORICAL) | set(proposal.files))
                    if (self.root / p).is_file()
                },
            },
        )
        assessment = {
            "decision": review.review_decision,
            "summary": review.summary,
            "findings": list(review.findings),
        }
        self.s.record(
            "ProductProposalReview",
            mission,
            proposer=agent,
            reviewer=REVIEWERS[agent],
            attempt=attempt,
            proposal=proposal.model_dump(mode="json"),
            run_id=usage["run_id"],
            **assessment,
        )
        if self.s.git.clean_baseline() != baseline:
            raise PermissionError("Source changed during proposal review")
        if review.review_decision != "APPROVE":
            return proposal, None, assessment
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
                "author_work_item_id": author_work.work_item_id,
                "author_run_id": author_usage["run_id"],
                "review_work_item_id": review_work.work_item_id,
            },
            owner="triad",
        )
        return proposal, approval, assessment

    def no_change(self, mission, agent, proposal, approval):
        from trading_core.product_deployment import health

        row = self.approval(mission, agent, proposal, approval)
        baseline = row["base_commit"]
        with self.s.ledger.store.lease("triad-product-development"):
            self.guard(mission)
            if self.s.git.clean_baseline() != baseline:
                raise PermissionError("No-change review baseline changed")
            verification = health(baseline)
            if self.s.git.clean_baseline() != baseline:
                raise PermissionError("Source changed during no-change verification")
            proof = self.s.canonical.append(
                "ProductNoChange",
                {
                    "cycle_id": mission,
                    "agent": agent,
                    "reviewer": REVIEWERS[agent],
                    "approval_id": approval,
                    "baseline": baseline,
                    "verified_at": now().isoformat(),
                    "health": verification,
                },
                owner="triad",
            )
            self.s.canonical.append(
                "ProductTurn",
                {
                    "mission_id": mission,
                    "agent": agent,
                    "reviewer": REVIEWERS[agent],
                    "status": "COMPLETED",
                    "outcome": "NO_CHANGE",
                    "no_change_id": proof,
                    "verified_revision": baseline,
                },
                owner="triad",
            )
        self.s.transition(
            mission,
            "VERIFYING",
            [proof],
            verified_revision=baseline,
            selected_proposal=proposal.model_dump(mode="json"),
        )

    def implementation_call(self, mission, agent, objective, context, schema, *, approval):
        from trading_core.product_workspace_grant import PROFILE

        if self.policy.get("workspace_profile") != PROFILE:
            return self.call(mission, agent, objective, context, schema)
        self.guard(mission)
        paths = tuple(sorted(set(self.inventory()) | set(context["proposal"]["files"])))
        return self.s.call(
            mission,
            agent,
            "IMPLEMENT",
            "Implement the independently approved product proposal using the supplied workspace tools. "
            "You can inspect the complete supplied product snapshot and edit, create, delete or rename product files. "
            "Day 6 baseline/backlog documents are historical evidence, not current grants or feature ceilings. "
            "Export changes only to the approved proposal's files. Use run_command for tools and tests inside "
            "the offline container; fix failures and retry as needed. Product commands have no host credentials or network. "
            "Use python -m unittest discover -s tests/products/triad for product tests where appropriate. "
            "Keep your final files_changed, analysis_artifacts, claims, actions_taken, commands_executed and tests_run empty; "
            "Core exports your actual edits and observed tool evidence. Never fabricate a patch in the response. "
            + token_guidance(agent),
            {
                "proposal": context["proposal"],
                "writable_files": context["proposal"]["files"],
                "inventory": paths,
                "shared_core": core_context(self.s.git, self.s.git.git("rev-parse", "HEAD")),
            },
            schema=schema,
            paths=paths,
            parent=self.s.daily.current(mission)["parent_work_item_id"],
            workspace_approval=approval,
            keep_open=True,
        )

    def build(self, mission, agent, proposal, approval):
        try:
            return self._build(mission, agent, proposal, approval)
        except Exception as exc:
            self.close_failed_work(mission, exc)
            raise

    def close_failed_work(self, mission, error):
        from trading_core.work import State

        parent = self.s.daily.current(mission)["parent_work_item_id"]
        for work in self.s.host.store.list_work(10000):
            if (
                work.owner == "triad"
                and work.mission_id == mission
                and work.parent_work_item_id == parent
                and work.work_type == "development"
                and work.status in {State.IN_PROGRESS, State.AWAITING_REVIEW}
            ):
                self.s.host.advance(
                    work,
                    State.FAILED,
                    "Product cycle failed; isolated candidate retained",
                    failure_reason=type(error).__name__,
                )
                self.s.record(
                    "ProductBuildFailure",
                    mission,
                    work_item_id=work.work_item_id,
                    error_class=type(error).__name__,
                    reason=str(error)[:500],
                )

    def _build(self, mission, agent, proposal, approval):
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
        work, _result, patch, usage = self.implementation_call(
            mission,
            agent,
            "Implement your independently approved proposal. Return exactly one Patch JSON object in analysis_artifacts. "
            "Each entry contains path, operation WRITE or DELETE, content, and the supplied original_sha256 (null for a new file). "
            "WRITE uses complete replacement content. DELETE requires null content and the exact original hash. "
            "To rename a file, delete the old path and write the new path; include both paths in the proposal. "
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
            approval=approval,
        )
        self.s.ledger.reserve(
            agent,
            work.work_item_id,
            improvement=True,
            day=self.improvement_day,
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
        if work.review_required:
            self.s.handoff(work, _result, metadata, checks, "REAL")
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

    def qa(self, mission, agent, proposal, git, build, *, retained=None):
        before = git.verify(build["git"])
        if any(before[k] != build["checks"][k] for k in ("files", "hashes", "diff")):
            raise PermissionError("Candidate changed before independent QA")
        if retained is None:
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
            work, result, assessment, usage = self.call(
                mission,
                REVIEWERS[agent],
                "Independently review this exact candidate code and diff against the approved proposal and test evidence. "
                "Check behavior, failure cases, regressions, product isolation and any attempt to bypass governance through product code. "
                "Reject unsafe imports/access to private storage, orchestration, credentials or permission changes. "
                "Require meaningful tests for behavior changes; syntax alone is insufficient. "
                "Return exactly one AcceptanceAssessment JSON in analysis_artifacts using the supplied schema, plus review_decision/findings. "
                "Assess EVERY required check separately; VERIFIED requires its supplied exact evidence ID, otherwise NOT_VERIFIED/BLOCKED. "
                "Copy IDs from allowed_evidence_ids verbatim; unit-test criteria must cite both raw test IDs. "
                "Source review cannot verify rendering, keyboard interaction or viewport behavior. Never APPROVE while any mandatory criterion "
                "is unmet or unverified. Do not claim tool execution; evaluate the supplied host test results.",
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "exact_commit": build["git"]["change_commit"],
                    "checks": build["checks"],
                    "repeated_test_result": repeated,
                    "repeated_test_record_id": repeated_id,
                    "assessment_schema": AcceptanceAssessment.model_json_schema(),
                    "source_evidence_id": "candidate:" + build["git"]["change_commit"],
                    "allowed_evidence_ids": [
                        "candidate:" + build["git"]["change_commit"],
                        build["checks"]["test_record_id"],
                        repeated_id,
                    ],
                },
                AcceptanceAssessment,
            )
        else:
            work, result, assessment, usage, repeated_id = retained
        proofs = {
            identifier: self.s.canonical.get(identifier)
            for identifier in (build["checks"]["test_record_id"], repeated_id)
        }
        from products.triad.sequential_citations import correct_citations

        work, result, assessment, usage = correct_citations(
            self, mission, agent, proposal, build, (work, result, assessment, usage), proofs
        )
        after = git.verify(build["git"])
        if any(after[k] != build["checks"][k] for k in ("files", "hashes", "diff")):
            raise PermissionError("Candidate changed during independent QA")
        decision = {
            "APPROVE": "PASS_WITH_OBSERVATIONS" if result.findings else "PASS",
            "REQUEST_CHANGES": "CHANGES_REQUIRED",
            "REJECT": "REJECT",
        }.get(result.review_decision, "BLOCKED")
        proofs = {
            identifier: self.s.canonical.get(identifier)
            for identifier in (build["checks"]["test_record_id"], repeated_id)
        }
        missing = acceptance_problems(
            [c.model_dump() for c in proposal.acceptance],
            assessment,
            build["git"]["change_commit"],
            proofs,
        )
        if missing:
            decision = "CHANGES_REQUIRED"
        qa_id, acceptance_id = uid(), uid()
        self.s.canonical.append(
            "ProductAcceptanceReview",
            {
                "cycle_id": mission,
                "implementation_id": build["implementation_id"],
                "commit": build["git"]["change_commit"],
                "qa_id": qa_id,
                "reviewer": REVIEWERS[agent],
                "run_id": usage["run_id"],
                "assessment": assessment.model_dump(mode="json"),
                "test_record_ids": list(proofs),
                "problems": list(missing),
                "required": [c.model_dump(mode="json") for c in proposal.acceptance],
                "approval_id": build["approval"],
            },
            owner="triad",
            identifier=acceptance_id,
        )
        qa = QARun(
            qa_run_id=qa_id,
            implementation_run_id=build["implementation_id"],
            qa_work_item_id=work.work_item_id,
            qa_agent=REVIEWERS[agent],
            qa_provider=usage["provider"],
            qa_model=usage["actual_model"],
            reviewed_commit=build["git"]["change_commit"],
            agent_capabilities_used=("structured_output", "document_analysis"),
            findings=tuple(result.findings) + missing,
            required_changes=missing,
            tests_repeated=tuple(build["checks"]["checks"]),
            evidence=(
                "run:" + usage["run_id"],
                "offline-check:" + build["checks"]["test_record_id"],
                "offline-check:" + repeated_id,
                "acceptance-review:" + acceptance_id,
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
        implementation_work = self.s.host.store.get(build["work_item_id"])
        if implementation_work.review_required:
            from trading_core.work import Review

            if decision == "BLOCKED":
                from trading_core.work import State

                self.s.host.advance(
                    implementation_work, State.BLOCKED, "Independent QA blocked implementation"
                )
            else:
                self.s.host.apply_review(
                    implementation_work,
                    Review(
                        work_item_id=implementation_work.work_item_id,
                        reviewer=REVIEWERS[agent],
                        decision="APPROVE"
                        if decision in {"PASS", "PASS_WITH_OBSERVATIONS"}
                        else "REJECT"
                        if decision == "REJECT"
                        else "REQUEST_CHANGES",
                        findings=tuple(result.findings) + missing,
                        severity="NONE",
                        evidence_checked=(
                            "qa:" + qa.qa_run_id,
                            "candidate:" + build["git"]["change_commit"],
                        ),
                        tests_repeated=tuple(build["checks"]["checks"]),
                        execution_mode="REAL",
                    ),
                )
        self.s.quality.require_pass(build["implementation_id"], build["git"]["change_commit"])
        return qa

    def require_acceptance(self, mission, build, qa):
        references = [
            e.removeprefix("acceptance-review:")
            for e in qa.evidence
            if e.startswith("acceptance-review:")
        ]
        if len(references) != 1:
            raise PermissionError("Exact independent acceptance evidence required")
        row = self.s.canonical.get(references[0])
        approved = self.s.canonical.get(build["approval"])
        if (
            row["kind"] != "ProductAcceptanceReview"
            or row["owner"] != "triad"
            or row["cycle_id"] != mission
            or row["implementation_id"] != build["implementation_id"]
            or row["commit"] != build["git"]["change_commit"]
            or row["qa_id"] != qa.qa_run_id
            or row["reviewer"] != qa.qa_agent
            or row["approval_id"] != build["approval"]
            or row["required"] != approved["proposal"]["acceptance"]
        ):
            raise PermissionError("Acceptance evidence differs from the exact reviewed candidate")
        proofs = {
            identifier: self.s.canonical.get(identifier) for identifier in row["test_record_ids"]
        }
        if len(proofs) != 2 or any(
            p["kind"] != "EngineeringTestRun"
            or p["owner"] != "triad"
            or p.get("commit") != row["commit"]
            or p.get("status") != "PASS"
            for p in proofs.values()
        ):
            raise PermissionError("Exact candidate test evidence is missing")
        missing = acceptance_problems(row["required"], row["assessment"], row["commit"], proofs)
        if missing:
            raise PermissionError("Mandatory acceptance checks unverified: " + "; ".join(missing))
        return row["id"]

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
        self.require_acceptance(mission, build, qa)
        self.s.quality.require_pass(build["implementation_id"], metadata["change_commit"])
        git.review_commit(metadata, qa.qa_run_id, qa.decision)
        with self.s.ledger.store.lease("triad-product-development"), self.s.ledger.gate():
            self.guard(mission)
            current = self.s.quality.require_pass(
                build["implementation_id"], metadata["change_commit"]
            )
            if current["id"] != qa.qa_run_id:
                raise PermissionError("Independent QA changed before merge")
            self.require_acceptance(mission, build, qa)
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
        self,
        *,
        scheduled=False,
        cycle_id=None,
        verify=None,
        expected_epoch=None,
        schedule_id=None,
        resume_patch_failure=False,
        resume_citation_failure=False,
    ):
        from contextlib import nullcontext

        if verify is None:
            raise PermissionError("Trusted post-deployment verification required")
        recovering = resume_patch_failure or resume_citation_failure
        if resume_patch_failure and resume_citation_failure:
            raise PermissionError("Choose one recovery path")
        if recovering and (
            scheduled or not cycle_id or expected_epoch is not None or schedule_id is not None
        ):
            raise PermissionError("Patch recovery requires an explicit existing manual cycle ID")
        with self.s.host.store.lease("triad-daily-product-execution"):
            completed = 0
            retained = None
            with (
                self.s.host.store.lease("triad-daily-schedule-slot") if scheduled else nullcontext()
            ):
                if resume_citation_failure:
                    from products.triad.sequential_qa_recovery import (
                        resume_citation_failure as recover,
                    )

                    cycle, completed, self.improvement_day, retained = recover(self, cycle_id)
                elif resume_patch_failure:
                    from products.triad.sequential_recovery import resume_patch_failure as recover

                    cycle, completed, self.improvement_day = recover(self, cycle_id)
                else:
                    cycle = self.s.daily.create(
                        scheduled=scheduled,
                        cycle_id=cycle_id,
                        expected_epoch=expected_epoch,
                        schedule_id=schedule_id,
                    )
            mission = cycle.cycle_id
            if not recovering:
                timezone = self.s.daily.schedule()["timezone"]
                self.improvement_day = (
                    cycle.created_at.astimezone(ZoneInfo(timezone)).date().isoformat()
                )
                self.s.canonical.append(
                    "SequentialDailyProgram",
                    {
                        "cycle_id": mission,
                        "policy_id": self.policy["id"],
                        "parent_work_item_id": cycle.parent_work_item_id,
                        "control_epoch": cycle.control_epoch,
                        "order": list(ORDER),
                        "local_date": self.improvement_day,
                        "timezone": timezone,
                        "acceptance_contract": "required-checks-v1",
                    },
                    owner="triad",
                )
            try:
                self.readiness(mission)
                for agent in ORDER[completed:]:
                    if retained is not None:
                        proposal, git, build, previous_review = retained
                        retained = None
                        qa = self.qa(mission, agent, proposal, git, build, retained=previous_review)
                    else:
                        self.s.record(
                            "ProductTurnStarted", mission, agent=agent, reviewer=REVIEWERS[agent]
                        )
                        self.s.transition(
                            mission, "INSPECTING", [agent + " turn; fresh deployed baseline"]
                        )
                        proposal, approval = self.propose(mission, agent)
                        if getattr(proposal, "outcome", "CHANGE") == "NO_CHANGE":
                            self.no_change(mission, agent, proposal, approval)
                            continue
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
                        verified_revision=merged["merge_commit"],
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
                    mission,
                    "DEBRIEFING",
                    ["All three provider turns independently reviewed and verified"],
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
                self.close_failed_work(mission, exc)
                self.s.transition(
                    mission,
                    "BLOCKED",
                    [type(exc).__name__],
                    failures=({"code": type(exc).__name__, "message": str(exc)[:500]},),
                )
                raise
