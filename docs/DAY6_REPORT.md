# Day 6 — Core intelligence and first autonomous product cycle

Date: 2026-09-19. Repository: `C:/Triad`. The evidence below distinguishes actual provider execution, independent host QA, deterministic fixtures and retained failures.

## Delivered Core capabilities

Core owns the append-only capability registry, configured agent registry, bounded specialist creation/lifecycle, capability routing, canonical implementation/QA/quality-debt records and generic Git enforcement. Triad supplies product decisions and consumes Core; Core imports neither product. `/core/intelligence` presents capabilities, agents, requests, verification, routing decisions and delegation limits as readable records. Registry adoption requires the exact reviewed payload digest and passing independent QA. Negative semantic revisions supersede older verified records even under a new ID.

Thirty-two governed capability versions were adopted after independent evidence review: **13 VERIFIED, 1 DEGRADED, 18 UNAVAILABLE**. Evidence/digests are in `docs/qa/DAY6_CAPABILITY_CANDIDATES.json` and the Core C QA report.

| Provider / actual observed model | Installed transport | Verified boundary | Limitation |
| --- | --- | --- | --- |
| OpenAI / gpt-6-astra | codex_cli; subscription | Structured output, isolated text read, document analysis | Installed role is REVIEW; no general repository editing, shell or Git grant |
| Anthropic / claude-sonnet-5 | claude_code_cli; subscription | Same read capabilities plus isolated text proposal | Non-executable staged text only; trusted host applies files in an isolated worktree |
| xAI / grok-4.6 | grok_build_cli; subscription | Structured output, isolated text read, document analysis | Text proposal is DEGRADED after actual NativeProposalEvidenceMismatch; not selected as builder |
| Ollama / qwen3:4b | Local Ollama | Structured output, local execution, private local processing | Observe-only support; no implementation or sole significant-QA authority |

Web, native X, shell, general repository editing, Git and MCP are UNAVAILABLE through the installed frontier boundaries. This describes present grants, not the unrestricted vendors' products. No marketing claim became verified truth. CLI subscription and local daily token/compute caps remain off, API cost ceiling remains $0 and fallback remains NEVER. Per-WorkItem output/time/authority limits remain enforced; provider subscription quotas are separate.

## Agents, lifecycle and routing

The four Core-owned static definitions are CODEX, CLAUDE, GROK and LOCAL_QWEN, persistent and ACTIVE. Frontier definitions retain tier 2 ceilings; actual product inspections/QA use tier 0 and builds tier 1. Qwen is tier 0 and not review-eligible. Effective execution requires both configured grants and verified provider/transport capabilities. A configured capability name alone grants no tool access.

Structured specialist requests are checked against the parent WorkItem, parent agent, owning product, current Control Plane and budgets. Creation decisions preserve ALLOW, DENY and REQUIRE_HUMAN_APPROVAL with reasons and grants; independent QA and review remain separate required pathways. Low-risk temporary creation can proceed without a new operator interaction. Persistent promotion requires distinct evidence of usefulness, independent QA and governance, not a usage count alone.

Conservative defaults: delegation depth 1, two children per parent, eight active specialists, four concurrent runs, zero creation spend, lifetime at most one hour. Atomic reservations enforce individual agent run/token grants; runtime checks separately enforce time/cost grants. Parent completion, expiry, disable and product pause remain effective; children cannot create authority. Canonical lineage links requests, parents, WorkItems, configured agents and results in PostgreSQL with database-namespaced Neo4j projections. No production specialist was needed for this bounded cycle; disposable QA demonstrated creation and lifecycle rather than pre-creating example agents.

Dynamic-agent evidence: `docs/qa/DAY6_CORE_B_QA.md` and `DAY6_CORE_C_QA.md`, with independent tests for allowed creation, privilege/path/tool/budget ceilings, recursion/depth/active ceilings, expiry/terminal parents, persistent promotion, concurrent reservations, runtime identity, product ownership and cross-database graph isolation.

