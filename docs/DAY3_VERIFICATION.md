# Day 3 verification — 2026-09-17

Day 3 implements bounded provider execution, proposal policy, daily rotation, isolated Git changes, independent review, cost/autonomy accounting, local Qwen support, persistent cancellation and the operator dashboard. Infrastructure and Day 2 behavior passed preflight before development. The credential-independent build is verified; a real cloud-to-cloud improvement/review mission remains BLOCKED. This report does not claim three real models completed a mission.

## Provider matrix

| Provider | Agent | Status / health | Interaction mode | Last test |
|---|---|---|---|---|
| OpenAI | CODEX | UNAVAILABLE: credentials/model not configured | UNAVAILABLE for real requests; separate SIMULATED fixture | 2026-09-17 19:21 UTC health; payload and outage tests |
| Anthropic | CLAUDE | UNAVAILABLE: credentials/model not configured | UNAVAILABLE for real requests; separate SIMULATED fixture | Same probe; structured transport/auth tests |
| xAI | GROK | UNAVAILABLE: credentials/model not configured | UNAVAILABLE for real requests; separate SIMULATED fixture | Same probe; structured transport/rate-limit tests |
| Ollama qwen3:4b | LOCAL_QWEN | AVAILABLE | REAL | 19:19 UTC structured support success; 19:21 UTC health |

Cloud models and per-token rates are deliberately unconfigured. No paid cloud inference was attempted. A successful mocked transport test proves adapter behavior, not live account/model compatibility.

## Actual repository cycle

Cycle `53a06c48-c699-4f6c-b405-e4aa4f04f139` used explicitly SIMULATED primary adapters against the actual repository, PostgreSQL and Neo4j. Each stage created a WorkItem, passed control-plane policy, read source evidence, proposed a scoped improvement, received proposal evaluation, returned structured content, wrote an isolated Git branch, passed host checks, and generated journal/handoff. Claude reviewed Codex; Grok reviewed Claude; both approved exact diffs and the broker merged them. Grok's own candidate reached its change commit, then the budget prevented Codex's review from dispatching.

At that stop, 143,521 tokens were reserved against 160,000. The reconstructed review envelope required 18,329 more (161,850 total). The third change stayed unmerged and its WorkItem became BLOCKED. Reservations and daily slots were not reset. The full three-member rotation passes in isolated integration tests with smaller fixture contexts; the real repository demonstration correctly stopped at its ceiling.

Real cycle `8a16bb3a-925e-4ff3-8131-94bad088fd1e` recorded three UNAVAILABLE providers, no agents run, no fabricated changes and a BLOCKED summary. Both cycles have PostgreSQL CycleSummary records and Markdown under `docs/vault/02_Journal/generated/cycle-<cycle-id>.md`.

## Every autonomous change and review

All entries below are SIMULATED model interactions with actual Git operations. Each change is one Markdown improvement note in `docs/improvements/<work-id>.md`.

| Worker / reviewer | Candidate | WorkItem | Outcome |
|---|---|---|---|
| CODEX / CLAUDE | Recovery documentation | c4a03e4e-3c30-4966-ad49-c0233d248bf9 | APPROVE; MERGED |
| CLAUDE / GROK | Provenance documentation | a4572167-fe2f-49ee-941b-d313679e91ed | APPROVE; MERGED |
| GROK / CODEX | Budget documentation | 79bcf269-e4a1-4998-b21a-02a1a4a9bdbd | BLOCKED before reviewer call; unmerged branch retained |

| Worker | Base commit | Change commit | Review commit | Merge commit |
|---|---|---|---|---|
| CODEX | 2e20e006191e6b05ce59c21248f26732cd8ab038 | c718f404b547a4029a542d00f14bea33f7c7e040 | c90dcff5e13f7f12cd50bbe09ab98779b29bb27b | ff21157e4a39a919914da4ad183ed88ca4caee62 |
| CLAUDE | ff21157e4a39a919914da4ad183ed88ca4caee62 | 147e2052aadecdb986a083cba459c65ddecb6c25 | 61a9d51196995eabb2067ca8aeb9163b77e7c658 | 2bfb0fe3051c5d054262ae21cfcae35818eaed72 |
| GROK | 2bfb0fe3051c5d054262ae21cfcae35818eaed72 | 6c718e28bb1f06101c9d23156331ea61cde2b602 | None: budget stop | None |

