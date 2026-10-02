"""One real daily product cycle, using verified Core tools and separate frontier QA."""

import json
from pathlib import Path

from trading_core.contracts import AgentRunRequest, AgentRunResult, Limits
from trading_core.engineering import (
    EngineeringGit,
    EngineeringGrant,
    issue_grant,
    run_approved_checks,
)
from trading_core.integrations.readiness import Readiness
from trading_core.intelligence.contracts import ImplementationRun, QARun
from trading_core.intelligence.routing import Requirements
from trading_core.work import ComputeBudget, State, WorkItem, now, uid

from products.triad.daily import Daily, Debrief, digest
from products.triad.development import Development
from products.triad.development_contracts import ProductInspection, ProductProposal

FILES = (
    "app/products/triad/features/research_readiness.html",
    "app/products/triad/features/research_readiness.js",
)
CAPS = ("structured_output", "isolated_text_proposal", "isolated_product_ui_edit")
# Trusted acceptance program. Model assets are parsed/read only in the offline
# container. Runtime/browser behavior receives separate independent review.
CHECK_SCRIPT = """from pathlib import Path
from html.parser import HTMLParser
html=Path("app/products/triad/features/research_readiness.html").read_text(encoding="utf-8")
js=Path("app/products/triad/features/research_readiness.js").read_text(encoding="utf-8")
class Page(HTMLParser):
 def __init__(self): super().__init__(); self.ids=set(); self.scripts=[]; self.viewport=False
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  assert not any(k.startswith("on") for k in a), "Inline handlers denied"
  if "id" in a: assert a["id"] not in self.ids; self.ids.add(a["id"])
  if tag=="script": self.scripts.append(a.get("src"))
  if tag=="meta" and a.get("name")=="viewport": self.viewport=True
p=Page(); p.feed(html)
assert p.viewport and p.scripts==["/triad/assets/research-readiness.js"]
assert {"source","dataset","symbols","start","end","mode","universe","membership","evaluate","result","notice"} <= p.ids
for text in ("/api/core/research-readiness", "/evaluate", "textContent", "JSON.stringify"):
 assert text in js, text
for forbidden in ("innerHTML", "outerHTML", "document.write", "eval(", "localStorage", "sessionStorage", "Authorization", "fetch('http", 'fetch("http'):
 assert forbidden not in js, forbidden
for link in ("/triad/product", "/triad/development", "/triad/cycles", "/triad/daily-debrief"):
 assert link in html, link
assert "strategy" in (html+js).lower()
assert "FIXTURE" in (html+js) and "REAL" in (html+js)
print("PASS: exact UI contract, required request controls, safe text rendering, isolated source inspection")
"""


