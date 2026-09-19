# Core extraction verification

Verified on 19 September 2026 on the local Windows host. This report accompanies
the `base/trading-core-v1` release on `codex/core-extraction`.

## Preserved baseline

- Implementation: `4e643611aa5d1d2552118d9b4a1a0b8b4f774fca`.
- Annotated `base/day5a-complete`: `9ba223e`, adding exact baseline evidence.
- Baseline tests: 239 unit/default and 69 explicit integration tests passed.
- Python 3.12.10; PostgreSQL 17 / TimescaleDB 2.25.2; Neo4j 5.26 Community;
  Ollama qwen3:4b; subscription Codex, Claude and Grok CLIs.
- Private recovery bundle: `backups/day5a-20260919`. PostgreSQL restored into
  isolated `core_baseline_restore`, recovering all 19 application tables. Neo4j
  restored into a separate volume: 2468 nodes and 1416 relationships matched.
  All 151 artifact files extracted separately and hash-checked.
- Credentials and recovery files are excluded from Git.

See [baseline evidence](PRE_SPLIT_BASELINE.md).

## Inventory and extraction

The source/static inventory contains 54 entries: CORE 42, TRIAD 7, CORE_UI 3,
SHARED_UTILITY 2, existing P2P 0, UNCLEAR 0. Persisted record kinds are separately
classified in [the inventory](CORE_EXTRACTION_INVENTORY.md).

Core owns generic execution, work/review contracts, authority enforcement,
provider transports/authentication, monitoring, usage, isolated tools, storage,
scoped context, provenance/graph projection, generic Git mechanics, data ingestion
and the existing deterministic research engine.

`ExecutionServices` was extracted before moving verification and research; these
services no longer import or instantiate Triad cycles. Generic review eligibility
is separate from Triad's rotation. Candidate selection, improvement slots, cycle
summaries, scheduler, jobs, relay acceptance and product readiness belong to
`products.triad`. Core does not choose a product mission or schedule development.
P2P is a sparse independently startable human-directed shell. No strategy library
was copied into Core or P2P.

## Services and UI ownership

| Route | Owner |
|---|---|
| `/`, `/core` | Core WorkItems, journals, handoffs, reviews, approvals, diagnostics and global controls |
| `/settings/ai-providers` | Core login, models, verification, usage and provider policies |
| `/research` | Core generic data/research engine inspector |
| `/day2` | Retained Core work explorer |
| `/triad` | Triad rotation, backlog, proposals, product reviews, journal, change lineage and jobs |
| `/p2p` | Independent empty human-directed product shell; exchange closed |

The launcher runs Core/gateway on loopback 8000, Triad on 8101 and P2P on 8102.
Core also starts directly as `trading_core.api:app`. The neutral gateway imports
neither product. Product failure yields a bounded 503 response on its route.

Browser QA covered Core's seven views, provider permissions/usage/diagnostics,
Triad's eight views, all six research views, P2P, the retained explorer and
`/core?work=<id>` canonical links. Record dialogs render readable fields. No
JavaScript console errors were observed. Core's narrow responsive layout was
visually inspected. Final service-state evidence appears below.

## Dependency, ownership and governance verification

- AST checks enforce dependency direction for normal and literal dynamic imports.
  A subprocess imports every Core module with `products`, `triad` and
  `platform_host` imports blocked; Core UI and protected controls still load.
- WorkItem ownership is immutable and host-selected. Foreign parents, record IDs,
  updates, events and private research reads are rejected. Queries scope before
  limiting results. Shared data is readable but not product-writable.
- Context uses the actual WorkItem owner. Exact artifact ownership and path grants
  protect private outputs. Exchange has a CLOSED typed contract and rejects imports.
- New graph mission/file/evidence identities are product-qualified. Lineage checks
  the source and filters neighbors. Projection gets ownership from canonical SQL,
  ignoring forged payload ownership. Tests cover both a forged payload and an
  intentionally bad cross-product graph edge.
