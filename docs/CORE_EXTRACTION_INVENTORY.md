# Core extraction inventory

Inspected Python imports and primary service implementations before movement. Mixed components must be split at the listed seams, not merely renamed.

| Current path | Purpose / dependencies | Product assumptions | Classification | Target | Risk |
|---|---|---|---|---|---|
| `app/triad/__init__.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/__init__.py` | Medium |
| `app/triad/api.py` | triad.brain, triad.day3.adapters, triad.day3.api, triad.day3.scheduler, triad.day5a.api, triad.day5a.control, triad.day5a.process, triad.jobs, triad.lab.api, triad.lab.service, triad.orchestrator, triad.research_review, triad.status, triad.work | Monolithic composition: independent Core app and product process; legacy gateway | CORE | `app/platform_host/api.py` | High |
| `app/triad/brain.py` | triad.settings, triad.store | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/brain.py` | High |
| `app/triad/context.py` | triad.work | Hard-coded charter and source paths: explicit product policy/context | CORE | `app/trading_core/context.py` | Medium |
| `app/triad/control.py` | triad.settings, triad.work | Registry embeds rotation: separate neutral review selection from product rotation | CORE | `app/trading_core/control.py` | High |
| `app/triad/day3/__init__.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/day3/__init__.py` | Medium |
| `app/triad/day3/adapters.py` | triad.day3.contracts, triad.day3.security, triad.day5a.control, triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/runtime.py` | Medium |
| `app/triad/day3/api.py` | triad.api, triad.brain, triad.day3.contracts, triad.day3.cycles, triad.day3.support, triad.jobs, triad.readiness | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/api.py` | Medium |
| `app/triad/day3/changes.py` | triad.control, triad.day3.security, triad.settings | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/git_tools.py` | Medium |
| `app/triad/day3/contracts.py` | triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/day3/contracts.py` | Medium |
| `app/triad/day3/cycles.py` | triad.brain, triad.day3.adapters, triad.day3.changes, triad.day3.contracts, triad.day3.ledger, triad.day5a.control, triad.gateway, triad.orchestrator, triad.settings, triad.work | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/cycles.py` | Medium |
| `app/triad/day3/ledger.py` | triad.day3.contracts, triad.day3.security, triad.settings, triad.store, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/ledger.py` | High |
| `app/triad/day3/scheduler.py` | triad.day3.cycles, triad.settings | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/scheduler.py` | Medium |
| `app/triad/day3/security.py` | triad.day5a.secrets, triad.settings | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/security.py` | Medium |
| `app/triad/day3/support.py` | triad.brain, triad.day3.contracts, triad.day3.security, triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/support.py` | Medium |
| `app/triad/day5a/__init__.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/day5a/__init__.py` | Medium |
| `app/triad/day5a/api.py` | triad.api, triad.day5a.contracts, triad.day5a.control, triad.day5a.verification | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/api.py` | Medium |
| `app/triad/day5a/bounded_tools.py` | triad.day3.contracts, triad.day3.security, triad.day5a.isolation | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/bounded_tools.py` | Medium |
| `app/triad/day5a/codex_executor.py` | triad.day3.adapters, triad.day3.contracts, triad.day3.security, triad.day5a.isolation, triad.day5a.process, triad.settings | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/codex_executor.py` | Medium |
| `app/triad/day5a/contracts.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/contracts.py` | Medium |
| `app/triad/day5a/control.py` | triad.day3.adapters, triad.day3.ledger, triad.day5a.contracts, triad.day5a.secrets, triad.day5a.transports, triad.store, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/control.py` | Medium |
| `app/triad/day5a/isolation.py` | triad.day3.security, triad.day5a.process, triad.settings | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/isolation.py` | Medium |
| `app/triad/day5a/native_agents.py` | triad.day3.adapters, triad.day3.contracts, triad.day5a.bounded_tools, triad.day5a.codex_executor, triad.day5a.isolation, triad.day5a.process | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/native_agents.py` | Medium |
| `app/triad/day5a/process.py` | triad.day3.security | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/process.py` | Medium |
| `app/triad/day5a/relay.py` | triad.brain, triad.day3.adapters, triad.day3.contracts, triad.day3.cycles, triad.day3.support, triad.day5a.contracts, triad.gateway, triad.work | Cycles dependency: replace with generic ExecutionServices | TRIAD | `app/products/triad/acceptance.py` | High |
| `app/triad/day5a/secrets.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/secrets.py` | Medium |
| `app/triad/day5a/transports.py` | triad.day3.adapters, triad.day3.contracts, triad.day5a.codex_executor, triad.day5a.contracts, triad.day5a.isolation, triad.day5a.native_agents, triad.day5a.process, triad.gateway, triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/providers/transports.py` | Medium |
| `app/triad/day5a/verification.py` | triad.brain, triad.day3.adapters, triad.day3.contracts, triad.day3.cycles, triad.day3.support, triad.day5a.contracts, triad.work | Cycles dependency: replace with generic ExecutionServices | CORE | `app/trading_core/providers/verification.py` | High |
| `app/triad/gateway.py` | triad.control, triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/gateway.py` | Medium |
| `app/triad/jobs.py` | triad.brain, triad.day3.cycles, triad.day3.ledger, triad.day3.security, triad.day5a.control, triad.settings, triad.store, triad.work | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/jobs.py` | Medium |
| `app/triad/lab/__init__.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/lab/__init__.py` | Medium |
| `app/triad/lab/api.py` | triad.api, triad.day3.support, triad.lab.contracts, triad.lab.data, triad.lab.service | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/api.py` | Medium |
| `app/triad/lab/calendar.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/calendar.py` | Medium |
| `app/triad/lab/contracts.py` | triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/contracts.py` | Medium |
| `app/triad/lab/data.py` | triad.lab.calendar, triad.lab.contracts, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/data.py` | Medium |
| `app/triad/lab/engine.py` | triad.lab.contracts, triad.lab.data | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/engine.py` | Medium |
| `app/triad/lab/planning.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research/planning.py` | Medium |
| `app/triad/lab/service.py` | triad.brain, triad.day3.cycles, triad.lab.contracts, triad.lab.data, triad.lab.engine, triad.settings, triad.work | Cycles dependency: replace with generic ExecutionServices | CORE | `app/trading_core/research/service.py` | High |
| `app/triad/market.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/market.py` | Medium |
| `app/triad/orchestrator.py` | triad.brain, triad.context, triad.control, triad.day3.ledger, triad.gateway, triad.providers, triad.settings, triad.store, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/orchestrator.py` | Medium |
| `app/triad/policy.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/policy.py` | Medium |
| `app/triad/providers.py` | triad.gateway, triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/legacy_providers.py` | Medium |
| `app/triad/readiness.py` | triad.day3.adapters, triad.day3.cycles | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/readiness.py` | Medium |
| `app/triad/research_review.py` | triad.brain, triad.lab.contracts, triad.lab.service, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/research_review.py` | Medium |
| `app/triad/settings.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/settings.py` | Medium |
| `app/triad/static/day3.html` | Presentation and HTTP routes | Autonomous evolution/rotation policy retained only in Triad | TRIAD | `app/products/triad/static/day3.html` | Medium |
| `app/triad/static/index.html` | Presentation and HTTP routes | Legacy namespace; preserve storage IDs and evidence | CORE_UI | `app/trading_core/static/index.html` | Medium |
| `app/triad/static/providers.html` | Presentation and HTTP routes | Legacy namespace; preserve storage IDs and evidence | CORE_UI | `app/trading_core/static/providers.html` | Medium |
| `app/triad/static/record-view.css` | Presentation and HTTP routes | Legacy namespace; preserve storage IDs and evidence | SHARED_UTILITY | `app/trading_core/static/record-view.css` | Medium |
| `app/triad/static/record-view.js` | Presentation and HTTP routes | Legacy namespace; preserve storage IDs and evidence | SHARED_UTILITY | `app/trading_core/static/record-view.js` | Medium |
| `app/triad/static/research.html` | Presentation and HTTP routes | Generic engine inspector remains Core; future product research UX independently owned | CORE_UI | `app/trading_core/static/research.html` | Medium |
| `app/triad/status.py` | triad.brain, triad.settings, triad.store | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/status.py` | Medium |
| `app/triad/store.py` | triad.settings, triad.work | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/store.py` | High |
| `app/triad/work.py` | Python / third-party libraries | Legacy namespace; preserve storage IDs and evidence | CORE | `app/trading_core/work.py` | Medium |

