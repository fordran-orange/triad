# Triad capability inventory

Mission `day6-product-20260919`. Snapshot after the first governed merge. Assessments below are the independent inspectors' bounded source-based findings, not exhaustive feature certification. They received the same three neutral source files without each other's findings. Core administration is shared infrastructure, not a Triad product feature.


## Governed product improvement — CODEX

State: **EXISTS**. Traceable inspections, candidate decisions, builds and separate QA before merge.

- **Dependencies:** Core execution and review infrastructure
- **Limitations:** Current autonomous changes are limited to bounded non-executable documents.; Lifecycle enforcement was described by the baseline; its implementation was outside supplied sources.
- **Technical debt:** None recorded
- **Evidence:** INSPECTION_BASELINE.md: development lifecycle and exact-source QA requirements.; development_contracts.py: ProductInspection, ProductCandidate and ProductProposal model evidence, permissions, QA and rollback plans.
- **Candidate improvements:** None recorded

Provenance: inspection `8b07e502-d9fd-4adb-85b0-72e3d6f247a3`, WorkItem `951cf0dc-bf6e-44a8-a75b-5d1bb3cd41d3`, actual model `gpt-6-astra`.

## Reproducible research laboratory — CODEX

State: **PARTIAL**. Retained artifacts and immutable fingerprints support repeatable experiments and review.

- **Dependencies:** Core data/backtest infrastructure; PostgreSQL/TimescaleDB; Operator authorization for laboratory mutations
- **Limitations:** Baseline reports FIXTURE data and real_market_provider UNAVAILABLE.; Built-in strategy and planning helpers do not establish investment merit.; Live trading and brokerage execution are disabled.
- **Technical debt:** Real-market provider integration remains unavailable.
- **Evidence:** INSPECTION_BASELINE.md: provider-neutral ingestion, quality checks, bounded backtests and checksum-verified artifacts.
- **Candidate improvements:** Document acceptance criteria for real-market research readiness.

Provenance: inspection `8b07e502-d9fd-4adb-85b0-72e3d6f247a3`, WorkItem `951cf0dc-bf6e-44a8-a75b-5d1bb3cd41d3`, actual model `gpt-6-astra`.

## Worker operation and health visibility — CODEX

State: **PARTIAL**. Background processing retries failures while the application exposes a liveness endpoint.

- **Dependencies:** Jobs; scheduler.tick; ManagedProcess
- **Limitations:** The supplied liveness endpoint returns a constant success response without checking worker progress.; Worker exceptions emit a generic warning without exception details.
- **Technical debt:** No worker success timestamp or failure state is exposed in server.py.
- **Evidence:** server.py: lifespan loop catches Exception, logs a generic warning and waits ten seconds.; server.py: /health/live returns status ok unconditionally.
- **Candidate improvements:** Expose worker readiness and diagnostic state.

Provenance: inspection `8b07e502-d9fd-4adb-85b0-72e3d6f247a3`, WorkItem `951cf0dc-bf6e-44a8-a75b-5d1bb3cd41d3`, actual model `gpt-6-astra`.

## Research lab data and backtesting — CLAUDE

State: **PARTIAL**. Reproducible, checksummed experiments

- **Dependencies:** trading_core research
- **Limitations:** Fixture data only; real provider UNAVAILABLE
- **Technical debt:** Built-in strategy is only an engine fixture
- **Evidence:** INSPECTION_BASELINE.md: real market provider unavailable
- **Candidate improvements:** Show evidence-gap status

Provenance: inspection `da5d9b11-6410-4f3d-b2fc-6f7de6eab349`, WorkItem `b1553932-24fb-4080-8df9-ee1cf8869509`, actual model `claude-sonnet-5`.

## Operator workflow UI — CLAUDE

State: **PARTIAL**. Visibility into cycles, reviews, lineage

- **Dependencies:** FastAPI product server
- **Limitations:** Split across /triad, /triad/development, /research
- **Technical debt:** Worker swallows errors; only a generic warning is logged
- **Evidence:** server.py: broad except logs a generic retry warning
- **Candidate improvements:** Unified status summary

Provenance: inspection `da5d9b11-6410-4f3d-b2fc-6f7de6eab349`, WorkItem `b1553932-24fb-4080-8df9-ee1cf8869509`, actual model `claude-sonnet-5`.

## Operator product shell and cycle worker — GROK

State: **EXISTS**. Operators can open /triad and a local worker ticks cycles.

- **Dependencies:** products.triad.jobs, scheduler, cycles
- **Limitations:** Worker exceptions only log and retry every 10s
- **Technical debt:** Failure is not returned on /health/live
- **Evidence:** app/products/triad/server.py lifespan loop, /triad, /health/live, /triad/api/work
- **Candidate improvements:** Expose worker retry state on the product shell

Provenance: inspection `7d3d37a1-c439-4340-aba7-9b8d0abb0aa0`, WorkItem `11b96d0f-96cb-4a1d-a908-63f7b83f23ad`, actual model `grok-4.6`.

## Governed development inspection records — GROK

State: **PARTIAL**. Structured areas/candidates/proposals for product decisions Triad owns.

- **Dependencies:** trading_core.work.Record
- **Limitations:** Day 6 lifecycle is not autonomous product improvement
- **Technical debt:** Inspection UI/API not in these three files
- **Evidence:** development_contracts.py ProductInspection; INSPECTION_BASELINE.md /triad/development
- **Candidate improvements:** Keep backlog items that need live market or shell grants deferred

Provenance: inspection `7d3d37a1-c439-4340-aba7-9b8d0abb0aa0`, WorkItem `11b96d0f-96cb-4a1d-a908-63f7b83f23ad`, actual model `grok-4.6`.