Branches are `codex/triad/<lowercase-agent>/<work-id>`. Review IDs: Claude `79bab5ad-1c50-49a5-a652-cbe549380f76`; Grok `596c5ff2-1e88-406b-912e-3baf00cab7c2`. Changes: Codex `94fe6ed7-bb8b-483a-921e-207a41f37a5b`; Claude `73236528-5284-4584-84ff-cf46b0e0af6b`; Grok `3e5da01b-6a95-42cb-a9fe-23452cabd3c4`. Review data and repeated scope, UTF-8/Markdown/JSON, secret, size and Git whitespace checks are canonical persisted records.

## Required verification matrix

Test names below refer to `tests/test_day3.py` and `tests/test_day3_integration.py`; retained Day 2 tests also run. `tools/verify_day3.py` rechecks actual persisted IDs, Git ancestry, service health, local usage, graph links, dashboard records and summary files. Machine evidence: `logs/day3-verification.json`; test evidence: `logs/day3-tests.xml`.

| # | Requirement | Implementation | Test / evidence | Result |
|---|---|---|---|---|
| 1 | Multiple provider types | AgentProvider + four HTTP transports | vendor_formats_preserve_envelope_and_validate_result; configuration matrix | PASS |
| 2 | Available real providers execute bounded work | Canonical runtime + Ollama support | Qwen work ca120986-e44f-451a-8371-09e2eb7c1bdc; Usage provider=ollama | PASS |
| 3 | Accurate unavailable reporting | Health states and explicit mode | real_unavailable_cycle_never_substitutes_simulation; actual blocked real cycle | PASS |
| 4 | Control Plane execution | Persisted policy and immutable WorkItem match | runtime_rejects_raised_budget_and_wrong_identity; actual policy records | PASS |
| 5 | Authority enforced | Role/path/tool/budget validation | unsafe_proposal_and_runtime_permissions_are_denied; scope tests | PASS |
| 6 | A real primary model implements improvement | Provider implementation path exists; fixture path exercised | Two actual Git merges used SIMULATED providers; no cloud credentials | BLOCKED |
| 7 | Different real model independently reviews | Exact-diff separate reviewer path exists | Two distinct simulated reviewers; full_rotation test; no cloud credentials | BLOCKED |
| 8 | Review before protected merge | Exact SHA, distinct identity, active policy checks | branch_isolation_review_before_merge_and_exact_rollback; rejected review test | PASS |
| 9 | Journal and handoff | Transactional Day 2 records | Actual three change WorkItems and helper; verifier checks kinds | PASS |
| 10 | Exact Git change | Branch/base/change/review/merge provenance | Commit table; verifier checks commit existence and ancestry | PASS |
| 11 | PostgreSQL operational history | Canonical records, reservations, controls | Live integration tests and persisted cycle records | PASS |
| 12 | Neo4j provenance | Durable outbox, work/commit/review/disagreement edges | full_rotation; conflicting_reviews_persist_edges_and_block_consensus; actual lineage | PASS |
| 13 | Approved Qwen support | Capability router, parent and depth bounds | Real helper summary; helper_scope_delegation_and_secrets; persisted count test | PASS |
| 14 | Daily autonomy/cost limits | Transactional reservations and daily unique slots | daily_slots_and_cost_token_compute_reservations; actual review budget stop | PASS |
| 15 | Kill switch | Persisted epoch, serialized dispatch/merge, polling | kill_switch_cancels_inflight_and_blocks_new_requests_merges_and_legacy | PASS |
| 16 | UI shows process | Nine views, record/work/graph inspectors, authenticated controls | Browser reviews and commit lineage, completed WorkItem inspector, populated overview; API auth tests | PASS |
| 17 | Cycle summary | Structured close record and Obsidian projection | Actual SIMULATED and REAL summary files; verifier | PASS |
| 18 | Traceable and reversible change | Recorded SHA plus separately reviewed Git revert | human_review_gate_and_runtime_rollback; original status ROLLED_BACK; actual demo metadata retained | PASS |