## Non-code ownership

- PostgreSQL: candles/manifests/work/evidence/provider controls are Core services. Existing cycle slots, improvement slots and cycle jobs are Triad policy state. Mixed JSON record storage requires an ownership catalog and scoped access before product access is enabled.
- Neo4j: retained stable IDs; explicit owner on product entities and scope-aware traversal.
- Parquet and raw datasets: retain paths/checksums; dataset access is explicitly shared only by host policy.
- Secrets: preserve existing Windows Credential Manager targets. Untrusted model tools never receive host secrets; trusted product processes call Core runtime code under the local account, as documented in the operations trust boundary.
- agents/day3.json: split provider/runtime capabilities from scheduler/rotation/product mission. agents/registry.json: retain capability ceilings in Core; rotation belongs to Triad.
- Core UI: provider controls, work/evidence, diagnostics, data-engine inspection. Triad UI: cycles, backlog, proposals, evolution. P2P: new empty human-directed shell.
- Shared UI: renderer and presentation primitives only; no merged product navigation.

Counts (existing source/static components, final classification): {'CORE': 42, 'TRIAD': 7, 'CORE_UI': 3, 'SHARED_UTILITY': 2}. UNCLEAR: 0; P2P existing: 0.
P2P existing components: 0. New P2P shell is deliberately sparse. No unresolved ownership is silently treated as shared.