## Independent implementation and correction QA

All host implementation segments were built by `/root` and reviewed by distinct delegated QA agents. These are host-independent QA runs in this Codex task, not misrepresented as CLI frontier calls. The autonomous product build and QA below have separately recorded REAL provider usage.

| Segment | Reviewer | Correction history and final evidence |
| --- | --- | --- |
| Core A capability/quality records | day6_qa_a | Initial CHANGES_REQUIRED: forged product QA, null discovery snapshot, omitted quality debt. Corrected run 16 passed; further typed-evidence correction received fresh17 passed and PASS. Report, initial/final source manifests and failed logs retained. |
| Core B configured/dynamic agents | day6_qa_b | Initial six findings, then two additional cost/projection findings; two correction rounds. Final75 regression tests and18 seam tests passed; PASS_WITH_OBSERVATIONS solely for graph namespace debt. |
| Core C routing/UI | day6_qa_c | Fixed cross-ID capability revocation and unsupported transport roles; fresh62 passed. Browser and clean installed package/SQL checks passed. PASS; B graph debt resolved by two-database test. |
| Product workflow and generic Git byte policy | day6_qa_a; UI evidence reviewed by day6_qa_c | Fixed read-journal actor, exact-source checks, missing capability gate and failure lifecycle; then required Review severity; then Windows CRLF checkout mismatch. Final60 regression tests plus fresh5 affected-root and5 source/QA-flow tests passed. Real disposable Git correction→new QA→merge and stale QA rejection demonstrated. |
| Inspection prompt | day6_qa_a | Two actual Claude output overruns retained; concise prompt corrected and independently checked,2 tests passed. Subsequent real Claude inspection succeeded. |
| Local synthesis and navigation | day6_qa_a / day6_qa_c | Smaller context and visible mobile entry point separately reviewed. Initial context-only change did not resolve actual local timeout; subsequent schema correction and fresh QA are recorded in DAY6_PRODUCT_SYNTHESIS_QA.md. Navigation served-page, syntax,2 integration checks and root319px browser navigation passed. |

Exact source revisions, all required changes and their resolution are in `docs/qa/DAY6_CORE_{A,B,C}_QA.md`, `DAY6_PRODUCT_FRAMEWORK_QA.md`, `DAY6_PRODUCT_BROWSER_QA.md`, `DAY6_PRODUCT_PROMPT_QA.md`, `DAY6_PRODUCT_SYNTHESIS_QA.md` and `DAY6_PRODUCT_NAV_QA.md`. Canonical implementation/QA IDs are indexed in the companion evidence snapshot. Core A initial failed and final passing revisions are canonical; its intermediate16-test correction has document/log provenance but no separately preserved exact source manifest, so it is not represented as an exact independently addressable Git revision.

During early Core B fixture QA, legacy static Agent graph identities collided with production links. The links were restored from canonical PostgreSQL evidence:87 work-agent,23 review and47 handoff links, zero missing after recovery. UUID records and database-namespaced ConfiguredAgent identities now prevent that tested collision. This incident is retained in `logs/day6-agent-link-recovery.json`. No current unresolved graph-loss claim is hidden. Canonical resolution81a40fc3-1849-4548-ae90-f2059a5b9cb9 closes debt32d0f816-d057-4189-96ed-2848300de6cd using Core C QA7597d99a-d96e-47a0-b1e4-fc04a07e1400; the original immutable OPEN record remains historical evidence.

## Product charter and authority

The canonical charter states: “Triad is an autonomous system whose mission is to continuously build and improve the best trading application it can create.” It covers architecture, UX, data, research, strategies, backtesting, scanning, risk, portfolio, execution, brokerage, observability, testing, reliability, performance, operator workflow and self-improvement. That mission does not create new execution authority.

This first cycle retains the verified non-executable text grant: at most3 files and180 changed lines under approved `docs/improvements` or `research/improvements` roots. Broader code-writing, shell, market-data or broker authority was not silently enabled. Current product map, inventory and backlog preserve each frontier assessment and its limitations; Core administration is not counted as a Triad product feature.

