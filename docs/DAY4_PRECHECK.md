# Day 4 research-laboratory precheck

The authoritative Day 4 brief specifies market data, experiments and backtesting. Earlier queue/recovery work was based on a recommendation before this brief arrived; its reports are preserved as DAY4_DURABILITY_*.md. It is supporting infrastructure, not the research acceptance result.

Baseline: clean main 4d3f2aaf35ae9b152f31ccddd1a1bcbc42dd71ca, 2026-09-17.

| Component | Check | Expected | Actual | Result | Evidence |
|---|---|---|---|---|---|
| Repository | status, HEAD | clean existing delivery | clean main 4d3f2aa | PASS | Git precheck |
| Python/tests | complete live suite | no regressions | 144 passed, zero failed/skipped, 185.75 sec | PASS | logs/day4-lab-precheck-tests.xml |
| Docker/PostgreSQL/Timescale/Neo4j | authenticated current service probes | up | all up | PASS | tools/verify_day4.py and logs/day4-verification.json at 20:30 UTC |
| Backend/frontend | API, dashboard and saved UI checks | reachable | reachable on localhost8000 | PASS | prior verifier and live UI |
| Ollama | tags/retained usage | qwen3:4b | AVAILABLE, prior REAL runs retained | PASS | ProviderHealth and Usage |
| Providers | configured transport state | honest absence | cloud UNAVAILABLE | BLOCKED for cloud inference only | provider-readiness report |
| Control Plane/review/journal | runtime and persistence tests | immutable authority, evidence | passed | PASS | full suite |
| Provenance | outbox and lineage checks | no unresolved projection errors | 0 pending/errors | PASS | current verifier |
| Kill switch/budgets | cancellation, stale epoch, limits tests | gates hold | passed, existing reservations retained | PASS | test_day3_integration.py and test_jobs.py |

The fixture market-data path does not require external market or cloud credentials. No critical foundation failure was bypassed.
