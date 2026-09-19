# Day 5A provider acceptance — PASS

**Subsequent operator policy update:** subscription CLI and local Qwen daily
token/compute caps are now optional and off by default, replacing the temporary
midnight suspension described below. Paid API budgets remain enforced. See
[current usage-limit policy](USAGE_LIMITS.md).

## Final acceptance: 2026-09-18, 19:00 UTC

All four real connection tests and bounded WorkItems passed. The independently
reviewed CODEX → CLAUDE → GROK → LOCAL_QWEN documentation relay passed; all four
providers reported ONLINE and the live gate PASS. A later operator-requested update
removed hourly expiry and added automatic connection checks; setup proofs remain
valid until invalidated by configuration changes. This timestamped acceptance is
not a guarantee of future availability.

Connection proofs: Codex `2fd9c388-4ac0-4b6e-a81b-d8fb0b743a50`,
Claude `e238615f-fc9b-4152-bd42-1727a3feeba7`,
Grok `813f8a9f-6a03-4220-a890-21abaf000e67`,
Qwen `ed3472d3-e84e-4b53-a46b-afad77357445`.

Relay `1f5cece0-86d5-4a23-a41a-f6d51b9e2646` completed parent WorkItem
`6f130794-0628-4d22-8c05-8056fdea6e6e`. Codex identified a missing provider-settings
link in the operator guide. Claude and Grok read both original documents and
independently approved the recommendation; Grok did not receive Claude's verdict.
Qwen returned a structured summary. Supporting inspection/helper records remain
available for operator review.

The mission **identified** an improvement; it did not implement or merge it. Git
records retain source HEAD, exact hashes and working-tree status. PostgreSQL
retains WorkItems, policy/transport decisions, results, journals, handoffs, the
recommendation claim, reviews, billing and usage. Neo4j verification found all four
WorkItems connected to their mission and all eight Git-evidence, claim, review and
usage records. Projection pending/errors: 0/0. No strategy discovery job was started.

Actual models: gpt-6-astra, claude-sonnet-5, grok-4.6 (SUBSCRIPTION); qwen3:4b (LOCAL).
Paid API ceiling remains $0 and fallback NEVER. Failed relay attempts/diagnostics
remain recorded. Grok's adapter now verifies real file reads before requesting a
structured verdict, sums both prompt phases' usage, and permits up to 4,096 ACP
notifications. It retains tool, output, wall-time, per-frame and isolation limits.

Daily token/compute limits are suspended until **midnight Central tonight**
(`2026-09-19T05:00:00Z`), with authorization recorded as a ControlAction. Expiry is
checked on every reservation, independent of restart. Usage still accumulates;
normal 160,000-token / 1,800-second ceilings resume automatically. Paid spending,
per-run limits, path/tool grants, kill switch and review requirements are unchanged.
The provider page displays the expiry. Revisit conservative reservation charging
(including failed runs) alongside numeric defaults before setting permanent limits.

Automated results:

- Focused isolation/provider/budget checks: 103 passed (`logs/day5a-remaining-tests.xml`).
- Full regression: 293 passed; one outdated readiness fixture failed because it
  assumed the installed CLIs were unavailable (`logs/day5a-final-suite.xml`).
- Corrected test covers both availability states independently of host logins.
  Jobs/relay/native follow-up: 49 passed (`logs/day5a-final-recheck.xml`).
- Updated native checks: 53 passed (`logs/relay-native-tests.xml`).
- Stronger relay graph checks: 2 passed (`logs/relay-final-graph-tests.xml`).
- Ruff, provider-page JavaScript syntax and whitespace checks passed.

This is consolidated evidence, not a single clean full-suite invocation. Two
framework deprecation warnings remain. Real proof exports are
`logs/day5a-relay-proof.json` and `logs/day5a-final-provider-matrix.json`.
Reproduce real acceptance with
`.\.venv\Scripts\python.exe tools/check_provider_acceptance.py`; this uses real
subscription/local allowance and never raises budgets or enables paid fallback.

Live browser check after backend restart confirmed gate PASS, four ONLINE cards,
the midnight suspension notice, and no active runs. API health is OK; no isolated
execution containers remained.

## Historical checkpoints (superseded by the results above)

## Live individual acceptance — 2026-09-18

All four providers passed real WorkItem acceptance through the normal runtime,

policy, journal and usage paths. Frontier tests read the explicitly supplied

README through isolated tools and returned its title and structure; Qwen produced

a bounded local support summary. These were read-only checks, not a complete

change/review/relay acceptance.

| Agent | Actual model | WorkItem | Billing | Input / output tokens | Proof |

|---|---|---|---|---|---|

| CODEX | gpt-6-astra | PASS | SUBSCRIPTION | 37950 / 279 | `624cbdaa-2c83-4ebb-855f-5fb572c28e23` |

| CLAUDE | claude-sonnet-5 | PASS | SUBSCRIPTION | 11799 / 838 | `de809ce2-f3da-4a60-a937-1cf9a2f2ce9b` |