There are 16 PASS and 2 BLOCKED criteria, with no claim that simulation satisfies real-model criteria. Rollback was exercised against disposable Git repositories, not silently performed on the production demo.

## Security verification

Tests block secret-path reads, known credential-bearing output, provider error-body leakage, authority/budget increases, governance-path writes, executable/shell changes, review bypass, rejected/stale merge, live-trading permission requests, kill-switch bypass and unbounded helper recursion. Integration tests also cover wrong runtime identity, malformed/truncated outputs, unavailable providers, rate limits, authentication failures, conflicting reviews, human merge gates and crash recovery. A no-change result creates no unnecessary commit. Fixed host checks run; models cannot supply arbitrary shell test commands.

Known boundaries: trusted local Python process, no OS sandbox, no remote-host branch protection, no durable task queue and no guaranteed upstream HTTP cancellation. Current autonomous changes are nonexecuting text only. The scheduler is configured but disabled. No trading, strategies, migrations, self-training or agent-controlled governance were added.

## Cost and local support

Two REAL Qwen runs consumed 1,192 input and 154 output tokens, with 56.672 seconds combined measured provider wait. Latest run `55c04863-8201-4029-b9c0-eeaa6dacdccd` used 596 input / 92 output tokens in 35.125 seconds. Its WorkItem `ca120986-e44f-451a-8371-09e2eb7c1bdc` remains AWAITING_REVIEW; a successful summary is not claimed as independently verified. It accurately retained the supplied 120 processed / two missing-timestamp rejections.

Eight SIMULATED provider calls have zero model tokens/API cost. Total estimated API spend: **$0.00**. No cloud API calls. Electricity/hardware costs are not estimated. Daily reservations after both helpers: 148,232 tokens, 1,200 seconds, three improvement opportunities and $0.00. Reservations are intentionally more conservative than measured usage.

Two EvidenceCorrection records preserve discoveries without erasing original evidence: `correction-day3-helper-mode` explains an earlier legacy display field that labeled real Ollama as cloud; `correction-day3-budget-stop` explains the original generic PermissionError and the corrected BLOCKED change classification. New code fixes both mappings; original Usage and failure history remain retained.

## Git, checks and reproduction

Preflight baseline `afe6d23`; runtime implementation `9fe7be7`; UI/docs baseline `2e20e00`. Autonomous commit lineage is listed above. Final verification/tooling commits follow on main. The final machine report records the exact checked HEAD and clean working-tree result, avoiding a self-referential report hash.

Final suite: **133 passed, 0 failed, 0 errors, 0 skipped**, 130.59 seconds. Ruff passed; pip reported no broken requirements; secret exclusion and Git whitespace checks passed. Two upstream FastAPI/Starlette deprecation warnings do not fail tests. The read-only verifier may run while implementation docs are being committed; its final invocation is after commits and must report an empty working_tree. Full historical source/report snapshots are not silently rewritten to imply fresh Day 2 validation.

The unmerged third branch is evidence of a blocked attempt. Later changes to main make its original baseline stale; continuing it would require a fresh assignment and review under available future budget, not directly forcing its old branch into main.

## Genuine human actions and Day 4

To validate real cloud-to-cloud work, supply provider API credentials locally, choose supported structured-output model IDs and verified pricing, and explicitly authorize a bounded nonzero cloud budget through reviewed governance configuration. A Codex usage reset does not supply these API keys. Never paste keys into chat. No external account action is required for the local dashboard or Qwen.

Recommended Day 4: credentialed low-cost multi-provider evaluation, reviewer-quality measurements and a durable worker/recovery queue, retaining these authority boundaries. Do not expand into live trading. Day 4 has not been started.