class DailyDevelopment(Development):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from trading_core.store import Store

        self.daily = Daily(Store(self.host.store.settings))

    def start_work(self, work, epoch=None):
        cycle = self.daily.current(work.mission_id)
        self.daily.product.ledger.guard(
            work_id=cycle["parent_work_item_id"], epoch=cycle["control_epoch"]
        )
        return super().start_work(work, epoch=cycle["control_epoch"])

    def transition(self, mission, state, evidence, **updates):
        self.daily.refresh(mission)
        return self.daily.transition(mission, state, evidence, **updates)

    def inspect(self, mission):
        import httpx

        current = Readiness().catalog()
        # Freeze historical product evidence before the first inspector runs;
        # later inspectors never receive this cycle's earlier conclusions.
        inspections = [
            r for r in self.records.list("ProductInspection") if r.get("mission_id") != mission
        ][-3:]
        areas = [
            {"inspection_id": r["id"], "agent": r.get("agent"), **area}
            for r in inspections
            for area in r.get("areas", [])
        ]
        control = self.ledger.control()
        worker = {"checked_at": now().isoformat(), "status": "UNKNOWN"}
        try:
            response = httpx.get("http://127.0.0.1:8101/health/live", timeout=5, trust_env=False)
            response.raise_for_status()
            health = response.json()
            worker["status"] = (
                "UP"
                if health.get("status") == "ok" and health.get("product") == "triad"
                else "UNKNOWN"
            )
        except (httpx.HTTPError, ValueError):
            worker["status"] = "UNAVAILABLE"
        worker["evidence"] = "Read-only Triad worker /health/live; liveness is not task success"
        context = {
            "product_schema": ProductInspection.model_json_schema(),
            "product_map": areas,
            "capability_inventory": [
                {
                    k: a.get(k)
                    for k in ("inspection_id", "capability", "state", "limitations", "evidence")
                }
                for a in areas
            ],
            "improvement_backlog": [
                {
                    k: r.get(k)
                    for k in ("id", "candidate_id", "title", "product_area", "status", "evidence")
                }
                for r in self.records.list("ProductCandidate")
                if r.get("mission_id") != mission
            ][-6:],
            "recent_independent_qa": [
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "implementation_run_id",
                        "reviewed_commit",
                        "decision",
                        "findings",
                        "required_changes",
                    )
                }
                for r in self.records.list("QARun")
            ][-3:],
            "worker_readiness": worker,
            "control_snapshot": {k: control.get(k) for k in ("epoch", "paused", "killed")},
            "preferred_operator_target": "Research Readiness View: what real historical research can be performed now, and what evidence is missing?",
            "current_data": {
                "limitations": current["limitations"],
                "datasets": current["datasets"][:3],
                "integrations": [
                    {k: s[k] for k in ("integration_id", "name", "status", "capabilities")}
                    for s in current["sources"]
                ],
            },
            "recent_cycles": [
                {k: c.get(k) for k in ("cycle_id", "status", "failures", "selected_proposal")}
                for c in self.daily.history.list()[:3]
            ],
            "recent_debt": self.records.list("QualityDebt")[-5:],
            "current_capabilities": self.routing.agents.list(),
        }
        for agent, focus in (
            ("CODEX", "implementation and architecture"),
            ("CLAUDE", "UX and operator workflow"),
            ("GROK", "research and market capability"),
        ):
            work, result, inspection, usage = self.call(
                mission,
                agent,
                "REVIEW",
                "Independently inspect current Triad "
                + focus
                + ". No other inspector conclusions are supplied. "
                "Read supplied product sources. Identify one bounded useful improvement, considering the preferred target. "
                "Return RESEARCH_FINDING and exactly one ProductInspection JSON in analysis_artifacts; two areas and one candidate. "
                "No files, commands, tests, actions or factual claims outside supplied evidence. Keep result concise, under 1200 tokens.",
                context,
                paths=("app/products/triad/static/product.html",),
                schema=ProductInspection,
                parent=self.daily.current(mission)["parent_work_item_id"],
            )
            self.record(
                "ProductInspection",
                mission,
                agent=agent,
                work_item_id=work.work_item_id,
                run_id=usage["run_id"],
                usage=usage,
                summary=result.summary,
                **inspection.model_dump(mode="json"),
            )
            for candidate in inspection.candidates:
                self.record(
                    "ProductCandidate",
                    mission,
                    inspection_agent=agent,
                    **candidate.model_dump(mode="json"),
                )
        work, result, _, usage = self.call(
            mission,
            "LOCAL_QWEN",
            "SUPPORT",
            "Summarize these differing independent judgments in at most35 words. Do not select or grant authority; assumptions empty.",
            {
                "findings": [
                    {"agent": r["agent"], "summary": r["summary"]}
                    for r in self.rows("ProductInspection", mission)
                ]
            },
            parent=self.daily.current(mission)["parent_work_item_id"],
        )
        self.record(
            "ProductSynthesis",
            mission,
            work_item_id=work.work_item_id,
            summary=result.summary,
            usage=usage,
        )

    def select(self, mission):
        _, result, proposal, usage = self.call(
            mission,
            "CODEX",
            "REVIEW",
            "Select exactly one evidenced candidate. Prefer Research Readiness operator feature, consuming Core. "
            "Available bounded engineering profile permits ONLY supplied exact HTML/JS feature paths, 3files/600lines, no backend/shell. "
            "Use those exact affected_components, permissions_required=['write_code'], required_capabilities exactly the supplied capabilities, "
            "recommended_agent CLAUDE, specialist 'existing agent sufficient', LOW risk. "
            "Return one ProductProposal JSON string in analysis_artifacts; no files/actions/tests/commands. If this scope cannot achieve the objective say BLOCKED.",
            {
                "candidates": self.rows("ProductCandidate", mission),
                "proposal_schema": ProductProposal.model_json_schema(),
                "allowed_paths": FILES,
                "required_capabilities": CAPS,
                "qwen_synthesis": self.rows("ProductSynthesis", mission)[-1]["summary"],
            },
            schema=ProductProposal,
            parent=self.daily.current(mission)["parent_work_item_id"],
        )
        if proposal.candidate_id not in {
            c["candidate_id"] for c in self.rows("ProductCandidate", mission)
        }:
            raise PermissionError("Selection must come from this cycle's independent inspection")
        self.record(
            "ProductProposal",
            mission,
            proposal=proposal.model_dump(mode="json"),
            selector="CODEX",
            usage=usage,
            summary=result.summary,
        )
        self.approve(mission, proposal)
        return proposal

    def approve(self, mission, proposal):
        self.ledger.guard()
        if (
            proposal.risk_class != "LOW"
            or proposal.specialist != "existing agent sufficient"
            or set(proposal.permissions_required) != {"write_code"}
            or set(proposal.required_capabilities) != set(CAPS)
            or set(proposal.affected_components) != set(FILES)
            or proposal.recommended_agent != "CLAUDE"
        ):
            raise PermissionError("Proposal exceeds the approved isolated product UI policy")
        self.record(
            "ProductApproval",
            mission,
            proposal_id=proposal.proposal_id,
            decision="ALLOW",
            reason="Exact UI assets, verified Core tools, reversible change, no new authority, mandatory independent QA",
        )
        return Limits.model_validate(self.ledger.control()["limits"])

    def qa_references(self, build):
        from products.triad.qa_reference import readiness_reference

        return readiness_reference(self.git.root, build["git"], Readiness().catalog())

    def build_assignment(self, mission, objective, context, parent=None):
        return (
            WorkItem(
                owner="triad",
                mission_id=mission,
                parent_work_item_id=parent,
                title="Bounded product UI implementation",
                description=objective,
                work_type="development",
                authority_tier=2,
                allowed_tools=("read_file", "write_artifact"),
                allowed_paths=FILES,
                execution_permissions=("read", "write_code"),
                reasoning_budget=8192,
                compute_budget=ComputeBudget(
                    max_input_chars=24000,
                    max_output_tokens=6144,
                    timeout_seconds=480,
                    max_tool_calls=60,
                ),
                review_required=True,
                reviewer="CODEX",
                acceptance_criteria=(
                    "Research readiness contract",
                    "No fake real data",
                    "Independent QA and exact governed merge",
                ),
            ),
            Requirements(
                role="IMPLEMENT",
                capabilities=CAPS,
                preferred_agent="CLAUDE",
                context_chars=len(json.dumps(context)) + len(objective),
                reason="Verified bounded UI engineering profile; independent Codex QA",
            ),
        )

    def readiness(self, mission):
        from trading_core.intelligence.capabilities import Capabilities

        self.routing.control.monitor_connections()
        stages = []
        for agent in ("CODEX", "CLAUDE", "GROK"):
            stages.append(
                (
                    "inspection",
                    self.call(
                        mission,
                        agent,
                        "REVIEW",
                        "Readiness",
                        {},
                        paths=("app/products/triad/static/product.html",),
                        _preview=True,
                    ),
                )
            )
        stages.append(
            (
                "local synthesis",
                self.call(mission, "LOCAL_QWEN", "SUPPORT", "Readiness", {}, _preview=True),
            )
        )
        stages.append(
            ("selection", self.call(mission, "CODEX", "REVIEW", "Readiness", {}, _preview=True))
        )
        stages.append(("implementation", self.build_assignment(mission, "Readiness", {})))
        stages.append(
            (
                "independent QA",
                self.call(
                    mission,
                    "CODEX",
                    "REVIEW",
                    "Readiness",
                    {},
                    paths=FILES,
                    excluded=("CLAUDE",),
                    _preview=True,
                ),
            )
        )
        for agent in ("CODEX", "CLAUDE", "GROK"):
            stages.append(
                ("debrief", self.call(mission, agent, "REVIEW", "Readiness", {}, _preview=True))
            )
        versions = Capabilities(self.routing.records).current()
        checks = []
        for stage, (work, requirements) in stages:
            agent = self.routing.agents.get(requirements.preferred_agent)
            result = self.routing._candidate(agent, work, requirements, versions)
            checks.append(
                {
                    "stage": stage,
                    "agent": requirements.preferred_agent,
                    "ready": result["eligible"],
                    "reasons": result["exclusions"],
                }
            )
        self.record("DailyReadiness", mission, checks=checks)
        blocked = [c for c in checks if not c["ready"]]
        if blocked:
            raise PermissionError(
                "Daily cycle cannot start: "
                + "; ".join(
                    c["agent"] + " (" + c["stage"] + "): " + ", ".join(c["reasons"])
                    for c in blocked
                )
            )
        return checks

    def build(self, mission, proposal, *, correction=()):
        self.approve(mission, proposal)
        base = self.git.clean_baseline()
        context = {
            "proposal": proposal.model_dump(mode="json"),
            "required_corrections": correction,
            "ui_contract": {
                "ids": [
                    "source",
                    "dataset",
                    "symbols",
                    "start",
                    "end",
                    "mode",
                    "universe",
                    "membership",
                    "evaluate",
                    "result",
                    "notice",
                ],
                "html_script": "/triad/assets/research-readiness.js",
                "navigation_links": {
                    "Product": "/triad/product",
                    "Development": "/triad/development",
                    "Cycles": "/triad/cycles",
                    "Daily Debrief": "/triad/daily-debrief",
                },
                "files": FILES,
            },
            "api_contract": {
                "catalog": "/api/core/research-readiness",
                "evaluate": "/api/core/research-readiness/evaluate",
                "method": "POST read-only evaluation, no auth token needed",
                "request_fields": [
                    "integration_id",
                    "dataset_id",
                    "symbols",
                    "start",
                    "end",
                    "mode",
                    "universe",
                    "membership_rule",
                ],
                "membership_rule": ["EXPLICIT_SYMBOLS", "HISTORICAL_CONSTITUENTS"],
                "dates": "timezone-aware ISO UTC; inclusive start/exclusive end",
                "catalog_example": Readiness().catalog(),
                "result_fields": [
                    "status",
                    "request",
                    "source",
                    "dataset",
                    "expected_coverage",
                    "missing",
                    "checks",
                    "independent_evidence",
                    "strategy_notice",
                ],
            },
        }
        objective = (
            "Build the approved Research Readiness operator UI. Use the native propose_file_change tool to stage BOTH exact supplied HTML/JS paths. "
            "Use accessible responsive layout and labels, readable evidence (never raw JSON). Select source and dataset explicitly; show REAL/FIXTURE truthfully. "
            "Expose universe/symbols/membership rule/start/end/timeframe/session/required OHLCV fields and expected coverage; display provenance, missing checks, license and gaps. "
            "Support loading/empty/error; API errors must remain readable. No automatic fetch beyond Core discovery/read-only evaluation, no paid calls, no accounts or trading. "
            "All untrusted strings via textContent; no innerHTML/eval/storage/inline handlers. Required IDs/API contract supplied. HTML uses only one external script supplied route. "
            "Use the exact supplied navigation_links destinations for Product/Development/Cycles/Daily Debrief. "
            "Max600changedlines and32000combinedbytes; keep eachfile below12000bytes. "
            "Return CODE_CHANGE with files_changed EMPTY and concise summary: Core reconstructs the exact files from your observed tool writes. "
            "Do not repeat file contents in the final JSON. No tests/commands/actions/claims. Host runs checks, Codex independently reviews."
        )
        work = self.routing.create(
            *self.build_assignment(
                mission, objective, context, self.daily.current(mission)["parent_work_item_id"]
            )
        )
        work, policy = self.start_work(work)
        grant = issue_grant(
            self.canonical,
            work,
            base_commit=base,
            files=FILES,
            test_id="research-readiness-ui-v1",
            test_script=CHECK_SCRIPT,
        )
        self.git = EngineeringGit(grant)
        metadata = self.git.isolate(work.work_item_id, work.assigned_agent)
        self.record(
            "ProductBuildCheckpoint",
            mission,
            work_item_id=work.work_item_id,
            git=metadata,
            phase="ISOLATED",
        )
        request = AgentRunRequest(
            agent_id="CLAUDE",
            work_item_id=work.work_item_id,
            mission_id=mission,
            role="IMPLEMENT",
            objective=objective,
            context_packet=context,
            allowed_tools=("propose_file_change",),
            allowed_paths=FILES,
            acceptance_criteria=work.acceptance_criteria,
            reasoning_budget=8192,
            token_budget=6144,
            cost_budget=0,
            execution_permissions=("write_code",),
            policy_decision=policy.model_dump(mode="json"),
            required_output_schema=AgentRunResult.model_json_schema(),
            control_epoch=grant.epoch,
        )
        try:
            result = self.runtime.execute(request)
            usage = next(
                r for r in self.ledger.records("Usage", 1000) if r.get("run_id") == request.run_id
            )
            self.check_ownership(result.files_changed)
            self.git.apply(metadata, result.files_changed)
            self.git.commit(metadata, "CLAUDE")
            checks = self.git.verify(metadata, None)
            proof = self.test_candidate(grant, metadata)
            if proof["status"] != "PASS":
                raise ValueError(
                    "Approved offline candidate checks failed: " + proof.get("stderr", "")[-240:]
                )
            checks["checks"].append("Approved offline UI contract checks")
            run = ImplementationRun(
                owner="triad",
                work_item_id=work.work_item_id,
                builder="CLAUDE",
                provider=usage["provider"],
                model=usage["actual_model"],
                transport=usage["transport"],
                base_commit=base,
                change_commit=metadata["change_commit"],
                files=tuple(checks["files"]),
                tests=tuple(checks["checks"]),
                evidence=("run:" + request.run_id, "offline-check:" + proof["record_id"]),
            )
            self.quality.implementation(run)
            self.handoff(work, result, metadata, checks, "REAL")
            record = {
                "implementation_id": run.implementation_run_id,
                "work_item_id": work.work_item_id,
                "proposal_id": proposal.proposal_id,
                "git": metadata,
                "checks": checks,
                "usage": usage,
                "builder": "CLAUDE",
                "correction": list(correction),
                "engineering_grant": grant.model_dump(mode="json"),
            }
            self.record("ProductBuild", mission, **record)
            return record
        except Exception as exc:
            self.failed_build(mission, work, request.run_id, exc)
            current = self.host.store.get(work.work_item_id)
            if current.status == State.IN_PROGRESS:
                self.host.advance(
                    current,
                    State.FAILED,
                    "Candidate failed; no merge",
                    failure_reason=type(exc).__name__,
                )
            raise

    def test_candidate(self, grant, metadata):
        snapshot = {
            p: (Path(metadata["worktree"]) / p).read_text(encoding="utf-8")
            for p in grant.writable_files
        }
        proof = run_approved_checks(
            grant,
            snapshot,
            CHECK_SCRIPT,
            guard=lambda: self.ledger.guard(grant.agent, grant.work_item_id, grant.epoch),
        )
        proof["record_id"] = self.canonical.append(
            "EngineeringTestRun",
            {**proof, "work_item_id": grant.work_item_id, "commit": metadata["change_commit"]},
            owner="triad",
        )
        return proof

    def exact_checks(self, build, limits, *, after_review=False):
        grant = EngineeringGrant.model_validate(build["engineering_grant"])
        self.git = EngineeringGit(grant)
        checks = super().exact_checks(build, limits, after_review=after_review)
        proof = self.test_candidate(grant, build["git"])
        if proof["status"] != "PASS":
            raise PermissionError("Fresh independent host checks failed")
        checks["checks"].append("Fresh approved offline checks: " + proof["record_id"])
        return checks

    def debrief(self, mission, corrections=()):
        self.daily.refresh(mission)
        cycle = self.daily.current(mission)
        provider_call = self.call
        if any(r["cycle_id"] == mission for r in self.records.list("SequentialDailyProgram")):
            from products.triad.sequential import SequentialCycle

            flow = SequentialCycle(self)

            def provider_call(
                mission, agent, role, objective, context, *, schema, parent, excluded=()
            ):
                if role != "REVIEW" or parent != cycle["parent_work_item_id"] or agent in excluded:
                    raise PermissionError("Debrief review assignment mismatch")
                return flow.call(mission, agent, objective, context, schema=schema)

        context = {
            "required_tomorrow_keys": [
                "new_capability",
                "more_important",
                "less_important",
                "changed_assumption",
                "new_dependency",
                "risk_to_monitor",
                "next_cycle",
            ],
            "schema": Debrief.model_json_schema(),
            "required_corrections": corrections,
            "post_merge_verification": [
                r for r in self.records.list("DailyVerification") if r["cycle_id"] == mission
            ],
            "cycle": cycle,
            "inspections": self.rows("ProductInspection", mission),
            "builds": self.rows("ProductBuild", mission),
            "qa": self.rows("ProductQA", mission),
            "merges": self.rows("ProductMerge", mission),
            "turns": self.rows("ProductTurn", mission),
            "no_change_decisions": [
                r for r in self.records.list("ProductNoChange") if r["cycle_id"] == mission
            ],
            "failures": self.rows("ProductBuildFailure", mission),
            "resource_extensions": [
                r
                for r in self.canonical.list("ResourceExtensionRequest")
                if r.get("work_item_id") in {w["work_item_id"] for w in cycle.get("work_items", [])}
            ],
        }
        drafts = [r for r in self.records.list("DailyDebriefDraft") if r["cycle_id"] == mission]
        if corrections and drafts:
            context["previous_debrief"] = drafts[-1]["debrief"]
        # Avoid resending every candidate source/diff in a strategic explanation.
        for row in context["builds"] + context["qa"]:
            row.pop("checks", None)
        for key in ("implementation_runs", "qa_runs", "correction_runs", "reviews"):
            for row in context["cycle"].get(key, []):
                row.pop("checks", None)
        _, _result, document, usage = provider_call(
            mission,
            "CLAUDE",
            "REVIEW",
            "Write a candid Daily Debrief using supplied actual evidence. Return one Debrief JSON in analysis_artifacts. "
            "When previous_debrief is supplied, revise that draft: address every required correction in the affected fields, "
            "preserve independently verified facts, and do not regenerate unrelated passages or reintroduce prior claims. "
            "No fictional idle-model contributions. Date from UTC timestamps. overall_status VERIFIED_AWAITING_DEBRIEF_QA. "
            "Finished time is the latest supplied deployment verification or no-change health verification time, not future cycle close. "
            "NO_CHANGE turns preserve the baseline: do not claim they built, merged or deployed anything. "
            "Distinguish OBSERVED/EXPECTED/HYPOTHESIZED effects. "
            "Explicitly account debt and failures, classify proposed gain modestly with evidence, and answer all seven tomorrow questions. "
            "Debt records and observations are distinct: legacy OPEN records may contain positive QA observations, not defects. "
            "Only an explicit recorded resolution proves debt retirement. A scope check or passing test alone cannot retire debt. "
            "Separate residual verification limitations from newly introduced defects; cite record IDs and actual status. "
            "No actions/claims/commands/tests/files. Keep explanation useful and concise.",
            context,
            schema=Debrief,
            parent=cycle["parent_work_item_id"],
        )
        if document.cycle_id != mission:
            raise PermissionError("Debrief refers to another cycle")
        # Draft identity belongs to Core; native revisions may reuse their suggested ID.
        document = document.model_copy(update={"debrief_id": uid()})
        draft_id = self.daily.draft(document)
        commit = "debrief:" + digest(document.model_dump(mode="json"))
        build = ImplementationRun(
            owner="triad",
            builder="CLAUDE",
            provider=usage["provider"],
            model=usage["actual_model"],
            transport=usage["transport"],
            base_commit=cycle.get("verified_revision") or cycle["merge_commit"],
            change_commit=commit,
            files=(),
            tests=("Debrief schema and actual evidence supplied",),
            evidence=("run:" + usage["run_id"], "draft:" + draft_id),
        )
        self.quality.implementation(build)
        from typing import Literal

        from pydantic import Field
        from trading_core.work import Record

        class Assessment(Record):
            classification: Literal["NONE", "LOW", "MEDIUM", "HIGH", "TRANSFORMATIVE"]
            reason: str = Field(min_length=1)
            action: Literal["CONFIRM", "DOWNGRADE", "UPGRADE_WITH_EVIDENCE", "DISAGREE"]

        work, review, assessment, reviewed_usage = provider_call(
            mission,
            "CODEX",
            "REVIEW",
            "Independently challenge this exact Daily Debrief against actual evidence: attribution, unsupported strategy/data readiness, effects, gain, missing debt or failures. "
            "Return review_decision APPROVE/REQUEST_CHANGES/REJECT and findings. Put exactly one Assessment JSON in analysis_artifacts using supplied schema. "
            "You control final gain classification. Do not claim tests/browser you did not execute; host test results are supplied evidence. No files/actions/tests/commands/claims.",
            {
                "debrief": document.model_dump(mode="json"),
                "actual_evidence": context,
                "assessment_schema": Assessment.model_json_schema(),
            },
            schema=Assessment,
            excluded=("CLAUDE",),
            parent=cycle["parent_work_item_id"],
        )
        decision = {
            "APPROVE": "PASS_WITH_OBSERVATIONS" if review.findings else "PASS",
            "REQUEST_CHANGES": "CHANGES_REQUIRED",
            "REJECT": "REJECT",
        }.get(review.review_decision, "BLOCKED")
        qa = QARun(
            implementation_run_id=build.implementation_run_id,
            qa_work_item_id=work.work_item_id,
            qa_agent="CODEX",
            qa_provider=reviewed_usage["provider"],
            qa_model=reviewed_usage["actual_model"],
            reviewed_commit=commit,
            agent_capabilities_used=("document_analysis", "structured_output"),
            tests_repeated=("Independent debrief evidence review",),
            findings=review.findings,
            required_changes=review.findings
            if decision not in {"PASS", "PASS_WITH_OBSERVATIONS"}
            else (),
            evidence=(
                "run:" + reviewed_usage["run_id"],
                "strategic-assessment:" + digest(assessment.model_dump()),
            ),
            decision=decision,
            execution_mode="REAL_PROVIDER",
        )
        self.quality.review(qa)
        if decision not in {"PASS", "PASS_WITH_OBSERVATIONS"}:
            return {
                "decision": decision,
                "required_changes": qa.required_changes,
                "qa_id": qa.qa_run_id,
            }
        self.daily.publish(
            draft_id,
            build.implementation_run_id,
            classification=assessment.classification,
            reason=assessment.reason,
            reviewer_action=assessment.action,
        )
        return {"decision": decision, "draft_id": draft_id}

    def run_daily(self, **kwargs):
        from products.triad.sequential import SequentialCycle

        return SequentialCycle(self).run(**kwargs)

    def run_legacy_daily(
        self, *, scheduled=False, cycle_id=None, verify=None, expected_epoch=None, schedule_id=None
    ):
        if verify is None:
            raise PermissionError("Trusted post-merge verification is required")
        with self.host.store.lease("triad-daily-product-execution"):
            from contextlib import nullcontext

            with self.host.store.lease("triad-daily-schedule-slot") if scheduled else nullcontext():
                cycle = self.daily.create(
                    scheduled=scheduled,
                    cycle_id=cycle_id,
                    expected_epoch=expected_epoch,
                    schedule_id=schedule_id,
                )
            mission = cycle.cycle_id
            try:
                self.readiness(mission)
                self.transition(mission, "INSPECTING", ["Current service/product inspection"])
                self.inspect(mission)
                self.transition(
                    mission,
                    "SELECTING",
                    ["Three independent frontier inspections and local synthesis"],
                )
                proposal = self.select(mission)
                self.transition(
                    mission,
                    "BUILDING",
                    [proposal.proposal_id],
                    selected_proposal=proposal.model_dump(mode="json"),
                )
                build = self.build(mission, proposal)
                for attempt in range(3):
                    self.transition(mission, "AWAITING_QA", [build["implementation_id"]])
                    qa = self.qa(mission, proposal, build)
                    if qa.decision in {"PASS", "PASS_WITH_OBSERVATIONS"}:
                        break
                    if qa.decision != "CHANGES_REQUIRED" or attempt == 2:
                        raise PermissionError(
                            "Independent QA did not pass; candidate stays unmerged"
                        )
                    self.transition(mission, "CORRECTING", [qa.qa_run_id])
                    build = self.build(mission, proposal, correction=qa.required_changes)
                self.transition(
                    mission,
                    "MERGING",
                    [qa.qa_run_id],
                    implementation_runs=(build,),
                    qa_runs=(qa.model_dump(mode="json"),),
                )
                merged = self.merge(mission, proposal, build, qa, operator_authorized=True)
                self.transition(
                    mission,
                    "VERIFYING",
                    [merged["merge_commit"]],
                    merge_commit=merged["merge_commit"],
                )
                verification = verify(merged)
                self.canonical.append(
                    "DailyVerification",
                    {
                        "cycle_id": mission,
                        "merge_commit": merged["merge_commit"],
                        **verification,
                        "verified_at": now().isoformat(),
                    },
                    owner="triad",
                )
                if verification.get("status") != "PASS":
                    raise PermissionError("Post-merge verification failed")
                self.transition(mission, "DEBRIEFING", ["Post-merge verification passed"])
                corrections = ()
                for _attempt in range(3):
                    debrief = self.debrief(mission, corrections)
                    if debrief["decision"] in {"PASS", "PASS_WITH_OBSERVATIONS"}:
                        break
                    corrections = debrief["required_changes"]
                else:
                    raise PermissionError("Debrief independent review did not pass")
                self.transition(
                    mission,
                    "COMPLETED",
                    ["Reviewed debrief published and post-merge checks passed"],
                )
                return self.daily.current(mission)
            except Exception as exc:
                current = self.daily.current(mission)
                if current["status"] not in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}:
                    self.transition(
                        mission,
                        "BLOCKED",
                        [type(exc).__name__],
                        failures=(
                            *current.get("failures", []),
                            {"code": type(exc).__name__, "message": str(exc)[:500]},
                        ),
                    )
                raise
