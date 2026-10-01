"""One bounded product cycle. Core supplies execution, routing, QA and Git authority.

Trusted host entry point, not a model tool. Checkpoints are append-only; a restart
never silently replays a build whose filesystem/database outcome is uncertain.
"""

import hashlib
import json
import stat
from pathlib import Path

from pydantic import ValidationError
from trading_core.brain import Brain
from trading_core.contracts import AgentRunRequest, AgentRunResult, Limits
from trading_core.execution import ExecutionServices
from trading_core.intelligence.agents import Agents
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.quality import Quality
from trading_core.intelligence.records import Records
from trading_core.intelligence.routing import Requirements, Routing
from trading_core.store import Store
from trading_core.work import ComputeBudget, Review, State, WorkItem, WorkResult, now, uid

from products.triad.development_contracts import ProductInspection, ProductProposal
from products.triad.resources import product_resource

BASELINE = "products/triad/docs/INSPECTION_BASELINE.md"
INSPECTION_PATHS = (
    BASELINE,
    "app/products/triad/server.py",
    "app/products/triad/development_contracts.py",
)


class ProductResponseFormatError(ValueError):
    """A native result cannot be parsed as the requested product artifact."""


def parse_product_artifact(schema, text):
    """Accept one observed redundant array closer; never repair substantive JSON."""

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError.from_exception_data(
                    schema.__name__,
                    [
                        {
                            "type": "value_error",
                            "loc": (),
                            "input": text,
                            "ctx": {"error": ValueError("Duplicate artifact key")},
                        }
                    ],
                )
            result[key] = value
        return result

    stripped = text.lstrip()
    try:
        value, end = json.JSONDecoder(object_pairs_hook=unique_object).raw_decode(stripped)
    except ValidationError:
        raise
    except (ValueError, TypeError):
        # Preserve the normal schema parser's error, rather than guessing repairs.
        return schema.model_validate_json(text), False
    if isinstance(value, dict) and stripped[end:].strip() == "]":
        return schema.model_validate_json(stripped[:end]), True
    return schema.model_validate_json(text), False