Migration order: baseline -> generic execution -> ownership contracts -> modules and compatibility aliases -> independently bootable surfaces -> migrations and regression.

## Final extraction decisions

- Generic execution was extracted before dependent services. Provider verification and laboratory code use `ExecutionServices`, never product cycles.
- Runtime, ledger, contracts, security, support and Git tools now live directly under `app/trading_core`. Provider adapters are under `providers/`; the research engine is under `research/`. The table's proposed `trading_core/day3` and `trading_core/day5a` targets were flattened: initializer files are compatibility-only, generic contracts are `trading_core/contracts.py`, and the provider package is `trading_core/providers`.
- Triad owns Candidate and CycleSummary contracts, relay acceptance policy, scheduler, jobs, rotation and daily improvement slots.
- Neutral `platform_host/api.py` uses HTTP proxies to independent product processes. `platform_host/legacy.py` is retained for in-process compatibility tests only.
- Legacy Python modules forward imports. Environment names, credential targets, container labels, persisted schema strings, the old JavaScript renderer global and historical branch prefixes are compatibility identifiers.
- Fixture strategies remain generic engine tests; no curated strategy library was imported.

## Persisted record classification

| Storage | Ownership rule |
|---|---|
| `core.work_items` | Historical items Triad; every new item has a host-selected Core/Triad/P2P owner. Parent ownership must match. |
| `core.orchestration_records` | Agent is shared Core infrastructure. ContextPacket, JournalEntry, Handoff, Review, PolicyDecision, Provenance and ElevationRequest inherit the associated WorkItem. |
| `core.day3_records`: transport/governance | Historical TransportStatus, ProviderPolicy, TransportVerification, TransportRun, Usage, ProviderHealth, ControlAction and FallbackGrant classified Core. New work-related usage/results inherit work ownership. Global status/policy records stay Core. |
| `core.day3_records`: research | Existing RawDataset, DatasetManifest and QualityReport are explicitly shared market/fixture data. Experiment, Hypothesis, BacktestRun, ResearchReview, ResearchFinding and EvidenceCorrection remain private to their product. |
| `core.day3_records`: product workflow | Candidate, Proposal, Change, Cycle, CycleSummary, AutonomousReview, JobEvent, ReadinessReport, ProviderRelay and RelayGitEvidence are Triad policy/history. |
| `core.day3_records`: execution/audit | AgentRunRequest, AgentRunResult, BudgetReservation, RunAuthority, SupportRequest, SupportResult and TransportDecision inherit work ownership. Historical Event and IngestionJob records remain Triad; new standalone Core operator events belong to Core. |
| `core.work_events`, `core.projection_outbox` | Internal canonical-work audit and projection queues; source records determine scope. They are not agent query endpoints. |
| `core.autonomy_control`, `core.autonomy_daily`, `core.product_controls`, `core.product_stops` | Global enforcement and accounting, plus product-local restrictions that cannot relax global authority. |
| `core.artifact_owners` | Exact artifact path, owner and canonical source record. Historical file bytes and paths remain unchanged. |
| `core.exchange_candidates` | Closed extension point; no transfer/import endpoint. |
| `triad.improvement_slots`, `triad.cycle_slots`, `triad.cycle_jobs` | Triad-only scheduling and improvement policy. |
| `core.candles_1m`, `core.datasets`, `core.experiments`, `core.events`, `core.metrics`, `core.operational_state`, `core.orders`, `core.positions` | Retained Day-1 foundation tables, empty at baseline. They are not newly exposed product-knowledge APIs. Live execution remains disabled. |
| `p2p` schema | Reserved, with no imported product knowledge. Shared generic records use explicit P2P ownership when created. |
| Neo4j | Owners follow canonical records; generic agents are Core. New mission/file/evidence identities are qualified by owner. Historical IDs and relationships remain retained. |

Historical fingerprints are evidence, not rewritten to reflect the new module paths.
