"""Current, product-owned planning context for the autonomous daily program."""

import ast
import hashlib
import json

from pydantic import Field, model_serializer
from trading_core.work import Record

from products.triad.sequential_application import (
    PLAN_PATH,
    ApplicationContribution,
    ApplicationPlan,
    CurrentApplicationContribution,
)

# Immutable Day 6 assessments remain available as history, never current grants.
HISTORICAL = frozenset(
    "products/triad/docs/" + name + ".md"
    for name in (
        "CAPABILITY_INVENTORY",
        "IMPROVEMENT_BACKLOG",
        "INSPECTION_BASELINE",
        "PRODUCT_MAP",
    )
)
CORE_REFERENCES = {
    "app/trading_core/product_sdk.py": "Pure product-owned research input adapter, installed read-only in the product test image",
    "app/trading_core/research/contracts.py": "Research data, experiment and result contracts",
    "app/trading_core/research/engine.py": "Deterministic research engine; inspect supported strategies",
    "app/trading_core/research/planning.py": "Walk-forward window construction; not an optimizer",
    "app/trading_core/ownership.py": "Product ownership and access boundaries",
}


class Alternative(Record):
    change: str = Field(min_length=1)
    expected_value: str = Field(min_length=1)
    reason_not_selected: str = Field(min_length=1)


class ValuePlan(Record):
    initiative: str = Field(min_length=1)
    user_outcome: str = Field(min_length=1)
    why_highest_value: str = Field(min_length=1)
    alternatives: tuple[Alternative, ...] = Field(min_length=2)
    next_steps: tuple[str, ...]
    dependencies_or_blockers: tuple[str, ...]
    mission_contribution: str | None = None
    major_gaps: tuple[str, ...] | None = None
    application_contribution: ApplicationContribution | None = None

    @model_serializer(mode="wrap")
    def preserve_historical_plan(self, handler):
        data = handler(self)
        for key in ("mission_contribution", "major_gaps", "application_contribution"):
            if getattr(self, key) is None:
                data.pop(key, None)
        return data


class CurrentValuePlan(ValuePlan):
    mission_contribution: str = Field(min_length=1)
    major_gaps: tuple[str, ...] = Field(min_length=1)
    application_contribution: CurrentApplicationContribution


def token_targets(agent):
    # Operator asked to conserve Codex while retaining its daily turn and scope.
    return (4096, 3072) if agent == "CODEX" else (8192, 6144)


def token_guidance(agent):
    reasoning, output = token_targets(agent)
    return (
        f" Token guidance: aim for {reasoning} reasoning and {output} output tokens; "
        "these are advisory targets, not cutoffs. Use more when needed for a complete correct result. "
        "Reuse supplied evidence and avoid repetitive analysis; do not reduce product value or QA quality. "
    )


def core_context(git, baseline):
    references = {}
    for path, purpose in CORE_REFERENCES.items():
        source = git.git("show", baseline + ":" + path)
        references[path] = {
            "purpose": purpose,
            "sha256": hashlib.sha256(source.encode()).hexdigest(),
        }
        if path.endswith("/engine.py"):
            # Discovery signatures avoid repeatedly sending the engine implementation.
            tree = ast.parse(source)
            references[path]["public_signatures"] = [
                f"{node.name}({ast.unparse(node.args)})"
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not node.name.startswith("_")
            ]
            references[path]["source_scope"] = (
                "Public function signatures only; implementation omitted"
            )
        else:
            references[path]["source"] = source
    return {
        "source_revision": baseline,
        "references_read_only": references,
        "availability": (
            "These are existing source interfaces, not proof of product access to live services. "
            "The pure product_sdk and its listed Core dependencies are installed read-only in the reviewed "
            "offline product test image. ProductResearch('triad') accepts explicitly supplied validated ResearchInput "
            "and Experiment objects, preserving owner, dataset identity, source provenance and fixture/real mode. "
            "Supply a product Strategy implementation when needed; built-in strategies validate the engine only. "
            "Use real SDK integration tests, not mock-only or copied Core implementations. Browser tests use "
            "Playwright Chromium inside the same offline boundary, named tests/products/triad/browser_*.py. "
            "Serve only container-local candidate assets/API or explicitly labeled fixtures; no live provider calls. "
            "No network, host database, credentials, or other product records are granted. "
            "Do not instantiate unscoped host services. Request a product-scoped Core interface "
            "where one is missing, and continue independent product work. Stored research access, full calendars, "
            "non-minute adapter aggregation and Alpaca are not supplied by this SDK. Alpaca is not integrated."
        ),
    }


