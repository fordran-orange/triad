# Day 7 — Core hardening and integration foundation

All implementation segments passed independent QA and the final complete regression
passed 535 tests. This report and its acceptance manifest form the release candidate;
the completion tag is created only after the final independent verdict and Core
governance check. No next product cycle is started by this build.

## Baseline and preservation

The exact Day 6 completion revision was
`f1835049aeb4778ec682f0c684d8cec12234a28c`. A fresh complete regression passed:
**396 tests in 714.48 seconds**. This replaced reliance on the older 381-test run.
Core, Triad, the preserved product shell, services, provider gate, data/backtest
outputs, installed package and browser surfaces were separately checked.
See `qa/DAY7_PRECHECK.md` and `qa/DAY7_PRECHECK_QA.md`.

Pre-rename backup: `backups/day7-before-aegis-20260919T181620Z`.
Pre-final-deployment backup: `backups/day7-before-final-20260919T210842Z`.
The latter contains the PostgreSQL dump, 228 hashed retained artifacts and a
logical graph export. Restore database `day7_final_restore_20260919_210842`
retains the rehearsal. Migration 013 preserved all restored WorkItem and
intelligence-record rows byte-for-byte at their JSON serialization boundary.
Evidence: `logs/day7-restore-final.log` and the backup's `manifest.json`.

## Aegis lineage

Current package/configuration ownership and UI routes use `products/aegis`,
`config/aegis` and `/aegis`. `/p2p` remains a compatibility redirect. A fixed
canonical alias and migration 012 preserve historical P2P ownership, record IDs,
timestamps, content, hashes and lineage. Immutable source evidence is not renamed.
The promotion pause bypass found in the first extraction was corrected and
independently retested. Explicit upgrades are separate from ordinary startup so
Core diagnostics do not depend on successful product or database initialization.

Aegis remains human-directed, inactive and preserved. Exchange is CLOSED. No
strategies, product features or trading authority were added. Core imports neither
product; neither product imports the other. Triad consumes shared Core services.

## Resource policy and lifecycle time

Initial run allocations are 8,192 reasoning tokens, 24,000 input characters,
6,144 output tokens, 480 seconds and 60 tool calls. Migration 013 installs an
immutable versioned policy and preserves deliberately lower custom controls.
It changes neither cost policy nor execution authority.

The host records allocation, observed progress, extension request, decision and
run state. Reasoning, input, output, time and tool allocations support ALLOW,
DENY and REQUIRE_HUMAN_APPROVAL. Authorized native work can continue in place;
input can be extended before generation. An incomplete HTTP response retains
measured usage and blocks with resource evidence; it is not silently retried as
a new paid call. Unsupported or unknown usage stays unknown.

Fresh authorized file evidence can justify a bounded extension. Reusing the same
evidence, stale ownership/assignment, scope changes, killed runs and unapproved
paid expansion fail closed. One piece of progress cannot justify repeated grants
for the same resource, and automatic extensions have a finite count. File reads,
native metadata/directory calls and shared elapsed time participate in the same
run accounting. No request creates new allowed paths, tools or agent authority.
Tests and examples are in the B1/B2/B3 QA reports.

WorkItems carry created/updated/started/completed/closed timestamps. Handoff
lifecycle evidence records sent, received, acknowledged and completed events.
Builds, QA, agent requests, verification, extensions, merge/debt/cycle and
integration records carry appropriate aware UTC times. Historical missing times
remain unknown. UI records render local time with canonical UTC available in
details. Terminal cycle times include cancellation and rejection.

CLI subscription and local orchestration usage is tracked without a daily token
cap; API spending and fallback restrictions remain enforced. This is separate
from finite governed per-run allocations.

## Canonical Triad cycles

`CycleRecord` gathers mode, status, timestamps, parent WorkItem, control epoch,
agents and usage, candidates/proposals, builds/corrections/QA/reviews, changes,
tests/failures/lessons/debt, billing, merge and before/after evidence. GET routes
only read history; explicit capture/backfill appends canonical snapshots.

The historical REAL blocked cycle
`8a16bb3a-925e-4ff3-8131-94bad088fd1e` retains its provider-gate failures. Its
historical evidence anchor is created at the actual backfill time, not backdated.
Recovery points to the separately completed Day 6 mission
`day6-product-20260919`; it does not turn the blocked execution into a success.
Simulated failures remain labelled SIMULATED.

The genuine Day 6 build was Claude implementation
`93e23303-36df-4446-ae19-2a9f096f3b00`, independently reviewed by Codex QA
`b797f54a-dd17-4402-946e-9cbb97aa7cac`, with merge
`445f1666115209fcf2c4cd04270f38579729b261`. Earlier failed attempts remain visible.
`/triad/cycles` presents status, mode, agents, selected proposal, builder, QA,
merge, duration, billing, failures and debt with readable evidence details.

## External integrations and data