| GROK | grok-4.6 | PASS | SUBSCRIPTION | 8010 / 321 | `edb1936e-507e-40cd-ad2d-4ab8eb7ee84e` |

| LOCAL_QWEN | qwen3:4b | PASS | LOCAL | 613 / 106 | `67d705b7-1a86-4c06-98b4-9bb57e60a289` |

Grok's first two attempts remain recorded as failures. Acceptance exposed Windows

descendant cleanup timing and a bounded protocol queue that dropped bursts while

file tools ran. Cleanup now retries briefly and the reader applies backpressure

without increasing its queue size. The Grok retry passed. An HTTP refusal race

on Windows was also fixed by consuming bounded request bodies before replying.

51 native/protocol regression tests passed after these changes.

The operator explicitly approved temporary limits of 500,000 tokens and 2,400

compute seconds. Each run restored the original 160,000 / 1,800 limits in `finally`.

No API budget, fallback policy, scope or authority limit was widened. Execution

used SUBSCRIPTION for all frontier providers and LOCAL for Qwen.

**Still pending:** fresh standalone connection checks and the complete independently

reviewed relay. Individual WorkItem PASS does not mark the overall Day 5A gate PASS.

No strategy discovery has been enabled. Today’s normal token allowance is exhausted

by conservative reservations, including failed attempts.

## Claude/Grok integration checkpoint (2026-09-18)

Both isolated text integrations are implemented: Claude via a dedicated MCP

catalog; Grok via a verified ACP file-tool profile. Both subscription logins are

verified through vendor-supported metadata. Real no-inference CLI handshakes and

Docker read/proposal operations passed with `tools/check_native_agents.py`.

Tests: 68 protocol/provider/Codex regression checks passed in

`logs/native-agents-tests.xml`; nine disposable-database routing/accounting checks

passed in `logs/native-routing-tests.xml`. These use fixture model replies, not

live inference. Paid API fallback remains disabled. No daily limit was changed.

Live connection/README acceptance is pending: the current daily ledger reserves

135,454 of 160,000 tokens, leaving 24,546, below a native run's reservation. No

successful acceptance proof was fabricated. All provider ONLINE badges and the

full Day 5A gate still require current real execution evidence.

## Earlier Codex remote executor checkpoint

Codex app-server and the container executor use version `0.155.0-alpha.2.6`.

Real remote-protocol smoke checks established `file:///workspace` as the executor

environment, and a real subscription-backed turn read a supplied README through

the container. Native execution is currently restricted to read-only reviews.

The full Day 5A gate remains blocked; Claude/Grok execution and the relay are pending.

The normal Triad connection test passed with actual model `gpt-6-astra`, selected

from the account's default model catalog rather than hard-coded. Proof:

`6aa8d64f-0108-4926-afdd-2bb80e51e41c`; WorkItem:

`dec99f57-a1f9-484b-b22b-e80986493353`; exact summary `TRIAD_TRANSPORT_OK`.

Billing is SUBSCRIPTION and no paid API request was authorized.

README acceptance is not yet passing. Initial checks exposed a required remote

protocol environment field and an insufficient input reservation for the native

tool loop. Both were corrected. The latest native read produced an observed

`cat -- README.md`, source SHA-256, and 37,956 input / 265 output tokens, but its

proof `854b77f9-be4d-40e3-8cc6-b718dc7f8188` correctly remained failed because usage

exceeded the earlier reservation. It has not been relabeled successful.

The corrected reservation needs more than the remaining 29,201 tokens in the

configured 160,000 daily budget. A temporary increase to 220,000 was requested

from the operator before a fresh acceptance run; no budget was changed yet.

Checks: 78 unit/container tests passed (`logs/codex-executor-tests.xml`), 20 live

database regression checks passed (`logs/codex-integration-tests.xml`), and six

focused transactional budget/provider tests passed (`logs/codex-budget-tests.xml`).

These runs are separate, not one combined full-suite run. Subsequent mediation

unit checks also passed after adding the WorkItem tool-call cap.

## Offline execution boundary checkpoint

`OfflineSandbox` is implemented; see `ISOLATED_EXECUTION.md`. On this host,

`tests/test_isolation.py` and `tests/test_provider_control.py` passed together:

35 passed, zero skipped. Real Docker tests cover read-only input, approved edit

proposals, blocked external/host-loopback networking, no host mounts or inherited

credentials, non-root execution, dropped capabilities, no-new-privileges,

symlink rejection, output bounds, timeout/descendant cleanup, cancellation,

guard revocation and no leftover containers. Evidence: `logs/isolation-tests.xml`.

An initial path test caught `.` as an invalid grant and was corrected before this

passing run. Ruff and whitespace checks passed.

This does not complete the native CLI harness boundary: all three vendor

adapters still deny execution pending complete tool mediation and verification.

No provider authentication, paid fallback policy, or production authority was

changed by this checkpoint. The original provider gate below remains blocked.

## Provider checkpoint

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