def planning_context(service, mission, baseline):
    charter = json.loads(
        service.git.git("show", baseline + ":app/products/triad/resources/product.json")
    )
    application_source = service.git.git("show", baseline + ":" + PLAN_PATH)
    application = ApplicationPlan.model_validate_json(application_source)
    # Use product-scoped records only. Old proposals are history, not current grants.
    history = {}
    fields = {
        "ProductProposal": ("mission_id", "proposer", "proposal", "attempt"),
        "ProductProposalReview": ("mission_id", "proposer", "decision", "summary"),
        "ProductTurn": (
            "mission_id",
            "agent",
            "status",
            "outcome",
            "merge_commit",
            "build",
            "qa",
            "implementation_id",
            "qa_id",
            "verified_revision",
            "no_change_id",
        ),
        "ProductBuildFailure": ("mission_id", "reason", "error_class"),
    }
    for kind, keys in fields.items():
        rows = [r for r in service.records.list(kind) if r.get("owner") == "triad"]
        history[kind] = [{"id": r["id"], **{k: r[k] for k in keys if k in r}} for r in rows[-12:]]
        if kind == "ProductProposal":
            for entry in history[kind]:
                proposal = entry.get("proposal", {})
                entry["proposal"] = {
                    key: proposal[key]
                    for key in ("title", "outcome", "problem", "files", "value_plan")
                    if key in proposal
                }
    return {
        "mission": charter["mission"],
        "product_scope": charter["product_scope"],
        "application_plan": {
            "path": PLAN_PATH,
            "source_revision": baseline,
            "sha256": hashlib.sha256(application_source.encode()).hexdigest(),
            "plan": application.model_dump(mode="json"),
            "schema": ApplicationPlan.model_json_schema(),
            "format": "Use these exact fields and status values. Put additional reasoning in decisions or architecture_reasoning; unsupported keys are rejected.",
            "ownership": "Agent-owned and revisable. Maintain this file with each adopted increment. It is not an operator feature checklist or proof of delivery.",
        },
        "current_direction": (
            "The product is the complete stock-trading application, not product.html or the current prototype. "
            "Assess major missing end-to-end capabilities against the mission before choosing a change. "
            "Identify a substantial initiative and an independently useful, testable contribution to it this turn; "
            "the initiative may span many days. The turn is a delivery increment, not a ceiling on ambition. "
            "Build one connected application. Maintain the persistent application plan: components, versioned contracts, "
            "producers, consumers, user workflows, decisions and the next missing connection. Choose and evolve your own "
            "architecture. Establish missing foundations before adding isolated tools. State which existing tools are "
            "adopted, adapted, deferred or replaced; their presence on a page is not proof they fit. "
            "Each provider independently chooses and implements its perceived highest-value product change. "
            "Build Triad's own useful trading application, tools and spaces; do not merely polish its shell. "
            "Core supplies shared infrastructure. Aegis is separately operator-directed; Triad does not build "
            "Aegis or depend on its roadmap. Choose your own initiative, compare meaningful alternatives, "
            "and continue or revise prior initiatives based on evidence. A small edit is valid when its "
            "impact warrants it; ease, low line count or avoiding substantive work are not value arguments."
        ),
        "current_authority": {
            "product": "Existing and new product UI, backend, analysis, documentation and tests",
            "protected": "Core, governance, Triad orchestration, credentials and other products",
            "obsolete_limits": "Day 6 document-only, three-file and 180-line grants are superseded",
            "tokens": "Advisory targets; no product token cutoff",
            "live_trading": "Disabled; no new account or execution authority",
        },
        "history": history,
        "history_scope": (
            "Latest 12 records per kind; compact proposal/decision summaries with record IDs. "
            "Old change text, acceptance checklists and individual findings omitted. "
            "Proposals are not proof of implementation."
        ),
        "historical_archives_not_current_policy": sorted(HISTORICAL),
        "shared_core": core_context(service.git, baseline),
        "cycle_id": mission,
    }