Core owns the registry, adapter contracts, sanitized shared metadata, connection
history, private integration candidates, capability matching and governed
adoption. Categories are BROKER, MARKET_DATA, HISTORICAL_DATA, FUNDAMENTALS, NEWS,
SENTIMENT, ECONOMIC_DATA, ALTERNATIVE_DATA, EXECUTION_VENUE and OTHER; new category
identifiers are extensible. Product-private candidates are not a shared catalog.

| Entry | State | Available behavior |
| --- | --- | --- |
| Charles Schwab | NOT_CONFIGURED; broker capabilities UNVERIFIED | Official interface references and capability inspection; shell only |
| Robinhood | NOT_CONFIGURED; supported domains/transports distinguished | Official Trading MCP and separate crypto REST references; no unofficial automation |
| Local Canonical Store | AVAILABLE; HISTORICAL_BARS IMPLEMENTED | Retained neutral datasets, mode/coverage/license/integrity matching |

No broker credentials or live account calls were required or performed. Order
placement, replacement and cancellation remain denied. Shell metadata does not
claim working account, quote, order or streaming access. Unsupported controls
are absent from the UI.

Agents can inspect capabilities, request use and propose integrations within
their active assignments. They cannot install an adapter, read credentials,
self-approve adoption or enable execution. An implemented external source needs
the exact approved candidate, Core build, definition fingerprint, capabilities,
commit, independent QA and canonical adoption decision. Every REAL fetch
revalidates that chain, current registry configuration and global controls.

Historical acquisition uses raw artifact → normalization → quality → canonical
one-minute Parquet → DatasetManifest. Records retain provider, request, time,
symbols, resolution, coverage, raw hashes, normalization and license/use evidence.
Raw bytes survive a later normalization failure. Matching checks nonempty expected
session coverage, retained raw/canonical integrity, consistent REAL/FIXTURE mode
and exact license allowlists. Conflicting datasets require an explicit choice.
No paid fallback is silent. The extension seam was exercised using local synthetic
adapters, including REAL-mode authority fixtures; this is not proof of real vendor
connectivity or real-market dataset coverage.

## UI, launcher and readiness debt

Core `/core/integrations` provides readable capabilities, source matching and
candidate review. Dynamic values render as text. Validation failures return
readable messages without raw submitted metadata or credentials. The page keeps
an entered operator key in memory only.

`/launch` separates Core from Triad Product, Development and Cycles, and the Aegis
shell. `/triad/product` is honestly labelled EARLY PRODUCT SHELL and contains no
Core administration controls. The existing desktop shortcut continues to target
the local launch HTML; deployment copies the reviewed launcher bytes there.

New `improvements/real-market-readiness-definitions-v2.md` defines zero unexplained
session/bar gaps, critical findings, nonempty expected coverage and completed
quality checks. Original Day 6 artifact SHA256 remains
`d5d1f6d00dc93a5e569b2e73bbed2ae1629c47ce372d403e15503aa7097e84f9`.
Debt `6402c739-cc23-4e07-9beb-2157e538ff4c` is resolved at the definitions level
through a new linked resolution record. Its original OPEN record remains immutable.
The readiness gate remains non-executable; no market-readiness claim is made.

## Independent QA by bounded build

Builder is `/root` throughout. Every required correction received fresh independent
QA; earlier failures, exact revision hashes and logs remain retained.

| Run | Reviewer | Corrections and final evidence |
| --- | --- | --- |
| A | `/root/day6_qa_a` | Ownership/pause and explicit deployment corrections; A1, A2 correction2 and PHASE1_FINAL_ACCEPTANCE PASS |
| B | `/root/day6_qa_a` and `/root/day6_qa_b` | Scoped resource authority, native accounting, invalid UTF-8 progress, HTTP usage and timestamps; B1/B2/B3 and timestamp correction/cleanup closure PASS |
| C | A | Proposal/link metadata, preserved prior facts and terminal times; C_FINAL_QA PASS, 11 tests |
| D/E | C | Exact Core adoption and metadata/legacy quarantine; DE_FINAL_QA PASS at 56e4f96, 21 tests |
| F | B | Registry revocation, raw integrity/provenance, strict licensing, cancellation, exact current adoption and latest QA; F_FINAL_QA PASS at 56e4f96, 14 tests |
| G/H/I | A | HTTP error reflection corrected; GHI_FINAL_QA PASS at 56e4f96, 5 tests plus installed package/14 asset checks |

Counts overlap broader regression; they must not be summed as unique tests.
Root's combined correction regression passed 32 tests in 65.18 seconds. Clean
installed-wheel smoke includes all new routes, HTML/JS/CSS, configuration and SQL
012/013 (`logs/day7-package-corrected.log`). Final complete regression, live browser,
deployment, provider/service and governance results are recorded at acceptance.

