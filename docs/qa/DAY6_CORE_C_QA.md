# Day 6 Core C — independent QA

Final verdict: **PASS**, after grouped correction and fresh independent QA. Reviewer: independent delegated Codex agent `/root/day6_qa_c`; builder `/root` did not act as this verifier. Implementation base: `05fafcf24ad24b3fe0ad929f07925817f64bf857`; exact accepted uncommitted files are recorded in `DAY6_CORE_C_QA_FINAL_HASHES.json`. No implementation files were edited by this reviewer. Initial CHANGES_REQUIRED findings and failed evidence are preserved below, bound to `DAY6_CORE_C_QA_INITIAL_HASHES.json`.

## Required corrections

1. **DAY6-C-001 (HIGH): semantic capability revocation can be bypassed by a new record ID.** An independently approved DEGRADED/RESTRICTED update with a new `capability_id`, but the same provider/model/transport/capability, leaves the earlier VERIFIED version eligible. The operator proposal form generates new IDs. `Capabilities.current` selects by ID, and routing discards degraded rows before forming its capability map. The adversarial test successfully routes CODEX after such a revocation. Effective truth must use the latest governed semantic capability revision, including negative revisions. Preserve the original history.
2. **DAY6-C-002 (MEDIUM): unsupported transport roles can receive a valid capability route.** A `documentation_audit` WorkItem with SUPPORT requirements routes to Codex CLI although the installed Codex transport permits REVIEW only. Capability fit must include the installed transport's supported execution role, before creating the assignment; recheck this at dispatch.

Both tests are retained in `tests/test_day6_qa_c.py`. Failed output: `logs/day6-qa-c-adversarial.log` — 2 failed, 5 deselected, 15.53 seconds. These findings were jointly identified during source review and reproduced independently by QA. Both are resolved and passed in the fresh final run described below.

## Tests and evidence

- `logs/day6-qa-c-initial.log`: 56 passed in 188.56 seconds. Independent additions exercise role/executor substitution, latest same-ID capability revocation, read-only assets, operator authentication/origin checks, rejection of unreviewed adoption, plus a real two-database graph probe. Repeated routing, dynamic agent, prior A/B QA and architecture tests. This run began before the two additional failing probes were added; it is not evidence that those probes passed.
- `logs/day6-qa-c-namespace-diagnostic.log`: explicit repeat of the two-database probe, 1 passed in 11.74 seconds. It creates separate disposable PostgreSQL databases sharing Neo4j, seeds the same static executor names, creates specialists/delegations and independent implementation/QA records, disables CODEX in only one database, and checks namespace-specific definitions, lifecycle, request/creation/delegation and build/QA edges. This satisfies the technical acceptance check for prior debt DAY6-B-QD-001; acceptance still depends on the complete corrected Core C revision.
- `logs/day6-qa-c-production-evidence.json`: read-only inspection of all 32 pending production capability proposals. Canonical payloads and SHA256 digests match; runtime references resolve to actual REAL usage and transport/native evidence. Counts: 13 VERIFIED, 1 DEGRADED, 18 UNAVAILABLE. Claude text proposal has actual successful offline native staging; Grok's latest write probe failed and remains DEGRADED. No shell/web/X/general repository editing/git/MCP authority is presented as verified. No inference was invoked by this QA evidence check and no provider settings were changed.
- The Core capability-adoption path revalidates the typed payload digest, and the repeated builder adversarial test rejects a forged product proposal borrowing a reviewed digest. Prior A/B protected-kind and immutable-source projection probes pass.
- P2P implementation/configuration have no changes in this segment (`git diff --name-only -- app/products/p2p config/p2p` empty).
- Independent clean wheel build/install passes (`logs/day6-qa-c-package.log`). Since the existing helper exercises prior routes, an additional independent installed-package probe checks the new `/core/intelligence` and `/assets/intelligence.js` plus packaged SQL migrations 010/011; passes in `logs/day6-qa-c-installed-assets.log`. Import location is asserted to be inside the clean installation.

## Independent browser QA

Used the disposable preview at `http://127.0.0.1:8006/core/intelligence` through browser UI automation. No production authority was mutated. All six views were exercised: provider capabilities, agent registry, agent requests, capability verification, routing decisions and delegation limits. Capability evidence opens as labeled readable sections; cards distinguish CLAIMED/PENDING, ACTIVE/EXPIRED, ALLOW/DENY/REQUIRE HUMAN APPROVAL. Expired filtering and unmatched searches work. Empty routing state is informative. Pending adoption prompts for the local operator token; a deliberately invalid fixture token plus the preview origin yields a readable `Untrusted origin` error and no mutation. Backend TestClient separately verifies authentication and origin enforcement. Controls were relocked and the temporary QA tab closed.

At 390×844, navigation/buttons/cards wrap without horizontal overflow (document width 375, viewport 390); visual screenshot inspected. Default viewport restored. Browser warnings/errors were empty before the expected denied mutation. No raw JSON is used as the primary evidence display.

## Optional observations

- **DAY6-C-QD-001 (LOW):** request reasons still show tokens such as `authority_ceiling` and `bounded_parent_grant; no_creation_spend; temporary_lifetime`. Translate them into short operator prose when convenient.
- **DAY6-C-QD-002 (LOW):** entering any nonempty token changes the button to “Controls unlocked” before the server validates it. Server authorization remains enforced; a “Token entered” label or successful validation would more accurately describe the state.

If left unresolved in an eventual PASS_WITH_OBSERVATIONS, retain these as canonical QualityDebt rather than hiding them.

## Final correction review

The builder corrected effective capability selection to use the latest governed provider/model/transport/capability tuple, including negative revisions under a different proposal ID. Installed transport role constraints now participate in routing and the same candidate check is repeated at dispatch. The two original adversarial probes pass unchanged in their expected behavior.

`logs/day6-qa-c-final.log`: **62 passed in 201.51 seconds**, with `TRIAD_INTEGRATION=1`. Command: `.venv/Scripts/python.exe -m pytest tests/test_day6_qa_c.py tests/test_intelligence_routing.py tests/test_intelligence_agents.py tests/test_intelligence_capabilities.py tests/test_day6_qa_a.py tests/test_day6_qa_b.py tests/test_architecture.py -q`. This independently repeats all affected behavior and the two-database graph test. Only existing dependency deprecation warnings appear. QA test file passes Ruff.

Both optional UI observations were addressed and are closed: request reason words no longer contain underscore tokens; the new authenticated validation endpoint must succeed before controls report unlocked. Fresh browser testing against the restarted disposable preview confirms an invalid token is cleared, the dialog remains open with an inline error, and a subsequent Discover attempt requests authentication again. Backend tests confirm 401 without credentials, 200 with the valid test operator token/allowed origin, and 403 for the disallowed preview origin. The preview reused its original disposable database; production services and authority were not changed.

Fresh clean-package checks pass in `logs/day6-qa-c-package-final.log` and `logs/day6-qa-c-installed-assets-final.log`, including installed new Day6 HTML/JS and SQL migrations. All final manifest hashes were rechecked against disk with zero mismatches after these checks. P2P code remains unchanged. Initial negative evidence is retained, no additional Core C quality debt remains, and the verified configured-agent namespace correction permits closing DAY6-B-QD-001 for this accepted revision. This verdict covers Core C only; later product implementations still require their own independent QA.