Product UI: `/triad/development` exposes current state, map, inventory, backlog, selected proposal, builder/QA/merge, product specialists and development journal. Evidence and merged artifacts are human-readable; merged artifacts are served only after ownership and exact recorded hash checks. The legacy real-cycle path fails closed and its old launch button now links to this lifecycle. Scheduled autonomy remains disabled.


## Actual independent product inspections

Mission `day6-product-20260919`. Each frontier read the same neutral baseline, product server and product contract sources; no prior frontier conclusions appeared in later initial inspection contexts. No P2P knowledge, preferred human indicator or legacy strategy library was supplied. Models report bounded source findings, not an exhaustive repository inspection.

- **CODEX / gpt-6-astra:** Triad provides governed improvement workflows and reproducible fixture research. Worker health visibility is limited; real-market research remains unavailable. WorkItem `951cf0dc-bf6e-44a8-a75b-5d1bb3cd41d3`; run `2342e009-bc18-446e-a9a6-3ca28d254d15`.
- **CLAUDE / claude-sonnet-5:** Two areas inspected: the research lab has no real market data, and the operator workflow is split across three surfaces. One candidate proposed: a lab evidence-gap status view. WorkItem `b1553932-24fb-4080-8df9-ee1cf8869509`; run `e77a21d7-81fc-4cad-a518-5027a6f3a9ad`.
- **GROK / grok-4.6:** Independent inspect: operator shell exists; Day 6 development contracts exist; live trading and real market remain out of grant. WorkItem `11b96d0f-96cb-4a1d-a908-63f7b83f23ad`; run `da21d70b-9bb2-4fb6-8551-0feac382e154`.

**Local Qwen / qwen3:4b:** Triad's workflows are governed but lack real-market research and worker health visibility; operator workflow split across surfaces. Evidence gaps persist in live trading and market data. WorkItem `0250289f-4da7-4deb-8ac0-112a9de46d41`; run `342c7ec1-226d-4323-aa8b-e885a7a41409`. Successful local execution: 30.81s, 637 input / 47 output tokens. Observe-only; no approval authority.

The resulting seven area assessments and four candidates are preserved in [product map](../products/triad/docs/PRODUCT_MAP.md), [capability inventory](../products/triad/docs/CAPABILITY_INVENTORY.md) and [improvement backlog](../products/triad/docs/IMPROVEMENT_BACKLOG.md). Differing inspector judgments and deferred executable work are retained.

## Selected improvement

**Define real-market research readiness criteria** — proposal `5a69eee9-7602-458a-b72f-28e91c44c0cc`, candidate `6f35d9c3-cf35-4b61-936f-fdbefc6f2521`.

Fixture-backed research cannot establish readiness for experiments on real market data; the supplied baseline reports the market provider unavailable.

Provides actionable evidence requirements at LOW risk and small effort. It is more concrete than a general evidence-gap inventory and feasible within this cycle, while worker readiness implementation requires executable-change authorization and agreed readiness semantics.

Selected builder: **CLAUDE**. Required verified capabilities: structured_output, isolated_text_proposal. Permission: write_docs; LOW risk; existing agent sufficient. No new production specialist was created. Control Plane approval is preserved and repeated at dispatch and merge.

## Actual product build and separate QA

The delivered artifact is [docs/improvements/real-market-readiness-criteria.md](../docs/improvements/real-market-readiness-criteria.md), one 24-line proposed-readiness document. It specifies evidence and decision rules for provider provenance, session coverage, data quality and reproducibility, explicitly marking real-data evidence unverified and separating data readiness from strategy validation. This is a documentation improvement, not a market-data connector or an executable feature.