class Development(ExecutionServices):
    def __init__(self, store=None, git=None):
        super().__init__(store or Store(scope="triad"), git)
        if self.host.store.scope != "triad":
            raise PermissionError("Product development requires the Triad scope")
        self.records = Records(self.host.store)
        self.canonical = Records(Store(self.host.store.settings))
        self.quality = Quality(self.canonical)
        self.routing = Routing(self.records)

    def record(self, kind, mission, **payload):
        return self.records.append(
            kind,
            {"mission_id": mission, "recorded_at": now().isoformat(), **payload},
            owner="triad",
        )

    def rows(self, kind, mission):
        return [r for r in self.records.list(kind) if r.get("mission_id") == mission]

    def journal_event(self, mission, message, **evidence):
        return self.record("DevelopmentJournal", mission, message=message, **evidence)

    def call(
        self,
        mission,
        agent,
        role,
        objective,
        context,
        *,
        paths=(),
        schema=None,
        excluded=(),
        parent=None,
        keep_open=False,
        _preview=False,
        workspace_approval=None,
    ):
        write = role == "IMPLEMENT"
        reasoning = 256 if agent == "LOCAL_QWEN" else 8192
        output_tokens = 256 if agent == "LOCAL_QWEN" else 6144
        workspace = workspace_approval is not None
        if workspace and role != "IMPLEMENT":
            raise PermissionError("Workspace requires implementation role")
        caps = (
            ("structured_output", "document_analysis")
            if workspace
            else (
                ("structured_output", "isolated_text_proposal")
                if write
                else (
                    ("structured_output", "private_local_processing")
                    if role == "SUPPORT"
                    else ("structured_output", "document_analysis")
                )
            )
        )
        size = len(json.dumps(context)) + len(objective)
        if size > 1000000:
            raise ValueError("Product context exceeds the physical serialization ceiling")
        assignment = (
            WorkItem(
                owner="triad",
                mission_id=mission,
                parent_work_item_id=parent,
                title=f"Product {role.lower()}: {agent}",
                description=objective,
                work_type="development"
                if write
                else "summarize_journal"
                if role == "SUPPORT"
                else "review",
                authority_tier=2 if workspace else 1 if write else 0,
                allowed_tools=("read_file", "write_artifact") if write else ("read_file",),
                allowed_paths=paths,
                execution_permissions=("read", "write_code")
                if workspace
                else ("read", "write_research")
                if write
                else ("read",),
                reasoning_budget=reasoning,
                compute_budget=ComputeBudget(
                    max_input_chars=24000, max_output_tokens=output_tokens, timeout_seconds=480
                ),
                review_required=write,
                reviewer={"CODEX": "CLAUDE", "CLAUDE": "GROK", "GROK": "CODEX"}[agent]
                if workspace
                else "CODEX"
                if write and agent != "CODEX"
                else None,
                acceptance_criteria=(
                    "Use only supplied evidence and explicit grants",
                    "Preserve exact output and provenance",
                    "Independent QA required before any merge",
                ),
                expected_outputs=("Structured product evidence",),
            ),
            Requirements(
                execution_profile="product_workspace" if workspace else "standard",
                role=role,
                capabilities=caps,
                preferred_agent=agent,
                excluded_executors=excluded,
                context_chars=size,
                privacy="local_only" if role == "SUPPORT" else "approved_remote",
                reason=objective[:1000],
            ),
        )
        if _preview:
            return assignment
        work = self.routing.create(*assignment)
        if write and not workspace:
            self.ledger.reserve(agent, work.work_item_id, improvement=True, day=self.day)
        work, policy = self.start_work(work)
        if write and not workspace:
            metadata = self.git.isolate(work.work_item_id, work.assigned_agent)
            self.record(
                "ProductBuildCheckpoint",
                mission,
                work_item_id=work.work_item_id,
                git=metadata,
                phase="ISOLATED",
            )
        from trading_core.product_workspace_grant import TOOLS

        request = AgentRunRequest(
            agent_id=agent,
            work_item_id=work.work_item_id,
            mission_id=mission,
            role=role,
            objective=objective,
            context_packet=context,
            allowed_tools=TOOLS
            if workspace
            else ("propose_file_change",)
            if write
            else ("read_file",)
            if paths
            else (),
            allowed_paths=paths,
            acceptance_criteria=work.acceptance_criteria,
            reasoning_budget=reasoning,
            token_budget=output_tokens,
            cost_budget=0,
            execution_permissions=("write_code",)
            if workspace
            else ("write_docs",)
            if write
            else ("read",),
            policy_decision=policy.model_dump(mode="json"),
            required_output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "assumptions"],
                "additionalProperties": False,
            }
            if role == "SUPPORT"
            else AgentRunResult.model_json_schema(),
            control_epoch=self.ledger.get("authority-" + work.work_item_id)["epoch"],
        )
        self.journal_event(
            mission,
            objective,
            work_item_id=work.work_item_id,
            run_id=request.run_id,
            agent=agent,
            capabilities=caps,
            phase="STARTED",
        )
        try:
            if workspace:
                from trading_core.product_workspace_grant import issue

                issue(self.canonical, work, workspace_approval)
            result = self.runtime.execute(request)
            if result.status == "BLOCKED":
                raise PermissionError("Provider blocked this assignment: " + result.summary)
            if schema and len(result.analysis_artifacts) != 1:
                raise ValueError("Expected exactly one structured product artifact")
            try:
                payload, normalized = (
                    parse_product_artifact(schema, result.analysis_artifacts[0])
                    if schema
                    else (None, False)
                )
                if normalized:
                    self.record(
                        "ProductArtifactNormalization",
                        mission,
                        agent=agent,
                        run_id=request.run_id,
                        work_item_id=work.work_item_id,
                        operation="Removed one redundant array closer after a complete JSON object",
                        original_sha256=hashlib.sha256(
                            result.analysis_artifacts[0].encode()
                        ).hexdigest(),
                    )
            except ValidationError as exc:
                raise ProductResponseFormatError(
                    "Invalid product artifact: "
                    + json.dumps(
                        exc.errors(include_input=False, include_url=False, include_context=False)
                    )
                ) from exc
            if not write and (result.files_changed or result.proposal):
                raise PermissionError("Read-only product inspection cannot change files")
            journal = self.host.journal(
                work,
                kind="creation",
                result=result.summary,
                evidence=("run:" + request.run_id,),
                mode="REAL",
            )
            if not write:
                # This is a separate read/QA assignment: its actor is the assigned
                # executor, not the optional reviewer of an implementation WorkItem.
                journal = journal.model_copy(update={"event_kind": "review", "handoff_to": None})
            if not keep_open:
                work = self.host.advance(
                    work,
                    State.COMPLETED,
                    "Read-only product evidence preserved",
                    records=(journal,),
                    result=WorkResult(
                        summary=result.summary,
                        execution_mode="cloud" if agent != "LOCAL_QWEN" else "ollama",
                        evidence=("run:" + request.run_id,),
                    ),
                )
            else:
                self.host.store.add_record(journal)
            usage = next(
                r for r in self.ledger.records("Usage", 100) if r.get("run_id") == request.run_id
            )
            return work, result, payload, usage
        except Exception as exc:
            if write and not workspace:
                self.failed_build(mission, work, request.run_id, exc)
            current = self.host.store.get(work.work_item_id)
            from trading_core.resource_policy import ResourceBlocked

            blocked = isinstance(exc, ResourceBlocked)
            if current.status == State.IN_PROGRESS:
                self.host.advance(
                    current,
                    State.BLOCKED if blocked else State.FAILED,
                    "Resource extension blocked"
                    if blocked
                    else "Product run failed: " + type(exc).__name__,
                    failure_reason="BLOCKED_RESOURCE_LIMIT" if blocked else type(exc).__name__,
                )
            self.journal_event(
                mission,
                "Resource extension blocked; evidence retained"
                if blocked
                else "Run failed; evidence retained",
                work_item_id=work.work_item_id,
                error_class=type(exc).__name__,
                phase="BLOCKED_RESOURCE_LIMIT" if blocked else "FAILED",
            )
            raise

    def failed_build(self, mission, work, run_id, exc):
        from trading_core.resource_policy import ResourceBlocked

        checkpoints = [
            r
            for r in self.rows("ProductBuildCheckpoint", mission)
            if r["work_item_id"] == work.work_item_id
        ]
        metadata = checkpoints[-1]["git"] if checkpoints else {}
        selected = self.records.get("route-" + work.work_item_id)["selected"]
        failed = ImplementationRun(
            owner="triad",
            work_item_id=work.work_item_id,
            builder=work.assigned_agent,
            provider=selected["provider"],
            model="not observed for failed implementation",
            transport=selected["transport"],
            base_commit=metadata.get("base_commit", "not isolated"),
            change_commit="failed:" + run_id,
            files=(),
            tests=(),
            status="BLOCKED_RESOURCE_LIMIT" if isinstance(exc, ResourceBlocked) else "FAILED",
            evidence=("run:" + run_id, "failure:" + type(exc).__name__),
        )
        self.quality.implementation(failed)
        self.record(
            "ProductBuildFailure",
            mission,
            work_item_id=work.work_item_id,
            implementation_id=failed.implementation_run_id,
            builder=work.assigned_agent,
            error_class=type(exc).__name__,
            git=metadata,
            status="FAILED",
        )

    def inspect(self, mission):
        existing = self.rows("ProductInspection", mission)
        for agent, focus in (
            ("CODEX", "implementation and technical product gaps"),
            ("CLAUDE", "architecture, workflow and UX gaps"),
            ("GROK", "market/product opportunities and missing capabilities"),
        ):
            if any(r["agent"] == agent for r in existing):
                continue
            objective = (
                f"Independently inspect Triad's {focus}. Read every supplied baseline and product source file. "
                "No other frontier findings are supplied. Do not infer real market access or trading success. "
                "Return RESEARCH_FINDING, no files/proposal/claims/actions/tests/commands. "
                "analysis_artifacts must contain exactly one JSON string matching the supplied product schema. "
                "Give exactly 2 evidenced product areas and 1 improvement candidate. "
                "Keep the entire response below 1000 output tokens: short phrases for fields, "
                "at most one short item per nested field list, no repeated explanations. "
                "Identify real product value without seeding a preferred strategy. Candidate IDs may be omitted."
            )
            work, result, payload, usage = self.call(
                mission,
                agent,
                "REVIEW",
                objective,
                {"product_schema": ProductInspection.model_json_schema()},
                paths=INSPECTION_PATHS,
                schema=ProductInspection,
            )
            self.record(
                "ProductInspection",
                mission,
                agent=agent,
                work_item_id=work.work_item_id,
                run_id=usage["run_id"],
                usage=usage,
                summary=result.summary,
                **payload.model_dump(mode="json"),
            )
            for candidate in payload.candidates:
                self.record(
                    "ProductCandidate",
                    mission,
                    inspection_agent=agent,
                    **candidate.model_dump(mode="json"),
                )
        inspections = self.rows("ProductInspection", mission)
        if {r["agent"] for r in inspections} != {"CODEX", "CLAUDE", "GROK"}:
            raise PermissionError("Three independent frontier inspections required")
        if not self.rows("ProductSynthesis", mission):
            findings = [
                {
                    "agent": r["agent"],
                    "summary": r["summary"],
                }
                for r in inspections
            ]
            work, result, _, usage = self.call(
                mission,
                "LOCAL_QWEN",
                "SUPPORT",
                "Summarize these independent product findings and disagreements in at most 35 words. "
                "Return a short summary and an empty assumptions list. "
                "Observe only; do not choose, approve or grant authority.",
                {"findings": findings},
            )
            self.record(
                "ProductSynthesis",
                mission,
                work_item_id=work.work_item_id,
                summary=result.summary,
                result=result.model_dump(mode="json"),
                usage=usage,
            )
        return inspections

    def select(self, mission):
        proposals = self.rows("ProductProposal", mission)
        if proposals:
            return ProductProposal.model_validate(proposals[-1]["proposal"])
        candidates = self.rows("ProductCandidate", mission)
        if not candidates:
            raise PermissionError("Inspections must precede selection")
        available = self.routing.agents.list()
        verified = self.routing.control
        objective = (
            "Select exactly ONE candidate based on evidenced product value, risk, reversibility, feasibility, "
            "dependencies and current product maturity. Do not force strategy or UI work. "
            "This cycle can only stage bounded non-executable text, at most3 files/180lines in docs/improvements "
            "or research/improvements. No new tools, trading authority or live data. "
            "affected_components must list these exact granted directory names, not filenames or subdirectories. "
            "Return RESEARCH_FINDING, no files/proposal/claims/actions/tests/commands. "
            "Put one JSON ProductProposal in analysis_artifacts matching the supplied schema; use an existing candidate ID. "
            "Require structured_output and isolated_text_proposal; permissions write_docs; LOW risk. "
            "Choose an agent with VERIFIED proposal capability; state if an existing role suffices."
        )
        from trading_core.intelligence.capabilities import Capabilities

        capabilities = [
            {
                "agent": a["agent_id"],
                "model": a["model"],
                "transport": a["preferred_transport"],
                "proof_current": verified.proven(verified.snapshot(a["preferred_transport"])),
                "capabilities": [
                    v["capability"]["capability"]
                    for v in Capabilities(self.records).current()
                    if v["capability"]["transport"] == a["preferred_transport"]
                    and v["capability"]["verification_status"] == "VERIFIED"
                ],
            }
            for a in available
        ]
        work, result, proposal, usage = self.call(
            mission,
            "CODEX",
            "REVIEW",
            objective,
            {
                "candidates": [
                    {
                        k: v
                        for k, v in r.items()
                        if k not in {"id", "kind", "owner", "recorded_at", "mission_id"}
                    }
                    for r in candidates
                ],
                "qwen_summary": self.rows("ProductSynthesis", mission)[-1]["summary"],
                "available_agents": capabilities,
                "proposal_schema": ProductProposal.model_json_schema(),
            },
            schema=ProductProposal,
        )
        if proposal.candidate_id not in {r["candidate_id"] for r in candidates}:
            raise PermissionError("Selection must refer to inspected backlog")
        self.record(
            "ProductProposal",
            mission,
            proposal=proposal.model_dump(mode="json"),
            selector="CODEX",
            work_item_id=work.work_item_id,
            usage=usage,
            summary=result.summary,
        )
        return proposal

    def approve(self, mission, proposal):
        self.ledger.guard()
        limits = Limits.model_validate(self.ledger.control()["limits"])
        if (
            proposal.risk_class != "LOW"
            or proposal.specialist != "existing agent sufficient"
            or set(proposal.permissions_required) != {"write_docs"}
            or {"structured_output", "isolated_text_proposal"}
            != set(proposal.required_capabilities)
            or not set(proposal.affected_components) <= set(limits.allowed_directories)
        ):
            raise PermissionError("Proposal needs authority outside this bounded product cycle")
        self.record(
            "ProductApproval",
            mission,
            proposal_id=proposal.proposal_id,
            decision="ALLOW",
            reason="Low-risk reversible text; capability route and Control Plane evaluated again at dispatch; independent QA mandatory",
        )
        return limits

    def build(self, mission, proposal, *, correction=()):
        limits = self.approve(mission, proposal)
        self.git.clean_baseline()
        work, result, _, usage = self.call(
            mission,
            proposal.recommended_agent,
            "IMPLEMENT",
            "Implement this approved product improvement using the isolated propose_file_change tool. "
            "Stage concise useful non-executable text with a # heading if Markdown, within the exact approved scope. "
            "Return matching files_changed. No tests, commands, claims, actions_taken or permission requests. "
            "The host will apply the staged proposal in an isolated Git worktree and run checks; a different provider will QA.",
            {"proposal": proposal.model_dump(mode="json"), "required_corrections": correction},
            paths=proposal.affected_components,
            keep_open=True,
            parent=self.rows("ProductBuild", mission)[-1]["work_item_id"]
            if correction and self.rows("ProductBuild", mission)
            else None,
        )
        metadata = next(
            r["git"]
            for r in self.rows("ProductBuildCheckpoint", mission)
            if r["work_item_id"] == work.work_item_id
        )
        try:
            self.check_ownership(result.files_changed)
            scoped = limits.model_copy(update={"allowed_directories": proposal.affected_components})
            checks = self.git.apply(metadata, result.files_changed, scoped)
            self.git.commit(metadata, work.assigned_agent)
            checks = self.git.verify(metadata, scoped)
            build = ImplementationRun(
                owner="triad",
                work_item_id=work.work_item_id,
                builder=work.assigned_agent,
                provider=usage["provider"],
                model=usage["actual_model"],
                transport=usage["transport"],
                base_commit=metadata["base_commit"],
                change_commit=metadata["change_commit"],
                files=tuple(checks["files"]),
                tests=tuple(checks["checks"]),
                evidence=(
                    "run:" + usage["run_id"],
                    *("sha256:" + h + ":" + p for p, h in checks["hashes"].items()),
                ),
            )
            self.quality.implementation(build)
            self.handoff(work, result, metadata, checks, "REAL")
            record = {
                "implementation_id": build.implementation_run_id,
                "work_item_id": work.work_item_id,
                "proposal_id": proposal.proposal_id,
                "git": metadata,
                "checks": checks,
                "usage": usage,
                "builder": work.assigned_agent,
                "correction": list(correction),
            }
            self.record("ProductBuild", mission, **record)
            return record
        except Exception as exc:
            self.failed_build(mission, work, usage["run_id"], exc)
            current = self.host.store.get(work.work_item_id)
            if current.status in {State.IN_PROGRESS, State.AWAITING_REVIEW}:
                self.host.advance(current, State.FAILED, "Host build validation failed")
            self.journal_event(
                mission,
                "Build interrupted; worktree retained for reconciliation",
                error_class=type(exc).__name__,
                work_item_id=work.work_item_id,
                git=metadata,
            )
            raise

    def exact_checks(self, build, limits, *, after_review=False):
        metadata = build["git"]
        expected = metadata["review_commit"] if after_review else metadata["change_commit"]
        if self.git.git("rev-parse", "HEAD", cwd=metadata["worktree"]) != expected or self.git.git(
            "status", "--porcelain", "--untracked-files=all", cwd=metadata["worktree"]
        ):
            raise PermissionError("Worktree changed since the recorded implementation")
        checks = self.git.verify(metadata, limits)
        if any(checks[key] != build["checks"][key] for key in ("hashes", "files", "diff")):
            raise PermissionError("Worktree source differs from the exact build evidence")
        return checks

    def check_ownership(self, changes):
        with self.host.store.connect() as conn:
            for change in changes:
                row = conn.execute(
                    "SELECT owner FROM core.artifact_owners WHERE lower(path)=lower(%s)",
                    (change.path,),
                ).fetchone()
                if row and row["owner"] != "triad":
                    raise PermissionError("Cannot modify another product's artifact")

    def qa_references(self, build):
        """Optional trusted reference evidence; never extends reviewer tool grants."""
        return {}

    def qa(self, mission, proposal, build):
        metadata = build["git"]
        limits = Limits.model_validate(self.ledger.control()["limits"]).model_copy(
            update={"allowed_directories": proposal.affected_components}
        )
        checks = self.exact_checks(build, limits)
        references = self.qa_references(build)
        reviewer = "CODEX" if build["builder"] != "CODEX" else "CLAUDE"
        work, result, _, usage = self.call(
            mission,
            reviewer,
            "REVIEW",
            "Independently QA the exact proposed product artifact against proposal/acceptance, correctness, normal/failure/empty use, "
            "architecture, security and adjacent regressions. The trusted host reran the listed deterministic checks and supplied "
            "the exact worktree sources, hashes and diff. You have no shell or browser; do not claim to run tests. "
            "Read the granted baseline and product source files as original reference evidence; the proposed artifact is in the host snapshot, not yet on main. "
            "Return review_decision APPROVE, REQUEST_CHANGES or REJECT; findings must list real issues, not generic praise. "
            "For APPROVE, any findings are non-blocking observations retained as QualityDebt. No files/proposal/claims/tests/commands/actions.",
            {
                "proposal": proposal.model_dump(mode="json"),
                "exact_commit": metadata["change_commit"],
                "repeated_host_checks": checks,
                **({"trusted_backend_reference": references} if references else {}),
            },
            excluded=(build["builder"],),
            parent=build["work_item_id"],
            paths=INSPECTION_PATHS,
        )
        if not result.review_decision:
            raise ValueError("QA omitted structured decision")
        self.exact_checks(build, limits)
        decision = {
            "APPROVE": "PASS_WITH_OBSERVATIONS" if result.findings else "PASS",
            "REQUEST_CHANGES": "CHANGES_REQUIRED",
            "REJECT": "REJECT",
        }[result.review_decision]
        qa = QARun(
            implementation_run_id=build["implementation_id"],
            qa_work_item_id=work.work_item_id,
            qa_agent=reviewer,
            qa_provider=usage["provider"],
            qa_model=usage["actual_model"],
            reviewed_commit=metadata["change_commit"],
            agent_capabilities_used=("structured_output", "document_analysis"),
            findings=result.findings,
            required_changes=result.findings if result.review_decision != "APPROVE" else (),
            severity="LOW" if result.review_decision == "APPROVE" else "MEDIUM",
            tests_repeated=tuple(checks["checks"]),
            evidence=(
                "run:" + usage["run_id"],
                *("sha256:" + h + ":" + p for p, h in checks["hashes"].items()),
                *(("qa-reference:" + references["sha256"],) if references else ()),
            ),
            decision=decision,
            execution_mode="REAL_PROVIDER",
        )
        self.quality.review(qa)
        self.record(
            "ProductQA",
            mission,
            qa_id=qa.qa_run_id,
            implementation_id=build["implementation_id"],
            reviewer=reviewer,
            usage=usage,
            decision=decision,
            findings=result.findings,
            checks=checks,
            **({"qa_reference": references} if references else {}),
        )
        if result.review_decision != "APPROVE":
            builder_work = self.host.store.get(build["work_item_id"])
            self.host.advance(
                builder_work,
                State.CHANGES_REQUESTED
                if result.review_decision == "REQUEST_CHANGES"
                else State.REJECTED,
                "Separate independent QA did not approve this implementation",
            )
        return qa

    def merge(self, mission, proposal, build, qa, *, operator_authorized=False):
        work = self.host.store.get(build["work_item_id"])
        metadata = build["git"]
        current = self.quality.require_pass(build["implementation_id"], metadata["change_commit"])
        if current["id"] != qa.qa_run_id or qa.qa_agent != work.reviewer:
            raise PermissionError("Merge must use the matching independent QA assignment")
        limits = self.approve(mission, proposal).model_copy(
            update={"allowed_directories": proposal.affected_components}
        )
        self.exact_checks(build, limits)
        if self.host.control.evaluate(work).decision not in {"ALLOW", "REQUIRE_REVIEW"}:
            raise PermissionError("Control Plane denied merge")
        review = Review(
            reviewer=qa.qa_agent,
            work_item_id=work.work_item_id,
            decision="APPROVE",
            findings=qa.findings or ("Exact artifact independently approved",),
            severity="LOW" if qa.findings else "NONE",
            evidence_checked=qa.evidence,
            tests_repeated=qa.tests_repeated,
            execution_mode="REAL",
        )
        work = self.host.advance(
            work,
            State.APPROVED_BY_REVIEWER,
            "Separate product QA passed",
            records=(review,),
            review=review,
        )
        epoch = self.ledger.get("authority-" + work.work_item_id)["epoch"]
        self.git.review_commit(metadata, qa.qa_run_id, qa.decision)
        with self.ledger.gate(work.assigned_agent, work.work_item_id, epoch) as control:
            if control["require_human_review"] and not operator_authorized:
                raise PermissionError("Operator authorization required for this merge")
            self.quality.require_pass(build["implementation_id"], metadata["change_commit"])
            limits = Limits.model_validate(control["limits"]).model_copy(
                update={"allowed_directories": proposal.affected_components}
            )
            self.check_ownership(
                [type("PathRecord", (), {"path": p}) for p in build["checks"]["files"]]
            )
            self.exact_checks(build, limits, after_review=True)
            self.git.merge(
                metadata,
                {
                    "decision": "APPROVE",
                    "change_commit": metadata["change_commit"],
                    "reviewer": qa.qa_agent,
                    "worker": work.assigned_agent,
                    "review_id": qa.qa_run_id,
                },
                limits,
            )
        for path, digest in build["checks"]["hashes"].items():
            if hashlib.sha256((self.git.root / path).read_bytes()).hexdigest() != digest:
                raise ValueError("Post-merge artifact hash differs from QA")
        with self.host.store.connect() as conn:
            for path in build["checks"]["files"]:
                conn.execute(
                    "INSERT INTO core.artifact_owners(path,owner,record_id) VALUES (%s,'triad',%s) ON CONFLICT(path) DO UPDATE SET record_id=EXCLUDED.record_id WHERE core.artifact_owners.owner='triad'",
                    (path, build["implementation_id"]),
                )
        self.host.advance(
            work, State.COMPLETED, "QA and governed merge completed; post-merge hashes verified"
        )
        self.record(
            "ProductMerge",
            mission,
            implementation_id=build["implementation_id"],
            qa_id=qa.qa_run_id,
            git=metadata,
            files=build["checks"]["files"],
            hashes=build["checks"]["hashes"],
            status="MERGED",
        )
        self.journal_event(
            mission,
            "Selected improvement merged after independent QA and post-merge verification",
            builder=work.assigned_agent,
            reviewer=qa.qa_agent,
            merge_commit=metadata["merge_commit"],
        )
        Brain(self.host.store).flush()
        return metadata

    def run(self, mission=None, *, operator_authorized=False):
        from products.triad.cycle_history import CycleHistory

        mission = mission or uid()
        history = CycleHistory(self.host.store)
        history.parent(mission)
        try:
            result = self._run(mission, operator_authorized=operator_authorized)
        except Exception as exc:
            history.capture(
                mission,
                status="BLOCKED",
                error=getattr(exc, "error_class", type(exc).__name__),
                cycle_type="PRODUCT_BUILD",
                execution_mode="REAL",
            )
            raise
        history.capture(mission)
        return result

    def _run(self, mission, *, operator_authorized=False):
        with self.host.store.lease("triad-product-development"):
            self.ledger.guard()
            if self.rows("ProductMerge", mission):
                return self.rows("ProductMerge", mission)[-1]
            if self.rows("ProductBuildCheckpoint", mission):
                raise PermissionError(
                    "Existing build checkpoint requires explicit reconciliation; no automatic replay"
                )
            if not self.rows("ProductCycle", mission):
                self.record("ProductCycle", mission, status="INSPECTING", schedule_enabled=False)
            self.inspect(mission)
            proposal = self.select(mission)
            build = self.build(mission, proposal)
            qa = self.qa(mission, proposal, build)
            if qa.decision not in {"PASS", "PASS_WITH_OBSERVATIONS"}:
                raise PermissionError("Independent QA requires correction; exact findings retained")
            return self.merge(mission, proposal, build, qa, operator_authorized=operator_authorized)

    def dashboard(self):
        kinds = (
            "ProductCycle",
            "ProductInspection",
            "ProductSynthesis",
            "ProductCandidate",
            "ProductProposal",
            "ProductApproval",
            "ProductBuild",
            "ProductBuildFailure",
            "ProductQA",
            "ProductMerge",
            "DevelopmentJournal",
            "QualityDebt",
        )
        return {
            "charter": json.loads(product_resource("product.json").read_text(encoding="utf-8")),
            "records": {k: self.records.list(k) for k in kinds},
            "specialists": [
                a for a in Agents(self.records).list() if a["agent_type"] == "specialist"
            ],
            "updated_at": now().isoformat(),
        }

    def artifact(self, path):
        merges = self.records.list("ProductMerge")
        match = next((r for r in reversed(merges) if path in r["hashes"]), None)
        if not match:
            raise KeyError("No reviewed merged artifact")
        if path.startswith("app/products/triad/features/"):
            # This is a read-only viewer for an exact, reviewed merge entry. Do
            # not widen the generic Git writer's text-only path permissions.
            from trading_core.engineering import checked_paths

            checked_paths("triad", (path,))
            root = Path(self.git.root).resolve()
            target = root / path
            for entry in (target, *target.parents):
                if entry == root:
                    break
                if entry.is_symlink() or (
                    entry.exists()
                    and getattr(entry.lstat(), "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
                ):
                    raise PermissionError("Reparse point rejected")
            if not target.resolve().is_relative_to(root) or (
                target.exists() and target.stat().st_nlink > 1
            ):
                raise PermissionError("Aliased or escaping artifact")
            if target.stat().st_size > 32000:
                raise PermissionError("Reviewed UI asset exceeds size ceiling")
        else:
            target = self.git.path(
                self.git.root, path, ("docs/improvements", "research/improvements")
            )
        self.check_ownership([type("PathRecord", (), {"path": path})])
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != match["hashes"][path]:
            raise PermissionError("Artifact changed since reviewed merge")
        return {
            "path": path,
            "content": data.decode("utf-8"),
            "merge_commit": match["git"]["merge_commit"],
        }