- Products may restrict their own work but cannot relax global policy or a kill
  switch. Relocated Core/config, credentials, cross-product files and human notes
  remain protected. No autonomous code, shell, credential, broker or live-capital
  authority was added.
- A real three-process test terminates each product in turn. Core UI/diagnostics
  remain available. Authenticated global kill blocks isolated test execution;
  resume restores only existing policy. Disposable data was used for this test.
- Subscription/local daily caps remain off with usage and local warnings retained.
  API budget remains zero, fallback NEVER. Automatic monitoring runs every five
  minutes without inference; successful verification does not expire just with time.

## Database, graph and reproducibility

005 moves 16 generic tables into `core` with compatibility views; 006 introduces
ownership and product controls; 007 initializes Triad-owned tables; 008 registers
artifact ownership; 009 corrects relay-envelope ownership metadata. Historical
IDs, evidence links, graph edges and artifact references remain intact.

`tools/check_extraction_data.py` verified 59 baseline WorkItem IDs, all 151
unchanged artifact SHA-256 hashes, and SQL up/down/up on the isolated restored
database. Rollback refuses to discard P2P records and retains additive ownership
columns to preserve evidence.

Both existing experiments produce identical complete deterministic outputs under
the original tagged and extracted engines. Their output digest is
`92fa86ba7608ba1cee91cca0dfb7e4b9c1df0a5355b525b6d3b51e761921b8e8`.
Historical fingerprints remain unchanged; the new research source fingerprint is
`f3c0d1f08aa0664cb6dafe4620337f460c7db5fde5a4f286b7ceab1b4b23a293`.
Evidence: `logs/extraction-data.json`.

Generated Markdown retains historical paths. New notes contain record ID, owner,
canonical source link and generation time. Annotations live separately under
`docs/vault/operator`. Editing notes cannot approve work or alter canonical
history; combined human notes never become agent context automatically. Obsidian
remains optional. [Operations and recovery](CORE_EXTRACTION_OPERATIONS.md) describes
launching, compatibility and rollback.

## Tests and packaging

318 tests collected: 244 unit/default and 74 integration. All passed across the
default suite, integration partitions and focused reruns after fixes. This is not
a claim that one command ran all 318 together.

| Evidence | Result |
|---|---|
| `logs/refactor-unit-final.log` | 244 passed; 74 integrations skipped |
| `logs/refactor-integration-final.log` | 57 non-Day2 integrations passed at that collection |
| `logs/refactor-day2-final.log` | 15 Day2 integrations and one job regression passed |
| `logs/refactor-final-governance.log` | 32 ownership, Day3 and job tests passed, including later additions |
| `logs/refactor-ownership-release.log` | All 4 ownership integrations passed after the graph-owner fix |
| `logs/refactor-stream-governance.log` | 21 ownership, Day3 and actual product-crash/kill-switch integrations passed after guard optimization |
| `logs/refactor-package-final.log` | Clean installed 0.2.0 wheel outside checkout passed |

The package ships Core/product HTML, JS/CSS, configuration and SQL. Installed
smoke checks run isolated Python outside the checkout. Ruff passes application,
test and tool code. Two test-client dependency deprecation warnings remain.

Initial failures were corrected: synthetic audit references, concurrent-update
synchronization, support-child ownership, scoped graph identities and generic
provider-gate expectations. Failed runs remain in logs; assertions were not
weakened to hide failures.

## Real provider acceptance

Fresh real connection and WorkItem proofs passed for all four providers (eight
successful proofs):

| Provider | Actual model | Billing |
|---|---|---|
| Codex | gpt-6-astra | Subscription CLI |
| Claude | claude-sonnet-5 | Subscription CLI |
| Grok | grok-4.6 | Subscription CLI |
| Qwen / Ollama | qwen3:4b | Local |