| Property | Actual evidence |
| --- | --- |
| Builder | CLAUDE / anthropic / claude-sonnet-5 / claude_code_cli |
| Billing | SUBSCRIPTION; no paid API fallback |
| Builder WorkItem / ImplementationRun | `dc66fd39-af0c-4a56-b128-c26a29cd8587` / `93e23303-36df-4446-ae19-2a9f096f3b00` |
| Branch | `codex/triad/claude/dc66fd39-af0c-4a56-b128-c26a29cd8587` |
| Base / change | `6838637d256f91c234faf70ffcb8f8ccf53ccb6a` / `36eaf49957bb3ba6532aed099878fd3927b1632e` |
| QA agent / model | CODEX / gpt-6-astra / codex_cli |
| Separate QA WorkItem / QARun | `2ff8c497-d78e-4033-bc79-41cfb8c23755` / `b797f54a-dd17-4402-946e-9cbb97aa7cac` |
| QA decision | **PASS_WITH_OBSERVATIONS** |
| Review / merge | `0208724f1b41ed6014e38a0e7eb67b79a7784650` / `445f1666115209fcf2c4cd04270f38579729b261` |

Host deterministic checks, repeated around QA/merge: approved path scope, file and diff ceilings, UTF-8 and Markdown/JSON validation, secret exclusion, git diff --check. The model reviewer received original source read grants plus the exact proposed worktree content, diff, hashes and host-check evidence. It had no shell/browser authority and did not claim to execute those checks itself. Parent linkage connects the separate QA WorkItem to its builder.

The native builder staged text through offline isolated tools; the trusted host applied and committed it in the isolated Git worktree. Main remained clean during build and merge. Passing independent QA, exact unchanged source, ownership, Control Plane, current kill-switch epoch and standing operator authorization were all required before the protected merge. Failed/stale QA and source mutation are independently tested rejection paths.

Post-merge verification independently matched the raw file, change-commit Git blob and merge-commit Git blob to SHA-256 `d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9`. Canonical artifact owner is Triad. No executable files changed in the autonomous product improvement.

## Retained failures and correction sequence

- Claude inspection attempts failed at 2,881 and 2,429 output tokens against the enforced 2,048 cap. Both failed WorkItems/Usage remain. The independently reviewed concise prompt produced a successful third inspection.
- Two Qwen summaries timed out at120s. Smaller input alone was insufficient. Independent review found the full frontier response schema was incompatible with the strict local SUPPORT decoder; the corrected compact schema and smaller256-token generation cap received new adapter-level QA, then the actual local run succeeded. Unknown usage on timed-out calls remains unknown, not zero measured consumption.
- First Claude build WorkItem `6a612caa-2270-40da-8bd8-16078432019b`, ImplementationRun `783f1e14-caf1-4d57-b610-8366e23c9ed3`, failed NativeProposalEvidenceMismatch; reported output2,836 also exceeded2,048. Its native event identifies claude-sonnet-5 while Usage.actual_model is null, which is preserved. Independent host QA returned BLOCKED. The unchanged clean isolated checkpoint was explicitly reconciled; nothing was applied or merged from that attempt.
- A fresh Claude correction used the same selected proposal and authority, shorter content and exact staged/final-content instructions. Its real implementation succeeded with1,858 output tokens. The new separate Codex QA reviewed its exact commit and returned PASS_WITH_OBSERVATIONS before merge. The original failed worktree and canonical failure remain recoverable.

No runtime assertion, source hash check, independent-QA gate or permission was relaxed to achieve completion. The cycle ran by explicit host invocation and checkpoint reconciliation; no automatic endless retry loop or daily scheduler was enabled.

## Quality debt

- **LOW / OPEN**, `6402c739-cc23-4e07-9beb-2157e538ff4c`: QualityDebt (non-blocking): Session coverage relies on an undefined agreed gap limit, and data quality relies on an undefined critical-finding classification. Before operational use, record these definitions and explicitly require nonempty expected coverage and completed quality checks so empty evidence cannot produce a passing decision. Source QA `b797f54a-dd17-4402-946e-9cbb97aa7cac`. Independent QA classified as non-blocking.