The first complete Day 7 run finished **524 passed, 5 failed in 1208.59s**. It is
retained in `logs/day7-full-regression.log`. One legacy reasoning-request helper
still rejected requests above 2,048 despite the new initial grant. Three fixtures
expected the former daily-cap/timeout behavior, and the API concurrency fixture
budget no longer admitted one larger reservation. Corrections preserve immutable
WorkItem limits and identity guards, structured zero-grant timeout denial, Qwen's
256-token compact schema and atomic paid reservation. Qwen's test double now
implements the actual context-capacity check. An intermediate correction still
failed that mock preflight and is retained. Fresh independent seven-case QA
passed at `eea65d393efc644f4b443914b26ce9023e4bec2e` in 34.83s; see
`qa/DAY7_REGRESSION_FINAL_QA.md`. The fresh final full-suite result follows below.

## Deployment and operating evidence

Explicit database upgrade 012/013, integration seeding, cycle backfill and debt
resolution completed. The corrected deployment helper binds the v2 document to
its exact reviewed Git blob before any mutation. Its initial missing-byte-binding
finding is preserved alongside the corrected four-test PASS. Windows line endings
were restored to the reviewed LF bytes; the guard was not relaxed.

Core 8000, Triad 8101 and Aegis 8102 run the reviewed release. PostgreSQL,
TimescaleDB 2.25.2, Neo4j, Ollama and Git are up. An initial Aegis 503 during worker
startup is retained; the settled root and independent 17-route reruns pass.
Final corrected-backend status: `logs/day7-release-services.log`, exit 0.

| Provider | Observed model | Billing | Readiness |
| --- | --- | --- | --- |
| Codex CLI | gpt-6-astra | SUBSCRIPTION | ONLINE |
| Claude Code CLI | claude-sonnet-5 | SUBSCRIPTION | ONLINE |
| Grok CLI | grok-4.6 | SUBSCRIPTION | ONLINE |
| Ollama/Qwen | qwen3:4b | LOCAL | ONLINE |

Provider gate PASS, zero active provider runs. Existing dated execution evidence and
automatic connection monitoring are current; this status check does not claim a
new provider generation or expanded native capability. Grok's historical native
write limitation is not erased. API fallback remains NEVER and live trading stays
disabled. Kill and authority denial paths are exercised in disposable tests;
production controls were not toggled just for demonstration.

Historical engine-output comparison and reversible baseline migration check
passed again: `logs/day7-final-data-regression.log`, exit 0. The 228 retained artifacts,
101 original WorkItems, 168 original intelligence rows and 91 artifact-owner rows were
independently checked unchanged. Neo4j logical backup integrity was checked;
this final pass does not claim another Neo4j restore rehearsal.

Actual browser navigation, loading, filtering, readable details, keyboard dialog
dismissal, product separation and online provider cards are recorded in
`qa/DAY7_LIVE_BROWSER.md`. The launchpad also fits the browser's actual 304px panel
without horizontal overflow; no viewport override was needed. Adversarial input
and authorization checks use independent HTTP fixtures/source review. No claim of
exhaustive mobile, forced-outage or browser-injection testing is made.

The actual desktop shortcut target was independently resolved through Windows COM
and matches the reviewed launcher hash. It is under the Codex packaged-app
LocalCache directory, not merely the nominal AppData path. The old HTML is backed
up. `qa/DAY7_LIVE_ACCEPTANCE_QA.md` records independent live acceptance; the final
legacy helper correction is covered by its later exact-source QA and restart.

Canonical evidence now includes 32 actual build/QA pairs, retaining negative
revisions and corrections. The first 30 were ingested from a reviewed, pinned,
hash-verified plan with scoped file lists and safe partial-failure retry behavior;
the two final regression correction pairs retain their own manifests. Actual
historical execution evidence stays in reports; ingestion times are not invented
execution times. See `qa/DAY7_CANONICAL_INGESTION_REVIEW.md` and the two canonical
QA indexes under logs.

The pre-release independent audit additionally verified all 32 canonical pairs,
245 unique pinned source blobs and 123 installed-file byte matches. Its temporary
audit assertion that every historical segment had Core ownership was corrected
to respect the reviewed Triad-owned segments; that audit failure is retained and
did not require an application change. See `qa/DAY7_RELEASE_PRECHECK_QA.md`.

## Git and next recommendation

Final full regression: **535 passed, 5 warnings in 1145.97 seconds**, exit 0,
`logs/day7-final-full-regression.log`. Every previous failure passed. The warnings
are two dependency deprecations and three duplicate proxy OpenAPI operation-ID
warnings; no warning was suppressed. The final 290-file source snapshot is
unchanged, including application code, configuration, SQL, tools and tests.
`qa/DAY7_ACCEPTANCE_MANIFEST.json` binds those bytes and the retained test,
package, service, historical-data, desktop and canonical QA evidence.

Build branch: `codex/day7-hardening`. Final independent acceptance and canonical
Core QA ingestion are required before merging/tagging `base/day7-complete`.
No remote push is part of this task.

Next recommended Triad-owned improvement: a read-only research readiness view
that consumes Core's source matcher, selects an explicitly approved historical
dataset and explains unmet coverage/quality criteria. Keep the first scope to
evidence and backtesting; live execution and broker integration need their own
reviewed work. Do not begin this recommendation automatically.