Evidence: `logs/refactor-provider-acceptance.log`. Relay
`83c4a348-74d9-49f0-9051-f423fde11b3c` passed with Codex proposal, independent
Claude/Grok approvals, local Qwen summary and graph evidence. After relay ownership
was tightened, three reruns timed out awaiting Grok's verdict after genuine isolated
file reads with no tool denials. A separate real Grok WorkItem passed in 40 seconds.
Investigation found the scoped guard opening three SQL connections per streamed
check; the guard now reads ownership, product restrictions and global authority
in one fresh query. No caching, skipped checks, timeout increases or expanded
permissions were introduced. Failed attempts remain in the audit history.

Final relay `02fd5b7a-e592-4ce9-b968-49d4581f0ca7` passed on `6f45568` at
06:28:36 UTC. All four real steps completed, Claude and Grok independently
APPROVED, Qwen produced the local summary, disagreement check was NONE, and all
eight required audit/usage/review graph records were verified. Evidence:
`logs/refactor-relay-final-pass.log`. This proves execution and evidence flow,
not that model prose is automatically correct; the Qwen summary remains an
operator-reviewable derivative, not an instruction to change code or documentation.

After restarting all three services, `tools/check_extraction_services.py` passed:
nine page/asset routes returned 200; PostgreSQL, TimescaleDB, Neo4j, Ollama, Git
and backend reported UP; both product workers were healthy; all four providers
were ONLINE; provider gate and Triad relay gate passed; zero provider runs remained
active. P2P contained zero assignments and exchange remained CLOSED. Browser
confirmation showed `Providers PASS · Relay PASS` with no console errors.
Evidence: `logs/extraction-services.json` and `logs/refactor-services-final.log`.

## Git and explicit remaining coupling

One maintained integration branch: `codex/core-extraction`. Significant commits:

```text
app/trading_core/       generic services, providers, research, operator UI
app/products/triad/     autonomous product policy, jobs, UI
app/products/p2p/       human-directed product shell
app/platform_host/     neutral local gateway; test-only legacy assembly
app/triad/             compatibility forwarding modules
config/{core,triad,p2p}/
infrastructure/postgres/  versioned migrations
docs/                  contracts, inventory, operations and evidence
```

- `8f77483`: generic execution extraction.
- `5847139`: independent services, scoped records and operator controls.
- `a8e8b1f`: migration compatibility and architecture documentation.
- `aa19397`: immutable ownership and product audit classification.
- `4fe5ccf`: independent Triad sequence and packaged resources.
- `cccdbf8`: canonical graph ownership and forged-payload regression.
- `6f45568`: one-query current authority checks, preserving scoped enforcement.

The final documentation commit follows these implementation commits; annotated
`base/trading-core-v1` identifies the release snapshot. Final working tree is clean.
No remote push is included. Existing `main`, `codex/day5a-provider-control` and
three prior `codex/triad/{codex,claude,grok}/<work-id>` branches/worktrees are
preserved. They are historical development work, not independent product forks.

Remaining compatibility and limitations:

1. Products are trusted local services using the same OS/database account. Scoped
   APIs protect data/model context; this is not OS isolation against hostile
   installed Python code. Multi-user identities and authenticated internal RPC
   are future work.
2. Legacy `triad.*` shims, routes, environment/credential names, container names,
   schema views, historical branches and Markdown paths remain. The in-process
   `platform_host.legacy` composition is only for compatibility tests.
3. Product pages use Core renderer assets through the gateway. Shared presentation
   primitives contain no product decisions.
4. Research remains the existing fixture-oriented engine. Broker, portfolio,
   advanced research and strategy-library capabilities are extension points.
   P2P stays sparse; exchange stays disabled.
5. Triad scheduling remains disabled. Autonomous Git modifications still require
   the existing clean protected `main` checkout. This integration branch does not
   bypass that guard. Integrating into `main` and enabling later autonomy remain
   separate operator decisions.

No unresolved import-direction, private-data, restoration, packaging or process
failure-isolation gate is deferred to Day 5B.
