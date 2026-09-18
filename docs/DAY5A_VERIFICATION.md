# Day 5A verification — NOT COMPLETE

The provider-control implementation is in progress. Strategy discovery remains
blocked. No frontier CLI WorkItem or full Triad relay has passed.

Implemented: provider settings page and dashboard panel, explicit transport
identities, CLI detection/vendor login controls, Windows Credential Manager API
storage, API selection/fallback policies and one-time grants, budget authorization,
managed process lifecycle, HTTP model/transport/billing provenance and local
capability verification. No API credentials were installed and no paid API requests
were authorized during this implementation.

| Agent | Transport | Installed | Authenticated | Real WorkItem | Billing | Fallback | Status |
|---|---|---|---|---|---|---|---|
| CODEX | codex_cli | 0.155.0-alpha.2.6 | ChatGPT confirmed | NOT_RUN | SUBSCRIPTION | NEVER | BLOCKED: outer isolation |
| CLAUDE | claude_code_cli | 2.1.276 | No | NOT_RUN | UNKNOWN | NEVER | AUTH_REQUIRED + isolation |
| GROK | grok_build_cli | 1.0.34 | Unverified | NOT_RUN | UNKNOWN | NEVER | AUTH_REQUIRED + isolation |
| LOCAL_QWEN | ollama | 0.34.1; qwen3:4b | Local | PASS | LOCAL | NEVER | ONLINE at verification |

OpenAI, Anthropic and xAI APIs: NOT_CONFIGURED. This is acceptable for the intended
subscription gate but does not substitute for successful CLI WorkItems.

Remaining implementation: hard outer CLI isolation, native execution and result
parsers, actual command/file/Git evidence, verified Grok subscription authentication,
CLI model discovery, restart reconciliation, the three frontier acceptance WorkItems,
and the independent CODEX → CLAUDE → GROK → QWEN relay and its provenance.
Version compatibility for native execution is NOT_VERIFIED.

The first Qwen attempts failed because the new server process did not inherit
OLLAMA_MODELS and saw an empty directory. Those failures remain recorded; the server
was restarted with the existing `C:\AI\Models\Ollama` directory. Successful reruns,
if any, must be read from the verification records; no failure is rewritten as success.

Qwen's real connection test passed at 2026-09-18 14:09:50 UTC:
proof `4fc47345-4297-4fda-9f38-7536c8b7088d`, WorkItem
`812c0920-3605-498e-a9b9-e6edd26f3d0a`, exact response `TRIAD_TRANSPORT_OK`.
Its journal-summary WorkItem passed at 14:11:36 UTC:
proof `f8765a33-0088-4840-a210-e7f485d1a5bb`, WorkItem
`f44d72a3-c41e-4884-b65d-2250aab2df2b`. Both returned actual model `qwen3:4b`,
LOCAL billing and provider token usage through the existing controlled capability
route. End-to-end elapsed times were 93.05 and 104.72 seconds on this CPU host.

Evidence: `logs/day5a-provider-matrix.json`, `TransportVerification` and `Usage`
records, canonical WorkItems/journals, and the test report generated for this change.
Automated fixture passes never establish production ONLINE. Browser verification
uses the live local `/settings/ai-providers` page.

## Automated checks and browser verification

The full regression run collected 210 checks: 207 passed, with three historical
expectations failing because real cycles now stop before enqueueing and subscription
CLIs no longer require API budgets. Those expectations were updated for the new
contract. All seven targeted regression checks then passed. A final 23-check run
passed, covering the provider unit/integration checks, an added process-tree timeout
check, and the full simulated reviewed Git rotation. Latest evidence across these
runs covers 211 distinct passing checks. This is consolidated evidence, not a claim
of a single clean full-suite invocation. Original failures are retained in
`logs/day5a-tests.xml`; reruns are in `logs/day5a-regression-recheck.xml` and
`logs/day5a-final-targeted.xml`; summary is `logs/day5a-test-summary.json`.

Ruff passes. Both HTML pages' JavaScript passes Node syntax checks. Live browser
inspection verified the provider cards, Qwen inference/WorkItem PASS, permissions
dialog, explicit gate blocker, and the main dashboard Settings link. Provider status
API measured approximately 0.5 seconds after batching database reads. No provider
process was active at the final status snapshot; global API budget remained $0.
Neo4j outbox flush reported no error and no outstanding delivery in that flush.

## Git checkpoint

Branch: `codex/day5a-provider-control`, based on Day 4 commit `261dc07`.
The checkpoint intentionally does not claim Day 5A completion. Native CLI isolation,
execution and the real frontier relay must be implemented and verified before merge
as a completed Day 5A gate or before strategy discovery resumes.
