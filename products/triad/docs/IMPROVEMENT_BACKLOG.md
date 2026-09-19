# Triad improvement backlog

Mission `day6-product-20260919`. Snapshot after the first governed merge. Assessments below are the independent inspectors' bounded source-based findings, not exhaustive feature certification. They received the same three neutral source files without each other's findings. Core administration is shared infrastructure, not a Triad product feature.


The selected candidate is retained as an immutable original record; selection/completion below is derived from the proposal and governed merge. Other candidates retain their original status.

## Define real-market research readiness criteria

Candidate `6f35d9c3-cf35-4b61-936f-fdbefc6f2521` · **SELECTED / MERGED** · Inspector CODEX

- **Problem:** Fixture-backed research cannot establish readiness for experiments on real market data.
- **Product area:** Reproducible research laboratory
- **Evidence:** INSPECTION_BASELINE.md explicitly reports the market provider unavailable while describing existing ingestion, quality and provenance infrastructure.
- **Expected user value:** Clarifies which evidence is needed before interpreting real-data experiments.
- **Technical value:** Creates reviewable provider acceptance criteria for provenance, session coverage, quality and reproducibility.
- **Risk:** Low; documentation must not imply provider access or validated performance.
- **Effort:** Small; one bounded document under docs/improvements.
- **Dependencies:** Separate QA of exact staged content before any merge
- **Reversibility:** Remove or revise the document.
- **Origin:** Independent review of supplied baseline

## Expose worker readiness and diagnostic state

Candidate `a4ed8051-552a-4939-901e-35364972dfc6` · **DEFERRED** · Inspector CODEX

- **Problem:** Operators cannot distinguish responsive HTTP service from failed background processing using the supplied liveness response.
- **Product area:** Worker operation and health visibility
- **Evidence:** server.py: constant /health/live response and generic exception warning in lifespan worker.
- **Expected user value:** Makes stalled or failing background work easier to detect and diagnose.
- **Technical value:** Add separate readiness reporting with last successful iteration and sanitized failure diagnostics; preserve liveness semantics.
- **Risk:** Medium; readiness semantics and diagnostic disclosure need review.
- **Effort:** Small to medium implementation; exceeds current document-only grants.
- **Dependencies:** Executable-change authorization; Definition of worker readiness; Independent QA before merge
- **Reversibility:** Revert readiness and diagnostic additions.
- **Origin:** Independent inspection of server.py

## Evidence-gap status document

Candidate `66bb016f-2f2b-4c0e-b55e-cf9e93bd1000` · **PROPOSED** · Inspector CLAUDE

- **Problem:** Operators cannot easily see which results are fixture-only or unvalidated
- **Product area:** Research lab data and backtesting
- **Evidence:** Baseline: fixture strategy, no validated out-of-sample performance
- **Expected user value:** Avoids mistaking engine checks for merit
- **Technical value:** Explicit evidence-maturity labels
- **Risk:** Low; documentation only
- **Effort:** Small
- **Dependencies:** docs/improvements grant
- **Reversibility:** Fully reversible
- **Origin:** CLAUDE inspection

## Show worker unavailable on /triad

Candidate `758548be-aea8-4ae7-b79d-4ad7412fc517` · **PROPOSED** · Inspector GROK

- **Problem:** Cycle worker failures are swallowed; /health/live still reports ok.
- **Product area:** Operator product shell and cycle worker
- **Evidence:** server.py except logs warning; live() always status ok
- **Expected user value:** Operators see whether the product cycle is actually running.
- **Technical value:** Separates liveness from cycle-loop health without new authority.
- **Risk:** LOW
- **Effort:** small text/docs or later UI
- **Dependencies:** existing Jobs tick loop
- **Reversibility:** revert status field
- **Origin:** server.py worker boundary