This observation is non-blocking for proposed documentation, and is a prerequisite before treating the criteria as an operational data gate. Grok native write capability remains DEGRADED; no unsupported web/X/shell capability is claimed. The older Core B graph-namespace debt is effectively resolved by the canonical resolution described above.

## Regression, data preservation and live status

- Broad regression:381 passed in `logs/day6-full-regression.log`, with two dependency deprecation warnings. This run predates the final product corrections; it is not represented as a full-suite run on the final bytes. Fresh independent affected suites after those changes are listed in the QA reports, including60+5+5 framework checks, the prompt/navigation checks and3 final SUPPORT codec checks. Counts overlap and must not be summed as unique tests.
- Final clean wheel installation passed: `logs/day6-final-package.log` and `logs/day6-final-package-assets.log`. The root-host installed-package smoke check loaded Core/Triad HTML/JS, navigation, config and migrations010/011, with imports asserted outside the source checkout.
- Live services after restart: Core8000, Triad8101 and P2P8102 healthy; PostgreSQL, TimescaleDB2.25.2, Neo4j, Ollama and Git up. Existing pages and assets returned200. Codex, Claude, Grok and Qwen all ONLINE; provider gate PASS; zero active provider runs. Evidence: `logs/day6-final-services.log`.
- P2P shell loads, zero assignments, human_directed mode and exchange CLOSED. P2P source/config is unchanged from the extraction baseline. No product findings were exchanged. Live brokerage execution, capital allocation, trading authority and scheduled autonomy remain disabled.
- Kill switch and policy gates were exercised through independent disposable tests, including kill-before-build, mid-run controls and protected merge; production authority was not toggled for demonstration.
- Historical151 artifact files remain byte-identical after the cycle. All59 baseline WorkItem IDs remain preserved. Staged migration up/down/up and two historical deterministic backtest comparisons passed in `logs/day6-data-regression.log`; old source fingerprints remain intact. This proves preserved fixture-engine behavior, not investment merit. Final artifact/ownership/projection evidence: `logs/day6-final-artifact-evidence.json`.
- Browser QA covered readable records, all new views, loading/empty/error/stale states, injection rendered as text, responsive layouts, console and navigation. Product fixture and final live interactions were performed by the root browser host and independently reviewed; reports explicitly identify that provenance. The independent Core C reviewer performed its own preview checks. Final live merged-artifact and UI evidence is included in the final acceptance report.

## Git, provenance and completion

Working branch: `main`. Core A091874a, B05fafcf, C8927755; product frameworkee08fdf; promptbb1bb53; synthesis/navigationfde92bb; corrected SUPPORT6838637; autonomous artifact36eaf49; independent review0208724; governed merge445f166. No push was performed. Existing failed/accepted worktrees and failure records are retained as evidence.

Preserved tags: `base/day5a-complete` and `base/trading-core-v1`. The reviewed completion documents and final acceptance report are identified by `base/day6-complete`; the final shell check verifies a clean working tree after that commit/tag. Canonical completion documentation QA is separately ingested after independent review, bound to that final commit.

Companion snapshot: `docs/qa/DAY6_REAL_CYCLE_EVIDENCE.json` preserves actual inspections/proposal/build/QA/merge/usage and the canonical quality/provenance index. PostgreSQL is authoritative. Development journal includes what was inspected, discovered, selected, routed, built, reviewed, corrected, merged and learned.

## Day 7 recommendation — not started

Make worker readiness and failure visibility a bounded product feature. Codex and Grok independently identified that the HTTP liveness endpoint can remain healthy while the background worker fails. Define readiness separately from liveness, show last successful work and sanitized failure/retry state, and test healthy, stalled, failed and recovering paths. Review the narrowly scoped executable-change grant before any autonomous code-writing; preserve Core governance and independent QA.

Before operational use of the new research-readiness document, resolve the recorded coverage/critical-quality definitions and require nonempty evidence. This is retained quality debt, not a claim that real-market readiness is achieved. No Day7 implementation or ongoing autonomous schedule was started.
